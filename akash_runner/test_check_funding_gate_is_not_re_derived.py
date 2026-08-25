"""The funding-gate rule must fire on a real re-derivation and stay silent on prose."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_funding_gate_is_not_re_derived import audit, main  # noqa: E402


def _wf(tmp_path: Path, run: str, name: str = "w.yml") -> Path:
    doc = textwrap.dedent(f"""\
        name: w
        on: [workflow_call]
        jobs:
          provision:
            runs-on: ubuntu-latest
            steps:
              - name: gate
                run: |
{textwrap.indent(textwrap.dedent(run), " " * 18)}
        """)
    p = tmp_path / name
    p.write_text(doc)
    return p


# ───────────────────────── KNOWN-NEGATIVES: measured defects ─────────────────────────


def test_KN_extrapolating_a_step_function_is_caught(tmp_path):
    """The ~24%-false-refusal defect: two samples, 60s apart, projected forward."""
    p = _wf(tmp_path, """
        a=$(read_allowance); sleep 60; b=$(read_allowance)
        rate=$(( (b - a) / 60 ))
        projected=$(( b + rate * 300 ))
        [ "$projected" -lt "$MIN_UACT" ] && exit 1
    """)
    probs = audit(p)
    assert probs, "a rate projection over an allowance must be caught"
    assert "extrapolates-a-step-function" in probs[0]


def test_KN_gating_on_console_deploy_credit_is_caught(tmp_path):
    p = _wf(tmp_path, """
        credit=$(just-akash balance --json | jq -r '.deploy_credit[0].micro')
        [ "$credit" -lt "$MIN_UACT" ] && exit 1
    """)
    probs = audit(p)
    assert probs and "gates-on-console-deploy-credit" in probs[0]


def test_KN_reading_the_singular_spend_limit_is_caught(tmp_path):
    """`spend_limit` is uakt:0 on a funded account; the uact figure is under the plural."""
    p = _wf(tmp_path, """
        amt=$(curl -s "$LCD/grants" | jq -r '.grants[0].authorization.spend_limit.amount')
        [ "$amt" -lt "$MIN_UACT" ] && exit 1
    """)
    probs = audit(p)
    assert probs and "reads-the-singular-spend-limit" in probs[0]


def test_KN_summing_slots_is_caught(tmp_path):
    p = _wf(tmp_path, """
        total=$(for slot in $SLOTS; do read_allowance "$slot"; done | paste -sd+ | bc)
        [ "$total" -lt "$MIN_UACT" ] && exit 1
    """)
    probs = audit(p)
    assert probs and "sums-slots-instead-of-max" in probs[0]


# ───────────────────────── KNOWN-POSITIVES: must stay silent ─────────────────────────


def test_KP_routing_through_the_primitive_passes(tmp_path):
    """The exemption IS the primitive. No allow-list, and it expires if removed.

    ⚠ This block deliberately READS an allowance and DECIDES on it — it satisfies both
    earlier conjuncts and is spared ONLY by the primitive marker. An earlier version read
    nothing, so the READS gate skipped it and the exemption was never consulted: the test
    passed with the exemption deleted.
    """
    p = _wf(tmp_path, """
        allowance=$(just-akash grants --json | jq -r '.spend_limits[0].amount')
        python3 -c 'from akash_lease_core.funding import evaluate_funding, FundingPolicy' \\
          --allowance "$allowance" || exit 1
        [ "$DECISION" = "BELOW_FLOOR" ] && exit 1
    """)
    assert audit(p) == []


def test_KP_reporting_a_balance_without_deciding_passes(tmp_path):
    """⛔ SCOPE. Printing a number for a human is not gating on it. Without this the rule
    would demand the primitive of every diagnostic that mentions an allowance."""
    p = _wf(tmp_path, """
        just-akash balance --json | jq '.deploy_credit'
        echo "for the operator's eyes only"
    """)
    assert audit(p) == []


def test_KP_a_workflow_with_no_funding_logic_passes(tmp_path):
    p = _wf(tmp_path, 'echo "hello"')
    assert audit(p) == []


def test_KP_an_unrelated_exit_1_is_not_a_funding_gate(tmp_path):
    """⛔ BOTH conjuncts are load-bearing. This block DECIDES (a comparison and an exit)
    but reads no allowance. Without this control, deleting the READS gate survives and
    the rule demands akash-lease-core of every step that can fail."""
    p = _wf(tmp_path, """
        pytest -q || exit 1
        [ "$COUNT" -lt 3 ] && exit 1
    """)
    assert audit(p) == []


# ───────────── THE CONTROL THAT SEPARATES THIS RULE FROM A GREP ─────────────


def test_PROSE_IN_A_COMMENT_DOES_NOT_TRIP_THE_RULE(tmp_path):
    """⛔⛔ THE DISCRIMINATING CONTROL, and it is not a footnote.

    A sibling guard in Blazing-Back scanned raw file text with a keyword window and flagged
    a DOCSTRING as an unclassified DELETE call site — demanding that a comment be
    registered in a list of things that actually close deployments. A rule that cannot tell
    code from a sentence about code can be satisfied by editing the sentence.

    This comment names every anti-pattern the rule looks for AND a decision phrase
    (`exit 1`, `MIN_UACT`). Both halves are required: an earlier version of this test
    omitted the decision words, so the DECIDES conjunct filtered the block out before the
    comment-stripping code ran, and the test passed with comment-stripping DELETED. Do not
    "tidy" those words out of the comment — they are what makes this control discriminating.
    """
    p = _wf(tmp_path, """
        # This job does NOT gate on funding. Historically it projected a rate from
        # deploy_credit, read spend_limit (singular), summed each slot, and would
        # `exit 1` when the total fell under MIN_UACT — all four defects, described
        # here so nobody reintroduces them.
        echo "no funding decision is made in this step"
    """)
    assert audit(p) == [], "a comment describing the defects must not BE the defect"


def test_only_run_blocks_are_read_not_the_raw_file(tmp_path):
    """Same property one level up: the same words in `env:` or a job name are not code."""
    p = tmp_path / "x.yml"
    p.write_text(textwrap.dedent("""\
        name: deploy_credit spend_limit rate projection
        on: [workflow_call]
        env:
          NOTE: "spend_limit deploy_credit rate MIN_UACT exit 1"
        jobs:
          j:
            runs-on: ubuntu-latest
            steps:
              - run: echo ok
        """))
    assert audit(p) == []


def test_the_PLURAL_key_is_not_accused_of_being_the_SINGULAR(tmp_path):
    """⛔ A CORRECT VERDICT REACHED BY A WRONG ROUTE. This block still re-derives locally,
    so it is rightly flagged — but it reads `spend_limits`, the CORRECT key. If the
    singular pattern loses its `(?!s)` lookahead the verdict stays the same and only the
    REASON goes wrong, which is the harder kind of defect to notice. Assert the reason."""
    p = _wf(tmp_path, """
        amt=$(curl -s "$LCD/grants" | jq -r '.grants[0].authorization.spend_limits[0].amount')
        [ "$amt" -lt "$MIN_UACT" ] && exit 1
    """)
    probs = audit(p)
    assert probs, "it still decides locally, so it is still a finding"
    assert "reads-the-singular-spend-limit" not in probs[0], (
        "spend_limits (PLURAL) is the correct key — accusing it is a wrong reason"
    )


def test_an_ENGLISH_word_containing_rate_is_not_an_extrapolation(tmp_path):
    """⛔ MEASURED, not imagined: run against the real akash-runner.yml, bare `rate`
    matched "delibeRATEly" inside an echo string. `_strip_comments` removes `#` comments
    but cannot remove prose that lives inside a quoted string, so the PATTERN must carry
    the boundary. This block still decides locally and is still flagged — but accusing it
    of extrapolating would be a wrong reason on a correct verdict."""
    p = _wf(tmp_path, """
        amt=$(get_allowance "$acct")
        echo "reading it once, deliberately, to generate an accurate operator note"
        [ "$amt" -lt "$MIN_UACT" ] && exit 1
    """)
    probs = audit(p)
    assert probs, "it still decides locally"
    assert "extrapolates-a-step-function" not in probs[0], (
        "'deliberately'/'generate'/'accurate' are English, not a rate projection"
    )


# ───────────────────────────── harness behaviour ─────────────────────────────


def test_an_empty_scan_is_an_ERROR_not_a_pass(tmp_path, capsys):
    """A rule that finds nothing to check must not report OK — that is the vacuous green
    this repo keeps finding."""
    assert main([str(tmp_path / "nonexistent")]) == 2


def test_unparseable_yaml_is_an_ERROR_not_a_pass(tmp_path, capsys):
    bad = tmp_path / "bad.yml"
    bad.write_text("jobs: [unclosed\n")
    assert main([str(bad)]) == 2


def test_a_clean_workflow_exits_zero(tmp_path):
    _wf(tmp_path, 'echo "hello"')
    assert main([str(tmp_path)]) == 0


def test_a_dirty_workflow_exits_one(tmp_path):
    _wf(tmp_path, """
        credit=$(get deploy_credit)
        [ "$credit" -lt "$MIN_UACT" ] && exit 1
    """)
    assert main([str(tmp_path)]) == 1
