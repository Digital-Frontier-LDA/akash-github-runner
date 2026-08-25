"""Controls for the silenced-teardown rule, labelled KP vs KN.

⚠ THE KNOWN-POSITIVE IS THE REAL LINE, BYTE-FOR-BYTE. A paraphrase is not a fixture
FROM the artefact: on df-cicd #169 a fixture wrote `sleep 60` where the real gate writes
`sleep "$DELTA_GAP_SEC"`, the pattern required literal digits, and that single
normalisation was the ONLY reason the fixture matched. The rule passed its own test while
being unable to fire on the file it was written from.

⚠ THE KNOWN-NEGATIVES CARRY THE WEIGHT HERE. `|| true` is correct on a best-effort
diagnostic or a log upload. A rule that flagged every `|| true` would bury the one real
instance in noise and train readers to dismiss it — worse than not having the rule.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_teardown_cannot_be_silenced import check_workflow  # noqa: E402

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent


def _wf(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "w.yml"
    p.write_text(body, encoding="utf-8")
    return p


# ── KP: the real defect, verbatim from df-akash-gate.yml:82 ──────────────────
_REAL = """
name: gate
jobs:
  gate:
    steps:
      - name: Close the lease
        run: |
          [ -n "${DSEQ:-}" ] && just-akash close "$DSEQ" 2>/dev/null || true
"""


def test_KP_the_real_silenced_close_is_flagged(tmp_path: Path) -> None:
    """KP, load-bearing. Verbatim from df-akash-gate.yml:82."""
    found = check_workflow(_wf(tmp_path, _REAL))
    assert found, "the real silenced close was not flagged — the rule cannot fire on its own subject"


def test_KP_it_fires_on_the_ACTUAL_repo_file() -> None:
    """KP against the artefact itself, not a copy of it.

    ⭐ This is the check that #169 lacked. A fixture can drift from the file it was taken
    from; running against the real path cannot.
    """
    target = _REPO / ".github" / "workflows" / "df-akash-gate.yml"
    if not target.exists():
        pytest.skip("df-akash-gate.yml absent — nothing to assert against")
    found = check_workflow(target)
    assert found, (
        "df-akash-gate.yml contains a silenced close (line 82 at time of writing) and the "
        "rule did not find it. If that line was FIXED, delete this test in the same PR — "
        "do not weaken the rule to make it pass."
    )


# ── KNs ──────────────────────────────────────────────────────────────────────

_CLOSE_THAT_CAN_FAIL = """
name: gate
jobs:
  gate:
    steps:
      - name: Close the lease
        run: |
          just-akash close "$DSEQ"
"""

_SILENCED_BUT_NOT_BILLABLE = """
name: gate
jobs:
  gate:
    steps:
      - name: Best-effort diagnostics
        run: |
          kubectl logs deploy/foo > logs.txt 2>/dev/null || true
          rm -f /tmp/scratch || true
"""

_COMMENT_DESCRIBING_THE_DEFECT = """
name: gate
jobs:
  gate:
    steps:
      - name: Close the lease properly
        run: |
          # ⛔ Do NOT write `just-akash close "$DSEQ" || true` — it cannot fail.
          just-akash close "$DSEQ"
"""


def test_KN_a_close_that_can_fail_is_not_flagged(tmp_path: Path) -> None:
    """KN. The rule targets the SILENCING, not the closing."""
    assert check_workflow(_wf(tmp_path, _CLOSE_THAT_CAN_FAIL)) == []


def test_KN_a_silenced_non_billable_command_is_not_flagged(tmp_path: Path) -> None:
    """KN, load-bearing. `|| true` on a diagnostic is correct, not a defect.

    Without this the rule could be widened to every `|| true` and still pass every KP —
    and it would then fire on most workflows in the fleet.
    """
    assert check_workflow(_wf(tmp_path, _SILENCED_BUT_NOT_BILLABLE)) == []


def test_KN_a_comment_describing_the_defect_is_not_the_defect(tmp_path: Path) -> None:
    """KN. Matching prose makes a prose detector.

    Measured on df-cicd #169: a rule matched `gh pr merge` in a DOCSTRING and in a
    `MERGE_SIGNATURE = "gh pr merge"` constant, and flagged two files that never call gh.
    """
    assert check_workflow(_wf(tmp_path, _COMMENT_DESCRIBING_THE_DEFECT)) == []


def test_the_population_is_not_empty() -> None:
    """Non-vacuity pin. A rule that scans nothing reports no findings."""
    wfs = sorted((_REPO / ".github" / "workflows").glob("*.yml"))
    assert wfs, "no workflows found — the scan population is empty and every result is vacuous"
    total = sum(len(check_workflow(w)) for w in wfs)
    assert total >= 1, (
        "the rule found nothing anywhere in df-cicd. Either every silenced close was fixed "
        "(in which case update this pin deliberately) or the rule stopped working."
    )
