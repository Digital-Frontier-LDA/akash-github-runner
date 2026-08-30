#!/usr/bin/env python3
"""The adoption rule must read what a workflow DOES, not what its comments say.

⛔ The rule shipped without a test of its own, covered only by the meta-tests that check it
is invocable and classified. Those prove it CAN run; they say nothing about what it decides.
A reviewer found the consequence: it scanned raw YAML, so a comment could decide the verdict
in BOTH directions — `# uses: <canonical>@<sha>` in a note would have counted as an adopter
and passed a repo with no caller, and a `just-akash deploy` quoted in a comment would have
pulled a repo that creates nothing into scope.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

RULE = Path(__file__).resolve().parent / "check_escrow_reaper_is_adopted.py"
CANONICAL = "Digital-Frontier-LDA/akash-github-runner/.github/workflows/reusable-akash-escrow-reaper.yml"
SHA = "0123456789abcdef0123456789abcdef01234567"

PREFIX = "dfci-infra-"
CREATES = (
    "jobs:\n  p:\n    steps:\n"
    f"      - run: uv tool run just-akash deploy --sdl x.yml   # placement {PREFIX}runner\n"
)
ADOPTS = f"jobs:\n  r:\n    uses: {CANONICAL}@{SHA}\n    with:\n      placement-prefix: {PREFIX}\n"


def _run(tmp_path: Path, files: dict[str, str]) -> subprocess.CompletedProcess:
    d = tmp_path / ".github" / "workflows"
    d.mkdir(parents=True)
    for name, body in files.items():
        (d / name).write_text(body)
    return subprocess.run(
        [sys.executable, str(RULE), str(d)], capture_output=True, text=True
    )


def test_a_creator_without_a_reaper_fails(tmp_path):
    assert _run(tmp_path, {"prov.yml": CREATES}).returncode == 1


def test_a_creator_with_a_pinned_reaper_passes(tmp_path):
    """Anti-vacuity: without this, a rule that always failed would satisfy every other case."""
    p = _run(tmp_path, {"prov.yml": CREATES, "reap.yml": ADOPTS})
    assert p.returncode == 0, p.stdout + p.stderr


def test_a_repo_that_creates_nothing_is_not_applicable(tmp_path):
    p = _run(tmp_path, {"read.yml": "jobs:\n  q:\n    steps:\n      - run: just-akash balance --json\n"})
    assert p.returncode == 0
    assert "NOT APPLICABLE" in p.stdout, "a skip must be printed, never silent"


def test_a_branch_ref_is_not_adoption(tmp_path):
    branch = ADOPTS.replace(f"@{SHA}", "@main")
    assert _run(tmp_path, {"prov.yml": CREATES, "reap.yml": branch}).returncode == 1


# ── the reviewer's finding: comments are not evidence, in EITHER direction ────────────

def test_a_commented_out_adoption_does_not_count(tmp_path):
    """⛔ THE ONE THAT WAS BROKEN. A note mentioning the canonical path would have passed a
    repo that calls nothing."""
    commented = f"# we should adopt this:\n#   uses: {CANONICAL}@{SHA}\njobs:\n  x:\n    steps:\n      - run: echo hi\n"
    p = _run(tmp_path, {"prov.yml": CREATES, "note.yml": commented})
    assert p.returncode == 1, "a commented-out `uses:` was counted as adoption"


def test_a_commented_out_create_does_not_pull_a_repo_into_scope(tmp_path):
    """The mirror. Over-claiming scope is the same defect pointed the other way — it would
    fail a repo that leaks nothing, and a rule that fails correct code gets exempted."""
    commented = "# historically this ran: uv tool run just-akash deploy --sdl x.yml\njobs:\n  x:\n    steps:\n      - run: echo hi\n"
    p = _run(tmp_path, {"note.yml": commented})
    assert p.returncode == 0
    assert "NOT APPLICABLE" in p.stdout


def test_an_indented_comment_is_also_stripped(tmp_path):
    """Comments inside a block are indented; a `startswith("#")` on the unstripped line
    would miss them, which is the shape that makes half a fix look like a fix."""
    commented = f"jobs:\n  x:\n    steps:\n      # uses: {CANONICAL}@{SHA}\n      - run: echo hi\n"
    assert _run(tmp_path, {"prov.yml": CREATES, "note.yml": commented}).returncode == 1


def test_an_empty_workflows_dir_refuses_rather_than_passes(tmp_path):
    """Judging nothing and returning 0 is what makes a rule look adopted everywhere it was
    never run."""
    d = tmp_path / ".github" / "workflows"
    d.mkdir(parents=True)
    p = subprocess.run([sys.executable, str(RULE), str(d)], capture_output=True, text=True)
    assert p.returncode == 1


# ── adopted is not the same as AIMED ──────────────────────────────────────────────────

def test_a_caller_with_no_placement_prefix_fails(tmp_path):
    """⛔ Without one the reaper sweeps under the mechanism's own default and matches none of
    this repo's deployments — 0 closable forever, while the adoption audit reads green."""
    no_prefix = f"jobs:\n  r:\n    uses: {CANONICAL}@{SHA}\n"
    p = _run(tmp_path, {"prov.yml": CREATES, "reap.yml": no_prefix})
    assert p.returncode == 1, "a caller declaring no prefix was accepted as adoption"
    assert "placement-prefix" in p.stdout


