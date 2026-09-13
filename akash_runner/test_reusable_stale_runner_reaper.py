#!/usr/bin/env python3
"""The reaper's SHELL is extracted from the workflow and EXECUTED against a stubbed `gh`.

Not a grep over the YAML. A source-scan proves a string is present; it cannot prove a busy
runner is never selected, that a blank prefix refuses, or that zero-reaped is announced —
and those are the three properties whose failure is silent or destructive.
"""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

import pytest
import yaml

WF = (
    Path(__file__).resolve().parents[1]
    / ".github/workflows/reusable-stale-runner-reaper.yml"
)


def _script() -> str:
    doc = yaml.safe_load(WF.read_text())
    # YAML 1.1 parses a bare `on:` as boolean True — the same trap check_dereg_backstop notes.
    job = doc["jobs"]["reap"]
    return next(s["run"] for s in job["steps"] if "run" in s)


def _run(
    tmp_path: Path,
    *,
    runners: str,
    prefixes: str = "akash-ci-",
    dry: str = "false",
    core: str = "5000",
    floor: str = "1500",
    run_state: str = "completed|success|test-org/test-repo",
    run_lookup_rc: int = 0,
    script: str | None = None,
) -> subprocess.CompletedProcess:
    """Execute the real step script with a fake `gh` that serves `runners` and logs DELETEs."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (tmp_path / "runners.json").write_text(runners)
    (bindir / "gh").write_text(
        textwrap.dedent(f"""\
        #!/bin/bash
        # A REAL stub: it serves JSON and applies the caller's OWN --jq with real jq.
        # An earlier version re-implemented the select() in awk — which tested the stub's
        # filter, not the workflow's. The selector under test must be the workflow's string.
        for a in "$@"; do [ "$a" = "rate_limit" ] && {{ echo "{core}"; exit 0; }}; done
        for a in "$@"; do [ "$a" = "-X" ] && {{ echo "$@" | grep -oE '[0-9]+$' >> "{tmp_path}/deleted.txt"; exit 0; }}; done
        for a in "$@"; do case "$a" in repos/*/actions/runs/*) echo '{run_state}'; exit {run_lookup_rc};; esac; done
        for a in "$@"; do case "$a" in *per_page=1) jq '.runners|length' "{tmp_path}/runners.json"; exit 0;; esac; done
        # extract the --jq expression this call passed, and apply it verbatim
        JQ=""; prev=""
        for a in "$@"; do [ "$prev" = "--jq" ] && JQ="$a"; prev="$a"; done
        jq -r "$JQ" "{tmp_path}/runners.json"
        """)
    )
    (bindir / "gh").chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "ORG": "test-org",
        "PREFIXES": prefixes,
        "CALLER_REPO": "test-org/test-repo",
        "DRY_RUN": dry,
        "API_FLOOR": floor,
    }
    return subprocess.run(
        ["bash", "-c", script or _script()], capture_output=True, text=True, env=env
    )


def _deleted(tmp_path: Path) -> list[str]:
    f = tmp_path / "deleted.txt"
    return f.read_text().split() if f.exists() else []


def test_a_blank_prefix_refuses_and_names_the_reason(tmp_path):
    """A blank prefix would match EVERY runner in the org. Fail closed, and say why."""
    r = _run(
        tmp_path,
        runners='{"runners":[{"id":1,"name":"akash-ci-a","status":"offline","busy":false}]}',
        prefixes="   ",
    )
    assert r.returncode == 2, r.stdout + r.stderr
    # Assert on the MESSAGE: an exit-code-only assertion passes if the guard is replaced by
    # any other error, so it would not pin THIS guard.
    assert "empty prefix matches EVERY runner" in (r.stdout + r.stderr)
    assert _deleted(tmp_path) == []


def test_a_busy_runner_is_never_selected(tmp_path):
    """online+busy is a runner MID-JOB. Deleting it kills someone's build."""
    r = _run(
        tmp_path,
        runners='{"runners":[{"id":1,"name":"akash-ci-busy-123456789-x","status":"online","busy":true},{"id":2,"name":"akash-ci-idle-online-123456789-x","status":"online","busy":false},{"id":9,"name":"akash-ci-offline-but-busy-123456789-x","status":"offline","busy":true},{"id":3,"name":"akash-ci-dead-123456789-x","status":"offline","busy":false}]}',
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert _deleted(tmp_path) == ["2", "3"], (
        f"selected {_deleted(tmp_path)}; only IDLE runners with a terminal creator run may be reaped. "
        "id=1 and id=9 are busy, so deleting either can kill a job."
    )


def test_a_runner_outside_our_prefix_is_never_touched(tmp_path):
    """The org listing is SHARED. Presence is not ownership — the name is."""
    r = _run(
        tmp_path,
        runners='{"runners":[{"id":7,"name":"akash-ci-ours-123456789-x","status":"offline","busy":false},{"id":8,"name":"someone-elses-runner-123456789-x","status":"offline","busy":false}]}',
        prefixes="akash-ci-",
    )
    assert _deleted(tmp_path) == ["7"], r.stdout


def test_zero_owned_is_announced_not_silent(tmp_path):
    """'nothing MATCHED' and 'nothing to do' read identically unless the reaper says so."""
    r = _run(
        tmp_path,
        runners='{"runners":[{"id":9,"name":"someone-elses","status":"offline","busy":false}]}',
        prefixes="akash-ci-",
    )
    assert r.returncode == 0
    assert "Reaped 0" in r.stdout and "nothing MATCHED" in r.stdout, r.stdout
    assert _deleted(tmp_path) == []


def test_dry_run_deletes_nothing_but_reports_what_it_would(tmp_path):
    r = _run(
        tmp_path,
        runners='{"runners":[{"id":4,"name":"akash-ci-dead-123456789-x","status":"offline","busy":false}]}',
        dry="true",
    )
    assert _deleted(tmp_path) == []
    assert "DRY RUN" in r.stdout and "would delete" in r.stdout


def test_dry_run_defaults_to_true_in_the_contract(tmp_path):
    """A destructive default is how a sweeper deletes before anyone reads its output."""
    doc = yaml.safe_load(WF.read_text())
    assert doc[True]["workflow_call"]["inputs"]["dry-run"]["default"] is True


def test_an_exhausted_budget_skips_without_failing_the_job(tmp_path):
    """The reaper shares one budget with the PROVISIONER. Starving it causes the leak."""
    r = _run(
        tmp_path,
        runners='{"runners":[{"id":5,"name":"akash-ci-dead","status":"offline","busy":false}]}',
        core="900",
        floor="1500",
    )
    assert r.returncode == 0, "a busy CI window must not read as a broken reaper"
    assert "SKIPPED" in r.stdout and "floor" in r.stdout
    assert _deleted(tmp_path) == []


def test_name_prefixes_is_required_so_a_consumer_cannot_omit_it(tmp_path):
    doc = yaml.safe_load(WF.read_text())
    assert doc[True]["workflow_call"]["inputs"]["name-prefixes"]["required"] is True


def test_caller_repo_is_required_for_creator_run_identity() -> None:
    doc = yaml.safe_load(WF.read_text())
    assert doc[True]["workflow_call"]["inputs"]["caller-repo"]["required"] is True


def test_diagnostics_aggregate_by_prefix_and_creator_run_without_names(
    tmp_path: Path,
) -> None:
    r = _run(
        tmp_path,
        runners='{"runners":[{"id":1,"name":"akash-ci-a-123456789-x","status":"offline","busy":false},{"id":2,"name":"akash-ci-b-123456789-y","status":"online","busy":false}]}',
        dry="true",
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert "owned_prefix=akash-ci- count=2" in r.stdout
    assert (
        "creator_run=123456789 count=2 state=completed|success|test-org/test-repo"
        in r.stdout
    )


@pytest.mark.parametrize(
    ("name", "state", "lookup_rc"),
    [
        ("akash-ci-malformed", "completed|success|test-org/test-repo", 0),
        ("akash-ci-live-123456789-x", "in_progress|?|test-org/test-repo", 0),
        ("akash-ci-foreign-123456789-x", "completed|success|other/repo", 0),
        ("akash-ci-unreadable-123456789-x", "?", 1),
    ],
)
def test_missing_live_foreign_and_unreadable_creator_runs_are_held(
    tmp_path: Path, name: str, state: str, lookup_rc: int
) -> None:
    r = _run(
        tmp_path,
        runners=(
            '{"runners":[{"id":7,"name":"'
            + name
            + '","status":"offline","busy":false}]}'
        ),
        run_state=state,
        run_lookup_rc=lookup_rc,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert _deleted(tmp_path) == []
    assert "held" in r.stdout


def test_creator_run_guard_is_an_effective_exact_call_site(tmp_path: Path) -> None:
    script = _script()
    target = '*) printf \'%s\\t%s\\t%s\\n\' "$id" "$name" "$RID" >> /tmp/held.tsv ;;'
    assert script.count(target) == 1, "mutation target must exist exactly once"
    mutant = script.replace(target, target.replace("held.tsv", "safe.tsv"))
    assert mutant != script

    # Execute the same live-run subject through a temporary workflow whose delete loop
    # bypasses the typed-safe population. The mutation must make the runner disappear.
    r = _run(
        tmp_path,
        runners='{"runners":[{"id":7,"name":"akash-ci-live-123456789-x","status":"offline","busy":false}]}',
        run_state="in_progress|?|test-org/test-repo",
        script=mutant,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert _deleted(tmp_path) == ["7"], (
        "bypassing the safe population must change effect"
    )
