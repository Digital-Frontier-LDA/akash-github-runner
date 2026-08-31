"""Tests for check_stale_runner_reaper_is_adopted.

⚠ The controls here are as load-bearing as the assertions. The first draft of this rule
granted the PUBLISHER exemption on a basename match, which handed it to df-cicd — a repo
whose copy was deleted in df-cicd#191 and survived only as an untracked leftover. Nothing
in a naive suite would have caught that, because every fixture would have been built with
the right basename in the right repo. `test_a_same_named_copy_in_another_repo_is_not_the_publisher`
is the test that pins it, and it is the reason this file constructs real git remotes.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
RULE = HERE / "check_stale_runner_reaper_is_adopted.py"

CANONICAL = (
    "Digital-Frontier-LDA/akash-github-runner"
    "/.github/workflows/reusable-stale-runner-reaper.yml"
)
SHA = "5d82c5973e01b0067e61e7b65ab97579aed5ffd9"

REGISTERS = (
    "on: push\njobs:\n  p:\n    steps:\n"
    "      - run: gh api orgs/o/actions/runners/registration-token -X POST\n"
)
ADOPTS = f"on:\n  schedule:\n    - cron: '0 */6 * * *'\njobs:\n  r:\n    uses: {CANONICAL}@{SHA}\n"


def _run(
    tmp_path: Path,
    files: dict[str, str],
    origin: str = "https://github.com/Digital-Frontier-LDA/just-akash.git",
):
    d = tmp_path / ".github" / "workflows"
    d.mkdir(parents=True, exist_ok=True)
    for name, body in files.items():
        (d / name).write_text(body)
    # A real remote: repo identity is resolved from it, never from the directory name.
    subprocess.run(["git", "-C", str(tmp_path), "init", "--quiet"], check=False)
    subprocess.run(
        ["git", "-C", str(tmp_path), "remote", "add", "origin", origin], check=False
    )
    return subprocess.run(
        [sys.executable, str(RULE), "--workflows-dir", str(d)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_a_registrar_without_adoption_fails(tmp_path):
    p = _run(tmp_path, {"prov.yml": REGISTERS})
    assert p.returncode == 1
    assert "no workflow calls" in p.stdout


def test_a_registrar_that_adopts_at_a_sha_passes(tmp_path):
    p = _run(tmp_path, {"prov.yml": REGISTERS, "reap.yml": ADOPTS})
    assert p.returncode == 0, p.stdout
    assert "adopts" in p.stdout


def test_a_repo_that_registers_nothing_is_not_applicable(tmp_path):
    p = _run(
        tmp_path,
        {
            "read.yml": "on: push\njobs:\n  q:\n    steps:\n      - run: gh api orgs/o/actions/runners\n"
        },
    )
    assert p.returncode == 0
    # ⚠ Asserted as PRINTED, not merely as rc=0. A silent skip and a pass are the same exit
    # code, and this repo has shipped a checker that reported NOT APPLICABLE on its own subject.
    assert "NOT APPLICABLE" in p.stdout


def test_a_branch_ref_is_not_adoption(tmp_path):
    body = f"on: push\njobs:\n  r:\n    uses: {CANONICAL}@main\n"
    p = _run(tmp_path, {"prov.yml": REGISTERS, "reap.yml": body})
    assert p.returncode == 1
    assert "not a 40-hex commit" in p.stdout


def test_a_commented_out_adoption_is_not_adoption(tmp_path):
    """⛔ The live failure mode, not a hypothetical: Blazing-Back's ONLY mention of this
    reaper on main is a comment naming df-cicd's DELETED copy. A raw grep scores that as an
    adopter of a file that does not exist."""
    body = f"on: push\n# uses: {CANONICAL}@{SHA}\njobs:\n  r:\n    steps:\n      - run: true\n"
    p = _run(tmp_path, {"prov.yml": REGISTERS, "reap.yml": body})
    assert p.returncode == 1


def test_the_retired_df_cicd_path_is_not_adoption(tmp_path):
    """df-cicd published a file with the SAME BASENAME and it was deleted (df-cicd#191).
    Matching on basename would credit a consumer still pointing at it — which is exactly
    where just-akash's working tree sat on 2026-08-31."""
    retired = "Digital-Frontier-LDA/df-cicd/.github/workflows/reusable-stale-runner-reaper.yml"
    body = f"on: push\njobs:\n  r:\n    uses: {retired}@{SHA}\n"
    p = _run(tmp_path, {"prov.yml": REGISTERS, "reap.yml": body})
    assert p.returncode == 1


def test_the_publisher_is_exempt(tmp_path):
    p = _run(
        tmp_path,
        {
            "prov.yml": REGISTERS,
            "reusable-stale-runner-reaper.yml": "on:\n  workflow_call:\n",
        },
        origin="https://github.com/Digital-Frontier-LDA/akash-github-runner.git",
    )
    assert p.returncode == 0, p.stdout
    assert "PUBLISHES" in p.stdout


def test_a_same_named_copy_in_another_repo_is_not_the_publisher(tmp_path):
    """⛔ THE REGRESSION TEST FOR THIS RULE'S OWN FIRST DRAFT.

    A basename check granted df-cicd the publisher exemption on 2026-08-31. A same-named
    file is what a RETIRED FORK looks like — granting it the exemption would excuse the
    second implementation this rule exists to eliminate."""
    p = _run(
        tmp_path,
        {
            "prov.yml": REGISTERS,
            "reusable-stale-runner-reaper.yml": "on:\n  workflow_call:\n",
        },
        origin="https://github.com/Digital-Frontier-LDA/df-cicd.git",
    )
    assert p.returncode == 1, p.stdout
    assert "PUBLISHES" not in p.stdout


def test_publisher_identity_fails_closed_without_a_remote(tmp_path):
    """No remote ⇒ cannot prove publisher ⇒ treated as a consumer. The safe direction."""
    d = tmp_path / ".github" / "workflows"
    d.mkdir(parents=True)
    (d / "prov.yml").write_text(REGISTERS)
    (d / "reusable-stale-runner-reaper.yml").write_text("on:\n  workflow_call:\n")
    p = subprocess.run(
        [sys.executable, str(RULE), "--workflows-dir", str(d)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert p.returncode == 1, p.stdout


def test_an_empty_workflows_dir_refuses_to_pass(tmp_path):
    """0 findings over 0 files is how a rule reports adopted everywhere it never ran."""
    d = tmp_path / ".github" / "workflows"
    d.mkdir(parents=True)
    p = subprocess.run(
        [sys.executable, str(RULE), "--workflows-dir", str(d)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert p.returncode == 1
    assert "cannot judge" in p.stdout


def test_scope_predicate_is_shared_with_the_dereg_backstop_rule():
    """⛔ NOT A STYLE ASSERTION. If this rule's idea of "registers runners" drifts from
    check_dereg_backstop's, a repo can be obliged to have a backstop while being exempt
    from converging on the shared one — silently, both rules green. The import is the only
    thing making that impossible, so the import is what is pinned."""
    import check_dereg_backstop
    import check_stale_runner_reaper_is_adopted as rule

    assert rule.CREATES_REGISTRATIONS is check_dereg_backstop.CREATES_REGISTRATIONS
    assert rule.IMMUTABLE_REF is check_dereg_backstop.IMMUTABLE_REF


def test_the_canonical_path_names_a_workflow_that_exists_here():
    """⛔ A RULE MUST NOT DEMAND A FILE THAT DOES NOT EXIST. This is the defect the rule
    itself is about, one level up: df-cicd's path stayed listed in CANONICAL_REAPERS after
    the file was deleted. Pinning the constant against the tree makes the same mistake
    impossible here."""
    import check_stale_runner_reaper_is_adopted as rule

    rel = rule.CANONICAL.split("/", 2)[2]
    assert (HERE.parent / rel).is_file(), (
        f"{rule.CANONICAL} names a file this repo does not have"
    )
