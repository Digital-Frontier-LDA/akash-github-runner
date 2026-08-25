#!/usr/bin/env python3
"""Report whether a pull request satisfies the real merge predicate.

"All checks pass" is not a merge predicate. This tool checks four independent
limbs: branch-protection-required contexts (the union of check-runs and commit
statuses, newest record per name), zero unresolved review threads, every
non-required failure listed by name, and evidence that the workflow actually
created jobs. A skipped required context is treated as branch protection does:
it satisfies the context, but it remains visible in the report.

The API details are intentional. ``tier-coverage`` is a commit status rather
than a check-run; check-run names repeat on one SHA; and Actions jobs must be
requested with ``filter=all`` because the default endpoint exposes only the
latest attempt. A workflow run with zero jobs is a failure of the instrument,
not a clean run.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

PASSING = {"success", "skipped", "neutral"}
TERMINAL_FAILURES = {"failure", "error", "cancelled", "timed_out", "action_required", "stale"}


def _time(value: str | None) -> str:
    return value or ""


@dataclass
class Report:
    pr: str
    head_sha: str = ""
    required: list[str] = field(default_factory=list)
    required_failures: list[str] = field(default_factory=list)
    skipped_required: list[str] = field(default_factory=list)
    unresolved_threads: list[str] = field(default_factory=list)
    non_required_failures: list[str] = field(default_factory=list)
    workflow_failures: list[str] = field(default_factory=list)
    workflow_runs: int = 0
    workflow_jobs: int = 0

    @property
    def ok(self) -> bool:
        return not (
            self.required_failures
            or self.unresolved_threads
            or self.workflow_failures
        )


class GitHub:
    def __init__(self, token: str, api: str = "https://api.github.com") -> None:
        self.token = token
        self.api = api.rstrip("/")

    def get(self, path: str, **params: str) -> Any:
        query = urllib.parse.urlencode(params)
        url = f"{self.api}{path}{'?' + query if query else ''}"
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        with urllib.request.urlopen(request) as response:
            return json.load(response)

    def graphql(self, query: str, variables: dict[str, Any]) -> Any:
        body = json.dumps({"query": query, "variables": variables}).encode()
        request = urllib.request.Request(
            "https://api.github.com/graphql",
            data=body,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        with urllib.request.urlopen(request) as response:
            payload = json.load(response)
        if payload.get("errors"):
            raise RuntimeError("GraphQL: " + "; ".join(e.get("message", "error") for e in payload["errors"]))
        return payload["data"]


def _latest_records(check_runs: list[dict], statuses: list[dict]) -> dict[str, dict]:
    """Union check-runs and commit statuses, choosing newest per context name."""
    records: dict[str, dict] = {}
    for run in check_runs:
        name = run.get("name", "")
        candidate = {"name": name, "state": run.get("conclusion") or run.get("status"), "at": _time(run.get("completed_at") or run.get("started_at")), "kind": "check-run"}
        if candidate["at"] >= records.get(name, {}).get("at", ""):
            records[name] = candidate
    for status in statuses:
        name = status.get("context", "")
        candidate = {"name": name, "state": status.get("state"), "at": _time(status.get("updated_at")), "kind": "commit-status"}
        if candidate["at"] >= records.get(name, {}).get("at", ""):
            records[name] = candidate
    return records


def _required_names(protection: dict) -> list[str]:
    block = protection.get("required_status_checks") or {}
    names = list(block.get("contexts") or [])
    names.extend(item.get("context") for item in block.get("checks") or [] if item.get("context"))
    return sorted(set(names))


def inspect_pr(api: GitHub, repo: str, number: int, base: str | None = None) -> Report:
    owner, name = repo.split("/", 1)
    pr = api.get(f"/repos/{owner}/{name}/pulls/{number}")
    branch = base or pr.get("base", {}).get("ref", "main")
    head_sha = pr.get("head", {}).get("sha", "")
    report = Report(f"{repo}#{number}", head_sha=head_sha)

    protection = api.get(f"/repos/{owner}/{name}/branches/{urllib.parse.quote(branch, safe='')}/protection")
    report.required = _required_names(protection)
    check_runs = api.get(f"/repos/{owner}/{name}/commits/{head_sha}/check-runs", per_page="100").get("check_runs", [])
    statuses = api.get(f"/repos/{owner}/{name}/commits/{head_sha}/status", per_page="100").get("statuses", [])
    latest = _latest_records(check_runs, statuses)
    for required in report.required:
        record = latest.get(required)
        if record is None:
            report.required_failures.append(f"{required}: ABSENT")
        elif record["state"] not in PASSING:
            report.required_failures.append(f"{required}: {record['state']} ({record['kind']})")
        elif record["state"] == "skipped":
            report.skipped_required.append(required)
    for name_, record in sorted(latest.items()):
        if name_ not in report.required and record["state"] in TERMINAL_FAILURES:
            report.non_required_failures.append(f"{name_}: {record['state']} ({record['kind']})")

    thread_query = """
      query($owner:String!, $name:String!, $number:Int!) {
        repository(owner:$owner, name:$name) {
          pullRequest(number:$number) {
            reviewThreads(first:100) { nodes { id isResolved } }
          }
        }
      }
    """
    thread_data = api.graphql(thread_query, {"owner": owner, "name": name, "number": number})
    threads = thread_data["repository"]["pullRequest"]["reviewThreads"]["nodes"]
    report.unresolved_threads = [node["id"] for node in threads if not node.get("isResolved")]

    runs = api.get(f"/repos/{owner}/{name}/actions/runs", head_sha=head_sha, per_page="100").get("workflow_runs", [])
    report.workflow_runs = len(runs)
    if not runs:
        report.workflow_failures.append("no workflow run found for the PR head SHA")
    for run in runs:
        jobs = api.get(f"/repos/{owner}/{name}/actions/runs/{run['id']}/jobs", per_page="100", filter="all").get("jobs", [])
        report.workflow_jobs += len(jobs)
        if not jobs:
            path = run.get("path") or run.get("name") or str(run["id"])
            report.workflow_failures.append(f"{path}: workflow run {run['id']} has zero jobs (filter=all)")
    return report


def print_report(report: Report) -> None:
    print(f"MERGE-READY {report.pr} head={report.head_sha}")
    print(f"[1] required contexts: {'PASS' if not report.required_failures else 'FAIL'}")
    print(f"    required={', '.join(report.required) or '(none)'}")
    for item in report.required_failures:
        print(f"    - {item}")
    if report.skipped_required:
        print(f"    skipped-but-branch-protection-satisfying: {', '.join(report.skipped_required)}")
    print(f"[2] review threads: {'PASS' if not report.unresolved_threads else 'FAIL'}")
    for item in report.unresolved_threads:
        print(f"    - unresolved {item}")
    print(f"[3] non-required failures: {'PASS (none)' if not report.non_required_failures else 'LISTED'}")
    for item in report.non_required_failures:
        print(f"    - {item}")
    print(f"[4] workflow execution: {'PASS' if not report.workflow_failures else 'FAIL'} runs={report.workflow_runs} jobs={report.workflow_jobs}")
    for item in report.workflow_failures:
        print(f"    - {item}")
    print(f"RESULT: {'MERGE-READY' if report.ok else 'NOT MERGE-READY'}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", help="owner/name")
    parser.add_argument("pr", type=int)
    parser.add_argument("--base", default=None)
    parser.add_argument("--token", default=os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN"))
    args = parser.parse_args(argv)
    if not args.token:
        parser.error("GH_TOKEN or GITHUB_TOKEN is required")
    try:
        report = inspect_pr(GitHub(args.token), args.repo, args.pr, args.base)
    except (urllib.error.HTTPError, urllib.error.URLError, KeyError, RuntimeError) as exc:
        print(f"merge-ready: ERROR: {exc}", file=sys.stderr)
        return 2
    print_report(report)
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
