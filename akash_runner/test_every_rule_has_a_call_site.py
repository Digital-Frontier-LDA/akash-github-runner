"""Every rule in this package must have a call site, or a stated reason it does not.

⛔ MEASURED 2026-08-24: `check_pool_owns_teardown`, `check_dereg_backstop` and
`check_reaper_schedule` were merged, tested, and invoked by NOBODY. The conformance action
— the single thing a consumer adopts — ran only `check_standard.py`. A green conformance
check certified one quarter of the standard and read as certifying all of it.

★ THEIR PASSING TEST SUITES ARE WHAT MADE IT INVISIBLE. A rule with green tests reads as
live. **A test proves the rule WORKS; only the call site proves it RUNS.** Every other
signal we had — merged, reviewed, tested, documented — was present and true, and none of
them is evidence that a consumer ever executes the thing.

⇒ THIS MODULE IS THE FIX. Wiring the three rules clears the backlog; only this stops the
fourth from being merged into the dark next week. If you are adding a rule and this test
fails, that is the test doing its job: wire it into the action, or list it below with a
reason and the condition that would change it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
ACTION = ROOT / ".github/actions/akash-runner-conformance/action.yml"
RULES_DIR = ROOT / "akash_runner"

# Rules whose failure FAILS the consumer's build.
ENFORCING = {
    # ⛔ ENFORCING FROM THE START, DELIBERATELY — the usual advisory-then-promote path is
    # skipped here because the blast radius was MEASURED BEFORE wiring, which is what the
    # promotion sweep exists to establish:
    #     just-akash  origin/main -> FAIL, exactly 2 sites (runner-pool.yml:398,
    #                                sdl/github-runner-probe.yaml:73) — both real
    #     just-akash  #215 branch -> PASS (the fix satisfies the rule)
    #     Blazing-Back            -> PASS (59 files) despite owning a guard whose grep and
    #                                ::error both NAME the variable
    # That last one caught a false positive in the rule's first draft, which matched the
    # bare identifier and flagged the detection code as the defect.
    #
    # Advisory would have been the wrong state: this is the rule that would have stopped
    # the 2026-08-26 outage, and check_runner_image_digest_floor sat advisory (#154) doing
    # exactly that — detecting the condition, exiting 1, and being swallowed into a green
    # conformance run.
    "check_disable_auto_update_absent.py",
    "check_standard.py",
    "check_teardown_can_identify.py",
    # Promoted from ADVISORY 2026-08-24 — see the sweep recorded in #154.
    "check_dereg_backstop.py",
    # Promoted from ADVISORY 2026-08-24. Its condition was "every consumer's emitted
    # prefixes are covered by its backstop, BY ANY ROUTE, or the gap is accepted in
    # writing." Measured met: blazing PASS (21 files), Blazing-Back PASS (56 files) —
    # both by renaming producers onto a covered stem rather than widening a reaper,
    # the outcome the STATE-not-remedy rewrite (#161) was made to admit. See #157.
    "check_backstop_covers_producers.py",
    # Promoted from ADVISORY 2026-08-24 (#163). Its condition was "every current
    # consumer's workflows-dir has been scanned and every finding is either fixed
    # or exempted-with-a-reason — i.e. the rule's blast radius across consumers is
    # zero-unexplained, not merely unmeasured." Measured met: DigitalFrontier-infra
    # PASS (56 workflows), Borduas-Holdings/blazing PASS (21 workflows, fresh
    # sparse clone), df-cicd PASS (25 workflows, own workflows-dir) — zero
    # findings, zero exemptions. Known-positive synthetic workflow with
    # `${{ job.workflow_sha }}` exits 1, proving the rule is not inert. Both real
    # measured instances (#182 github.organization, #184 job.workflow_sha /
    # job.workflow_repository) predate this rule, so the known-positive is
    # synthetic — but the rule's blast radius across the named consumer set is
    # zero-unexplained, which is what the condition named. Precedent: #162, which
    # was promoted on the same shape (blazing 21 PASS + Blazing-Back 56 PASS +
    # known-positive exit 1).
    "check_context_properties_exist.py",
}

# ⚠ INVOKED, REPORTED, AND NOT YET FAILING THE BUILD. Each entry states WHY it is not
# enforced and WHAT WOULD CHANGE THAT — because "advisory" without a promotion condition
# is just a quieter version of the defect this module exists to catch. An advisory rule
# nobody ever promotes has a call site and still enforces nothing.
ADVISORY: dict[str, str] = {
    "check_escrow_reaper_is_adopted.py": (
        "ADVISORY because it FAILS BOTH IN-SCOPE CONSUMERS TODAY, and that is the finding "
        "rather than a defect in the rule. Blast radius RE-MEASURED 2026-08-30 after the "
        "comment-stripping fix, which CHANGED THE POPULATION: "
        "DigitalFrontier-infra -> FAIL (akash-runner.yml, runner-time-to-ready.yml), "
        "just-akash -> FAIL (provider-canary.yml), "
        "akash-github-runner -> NOT APPLICABLE, "
        "df-wiki -> NOT APPLICABLE. "
        "⚠ agr WAS COUNTED AS FAILING IN THE FIRST MEASUREMENT AND THAT WAS WRONG: the "
        "only `just-akash deploy` in this repo is df-akash-gate.yml:75, a COMMENTED-OUT "
        "sketch of a future design. The rule read its own comments as evidence; fixing that "
        "moved this repo out of scope, so the honest count is 2 of 2, not 3 of 3. "
        "⛔ The rule is correct and the fleet is not compliant yet -- the canonical workflow "
        "landed with it, so no consumer has had a SHA to pin, and adoption additionally "
        "needs the mechanism's placement-prefix parameter (just-akash #230) or it would be "
        "INERT: a consumer stamping `dfci-infra-` swept under the default `just-akash-` "
        "matches nothing and reports 0 forever while this rule reads green. "
        "PROMOTE WHEN: both in-scope repos adopt it at a pinned SHA with a placement-prefix "
        "this rule can see them stamp -- at that point it passes everywhere and this "
        "exemption's own reason stops being true."
    ),
    "check_provisioning_is_delegated.py": (
        "ADVISORY because it FAILS TWO CURRENT CONSUMERS TODAY, by design. Standard §1 "
        "mandates that runner provisioning live ONLY in just-akash, consumed via `uses:` at "
        "a pinned tag, and NOTHING enforced it — the gap was in the RULE SET, not in uptake: "
        "Blazing-Back already runs this suite cross-org at a pin level with main and still "
        "violates §1. Blast radius MEASURED 2026-08-29 by running the rule against each "
        "workflows dir directly: blazing FAIL (>=3 — akash-ci.yml, akash-integration-new.yml, "
        "akash-runner.yml; a FLOOR, measured over 6 of its 23 workflows); Blazing-Back FAIL "
        "(2 — akash-runner.yml AND runner-time-to-ready.yml, the second of which a "
        "filename-keyed check could never surface); df-cicd, akash-github-runner and df-wiki "
        "NOT-JUDGEABLE (exit 3 — they provision nothing, which is not a pass). "
        "⚠ THE PROMOTION CONDITION NAMES THE PIN, because the obvious phrasing is "
        "UNSATISFIABLE: a consumer pinned at a SHA predating this rule cannot go green by "
        "fixing its workflows, since the rule it would be judged by is not in its pin. "
        "PROMOTE WHEN: (a) blazing and Blazing-Back have moved provisioning behind "
        "`uses: <owner>/just-akash/.github/workflows/runner-pool.yml@<tag>`, AND (b) both "
        "have moved their conformance pin to a SHA containing this rule. Either half alone "
        "leaves the promotion unreachable."
    ),
    "check_listing_failure_is_loud.py": (
        "ADVISORY because it FAILS A CURRENT CONSUMER TODAY, by design. Measured "
        "2026-08-29 by running the rule against each workflows dir directly: "
        "akash-github-runner PASS (rc=0, NON-VACUOUS — 1 workflow actually reads the org "
        "listing); just-akash PASS (rc=0, NON-VACUOUS — 2 workflows); df-cicd FAIL "
        "(rc=1, 1 finding) because its FORK of reusable-stale-runner-reaper.yml still "
        "swallows the listing. The two files are byte-identical apart from 8 comment "
        "lines, so it is the same defect this PR fixes here. "
        "⚠ THE PROMOTION CONDITION NAMES THE PIN, because the obvious phrasing is "
        "UNSATISFIABLE: df-cicd pins the checker at a SHA PREDATING this file, so 'goes "
        "green on df-cicd' cannot be reached by fixing df-cicd alone — the rule is ABSENT "
        "at the SHA it executes. Same unreachable shape already recorded for "
        "check_conformance_pin_agrees_with_checker_ref.py. "
        "PROMOTE WHEN: df-cicd's `uses:@sha` AND `checker-ref` have both advanced to a SHA "
        "CONTAINING this file, AND its reaper's listing captures the exit status, AND the "
        "rule has reported OK (not NOT-JUDGEABLE) on a real conformance run there. "
        "⚠ Blazing-Back and blazing are OUT OF SCOPE at any tier: cross-org, unreachable "
        "by this suite, and blazing's live hourly reaper carries this exact defect in "
        "scripts/akash-runner-reaper.sh — a shell script, not a workflow, so widening the "
        "rule would not catch it either."
    ),
    "check_conformance_pin_agrees_with_checker_ref.py": (
        "ADVISORY because it CANNOT YET RUN ON ANY CONSUMER. Both consumers pin the "
        "checker at 6ba4316, which PREDATES this rule, so it is absent at the SHA they "
        "execute — the same absence that made three other rules unreachable and was "
        "fixed by hand in df-cicd#186 and just-akash#209. Enforcing a rule nobody runs "
        "would be a promotion on paper. "
        "⚠ Its promotion condition therefore NAMES that dependency instead of assuming "
        "it away: a condition of the form 'goes green on a consumer' is UNSATISFIABLE "
        "while the consumer pins a SHA without the rule, and one was filed in exactly "
        "that unreachable form earlier today. "
        "PROMOTE WHEN: a consumer's `uses:@sha` AND `checker-ref` have both advanced to "
        "a SHA that CONTAINS this file, AND the rule has reported OK (not NOT-JUDGEABLE) "
        "on at least one real conformance run there. Blast radius already measured at "
        "zero across all four repos: just-akash OK, df-cicd OK, akash-github-runner and "
        "Blazing-Back NOT-JUDGEABLE (no caller)."
    ),
    "check_teardown_cannot_be_silenced.py": (
        "ADVISORY until every consumer has been scanned. It currently finds exactly ONE "
        'instance repo-wide -- df-akash-gate.yml:82, `[ -n "${DSEQ:-}" ] && just-akash '
        'close "$DSEQ" 2>/dev/null || true` -- which is a genuine guaranteed no-op: there '
        "is no just-akash package on PyPI, so the install two lines up (also silenced) has "
        "never placed a binary, and the shell shape exits 0 in all three failure modes. "
        "Mutation-verified on three limbs, each killed by its own known-negative. "
        "⚠ What is NOT measured is its false-positive rate across the OTHER consumers "
        "(Blazing-Back, blazing, just-akash), which carry far more teardown code than "
        "df-cicd does. `|| true` is correct on a diagnostic, and a rule that reds a "
        "correct design trains readers to dismiss it. "
        "PROMOTE WHEN: every consumer workflows-dir has been scanned and every finding is "
        "TRUE and either fixed or exempted-with-a-reason -- an untrue finding is a defect "
        "in the RULE and is never exemptible."
    ),
    "check_gate_is_not_re_derived.py": (
        "ADVISORY until a consumer actually adopts the capacity primitive. Blast radius "
        "MEASURED across three trees today with the capacity gate: DigitalFrontier-infra "
        "56 workflows 0 findings, df-cicd 26 workflows 0 findings, akash-github-runner 4 "
        "workflows 0 findings — zero-unexplained, not merely unmeasured. Non-vacuity "
        "proven two ways: a synthetic node-allocatable derivation fires with "
        "`ignores-the-autoscaler-ceiling`, and a real-shaped `kubectl get pods` + "
        "requests computation fires — so the zero above is a measurement, not an inert "
        "rule. "
        "⚠ TWO FALSE POSITIVES WERE MEASURED AND FIXED BEFORE THIS LANDED, both on "
        "Blazing-Back's ci-pr.yml canary-deploy, and both are pinned as regression "
        "fixtures. (1) The exemption was matched against the `run:` block alone, so a job "
        "consuming the primitive through `needs.<job>.outputs.*` bound in a step `env:` "
        "was flagged — and that is the SAFE two-job design specifically, the one that "
        "stops a broken preflight from skipping a required check. Exemption is now a JOB "
        "property closed over `needs:`, and deliberately not file-level. (2) A bare "
        "`resources.requests` read matched a yq assignment AUTHORING a manifest "
        '(`.resources.requests.cpu = "100m"`); it now requires co-occurrence with an '
        "actual cluster query. ⛔ The second was nearly invisible: with the preflight "
        "wired the job became needs-exempt, so the rule went green and the before/after "
        "read like proof it worked. Only printing the MATCH showed the finding was never "
        "real. "
        "PROMOTE WHEN: at least one consumer routes a capacity decision through "
        "df-cicd's gke-capacity-preflight action and this rule has gone green on that "
        "consumer's conformance run — shown to PASS on a real adopter, not merely to "
        "fail on non-adopters. Blazing-Back#1620 is the candidate adopter."
    ),
    "check_funding_gate_is_not_re_derived.py": (
        "ADVISORY because it FAILS A CURRENT CONSUMER TODAY, by design: Blazing-Back's "
        "akash-runner.yml decides funding in inline shell and carries all four measured "
        "defects — a rate projected from two samples 60s apart (30/39 sampled intervals "
        "were FLAT and every delta an exact multiple of 5.00 ACT, so ~24% of prechecks "
        "refuse on the artefact), a gate on Console deploy_credit which does not gate a "
        "create, and a three-way floor disagreement (5M/6M/12M) on a variable read in "
        "three places and set in none. Enforcing now would red every consumer's runner "
        "workflow before the primitive is wired anywhere. "
        "PROMOTE WHEN: at least one consumer routes its funding decision through "
        "akash-lease-core's evaluate_funding and this rule has gone green on that "
        "consumer's conformance run — i.e. the rule has been shown to PASS on a real "
        "adopter, not merely to fail on non-adopters."
    ),
    "check_pool_owns_teardown.py": (
        "Its premise — 'an empty identity is a safe no-op' — is a property of the TEARDOWN, "
        "and it splits across consumers: true for just-akash (runner-teardown.yml:140 "
        "no-ops on an empty DSEQ), false for Blazing-Back (ci_close_akash_deployment.sh:43 "
        "exits 1). Enforcing now fails a repo that is correct today. PROMOTE WHEN: every "
        "consumer's close path no-ops on an empty identity."
    ),
    "check_schedule_inputs_are_empty.py": (
        "ADVISORY until one consumer has adopted it. Blazing-Back's cleanup-stale-akash.yml "
        "carried exactly this defect (DRY_RUN: ${{ github.event.inputs.dry_run || 'false' }} "
        "on a 6-hourly cron, so the unattended path closed for real) and is fixed there, but "
        "no consumer INVOKES this rule yet and enforcing a rule nobody has run against their "
        "own workflows breaks CI for a defect they have not been shown. "
        "PROMOTE WHEN: one consumer's conformance run has gone green on it, so the rule is "
        "known to pass a repo that is actually correct rather than merely to fail a bad one."
    ),
    "check_funding_projection_is_quantised.py": (
        "⚠ Its corpus is workflow_corpus.run_blocks, shared with "
        "check_funding_gate_is_not_re_derived — neither rule owns the other's corpus. "
        "It previously windowed the RAW FILE in 60-line slices. "
        "ADVISORY until its blast radius across every consumer is measured. The rule's "
        "SHAPE is sound: the known-positive is the REAL two-sample projection measured in "
        "DigitalFrontier-infra's akash-runner.yml on 2026-08-24 ('fell 5.00 ACT in 60s "
        "(26.29 -> 21.29) ... projected at +300s = -3.71 ACT'), and it is mutation-verified "
        "in BOTH directions — an inert mutant fails the two known-positives, an over-firing "
        "mutant fails the diagnostic-series known-negative. The underlying measurement is a "
        "40-sample series showing 30 of 39 intervals FLAT with every delta an integer "
        "multiple of one 5.00 ACT deposit, so the allowance is a step function and a fitted "
        "rate is not a property it has. What is NOT measured is how many consumer workflows "
        "sample an allowance twice for legitimate reasons the three known-negatives do not "
        "model. A rule that reds a gate its author considers correct breaks the consumer for "
        "a defect they have not been shown. "
        "⛔ AMENDED (#171). The original criterion said every finding must be 'either "
        "fixed or exempted-with-a-reason', which converts a FALSE POSITIVE into PRECEDENT: "
        "nothing is wrong, so it cannot be fixed, so it gets exempted, and the exemption "
        "permanently encodes a defect in the rule as an accepted finding about the "
        "consumer. Three false positives were then measured — it fired on a workflow whose "
        "four tokens lived only in a COMMENT, on four tokens split across four SEPARATE "
        "JOBS, and it could not detect its own source artefact at all. "
        "PROMOTE WHEN: every consumer's workflows-dir (Blazing-Back, blazing, just-akash, "
        "df-cicd itself) has been scanned, and every finding is TRUE and either fixed or "
        "exempted-with-a-reason. A finding that is not true is a defect in the RULE and is "
        "never exemptible — blast radius zero-unexplained, not merely unmeasured."
    ),
    "check_unvalidated_default.py": (
        "ADVISORY until it has judged real consumer workflows. Two measured instances in "
        "DigitalFrontier-infra today (akash-runner.yml:328 MIN_UACT, ci-pr.yml:4747 "
        "MIN_AGE_HOURS) — both numeric-threshold sites where ${VAR:-default} substitutes "
        "ONLY on unset/empty and passes a non-numeric value straight through. The rule's "
        "known-positives and known-negatives are concrete (akash-runner.yml:887 MIN_POOL is "
        "the regex-validated negative), so its shape is sound; its false-positive rate on "
        "the FULL set of consumers (Blazing-Back, blazing, just-akash, df-cicd itself) is "
        "not yet measured, and a rule that fires on a workflow that the repo's author "
        "considers correct breaks the consumer for a defect they have not been shown. "
        "PROMOTE WHEN: every current consumer's workflows-dir has been scanned and every "
        "finding is either fixed or exempted-with-a-reason — i.e. the rule's blast radius "
        "across consumers is zero-unexplained, not merely unmeasured."
    ),
    "check_test_pins_a_literal.py": (
        "ADVISORY until the defect class is bounded by measured false positives. Three "
        "regressions measured in one day (just-akash #184 job.workflow_sha pinned in the "
        "assertion body, df-cicd #149 caller-relative path pinned in the assertion body, "
        "DEVOPS blank-prefix control pinned the wrong conjunct), all sharing the shape "
        "`test asserts MECHANISM while message describes PROPERTY`. The rule's scope is "
        "deliberately narrow: it flags only where the body pins a `uses:` path / `${{ }}` "
        "expression / context-property literal AND the message or docstring names a "
        "property AND the message does NOT use precision words (`exactly`, `must equal`, "
        "`must reference`). A rule that fires on fixture-style assertions gets switched "
        "off in a week; the precision-word filter is what keeps the blast radius bounded. "
        "PROMOTE WHEN: every consumer's test files have been scanned advisory and every "
        "finding is either fixed or accepted-with-a-reason — i.e. the rule's hit-rate on "
        "legitimate fixture assertions is zero-unexplained, not merely unmeasured."
    ),
    "check_pool_not_before_consumers.py": (
        "ADVISORY while consumer workflows are being swept. It catches the liveness "
        "hole introduced when a pool receives ordering `needs` without an explicit "
        "status-check function; the known-positive is Blazing-Back's provision-cd-pool "
        "at bc3819e30. PROMOTE WHEN: every consumer's pool jobs have an explicit "
        "!cancelled() policy and remaining always() warnings are dispositioned."
    ),
    "check_runner_image_digest_floor.py": (
        "ADVISORY until each consumer's runner image inventory has been measured. It "
        "requires immutable digests and a supported version floor; the known-positive "
        "is Blazing-Back's 2.336.0 digest at akash-runner.yml:852 and "
        "runner-time-to-ready.yml:150. PROMOTE WHEN: all consumer references have "
        "been audited and any below-floor deployment path has a runtime fail-fast."
    ),
    "check_reaper_schedule.py": (
        "Same — repo-scoped, blast radius unmeasured. PROMOTE WHEN: it has run advisory "
        "across the consumer set and the findings are either fixed or accepted."
    ),
}

# Rules deliberately NOT invoked at all. Empty on purpose: today every rule has a call
# site. An entry here needs a reason that a reader can falsify, not a note that it is fine.
NOT_INVOKED: dict[str, str] = {
    "check_sibling_prefix_collisions.py": (
        "It is an ORG-LEVEL AUDIT over SEVERAL repos, and the conformance action judges ONE. "
        "A collision is a relation BETWEEN repos: measured 2026-08-24, Blazing-Back and "
        "blazing BOTH emit the same prefix, so from inside either one a filter on it selects "
        "a prefix that repo genuinely owns — and also the sibling's. Nothing in one checkout "
        "distinguishes them. Wiring it per-consumer would make it assert a property it "
        "structurally cannot evaluate, which is the defect this standard exists to remove. "
        "Run it over the checkouts named in CONSUMERS.md instead. INVOKE WHEN: the action "
        "gains a way to see more than one repo, which today it has no reason to."
    ),
}


def _rule_files() -> list[str]:
    return sorted(p.name for p in RULES_DIR.glob("check_*.py"))


def _action_script() -> str:
    document = yaml.safe_load(ACTION.read_text())
    steps = document["runs"]["steps"]
    assert steps, "the conformance action declares no steps"
    return "\n".join(str(step.get("run") or "") for step in steps)


def _invoked() -> set[str]:
    """Rule filenames the action actually names in a command."""
    script = _action_script()
    return {
        name for name in _rule_files() if re.search(rf"\b{re.escape(name)}\b", script)
    }


# --------------------------------------------------------------------------- #
# Non-vacuity first. A green over an empty rule set is exactly the defect.
# --------------------------------------------------------------------------- #


def test_rules_are_actually_discovered() -> None:
    rules = _rule_files()
    assert len(rules) >= 5, (
        f"found only {rules} — if the glob or the layout moved, every assertion below "
        "passes over an empty population, which is the failure this module is about"
    )


def test_the_action_script_is_actually_read() -> None:
    script = _action_script()
    assert "check_standard.py" in script, (
        "the action script came back without the one invocation we know is there — the "
        "parse is wrong and every 'invoked' verdict below is meaningless"
    )


# --------------------------------------------------------------------------- #
# The rule.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("rule", _rule_files())
def test_every_rule_is_invoked_or_listed_with_a_reason(rule: str) -> None:
    """★★ THE FIX. A rule that is neither called nor explained is a rule in the dark."""
    if rule in NOT_INVOKED:
        assert NOT_INVOKED[rule].strip(), (
            f"{rule} is listed as not-invoked with a BLANK reason"
        )
        return
    assert rule in _invoked(), (
        f"{rule} exists in akash_runner/ but the conformance action never invokes it, and "
        f"it is not listed in NOT_INVOKED with a reason. It has passing tests and no call "
        f"site — which is exactly how three rules stayed invisible for weeks. Wire it into "
        f".github/actions/akash-runner-conformance/action.yml, or list it with a reason."
    )


@pytest.mark.parametrize("rule", _rule_files())
def test_every_invoked_rule_declares_whether_it_ENFORCES(rule: str) -> None:
    """Advisory must be a DECLARED state, not an accident of how the line was written.

    Otherwise a rule can be invoked, never fail anything, and look wired.
    """
    if rule in NOT_INVOKED:
        return
    assert (rule in ENFORCING) != (rule in ADVISORY), (
        f"{rule} must be listed in exactly one of ENFORCING or ADVISORY. Being invoked is "
        f"not the same as being enforced, and a rule that is quietly advisory forever has "
        f"a call site and still enforces nothing."
    )


@pytest.mark.parametrize("rule", sorted(ADVISORY))
def test_every_advisory_rule_states_what_would_promote_it(rule: str) -> None:
    """⚠ 'Temporary' needs a definition or it is permanent."""
    reason = ADVISORY[rule]
    assert "PROMOTE WHEN:" in reason, (
        f"{rule} is advisory with no promotion condition. Without one, 'not yet enforced' "
        f"is indistinguishable from 'never will be'."
    )


def test_the_lists_do_not_name_rules_that_no_longer_exist() -> None:
    """A stale entry silently exempts nothing and hides that the rule was deleted."""
    known = set(_rule_files())
    for label, listing in (
        ("ENFORCING", ENFORCING),
        ("ADVISORY", set(ADVISORY)),
        ("NOT_INVOKED", set(NOT_INVOKED)),
    ):
        stale = sorted(listing - known)
        assert not stale, f"{label} names rules that do not exist: {stale}"


def test_enforcing_rules_are_wired_so_their_failure_fails_the_build() -> None:
    """`|| rc=1` is what makes a rule enforcing; `advisory ...` is what makes it not."""
    script = _action_script()
    for rule in sorted(ENFORCING):
        assert re.search(rf"{re.escape(rule)}\"?\s+.*\|\|\s*rc=1", script), (
            f"{rule} is listed ENFORCING but the action does not propagate its failure "
            f"into the exit status — it would run, report, and change nothing."
        )


def test_a_skipped_repo_scoped_rule_says_so_rather_than_passing_silently() -> None:
    """⛔ A rule that reports nothing when skipped is indistinguishable from one that passed.

    That silence is precisely what let three rules stay invisible.
    """
    script = _action_script()
    assert "were NOT run" in script and "SKIPPED, not passed" in script, (
        "the action no longer announces that the repo-scoped rules were skipped when "
        f"`workflows-dir` is absent:\n{script}"
    )