def test_a_prefix_this_repo_never_stamps_fails(tmp_path):
    """The inert-adoption case with a prefix present but wrong: it appears nowhere else in
    the repo, so the reaper would match nothing."""
    wrong = f"jobs:\n  r:\n    uses: {CANONICAL}@{SHA}\n    with:\n      placement-prefix: nobody-stamps-this-\n"
    p = _run(tmp_path, {"prov.yml": CREATES, "reap.yml": wrong})
    assert p.returncode == 1
    assert "appears nowhere else" in p.stdout


def test_a_prefix_the_repo_DOES_stamp_passes(tmp_path):
    """Anti-vacuity partner for both of the above: if any prefix were rejected, 'declares a
    prefix' would be satisfiable only by failing, and the rule would fail correct code."""
    p = _run(tmp_path, {"prov.yml": CREATES, "reap.yml": ADOPTS})
    assert p.returncode == 0, p.stdout + p.stderr


# ── the repo that SHIPS the mechanism has a different obligation, not a lighter one ────

INVOKES = "jobs:\n  r:\n    steps:\n      - run: uv run python -m just_akash.cleanup_stale --reap-runners\n"


def _with_mechanism(tmp_path: Path, files: dict[str, str]) -> subprocess.CompletedProcess:
    (tmp_path / "just_akash").mkdir(parents=True)
    (tmp_path / "just_akash" / "cleanup_stale.py").write_text("# the mechanism\n")
    return _run(tmp_path, files)


def test_the_mechanism_repo_passes_by_invoking_directly(tmp_path):
    """Requiring it to `uses:` the reusable would make it install ITSELF at a released SHA
    and sweep with that instead of HEAD — so a defect on HEAD would go unexercised by the one
    repo whose CI could catch it before consumers pin it."""
    p = _with_mechanism(tmp_path, {"prov.yml": CREATES, "reap.yml": INVOKES})
    assert p.returncode == 0, p.stdout + p.stderr
    assert "SHIPS the mechanism" in p.stdout


def test_the_mechanism_repo_still_has_to_RUN_it(tmp_path):
    """⛔ THE ANTI-HOLE. Without this, "ships the mechanism" would be a free pass and the repo
    most able to reap would be the only one not required to."""
    p = _with_mechanism(tmp_path, {"prov.yml": CREATES})
    assert p.returncode == 1, "shipping the mechanism without invoking it was accepted"
    assert "no workflow invokes it" in p.stdout


def test_a_consumer_gets_no_such_exemption(tmp_path):
    """Anti-vacuity in the other direction: a repo that merely MENTIONS the module, without
    shipping it, is still a consumer and must adopt."""
    p = _run(tmp_path, {"prov.yml": CREATES, "reap.yml": INVOKES})
    assert p.returncode == 1, "a consumer invoking the module directly was let off adoption"
