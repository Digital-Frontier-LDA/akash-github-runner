"""One repo's reaper must not delete another repo's runners.

⛔ THE KNOWN-BAD IS A PREFIX THAT GENUINELY COLLIDES. A rule that cannot demonstrate a
collision cannot claim to prevent one, so `test_known_bad_the_widening_that_was_forbidden`
reproduces the exact change ruled out on Blazing-Back: widening `PREFIXES: df-core-` to
`akash-`, which selects blazing's `akash-ci-*` and `akash-integration-*` in the shared org.

⚠ THE POPULATION IS DERIVED, NEVER RESTATED. Every prefix comes out of the repos handed in.
There is no literal list of known prefixes to fall out of date — pinned by
`test_no_prefix_list_is_hardcoded`. What IS bounded is the set of repos passed: one that
registers into the same org and was not passed is invisible, and the PASS line says so.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from akash_runner.check_sibling_prefix_collisions import (  # noqa: E402
    check,
    describe,
)

MODULE = (
    Path(__file__).resolve().parents[1]
    / "akash_runner/check_sibling_prefix_collisions.py"
)


def _repo(root: Path, *, org: str, emits: list[str], filters: list[str]) -> Path:
    wf = root / ".github" / "workflows"
    wf.mkdir(parents=True)
    for i, prefix in enumerate(emits):
        (wf / f"producer{i}.yml").write_text(
            "on: {workflow_dispatch: {}}\njobs:\n  pool:\n    runs-on: ubuntu-latest\n"
            "    steps:\n      - run: |\n"
            f"          echo '- RUNNER_NAME_PREFIX={prefix}'\n"
            f"        env:\n          ORG: {org}\n"
        )
    if filters:
        (wf / "reaper.yml").write_text(
            'on:\n  schedule: [{cron: "0 * * * *"}]\njobs:\n  reap:\n    runs-on: ubuntu-latest\n'
            "    steps:\n      - run: |\n"
            '          gh api -X DELETE "orgs/$ORG/actions/runners/$id"\n'
            "        env:\n"
            f"          ORG: {org}\n          PREFIXES: {','.join(filters)}\n"
        )
    return root


# ── the forbidden change ─────────────────────────────────────────────────────


def test_known_bad_the_widening_that_was_forbidden(tmp_path):
    """★★ Blazing-Back widening `df-core-` to `akash-` eats blazing's registrations."""
    a = _repo(
        tmp_path / "backend",
        org="Borduas-Holdings",
        emits=["akash-", "df-core-"],
        filters=["akash-"],
    )
    b = _repo(
        tmp_path / "blazing",
        org="Borduas-Holdings",
        emits=["akash-ci-", "akash-integration-"],
        filters=["akash-integration-"],
    )
    findings = check([describe(a), describe(b)])
    assert findings, "the forbidden widening produced no collision"
    assert any("akash-ci-" in f for f in findings), findings
    assert any("akash-integration-" in f for f in findings), findings


def test_known_good_the_narrowed_filter_that_fixed_it(tmp_path):
    a = _repo(
        tmp_path / "backend",
        org="Borduas-Holdings",
        emits=["akash-", "df-core-"],
        filters=["df-core-"],
    )
    b = _repo(
        tmp_path / "blazing",
        org="Borduas-Holdings",
        emits=["akash-ci-"],
        filters=["akash-integration-"],
    )
    assert check([describe(a), describe(b)]) == []


def test_the_finding_says_narrow_the_filter_not_widen_it(tmp_path):
    """⚠ The obvious repair is the defect. The message must not leave that to judgement."""
    a = _repo(tmp_path / "a", org="O", emits=["x-"], filters=["x-"])
    b = _repo(tmp_path / "b", org="O", emits=["x-y-"], filters=[])
    findings = check([describe(a), describe(b)])
    assert findings and "do NOT widen" in findings[0], findings


# ── scope ────────────────────────────────────────────────────────────────────


def test_different_orgs_do_not_collide(tmp_path):
    """A shared prefix in two different orgs reaps nothing of the other's."""
    a = _repo(tmp_path / "a", org="OrgOne", emits=["akash-"], filters=["akash-"])
    b = _repo(tmp_path / "b", org="OrgTwo", emits=["akash-ci-"], filters=[])
    assert check([describe(a), describe(b)]) == []


