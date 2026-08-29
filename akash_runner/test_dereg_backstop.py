"""Controls for "a repo registering org runners must run a scheduled dereg backstop".

⛔ THE MEASURED LOOP: Borduas-Holdings carried 3,025 org runner registrations (2,900
offline+idle, 53 online, 0 busy) against Digital-Frontier's 1. `runner-pool.yml` polls
`orgs/{org}/actions/runners --paginate`, so each poll costs ceil(3025/100) = 31 calls.
Stale registrations raise the poll cost, the core budget empties, the provisioner goes
blind, runners are orphaned, and the count rises again. Positive feedback, every term
measured. What was missing is a DRAIN.
"""

from __future__ import annotations

import sys

import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from akash_runner.check_dereg_backstop import check_directory  # noqa: E402

POOL = """
on:
  workflow_call:
jobs:
  pool:
    runs-on: ubuntu-latest
    steps:
      - run: |
          gh api --paginate "orgs/${ORG}/actions/runners?per_page=100" | jq .
          # ⚠ A LISTING READ NO LONGER PUTS A REPO IN SCOPE — it is what a REAPER does
          # too, and scoping on it made the rule fail df-cicd for shipping the reaper.
          # These fixtures always MEANT "a repo that registers runners"; they merely
          # expressed it with a signal that turns out not to mean that. The env below
          # is the creation act.
          #   - RUNNER_SCOPE=org
          #   - RUNNER_NAME_PREFIX=fixture-
"""

PER_RUN_DEREG = """
on:
  workflow_call:
jobs:
  teardown:
    runs-on: ubuntu-latest
    steps:
      - run: |
          IDS=$(gh api --paginate "orgs/${ORG}/actions/runners?per_page=100" \\
                | jq -r '.runners[] | select(.status=="offline") | .id')
          for id in $IDS; do gh api -X DELETE "orgs/${ORG}/actions/runners/${id}"; done
"""

SCHEDULED_SAFE = PER_RUN_DEREG.replace(
    "on:\n  workflow_call:",
    'on:\n  schedule:\n    - cron: "41 */6 * * *"\n  workflow_dispatch:',
)
SCHEDULED_UNSAFE = SCHEDULED_SAFE.replace(' | select(.status=="offline")', "")


def _dir(tmp_path, **files):
    for name, text in files.items():
        (tmp_path / name).write_text(text)
    return check_directory(tmp_path)


def test_known_bad_org_runners_registered_with_only_per_run_cleanup(tmp_path):
    """★ just-akash @origin/main: exactly two workflows de-register, NEITHER scheduled."""
    findings = _dir(
        tmp_path, **{"runner-pool.yml": POOL, "runner-teardown.yml": PER_RUN_DEREG}
    )
    assert findings and "no workflow performs a SCHEDULED" in findings[0]


def test_known_good_a_scheduled_offline_filtered_reaper_satisfies_it(tmp_path):
    findings = _dir(
        tmp_path,
        **{
            "runner-pool.yml": POOL,
            "runner-teardown.yml": PER_RUN_DEREG,
            "reap-offline-runners.yml": SCHEDULED_SAFE,
        },
    )
    assert findings == []


def test_an_unsafe_reaper_is_a_HAZARD_and_does_not_satisfy_the_rule(tmp_path):
    """★★ THE close-orphans TRAP, avoided. A rule demanding "a scheduled dereg" and nothing
    more is satisfiable by a workflow that de-registers EVERY runner, including one mid-job
    — making the rule the cause of a worse outage than it prevents.

    An unsafe reaper must fail BOTH ways: flagged as a hazard, AND not counted toward the
    requirement. If it merely failed the hazard check while satisfying the requirement,
    removing the filter would trade one finding for a destroyed running job."""
    findings = _dir(
        tmp_path, **{"runner-pool.yml": POOL, "reap-all.yml": SCHEDULED_UNSAFE}
    )
    assert any("without filtering to one of the two safe predicates" in f for f in findings)
    assert any("no workflow performs a SCHEDULED" in f for f in findings), (
        "an unsafe reaper satisfied the backstop requirement — the rule would demand a hazard"
    )


def test_a_repo_that_does_not_register_org_runners_is_out_of_scope(tmp_path):
    """★ KNOWN-NEGATIVE: this rule must not demand a runner reaper of every repository."""
    assert (
        _dir(
            tmp_path,
            **{
                "ci.yml": "on:\n  push:\njobs:\n  t:\n    steps:\n      - run: pytest\n"
            },
        )
        == []
    )


