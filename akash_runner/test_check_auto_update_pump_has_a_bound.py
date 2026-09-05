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
    assert r.returncode == 3
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
    assert r.returncode == 3
    assert "NOT APPLICABLE" in r.stdout, r.stdout


def test_one_bounded_file_does_not_silence_an_unbounded_sibling(tmp_path):
    """⛔ THE FAIL-OPEN THIS RULE SHIPPED WITH, reported by Copilot AND CodeRabbit on #69.

    `check()` returned no findings as soon as ANY file had a bound, so a repo could gate one
    workflow and go clean while another still pumped. The rule's own blast radius names the
    case: Blazing-Back FAIL (2 — akash-runner.yml AND runner-time-to-ready.yml). Bound either
    and the other disappeared.
    """
    d = _wf(tmp_path, "bounded.yml",
            "jobs:\n  x:\n" + RUNNER_CONTAINER + LISTING_READ + VERSION_PROJECTION)
    (d / "unbounded.yml").write_text("jobs:\n  y:\n" + RUNNER_CONTAINER + LISTING_READ)
    r = _run(d)
    assert r.returncode == 1, (
        f"a bounded sibling silenced an unbounded runner container:\n{r.stdout}{r.stderr}"
    )
    # ⚠ MATCH THE FINDING'S SUBJECT, NOT A SUBSTRING. The first version asserted
    # `"bounded.yml:" not in stdout` — but the finding for the UNBOUNDED file legitimately
    # NAMES the bound it found elsewhere, and "unbounded.yml" literally contains the
    # substring "bounded.yml". Two ways to be wrong in one assertion. A finding's subject is
    # the path at the START of its line, so that is what gets checked.
    subjects = [
        ln.split(":", 1)[0].rsplit("/", 1)[-1]
        for ln in r.stdout.splitlines()
        if "[auto-update-pump-has-a-bound]" in ln
    ]
    assert subjects == ["unbounded.yml"], (
        f"expected exactly the unbounded file to be reported, got {subjects}\n{r.stdout}"
    )


def test_a_gate_in_an_out_of_scope_file_still_reports_the_container(tmp_path):
    """A landing gate in a file that defines NO runner container must not clear one that does.

    Pins the scoping: the rule cannot prove from workflow text that a gate elsewhere protects
    this container, so it reports it and names the other bound rather than guessing clean.
    """
    d = _wf(tmp_path, "gate-only.yml", "jobs:\n  g:\n" + LISTING_READ + VERSION_PROJECTION)
    (d / "container.yml").write_text("jobs:\n  c:\n" + RUNNER_CONTAINER)
    r = _run(d)
    assert r.returncode == 1, f"an out-of-scope gate cleared a runner container:\n{r.stdout}"
    assert "container.yml" in r.stdout, r.stdout
    assert "elsewhere" in r.stdout.lower(), "the finding should NAME the bound it found elsewhere"


def test_not_applicable_exits_3_not_0(tmp_path):
    """⛔ The message said NOT A PASS and the exit code said PASS. The action reads the code.

    `advisory()` in the conformance action maps 0 -> PASS and 3 -> NOT-JUDGEABLE. Returning 0
    here made the harness report a repo it never judged as passing — defeating the printed
    third state entirely. (CodeRabbit, #69.)
    """
    d = _wf(tmp_path, "unrelated.yml", "jobs:\n  x:\n    steps:\n      - run: echo hi\n")
    r = _run(d)
    assert r.returncode == 3, f"NOT APPLICABLE returned {r.returncode}, not 3:\n{r.stdout}"
    assert "NOT APPLICABLE" in r.stdout
