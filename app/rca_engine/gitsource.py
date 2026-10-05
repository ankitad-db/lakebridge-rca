"""Resolve source / transpiled SQL that lives in a Git repo (e.g. GitHub) to a local
directory the code-aware mapping can scan.

Migration projects commonly keep the ORIGINAL source-dialect SQL (e.g. Teradata) in one
repo and the transpiled Databricks SQL in another. This module clones such a repo at run
time (shallow) and returns the local path of the requested subdirectory, so the existing
``build_mapping(transpiled_output=..., source_scripts=..., source_transpiled=...)`` can
consume it exactly like a workspace folder.

A spec is a dict::

    {
      "repo": "https://github.com/org/td-source-sql.git",   # required (https or ssh URL)
      "ref": "main",            # optional branch / tag / commit SHA (default: repo HEAD)
      "path": "ddl",            # optional subdirectory within the repo (default: repo root)
      "token": "ghp_...",       # optional PAT for a private https repo (prefer token_secret)
      "token_secret": {"scope": "mig", "key": "github_token"},  # optional: read the PAT
                                #   from a Databricks secret scope instead of inlining it
      "profile": "ps-dr-east"   # optional CLI profile used to read the secret (CLI runs)
    }

Everything is best-effort: a missing ``git``, no network, a bad ref, or a failed secret
lookup logs a warning and returns ``None`` so the caller falls back to its ``*_dir`` path
(or to pure data-driven RCA). Clones are cached per ``(repo, ref)`` for the process so the
three script slots of one repo aren't cloned three times.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from typing import Any, Optional

# Process-wide clone cache: (repo, ref) -> local checkout root. Also tracks temp dirs so a
# caller can clean them up at end of run if it wants (best-effort; the OS reaps /tmp anyway).
_CLONE_CACHE: dict[tuple[str, str], str] = {}
_TEMP_DIRS: list[str] = []


def _looks_like_sha(ref: str) -> bool:
    return bool(ref) and len(ref) >= 7 and all(c in "0123456789abcdefABCDEF" for c in ref)


def _resolve_token(spec: dict[str, Any]) -> Optional[str]:
    """Return a PAT from the spec: inline ``token`` wins, else ``token_secret`` read from a
    Databricks secret scope (via dbutils in a notebook/job, else the CLI). Best-effort."""
    if spec.get("token"):
        return str(spec["token"])
    sec = spec.get("token_secret")
    if not isinstance(sec, dict) or not sec.get("scope") or not sec.get("key"):
        return None
    scope, key = str(sec["scope"]), str(sec["key"])
    # In a Databricks notebook/job, dbutils is the supported secret reader.
    try:
        from pyspark.dbutils import DBUtils  # type: ignore
        from pyspark.sql import SparkSession

        spark = SparkSession.getActiveSession()
        if spark is not None:
            return DBUtils(spark).secrets.get(scope=scope, key=key)
    except Exception:
        pass
    # CLI / headless fallback: the databricks CLI.
    try:
        args = ["databricks", "secrets", "get-secret", scope, key, "-o", "json"]
        if spec.get("profile"):
            args += ["-p", str(spec["profile"])]
        out = subprocess.run(args, capture_output=True, text=True, timeout=30)
        if out.returncode == 0 and out.stdout.strip():
            import base64
            import json
            val = json.loads(out.stdout).get("value")
            if val:
                # CLI returns the value base64-encoded.
                try:
                    return base64.b64decode(val).decode()
                except Exception:
                    return val
    except Exception:
        pass
    return None


def _auth_url(repo: str, token: Optional[str]) -> str:
    """Inject a PAT into an https GitHub URL for a private repo. SSH URLs are left as-is."""
    if not token or not repo.startswith("https://"):
        return repo
    rest = repo[len("https://"):]
    # x-access-token works for GitHub App tokens and classic/fine-grained PATs alike.
    return f"https://x-access-token:{token}@{rest}"


def _clone(repo: str, ref: str, token: Optional[str]) -> Optional[str]:
    key = (repo, ref or "")
    if key in _CLONE_CACHE and os.path.isdir(_CLONE_CACHE[key]):
        return _CLONE_CACHE[key]
    if not shutil.which("git"):
        print("[gitsource] git not found on PATH — cannot clone; falling back to local dir.")
        return None
    dest = tempfile.mkdtemp(prefix="rca_gitsrc_")
    _TEMP_DIRS.append(dest)
    url = _auth_url(repo, token)
    try:
        if ref and not _looks_like_sha(ref):
            # Fast path: shallow clone of a named branch/tag.
            r = subprocess.run(["git", "clone", "--depth", "1", "--branch", ref, url, dest],
                               capture_output=True, text=True, timeout=180)
            if r.returncode != 0:
                # Ref may be a branch not reachable by --branch (or a SHA misdetected); retry generic.
                r = subprocess.run(["git", "clone", "--depth", "1", url, dest],
                                   capture_output=True, text=True, timeout=180)
        else:
            r = subprocess.run(["git", "clone", url, dest],
                               capture_output=True, text=True, timeout=300)
            if r.returncode == 0 and ref:
                subprocess.run(["git", "-C", dest, "checkout", ref],
                               capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            # Redact the token from any echoed URL before logging.
            msg = (r.stderr or "").replace(token or "\0", "***")[:300]
            print(f"[gitsource] clone failed for {repo}@{ref or 'HEAD'}: {msg}")
            return None
    except Exception as exc:
        print(f"[gitsource] clone error for {repo}: {str(exc)[:200]}")
        return None
    _CLONE_CACHE[key] = dest
    return dest


def resolve_git_dir(spec: Any) -> Optional[str]:
    """Clone ``spec['repo']`` at ``spec['ref']`` and return the local path of ``spec['path']``
    (repo root if no path). Returns ``None`` on any failure so the caller uses its fallback.

    A falsy or non-dict ``spec`` returns ``None`` (nothing configured). Clones are cached per
    ``(repo, ref)`` so multiple script slots pointing at the same repo clone it once.
    """
    if not spec or not isinstance(spec, dict) or not spec.get("repo"):
        return None
    repo = str(spec["repo"])
    ref = str(spec.get("ref") or "")
    token = _resolve_token(spec)
    root = _clone(repo, ref, token)
    if not root:
        return None
    sub = str(spec.get("path") or "").strip().lstrip("/")
    local = os.path.join(root, sub) if sub else root
    if not os.path.isdir(local):
        print(f"[gitsource] path '{sub}' not found in {repo}@{ref or 'HEAD'} — using repo root.")
        return root
    return local


def cleanup() -> None:
    """Remove temp clone dirs (best-effort). Optional — /tmp is reaped by the OS anyway."""
    for d in _TEMP_DIRS:
        shutil.rmtree(d, ignore_errors=True)
    _TEMP_DIRS.clear()
    _CLONE_CACHE.clear()