def test_a_per_run_dereg_alone_is_not_a_backstop(tmp_path):
    """★★ THE DISTINCTION THE LOOP TURNS ON. Per-run cleanup is correct and insufficient:
    it cannot drain registrations left by runs that were throttled or killed before reaching
    it. `runner-teardown.yml` does its job properly and the count still reached 3,025."""
    findings = _dir(
        tmp_path, **{"runner-pool.yml": POOL, "runner-teardown.yml": PER_RUN_DEREG}
    )
    assert findings, "a per-run dereg was accepted as a backstop"


def test_an_unreadable_workflow_is_reported_not_skipped(tmp_path):
    """★ Otherwise a repo looks compliant because its only backstop failed to parse."""
    (tmp_path / "reap-broken.yml").write_text("this: [is: not: valid")
    findings = check_directory(tmp_path)
    assert findings and "was NOT checked" in findings[0]


def test_the_yaml_boolean_on_key_is_handled(tmp_path):
    """★ A bare `on:` parses as True, not "on" — read naively, the scheduled reaper looks
    trigger-less and the known-good would fail."""
    findings = _dir(
        tmp_path,
        **{"runner-pool.yml": POOL, "reap-offline-runners.yml": SCHEDULED_SAFE},
    )
    assert findings == [], "the boolean-key trap is unhandled: a real known-good failed"


# ===========================================================================
# ADOPTION. Until #145 there was nothing to adopt, so this rule looked only for a
# LOCAL `-X DELETE`. Once the reusable reaper shipped, the DELETE lived in df-cicd
# and a consumer that wired it CORRECTLY still failed the rule demanding it.
#
# Measured on just-akash before this change: FAIL with no backstop, and STILL FAIL
# with a correct sha-pinned `uses:` in place. A rule that fails the compliant path
# teaches consumers to write another repo-local reaper — the exact divergence the
# standard exists to prevent.
# ===========================================================================

# Repointed with df-cicd#191: the df-cicd copy is deleted, so a fixture built on its path
# would exercise a route no consumer can take and no longer proves anything about adoption.
CANONICAL = (
    "Digital-Frontier-LDA/akash-github-runner/.github/workflows/reusable-stale-runner-reaper.yml"
)
RETIRED_DF_CICD = (
    "Digital-Frontier-LDA/df-cicd/.github/workflows/reusable-stale-runner-reaper.yml"
)
SHA = "5d82c5973e01b0067e61e7b65ab97579aed5ffd9"

PRODUCER = """
on: {workflow_call: {}}
jobs:
  pool:
    runs-on: ubuntu-latest
    steps:
      - run: |
          gh api "orgs/$ORG/actions/runners?per_page=100"
          # RUNNER_SCOPE=org  RUNNER_NAME_PREFIX=fixture-   (the creation act; see POOL)
"""


def _adopting(ref, scheduled=True):
    trigger = 'schedule: [{cron: "0 * * * *"}]' if scheduled else "workflow_call: {}"
    return (
        "\non:\n  "
        + trigger
        + "\njobs:\n  reap:\n    uses: "
        + CANONICAL
        + "@"
        + ref
        + "\n    with:\n      org: some-org\n      name-prefixes: some-\n"
    )


def _adopt_dir(tmp_path, reaper_text):
    return _dir(tmp_path, **{"pool.yml": PRODUCER, "reap.yml": reaper_text})


def test_known_good_a_scheduled_sha_pinned_adoption_satisfies_the_rule(tmp_path):
    """The case that FAILED before this change while being exactly right."""
    assert _adopt_dir(tmp_path, _adopting(SHA)) == []


def test_known_bad_an_unpinned_adoption_fails_BOTH_ways(tmp_path):
    """A tag moves, so behaviour can change with no commit here.

    It must be REPORTED and must NOT count — otherwise the rule degrades to "mention
    the reaper somewhere" and the pin quietly stops being enforced.
    """
    findings = _adopt_dir(tmp_path, _adopting("main"))
    assert any("not a 40-hex commit" in f for f in findings), findings
    assert any("no workflow performs a SCHEDULED" in f for f in findings), (
        f"an unpinned adoption was still counted toward the requirement: {findings}"
    )


def test_known_bad_a_moving_TAG_is_not_a_pin_either(tmp_path):
    """`@v2.7.1` reads as immutable and is not — df-cicd's own usage example shows it."""
    findings = _adopt_dir(tmp_path, _adopting("v2.7.1"))
    assert any("not a 40-hex commit" in f for f in findings), findings


