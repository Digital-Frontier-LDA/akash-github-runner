"""`uses:@sha` and `checker-ref` are two declarations of one decision.

⚠ EVERY FIXTURE HERE IS ASYMMETRIC ON PURPOSE. The rule guards two independent
values, and a fixture that moves BOTH (or neither) passes through the same door as a
correct file. Bumping one is the realistic shape — it is a one-line edit that looks
complete in review — so the mutants below advance `uses:` alone and `checker-ref`
alone, separately.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from akash_runner.check_conformance_pin_agrees_with_checker_ref import audit, main

A = "47f2835d7a8284ae19bb0e36a531de69da4beaba"
B = "6ba4316accea74c249ce3c7173f9d39ba1e05494"

TEMPLATE = """\
name: Runner Conformance
on:
  pull_request:
jobs:
  pool:
    uses: Digital-Frontier-LDA/akash-github-runner/.github/workflows/reusable-akash-runner-conformance.yml@{uses}
    with:
      workflow: .github/workflows/runner-pool.yml
      workflows-dir: .github/workflows
      checker-ref: {ref}
"""


def _wf(
    tmp_path: Path, uses: str, ref: str, name: str = "runner-conformance.yml"
) -> Path:
    p = tmp_path / name
    p.write_text(TEMPLATE.format(uses=uses, ref=ref))
    return p


def test_agreeing_pins_are_clean(tmp_path: Path) -> None:
    problems, callers = audit(_wf(tmp_path, A, A))
    assert problems == []
    assert callers == 1


def test_uses_advanced_alone_is_caught(tmp_path: Path) -> None:
    """The contract moves, the checker does not."""
    problems, _ = audit(_wf(tmp_path, B, A))
    assert len(problems) == 1
    assert B[:9] in problems[0] and A[:9] in problems[0]


def test_checker_ref_advanced_alone_is_caught(tmp_path: Path) -> None:
    """⭐ The OTHER direction. A rule that only compared in one order would pass this."""
    problems, _ = audit(_wf(tmp_path, A, B))
    assert len(problems) == 1
    assert A[:9] in problems[0] and B[:9] in problems[0]


def test_the_message_names_BOTH_shas_not_just_that_they_differ(tmp_path: Path) -> None:
    """ "They disagree" sends a reader to diff two files. Naming which is which says
    whether the contract or the checker is the stale half."""
    problems, _ = audit(_wf(tmp_path, B, A))
    assert "CONTRACT" in problems[0] and "CHECKER" in problems[0]


@pytest.mark.parametrize("ref", ["main", "v2.7.1", "HEAD"])
def test_a_mutable_uses_ref_is_caught(tmp_path: Path, ref: str) -> None:
    problems, _ = audit(_wf(tmp_path, ref, A))
    assert any("not a 40-char commit SHA" in p for p in problems)


def test_a_mutable_checker_ref_is_caught(tmp_path: Path) -> None:
    problems, _ = audit(_wf(tmp_path, A, "main"))
    assert any("not a 40-char commit SHA" in p for p in problems)


def test_a_caller_with_no_checker_ref_at_all_is_caught(tmp_path: Path) -> None:
    p = tmp_path / "wf.yml"
    p.write_text(
        "name: x\non:\n  pull_request:\njobs:\n  pool:\n"
        f"    uses: org/repo/.github/workflows/reusable-akash-runner-conformance.yml@{A}\n"
        "    with:\n      workflow: .github/workflows/runner-pool.yml\n"
    )
    problems, callers = audit(p)
    assert callers == 1
    assert any("supplies no `checker-ref`" in x for x in problems)


def test_a_workflow_with_no_caller_is_NOT_JUDGEABLE_not_a_pass(
    tmp_path: Path, capsys
) -> None:
    """⛔ The load-bearing one. If a repo that never calls the reusable printed OK, a
    caller could be DELETED and this rule would keep reporting success."""
    p = tmp_path / "other.yml"
    p.write_text(
        "name: x\non: [push]\njobs:\n  a:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo hi\n"
    )
    rc = main([str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "NOT-JUDGEABLE" in out
    assert "not a pass" in out


def test_an_empty_scan_is_rc2_not_rc0(tmp_path: Path) -> None:
    """ "No files" and "files, all clean" are opposite facts that print the same
    reassurance if both return 0."""
    assert main([str(tmp_path / "does-not-exist")]) == 2


def test_unparseable_yaml_is_rc2_not_a_pass(tmp_path: Path) -> None:
    p = tmp_path / "bad.yml"
    p.write_text("jobs: [unclosed\n")
    assert main([str(p)]) == 2


def test_a_non_caller_job_in_the_same_file_is_ignored(tmp_path: Path) -> None:
    """Only jobs that actually `uses:` the reusable are judged — a repo may have many."""
    p = tmp_path / "mixed.yml"
    p.write_text(
        TEMPLATE.format(uses=A, ref=A)
        + "  other:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo hi\n"
    )
    problems, callers = audit(p)
    assert problems == []
    assert callers == 1
