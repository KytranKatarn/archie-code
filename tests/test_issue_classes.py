"""#5933: the mechanical-only gate — an autonomous coder may only attempt
find/replace-shaped findings. FAIL CLOSED: unrecognised codes and prose are
NOT buildable.

Grounding: 2026-08-27 measured 5/5 open issues-lane PRs defective (three
boot/import-breaking), every one from a heuristic security finding. The five
REAL messages from that batch are pinned below as refusal fixtures.
"""

from archie_engine.engine import Engine
from archie_engine.issue_classes import is_mechanical_code, is_mechanical_message

IN_SCOPE = "platform_v2/tools/doc/routes.py"


# ---- classifier: codes (proposals lane) --------------------------------------------------


def test_mechanical_codes_pass():
    for code in ("F401", "F841", "F541", "PYFLAKES", "MISSING_SYMBOL", "F821",
                 "BARE_EXCEPT", "WRONG_SUBMODULE_IMPORT", "WRONG_ROOT_IMPORT"):
        assert is_mechanical_code(code) is True, code
    assert is_mechanical_code("f401") is True  # case-insensitive


def test_non_mechanical_and_unknown_codes_fail_closed():
    for code in ("SQL_INJECTION_RISK", "LARGE_FILE", "HARDCODED_SECRET",
                 "DIRECT_OLLAMA", "TOTALLY_NEW_CODE", "", None):
        assert is_mechanical_code(code) is False, code


# ---- classifier: prose (issues lane — code_issues rows carry no codes) -------------------


def test_mechanical_messages_pass():
    for msg in (
        "'os' imported but unused",
        "`psycopg2` imported but unused (line 15)",
        "local variable 'x' is assigned to but never used",
        "f-string is missing placeholders",
        "undefined name 'foo'",
        "Bare except clause catches all exceptions",
    ):
        assert is_mechanical_message(msg) is True, msg


def test_the_five_real_defective_findings_are_refused():
    """The exact messages behind the 5/5-defective 2026-08-27 batch (#2888/91/92/94/95)."""
    for msg in (
        "Potential hardcoded secret detected",
        "Insecure direct object reference to password in database configuration.",
        "Potential security risk due to hardcoded or weak secret values.",
        "Environment variables for database credentials are being accessed directly.",
    ):
        assert is_mechanical_message(msg) is False, msg


def test_unrecognised_prose_fails_closed():
    for msg in ("Refactor this function for clarity", "Line exceeds 120 characters (124)",
                "Print statement found (use logging instead)", "", None):
        assert is_mechanical_message(msg) is False, msg


# ---- issues lane: the gate binds at selection --------------------------------------------


class _Conn:
    def __init__(self, issues):
        self._i = issues

    async def get_repair_issues(self, status="open", limit=100, auto_fixable=True, path_prefixes=None):
        return {"success": True, "issues": self._i}


class _StubEngine:
    def _finding_is_stale(self, task, file_path):
        return False

    async def _pull_proposal_build(self):
        return None

    def __init__(self, conn):
        self.hub_connector = conn
        self.run_build_calls = []

    async def run_build(self, task, base="main", module=None, target="archie-code", target_file=None):
        self.run_build_calls.append({"task": task, "module": module, "target": target})
        return {"success": True, "stage": "done", "pr_url": "x", "branch": "engine/x"}


async def test_issues_lane_refuses_a_security_finding_even_when_it_is_the_only_candidate():
    stub = _StubEngine(_Conn([
        {"id": 1, "file_path": IN_SCOPE, "severity": "high",
         "message": "Potential hardcoded secret detected"},
    ]))
    r = await Engine.pull_and_build(stub)
    assert r.get("skipped") is True
    assert stub.run_build_calls == []
    assert r.get("non_mechanical_refused") == 1  # visibility: never a silent cap


async def test_issues_lane_prefers_a_mechanical_finding_over_a_higher_severity_refused_one():
    stub = _StubEngine(_Conn([
        {"id": 1, "file_path": IN_SCOPE, "severity": "critical",
         "message": "Potential hardcoded secret detected"},
        {"id": 2, "file_path": IN_SCOPE, "severity": "low",
         "message": "'os' imported but unused"},
    ]))
    r = await Engine.pull_and_build(stub)
    assert r.get("issue_id") == 2
    assert len(stub.run_build_calls) == 1
