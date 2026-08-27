"""#6057: the dedup cooldown throttles re-attempts; the cap STOPS them.

PRs #2857/#2865 were byte-identical engine builds one 6h cooldown apart -- a
finding no fix lands on regenerates a PR every cycle forever. After
DEFAULT_MAX_ATTEMPTS recorded builds a key is skipped permanently; a merged fix
never reaches the cap because the hub closes its issue and stops serving it."""

import json
import time

from archie_engine.dedup_tracker import DedupTracker, DEFAULT_MAX_ATTEMPTS


def _tracker(tmp_path):
    return DedupTracker(tmp_path)


def test_cap_skips_permanently_even_after_cooldown(tmp_path):
    t = _tracker(tmp_path)
    for _ in range(DEFAULT_MAX_ATTEMPTS):
        t.record(8350)
    # cooldown of 0 = every timestamp is expired; the cap must still skip
    assert t.should_skip(8350, cooldown_sec=0) is True


def test_under_cap_expired_cooldown_allows_retry(tmp_path):
    t = _tracker(tmp_path)
    t.record(8350)
    assert t.should_skip(8350, cooldown_sec=0) is False, "one attempt + expired cooldown -> retry"
    assert t.should_skip(8350, cooldown_sec=999999) is True, "cooldown itself still throttles"


def test_max_attempts_none_disables_the_cap(tmp_path):
    t = _tracker(tmp_path)
    for _ in range(10):
        t.record(77)
    assert t.should_skip(77, cooldown_sec=0, max_attempts=None) is False


def test_legacy_float_format_migrates_as_one_attempt(tmp_path):
    (tmp_path / "attempted_issues.json").write_text(json.dumps({"8393": time.time() - 99999}))
    t = _tracker(tmp_path)
    assert t.should_skip("8393", cooldown_sec=0) is False, "legacy entry = 1 attempt, not capped"
    t.record("8393")
    assert t.should_skip("8393", cooldown_sec=0) is True, "history survived: 1+1 = capped"


def test_proposal_keys_share_the_same_cap(tmp_path):
    t = _tracker(tmp_path)
    for _ in range(DEFAULT_MAX_ATTEMPTS):
        t.record("proposal:2663")
    assert t.should_skip("proposal:2663", cooldown_sec=0) is True


def test_unknown_key_never_skips(tmp_path):
    assert _tracker(tmp_path).should_skip(1234, cooldown_sec=0) is False
