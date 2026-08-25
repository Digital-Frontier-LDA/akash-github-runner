"""A teardown may not be gated on its provisioner's SUCCESS.

⛔ THE DEFECT THIS EXISTS FOR, measured 2026-08-23 in Borduas-Holdings/Blazing-Back
`ci-pr.yml` on origin/main:

    L5149  # Always runs (even on failure/cancel) to prevent leaked deployments.
    L5151  close-akash-runner:
    L5153    if: always() && needs.provision-akash-runner.result == 'success'

A provision that CREATES A LEASE and then fails or is cancelled does not reach
`success`, so its own closer is skipped and the lease outlives the run. Five failures
of this shape across two repos immobilised $449.80 in deposits.

⇒ THE RULE IS ABOUT THE PREDICATE, NOT THE PROSE. An earlier draft required the
docstring to claim always-runs before failing. That is satisfiable by DELETING THE
COMMENT: the fix becomes "stop promising" rather than "start reaping", and the leak
survives with honest documentation. It also cannot be enforced on a repo with no
comments. The rule here reads the predicate alone.

⚠ AND IT MUST NOT REJECT CONJUNCTION GENERALLY. Surveying every always-runs claim in
that file returned exactly two, which is the known-good/known-bad pair used below:

    collect-worker-logs  if: always() && github.event.action != 'closed'   HONEST
    close-akash-runner   if: always() && needs.…result == 'success'        DEFECT

Both are `always() && …`. Only the second gates on a job RESULT. Gating on OUTPUT
PRESENCE (`needs.pool.outputs.dseq != ''`) is the correct way to express "do not close
a lease that was never opened" and stays permitted.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from akash_runner.check_standard import check  # noqa: E402

RESULT_GATED = "teardown must not be gated on its provisioner's result"


def _wf(jobs):
    return {"jobs": jobs}


# ── CHARACTERISATION: pin what the :47 early return governs, BEFORE changing it ──────
# A rule that stops firing looks exactly like a repo that got better. These pin the
# pool-relative rules as UNREACHABLE without a canonical pool, so if the reachability
# change accidentally widens them, it fails here rather than silently.


def test_characterisation_no_pool_still_reports_exactly_that():
    findings = check(_wf({"build": {"runs-on": "ubuntu-latest"}}))
    assert findings == ["no canonical just-akash runner-pool reusable job found"]


def test_characterisation_pool_relative_rules_stay_suppressed_without_a_pool():
    """⚠ The local-duplication rule sits AFTER the early return but OUTSIDE the pool
    loop. Deleting the return alone starts firing it on every non-canonical repo — a
    behaviour change to an existing rule, disguised as a reachability fix. Pinned."""
    findings = check(
        _wf({"provision": {"uses": "./.github/workflows/akash-runner.yml"}})
    )
    assert findings == ["no canonical just-akash runner-pool reusable job found"]
    assert not any("duplicates the shared mechanism" in f for f in findings)


# ── KNOWN-BAD: the two real Blazing-Back predicates ──────────────────────────────────


def test_known_bad_close_akash_runner_as_it_stands_on_main():
    findings = check(
        _wf(
            {
                "provision-akash-runner": {"runs-on": "ubuntu-latest"},
                "close-akash-runner": {
                    "needs": ["provision-akash-runner"],
                    "if": "always() && needs.provision-akash-runner.result == 'success'",
                    "runs-on": "ubuntu-latest",
                },
            }
        )
    )
    assert any(RESULT_GATED in f and "close-akash-runner" in f for f in findings)


def test_known_bad_close_cd_pool_as_it_stands_on_main():
    findings = check(
        _wf(
            {
                "provision-cd-pool": {"runs-on": "ubuntu-latest"},
                "close-cd-pool": {
                    "needs": ["provision-cd-pool"],
                    "if": "always() && needs.provision-cd-pool.result == 'success'",
                    "runs-on": "ubuntu-latest",
                },
            }
        )
    )
    assert any(RESULT_GATED in f and "close-cd-pool" in f for f in findings)


# ── KNOWN-GOOD: all three must pass, or the rule catches nothing ─────────────────────


def test_known_good_1439_fixed_predicate():
    for job in ("close-akash-runner", "close-cd-pool"):
        findings = check(
            _wf(
                {
                    "provision": {"runs-on": "x"},
                    job: {"needs": ["provision"], "if": "always()"},
                }
            )
        )
        assert not any(RESULT_GATED in f for f in findings), (
            f"{job} flagged after the fix"
        )


def test_known_good_just_akash_182_internalised_teardown():
    findings = check(
        _wf(
            {
                "pool": {"runs-on": "x"},
                "teardown": {
                    "needs": ["pool"],
                    "if": "${{ always() }}",
                    "runs-on": "x",
                },
            }
        )
    )
    assert not any(RESULT_GATED in f for f in findings)


def test_known_good_output_presence_gate_is_permitted():
    """★ The legitimate form of "do not close a lease that was never opened" — and the
    thing ci-pr.yml:159's comment currently uses the DEFECT to justify."""
    findings = check(
        _wf(
            {
                "pool": {"runs-on": "x"},
                "teardown": {
                    "needs": ["pool"],
                    "if": "always() && needs.pool.outputs.dseq != ''",
                    "runs-on": "x",
                },
            }
        )
    )
    assert not any(RESULT_GATED in f for f in findings)


def test_known_good_non_teardown_job_is_not_in_scope():
    """★ KNOWN-NEGATIVE for the job selector. `collect-worker-logs` is result-gated in
    spirit elsewhere in that file; a rule that flags every job is not a teardown rule."""
    findings = check(
        _wf(
            {
                "build": {"runs-on": "x"},
                "smoke-single": {
                    "needs": ["build"],
                    "if": "always() && needs.build.result == 'success'",
                    "runs-on": "x",
                },
            }
        )
    )
    assert not any(RESULT_GATED in f for f in findings)


def test_every_allowlist_entry_states_a_reason():
    """★ An exception with no stated reason is indistinguishable from someone quietly
    turning the rule off — the failure mode the C5 addendum was written to prevent."""
    from akash_runner.check_standard import RESULT_GATE_ALLOWLIST

    for job, reason in RESULT_GATE_ALLOWLIST.items():
        assert isinstance(reason, str) and len(reason.strip()) >= 20, (
            f"allowlist entry {job!r} must carry a substantive reason, got {reason!r}"
        )


def test_the_allowlist_actually_suppresses_and_is_therefore_load_bearing():
    """★ KNOWN-POSITIVE for the escape hatch: if it never suppressed anything, a future
    exception would be silently ineffective and someone would delete the rule instead."""
    import akash_runner.check_standard as cs

    jobs = {
        "provision": {"runs-on": "x"},
        "close-thing": {"if": "always() && needs.provision.result == 'success'"},
    }
    assert cs._result_gated_teardowns(jobs), (
        "known-bad did not fire; the test proves nothing"
    )
    cs.RESULT_GATE_ALLOWLIST["close-thing"] = (
        "documented exception for the purposes of this test"
    )
    try:
        assert not cs._result_gated_teardowns(jobs)
    finally:
        cs.RESULT_GATE_ALLOWLIST.pop("close-thing", None)
