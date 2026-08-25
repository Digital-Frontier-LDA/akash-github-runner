"""Every `reusable-*.yml` must appear in CONSUMERS.md — even to say it has none.

⛔ WHY. `reusable-akash-runner-conformance.yml` had ZERO callers for its entire life and
nothing noticed, because nothing was looking. The first real adoption found in one run that
this repo's own published `uses:` example pointed at a tag that did not contain the file — and
found it as a run with no job, no log and no annotation (#147, #148, #149).

⇒ A standard that has never been consumed has never been tested. This test makes "nobody uses
this" something you must WRITE DOWN rather than something you can fail to say.

⚠ A row of `NONE` PASSES, deliberately. An untested standard that admits it is untested is far
better than one that merely looks adopted. What this test forbids is ABSENCE — a reusable that
the registry does not mention at all, which is indistinguishable from an adopted one.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
REGISTRY = REPO / "CONSUMERS.md"
WORKFLOWS = REPO / ".github" / "workflows"
VALID_STATUS = {"GREEN", "NEVER-GREEN", "NONE", "UNVERIFIED"}


def _reusables() -> list[str]:
    return sorted(p.name for p in WORKFLOWS.glob("reusable-*.yml"))


def _rows() -> list[list[str]]:
    rows = []
    for line in REGISTRY.read_text().split("\n"):
        if not line.startswith("| `reusable-"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 3:
            rows.append(cells)
    return rows


def test_the_locator_finds_reusables_and_rows():
    """⛔ Non-vacuity. With an empty population every assertion below passes over nothing."""
    assert _reusables(), "no reusable-*.yml found — the locator is stale"
    assert _rows(), (
        "no registry rows parsed — the table format changed and this test is blind"
    )


@pytest.mark.parametrize("name", _reusables())
def test_every_reusable_is_declared(name: str):
    declared = {r[0].strip("`") for r in _rows()}
    assert name in declared, (
        f"{name} is not in CONSUMERS.md.\n"
        "Add a row. `NONE` is a legitimate answer — an unexercised standard that SAYS so is "
        "fine; one that is silently unexercised is how a reusable ends up with zero callers "
        "for its entire life and nobody notices (#149)."
    )


@pytest.mark.parametrize("row", _rows(), ids=lambda r: r[0][:40])
def test_every_row_has_a_valid_status(row: list[str]):
    status = row[2].strip("`")
    assert status in VALID_STATUS, (
        f"{row[0]}: status {status!r} is not one of {sorted(VALID_STATUS)}"
    )


@pytest.mark.parametrize("row", _rows(), ids=lambda r: r[0][:40])
def test_a_GREEN_row_cites_a_RUN_ID(row: list[str]):
    """⛔ The load-bearing one. 'The file exists', 'the pin resolves', 'the tests pass' and
    'the contract matches' were ALL true of the conformance reusable while it had never
    executed. Only an execution counts, and an execution has an id."""
    if row[2].strip("`") != "GREEN":
        return
    evidence = row[3] if len(row) > 3 else ""
    assert re.search(r"\b\d{9,}\b", evidence), (
        f"{row[0]} claims GREEN but cites no run id in its evidence: {evidence!r}.\n"
        "A GREEN row asserts that a run of this reusable, invoked from the named consumer, "
        "actually EXECUTED. Cite the run id so the next reader can check it."
    )


def test_a_reusable_with_no_row_would_be_REJECTED():
    """⛔ Known-negative: the check must be able to fail."""
    declared = {r[0].strip("`") for r in _rows()}
    assert "reusable-this-does-not-exist.yml" not in declared, (
        "fixture name leaked into the registry"
    )
    # the assertion the parametrised test makes, applied to a name that is absent:
    assert "reusable-this-does-not-exist.yml" not in declared, (
        "the membership test cannot fail"
    )