def test_known_bad_a_pinned_call_to_SOME_OTHER_workflow_is_not_adoption(tmp_path):
    """Otherwise any pinned `uses:` at all would satisfy a de-registration rule."""
    other = _adopting(SHA).replace(
        CANONICAL, "Someone-Else/other/.github/workflows/nope.yml"
    )
    findings = _adopt_dir(tmp_path, other)
    assert any("no workflow performs a SCHEDULED" in f for f in findings), findings


def test_an_UNSCHEDULED_adoption_does_not_satisfy_the_rule_yet(tmp_path):
    """A `workflow_call` wrapper EXPORTS a backstop; it does not RUN one.

    ⚠ Deliberately still a FAIL, and it is the state just-akash#186 is in — a library
    repo holds neither the PAT nor the org, so it cannot schedule. Expressing "the
    obligation transfers to the caller" is a separate rule; until that exists this must
    not silently pass, because an unscheduled reaper drains nothing.
    """
    findings = _adopt_dir(tmp_path, _adopting(SHA, scheduled=False))
    assert any("no workflow performs a SCHEDULED" in f for f in findings), findings


def test_a_step_level_uses_is_not_a_reusable_workflow_call(tmp_path):
    """An action cannot de-register; only a job-level `uses:` reaches a reusable workflow."""
    step_level = (
        '\non:\n  schedule: [{cron: "0 * * * *"}]\njobs:\n  reap:\n    runs-on: ubuntu-latest\n'
        "    steps:\n      - uses: " + CANONICAL + "@" + SHA + "\n"
    )
    findings = _adopt_dir(tmp_path, step_level)
    assert any("no workflow performs a SCHEDULED" in f for f in findings), findings


# ===========================================================================
# EXPORT. A library repo registers runners on behalf of its CALLERS: it holds no PAT
# and cannot know the org, so a cron there authenticates with an empty secret against
# a guessed org — a backstop that reaps nothing and reports success.
#
# ⚠ The exemption must be VERIFIED, never claimed, or "library repo" becomes an opt-out
# anybody asserts by deleting their cron. The dodge tests below are the whole point:
# a repo that converts its scheduled reaper to `workflow_call` still fails, because it
# still holds the credential or still names the org.
# ===========================================================================

EXPORTER = (
    "\non:\n  workflow_call:\n    inputs:\n      github-org:\n        required: true\n"
    "        type: string\n    secrets:\n      GH_RUNNER_PAT:\n        required: true\n"
    "jobs:\n  reap:\n    uses: " + CANONICAL + "@" + SHA + "\n"
    "    with:\n      org: ${{ inputs.github-org }}\n      name-prefixes: some-\n"
    "    secrets:\n      runner-pat: ${{ secrets.GH_RUNNER_PAT }}\n"
)


def test_known_good_a_library_repo_that_EXPORTS_the_backstop_satisfies_it(tmp_path):
    """★ just-akash#186's exact shape: callable, caller-supplied org AND credential."""
    assert _adopt_dir(tmp_path, EXPORTER) == []


def test_known_bad_the_DODGE_hard_coding_the_org(tmp_path):
    """Knowing the org means it could have scheduled itself, so it must."""
    dodge = EXPORTER.replace("org: ${{ inputs.github-org }}", "org: my-actual-org")
    findings = _adopt_dir(tmp_path, dodge)
    assert any("hard-codes org" in f for f in findings), findings
    assert any("no workflow performs a SCHEDULED" in f for f in findings), (
        f"the dodge was accepted as an export: {findings}"
    )


def test_known_bad_the_DODGE_handing_over_its_OWN_repo_secret(tmp_path):
    """Holding the credential means it could have scheduled itself, so it must."""
    dodge = EXPORTER.replace(
        "    secrets:\n      GH_RUNNER_PAT:\n        required: true\n", ""
    )
    findings = _adopt_dir(tmp_path, dodge)
    assert any("OWN secret" in f for f in findings), findings
    assert any("no workflow performs a SCHEDULED" in f for f in findings), findings


def test_known_bad_an_exporter_that_passes_no_secret_cannot_authenticate(tmp_path):
    dodge = EXPORTER.replace(
        "    secrets:\n      runner-pat: ${{ secrets.GH_RUNNER_PAT }}\n", ""
    )
    findings = _adopt_dir(tmp_path, dodge)
    assert any("passes no secret" in f for f in findings), findings


def test_known_bad_neither_scheduled_nor_callable_is_not_an_export(tmp_path):
    """`workflow_dispatch` only: nothing will ever run it on its own."""
    orphan = EXPORTER.replace(
        "on:\n  workflow_call:\n    inputs:\n      github-org:\n        required: true\n"
        "        type: string\n    secrets:\n      GH_RUNNER_PAT:\n        required: true\n",
        "on:\n  workflow_dispatch: {}\n",
    )
    findings = _adopt_dir(tmp_path, orphan)
    assert any("neither scheduled nor callable" in f for f in findings), findings


