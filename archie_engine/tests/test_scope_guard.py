"""Tests for PLATFORM_SCOPE (#380 Lane 3): platform-minus-kernel.

A.R.C.H.I.E. is COO and the platform is hers, so her lane is bounded by PROCESS
(owner-approved manifest + PR + F.O.R.G.E. + window-scoped merge — see Tasks 1-4),
not by a narrow path allowlist. This mirrors DEFAULT_ARCHIE_CODE_SCOPE's own
guarantees (traversal/absolute-path refusal, blocked-globs-always-win) against the
wider PLATFORM_SCOPE config. See tests/test_platform_pull_work.py and
tests/test_eval_harness.py for the pull_and_build/eval_harness consumers of this
same config -- both were updated in this change since they encoded the OLD
narrow-scope assumption that ai_bridge/ is out of scope.
"""

from archie_engine.scope_guard import PLATFORM_SCOPE, is_in_scope


def test_she_can_reach_the_platform_she_runs():
    for p in ("platform_v2/services/agent_jobs.py",
              "platform_v2/tools/department_hq/jobs.py",
              "ai_bridge/agent_loop.py",
              "platform_v2/templates/tools/wtf_hub.html"):
        assert is_in_scope(p, PLATFORM_SCOPE), p


def test_the_governance_kernel_stays_blocked():
    """An actor that can rewrite the rules binding it is not governed.
    Safety property -> universal, per decision #953."""
    for p in ("platform_v2/services/agent_service.py",
              "platform_v2/tools/department_hq/services/department_dispatcher.py"):
        assert not is_in_scope(p, PLATFORM_SCOPE), p


def test_secrets_infra_and_ci_stay_blocked():
    for p in (".env", "platform_v2/.env", "secrets/database/password.txt",
              "docker-compose.yml", "Dockerfile", "scripts/dr/failover.sh",
              ".github/workflows/ci.yml"):
        assert not is_in_scope(p, PLATFORM_SCOPE), p


def test_traversal_and_absolute_paths_still_refused():
    for p in ("../etc/passwd", "/etc/passwd", "platform_v2/../../x"):
        assert not is_in_scope(p, PLATFORM_SCOPE), p


def test_excluded_high_risk_modules_still_blocked():
    # media_studio/game_studio/media_hub hold real production data and have no
    # DB isolation yet -- excluded even though they sit under platform_v2/.
    for p in ("platform_v2/tools/media_studio/routes.py",
              "platform_v2/tools/game_studio/routes.py",
              "platform_v2/tools/media_hub/routes.py"):
        assert not is_in_scope(p, PLATFORM_SCOPE), p
