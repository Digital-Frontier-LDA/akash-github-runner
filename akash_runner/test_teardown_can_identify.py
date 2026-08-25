"""The rule must reject the shape both repos ACTUALLY SHIPPED, not merely find the field.

⛔ THE CONTROL THAT MAKES THIS NON-VACUOUS is `test_a_naive_output_exists_rule_would_pass
_the_broken_form`. Measured on the real files: BOTH just-akash and Blazing-Back declare a
`dseq` output, including the broken one. So "an output named dseq exists somewhere"
certifies the exact workflow that leaked two deployments for 32 hours. If this module ever
stops distinguishing them it has stopped being worth running.

★ THE STRONGEST FIXTURE PAIR IS ONE FILE, ONE COMMIT APART. just-akash's runner-pool.yml
fails this rule at 53515bc^ and passes at 53515bc — the commit whose message is "the pool
owns its teardown". The rule flips exactly on the fix, which is the only evidence that it
is measuring the fix and not something correlated with it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from akash_runner.check_teardown_can_identify import (  # noqa: E402
    check_document,
    check_run_block,
)

# ── The two real shapes, reduced to their discriminating structure ──────────────

# just-akash, after 53515bc: published the moment it exists.
GOOD = """
rm -f /tmp/ja.log
"${JA[@]}" deploy --sdl /tmp/runner-sdl.yaml 2>&1 | tee /tmp/ja.log || true
DSEQ=$(awk -F': +' '/^[[:space:]]*DSEQ:/{print $2; exit}' /tmp/ja.log || true)
echo "dseq=$DSEQ" >> "$GITHUB_OUTPUT"
PROVIDER=$(awk -F': +' '/Provider:/{print $2; exit}' /tmp/ja.log || true)
"""

# Blazing-Back akash-runner.yml: published only inside the success branch.
BROKEN = """
DSEQ=$(akash tx deployment create | awk '/dseq/{print $2}')
for i in $(seq 1 "$REG_TRIES"); do
  if [ "$ONLINE_COUNT" -ge "${MIN_POOL}" ]; then
    online=1; break
  fi
  sleep 10
done
if [ "$online" -eq 1 ]; then
  echo "dseq=$DSEQ" >> "$GITHUB_OUTPUT"
  echo "provision_healthy=true" >> "$GITHUB_OUTPUT"
