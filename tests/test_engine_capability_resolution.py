"""Every capability the engine emits must RESOLVE on the platform (#6704).

WHY THIS FILE EXISTS
tests/test_dispatch_strategy.py asserted `capability == "code_generation"` and
`== "refactoring"` and was green for months. Both were DEAD REFERENCES: neither
appears in the platform's CAPABILITY_DEPARTMENT_MAP, and neither is held as a skill
by any non-decommissioned agent. Measured live 2026-09-11 — three of the five strings
this engine could emit resolved to nobody:

    capability         mapped?  agents holding the skill
    general            yes      2   (P.O.R.T.A.L.A., P.R.O.B.E.)
    code_review        yes      3   (F.O.R.G.E., N.I.M.B.U.S., P.R.O.B.E.)
    knowledge_search   NO       0   <- dead
    code_generation    NO       0   <- dead
    refactoring        NO       0   <- dead

The old assertions could not catch it, because comparing a string to a literal asks
"is it spelled this way", never "does anything answer to this name". That is the same
defect as the platform's `auto_document` capability (KB #261742) and the 'news'
residency profile that did not exist (KB #300145).

Consequence on the live platform: an unmapped capability falls back to the Engineering
default, and the agent scorer applies a **-1.0 hard penalty** when a capability is
requested and the candidate does not hold it as a skill — so the work lands on whoever
scores least badly instead of on anyone able to do it.

⚠️ THE LIMIT OF THIS TEST, STATED PLAINLY. archie-code cannot import the platform's
CAPABILITY_DEPARTMENT_MAP or query agent_skills — different repo, different container.
So KNOWN_GOOD below is a CURATED SNAPSHOT, not a live check, and it can go stale if
the platform renames or retires a capability. It is still worth having: it converts
"someone invents a new capability string" from a silent months-long misroute into a
failing test that names the exact risk. Re-verify against the live platform with:

    docker exec archie_platform python3 -c "
    import sys; sys.path.insert(0,'/app')
    from services.department_coordinator import CAPABILITY_DEPARTMENT_MAP as M
    from database import get_db_cursor
    with get_db_cursor() as (c,cur):
        cur.execute(\\"SELECT DISTINCT skill_name FROM agent_skills s JOIN agents a \\"
                    \\"ON a.id=s.agent_id WHERE a.shift_state<>'decommissioned'\\")
        skills={r['skill_name'] for r in cur.fetchall()}
    for cap in ('general','research','code','code_review'):
        print(cap, 'mapped=', cap in M, 'agents=', cap in skills)"
"""

import pytest

from archie_engine.dispatch_strategy import (
    EMITTED_CAPABILITIES,
    LLM_INTENTS,
    DispatchStrategy,
)
from archie_engine.intent import IntentParser

# Verified against the live platform 2026-09-11: each is present in
# CAPABILITY_DEPARTMENT_MAP **and** held as a skill by >=1 active agent.
KNOWN_GOOD = {
    "general": 2,
    "research": 8,
    "code": 4,
    "code_review": 3,
}

# Dead references this engine used to emit. Named individually so a revert is a
# failing test with an explanation, not a silent regression.
KNOWN_DEAD = {"code_generation", "refactoring", "knowledge_search"}


def _intent(t, conf=0.9, raw=""):
    return {"type": t, "confidence": conf, "raw_input": raw}


class TestEveryEmittedCapabilityResolves:
    @pytest.mark.parametrize("cap", sorted(EMITTED_CAPABILITIES))
    def test_capability_is_known_to_the_platform(self, cap):
        assert cap in KNOWN_GOOD, (
            f"{cap!r} is not a verified platform capability. Before adding it, check it "
            f"against BOTH CAPABILITY_DEPARTMENT_MAP and agent_skills.skill_name — an "
            f"unmapped/unskilled capability does not error, it silently misroutes."
        )

    @pytest.mark.parametrize("cap", sorted(KNOWN_DEAD))
    def test_the_dead_references_never_come_back(self, cap):
        assert cap not in EMITTED_CAPABILITIES
        assert cap not in set(LLM_INTENTS.values())

    def test_llm_intents_values_are_a_subset_of_the_declared_set(self):
        """EMITTED_CAPABILITIES is what the test checks; LLM_INTENTS is what the code
        uses. If they drift, the test starts guarding a list nothing emits."""
        assert set(LLM_INTENTS.values()) <= EMITTED_CAPABILITIES

    def test_every_resolve_branch_is_declared(self):
        """_resolve_capability has branches LLM_INTENTS alone does not reveal. Drive
        them and confirm each output is declared — otherwise a branch can emit a dead
        reference that the subset check above would never see."""
        s = DispatchStrategy(hub_available=True)
        probes = [
            "review this diff",       # -> code_review
            "audit the parser",       # -> code_review
            "refactor the module",    # -> code
            "simplify this",          # -> code
            "write a function",       # -> code (base)
        ]
        for raw in probes:
            cap = s.decide(_intent("code_task", raw=raw)).capability
            assert cap in EMITTED_CAPABILITIES, f"{raw!r} emitted undeclared {cap!r}"


class TestOrdinaryCodingRequestsReachACoder:
    """The classifier half. A capability that resolves is useless if plain coding
    requests never classify as code_task in the first place."""

    # The measured live failure. Task #6703 recorded it as
    # "general: write a python function that reverses a linked list".
    REGRESSION = "write a python function that reverses a linked list"

    @pytest.mark.parametrize(
        "text",
        [
            REGRESSION,
            "add a method to the parser class",
            "generate a bash script to rotate logs",
            "write me a unit test for the auth flow",
            "create a function to parse the config",
            "fix the login bug",
            "implement retry logic",
        ],
    )
    def test_a_coding_request_classifies_as_code_task(self, text):
        assert IntentParser().classify(text)["type"] == "code_task", (
            f"{text!r} did not reach a coder — it falls through to `conversation`, "
            f"which dispatches the `general` capability."
        )

    @pytest.mark.parametrize(
        "text,expect",
        [
            # Questions ABOUT code are knowledge, not code work. knowledge_query also
            # outranks code_task on priority (10 > 6), which is what keeps these apart.
            ("what is the function of the spleen", "knowledge_query"),
            ("explain how does the dispatcher work", "knowledge_query"),
            ("how do i read this file", "knowledge_query"),
            # Plain chat must stay chat.
            ("hello, how are you today", "conversation"),
            ("thanks, that worked", "conversation"),
        ],
    )
    def test_non_coding_input_is_not_swallowed(self, text, expect):
        """The widened patterns must not turn every sentence into code work."""
        assert IntentParser().classify(text)["type"] == expect

    def test_the_regression_case_reaches_a_real_coder_capability(self):
        """End to end through both halves: classify, then resolve."""
        parser, strategy = IntentParser(), DispatchStrategy(hub_available=True)
        decision = strategy.decide(parser.classify(self.REGRESSION))
        assert decision.capability == "code"
        assert decision.capability in KNOWN_GOOD
