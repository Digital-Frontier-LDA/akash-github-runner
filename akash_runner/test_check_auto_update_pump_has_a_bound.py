"""The auto-update pump rule must fail the defect, pass the fix, and refuse to guess.

⛔ THE PAIR THAT MAKES IT NON-VACUOUS, both measured against live repos on 2026-09-05:
    NEGATIVE  Blazing-Back main / just-akash / blazing  -> exit 1, no bound
    POSITIVE  Blazing-Back #1590 (the landing gate)     -> exit 0, bound found
A rule that only ever fails is as useless as one that only ever passes; a rule asserted
against one side of that pair would be neither.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

CHECK = Path(__file__).resolve().parent / "check_auto_update_pump_has_a_bound.py"

RUNNER_CONTAINER = "        env:\n          - ACCESS_TOKEN=${GH_RUNNER_PAT}\n"
LISTING_READ = '        raw="$(gh api "orgs/X/actions/runners?per_page=100")"\n'
VERSION_PROJECTION = '        echo "$raw" | jq -r \'map(.version // "NULL") | .[]\'\n'


def _run(d: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CHECK), "--workflows-dir", str(d)],
        capture_output=True,
        text=True,
    )


def _wf(tmp_path: Path, name: str, body: str) -> Path:
    d = tmp_path / ".github" / "workflows"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(body)
    return d


def test_runner_container_with_no_bound_is_a_finding(tmp_path):
    """The defect: defines a runner, nothing bounds the restart pump."""
    d = _wf(tmp_path, "pool.yml", "jobs:\n  x:\n" + RUNNER_CONTAINER + LISTING_READ)
    r = _run(d)
    assert r.returncode == 1, f"unbounded pump was not flagged:\n{r.stdout}{r.stderr}"
    assert "auto-update-pump-has-a-bound" in r.stdout


def test_landing_gate_near_the_read_is_a_bound(tmp_path):
    """POSITIVE CONTROL — #1590's shape: the projection is 11 lines below the read."""
    body = (
        "jobs:\n  x:\n"
        + RUNNER_CONTAINER
        + LISTING_READ
        + "".join(f"        # filler {i}\n".replace("#", "echo") for i in range(11))
        + VERSION_PROJECTION
    )
    d = _wf(tmp_path, "pool.yml", body)
    r = _run(d)
    assert r.returncode == 0, f"the real gate was rejected:\n{r.stdout}{r.stderr}"
    assert "landing-gate" in r.stdout


def test_a_distant_version_mention_is_not_a_bound(tmp_path):
    """NEGATIVE CONTROL — the false positive this rule actually shipped with.

    blazing/akash-ci.yml matched `.application_version.version` 202 lines from its
    runner-listing read and was certified as gated. File-level AND is not proximity.
    """
    body = (
        "jobs:\n  x:\n"
        + RUNNER_CONTAINER
        + '        VER=$(echo "$NODE" | jq -r \'.application_version.version\')\n'
        + "".join(f"        echo filler {i}\n" for i in range(202))
        + LISTING_READ
    )
    d = _wf(tmp_path, "pool.yml", body)
    r = _run(d)
    assert r.returncode == 1, (
        "a `.version` 202 lines from the listing read was accepted as a landing gate "
        f"— the measured false positive is back:\n{r.stdout}{r.stderr}"
    )


def test_a_commented_gate_is_not_a_bound(tmp_path):
    """Blazing-Back carries the whole analysis in comments. Analysis is not a gate."""
    body = (
        "jobs:\n  x:\n"
        + RUNNER_CONTAINER
        + LISTING_READ
        + "        # " + VERSION_PROJECTION.strip() + "\n"
    )
    d = _wf(tmp_path, "pool.yml", body)
    r = _run(d)
    assert r.returncode == 1, (
        f"a commented-out gate satisfied the rule:\n{r.stdout}{r.stderr}"
    )


def test_restart_bound_is_accepted(tmp_path):
    d = _wf(tmp_path, "pool.yml", "jobs:\n  x:\n" + RUNNER_CONTAINER + "        restart: on-failure\n")
    r = _run(d)
    assert r.returncode == 0, f"a restart bound was rejected:\n{r.stdout}{r.stderr}"
    assert "restart-bound" in r.stdout


def test_restart_always_is_not_a_bound(tmp_path):
    """`restart: always` IS the pump. Accepting it would invert the rule."""
    d = _wf(tmp_path, "pool.yml", "jobs:\n  x:\n" + RUNNER_CONTAINER + "        restart: always\n")
    r = _run(d)
    assert r.returncode == 1, f"`restart: always` was accepted as a bound:\n{r.stdout}"


def test_not_applicable_is_a_third_state(tmp_path):
    """A repo defining no runner container is OUT OF SCOPE, not compliant.

    check_runner_image_digest_floor reported NOT APPLICABLE on the very repo it was
    written for. Printing the verdict is what makes that visible instead of silent.
    """
    d = _wf(tmp_path, "unrelated.yml", "jobs:\n  x:\n    steps:\n      - run: echo hi\n")
    r = _run(d)
    assert r.returncode == 0
    assert "NOT APPLICABLE" in r.stdout, r.stdout
    assert "NOT a pass" in r.stdout, "the third state must not read as a pass"


def test_a_caller_that_delegates_provisioning_is_out_of_scope(tmp_path):
    """blazing/ci.yml passes GH_RUNNER_PAT as a SECRET and defines no container.

    Scoping on the secret name would make the rule unsatisfiable for repos that
    correctly delegate to the shared pool workflow.
    """
    body = (
        "jobs:\n  pool:\n    uses: org/just-akash/.github/workflows/runner-pool.yml@abc\n"
        "    secrets:\n      GH_RUNNER_PAT: ${{ secrets.GH_RUNNER_PAT }}\n"
    )
    d = _wf(tmp_path, "ci.yml", body)
    r = _run(d)
    assert r.returncode == 0
    assert "NOT APPLICABLE" in r.stdout, r.stdout
