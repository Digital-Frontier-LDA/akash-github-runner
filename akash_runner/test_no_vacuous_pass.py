"""No checker may report PASS over an empty population.

⛔ THE DEFECT, and it was mine. Blazing-Back #1443 proposed
`git ls-files --others --exclude-standard` as "the only rule that cannot be quietly
skipped". It is the only one that can NEVER FIRE: an untracked file does not exist in a
CI clone, so the command is vacuously green on every runner forever while the scripts sit
on laptops. DX caught it. I had asserted a property the guard could not observe — the exact
defect family this campaign exists to close.

⇒ GENERALISED, THEN MEASURED RATHER THAN ASSUMED. The class is "a checker whose subject is
not present where the checker runs". My five inspect workflow FILES, which are in the clone,
so that exact class does not apply — but a sibling does, and three of the five had it:

    check_standard.py            empty document   FAIL   non-vacuous already
    check_pool_owns_teardown.py  empty document   PASS   <- vacuous
    check_reaper_schedule.py     empty directory  PASS   <- vacuous
    check_dereg_backstop.py      empty directory  PASS   <- vacuous

A wrong path, a repo layout change, or a checkout that omitted `.github` produces an empty
population, and all three then reported PASS while observing nothing.

⚠ AND A VACUITY CONTROL IN THE TESTS DID NOT PREVENT IT. `check_pool_owns_teardown` shipped
with `test_the_population_is_not_empty_…`, which asserts the FIXTURE selects something. That
guards the test, not the runtime. **A non-vacuity assertion about a fixture is not a floor
under the checker.**

⇒ These tests drive the real entrypoints by subprocess, because the floors live in `main()`
— the path CI actually invokes — and calling `check()` directly would miss them entirely.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from conformance_exit import NOT_JUDGEABLE

ROOT = Path(__file__).resolve().parents[1]

DIR_CHECKERS = [
    "check_reaper_schedule.py",
    "check_dereg_backstop.py",
    "check_provisioning_lives_in_just_akash.py",
]


def _run(script: str, target: Path):
    return subprocess.run(
        [sys.executable, str(ROOT / "akash_runner" / script), str(target)],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )


@pytest.mark.parametrize("script", DIR_CHECKERS)
def test_an_empty_directory_FAILS_rather_than_passing(script, tmp_path):
    """★★ THE FLOOR. 'I found nothing to check' is not 'you comply'."""
    r = _run(script, tmp_path)
    # ⚠ RE-AIMED, not relaxed. The floor now returns NOT_JUDGEABLE (3) so a fleet sweep can
    # separate "this rule does not apply here" from "this repo is broken". The SEMANTIC these
    # tests protect — an empty population must never read as a pass — is asserted separately
    # below and is the part that must never weaken.
    assert r.returncode != 0, "an empty population read as a PASS"
    assert r.returncode == NOT_JUDGEABLE, (
        f"{script} passed over an empty population:\n{r.stdout}{r.stderr}"
    )
    assert "found 0 WORKFLOW documents" in (r.stdout + r.stderr)


@pytest.mark.parametrize("script", DIR_CHECKERS)
def test_a_real_directory_PASSES_and_says_how_many_it_examined(script, tmp_path):
    """★★ PRINT WHICH MODE IT RAN IN. A pass that does not say what it covered cannot be
    told from a pass that covered nothing — which is how the vacuous ones went unnoticed."""
    (tmp_path / "ci.yml").write_text(
        "on:\n  push:\njobs:\n  t:\n    steps:\n      - run: pytest\n"
    )
    r = _run(script, tmp_path)
    assert r.returncode == 0, (
        f"{script} failed on a benign workflow:\n{r.stdout}{r.stderr}"
    )
    assert "1 workflow file(s) examined" in r.stdout, r.stdout


def test_pool_owns_teardown_FAILS_on_a_document_with_no_jobs(tmp_path):
    doc = tmp_path / "empty.yml"
    doc.write_text("{}\n")
    r = _run("check_pool_owns_teardown.py", doc)
    assert r.returncode != 0, "an empty document read as a PASS"
    assert r.returncode == NOT_JUDGEABLE, f"expected NOT_JUDGEABLE:\n{r.stdout}{r.stderr}"
    assert "declares no jobs" in (r.stdout + r.stderr)


def test_pool_owns_teardown_PASSES_a_real_document_and_counts_jobs(tmp_path):
    doc = tmp_path / "wf.yml"
    doc.write_text("on:\n  push:\njobs:\n  build:\n    runs-on: x\n")
    r = _run("check_pool_owns_teardown.py", doc)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "1 job(s) examined" in r.stdout, r.stdout


def test_a_nonexistent_path_is_an_ERROR_not_a_pass():
    """★ KNOWN-NEGATIVE for the floor: a missing path must stay distinguishable from an
    empty one. Both are 'nothing to judge', but they have different causes and different
    fixes, and collapsing them loses the one that names a typo."""
    for script in DIR_CHECKERS:
        r = _run(script, Path("/definitely/not/here"))
        assert r.returncode == 2, f"{script} did not error on a missing path"


def test_check_standard_was_already_non_vacuous(tmp_path):
    """★ CONTROL on the audit itself. If this passed too, my classification of which
    checkers were vacuous would be wrong and the other tests would be measuring nothing."""
    doc = tmp_path / "empty.yml"
    doc.write_text("{}\n")
    r = _run("check_standard.py", doc)
    assert r.returncode == 1
    assert "no canonical just-akash runner-pool" in r.stdout


# ===========================================================================
# ⛔ THE FIRST VERSION OF THIS FLOOR COUNTED GLOB HITS, NOT WORKFLOWS — so it made the
# silent green LOUDER instead of catching it.
#
# Measured 2026-08-23, in the same wrong-path incident this module was written for:
# pointed at the just-akash repo ROOT, the checker matched .pre-commit-config.yaml,
# .sops.yaml and .coderabbit.yaml — none of which declares `on:` or `jobs:` — and
# printed:
#
#     Dereg backstop: PASS — 3 workflow file(s) examined
#
# That is MORE convincing than the bare PASS it replaced, because it asserts a number
# and reads as evidence of work done. The floor has to count what it actually judged.
# ===========================================================================

# The three real files that produced the false count, by shape.
NON_WORKFLOW_YAML = {
    ".pre-commit-config.yaml": "repos:\n  - repo: local\n    hooks: []\n",
    ".sops.yaml": "creation_rules:\n  - path_regex: .*\n    age: age1xyz\n",
    ".coderabbit.yaml": "reviews:\n  profile: chill\n",
}

REAL_WORKFLOW = 'name: w\non:\n  schedule: [{cron: "0 * * * *"}]\njobs:\n  j:\n    runs-on: ubuntu-latest\n    steps:\n      - run: "true"\n'


@pytest.mark.parametrize("script", DIR_CHECKERS)
def test_a_directory_of_NON_workflow_yaml_FAILS(script, tmp_path):
    """★★ The wrong-path case, verbatim. Files matched; nothing was a workflow."""
    for name, text in NON_WORKFLOW_YAML.items():
        (tmp_path / name).write_text(text)
    r = _run(script, tmp_path)
    out = r.stdout + r.stderr
    assert r.returncode != 0, f"{script} passed over 3 non-workflow files:\n{out}"
    assert r.returncode == NOT_JUDGEABLE, f"{script} did not report NOT_JUDGEABLE:\n{out}"
    assert "found 0 WORKFLOW documents" in out, out


@pytest.mark.parametrize("script", DIR_CHECKERS)
def test_the_failure_names_BOTH_counts_so_the_wrong_path_is_obvious(script, tmp_path):
    """"0 workflows, 3 files matched" is what tells a reader they aimed at a repo root.

    "0 workflows" alone reads like an empty directory and invites the wrong fix.
    """
    for name, text in NON_WORKFLOW_YAML.items():
        (tmp_path / name).write_text(text)
    out = _run(script, tmp_path).stdout + _run(script, tmp_path).stderr
    assert "3 yaml file(s) matched" in out, out


@pytest.mark.parametrize("script", DIR_CHECKERS)
def test_one_real_workflow_among_non_workflows_is_still_a_population(script, tmp_path):
    """The floor must not over-fire: a repo with config yaml AND workflows is fine."""
    for name, text in NON_WORKFLOW_YAML.items():
        (tmp_path / name).write_text(text)
    (tmp_path / "real.yml").write_text(REAL_WORKFLOW)
    r = _run(script, tmp_path)
    out = r.stdout + r.stderr
    assert "found 0 WORKFLOW documents" not in out, out
    assert "1 workflow file(s) examined" in out or r.returncode == 1, out


@pytest.mark.parametrize("script", DIR_CHECKERS)
def test_an_UNREADABLE_file_still_counts_toward_the_population(script, tmp_path):
    """⚠ Dropping it would trade one vacuity for another.

    An unparseable workflow is not a workflow we could confirm — but removing it from
    the population would delete the "could not be read, so it was NOT checked" finding
    and let a repo look compliant because its only backstop failed to parse.
    """
    (tmp_path / "broken.yml").write_text("jobs: [unclosed\n")
    r = _run(script, tmp_path)
    out = r.stdout + r.stderr
    assert "found 0 WORKFLOW documents" not in out, (
        f"an unreadable file was dropped from the population, so the read failure is "
        f"now reported as an empty directory:\n{out}"
    )
