"""Controls for the funding-projection rule, labelled KP vs KN.

⚠ The known-positive is the REAL shape measured in a consuming repo's
`akash-runner.yml` on 2026-08-24, not a synthetic one. A synthetic fixture would
not carry the `at +300s` phrasing the discriminator keys on, and the rule would
pass its own test while missing the thing it was built for.

⚠ The known-negatives are the load-bearing half here. A rule that flags any
workflow mentioning an allowance would satisfy the KP and be useless — it would
red every funding gate including the correct ones. Each KN pins one way the rule
must NOT fire.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SPEC = importlib.util.spec_from_file_location(
    "check_funding_projection_is_quantised",
    _HERE / "check_funding_projection_is_quantised.py",
)
assert _SPEC and _SPEC.loader
_mod = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _mod
_SPEC.loader.exec_module(_mod)

check_workflow = _mod.check_workflow
check_funding_projection_is_quantised = _mod.check_funding_projection_is_quantised


# ── The real defect, verbatim in shape ────────────────────────────────────────
# akash-runner.yml's "Precheck Console deploy credit": read, sleep 60, read
# again, project the difference 300s forward, refuse. Its own emitted message on
# 2026-08-24 was:
#   "fell 5.00 ACT in 60s (26.29 -> 21.29) ... projected at +300s = -3.71 ACT"
_KP_TWO_SAMPLE_PROJECTION = """
name: provision
jobs:
  provision:
    steps:
      - name: Precheck Console deploy credit (fail fast on exhaustion)
        run: |
          a1="$(just-akash balance --json | jq -r '.allowance_uact')"
          sleep 60
          a2="$(just-akash balance --json | jq -r '.allowance_uact')"
          drop=$(( a1 - a2 ))
          projected=$(( a2 - drop * 5 ))
          if [ "$projected" -lt "$MIN_UACT" ]; then
            echo "::error::allowance fell ${drop} in 60s, projected at +300s = ${projected}"
            exit 1
          fi
"""

# ── KNs ───────────────────────────────────────────────────────────────────────

# The CORRECT gate: read the level once, compare to the floor. No extrapolation.
_KN_SINGLE_READ_FLOOR = """
name: provision
jobs:
  provision:
    steps:
      - name: Precheck allowance
        run: |
          allowance_uact="$(just-akash balance --json | jq -r '.allowance_uact')"
          if [ "$allowance_uact" -lt "$MIN_UACT" ]; then
            echo "::error::allowance below one deployment's deposit"
            exit 1
          fi
"""

# Repeated sampling that only PRINTS. Diagnostics are explicitly permitted; the
# rule must not punish an operator series.
_KN_DIAGNOSTIC_SERIES_ONLY = """
name: observe
jobs:
  observe:
    steps:
      - name: Sample the allowance for diagnostics
        run: |
          for i in $(seq 1 40); do
            a="$(just-akash balance --json | jq -r '.allowance_uact')"
            echo "sample $i deploy_credit=$a projected trend for the operator log"
            sleep 20
          done
"""

# Two reads with a gate, but NO extrapolation — a settle-wait then a fresh
# level check. Legitimate, and the rule must not fire on the second read alone.
_KN_SECOND_READ_WITHOUT_PROJECTION = """
name: provision
jobs:
  provision:
    steps:
      - name: Recheck after settle
        run: |
          a1="$(just-akash balance --json | jq -r '.allowance_uact')"
          sleep 30
          a2="$(just-akash balance --json | jq -r '.allowance_uact')"
          if [ "$a2" -lt "$MIN_UACT" ]; then
            echo "::error::allowance below floor after settle"
            exit 1
          fi
