"""The DISABLE_AUTO_UPDATE rule must catch the setting and ignore the mention.

⛔ THE DEFECT IT GUARDS — just-akash deployment 1787733947684, four times in ~63s: the
runner printed "Disable auto update option is enabled", reported version 2.334.0, said
"Listening for Jobs", then "deprecated and cannot receive messages" — and the supervisor
restarted and RE-REGISTERED. A paid lease that runs nothing, plus one org registration per
restart feeding the listing whose page count sets the CI quota floor.

⚠ PRESENCE, NOT VALUE. Measured (Blazing-Back run 31614227678): `DISABLE_AUTO_UPDATE=false`
still printed "Disable auto update option is enabled". The entrypoint tests presence.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

CHECK = Path(__file__).resolve().parent / "check_disable_auto_update_absent.py"


def _run(workflows_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CHECK), "--workflows-dir", str(workflows_dir)],
        capture_output=True,
        text=True,
    )


def _wf(tmp_path: Path, name: str, body: str) -> Path:
    d = tmp_path / ".github" / "workflows"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(body)
    return d


def test_env_list_item_is_a_finding(tmp_path):
    """The SDL/docker form: `- DISABLE_AUTO_UPDATE=true`."""
    d = _wf(
        tmp_path,
        "pool.yml",
        "jobs:\n  x:\n    env:\n      - DISABLE_AUTO_UPDATE=true\n",
    )
    r = _run(d)
    assert r.returncode == 1, f"the setting was not flagged:\n{r.stdout}{r.stderr}"


def test_false_is_still_a_finding():
    """MUTATION-PROOF: `=false` must NOT be accepted.

    A rule that let `false` through would certify the exact outage it exists to prevent —
    the entrypoint applies --disableupdate for ANY non-empty value.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        d = _wf(
            Path(td),
            "pool.yml",
            "jobs:\n  x:\n    env:\n      - DISABLE_AUTO_UPDATE=false\n",
        )
        r = _run(d)
        assert r.returncode == 1, (
            f"`=false` was accepted — that is the documented trap:\n{r.stdout}"
        )


def test_yaml_mapping_form_is_a_finding(tmp_path):
    d = _wf(
        tmp_path,
        "pool.yml",
        'jobs:\n  x:\n    env:\n      DISABLE_AUTO_UPDATE: "true"\n',
    )
    r = _run(d)
    assert r.returncode == 1, f"the mapping form was not flagged:\n{r.stdout}"


def test_a_comment_explaining_the_deletion_is_not_a_finding(tmp_path):
    """Blazing-Back documents the whole incident in comments. That is the FIX, not the bug."""
    d = _wf(
        tmp_path,
        "pool.yml",
        "jobs:\n  x:\n    steps:\n      # DISABLE_AUTO_UPDATE was deleted here, see #985\n",
    )
    r = _run(d)
    assert r.returncode == 0, f"a comment was flagged as a violation:\n{r.stdout}"


def test_a_guard_that_DETECTS_the_variable_is_not_a_finding(tmp_path):
    """KNOWN-NEGATIVE FROM THE REAL FLEET, and it caught a real false positive.

    Blazing-Back's runner-time-to-ready.yml greps for the variable and echoes an ::error
    naming it. The first version of this rule flagged that guard's own source. A rule that
    reports detection code as the defect matches everything that TALKS about the subject.
    """
    body = (
        "jobs:\n  x:\n    steps:\n      - run: |\n"
        "          if grep -qE '^\\s*-\\s*DISABLE_AUTO_UPDATE=true' .github/workflows/akash-runner.yml; then\n"
        '            echo "::error::DISABLE_AUTO_UPDATE=true is still set"\n'
        "          fi\n"
    )
    d = _wf(tmp_path, "guard.yml", body)
    r = _run(d)
    assert r.returncode == 0, (
        f"a guard that DETECTS the variable was flagged:\n{r.stdout}"
    )


def test_sdl_files_are_in_scope(tmp_path):
    """⚠ NOT WORKFLOWS ONLY. just-akash set it at TWO sites and one was sdl/."""
    d = _wf(tmp_path, "pool.yml", "jobs:\n  x:\n    steps: []\n")
    sdl = tmp_path / "sdl"
    sdl.mkdir(parents=True, exist_ok=True)
    (sdl / "probe.yaml").write_text(
        "services:\n  runner:\n    env:\n      - DISABLE_AUTO_UPDATE=true\n"
    )
    r = _run(d)
    assert r.returncode == 1, (
        "the sibling sdl/ was not scanned — a workflows-only scan reports PASS while half "
        f"the fleet still freezes its runner:\n{r.stdout}"
    )


def test_a_clean_tree_passes(tmp_path):
    """NON-VACUITY: the rule must not simply fail everything."""
    d = _wf(tmp_path, "pool.yml", "jobs:\n  x:\n    env:\n      - RUNNER_SCOPE=org\n")
    r = _run(d)
    assert r.returncode == 0, f"a clean tree was flagged:\n{r.stdout}"


def test_a_value_containing_a_detection_token_is_still_a_finding(tmp_path):
    """REGRESSION (CodeRabbit, #24): `DISABLE_AUTO_UPDATE: echo` is a valid assignment.

    An earlier draft skipped any line containing grep/echo/::error BEFORE testing the
    assignment shape, so a value that merely contained such a token was accepted — the rule
    silently passed the exact thing it exists to reject. Anchoring `_ASSIGN` at ^\\s* does the
    job a blacklist was reaching for, without the hole.
    """
    d = _wf(
        tmp_path, "pool.yml", "jobs:\n  x:\n    env:\n      DISABLE_AUTO_UPDATE: echo\n"
    )
    r = _run(d)
    assert r.returncode == 1, (
        f"a value containing a detection token was skipped:\n{r.stdout}"
    )


def test_env_list_value_containing_a_token_is_still_a_finding(tmp_path):
    d = _wf(
        tmp_path,
        "pool.yml",
        "jobs:\n  x:\n    env:\n      - DISABLE_AUTO_UPDATE=grep\n",
    )
    r = _run(d)
    assert r.returncode == 1, f"env-list value with a token was skipped:\n{r.stdout}"
