"""NOT-JUDGEABLE (exit 3) must be distinguishable from a finding (1) and a usage error (2).

★ THE AMBIGUITY. Measured across seven repos, the same exit code carried two different facts:

    df-wiki           FAIL — 0 workflow(s) read the org listing   <- the rule does not apply
    blazing           FAIL (4 findings)                           <- four real defects

The non-vacuity floor is right — a PASS over an empty population reads as coverage. But it
replaced one ambiguity with another, and a fleet sweep could not separate NOT-JUDGEABLE from
DEFECTIVE without reading prose.

⚠ WHY THESE TESTS ASSERT BOTH DIRECTIONS. A rule that returned 3 unconditionally would satisfy
"empty population exits 3" perfectly. `test_a_real_population_is_never_not_judgeable` is what
makes that impossible, and it is the limb that would catch a mis-aimed patch — including the one
made while writing this: a floor-detector matching the phrase "is not a pass" hit a FINDINGS
message in check_funding_gate_is_not_re_derived.py and converted the wrong return.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from conformance_exit import MARKER, NOT_JUDGEABLE

ROOT = Path(__file__).resolve().parent

# Rules whose non-vacuity floor has adopted the third state, verified behaviourally.
# ⚠ (script, flag-or-None). The suite uses FIVE CLI conventions across its rules (issue #30):
# most dir-scoped rules take a POSITIONAL path, `check_listing_failure_is_loud.py` takes
# `--workflows-dir`. A harness that assumed one convention would report the other as broken —
# which is what happened while writing this, and is the same divergence #32's guard exists for.
DIR_SCOPED = [
    ("check_backstop_covers_producers.py", None),
    ("check_dereg_backstop.py", None),
    ("check_reaper_schedule.py", None),
    ("check_listing_failure_is_loud.py", "--workflows-dir"),
]
DOC_SCOPED = [
    "check_pool_owns_teardown.py",
    "check_teardown_can_identify.py",
]


def _run(script: str, target: Path, flag: str | None = None) -> subprocess.CompletedProcess:
    argv = [sys.executable, str(ROOT / script)]
    argv += ([flag, str(target)] if flag else [str(target)])
    return subprocess.run(argv, capture_output=True, text=True, timeout=60)


@pytest.fixture
def empty_dir(tmp_path: Path) -> Path:
    (tmp_path / "not-a-workflow.yml").write_text("just: a mapping\nnot: a workflow\n")
    return tmp_path


@pytest.fixture
def empty_doc(tmp_path: Path) -> Path:
    p = tmp_path / "nojobs.yml"
    p.write_text("name: n\non: [push]\n")
    return p


@pytest.mark.parametrize("script,flag", DIR_SCOPED)
def test_an_empty_population_is_NOT_JUDGEABLE_not_a_finding(script, flag, empty_dir):
    r = _run(script, empty_dir, flag)
    assert r.returncode == NOT_JUDGEABLE, (
        f"{script} exited {r.returncode} on an empty population. 1 is a real finding and 2 is a "
        f"usage error; neither says 'I observed nothing'.\n{r.stdout}{r.stderr}"
    )
    assert MARKER in r.stdout, (
        f"{script} did not print the machine-readable marker. The exit code alone is lost to any "
        f"wrapper that collapses it (`|| true`, `&&`), which is the failure this replaces."
    )


@pytest.mark.parametrize("script", DOC_SCOPED)
def test_an_empty_document_is_NOT_JUDGEABLE(script, empty_doc):
    r = _run(script, empty_doc)
    assert r.returncode == NOT_JUDGEABLE, f"{script} -> {r.returncode}\n{r.stdout}{r.stderr}"
    assert MARKER in r.stdout


@pytest.mark.parametrize("script,flag", DIR_SCOPED)
def test_a_real_population_is_never_NOT_JUDGEABLE(script, flag):
    """⛔ THE LIMB THAT MAKES THE ABOVE MEAN SOMETHING. A rule returning 3 unconditionally would
    pass every test above; only this one refutes it."""
    r = _run(script, Path(".github/workflows"), flag)
    assert r.returncode != NOT_JUDGEABLE, (
        f"{script} reported NOT-JUDGEABLE against the repo's own workflows, which are not an "
        f"empty population. The floor is firing when it should not.\n{r.stdout}{r.stderr}"
    )


def test_three_is_distinct_from_the_usage_error_code():
    """⚠ 2 is DOUBLY taken: argparse uses it for an unrecognised flag, and the rules use it for
    a missing path. That is why the third state is 3 — 2 cannot separate 'I could not judge'
    from 'you called me wrong'."""
    r = _run("check_dereg_backstop.py", Path("/nonexistent/path/xyz"))
    assert r.returncode == 2, f"expected the usage-error code 2, got {r.returncode}"
    assert r.returncode != NOT_JUDGEABLE


def test_the_third_state_is_non_zero_so_old_consumers_are_unaffected():
    """⚠ THE CONTRACT-CHANGE GUARD. This action is public and consumed cross-org by repos pinned
    at SHAs that have never heard of exit 3. Both the old code (1) and the new (3) are non-zero,
    so `if ! rule; then fail` behaves identically. No previously-failing build starts passing —
    that is the direction that would break someone else's CI silently."""
    assert NOT_JUDGEABLE != 0, "a not-judgeable rule must never read as a pass to any caller"
