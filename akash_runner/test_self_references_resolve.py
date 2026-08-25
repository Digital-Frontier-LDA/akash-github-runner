"""Every `uses:` example df-cicd publishes must actually resolve at the ref it names.

⚠ WHY. just-akash#185 was the FIRST consumer of `reusable-akash-runner-conformance.yml`.
It followed this repo's own docstring — "must pin df-cicd to an immutable tag" — and its
run came back `completed / failure` with **zero jobs**: no job, no log, no annotation.
That is not a failing check, it is a check that never started. GitHub could not resolve
the callee, so the run died at validation.

The reusable was added in `92f6530eb` at 10:45 that day and **no tag contained it**
(v2.7.1 / v2.7.0 / v2.6.0 all ABSENT, with `README.md` as a known-positive control
proving the probe could return PRESENT).

⛔ Measured across the whole repo, FOUR published examples pointed at refs that do not
contain their file — the conformance reusable, the stale-runner reaper, sentinel
engagement + freshness gate, and shannon-reap. Every consumer who copy-pasted any of them
got a jobs=0 run with nothing to read.

This is the same shape as #145 and #146: **the standard existed and did not enforce
itself.** The conformance workflow had zero consumers for its entire life, so nothing ever
exercised the call path its own documentation described. The first adoption found it.

Two properties, and the second is the one that bit:
  1. the ref is a 40-hex commit SHA (a tag is mutable — the thing pin-integrity removes)
  2. THE FILE EXISTS AT THAT REF (a valid SHA that predates the file resolves to nothing)
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

# Consumer-facing surface only. `baseline/` holds fixtures that are DELIBERATELY
# tag-shaped so the pin checkers have something to reject — sweeping them would delete
# the negative cases and leave those checkers unable to fail.
SEARCH_ROOTS = (".github", "templates", "standards", "README.md")

REF_RE = re.compile(r"Digital-Frontier-LDA/akash-github-runner/(?P<path>[A-Za-z0-9_./-]+)@(?P<ref>[A-Za-z0-9._-]+)")
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")


def _files() -> list[Path]:
    out: list[Path] = []
    for root in SEARCH_ROOTS:
        p = REPO / root
        if p.is_file():
            out.append(p)
        elif p.is_dir():
            out.extend(f for f in p.rglob("*") if f.is_file() and f.suffix in {".yml", ".yaml", ".md"})
    return out


def _references() -> list[tuple[Path, str, str]]:
    found = []
    for f in _files():
        try:
            text = f.read_text()
        except (UnicodeDecodeError, OSError):
            continue
        for m in REF_RE.finditer(text):
            found.append((f.relative_to(REPO), m.group("path"), m.group("ref")))
    return found


def _is_shallow() -> bool:
    r = subprocess.run(
        ["git", "rev-parse", "--is-shallow-repository"], cwd=REPO, capture_output=True, text=True
    )
    return r.stdout.strip() == "true"


def _exists_at(ref: str, path: str) -> bool:
    """`<ref>:<path>` present in THIS repo's git objects. Offline; no forge call."""
    r = subprocess.run(
        ["git", "cat-file", "-e", f"{ref}:{path}"], cwd=REPO, capture_output=True
    )
    return r.returncode == 0


ALL = _references()


def test_the_clone_is_deep_enough_to_ANSWER():
    """⛔ FIRST, because a shallow clone makes every other test here WRONG, not skipped.

    Measured on #148 against a default `actions/checkout` (depth 1): the referenced commits
    are absent from the clone, so every containment check reported "missing" — 13 false
    failures — and `rev-list --max-parents=0 HEAD` returned the shallow BOUNDARY commit,
    which DOES contain the file, so the known-negative control silently stopped being
    negative. That is the worst outcome available: a guard answering confidently from a
    narrower object than the one it names.

    So this FAILS rather than skips. "Cannot verify" must not read as "verified".
    """
    assert not _is_shallow(), (
        "this repository is a SHALLOW clone, so `git cat-file` cannot see the commits these "
        "references name. Every containment assertion below would answer from a truncated "
        "history — reporting present refs as missing AND letting a stale ref pass the "
        "known-negative control.\n"
        "Fix the WORKFLOW, not this test: `actions/checkout` needs `fetch-depth: 0`."
    )


def test_the_scanner_finds_something():
    """⛔ Non-vacuity. With an empty population every assertion below passes over nothing —
    which is exactly how the broken examples survived until a consumer tried one."""
    assert ALL, (
        f"no df-cicd self-references found under {SEARCH_ROOTS} — the locator is stale and "
        "this whole file is passing vacuously"
    )


@pytest.mark.parametrize("where,path,ref", ALL, ids=lambda v: str(v)[:40])
def test_every_published_reference_is_a_full_sha(where, path, ref):
    assert FULL_SHA.match(ref), (
        f"{where} publishes `{path}@{ref}` — pin by 40-hex COMMIT SHA, not a tag.\n"
        "A tag is mutable, which is the property pin-integrity exists to remove, and a tag "
        "that does not contain the file fails at VALIDATION with jobs=0 (no job, no log, no "
        "annotation) — it reads as a broken check rather than an unresolvable pin."
    )


@pytest.mark.parametrize("where,path,ref", ALL, ids=lambda v: str(v)[:40])
def test_every_published_reference_actually_contains_the_file(where, path, ref):
    """⛔ The property that actually bit. A well-formed ref that PREDATES the file resolves
    to nothing, and a SHA check alone would wave it through."""
    if not _exists_at(ref, path):
        pytest.fail(
            f"{where} publishes `{path}@{ref}` but that ref does NOT contain that path.\n"
            "A consumer copy-pasting this gets `completed/failure` with ZERO jobs and no "
            "diagnostic. Repoint it at a commit that contains the file."
        )


def test_a_ref_that_predates_a_file_is_REJECTED():
    """⛔ Known-negative: the containment probe must be able to say NO.

    Uses this repo's own first commit, which cannot contain a file added later. Without
    this, `_exists_at` returning True unconditionally would make the test above vacuous."""
    # ⚠ In a shallow clone `--max-parents=0` returns the shallow BOUNDARY, which is a
    # recent commit and DOES contain the file — the control would pass while proving
    # nothing. test_the_clone_is_deep_enough_to_ANSWER fails first so this cannot happen
    # quietly, and the assert below is a second line of defence.
    assert not _is_shallow(), "shallow clone — the known-negative below would be meaningless"
    first = subprocess.run(
        ["git", "rev-list", "--max-parents=0", "HEAD"], cwd=REPO, capture_output=True, text=True
    ).stdout.split()
    assert first, "no root commit — cannot construct a known-negative"
    assert not _exists_at(
        first[-1], ".github/workflows/reusable-akash-runner-conformance.yml"
    ), "the containment probe cannot fail — it would pass over any stale ref"


def test_a_known_present_file_is_ACCEPTED():
    """⛔ The other half: the probe must also be able to say YES."""
    assert _exists_at("HEAD", "README.md"), "the containment probe cannot succeed — it is broken"
