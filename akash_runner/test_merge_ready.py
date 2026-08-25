"""Adversarial tests for the four merge-ready limbs."""

from __future__ import annotations

from akash_runner.merge_ready import (
    GitHub,
    _latest_records,
    _required_names,
    inspect_pr,
)


class FakeGitHub(GitHub):
    def __init__(self, responses: dict[str, object]) -> None:
        super().__init__("test")
        self.responses = responses
        self.calls: list[tuple[str, dict[str, str]]] = []

    def get(self, path: str, **params: str):  # type: ignore[no-untyped-def]
        self.calls.append((path, params))
        key = path + (
            "?" + "&".join(f"{k}={v}" for k, v in params.items()) if params else ""
        )
        return self.responses[key]

    def graphql(self, query: str, variables: dict):  # type: ignore[no-untyped-def]
        self.calls.append(("graphql", variables))
        return self.responses["graphql"]


def _responses(
    *, jobs: list[dict], check_runs=None, statuses=None, threads=None, runs=None
):
    return {
        "/repos/o/r/pulls/7": {"base": {"ref": "main"}, "head": {"sha": "abc"}},
        "/repos/o/r/branches/main/protection": {
            "required_status_checks": {
                "contexts": ["A1", "tier-coverage"],
                "checks": [],
            }
        },
        "/repos/o/r/commits/abc/check-runs?per_page=100": {
            "check_runs": check_runs or []
        },
        "/repos/o/r/commits/abc/status?per_page=100": {"statuses": statuses or []},
        "graphql": {
            "repository": {"pullRequest": {"reviewThreads": {"nodes": threads or []}}}
        },
        "/repos/o/r/actions/runs?head_sha=abc&per_page=100": {
            "workflow_runs": runs
            if runs is not None
            else [{"id": 1, "path": ".github/workflows/ci.yml"}]
        },
        "/repos/o/r/actions/runs/1/jobs?per_page=100&filter=all": {"jobs": jobs},
    }


def test_latest_per_name_and_status_union_keeps_newest_record():
    latest = _latest_records(
        [
            {
                "name": "B1b",
                "conclusion": "skipped",
                "started_at": "2026-08-25T10:00:00Z",
            },
            {
                "name": "B1b",
                "conclusion": "success",
                "started_at": "2026-08-25T11:00:00Z",
            },
        ],
        [
            {
                "context": "tier-coverage",
                "state": "success",
                "updated_at": "2026-08-25T11:00:00Z",
            }
        ],
    )
    assert latest["B1b"]["state"] == "success"
    assert latest["tier-coverage"]["kind"] == "commit-status"


def test_required_status_and_unresolved_threads_and_jobs_are_independent():
    api = FakeGitHub(
        _responses(
            check_runs=[
                {
                    "name": "A1",
                    "conclusion": "success",
                    "completed_at": "2026-08-25T11:00:00Z",
                }
            ],
            statuses=[
                {
                    "context": "tier-coverage",
                    "state": "skipped",
                    "updated_at": "2026-08-25T11:01:00Z",
                }
            ],
            threads=[{"id": "thread-1", "isResolved": False}],
            jobs=[],
        )
    )
    report = inspect_pr(api, "o/r", 7)
    assert report.required_failures == []  # skipped required context is accepted
    assert report.skipped_required == ["tier-coverage"]
    assert report.unresolved_threads == ["thread-1"]
    assert report.workflow_failures and "zero jobs" in report.workflow_failures[0]
    assert any(
        path.endswith("/jobs") and params.get("filter") == "all"
        for path, params in api.calls
    )


def test_absent_required_and_non_required_failure_are_not_hidden():
    api = FakeGitHub(
        _responses(
            check_runs=[
                {
                    "name": "A1",
                    "conclusion": "success",
                    "completed_at": "2026-08-25T11:00:00Z",
                },
                {
                    "name": "copilot-pull-request-reviewer",
                    "conclusion": "failure",
                    "completed_at": "2026-08-25T11:00:00Z",
                },
            ],
            jobs=[{"name": "test", "conclusion": "success"}],
        )
    )
    report = inspect_pr(api, "o/r", 7)
    assert report.required_failures == ["tier-coverage: ABSENT"]
    assert report.non_required_failures == [
        "copilot-pull-request-reviewer: failure (check-run)"
    ]
    assert report.workflow_failures == []


