"""Adversarial tests for the four merge-ready limbs."""

from __future__ import annotations

from akash_runner.merge_ready import GitHub, _latest_records, _required_names, inspect_pr


class FakeGitHub(GitHub):
    def __init__(self, responses: dict[str, object]) -> None:
        super().__init__("test")
        self.responses = responses
        self.calls: list[tuple[str, dict[str, str]]] = []

    def get(self, path: str, **params: str):  # type: ignore[no-untyped-def]
        self.calls.append((path, params))
        key = path + ("?" + "&".join(f"{k}={v}" for k, v in params.items()) if params else "")
        return self.responses[key]

    def graphql(self, query: str, variables: dict):  # type: ignore[no-untyped-def]
        self.calls.append(("graphql", variables))
        return self.responses["graphql"]


def _responses(*, jobs: list[dict], check_runs=None, statuses=None, threads=None, runs=None):
    return {
        "/repos/o/r/pulls/7": {"base": {"ref": "main"}, "head": {"sha": "abc"}},
        "/repos/o/r/branches/main/protection": {
            "required_status_checks": {"contexts": ["A1", "tier-coverage"], "checks": []}
        },
        "/repos/o/r/commits/abc/check-runs?per_page=100": {"check_runs": check_runs or []},
        "/repos/o/r/commits/abc/status?per_page=100": {"statuses": statuses or []},
        "graphql": {"repository": {"pullRequest": {"reviewThreads": {"nodes": threads or []}}}},
        "/repos/o/r/actions/runs?head_sha=abc&per_page=100": {
            "workflow_runs": runs if runs is not None else [{"id": 1, "path": ".github/workflows/ci.yml"}]
        },
        "/repos/o/r/actions/runs/1/jobs?per_page=100&filter=all": {"jobs": jobs},
    }


def test_latest_per_name_and_status_union_keeps_newest_record():
    latest = _latest_records(
        [
            {"name": "B1b", "conclusion": "skipped", "started_at": "2026-08-25T10:00:00Z"},
            {"name": "B1b", "conclusion": "success", "started_at": "2026-08-25T11:00:00Z"},
        ],
        [{"context": "tier-coverage", "state": "success", "updated_at": "2026-08-25T11:00:00Z"}],
    )
    assert latest["B1b"]["state"] == "success"
    assert latest["tier-coverage"]["kind"] == "commit-status"


def test_required_status_and_unresolved_threads_and_jobs_are_independent():
    api = FakeGitHub(
        _responses(
            check_runs=[{"name": "A1", "conclusion": "success", "completed_at": "2026-08-25T11:00:00Z"}],
            statuses=[{"context": "tier-coverage", "state": "skipped", "updated_at": "2026-08-25T11:01:00Z"}],
            threads=[{"id": "thread-1", "isResolved": False}],
            jobs=[],
        )
    )
    report = inspect_pr(api, "o/r", 7)
    assert report.required_failures == []  # skipped required context is accepted
    assert report.skipped_required == ["tier-coverage"]
    assert report.unresolved_threads == ["thread-1"]
    assert report.workflow_failures and "zero jobs" in report.workflow_failures[0]
    assert any(path.endswith("/jobs") and params.get("filter") == "all" for path, params in api.calls)


def test_absent_required_and_non_required_failure_are_not_hidden():
    api = FakeGitHub(
        _responses(
            check_runs=[
                {"name": "A1", "conclusion": "success", "completed_at": "2026-08-25T11:00:00Z"},
                {"name": "copilot-pull-request-reviewer", "conclusion": "failure", "completed_at": "2026-08-25T11:00:00Z"},
            ],
            jobs=[{"name": "test", "conclusion": "success"}],
        )
    )
    report = inspect_pr(api, "o/r", 7)
    assert report.required_failures == ["tier-coverage: ABSENT"]
    assert report.non_required_failures == ["copilot-pull-request-reviewer: failure (check-run)"]
    assert report.workflow_failures == []


def test_no_workflow_run_is_a_distinct_fourth_limb_failure():
    api = FakeGitHub(_responses(jobs=[], runs=[]))
    report = inspect_pr(api, "o/r", 7)
    assert report.workflow_failures == ["no workflow run found for the PR head SHA"]


def test_branch_protection_checks_and_legacy_contexts_are_union_deduped():
    assert _required_names({"required_status_checks": {"contexts": ["A1"], "checks": [{"context": "tier-coverage"}, {"context": "A1"}]}}) == ["A1", "tier-coverage"]
