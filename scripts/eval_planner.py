#!/usr/bin/env python3
"""Plan-quality A/B eval (#380 Phase 2).

Measures the SINGLE-SHOT plan quality of one or more Ollama models on real in-scope
Repair-Bay issues: does the model emit a parseable, in-scope op-list whose every edit
old_string actually exists in the file? That's exactly the stage the live cycles failed
at (parse + hallucinated old_string), so it's the highest-signal, cheapest metric.

PLAN-ONLY: dispatch → parse → dry-run validate against the REAL /workspace-platform
checkout. It NEVER applies, tests, pushes, or opens a PR — zero side effects. Strictly
local (ADR-003): each candidate runs against cfg.ollama_host with format=json.

Usage (inside the archie_engine container):
  python3 scripts/eval_planner.py --models qwen2.5:7b,qwen2.5-coder:7b --sample 4
"""

from __future__ import annotations

import argparse
import asyncio

from archie_engine.build_loop import BuildLoop
from archie_engine.config import EngineConfig
from archie_engine.eval_harness import score_runs, tasks_from_issues, format_summary
from archie_engine.hub.auth import HubAuth
from archie_engine.hub.connector import HubConnector
from archie_engine.inference import InferenceClient
from archie_engine.scope_guard import PLATFORM_SCOPE
from archie_engine.tools.base import ToolResult
from archie_engine.tools.file_ops import FileOpsTool


class _PlanOnlyTools:
    """Minimal tool registry: real file_ops on the platform workspace (for verbatim
    old_string validation), everything else a no-op success. Plan-only never calls the
    other tools, so this is sufficient and side-effect-free."""

    def __init__(self, workspace: str):
        self._fo = FileOpsTool(workspace=workspace)

    async def execute(self, name, **kw):
        if name == "file_ops":
            return await self._fo.execute(**kw)
        return ToolResult(success=True, output="ok")


# JSON-schema for the op-list — Ollama constrained decoding forces a top-level ARRAY of
# op objects, so the planner can't emit an object/prose that fails the array parser.
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

_FORMATS = {"none": None, "json": "json", "schema": OPS_SCHEMA}


def _local_dispatch(ic: InferenceClient, model: str, fmt=None):
    async def _d(prompt: str) -> str:
        resp = await ic.chat(messages=[{"role": "user", "content": prompt}], model=model, format=fmt)
        msg = resp.get("message", {}) if isinstance(resp, dict) else {}
        return msg.get("content", "") if isinstance(msg, dict) else ""
    return _d


async def eval_model(model: str, tasks: list, cfg: EngineConfig, retries: int, fmt=None) -> dict:
    ic = InferenceClient(cfg.ollama_host, timeout=cfg.build_test_timeout)
    tools = _PlanOnlyTools(cfg.platform_workspace)
    loop = BuildLoop(tools=tools, dispatch_fn=_local_dispatch(ic, model, fmt),
                     scope_config=PLATFORM_SCOPE, plan_max_retries=retries)
    runs = []
    for t in tasks:
        ops, err = await loop._plan_with_retries(t["task"])
        ok = err is None and bool(ops)
        runs.append({"success": False,  # we never apply; "plan passed" == stage past plan
                     "stage": "apply" if ok else "plan",
                     "error": err or "",
                     "task": t["task"][:70],
                     "n_ops": len(ops or [])})
    return {"model": model, "summary": score_runs(runs), "runs": runs}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="qwen2.5:7b,qwen2.5-coder:7b")
    ap.add_argument("--sample", type=int, default=4)
    ap.add_argument("--retries", type=int, default=0, help="0 = raw single-shot model quality")
    ap.add_argument("--format", default="schema", choices=list(_FORMATS),
                    help="none | json (bare valid-JSON) | schema (constrained op-array)")
    args = ap.parse_args()
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    fmt = _FORMATS[args.format]

    cfg = EngineConfig()
    auth = HubAuth(key_file=cfg.data_dir / ".hub_key")
    if cfg.hub_api_key and not auth.has_key():
        auth.store_key(cfg.hub_api_key)
    conn = HubConnector(hub_url=cfg.hub_url, auth=auth, timeout=cfg.hub_timeout)
    resp = await conn.get_repair_issues(status="open", limit=200)
    issues = (resp or {}).get("issues", []) if isinstance(resp, dict) else []
    tasks = tasks_from_issues(issues)[: args.sample]
    print(f"in-scope tasks sampled: {len(tasks)} (of {len(issues)} open issues)")
    if not tasks:
        print("no in-scope tasks — nothing to eval")
        return

    print(f"\n=== PLAN-ONLY A/B (retries={args.retries}, format={args.format}) ===")
    results = []
    for m in models:
        print(f"\n--- {m} ---")
        r = await eval_model(m, tasks, cfg, args.retries, fmt)
        results.append(r)
        print(format_summary(r["summary"]))
        for run in r["runs"]:
            mark = "OK " if run["stage"] == "apply" else "XX "
            print(f"  {mark}[{run['n_ops']} ops] {run['task']}  {('' if run['stage']=='apply' else run['error'][:90])}")

    print("\n=== PLAN-OK% BY MODEL ===")
    for r in results:
        s = r["summary"]
        print(f"  {r['model']:24} plan_ok {s['plan_ok']}/{s['total']} ({s['plan_ok_pct']}%)")


if __name__ == "__main__":
    asyncio.run(main())
