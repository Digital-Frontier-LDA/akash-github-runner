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


# ⛔ RETIRED: test_KP_it_fires_on_the_ACTUAL_repo_file
#
# It asserted that .github/workflows/df-akash-gate.yml STILL CONTAINS the silenced close
# documented in the rule's docstring (df-cicd #1553, line 82), and instructed: "If that
# line was FIXED, delete this test in the same PR — do not weaken the rule to make it
# pass." The line WAS fixed — that file now branches explicitly and emits
# "::error title=Teardown FAILED" when the close fails — so the assertion is now false and
# forcing it true would mean re-introducing the defect.
#
# The property it protected is NOT lost. It guarded against a fixture drifting from the
# artefact it was copied from; that risk existed only while the artefact still carried the
# defect. test_KP_the_real_silenced_close_is_flagged keeps the rule honest against `_REAL`,
# which is the verbatim historical line, and is now a regression pin rather than a mirror
# of live code.
#
# DO NOT restore this test by planting a silenced close back into df-akash-gate.yml.


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
    """Non-vacuity pin. A rule that scans nothing reports no findings.

    ⚠ This used to assert the scan found >= 1 finding in this repo, using "a live defect
    exists" as a proxy for "the rule still works". That proxy inverted the moment the
    defect was fixed: a clean repo is the GOAL, and a test that fails when you reach it
    trains people to re-introduce defects or delete the test. Both halves are now asserted
    directly instead.
    """
    wfs = sorted((_REPO / ".github" / "workflows").glob("*.yml"))
    # (a) there is something to scan — otherwise every "no findings" result is vacuous
    assert wfs, "no workflows found — the scan population is empty and every result is vacuous"

    # (b) the scan is LIVE: the same check_workflow used over the corpus above must still
    #     flag the real historical defect. If the rule silently stopped working, (a) alone
    #     would keep passing while reporting a clean repo that was never actually examined.
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        planted = Path(td) / "planted.yml"
        planted.write_text(_REAL)
        assert check_workflow(planted), (
            "the rule no longer flags the verbatim historical defect (_REAL) — it has "
            "stopped working, and every clean result over the corpus is meaningless"
        )


# ── Criterion 2: the close depends on a tool whose installation is silenced ───
# KP: df-akash-gate.yml:56 BYTE-FOR-BYTE, next to the (already fixed, failure-propagating)
# reap it fed. The reap alone is clean; the finding is that its tool never installs.
_SILENCED_INSTALL_REAL = """
name: gate
jobs:
  gate:
    steps:
      - name: Allowlist + manifest
        run: |
          pipx install just-akash 2>/dev/null || pip install just-akash 2>/dev/null || true
      - name: Reap the lease (always)
        run: |
          if [ -n "${DSEQ:-}" ]; then
            just-akash destroy --dseq "$DSEQ" --yes
          fi
"""

# KN: the fix — pinned wheel, verified, failure propagates.
_PINNED_INSTALL = """
name: gate
jobs:
  gate:
    steps:
      - run: |
          echo "$JA_SHA256  $whl" | sha256sum -c -
          pipx install "$whl"
          just-akash destroy --help > /dev/null
      - run: |
          just-akash destroy --dseq "$DSEQ" --yes
"""

# KN: silenced install of the close tool, but nothing in the workflow closes anything.
_SILENCED_INSTALL_NO_CLOSE = """
name: tools
jobs:
  t:
    steps:
      - run: |
          pipx install just-akash 2>/dev/null || true
          just-akash list || true
"""

# KN: silenced install of an UNRELATED tool alongside a real close.
_SILENCED_UNRELATED_INSTALL = """
name: gate
jobs:
  gate:
    steps:
      - run: |
          pip install rich 2>/dev/null || true
      - run: |
          just-akash destroy --dseq "$DSEQ" --yes
"""

# KP: `destroy-all` is the real bulk close (there is no `close-all` in just-akash).
_SILENCED_DESTROY_ALL = """
name: sweep
jobs:
  s:
    steps:
      - run: |
          just-akash destroy-all --yes || true
"""


def test_KP_the_real_silenced_install_of_the_close_tool_is_flagged(tmp_path: Path) -> None:
    """KP, load-bearing. Verbatim df-akash-gate.yml:56; the reap beside it is clean."""
    found = check_workflow(_wf(tmp_path, _SILENCED_INSTALL_REAL))
    assert len(found) == 1, found
    assert "pipx install just-akash" in found[0][1]


def test_KN_a_pinned_failure_propagating_install_is_not_flagged(tmp_path: Path) -> None:
    """KN, the fix itself must pass — otherwise the rule forbids the remedy."""
    assert check_workflow(_wf(tmp_path, _PINNED_INSTALL)) == []


def test_KN_silenced_install_without_any_billable_close_is_not_flagged(tmp_path: Path) -> None:
    """KN. The conjunction matters: no close, no teardown hazard."""
    assert check_workflow(_wf(tmp_path, _SILENCED_INSTALL_NO_CLOSE)) == []


def test_KN_silenced_install_of_an_unrelated_tool_is_not_flagged(tmp_path: Path) -> None:
    """KN. Only tools a billable close actually invokes count."""
    assert check_workflow(_wf(tmp_path, _SILENCED_UNRELATED_INSTALL)) == []


def test_KP_a_silenced_destroy_all_is_flagged(tmp_path: Path) -> None:
    """KP. The real bulk subcommand; the old pattern only knew a non-existent close-all."""
    assert check_workflow(_wf(tmp_path, _SILENCED_DESTROY_ALL)), "destroy-all || true not flagged"