"""


def _write(tmp_path: Path, name: str, body: str) -> Path:
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


def test_kp_two_sample_projection_is_flagged(tmp_path: Path) -> None:
    """KP, load-bearing. The measured defect must be caught."""
    p = _write(tmp_path, "akash-runner.yml", _KP_TWO_SAMPLE_PROJECTION)
    findings = check_workflow(p)
    assert findings, (
        "the two-sample linear projection is the defect this rule exists for — "
        "a rule that does not flag it is inert"
    )
    assert any("quantised" in f.message for f in findings)


def test_kn_single_read_against_the_floor_is_not_flagged(tmp_path: Path) -> None:
    """KN. The CORRECT gate must stay green, or the rule reds every consumer."""
    p = _write(tmp_path, "ok.yml", _KN_SINGLE_READ_FLOOR)
    assert check_workflow(p) == []


def test_kn_diagnostic_series_without_a_decision_is_not_flagged(tmp_path: Path) -> None:
    """KN. Sampling for the operator log is permitted; only gating is forbidden."""
    p = _write(tmp_path, "observe.yml", _KN_DIAGNOSTIC_SERIES_ONLY)
    assert check_workflow(p) == []


def test_kn_a_second_read_alone_is_not_the_defect(tmp_path: Path) -> None:
    """KN. Two reads are legitimate. The defect is the EXTRAPOLATION, not the re-read."""
    p = _write(tmp_path, "settle.yml", _KN_SECOND_READ_WITHOUT_PROJECTION)
    assert check_workflow(p) == []


def test_an_empty_workflows_dir_is_n_a_not_a_pass(tmp_path: Path) -> None:
    """Population pin. A zero from 'nothing scanned' must not read as 'nothing wrong'."""
    res = check_funding_projection_is_quantised(tmp_path, set())
    assert res.status == "n-a", "an empty scan must be n-a, never a pass"


def test_a_missing_dir_is_n_a_not_a_pass(tmp_path: Path) -> None:
    """Population pin, the other absence."""
    res = check_funding_projection_is_quantised(tmp_path / "nope", set())
    assert res.status == "n-a"


def test_the_rule_fires_at_repo_level_too(tmp_path: Path) -> None:
    """The wrapper must aggregate, not just the per-file entry point.

    A rule whose per-file function works while its repo-level wrapper returns
    nothing is invoked-but-inert — the shape this repo already catches with
    test_every_rule_has_a_call_site.
    """
    _write(tmp_path, "akash-runner.yml", _KP_TWO_SAMPLE_PROJECTION)
    res = check_funding_projection_is_quantised(tmp_path, set())
    assert res.findings, "repo-level wrapper must surface what check_workflow finds"
    assert res.status != "n-a"


# ═════════════ REGRESSION: THE ARTEFACT'S SHAPE, NOT A PARAPHRASE OF IT (#171) ═════════════
#
# ⛔ This rule shipped unable to detect the defect it was measured from. Two independent
# reasons, both verified by running the rule against the real akash-runner.yml (rc=0 before,
# rc=1 after):
#
#   1. `_SECOND_SAMPLE` was `\bsleep\s+\d+` — LITERAL digits. The real gate writes
#      `sleep "$DELTA_GAP_SEC"` (line 467). The known-positive above writes `sleep 60`, and
#      that literalisation was the only reason the fixture matched.
#   2. `_PROJECTION` was `project(ed|ion)?\b` and `_` IS A WORD CHARACTER, so it could not
#      match `projected_uact` — the identifier in the arithmetic on line 486. Its only match
#      in the real file was the ENGLISH word "projected" inside an echo on line 490, so the
#      finding cited a notice rather than the computation.
#
# ⇒ A fixture paraphrased from an artefact is not a fixture FROM it. These use the real
# spellings verbatim.


def _real_shape(tmp_path: Path, body: str) -> Path:
    d = tmp_path / "wf"
    d.mkdir(exist_ok=True)
    p = d / "akash-runner.yml"
    p.write_text(
        "name: runner\non: [workflow_call]\njobs:\n  deploy-runner:\n"
        "    runs-on: ubuntu-latest\n    steps:\n      - name: Precheck\n        run: |\n"
        + "".join(f"          {ln}\n" for ln in body.strip().splitlines())
    )
    return p


def test_kp_the_gap_is_a_VARIABLE_as_it_is_in_the_real_gate(tmp_path: Path) -> None:
    p = _real_shape(tmp_path, """
        DELTA_GAP_SEC="${AKASH_ALLOWANCE_SAMPLE_GAP_SEC:-60}"
        allowance_uact=$(read_allowance)
        sleep "$DELTA_GAP_SEC"
        allowance2_uact=$(read_allowance)
        drop_uact=$(( allowance_uact - allowance2_uact ))
        projected_uact=$(( allowance2_uact - ( drop_uact * DELTA_HORIZON_SEC / DELTA_GAP_SEC ) ))
        if [ "$projected_uact" -lt "$MIN_UACT" ]; then
          echo "::error title=ALLOWANCE COLLAPSING::below floor"
          exit 1
        fi
    """)
    findings = check_workflow(p)
    assert findings, "the real gate's own shape must be detected"


def test_the_finding_cites_the_ARITHMETIC_not_a_later_echo(tmp_path: Path) -> None:
    """⚠ A rule that cites the wrong line sends the reader to the wrong place. The
    identifier `projected_uact` must match, not merely the English word in a notice."""
    p = _real_shape(tmp_path, """
        allowance_uact=$(read_allowance)
        sleep "$GAP"
        projected_uact=$(( allowance_uact - drop * H / G ))
        [ "$projected_uact" -lt "$MIN_UACT" ] && exit 1
        echo "projected at +300s, for the log"
    """)
    findings = check_workflow(p)
    assert findings
    cited = p.read_text().splitlines()[findings[0].line - 1]
    assert "projected_uact=$((" in cited, f"cited the wrong line: {cited.strip()!r}"


def test_kn_a_variable_sleep_with_NO_projection_is_still_not_the_defect(tmp_path: Path) -> None:
    """⚠ Widening `_SECOND_SAMPLE` must not widen the RULE. Polling with a variable delay
    is ordinary; only a projection that gates is the defect."""
    p = _real_shape(tmp_path, """
        allowance_uact=$(read_allowance)
        sleep "$POLL_INTERVAL"
        [ "$allowance_uact" -lt "$MIN_UACT" ] && exit 1
    """)
    assert check_workflow(p) == [], "a single level check is the CORRECT gate"
