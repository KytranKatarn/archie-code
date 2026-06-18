"""Planner-quality eval harness (#380 Phase 0).

Runs a set of build tasks through a build function (the engine's ``run_build``, or a
stub) and tallies HOW FAR each got, so a (model, config) change can be judged by
numbers — plan-ok% → apply-ok% → test-green% → PR-opened% — instead of vibes. This is
what makes adopting a new model a data-driven swap (re-run, compare, flip config).

Design: a PURE scorer (``score_runs`` over plain result dicts) + an injectable async
runner (``run_eval`` takes an async ``build_fn``), so the whole thing is unit-testable
with no live hub / Ollama / GitHub. ``tasks_from_issues`` maps Repair-Bay issues to eval
tasks using the SAME helpers the autonomous loop uses, so the eval mirrors production.
"""

from __future__ import annotations

# Ordered build stages (mirrors BuildResult.stage). A build that fails at stage S
# reached every stage BEFORE S; success ("done") reached them all.
STAGES = ["init", "branch", "plan", "apply", "test", "stage", "commit", "push", "pr", "done"]
_RANK = {s: i for i, s in enumerate(STAGES)}

# The stages worth reporting as cumulative pass-rates (the funnel the planner drives).
_FUNNEL = ["plan", "apply", "test", "pr"]


def _passed(result: dict, stage: str) -> bool:
    """True if the build got strictly PAST ``stage`` (success ⇒ passed everything)."""
    if result.get("success"):
        return True
    return _RANK.get(result.get("stage", ""), -1) > _RANK.get(stage, 0)


def score_runs(results: list) -> dict:
    """Tally a list of build-result dicts (each has 'success', 'stage', ...).

    Returns counts + percentages for the plan→apply→test→PR funnel plus a histogram of
    where builds die (failed_stage_counts). 'pr_opened' == success (the loop only sets
    success after pr_create)."""
    total = len(results)
    out: dict = {"total": total}
    funnel = {f"{stage}_ok": sum(1 for r in results if _passed(r, stage)) for stage in _FUNNEL}
    funnel["pr_opened"] = sum(1 for r in results if (r or {}).get("success"))
    out.update(funnel)
    # percentages (guard div-by-zero)
    for k, v in list(funnel.items()):
        out[f"{k}_pct"] = round(100.0 * v / total, 1) if total else 0.0
    # where do failures land?
    hist: dict = {}
    for r in results:
        if not (r or {}).get("success"):
            hist[(r or {}).get("stage", "unknown")] = hist.get((r or {}).get("stage", "unknown"), 0) + 1
    out["failed_stage_counts"] = hist
    return out


async def run_eval(tasks: list, build_fn) -> dict:
    """Run each task through ``build_fn`` (async (task, module=, target=) -> result dict)
    and score the lot. A build_fn exception is captured as a failed run (stage 'error')
    so one bad task can't abort the eval. Returns {summary, runs}."""
    runs: list = []
    for t in tasks:
        t = t or {}
        task = t.get("task", "")
        try:
            res = await build_fn(task, module=t.get("module"), target=t.get("target", "archie-code"))
        except Exception as exc:  # never let one task abort the sweep
            res = {"success": False, "stage": "error", "error": str(exc), "task": task}
        res = dict(res or {})
        res.setdefault("task", task)
        runs.append(res)
    return {"summary": score_runs(runs), "runs": runs}


def tasks_from_issues(issues: list, target: str = "archie-platform") -> list:
    """Map Repair-Bay issues (open, with a file_path) to eval tasks, keeping only those
    IN PLATFORM_SCOPE — exactly the set the autonomous loop would build. Uses the same
    _format_issue_task / _module_from_path the engine uses so the eval mirrors prod."""
    from archie_engine.engine import _format_issue_task, _module_from_path
    from archie_engine.scope_guard import PLATFORM_SCOPE, is_in_scope

    tasks: list = []
    for i in issues or []:
        fp = (i or {}).get("file_path")
        if not fp or not is_in_scope(fp, PLATFORM_SCOPE):
            continue
        tasks.append({
            "task": _format_issue_task(i, fp),
            "module": _module_from_path(fp),
            "target": target,
        })
    return tasks


def format_summary(summary: dict) -> str:
    """One-line-per-metric human summary for logs/CLI."""
    s = summary or {}
    lines = [f"total={s.get('total', 0)}"]
    for stage in _FUNNEL:
        lines.append(f"{stage}_ok={s.get(stage + '_ok', 0)} ({s.get(stage + '_ok_pct', 0)}%)")
    lines.append(f"pr_opened={s.get('pr_opened', 0)} ({s.get('pr_opened_pct', 0)}%)")
    if s.get("failed_stage_counts"):
        lines.append("fails=" + ", ".join(f"{k}:{v}" for k, v in s["failed_stage_counts"].items()))
    return " | ".join(lines)