def test_an_export_does_not_excuse_an_UNSAFE_local_reaper(tmp_path):
    """The export discharges the CADENCE obligation, never the busy-safety one."""
    findings = _dir(
        tmp_path,
        **{"pool.yml": PRODUCER, "reap.yml": EXPORTER, "unsafe.yml": SCHEDULED_UNSAFE},
    )
    assert any("without filtering to one of the two safe predicates" in f for f in findings), findings


# ===========================================================================
# THE ESCAPED QUOTE. A jq program inside a DOUBLE-quoted shell string is written
# `select(.status == \"offline\")`. The original OFFLINE_FILTER demanded a bare `"`,
# so it missed that spelling — and reported Blazing-Back/akash-close.yml:167, which
# DOES filter offline, as a busy-safety hazard. Through the same code path it also
# refused to count the workflow toward the requirement: two false findings against a
# repo doing it right, from one missing `\?`.
#
# ⇒ The rule committed the defect the rule is about: reporting on the SPELLING it
# expected rather than the PROPERTY it claims to check.
# ===========================================================================

_SAFE_SPELLINGS = [
    'select(.status == "offline")',
    'select(.status == \\"offline\\")',
    "select(.status == 'offline')",
    '.status=="offline"',
    '.status==\\"offline\\"',
]


@pytest.mark.parametrize("selector", _SAFE_SPELLINGS)
def test_every_safe_offline_spelling_is_recognised(tmp_path, selector):
    reaper = (
        '\non:\n  schedule: [{cron: "0 * * * *"}]\njobs:\n  reap:\n    runs-on: ubuntu-latest\n'
        "    steps:\n      - run: |\n"
        '          IDS=$(gh api "orgs/$ORG/actions/runners" --jq \'.runners[] | '
        + selector
        + " | .id')\n"
        '          for id in $IDS; do gh api -X DELETE "orgs/$ORG/actions/runners/$id"; done\n'
    )
    findings = _dir(tmp_path, **{"pool.yml": PRODUCER, "reap.yml": reaper})
    assert findings == [], (
        f"{selector!r} was not recognised as an offline filter: {findings}"
    )


@pytest.mark.parametrize(
    "selector", ['select(.status == "online")', 'select(.status == \\"online\\")']
)
def test_an_online_selector_is_still_a_hazard_however_it_is_quoted(tmp_path, selector):
    """The widened pattern must not have started accepting the unsafe predicate."""
    reaper = (
        '\non:\n  schedule: [{cron: "0 * * * *"}]\njobs:\n  reap:\n    runs-on: ubuntu-latest\n'
        "    steps:\n      - run: |\n"
        '          IDS=$(gh api "orgs/$ORG/actions/runners" --jq \'.runners[] | '
        + selector
        + " | .id')\n"
        '          for id in $IDS; do gh api -X DELETE "orgs/$ORG/actions/runners/$id"; done\n'
    )
    findings = _dir(tmp_path, **{"pool.yml": PRODUCER, "reap.yml": reaper})
    assert any("without filtering to one of the two safe predicates" in f for f in findings), findings


# ===========================================================================
# THE SECOND SAFE PREDICATE: `busy == false`. The original rule demanded ONLY the
# offline spelling — a true premise with a false "only". Offline filters out 100% of the
# live leak's busy half AND 100% of the live leak's online-and-busy half, but the live
# leak is overwhelmingly the OTHER half: `online AND busy=false`, a starved runner
# printing "Listening for Jobs". Measured 2026-08-25 by
# reference_the_leak_metric_is_online_and_idle_not_offline: of 144 live leaks, 119 (83%)
# are online+idle — invisible to every offline-only reaper.
#
# `busy == false` is the STRICTLY BETTER conjunct: it misses 0% of the live leak (the
# starved runners are exactly `online AND busy=false`) AND never selects a busy runner
# (the rule's whole point — see the module docstring).
#
# ⚠ The relaxation must not have removed the guard. Proving both directions:
#   • every `busy == false` spelling is recognised (positive)
#   • every `busy == true`  spelling is still a hazard (negative)
#   • a reaper with NO safety conjunct at all is still a hazard (TEAMLEAD's known-positive)
# ===========================================================================

_BUSY_FALSE_SPELLINGS = [
    'select(.busy == false)',
    'select(.busy==false)',
    '.busy == false',
    '.busy==false',
    # NOTE: `busy == false` and `busy==false` (without a leading `.`) are deliberately
    # NOT in this list. A bare `busy` in jq is a VARIABLE reference, not a field access,
    # and the relaxation must not widen the rule to admit variable references. The new
    # regex's mandatory `\.` enforces the field-access reading.
]


