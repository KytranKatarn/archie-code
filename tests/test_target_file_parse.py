"""`File: <path>` parsing — a silent miss disables file-content injection (#380 Phase 2b).

The planner is shown the target file's CURRENT content so it copies `old_string`
verbatim instead of guessing. When the path parses wrong the file simply is not read,
the prompt omits it, and the model guesses — surfacing as "the model hallucinated
old_string" when the real cause is this parse.

Measured 2026-08-26 on a live engine build: a task phrased the natural way,
"File: archie_engine/hub/connector.py. The method dhq_complete...", yielded a path
with a TRAILING PERIOD, which does not exist.
"""

from __future__ import annotations

import pytest

from archie_engine.build_loop import _target_file_from_task

REAL = "archie_engine/hub/connector.py"


class TestTheLiveFailure:
    def test_sentence_period_is_not_part_of_the_path(self):
        t = f"File: {REAL}. The method dhq_complete currently returns an empty string."
        assert _target_file_from_task(t) == REAL

    def test_comma_mid_sentence(self):
        assert _target_file_from_task(f"Fix File: {REAL}, near the top.") == REAL

    @pytest.mark.parametrize("trailer", [".", ",", ";", ":", "!", "?", ")", "]", "}", '"', "'", "`", ">"])
    def test_each_trailing_punctuation_mark(self, trailer):
        assert _target_file_from_task(f"File: {REAL}{trailer} rest of sentence") == REAL

    def test_multiple_trailing_marks(self):
        assert _target_file_from_task(f'File: {REAL}"). Next.') == REAL


class TestNegativeControls:
    """⚠️ The strip must not eat anything that belongs to the path."""

    def test_a_bare_path_is_unchanged(self):
        assert _target_file_from_task(f"File: {REAL}") == REAL

    def test_interior_dots_survive(self):
        """The `.py` dot is INTERIOR, never trailing — a naive strip would break this."""
        assert _target_file_from_task("File: a.b.c/d.e.py after") == "a.b.c/d.e.py"

    def test_a_dotfile_is_not_eaten(self):
        assert _target_file_from_task("File: docs/.keep and more") == "docs/.keep"

    def test_no_file_marker_returns_none(self):
        assert _target_file_from_task("Just fix the parser please.") is None
        assert _target_file_from_task("") is None
        assert _target_file_from_task(None) is None

    def test_punctuation_only_path_is_none_not_empty_string(self):
        """`""` would read as a real path downstream; None is the honest answer."""
        assert _target_file_from_task("File: ... rest") is None

    def test_first_match_wins_when_two_files_named(self):
        assert _target_file_from_task(f"File: {REAL}. Also File: other.py.") == REAL
