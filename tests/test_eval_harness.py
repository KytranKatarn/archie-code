"""Tests for the planner-quality eval harness (#380 Phase 0).

Pure scorer + injectable async runner — no live hub/Ollama/GitHub."""

from archie_engine.eval_harness import (
    _passed, score_runs, run_eval, tasks_from_issues, format_summary,
)


# --- _passed semantics ------------------------------------------------------

def test_passed_semantics():
    assert _passed({"success": True, "stage": "done"}, "pr")        # success passes everything
    assert _passed({"success": True}, "plan")
    # failed AT plan → did NOT pass plan, but DID pass nothing before it
    assert not _passed({"success": False, "stage": "plan"}, "plan")
    # failed at apply → passed plan, not apply
    assert _passed({"success": False, "stage": "apply"}, "plan")
    assert not _passed({"success": False, "stage": "apply"}, "apply")
    # failed at test → passed plan + apply
    assert _passed({"success": False, "stage": "test"}, "apply")
    assert not _passed({"success": False, "stage": "test"}, "test")


# --- score_runs -------------------------------------------------------------

def test_score_runs_funnel_and_histogram():
    runs = [
        {"success": True, "stage": "done"},                 # full PR
        {"success": False, "stage": "plan"},                # died at plan
        {"success": False, "stage": "apply"},               # died at apply (passed plan)
        {"success": False, "stage": "test"},                # died at test (passed plan+apply)
    ]
    s = score_runs(runs)
    assert s["total"] == 4
    assert s["plan_ok"] == 3 and s["plan_ok_pct"] == 75.0      # all but the plan failure
    assert s["apply_ok"] == 2                                   # done + test failure
    assert s["test_ok"] == 1                                    # only the full-PR run
    assert s["pr_opened"] == 1 and s["pr_opened_pct"] == 25.0
    assert s["failed_stage_counts"] == {"plan": 1, "apply": 1, "test": 1}


def test_score_runs_empty():
    s = score_runs([])
    assert s["total"] == 0 and s["pr_opened_pct"] == 0.0 and s["failed_stage_counts"] == {}


# --- run_eval ---------------------------------------------------------------

async def test_run_eval_collects_scores_and_isolates_exceptions():
    async def build_fn(task, module=None, target="archie-code"):
        if "boom" in task:
            raise RuntimeError("planner died")
        if "win" in task:
            return {"success": True, "stage": "done", "pr_url": "u"}
        return {"success": False, "stage": "apply", "error": "bad edit"}

    tasks = [{"task": "win one"}, {"task": "boom two"}, {"task": "meh three"}]
    out = await run_eval(tasks, build_fn)
    assert out["summary"]["total"] == 3
    assert out["summary"]["pr_opened"] == 1
    # the exception became a captured failed run at stage 'error' (sweep not aborted)
    stages = sorted(r["stage"] for r in out["runs"])
    assert stages == ["apply", "done", "error"]
    assert any(r.get("error") == "planner died" for r in out["runs"])


# --- tasks_from_issues ------------------------------------------------------

def test_tasks_from_issues_keeps_only_in_scope():
    issues = [
        {"id": 1, "file_path": "platform_v2/tools/doc/routes.py", "message": "m", "severity": "high"},
        {"id": 2, "file_path": "ai_bridge/agent_loop.py", "message": "core", "severity": "high"},
        {"id": 3, "file_path": "platform_v2/tools/media_studio/x.py", "message": "excluded", "severity": "low"},
        {"id": 4, "file_path": None, "message": "no path"},
    ]
    tasks = tasks_from_issues(issues)
    assert len(tasks) == 1
    t = tasks[0]
    assert t["target"] == "archie-platform"
    assert t["module"] == "doc"
    assert "platform_v2/tools/doc/routes.py" in t["task"]


def test_format_summary_is_one_line():
    s = score_runs([{"success": True, "stage": "done"}, {"success": False, "stage": "plan"}])
    line = format_summary(s)
    assert "total=2" in line and "pr_opened=1" in line and "plan:1" in line