# KNOWN-NEGATIVES. The bypass the FIRST iteration of SAFE_FILTER allowed: a longer
# identifier ending in `busy` (e.g., `.notbusy`, `.reallybusy`) contains the substring
# `busy == false`, and a regex without a word-boundary will match it. The fix makes the
# `.` MANDATORY and adds a `(?<![A-Za-z0-9_])` negative lookbehind, so these are no
# longer matched. Each of these is a reaper that adds ONE CHARACTER to a field name
# and was wrongly accepted as safe. Pre-2026-08-26 they all passed; they must all fail.
_NOT_BUSY_NEGATIVES = [
    'select(.notbusy == false)',
    'select(.reallybusy == false)',
    'select(.busy_actually == false)',
    'select(.busyman == false)',
    'select(.mybusy == false)',
]


_BUSY_TRUE_SPELLINGS = [
    'select(.busy == true)',
    'select(.busy==true)',
    '.busy == true',
    '.busy==true',
]


def _make_reaper_with_selector(selector: str) -> str:
    return (
        '\non:\n  schedule: [{cron: "0 * * * *"}]\njobs:\n  reap:\n    runs-on: ubuntu-latest\n'
        "    steps:\n      - run: |\n"
        '          IDS=$(gh api "orgs/$ORG/actions/runners" --jq \'.runners[] | '
        + selector
        + " | .id')\n"
        '          for id in $IDS; do gh api -X DELETE "orgs/$ORG/actions/runners/$id"; done\n'
    )


@pytest.mark.parametrize("selector", _BUSY_FALSE_SPELLINGS)
def test_every_safe_busy_false_spelling_is_recognised(tmp_path, selector):
    """The post-relaxation positive case. Each `busy == false` spelling must pass."""
    reaper = _make_reaper_with_selector(selector)
    findings = _dir(tmp_path, **{"pool.yml": PRODUCER, "reap.yml": reaper})
    assert findings == [], (
        f"{selector!r} was not recognised as a busy==false filter: {findings}"
    )


@pytest.mark.parametrize("selector", _BUSY_TRUE_SPELLINGS)
def test_a_busy_true_selector_is_still_a_hazard(tmp_path, selector):
    """The post-relaxation negative case. The unsafe TWIN must remain flagged.

    If the relaxation started accepting `busy == true`, every busy runner — including
    one mid-job — would be selected, and the rule would have manufactured the defect
    it exists to stop. This test pins that direction.
    """
    reaper = _make_reaper_with_selector(selector)
    findings = _dir(tmp_path, **{"pool.yml": PRODUCER, "reap.yml": reaper})
    assert any("without filtering to one of the two safe predicates" in f for f in findings), (
        f"{selector!r} was accepted as a safe filter — the relaxation removed the guard: {findings}"
    )


@pytest.mark.parametrize("selector", _NOT_BUSY_NEGATIVES)
def test_a_longer_identifier_containing_busy_is_NOT_recognised(tmp_path, selector):
    """★ THE BYPASS THE FIRST DRAFT INTRODUCED, regression-locked.

    An earlier draft of SAFE_FILTER used `\\.?\\s*busy\\s*==\\s*false`, making the dot
    optional — so `select(.notbusy == false)` and `select(.reallybusy == false)`
    matched, because the SUBSTRING `busy == false` is present inside a longer
    identifier. Measured 2026-08-26 by CodeRabbit on #25: an unsafe reaper adds ONE
    CHARACTER to a field name and satisfies the safety rule.

    The fix makes the `.` MANDATORY and adds a `(?<![A-Za-z0-9_])` negative lookbehind.
    This test enumerates the family of bypasses — longer identifiers ending in `busy`,
    with either case transitions or word characters — and asserts every one is still
    flagged as a hazard. If the fix regresses, a regex change has either re-introduced
    the optional `\.?` or dropped the lookbehind, and this test fires.

    The mirror of `reference_underscore_is_a_word_character_so_b_misses_identifiers`:
    there a regex boundary was too STRICT and missed tokens; here there was no boundary
    at all and matched too MUCH.
    """
    reaper = _make_reaper_with_selector(selector)
    findings = _dir(tmp_path, **{"pool.yml": PRODUCER, "reap.yml": reaper})
    assert any("without filtering to one of the two safe predicates" in f for f in findings), (
        f"{selector!r} was accepted as a safe filter — a longer identifier containing "
        f"`busy` slipped through; the `.` is no longer mandatory or the word-boundary "
        f"lookbehind regressed. Findings: {findings}"
    )