fi
"""


def _wf(run: str) -> dict:
    return {"jobs": {"pool": {"steps": [{"name": "Deploy", "run": run}]}}}


# ── Known bad / known good, in both directions ────────────────────────────────


def test_known_bad_publishing_only_on_the_success_path_is_REJECTED():
    """★★ The shape both repos shipped. This is the whole point of the rule."""
    findings = check_run_block(BROKEN)
    assert findings, "the success-path-only shape was accepted"
    assert "only from a CONDITIONAL path" in findings[0], findings


def test_known_good_publishing_at_the_assignment_depth_is_ACCEPTED():
    assert check_run_block(GOOD) == [], check_run_block(GOOD)


def test_a_naive_output_exists_rule_would_pass_the_broken_form():
    """⛔ Pins WHY the rule is structural and not a field lookup.

    If this ever fails because the broken fixture stopped declaring the output, the
    fixture has drifted away from the real defect and must be re-derived — not deleted.
    """
    assert "dseq=" in BROKEN and "GITHUB_OUTPUT" in BROKEN, (
        "the broken fixture no longer even writes the output, so it is no longer the "
        "realistic wrong shape — it has become a strawman"
    )
    assert check_run_block(BROKEN), "the structural rule must still reject it"


# ── The other ways an identity fails to reach a teardown ──────────────────────


def test_never_writing_the_identity_at_all_is_REJECTED():
    findings = check_run_block(
        'DSEQ=$(akash tx deployment create | head -1)\necho "$DSEQ"\n'
    )
    assert findings and "never writes it to $GITHUB_OUTPUT" in findings[0], findings


def test_an_emit_BEFORE_the_assignment_does_not_count():
    """Publishing an empty variable is not publishing the identity."""
    findings = check_run_block(
        'echo "dseq=$DSEQ" >> "$GITHUB_OUTPUT"\nDSEQ=$(akash tx deployment create)\n'
    )
    assert findings, "an emit that precedes the assignment was accepted"


def test_an_exit_between_the_assignment_and_the_emit_does_not_count():
    """⚠ Same nesting depth is not enough if the path can leave before reaching it."""
    findings = check_run_block(
        "DSEQ=$(akash tx deployment create)\n"
        "validate || exit 1\n"
        'echo "dseq=$DSEQ" >> "$GITHUB_OUTPUT"\n'
    )
    assert findings, "an emit unreachable past an `exit` was accepted"


def test_a_brace_group_redirected_to_GITHUB_OUTPUT_counts():
    """`{ echo "dseq=..."; ... } >> "$GITHUB_OUTPUT"` is the other real spelling."""
    assert (
        check_run_block(
            "DSEQ=$(akash tx deployment create)\n"
            "{\n"
            '  echo "dseq=$DSEQ"\n'
            '  echo "provider=$P"\n'
            '} >> "$GITHUB_OUTPUT"\n'
        )
        == []
    )


def test_a_workflow_that_never_provisions_is_OUT_OF_SCOPE():
    """A rule that fired on every workflow would be noise, not a standard."""
    assert check_run_block("echo hello\nmake test\n") == []


# ── Non-vacuity ───────────────────────────────────────────────────────────────


def test_the_fixtures_are_actually_distinguishable():
    """Floor: if both fixtures ever produce the same verdict, every test above is theatre."""
    assert bool(check_run_block(BROKEN)) != bool(check_run_block(GOOD)), (
        "the known-bad and known-good now agree — the rule distinguishes nothing"
    )


def test_findings_name_the_job_and_step_so_the_site_is_findable():
    findings = check_document(_wf(BROKEN))
    assert findings and findings[0].startswith("pool / Deploy:"), findings


@pytest.mark.parametrize("run", [BROKEN, GOOD])
def test_a_document_with_no_jobs_judges_nothing(run):
    assert check_document({"jobs": {}}) == []
    assert check_document({}) == []


# ===========================================================================
# ⛔ A RULE THE ADOPTION SURFACE DOES NOT RUN DOES NOT EXIST.
#
# The conformance action is the single thing a consumer adopts. Measured 2026-08-24: it
# invoked ONLY check_standard.py, so check_pool_owns_teardown, check_dereg_backstop and
# check_reaper_schedule — all merged, all tested — were reachable by nobody. This rule
# must not join them, and it must not be silently unwired later.
# ===========================================================================

ACTION = (
    Path(__file__).resolve().parents[1]
    / ".github/actions/akash-runner-conformance/action.yml"
)


def _action_script() -> str:
    doc = yaml.safe_load(ACTION.read_text())
    steps = doc["runs"]["steps"]
    assert steps, "the conformance action has no steps"
    return "\n".join(str(s.get("run") or "") for s in steps)


def test_the_conformance_action_actually_invokes_this_rule():
    assert "check_teardown_can_identify.py" in _action_script(), (
        "the rule is not wired into the adoption surface, so no consumer runs it"
    )


def test_the_action_does_not_stop_at_the_first_failing_rule():
    """`set -e` would make a consumer fix one rule, re-run, and meet the next.

    Verified behaviourally elsewhere; asserted structurally here so the collect-then-exit
    shape cannot be replaced by a bare sequence that short-circuits.
    """
    script = _action_script()
    assert "|| rc=1" in script and 'exit "$rc"' in script, (
        "the action no longer collects both statuses; a second failing rule would be "
        f"invisible until the first was fixed:\n{script}"
    )
