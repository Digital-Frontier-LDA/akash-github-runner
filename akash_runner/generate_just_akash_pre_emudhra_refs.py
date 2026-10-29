#!/usr/bin/env python3
"""Measure every just-akash (commit, workflow) whose file pins a pre-eMudhra runner (df-cicd-rpi.10).

WHY. check_no_pre_emudhra_runner_digest reads the consumer's own files. A consumer that calls
`just-akash/.github/workflows/runner-pool.yml@<sha>` runs whatever image runner-pool.yml names AT
THAT SHA, and that digest is not in the consumer's files. Measured 2026-10-29: df-cicd's
templates/akash-runner-ci.yml pinned ca353a9c (runner-pool runs aaf3799b, pre-fix) and the ban
reported 0. Blazing-Back and blazing had 11 such call sites, and the ban was 0 for them too.

WHAT. For every commit reachable from any ref of a just-akash clone (`git rev-list --all`), every
direct *.yml/*.yaml child of .github/workflows is judged with the ban's own findings(): a
pre-fix digest in code, where comments are history. Each blob is judged once. The output
(data/just_akash_pre_emudhra_workflow_refs.txt) lists each (commit, workflow) pair that pins a
pre-fix image, sorted. It names no digest in full, so the repo-wide scan does not read it as a
pin.

ONE LEVEL. Only the called file is judged. A pre-fix image that runner-pool.yml@<sha> reaches
through ITS OWN `uses:` of another just-akash sha is not followed.

SOURCE. Measure a `git clone --mirror` of just-akash: it carries refs/pull/*, and a consumer can
pin a PR head GitHub still serves (2026-10-29: 584 pairs from the mirror, 465 from a
branches-only clone). A local clone may also hold unpushed commits nobody can pin.

MODES. `--write` regenerates the file. `--check` fails if the clone holds a pair the file lacks.
A pair the file has but the clone lacks is reported, not failed: GitHub keeps serving a commit
after its branch is deleted, so a consumer can still pin it, and the list only grows.

    python akash_runner/generate_just_akash_pre_emudhra_refs.py --repo <just-akash clone> --check
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import check_no_pre_emudhra_runner_digest as ban

OUT = ban.JUST_AKASH_REFS_DATA
_HEADER = """\
# Every (just-akash commit, workflow file) whose file at that commit pins a df-akash-runner image
# built BEFORE the eMudhra/emSign CA distrust (df-cicd-rpi.10). GENERATED, never hand-edited:
#   git clone --mirror https://github.com/Digital-Frontier-LDA/just-akash just-akash.git
#   python akash_runner/generate_just_akash_pre_emudhra_refs.py --repo just-akash.git --write
# Measured over `git rev-list --all` of the clone, with check_no_pre_emudhra_runner_digest's own
# findings() (comments are history). Format: <commit>  <.github/workflows file>  <digest prefix>
"""


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout


def _blobs(repo: Path, blobs: set[str]) -> dict[str, str]:
    """blob sha -> text, read in one `git cat-file --batch` (5k+ commits share few blobs)."""
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


def measure(repo: Path) -> list[tuple[str, str, str]]:
    """Sorted (commit, workflow path, 12-hex digest prefix) for every pre-fix pin."""
    commits = _git(repo, "rev-list", "--all").split()
    if not commits:
        raise SystemExit(f"{repo}: no commits; is this a just-akash clone?")
    entries: list[tuple[str, str, str]] = []  # (commit, path, blob)
    for commit in commits:
        for line in _git(repo, "ls-tree", commit, ".github/workflows/").splitlines():
            meta, path = line.split("\t", 1)
            _mode, kind, blob = meta.split()
            if kind == "blob" and Path(path).suffix in {".yml", ".yaml"}:
                entries.append((commit, path, blob))
    texts = _blobs(repo, {blob for _c, _p, blob in entries})
    verdict: dict[str, str | None] = {}
    for _c, path, blob in entries:
        if blob not in verdict:
            code = "\n".join(ban._code_part(line, Path(path).suffix) for line in texts[blob].splitlines())
            hits = ban._pre_fix(code)
            verdict[blob] = hits[0].removeprefix("sha256:")[:12] if hits else None
    return sorted({(c, p, verdict[b]) for c, p, b in entries if verdict[b]})


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
        print(f"wrote {len(rows)} pair(s) to {args.out}")
        return 0
    have = set(ban.load_just_akash_refs(args.out))
    measured = {(c, p) for c, p, _d in rows}
    missing, gone = sorted(measured - have), sorted(have - measured)
    for c, p in missing:
        print(f"::error file={args.out}::just-akash {c} {p} pins a pre-fix runner and is not listed; re-run --write")
    for c, p in gone:
        print(f"note: listed {c} {p} is not in this clone (kept: GitHub still serves a deleted branch's commit)")
    print(f"just-akash pre-fix refs: {len(measured)} measured, {len(have)} listed, {len(missing)} missing")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
