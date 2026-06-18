"""Tests for GitHubOpsTool — branch+PR-only PR creation (ADR-003 / #4255).

The HTTP layer (_post/_get) is overridden so these run without a network call."""

from archie_engine.tools.github_ops import GitHubOpsTool, DEFAULT_GITHUB_REPO


class _StubGitHub(GitHubOpsTool):
    def __init__(self, **kw):
        super().__init__(token="t0ken", **kw)
        self.posts = []
        self.gets = []
        self.post_response = (True, {"number": 7, "html_url": "https://github.com/x/y/pull/7"})
        self.get_response = (True, {"state": "open", "mergeable": True, "html_url": "u"})

    async def _post(self, path, json_body):
        self.posts.append((path, json_body))
        return self.post_response

    async def _get(self, path):
        self.gets.append(path)
        return self.get_response


# --- guard rails (fail closed) ---

async def test_pr_create_requires_token(monkeypatch):
    # Hermetic: GitHubOpsTool(token="") falls back to ARCHIE_GITHUB_TOKEN/
    # GITHUB_TOKEN from the env, which the engine container injects (#4258). Clear
    # them so this guard-rail asserts the no-token path regardless of runtime env.
    monkeypatch.delenv("ARCHIE_GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    r = await GitHubOpsTool(token="").execute(operation="pr_create", title="x", head="feat/x")
    assert not r.success and "token" in r.error.lower()


async def test_pr_create_requires_title_and_head():
    t = _StubGitHub()
    assert not (await t.execute(operation="pr_create", head="feat/x")).success
    assert not (await t.execute(operation="pr_create", title="x")).success
    assert t.posts == []


async def test_pr_create_refuses_protected_head():
    t = _StubGitHub()
    r = await t.execute(operation="pr_create", title="x", head="main")
    assert not r.success and "protected" in r.error.lower()
    assert t.posts == []  # never reached the API


async def test_pr_create_refuses_disallowed_base():
    t = _StubGitHub()
    r = await t.execute(operation="pr_create", title="x", head="feat/x", base="release")
    assert not r.success
    assert t.posts == []


# --- happy path (mocked HTTP) ---

async def test_pr_create_posts_correct_payload():
    t = _StubGitHub()
    r = await t.execute(operation="pr_create", title="My PR", body="b", head="feat/x")
    assert r.success, r.error
    assert r.metadata["number"] == 7
    path, payload = t.posts[0]
    assert path == f"/repos/{DEFAULT_GITHUB_REPO}/pulls"
    assert payload == {"title": "My PR", "body": "b", "head": "feat/x", "base": "main"}


async def test_pr_create_propagates_api_error():
    t = _StubGitHub()
    t.post_response = (False, {"message": "Validation Failed"})
    r = await t.execute(operation="pr_create", title="x", head="feat/x")
    assert not r.success and "Validation Failed" in r.error


async def test_pr_get_reads_state():
    t = _StubGitHub()
    r = await t.execute(operation="pr_get", number=7)
    assert r.success
    assert r.metadata["state"] == "open"
    assert t.gets == [f"/repos/{DEFAULT_GITHUB_REPO}/pulls/7"]


async def test_pr_get_requires_number():
    assert not (await _StubGitHub().execute(operation="pr_get")).success


# --- the engine must NEVER merge: there is no merge operation ---

async def test_no_merge_operation_exists():
    t = _StubGitHub()
    r = await t.execute(operation="pr_merge", number=7)
    assert not r.success and "unknown operation" in r.error.lower()
    assert t.posts == []
