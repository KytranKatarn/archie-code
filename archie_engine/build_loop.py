"""Autonomous coordinate→build→test→deploy loop for the A.R.C.H.I.E. Engine (#4256).

This is the capstone that strings the engine's tools together into one bounded,
PR-gated build cycle (ADR-003):

  coordinate  — dispatch the task to DHQ (strictly local) for a structured plan
  build       — apply each file op via file_ops, deny-by-default scope-guarded
  test        — run the test command via shell_ops
  deploy      — ONLY on green: git add (scoped) → commit → push (refuses main)
                → github_ops.pr_create → telemetry → STOP.

Hard invariants (enforced here + by the tools):
  * NEVER merges — there is no merge call anywhere in this loop; it ends at PR.
  * NEVER deploys a red build — no push/PR unless tests pass.
  * Every applied path is re-checked with is_in_scope (defense in depth on top of
    file_ops' own guard) and the change set is capped at ``max_files``.
  * One run at a time (the caller serialises; see ADR-003 "1 concurrent").

The LLM dispatch + the tools are injected so the loop is fully unit-testable
without a live hub or filesystem.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass, field

from archie_engine.scope_guard import is_in_scope

# A conservative default; tunable via EngineConfig later. ADR-003: "~25 files".
DEFAULT_MAX_FILES = 25
DEFAULT_TEST_COMMAND = "python -m pytest -q"
DEFAULT_TEST_TIMEOUT = 600
DEFAULT_PLAN_FILE_BUDGET = 16000  # max chars of target-file content injected into the plan prompt

# Ollama structured-output schema for the plan: constrains the model to emit a top-level
# ARRAY of op objects so the op-list always parses (#380 Phase 2 — bare format="json"
# forced object-shaped JSON that the array parser rejected; a schema fixed parse 0%→100%).
OPS_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "action": {"type": "string", "enum": ["write", "edit"]},
            "content": {"type": "string"},
            "old_string": {"type": "string"},
            "new_string": {"type": "string"},
        },
        "required": ["path", "action"],
    },
}


@dataclass
class BuildResult:
    task: str
    branch: str
    success: bool = False
    stage: str = "init"          # last stage reached (branch/plan/apply/test/stage/commit/push/pr/done)
    error: str = ""
    files: list = field(default_factory=list)
    tests_passed: bool = False
    pr_url: str | None = None
    pr_number: int | None = None
    duration_ms: int = 0
    test_output: str = ""              # captured test command output (for build-result reporting)
    module: str | None = None         # target platform Code-Health module, if any (drives reverify)
    reverify: dict | None = None      # loop-closer verdict {modules,fixed,still_open,details}

    def fail(self, stage: str, error: str) -> "BuildResult":
        self.stage = stage
        self.error = error or ""
        self.success = False
        return self


class BuildLoop:
    def __init__(self, tools, dispatch_fn, connector=None, scope_config=None,
                 max_files: int = DEFAULT_MAX_FILES,
                 test_command: str = DEFAULT_TEST_COMMAND,
                 test_timeout: int = DEFAULT_TEST_TIMEOUT,
                 capability: str = "code",  # informational; engine closure sets live dispatch capability
                 model: str = "archie:7b",
                 plan_max_retries: int = 2,
                 plan_file_budget: int = DEFAULT_PLAN_FILE_BUDGET):
        """
        tools       — a ToolRegistry exposing file_ops / git_ops / github_ops / shell_ops.
        dispatch_fn — async callable(prompt:str) -> str: the coordinate step. In the
                      engine this routes through DHQ (strictly local, #4252).
        connector   — optional hub connector for telemetry (log_job). None = skip.
        scope_config— None → DEFAULT_ARCHIE_CODE_SCOPE in scope_guard.
        """
        self.tools = tools
        self.dispatch_fn = dispatch_fn
        self.connector = connector
        self.scope_config = scope_config
        self.max_files = max_files
        self.test_command = test_command
        self.test_timeout = test_timeout
        self.capability = capability
        self.model = model
        self.plan_max_retries = plan_max_retries
        self.plan_file_budget = plan_file_budget

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def run(self, task: str, base: str = "main", branch: str | None = None,
                  module: str | None = None, target_file: str | None = None) -> BuildResult:
        start = time.monotonic()
        branch = branch or _branch_name(task)
        result = BuildResult(task=task, branch=branch)
        result.module = module  # target platform Code-Health module → drives the loop-closer reverify

        if base in {"", None}:
            base = "main"

        # 1. branch (off the current HEAD)
        br = await self.tools.execute("git_ops", operation="branch", action="create", name=branch)
        if not br.success:
            return self._done(result.fail("branch", br.error), start)

        # 2. coordinate — plan the change set via DHQ, then DRY-RUN validate the whole
        # op-list and re-prompt the model with the exact error on a parse OR validation
        # failure (model-independent reliability; #380 Phase 1). Nothing is written until
        # every op is in-scope and every edit's old_string is confirmed present.
        ops, plan_err = await self._plan_with_retries(task, target_file=target_file)
        if plan_err:
            return self._done(result.fail("plan", plan_err), start)

        # 3. build — apply each op, deny-by-default scope-guarded
        applied: list[str] = []
        for op in ops:
            path = (op or {}).get("path")
            action = (op or {}).get("action")
            if not path or not is_in_scope(path, self.scope_config):
                return self._done(result.fail("apply", f"out-of-scope or missing path: {path!r}"), start)
            if action == "write":
                ar = await self.tools.execute("file_ops", operation="write", path=path,
                                              content=op.get("content", ""))
            elif action == "edit":
                ar = await self.tools.execute("file_ops", operation="edit", path=path,
                                              old_string=op.get("old_string", ""),
                                              new_string=op.get("new_string", ""))
            else:
                return self._done(result.fail("apply", f"unknown action {action!r} for {path}"), start)
            if not ar.success:
                return self._done(result.fail("apply", f"{path}: {ar.error}"), start)
            applied.append(path)
        result.files = applied

        # 4. test — deploy ONLY on green
        tr = await self.tools.execute("shell_ops", command=self.test_command, timeout=self.test_timeout)
        result.tests_passed = bool(tr.success)
        result.test_output = ((getattr(tr, "output", "") or getattr(tr, "error", "") or "")[:4000])
        if not tr.success:
            return self._done(result.fail("test", (tr.error or tr.output or "tests failed")[:500]), start)

        # 5. deploy = open a PR (NEVER merge)
        ga = await self.tools.execute("git_ops", operation="add", paths=applied)
        if not ga.success:
            return self._done(result.fail("stage", ga.error), start)
        gc = await self.tools.execute("git_ops", operation="commit", message=_commit_message(task))
        if not gc.success:
            return self._done(result.fail("commit", gc.error), start)
        gp = await self.tools.execute("git_ops", operation="push")  # refuses protected branches by construction
        if not gp.success:
            return self._done(result.fail("push", gp.error), start)
        pr = await self.tools.execute("github_ops", operation="pr_create",
                                      title=_pr_title(task),
                                      body=_pr_body(task, applied),
                                      head=branch, base=base)
        if not pr.success:
            return self._done(result.fail("pr", pr.error), start)
        meta = pr.metadata or {}
        result.pr_url = meta.get("url")
        result.pr_number = meta.get("number")
        result.success = True
        result.stage = "done"
        return self._done(result, start)

    # ------------------------------------------------------------------
    # Coordinate (LLM plan) — injected dispatch, robust parse
    # ------------------------------------------------------------------

    async def _plan(self, task: str, feedback: str | None = None,
                    file_content: str | None = None, file_path: str | None = None) -> tuple[list, str | None]:
        # Tell the planner the TARGET's allowed paths so it writes under the right
        # prefix (archie-code -> archie_engine/...; platform -> platform_v2/tools/...).
        from archie_engine.scope_guard import DEFAULT_ARCHIE_CODE_SCOPE

        allowed = (self.scope_config or DEFAULT_ARCHIE_CODE_SCOPE).get("allowed_paths", [])
        prompt = _plan_prompt(task, allowed, file_path=file_path, file_content=file_content)
        if feedback:
            # Re-prompt with the exact reason the last attempt was rejected (#380 Phase 1).
            prompt = (f"{prompt}\n\nYOUR PREVIOUS ATTEMPT WAS REJECTED:\n{feedback}\n"
                      "Return a CORRECTED JSON array ONLY — no prose, no code fences.")
        try:
            raw = await self.dispatch_fn(prompt)
        except Exception as exc:  # dispatch failure is a graceful plan failure
            return [], f"dispatch failed: {exc}"
        ops = _parse_ops(raw or "")
        if ops is None:
            return [], "could not parse a JSON op list from the plan"
        return ops, None

    async def _plan_with_retries(self, task: str, target_file: str | None = None) -> tuple[list, str | None]:
        """Plan → DRY-RUN validate the whole op-list before any file is touched. On a
        parse failure or a validation failure, re-prompt the model with the exact error
        (up to plan_max_retries). Corrects the two dominant small-model failure modes —
        unparseable JSON and a hallucinated edit old_string — WITHOUT changing the model
        (#380 Phase 1). A dispatch (infra) failure and the file-cap are not retried.

        #380 Phase 2b: inject the TARGET FILE's CURRENT content into the plan prompt
        (resolved from target_file, else parsed from the task's 'File: <path>') so the
        model copies the exact old_string instead of guessing it — the dominant cause of
        the 'old_string not found' failure. Read ONCE, reused across retries."""
        file_path = target_file or _target_file_from_task(task)
        file_content = None
        if file_path and is_in_scope(file_path, self.scope_config):
            file_content = await self._read_target(file_path, task)
        feedback = None
        last_err = "no plan produced"
        attempts = 1 + max(0, self.plan_max_retries)
        for _attempt in range(attempts):
            ops, perr = await self._plan(task, feedback, file_content, file_path)
            if perr:
                if perr.startswith("dispatch failed"):
                    return [], perr  # infra failure — retrying the same call won't help
                last_err = perr
                feedback = ("Your output was not a valid JSON array. Return ONLY a JSON "
                            "array of file ops — no prose, no code fences.")
                continue
            if not ops:
                last_err = "no file operations produced"
                feedback = "Your plan had no file operations. Produce the ops needed to do the task."
                continue
            if len(ops) > self.max_files:
                # Hard cap — not a model mistake to coach; fail fast.
                return [], f"change set too large: {len(ops)} > {self.max_files} files"
            verrs = await self._validate_ops(ops)
            if verrs:
                last_err = "; ".join(verrs[:5])
                feedback = ("Your plan had these problems — fix EACH and return a corrected "
                            "JSON array:\n" + "\n".join(f"- {e}" for e in verrs[:10]))
                continue
            return ops, None
        return [], f"plan failed validation after {attempts} attempts: {last_err}"

    async def _validate_ops(self, ops: list) -> list:
        """Dry-run: confirm every op is applicable BEFORE mutating the workspace.
        Returns a list of human-readable problems (empty = all good). For an 'edit',
        reads the target file RAW and checks old_string exists verbatim — exactly the
        condition file_ops._edit enforces, surfaced early so it can be re-prompted."""
        errors: list = []
        for idx, op in enumerate(ops):
            op = op or {}
            path = op.get("path")
            action = op.get("action")
            if not path or not is_in_scope(path, self.scope_config):
                errors.append(f"op {idx}: out-of-scope or missing path: {path!r}")
                continue
            if action == "write":
                continue
            if action == "edit":
                old = op.get("old_string", "")
                if not old:
                    errors.append(f"op {idx} ({path}): edit has an empty old_string")
                    continue
                rd = await self.tools.execute("file_ops", operation="read", path=path, numbered=False)
                if not rd.success:
                    errors.append(f"op {idx}: cannot read {path} to edit: {rd.error}")
                elif old not in (getattr(rd, "output", "") or ""):
                    errors.append(f"op {idx} ({path}): old_string not found verbatim: {old[:80]!r}")
            else:
                errors.append(f"op {idx} ({path}): unknown action {action!r}")
        return errors

    async def _read_target(self, path: str, task: str) -> str | None:
        """Read the target file RAW for prompt injection. Full content if within budget;
        otherwise a window around the flagged 'line N' (so the edit region is present),
        falling back to a head slice. Returns None if the file can't be read."""
        rd = await self.tools.execute("file_ops", operation="read", path=path, numbered=False)
        if not rd.success:
            return None
        content = getattr(rd, "output", "") or ""
        if len(content) <= self.plan_file_budget:
            return content
        line = _extract_line(task)
        lines = content.splitlines()
        if line and 1 <= line <= len(lines):
            lo, hi = max(0, line - 80), min(len(lines), line + 80)
            return "\n".join(lines[lo:hi]) + f"\n... (showing lines {lo + 1}-{hi} of {len(lines)})"
        return content[: self.plan_file_budget] + "\n... (truncated)"

    # ------------------------------------------------------------------
    # Telemetry + finalisation
    # ------------------------------------------------------------------

    def _done(self, result: BuildResult, start: float) -> BuildResult:
        result.duration_ms = int((time.monotonic() - start) * 1000)
        return result

    async def emit_telemetry(self, result: BuildResult) -> None:
        """Best-effort post-run reporting. Each step is isolated — telemetry must
        NEVER break a build, and one reporter failing must not skip the others.

        1. task_execution_log (#4257) via log_job.
        2. qa_test_runs/qa_test_results (#4261) via report_build_result — for EVERY
           outcome, so a red build is visible on the Test Bay / QA tabs too.
        3. Loop-closer (#4262) via code_health_reverify — ONLY when a platform
           Code-Health module is the target AND the change deployed (PR opened):
           re-audit and confirm the finding actually landed (fixed / still_open).
        """
        if not self.connector:
            return
        try:
            await self.connector.log_job(
                task=result.task,
                agent_name="A.R.C.H.I.E. Engine",
                result_summary=(result.error or result.pr_url or result.stage)[:200],
                duration_ms=result.duration_ms,
                success=result.success,
                model=self.model,
                files_changed=result.files,
                branch=result.branch,
            )
        except Exception:
            pass
        try:
            await self.connector.report_build_result(
                task=result.task,
                branch=result.branch,
                pr_url=result.pr_url,
                pr_number=result.pr_number,
                files_changed=result.files,
                status=("completed" if result.success else "failed"),
                duration_ms=result.duration_ms,
                output=result.test_output,
                tests=[{
                    "name": self.test_command,
                    "status": "pass" if result.tests_passed else "fail",
                    "output": result.test_output,
                    "duration_ms": result.duration_ms,
                }],
            )
        except Exception:
            pass
        if result.success and result.module:
            try:
                result.reverify = await self.connector.code_health_reverify(result.module)
            except Exception:
                pass


# ----------------------------------------------------------------------
# Pure helpers (module-level so they're trivially testable)
# ----------------------------------------------------------------------

def _branch_name(task: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (task or "").lower()).strip("-")[:40] or "task"
    # Short unique suffix so a RETRY of the same task never collides with a stale
    # local branch in the persistent /workspace (the autonomous loop hits this; #4322).
    return f"engine/{slug}-{uuid.uuid4().hex[:6]}"


def _commit_message(task: str) -> str:
    return f"feat(engine-build): {task[:72]}\n\nAutonomous build by the A.R.C.H.I.E. Engine (#4256).\n\nCo-Authored-By: A.R.C.H.I.E. Engine <engine@kytranempowerment.com>"


def _pr_title(task: str) -> str:
    return f"[engine] {task[:80]}"


def _pr_body(task: str, files: list) -> str:
    flist = "\n".join(f"- `{f}`" for f in files) or "- (none)"
    return (
        f"Autonomous build by the **A.R.C.H.I.E. Engine** (#4256).\n\n"
        f"**Task:** {task}\n\n**Files changed:**\n{flist}\n\n"
        f"Tests passed locally before this PR was opened. Awaiting F.O.R.G.E. review — "
        f"the engine never merges."
    )


def _plan_prompt(task: str, allowed_paths=None, file_path=None, file_content=None) -> str:
    paths = ", ".join(allowed_paths or ["archie_engine/", "tests/", "docs/"])
    file_block = ""
    if file_path and file_content is not None:
        # #380 Phase 2b: show the model the file it must edit so its old_string is the
        # ACTUAL text, not a guess (the dominant 'old_string not found' cause).
        file_block = (
            f"\nThe file to change is `{file_path}`. Its CURRENT contents are between the markers "
            "below — for an 'edit', old_string MUST be copied EXACTLY (verbatim, including whitespace) "
            "from these contents; do NOT invent or paraphrase it.\n"
            f"<<<FILE {file_path}>>>\n{file_content}\n<<<END FILE>>>\n"
        )
    return (
        "You are the A.R.C.H.I.E. build engine. Produce ONLY the file changes needed for the task.\n"
        "Return a STRICT JSON array of file operations and NOTHING else. Each item is one of:\n"
        '  {"path": "<repo-relative path>", "action": "write", "content": "<full new file contents>"}\n'
        '  {"path": "<repo-relative path>", "action": "edit", "old_string": "<exact text>", "new_string": "<replacement>"}\n'
        f"Only touch files under: {paths}. Never secrets/infra/CI.\n"
        "Paths are REPO-RELATIVE and MUST begin with one of those exact prefixes (do not add any other "
        "prefix). For an 'edit', old_string MUST be text that ALREADY EXISTS verbatim in the file; if you "
        "are not certain it exists, use 'write' with the full new contents instead.\n"
        f"{file_block}"
        f"\nTASK: {task}\n\nJSON:"
    )


def _extract_line(task: str):
    """Parse a 'line N' hint out of the task text, if present (for windowing big files)."""
    m = re.search(r"line\s+(\d+)", task or "")
    return int(m.group(1)) if m else None


def _target_file_from_task(task: str):
    """Parse the 'File: <path>' the task references, so the planner can be shown that
    file's content without the caller threading it explicitly."""
    m = re.search(r"File:\s*([^\s()]+)", task or "")
    return m.group(1) if m else None


def _parse_ops(text: str):
    """Extract a JSON array of ops from an LLM response. Returns list or None.

    Tolerant of ```json fences and surrounding prose: takes the first balanced
    top-level [...] array.
    """
    if not text:
        return None
    # strip code fences
    fenced = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else None
    if candidate is None:
        # first top-level [ ... ] span
        start = text.find("[")
        end = text.rfind("]")
        if start == -1 or end == -1 or end <= start:
            return None
        candidate = text[start:end + 1]
    try:
        data = json.loads(candidate)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, list):
        return None
    # keep only dict ops
    return [op for op in data if isinstance(op, dict)]