def test_a_reaper_with_NO_safety_conjunct_at_all_is_a_hazard(tmp_path):
    """★ KNOWN-POSITIVE THE RELAXATION MUST NOT HAVE REMOVED.

    A scheduled workflow that DELETEs against runners without any predicate at all
    reaps everything, including mid-job. The relaxation — accepting `busy == false` in
    addition to `status == "offline"` — must not have widened the rule so far that an
    UNFILTERED reaper now passes. Proves both directions: positive (the right filters
    ARE recognised), negative (the absence of any filter is still a hazard), AND that
    the absence does NOT count toward the requirement.

    If your relaxation makes this test pass, you have removed the guard rather than
    corrected it.
    """
    reaper = (
        '\non:\n  schedule: [{cron: "0 * * * *"}]\njobs:\n  reap:\n    runs-on: ubuntu-latest\n'
        "    steps:\n      - run: |\n"
        '          IDS=$(gh api "orgs/$ORG/actions/runners" --jq \'.runners[] | .id\')\n'
        '          for id in $IDS; do gh api -X DELETE "orgs/$ORG/actions/runners/$id"; done\n'
    )
    findings = _dir(tmp_path, **{"pool.yml": PRODUCER, "reap.yml": reaper})
    assert any("without filtering to one of the two safe predicates" in f for f in findings), (
        f"an unfiltered reaper was accepted: {findings}"
    )
    assert any("no workflow performs a SCHEDULED" in f for f in findings), (
        f"an unsafe reaper was counted toward the backstop requirement: {findings}"
    )


# ===========================================================================
# ⛔ TOUCHING THE ORG RUNNER API IS NOT REGISTERING RUNNERS.
#
# The old predicate was `orgs/.../actions/runners`, which the reaper df-cicd PUBLISHES
# matches on all four of its own lines — three listing GETs and its own DELETE. The rule
# concluded that the repo shipping the backstop needed a backstop, and that false positive
# is why it shipped ADVISORY rather than ENFORCING.
#
# ⚠ A PATTERN TWEAK CANNOT FIX IT: the DELETE is genuinely present in both a registrar and
# a reaper, and only the surrounding ROLE differs. The discriminator asks a different
# question — does this repo CREATE registrations?
#
# ⚠ AND `registration-token` IS NOT THAT DISCRIMINATOR, though it is the obvious guess:
# measured 0 in all three repos, because the runner IMAGE mints the token, not the
# workflow. A rule built on it scopes NOBODY and passes EVERYONE.
# ===========================================================================

REAPER_ONLY = """
on:
  schedule: [{cron: "0 * * * *"}]
jobs:
  reap:
    runs-on: ubuntu-latest
    steps:
      - run: |
          gh api --paginate "orgs/$ORG/actions/runners?per_page=100" --jq '.runners[] | select(.status=="offline") | .id' > ids
          for id in $(cat ids); do gh api -X DELETE "orgs/$ORG/actions/runners/$id"; done
"""

REGISTRAR = """
on: {workflow_call: {}}
jobs:
  pool:
    runs-on: ubuntu-latest
    steps:
      - run: |
          cat > sdl.yaml <<EOF
          services:
            runner:
              image: ghcr.io/akash-network/github-runner:latest
              env:
                - ACCESS_TOKEN=$GH_RUNNER_PAT
                - RUNNER_SCOPE=org
                - RUNNER_NAME_PREFIX=demo-
          EOF
"""


def test_a_repo_that_only_REAPS_is_not_in_scope(tmp_path):
    """★★ df-cicd's own shape. It ships the reaper; it registers nothing."""
    assert _dir(tmp_path, **{"reaper.yml": REAPER_ONLY}) == []


def test_a_repo_that_REGISTERS_and_never_reaps_is_in_scope(tmp_path):
    findings = _dir(tmp_path, **{"pool.yml": REGISTRAR})
    assert any("registers org runners" in f for f in findings), findings


def test_the_DELETE_alone_never_puts_a_repo_in_scope(tmp_path):
    """⛔ The whole point: the DELETE is present in BOTH roles, so it discriminates nothing."""
    delete_only = REAPER_ONLY.replace(
        'schedule: [{cron: "0 * * * *"}]', "workflow_dispatch: {}"
    )
    assert _dir(tmp_path, **{"d.yml": delete_only}) == [], (
        "a workflow that only de-registers was treated as one that registers"
    )


