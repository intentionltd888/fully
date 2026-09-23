# -*- coding: utf-8 -*-
"""maxurl.py — ask qsniyg/maxurl ("Image Max URL", Apache-2.0) for bigger versions of image URLs.

Runs maxurl_runner.js under the quickjs-ng binary Fully already bundles; one qjs process handles
the whole batch (~0.2 s to load maxurl's 3.7 MB rule file, then well under 1 ms per URL).
Offline: maxurl's network-backed rules are disabled, only its URL-rewrite rules run.

    from maxurl import bigger
    bigger(["https://cdn.example.com/photos/abc_small.jpg"], "/path/to/qjs", "/path/to/maxurl_runner.js",
           lib="/path/to/userscript_smaller.user.js")
    -> {"https://cdn.example.com/photos/abc_small.jpg": ["https://cdn.example.com/photos/abc_original.jpg", ...]}

lib defaults to userscript_smaller.user.js next to the runner.
Each value lists candidates best-first and never contains the input URL itself;
[] (or a missing key) means maxurl has nothing better. Stdlib only; never raises.
"""
from __future__ import annotations

import json
import os
import subprocess

def bigger(urls: list[str], qjs_path: str, runner: str, lib: str | None = None, timeout=20,
           page_url: str | None = None) -> dict[str, list[str]]:
    """{input_url: [bigger candidate, ...]} best-first. Returns {} on any failure.
    page_url (optional) is the page the images came from; a few maxurl rules look at it."""
    try:
        todo = [u for u in dict.fromkeys(urls or [])
                if isinstance(u, str) and u.startswith(("http://", "https://"))]
        if not todo:
            return {}
        if not (os.path.isfile(runner) and os.path.isfile(qjs_path) and os.access(qjs_path, os.X_OK)):
            return {}
        cmd = [qjs_path, "--std", "--script", runner]   # classic script, not ES module
        if lib:
            cmd += ["--lib", lib]
        if page_url:
            cmd += ["--page", page_url]
        env = dict(os.environ)
        env.pop("MAXURL_DEBUG", None)
        proc = subprocess.run(cmd, input=json.dumps(todo).encode("utf-8"),
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              timeout=timeout, env=env)
        if proc.returncode != 0:
            return {}
        data = json.loads(proc.stdout.decode("utf-8"))
        if not isinstance(data, dict):
            return {}
        return {u: [c for c in cands if isinstance(c, str) and c != u]
                for u, cands in data.items()
                if isinstance(u, str) and isinstance(cands, list)}
    except Exception:
        return {}


if __name__ == "__main__":   # quick manual check: python3 maxurl.py QJS RUNNER LIB URL [URL ...]
    import sys
    if len(sys.argv) < 5:
        print("usage: python3 maxurl.py QJS RUNNER LIB URL [URL ...]")
        sys.exit(64)
    print(json.dumps(bigger(sys.argv[4:], sys.argv[1], sys.argv[2], lib=sys.argv[3]), indent=1, ensure_ascii=False))
