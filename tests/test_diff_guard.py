"""Diff-safety gate (#6053) -- pins the rules that would have stopped engine
PR #2861 (698/744 lines deleted + placeholder credentials, tests green because
the suite never imports the module). Pure-function tests + wiring/ordering pins."""

import inspect

from archie_engine import diff_guard
from archie_engine.build_loop import BuildLoop


def _diff(path, deleted=0, added=()):
    lines = [f"diff --git a/{path} b/{path}", f"--- a/{path}", f"+++ b/{path}",
             "@@ -1,%d +1,%d @@" % (max(deleted, 1), max(len(added), 1))]
    lines += [f"-old line {i}" for i in range(deleted)]
    lines += [f"+{a}" for a in added]
    return "\n".join(lines) + "\n"


def test_pr2861_replay_is_refused():
    """The incident shape: most of the file deleted, placeholder creds added."""
    d = _diff("platform_v2/mcp_server/server.py", deleted=698,
              added=["        conn = psycopg2.connect(", "            dbname='your_dbname',",
                     "            password='your_password',", "        )"])
    ok, why = diff_guard.check(d, {"platform_v2/mcp_server/server.py": 744},
                               task="Fix this code issue. The server is loading tools from the database, which could be slow.")
    assert not ok
    assert "placeholder" in why  # rule 1 fires first; ratio would refuse it too


def test_deletion_ratio_refused_without_removal_ask():
    d = _diff("a.py", deleted=300, added=["pass"])
    ok, why = diff_guard.check(d, {"a.py": 400}, task="Fix this code issue.")
    assert not ok and "deletion ratio" in why and "75%" in why


def test_small_file_floor_exempts_tiny_edits():
    # 4 of 6 lines = 67% but under the 20-line floor -> fine
    d = _diff("tiny.py", deleted=4, added=["x = 1"])
    ok, _ = diff_guard.check(d, {"tiny.py": 6}, task="Fix this code issue.")
    assert ok


def test_under_ratio_passes():
    d = _diff("b.py", deleted=30, added=["y = 2"])
    ok, _ = diff_guard.check(d, {"b.py": 100}, task="Fix this code issue.")
    assert ok


def test_new_file_cannot_trip_the_ratio():
    d = "diff --git a/new.py b/new.py\n--- /dev/null\n+++ b/new.py\n@@ -0,0 +1,2 @@\n+a = 1\n+b = 2\n"
    ok, _ = diff_guard.check(d, {}, task="Fix this code issue.")
    assert ok


def test_placeholder_refused_even_on_a_one_line_edit():
    d = _diff("c.py", deleted=1, added=["API_KEY = 'changeme'"])
    ok, why = diff_guard.check(d, {"c.py": 500}, task="Fix this code issue.")
    assert not ok and "placeholder" in why


def test_explicit_removal_task_relaxes_ratio_but_never_placeholders():
    task = "Remove the legacy compatibility block from a.py"
    d = _diff("a.py", deleted=300, added=["pass"])
    ok, _ = diff_guard.check(d, {"a.py": 400}, task=task)
    assert ok, "an explicit removal ask must relax the ratio rule"
    d2 = _diff("a.py", deleted=300, added=["password = 'your_password'"])
    ok2, why2 = diff_guard.check(d2, {"a.py": 400}, task=task)
    assert not ok2 and "placeholder" in why2, "placeholders are NEVER carved out"


def test_binary_chunk_does_not_crash():
    d = "diff --git a/x.png b/x.png\nBinary files a/x.png and b/x.png differ\n"
    ok, _ = diff_guard.check(d, {}, task="")
    assert ok


def test_mention_in_comment_is_not_a_placeholder():
    # prose ABOUT placeholders (unquoted) must not trip rule 1
    d = _diff("d.py", deleted=1, added=["# never commit your_password style placeholders"])
    ok, _ = diff_guard.check(d, {"d.py": 100}, task="Fix this code issue.")
    assert ok


def test_gate_is_wired_before_the_test_stage_and_fails_closed():
    """Wiring + ORDERING pin: the gate must consult diff_guard.check between the
    efficacy gate and the test run, and an unreadable diff must refuse (fail
    closed), not proceed. A gate wired after `test` would waste the run the
    incident already proved meaningless."""
    src = inspect.getsource(BuildLoop.run)
    i_guard = src.find("diff_guard.check")
    i_test = src.find('_emit("test"')
    assert i_guard != -1, "BuildLoop.run lost the #6053 diff-safety gate"
    assert i_test != -1 and i_guard < i_test, "the gate must run BEFORE the test stage"
    assert "could not read diff" in src, "unreadable diff must fail closed"
    assert '"diff_unsafe"' in src