def test_registration_token_alone_would_have_scoped_nobody(tmp_path):
    """Pins the measurement that killed the obvious design.

    If a future edit makes `registration-token` the sole signal, the REGISTRAR fixture —
    which mints nothing itself, exactly like the real ones — stops being in scope.
    """
    assert "registration-token" not in REGISTRAR
    assert _dir(tmp_path, **{"pool.yml": REGISTRAR}), (
        "the registrar fixture must be in scope WITHOUT minting a token itself"
    )


# ===========================================================================
# ⛔ A REAPER THAT DELEGATES TO A SCRIPT IS STILL A REAPER.
#
# blazing's akash-runner-registration-reaper.yml is scheduled and its only step is
# `bash scripts/akash-runner-reaper.sh`. The listing, the offline filter and the DELETE all
# live in that script. Reading only `run:` text reported a repo with a WORKING backstop as
# having none — the same delegation blindness #146 fixed for `uses:`, in a second form.
# ===========================================================================

DELEGATING_REAPER = """
on:
  schedule: [{cron: "13 * * * *"}]
jobs:
  reap:
    runs-on: ubuntu-latest
    steps:
      - run: bash scripts/reap.sh
"""

REAPER_SCRIPT = """#!/usr/bin/env bash
IDS=$(gh api --paginate "orgs/${ORG}/actions/runners?per_page=100" \\
  --jq '.runners[] | select(.status=="offline") | .id')
for ID in $IDS; do gh api -X DELETE "/orgs/${ORG}/actions/runners/${ID}"; done
"""


def _repo(tmp_path, workflows: dict, scripts: dict | None = None):
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    for name, text in workflows.items():
        (wf / name).write_text(text)
    for rel, text in (scripts or {}).items():
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    return check_directory(wf)


def test_a_script_delegated_reaper_SATISFIES_the_requirement(tmp_path):
    """★★ blazing's shape. The backstop works; only the checker could not see it."""
    findings = _repo(
        tmp_path,
        {"pool.yml": REGISTRAR, "reaper.yml": DELEGATING_REAPER},
        {"scripts/reap.sh": REAPER_SCRIPT},
    )
    assert findings == [], findings


def test_a_delegated_script_that_does_NOT_dereg_still_fails(tmp_path):
    """The delegation must be followed, not assumed to contain a reaper."""
    findings = _repo(
        tmp_path,
        {"pool.yml": REGISTRAR, "reaper.yml": DELEGATING_REAPER},
        {"scripts/reap.sh": "#!/usr/bin/env bash\necho 'nothing to see'\n"},
    )
    assert any("no workflow performs a SCHEDULED" in f for f in findings), findings


def test_a_dotted_script_path_resolves(tmp_path):
    """⚠ `.lstrip('./')` strips ANY leading dot or slash, so `.github/x.sh` became
    `github/x.sh` and never resolved. Caught by false findings against four real repos."""
    wf = DELEGATING_REAPER.replace(
        "bash scripts/reap.sh", "bash .github/scripts/reap.sh"
    )
    findings = _repo(
        tmp_path,
        {"pool.yml": REGISTRAR, "reaper.yml": wf},
        {".github/scripts/reap.sh": REAPER_SCRIPT},
    )
    assert findings == [], findings


def test_an_ABSOLUTE_host_path_is_not_a_repo_script(tmp_path):
    """⚠ Blazing-Back runs `/home/pentest/.guardian/run-engagement.sh` — a file on the
    RUNNER, which cannot exist at check time and is not a backstop. Treating it as an
    unreadable delegation turned a host-path invocation into a dereg finding."""
    wf = DELEGATING_REAPER.replace(
        "bash scripts/reap.sh", "bash /home/someone/.tools/thing.sh"
    )
    findings = _repo(tmp_path, {"reaper.yml": wf})
    assert not any("could not be read" in f for f in findings), findings


def test_an_unreadable_repo_script_in_a_SCHEDULED_workflow_is_reported(tmp_path):
    """Unreadable is not empty — but only where it could change the answer."""
    findings = _repo(tmp_path, {"pool.yml": REGISTRAR, "reaper.yml": DELEGATING_REAPER})
    assert any("could not be read" in f for f in findings), findings


def test_an_unreadable_script_in_an_UNSCHEDULED_workflow_is_not_a_dereg_finding(
    tmp_path,
):
    """⚠ Otherwise every telemetry and install helper becomes a de-registration finding —
    measured: 3 such on just-akash and 1 on df-cicd, none of them about reaping."""
    unscheduled = DELEGATING_REAPER.replace(
        'schedule: [{cron: "13 * * * *"}]', "workflow_dispatch: {}"
    )
    findings = _repo(tmp_path, {"noise.yml": unscheduled})
    assert not any("could not be read" in f for f in findings), findings


