#!/usr/bin/env python3
"""Measure every just-akash commit whose tree pins a pre-eMudhra runner image (df-cicd-rpi.10).

WHY. check_no_pre_emudhra_runner_digest reads the consumer's own files. A consumer that calls
`just-akash/.github/workflows/runner-pool.yml@<sha>` runs what just-akash's files name AT THAT
SHA, and that digest is not in the consumer's files. Measured 2026-10-29: df-cicd's
templates/akash-runner-ci.yml pinned ca353a9c (runner-pool runs aaf3799b, pre-fix) and the ban
reported 0. Blazing-Back and blazing had 11 such call sites, and the ban was 0 for them too.

WHAT. For every commit reachable from any ref of a just-akash clone (`git rev-list --all`), the
WHOLE TREE is judged the way the ban judges a consumer's repository: every non-test code file
(the ban's _CODE_SUFFIXES, _is_test_path and _never), with comments as history. Each
(blob, suffix) is judged once. Judging only the workflow files missed a4fdd525, whose pre-fix
digest is only in sdl/github-runner-probe.yaml (df-grafana-7e on #88). The output
(data/just_akash_pre_emudhra_commits.txt) lists each such commit once, sorted, with the first
offending path as evidence. It names no digest in full, so the repo-wide scan does not read it
as a pin.

ONE LEVEL. Only the called sha's own tree is judged. An image it reaches through ITS OWN `uses:`
of another just-akash sha is not followed.

SOURCE. Measure a `git clone --mirror` of just-akash: it carries refs/pull/*, and a consumer can
pin a PR head GitHub still serves. A local clone may also hold unpushed commits nobody can pin.

MODES. `--write` regenerates the file. `--check` fails if the clone holds a commit the file lacks.
A commit the file has but the clone lacks is reported, not failed: GitHub keeps serving a commit
after its branch is deleted, so a consumer can still pin it, and the list only grows.

    python akash_runner/generate_just_akash_pre_emudhra_refs.py --repo <just-akash mirror> --check
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import check_no_pre_emudhra_runner_digest as ban

OUT = ban.JUST_AKASH_COMMITS_DATA
_HEADER = """\
# Every just-akash commit whose tree pins a df-akash-runner image built BEFORE the eMudhra/emSign
# CA distrust, in non-test code (df-cicd-rpi.10). GENERATED, never hand-edited:
#   git clone --mirror https://github.com/Digital-Frontier-LDA/just-akash just-akash.git
#   python akash_runner/generate_just_akash_pre_emudhra_refs.py --repo just-akash.git --write
# Measured over `git rev-list --all` of the clone, the whole tree judged with
# check_no_pre_emudhra_runner_digest's own scope (comments are history, test code is not read).
# Format: <commit>  <first offending path>  <digest prefix>
"""


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout


def _blobs(repo: Path, blobs: set[str]) -> dict[str, str]:
    """blob sha -> text, read in one `git cat-file --batch` (thousands of commits share blobs)."""
    want = sorted(blobs)
    out = subprocess.run(
        ["git", "-C", str(repo), "cat-file", "--batch"],
        input="".join(f"{b}\n" for b in want).encode(),
        check=True,
        capture_output=True,
    ).stdout
    texts, pos = {}, 0
    for blob in want:
        header_end = out.index(b"\n", pos)
        sha, _kind, size = out[pos:header_end].split()
        start = header_end + 1
        texts[sha.decode()] = out[start : start + int(size)].decode("utf-8", errors="replace")
        pos = start + int(size) + 1
    return texts


def _scanned(path: str) -> bool:
    rel = Path(path)
    return rel.suffix in ban._CODE_SUFFIXES and not ban._never(rel) and not ban._is_test_path(rel)


def measure(repo: Path) -> list[tuple[str, str, str]]:
    """Sorted (commit, first offending path, 12-hex digest prefix), one row per pre-fix commit."""
    commits = _git(repo, "rev-list", "--all").split()
    if not commits:
        raise SystemExit(f"{repo}: no commits; is this a just-akash clone?")
    trees: dict[str, list[tuple[str, str]]] = {}  # commit -> [(path, blob)]
    for commit in commits:
        rows = []
        for line in _git(repo, "ls-tree", "-r", commit).splitlines():
            meta, path = line.split("\t", 1)
            _mode, kind, blob = meta.split()
            if kind == "blob" and _scanned(path):
                rows.append((path, blob))
        trees[commit] = sorted(rows)
    texts = _blobs(repo, {blob for rows in trees.values() for _p, blob in rows})
    verdict: dict[tuple[str, str], str | None] = {}

    def judge(path: str, blob: str) -> str | None:
        key = (blob, Path(path).suffix)
        if key not in verdict:
            code = "\n".join(ban._code_part(line, key[1]) for line in texts[blob].splitlines())
            hits = ban._pre_fix(code)
            verdict[key] = hits[0].removeprefix("sha256:")[:12] if hits else None
        return verdict[key]

    out = []
    for commit, rows in trees.items():
        for path, blob in rows:
            digest = judge(path, blob)
            if digest:
                out.append((commit, path, digest))
                break
    return sorted(out)


def render(rows: list[tuple[str, str, str]]) -> str:
    return _HEADER + "".join(f"{c}  {p}  {d}\n" for c, p, d in rows)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", required=True, type=Path, help="a full (not shallow) just-akash clone")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)
    if _git(args.repo, "rev-parse", "--is-shallow-repository").strip() == "true":
        print(f"::error::{args.repo} is shallow; a shallow clone hides old commits, so it cannot answer")
        return 2
    rows = measure(args.repo)
    if args.write:
        args.out.write_text(render(rows), encoding="utf-8")
        print(f"wrote {len(rows)} commit(s) to {args.out}")
        return 0
    have = ban.load_just_akash_commits(args.out)
    where = {c: (p, d) for c, p, d in rows}
    missing, gone = sorted(set(where) - have), sorted(have - set(where))
    for c in missing:
        p, d = where[c]
        print(f"::error file={args.out}::just-akash {c} pins a pre-fix runner ({p}: {d}) and is not listed; re-run --write")
    for c in gone:
        print(f"note: listed {c} is not in this clone (kept: GitHub still serves a deleted branch's commit)")
    print(f"just-akash pre-fix commits: {len(where)} measured, {len(have)} listed, {len(missing)} missing")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
