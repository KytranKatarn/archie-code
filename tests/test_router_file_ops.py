"""The router ↔ FileOpsTool keyword contract, pinned.

Measured 2026-09-11 from archie-tui: "list files in the workspace" made the
engine answer ``Unacceptable pattern: ''`` in 0.1s. Two defects stacked:

* ``_handle_file_operation`` passed ``path=`` for EVERY operation, while
  ``FileOpsTool.execute`` takes ``pattern=`` for glob and grep — so those two
  always received an empty pattern and were refused.
* ``_extract_path`` fell back to ``text.strip()`` — the whole sentence — when
  nothing path-like was present, so the refusal arrived with the request text
  as a "path". No phrasing of "list files" could ever have succeeded.

These tests call the handler directly with a recording registry, so they pin
the exact keywords the tool receives — the thing that was wrong.
"""

import asyncio
from types import SimpleNamespace

from archie_engine.router import CommandRouter, _extract_grep_pattern, _extract_path


class RecordingRegistry:
    """Stands in for ToolRegistry: records every execute() call, answers success."""

    def __init__(self):
        self.calls = []

    async def execute(self, name, **kwargs):
        self.calls.append((name, kwargs))
        return SimpleNamespace(success=True, output="ok", error=None)


def _handle(text, entities=None):
    reg = RecordingRegistry()
    router = CommandRouter(reg, None)  # (tools, inference) — no model on this path
    result = asyncio.run(router._handle_file_operation(text, entities or {}, {}))
    return result, reg.calls


# --- the two helpers ---------------------------------------------------------

def test_extract_path_returns_empty_when_nothing_pathlike():
    # Was: the whole sentence. The caller decides what "no path" means.
    assert _extract_path("list files in the workspace") == ""
    assert _extract_path("read archie_engine/router.py please") == "archie_engine/router.py"


def test_extract_grep_pattern_prefers_a_quoted_term():
    assert _extract_grep_pattern('search for "needle in a haystack" in src/') == "needle in a haystack"
    assert _extract_grep_pattern("grep TODO in the tests") == "TODO"
    assert _extract_grep_pattern("search for retry_after") == "retry_after"


def test_extract_grep_pattern_is_empty_when_only_a_place_is_named():
    assert _extract_grep_pattern("search the workspace") == ""
    assert _extract_grep_pattern("search in src/") == ""


# --- glob --------------------------------------------------------------------

def test_list_files_calls_glob_with_a_pattern_not_a_path():
    result, calls = _handle("list files in the workspace")
    assert result["success"] is True
    assert calls == [("file_ops", {"operation": "glob", "pattern": "*"})]


def test_find_a_named_file_searches_the_tree_for_it():
    _, calls = _handle("find router.py")
    assert calls == [("file_ops", {"operation": "glob", "pattern": "**/router.py"})]


def test_a_wildcard_from_the_classifier_passes_through_untouched():
    _, calls = _handle("list the python files", {"files": ["src/*.py"]})
    assert calls == [("file_ops", {"operation": "glob", "pattern": "src/*.py"})]


# --- grep --------------------------------------------------------------------

def test_grep_sends_the_term_as_pattern_and_the_file_as_path():
    _, calls = _handle('search for "needle" in src/utils.py')
    assert calls == [("file_ops", {"operation": "grep", "pattern": "needle", "path": "src/utils.py"})]


def test_grep_without_a_term_refuses_in_plain_words_and_calls_nothing():
    result, calls = _handle("search the workspace")
    assert result["success"] is False
    assert "needs a search term" in result["response"]
    assert calls == []


# --- read / write ------------------------------------------------------------

def test_read_passes_the_path_keyword():
    _, calls = _handle("read archie_engine/router.py")
    assert calls == [("file_ops", {"operation": "read", "path": "archie_engine/router.py"})]


def test_read_without_a_path_refuses_instead_of_reading_the_root():
    result, calls = _handle("read the file")
    assert result["success"] is False
    assert "needs a file path" in result["response"]
    assert calls == []
