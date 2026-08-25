"""Existence is not coverage: a backstop must reap what the repo actually creates.

`check_dereg_backstop` was promoted to ENFORCING on a clean five-consumer sweep, and two of
those five were leaking while green. It asks whether a scheduled dereg EXISTS; it never
asks whether that dereg covers the prefixes the repo EMITS.

★ Cross-validated against an artifact written weeks earlier by other means: #145's own
producer table records blazing as `akash-integration-* yes · akash-ci-* NONE · akash-* NONE`,
and this rule reports exactly those two gaps.
"""

from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from akash_runner.check_backstop_covers_producers import check_directory  # noqa: E402

PRODUCER = """
on: {workflow_call: {}}
jobs:
  pool:
    runs-on: ubuntu-latest
    steps:
      - run: |
          cat > sdl.yaml <<EOF
                - RUNNER_NAME_PREFIX=demo-${RUNNER_LABEL}
          EOF
"""


def _reaper(filter_expr: str, trigger: str = 'schedule: [{cron: "0 * * * *"}]') -> str:
    return (
        "\non:\n  " + trigger + "\njobs:\n  reap:\n    runs-on: ubuntu-latest\n"
        "    steps:\n      - run: |\n"
        '          gh api "orgs/$ORG/actions/runners" --jq \'.runners[] '
        + filter_expr
        + ' | select(.status=="offline") | .id\' > ids\n'
        '          for id in $(cat ids); do gh api -X DELETE "orgs/$ORG/actions/runners/$id"; done\n'
    )


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


# ── the core question ─────────────────────────────────────────────────────────


def test_known_bad_a_backstop_that_filters_a_DIFFERENT_prefix(tmp_path):
    """★★ blazing's and Blazing-Back's real shape: a reaper that reaps someone else."""
    findings = _repo(
        tmp_path,
        {
            "pool.yml": PRODUCER,
            "reap.yml": _reaper('| select(.name|startswith("other-"))'),
        },
    )
    assert findings, "an uncovered producer was accepted"
    assert "demo-" in findings[0] and "pool.yml" in findings[0], findings


def test_known_good_a_backstop_that_filters_what_is_emitted(tmp_path):
    assert (
        _repo(
            tmp_path,
            {
                "pool.yml": PRODUCER,
                "reap.yml": _reaper('| select(.name|startswith("demo-"))'),
            },
        )
        == []
    )


def test_the_finding_names_the_PRODUCER_file_not_just_the_repo(tmp_path):
    """ "this repo leaks" is not actionable; "pool.yml emits demo- and nothing reaps it" is."""
    findings = _repo(
        tmp_path,
        {"pool.yml": PRODUCER, "reap.yml": _reaper('| select(.name|startswith("x-"))')},
    )
    assert findings[0].startswith("pool.yml:"), findings


# ── the forms a backstop takes. Each one handled ALONE looks like handling it. ──


def test_an_EXPORTED_backstop_declares_its_coverage(tmp_path):
    """just-akash's shape: a library repo cannot schedule, so it exports with name-prefixes.

    ⚠ Handling only the SCHEDULED form reported just-akash — whose coverage is correct and
    complete — as leaking. Third time this shape bit, inside the rule written about it.
    """
    exporter = (
        "\non:\n  workflow_call: {}\njobs:\n  reap:\n"
        "    uses: Digital-Frontier-LDA/df-cicd/.github/workflows/reusable-stale-runner-reaper.yml@"
        + "a"
        * 40
        + "\n"
        "    with:\n      name-prefixes: demo-\n"
    )
    assert _repo(tmp_path, {"pool.yml": PRODUCER, "export.yml": exporter}) == []


def test_a_SCRIPT_delegated_filter_counts(tmp_path):
    """blazing's shape: the filter lives in scripts/, not in run: text."""
    wf = '\non:\n  schedule: [{cron: "0 * * * *"}]\njobs:\n  reap:\n    runs-on: ubuntu-latest\n    steps:\n      - run: bash scripts/reap.sh\n'
    script = (
        "#!/usr/bin/env bash\n"
        'gh api "orgs/$ORG/actions/runners" --jq \'.runners[] | select(.name|startswith("demo-")) | .id\'\n'
        'gh api -X DELETE "/orgs/$ORG/actions/runners/$ID"\n'
    )
    assert (
        _repo(
            tmp_path,
            {"pool.yml": PRODUCER, "reap.yml": wf},
            {"scripts/reap.sh": script},
        )
        == []
    )


def test_a_SCHEDULED_reaper_with_NO_name_filter_covers_everything(tmp_path):
    """It reaps every offline runner in the org. Whether that is SAFE is another rule's job."""
    assert _repo(tmp_path, {"pool.yml": PRODUCER, "reap.yml": _reaper("")}) == []


def test_known_bad_a_PER_RUN_teardown_is_NOT_blanket_coverage(tmp_path):
    """⛔ A `workflow_call` dereg with no name filter cleans up after the run that invoked
    it — nothing else. Counting it as covering everything made Blazing-Back PASS on the
    strength of akash-close.yml while runner-time-to-ready.yml emitted an unreaped prefix.
    """
    findings = _repo(
        tmp_path,
        {
            "pool.yml": PRODUCER,
            "teardown.yml": _reaper("", trigger="workflow_call: {}"),
        },
    )
    assert findings, "a per-run teardown was treated as blanket coverage"


# ── extraction must not compute coverage from noise ───────────────────────────


def test_a_startswith_that_is_not_a_NAME_filter_is_ignored(tmp_path):
    """⚠ A bare `startswith` scan over the real repos returns http, #, v0.2, akash1 and a
    dozen more. Anchoring on `.name` is what stops coverage being computed from noise."""
    noisy = _reaper('| select(.url|startswith("demo-"))')
    findings = _repo(tmp_path, {"pool.yml": PRODUCER, "reap.yml": noisy})
    assert findings, "a non-.name startswith was counted as a runner-name filter"


# ── scope and non-vacuity ────────────────────────────────────────────────────


def test_a_repo_with_no_producers_is_out_of_scope(tmp_path):
    assert (
        _repo(tmp_path, {"reap.yml": _reaper('| select(.name|startswith("x-"))')}) == []
    )


def test_an_empty_directory_judges_nothing(tmp_path):
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    assert check_directory(wf) == []


def test_the_fixtures_are_actually_distinguishable(tmp_path):
    """Floor: if covered and uncovered ever agree, every test above is theatre."""
    a = _repo(
        tmp_path / "a",
        {"pool.yml": PRODUCER, "r.yml": _reaper('| select(.name|startswith("demo-"))')},
    )
    b = _repo(
        tmp_path / "b",
        {"pool.yml": PRODUCER, "r.yml": _reaper('| select(.name|startswith("nope-"))')},
    )
    assert bool(a) != bool(b), (a, b)
