"""A knowledge-base question must not be handled as a filesystem search (#6724).

Measured live 2026-09-12 driving archie-tui through the cockpit:

    prompt : "Search the A.R.C.H.I.E. knowledge base for the mistake about a fabricated
              delegated security audit, and summarise in exactly 3 short bullet points..."
    engine : Dispatch: file_operation -> local (Tool intent - handled locally (no LLM))

No unified_tasks row, no agent, nothing in the Live Dispatch feed — the request vanished.
A dropped request is worse than a failed one: a failure is visible.

TWO independent causes, and fixing either alone leaves the bug reachable:

1. Keyword matching was a SUBSTRING test (`kw in text`), so file_operation's "cat" matched
   inside "fabri*cat*ed". That spurious hit took file_operation to 0.60 against
   knowledge_query's 0.50. 13 of the table's keywords misfire this way on ordinary English.
2. Even with that fixed, "Search the knowledge base for X" scores ONLY on file_operation's
   "search" (0.30) while knowledge_query scores 0.00 — no question words at all. The
   knowledge base had to become recognisable as an OBJECT of a lookup verb.
"""

import pytest

from archie_engine.intent import INTENT_PATTERNS, IntentParser, _keyword_regex


@pytest.fixture(scope="module")
def parser():
    return IntentParser()


# ---------------------------------------------------------------------------
# the reported bug, verbatim
# ---------------------------------------------------------------------------

_REPORTED = (
    "Search the A.R.C.H.I.E. knowledge base for the mistake about a fabricated "
    "delegated security audit, and summarise in exactly 3 short bullet points "
    "what went wrong and how to detect it."
)


def test_the_exact_reported_prompt_is_a_knowledge_query(parser):
    assert parser.classify(_REPORTED)["type"] == "knowledge_query"


def test_fabricated_no_longer_triggers_the_cat_keyword(parser):
    """The precise mechanism. 'cat' is a real file_operation keyword and 'fabricated'
    is an ordinary word; nothing about that sentence is a file operation."""
    assert not _keyword_regex("cat").search("a fabricated audit")
    assert not _keyword_regex("cat").search("the category of errors")
    # ...while the actual command still matches
    assert _keyword_regex("cat").search("cat config.py")


# ---------------------------------------------------------------------------
# KB lookups phrased with a file-ish verb
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Search the knowledge base for the deploy provenance rules",
        "Find the documentation about the cold-load queue",
        "look up the mistakes about fleet placement",
        "check the KB for prior art on this",
        "recall past sessions about the dispatcher",
        "search memory for what we decided about OmniRoute",
    ],
)
def test_kb_lookups_route_to_knowledge_query(parser, text):
    """These all start with a verb the file layer wants. The OBJECT is what settles it."""
    assert parser.classify(text)["type"] == "knowledge_query"


# ---------------------------------------------------------------------------
# ...without breaking the file layer, which is the whole risk of this change
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "read config.py",
        "show me app.py",
        "list files in the workspace",
        "grep for get_db_cursor",
        "cat requirements.txt",
        "find the file that defines dispatch",
    ],
)
def test_real_file_operations_still_route_locally(parser, text):
    assert parser.classify(text)["type"] == "file_operation"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("write a python function that reverses a linked list", "code_task"),
        ("fix the bugs in the parser", "code_task"),
        ("git commit the staged changes", "git_operation"),
        ("run the test suite", "shell_command"),
        ("docker compose restart archie_platform", "shell_command"),
    ],
)
def test_other_intents_are_unchanged(parser, text, expected):
    assert parser.classify(text)["type"] == expected


# ---------------------------------------------------------------------------
# the substring class, generally
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "keyword,innocent",
    [
        ("cat", "fabricated"), ("cat", "category"), ("cat", "catalog"),
        ("run", "prune"), ("run", "truncate"),
        ("diff", "difficult"), ("diff", "different"),
        ("log", "technology"), ("log", "logic"),
        ("read", "already"), ("read", "spreadsheet"),
        ("merge", "emerged"), ("merge", "emergency"),
    ],
)
def test_keywords_do_not_fire_inside_unrelated_words(keyword, innocent):
    assert keyword in innocent, "bad fixture: pick a word that CONTAINS the keyword"
    assert not _keyword_regex(keyword).search(innocent)


@pytest.mark.parametrize(
    "keyword,inflected",
    [("bug", "bugs"), ("error", "errors"), ("find", "findings"),
     ("commit", "commits"), ("build", "building")],
)
def test_simple_inflections_still_match(keyword, inflected):
    """A strict `\\bkw\\b` would trade one silent misroute for another: "fix the bugs"
    would stop matching "bug". The optional suffix is deliberate, not sloppy."""
    assert _keyword_regex(keyword).search(f"please {inflected} now")


def test_keyword_regexes_cover_every_declared_keyword():
    """Non-vacuity: the parametrized cases above pass trivially if the matcher is never
    consulted. This pins that EVERY keyword in the table goes through it."""
    from archie_engine.intent import _KEYWORD_RES

    for name, cfg in INTENT_PATTERNS.items():
        assert len(_KEYWORD_RES[name]) == len(cfg["keywords"]), name
        for kw in cfg["keywords"]:
            assert _keyword_regex(kw).search(kw), f"{name}: {kw!r} must match itself"


# ---------------------------------------------------------------------------
# the CALL SITE, not just the helper
# ---------------------------------------------------------------------------
#
# The helper tests above pass a keyword straight to _keyword_regex. That leaves a hole:
# revert classify() to `kw in text_lower` and the helper is still correct, still tested,
# and simply not used — every helper test stays green while the bug is back. Caught by
# mutation-checking this file against a copy; these close it by driving classify().


@pytest.mark.parametrize(
    "text",
    [
        "the fabricated category in our technology stack",
        "summarise the fabricated category of errors",
        "a fabricated catalog entry in the technology log",
        "discuss the fabricated category",
    ],
)
def test_classify_itself_ignores_substring_noise(parser, text):
    """No question words, no file words — the ONLY file_operation signal in each of these
    is 'cat' hiding inside fabricated/category/catalog (and 'log' inside technology).
    Verified: with substring matching restored, every one of these returns
    'file_operation' — i.e. a sentence about nothing filesystem-related gets handled
    locally by the file tool and the user's request disappears."""
    assert parser.classify(text)["type"] != "file_operation"


def test_classify_uses_the_boundary_matcher(parser):
    """Belt and braces on the same hole: prove the compiled matchers are what classify()
    consults, so the helper cannot be quietly orphaned."""
    import archie_engine.intent as intent_mod

    original = intent_mod._KEYWORD_RES["file_operation"]
    intent_mod._KEYWORD_RES["file_operation"] = []  # blind the file layer entirely
    try:
        # 'read config.py' can now only match on patterns, not keywords
        assert parser.classify("cat requirements.txt")["type"] != "file_operation"
    finally:
        intent_mod._KEYWORD_RES["file_operation"] = original
    assert parser.classify("cat requirements.txt")["type"] == "file_operation"