def test_a_repo_does_not_collide_with_itself(tmp_path):
    """Reaping your own producers across prefixes is coverage, not collision."""
    a = _repo(
        tmp_path / "a", org="O", emits=["akash-", "akash-ci-"], filters=["akash-"]
    )
    assert check([describe(a)]) == []


def test_the_longer_filter_does_not_reap_the_shorter_prefix(tmp_path):
    """Direction matters: `akash-integration-` does not select a runner named `akash-x`."""
    a = _repo(
        tmp_path / "a",
        org="O",
        emits=["akash-integration-"],
        filters=["akash-integration-"],
    )
    b = _repo(tmp_path / "b", org="O", emits=["akash-"], filters=[])
    assert check([describe(a), describe(b)]) == []


# ── extraction must not compute from noise, and must look where the value IS ──


def test_a_filter_declared_in_step_env_is_found(tmp_path):
    """⚠ The real reaper's filter lives in a STEP's `env:`, not a `with:` block.

    Searching only `with:` read the filter from a different workflow's per-run dereg, so a
    simulated widening of the real reaper changed nothing and the rule looked sound.
    """
    a = _repo(tmp_path / "a", org="O", emits=["x-"], filters=["x-"])
    assert "x-" in describe(a).filters


def test_input_DECLARATIONS_are_not_read_as_values(tmp_path):
    """⛔ `name-prefixes:` under `inputs:` has a `description:` child. A regex over dumped
    YAML read that child as a filter, so df-cicd — which declares the input and passes no
    value — acquired a filter of 'description'."""
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "reusable.yml").write_text(
        "on:\n  workflow_call:\n    inputs:\n      name-prefixes:\n"
        "        description: Comma-separated prefixes\n        required: true\n        type: string\n"
        "jobs:\n  noop:\n    runs-on: ubuntu-latest\n    steps:\n      - run: 'true'\n"
    )
    described = describe(tmp_path)
    assert described.filters == frozenset(), described.filters
    assert described.orgs == frozenset(), described.orgs


def test_no_prefix_list_is_hardcoded():
    """★ TEAMLEAD's constraint: derive the population, do not restate it.

    A literal list of known prefixes inherits every gap in the list on the day it is
    written. The only literals allowed are YAML schema words, which are excluded FROM
    matches rather than being a population.
    """
    import ast

    source = MODULE.read_text()
    tree = ast.parse(source)
    # ⚠ EXCLUDE DOCSTRINGS AND COMMENTS. The module's docstring cites the real prefixes as
    # EVIDENCE — that is the measurement it rests on, and stripping it from the record to
    # satisfy a lint would be removing the reason the rule exists. What must not appear is
    # a prefix in CODE, where it would become a population.
    doc_spans = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            doc_spans.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))
    for suspect in (
        "akash-",
        "df-core-",
        "just-akash-",
        "akash-ci-",
        "akash-integration-",
    ):
        occurrences = [
            f"{i}: {line.strip()[:70]}"
            for i, line in enumerate(source.splitlines(), 1)
            if suspect in line
            and not line.strip().startswith("#")
            and i not in doc_spans
        ]
        assert not occurrences, (
            f"{suspect!r} appears in CODE, not commentary — the population is being "
            f"restated rather than derived: {occurrences}"
        )


# ── non-vacuity ──────────────────────────────────────────────────────────────


def test_a_single_repo_cannot_produce_a_collision(tmp_path):
    """Floor: a collision is a relation BETWEEN repos. One repo is not a population."""
    a = _repo(tmp_path / "a", org="O", emits=["akash-"], filters=["akash-"])
    assert check([describe(a)]) == []


@pytest.mark.parametrize("count", [0, 1])
def test_fewer_than_two_repos_is_reported_not_passed(tmp_path, count):
    """The CLI must refuse, not print PASS — a green over one repo answers nothing."""
    import subprocess

    roots = []
    for i in range(count):
        roots.append(
            str(_repo(tmp_path / f"r{i}", org="O", emits=["x-"], filters=["x-"]))
        )
    result = subprocess.run(
        [sys.executable, "-m", "akash_runner.check_sibling_prefix_collisions", *roots],
        capture_output=True,
        text=True,
        cwd=str(MODULE.parents[1]),
    )
    if count == 0:
        assert result.returncode != 0
    else:
        assert result.returncode == 1, result.stdout + result.stderr
        assert "cannot be detected in fewer than two" in (result.stdout + result.stderr)
