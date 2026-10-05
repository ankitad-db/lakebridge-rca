"""Unit tests for rca_engine.gitsource — spec resolution, subpath join, and best-effort
fallback. Git itself is mocked, so these run offline with no network."""

import os

import rca_engine.gitsource as gs


def _reset():
    gs._CLONE_CACHE.clear()
    gs._TEMP_DIRS.clear()


def test_none_spec_returns_none():
    _reset()
    assert gs.resolve_git_dir(None) is None
    assert gs.resolve_git_dir({}) is None
    assert gs.resolve_git_dir({"ref": "main"}) is None   # no repo
    assert gs.resolve_git_dir("not-a-dict") is None


def test_resolves_subpath(tmp_path, monkeypatch):
    _reset()
    root = tmp_path / "clone"
    (root / "transpiled").mkdir(parents=True)
    monkeypatch.setattr(gs, "_clone", lambda repo, ref, token: str(root))
    out = gs.resolve_git_dir({"repo": "https://x/y.git", "ref": "main", "path": "transpiled"})
    assert out == os.path.join(str(root), "transpiled")


def test_missing_subpath_falls_back_to_root(tmp_path, monkeypatch):
    _reset()
    root = tmp_path / "clone"
    root.mkdir()
    monkeypatch.setattr(gs, "_clone", lambda repo, ref, token: str(root))
    out = gs.resolve_git_dir({"repo": "https://x/y.git", "path": "nope"})
    assert out == str(root)


def test_clone_failure_returns_none(monkeypatch):
    _reset()
    monkeypatch.setattr(gs, "_clone", lambda repo, ref, token: None)
    assert gs.resolve_git_dir({"repo": "https://x/y.git"}) is None


def test_sha_detection():
    assert gs._looks_like_sha("a1b2c3d")
    assert gs._looks_like_sha("0123456789abcdef")
    assert not gs._looks_like_sha("main")
    assert not gs._looks_like_sha("v1.2.0")
    assert not gs._looks_like_sha("")


def test_auth_url_injects_token_https_only():
    assert gs._auth_url("https://github.com/o/r.git", "tok") == \
        "https://x-access-token:tok@github.com/o/r.git"
    # ssh + no-token are left untouched
    assert gs._auth_url("git@github.com:o/r.git", "tok") == "git@github.com:o/r.git"
    assert gs._auth_url("https://github.com/o/r.git", None) == "https://github.com/o/r.git"


def test_inline_token_preferred():
    assert gs._resolve_token({"token": "abc"}) == "abc"
    # no token config -> None (no secret backends available offline)
    assert gs._resolve_token({}) is None
    assert gs._resolve_token({"token_secret": {"scope": "s"}}) is None  # missing key