def test_no_workflow_run_is_a_distinct_fourth_limb_failure():
    api = FakeGitHub(_responses(jobs=[], runs=[]))
    report = inspect_pr(api, "o/r", 7)
    assert report.workflow_failures == ["no workflow run found for the PR head SHA"]


def test_branch_protection_checks_and_legacy_contexts_are_union_deduped():
    assert _required_names(
        {
            "required_status_checks": {
                "contexts": ["A1"],
                "checks": [{"context": "tier-coverage"}, {"context": "A1"}],
            }
        }
    ) == ["A1", "tier-coverage"]


# ── RFC3339 ordering ────────────────────────────────────────────────────────────
#
# ⚠ EVERY FIXTURE BELOW MIXES TIMESTAMP SHAPES ON PURPOSE. A pair that both carry
# fractional seconds — or both omit them — sorts identically whether compared as
# strings or as datetimes, so it passes on the broken implementation. The mixed pair
# is the only one that separates them, and it is the shape GitHub actually emits.

_BARE = "2026-08-25T19:30:43Z"
_FRAC = "2026-08-25T19:30:43.500Z"  # SAME second, 500 ms LATER


def test_a_later_fractional_timestamp_beats_an_earlier_bare_one() -> None:
    """⛔ THE REGRESSION. Lexically `"…43.500Z" >= "…43Z"` is False because
    ord('.')=46 < ord('Z')=90, so the later run loses and a stale state is reported."""
    latest = _latest_records(
        [
            {"name": "ci", "conclusion": "failure", "completed_at": _BARE},
            {"name": "ci", "conclusion": "success", "completed_at": _FRAC},
        ],
        [],
    )
    assert latest["ci"]["state"] == "success", "the later (fractional) run must win"


def test_the_same_ordering_holds_when_the_later_run_is_the_FAILING_one() -> None:
    """⭐ Both directions. A checker that only got the passing case right would still
    report a green from before a required context went red."""
    latest = _latest_records(
        [
            {"name": "ci", "conclusion": "success", "completed_at": _BARE},
            {"name": "ci", "conclusion": "failure", "completed_at": _FRAC},
        ],
        [],
    )
    assert latest["ci"]["state"] == "failure"


def test_arrival_order_does_not_decide_it(_=None) -> None:
    """The later timestamp wins regardless of which arrives first in the list."""
    for order in ([_FRAC, _BARE], [_BARE, _FRAC]):
        runs = [
            {
                "name": "ci",
                "conclusion": "success" if t is _FRAC else "failure",
                "completed_at": t,
            }
            for t in order
        ]
        assert _latest_records(runs, [])["ci"]["state"] == "success"


def test_a_record_with_no_timestamp_loses_to_one_that_has_it() -> None:
    """⚠ Absent/unparseable sorts FIRST via a named sentinel, not via `""`. Preferring
    an undatable record over a dated one is the worse failure."""
    latest = _latest_records(
        [
            {"name": "ci", "conclusion": "success", "completed_at": _BARE},
            {"name": "ci", "conclusion": "failure"},  # no completed_at, no started_at
        ],
        [],
    )
    assert latest["ci"]["state"] == "success"


def test_an_unparseable_timestamp_does_not_raise() -> None:
    latest = _latest_records(
        [{"name": "ci", "conclusion": "success", "completed_at": "not-a-date"}], []
    )
    assert latest["ci"]["state"] == "success"


def test_a_commit_status_still_wins_an_exact_tie_against_a_check_run() -> None:
    """The tie rule is now stated in the docstring; this pins it so a loop reorder
    cannot change it silently."""
    latest = _latest_records(
        [{"name": "ci", "conclusion": "failure", "completed_at": _BARE}],
        [{"context": "ci", "state": "success", "updated_at": _BARE}],
    )
    assert latest["ci"]["kind"] == "commit-status"