# ===========================================================================
# The canonical reaper moved to THIS repo (#31/#34). Before that change this
# rule recognised only df-cicd's path, so a consumer that adopted the copy the
# workflow itself calls canonical was reported non-compliant. These fail on the
# old constant.
# ===========================================================================

from akash_runner.check_dereg_backstop import CANONICAL_USES  # noqa: E402

AGR_CANONICAL = (
    "Digital-Frontier-LDA/akash-github-runner"
    "/.github/workflows/reusable-stale-runner-reaper.yml"
)


def _exporter_calling(path: str) -> str:
    return (
        "\non:\n  workflow_call:\n    inputs:\n      github-org:\n"
        "        type: string\n        required: true\n"
        "    secrets:\n      runner-pat:\n        required: true\n"
        "jobs:\n  reap:\n"
        f"    uses: {path}@" + "a" * 40 + "\n"
        "    with:\n      org: ${{ inputs.github-org }}\n"
        "    secrets:\n      runner-pat: ${{ secrets.runner-pat }}\n"
    )


def test_this_repos_reaper_is_accepted_as_canonical():
    """A consumer adopting THIS repo's reaper must satisfy the backstop rule.

    On the old constant only df-cicd's path matched, so the correct adoption
    matched nothing and the repo was judged as having no backstop at all."""
    assert CANONICAL_USES.search(f"{AGR_CANONICAL}@" + "a" * 40) is not None


def test_the_retired_df_cicd_path_is_no_longer_canonical():
    """The migration is complete, so the deleted path must stop granting the exemption.

    This test REPLACES test_df_cicd_path_still_accepted_during_migration, which pinned the
    opposite and was correct while it stood: dropping the entry early would have stripped
    just-akash's exporter exemption before it repointed, marking it non-compliant for doing
    the right thing. The guard fired when I tried exactly that — 10 tests red — and the
    sequence was corrected to agr#37 -> just-akash#226 -> df-cicd#191 -> here.

    Now that df-cicd#191 has deleted the file, the danger inverts: the exemption is a text
    match that never checks the target exists, so keeping the path listed would grant a
    backstop exemption for a `uses:` pointing at nothing."""
    retired = (
        "Digital-Frontier-LDA/df-cicd"
        "/.github/workflows/reusable-stale-runner-reaper.yml"
    )
    assert CANONICAL_USES.search(f"{retired}@" + "a" * 40) is None, (
        "df-cicd's reaper was deleted in df-cicd#191; accepting its path would grant the "
        "dereg-backstop exemption to a consumer pointing at a file that does not exist"
    )


def test_an_exporter_naming_the_RETIRED_path_is_not_exempt(tmp_path):
    """END-TO-END: the exemption must actually be DENIED, not merely unmatched by a regex.

    ⛔ The two tests below assert REGEX behaviour — that `CANONICAL_USES` does or does not
    match a string. That is necessary and not sufficient: it proves the constant changed,
    not that a repo exporting the retired path loses its backstop exemption. A refactor
    could keep the regex correct and still grant the exemption by another route.

    Raised in cross-model review of #42 (codex-1): "proves only regex behavior — not
    end-to-end rejection of a retired-path exporter."
    """
    retired_exporter = EXPORTER.replace(AGR_CANONICAL, RETIRED_DF_CICD)
    assert RETIRED_DF_CICD in retired_exporter, (
        "fixture did not substitute — this test would otherwise exercise the LIVE path "
        "and pass for the wrong reason"
    )
    findings = _adopt_dir(tmp_path, retired_exporter)
    assert findings, (
        "a repo whose only backstop is an export naming the RETIRED df-cicd reaper must "
        "not be exempt — that file was deleted in df-cicd#191, so the exemption would be "
        "granted for a `uses:` pointing at nothing"
    )


def test_the_surviving_canonical_path_is_still_accepted():
    """ANTI-VACUITY: the test above must not pass because the matcher stopped matching."""
    live = (
        "Digital-Frontier-LDA/akash-github-runner"
        "/.github/workflows/reusable-stale-runner-reaper.yml"
    )
    assert CANONICAL_USES.search(f"{live}@" + "a" * 40) is not None, (
        "the canonical path must still be accepted — if this fails, the previous test is "
        "passing because CANONICAL_USES matches nothing at all"
    )


def test_a_lookalike_third_party_path_is_not_canonical():
    """Anti-vacuity: the alternation must not have widened into a substring match."""
    assert (
        CANONICAL_USES.search(
            "someone-else/akash-github-runner"
            "/.github/workflows/reusable-stale-runner-reaper.yml@" + "a" * 40
        )
        is None
    )
