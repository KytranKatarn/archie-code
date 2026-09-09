"""#6657 — the ws file surface is confined to allowlisted roots and denies secrets.

Reproduced before the fix, from a sibling container with no credential:
``file_tree root=/`` → 2,000 entries of the engine's root filesystem;
``file_tree root=/workspace-platform`` → the live platform clone. Every test here
is one of the shapes that repro (or its write/diff twin) and must now be an error
frame, never data.
"""

import os
from pathlib import Path

import pytest

from archie_engine import workspace_ops as wo


@pytest.fixture
def root(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "src").mkdir()
    (ws / "src" / "app.py").write_text("print('hi')\n")
    (ws / ".env").write_text("INTERNAL_API_KEY=nope\n")
    (ws / "secrets").mkdir()
    (ws / "secrets" / "db_password.txt").write_text("x\n")
    (ws / ".git").mkdir()
    (ws / ".git" / "config").write_text("[core]\n")
    (ws / "deploy.key").write_text("-----BEGIN\n")
    monkeypatch.setenv("ARCHIE_ENGINE_WORKSPACE", str(ws))
    monkeypatch.delenv("ARCHIE_PLATFORM_WORKSPACE", raising=False)
    monkeypatch.delenv("ARCHIE_ENGINE_WS_ROOTS", raising=False)
    return ws


def test_allowed_roots_come_from_env_only(root, tmp_path, monkeypatch):
    assert wo.allowed_roots() == [root.resolve()]
    extra = tmp_path / "extra"
    extra.mkdir()
    monkeypatch.setenv("ARCHIE_ENGINE_WS_ROOTS", f"{extra}, /definitely/not/a/dir")
    assert wo.allowed_roots() == [root.resolve(), extra.resolve()]


def test_list_repos_advertises_only_allowed_roots(root):
    assert [r["path"] for r in wo.list_repos()] == [str(root.resolve())]


@pytest.mark.parametrize("bad_root", ["/", "/etc", "/tmp", ".."])
def test_root_outside_allowlist_is_refused(root, bad_root):
    assert "error" in wo.file_tree(bad_root)
    assert "error" in wo.read_file(bad_root, "passwd")
    assert "error" in wo.git_diff(bad_root)
    assert "error" in wo.write_file(bad_root, "x.txt", "x")


def test_the_repro_shapes_are_errors(root):
    # exactly what was sent from archie_platform before the fix
    assert "error" in wo.file_tree("/")
    assert "error" in wo.read_file("/", "etc/passwd")
    assert "error" in wo.read_file(str(root), "/etc/passwd")  # absolute path escaping the root


def test_no_root_means_first_allowed_root(root):
    assert wo.file_tree(None)["root"] == str(root.resolve())
    assert wo.read_file(None, "src/app.py")["content"] == "print('hi')\n"


def test_subdir_of_allowed_root_is_ok(root):
    assert wo.file_tree(str(root / "src"))["files"] == ["app.py"]


@pytest.mark.parametrize("rel", [".env", "secrets/db_password.txt", ".git/config", "deploy.key", "../ws/.env"])
def test_secret_paths_are_denied_for_read_write_diff(root, rel):
    assert "secret path denied" in wo.read_file(str(root), rel).get("error", "")
    assert "error" in wo.write_file(str(root), rel, "pwned")
    assert "error" in wo.git_diff(str(root), rel)
    if not rel.startswith(".."):
        assert (root / rel).read_text() != "pwned"


def test_file_tree_omits_secrets(root):
    files = wo.file_tree(str(root))["files"]
    assert "src/app.py" in files
    for hidden in (".env", "secrets/db_password.txt", ".git/config", "deploy.key"):
        assert hidden not in files


def test_symlink_out_of_root_is_refused(root, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("leak\n")
    os.symlink(outside, root / "link.txt")
    assert "error" in wo.read_file(str(root), "link.txt")


def test_write_stays_inside_root(root):
    ok = wo.write_file(str(root), "src/new.py", "x = 1\n")
    assert ok.get("bytes") == 6 and (root / "src" / "new.py").exists()
    assert "error" in wo.write_file(str(root), "../escape.txt", "x")
    assert not (root.parent / "escape.txt").exists()


def test_unconfigured_process_falls_back_to_cwd_only(monkeypatch, tmp_path):
    """A dev/test process with no workspace env has exactly one root: its cwd.
    The container always sets the env, so this branch never runs there."""
    for k in ("ARCHIE_ENGINE_WORKSPACE", "ARCHIE_PLATFORM_WORKSPACE", "ARCHIE_ENGINE_WS_ROOTS"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.chdir(tmp_path)
    assert wo.allowed_roots() == [Path(tmp_path).resolve()]
    assert "error" in wo.file_tree("/")
