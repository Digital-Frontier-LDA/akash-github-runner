"""Controls for check_context_properties_exist.

The rule exists because TWO measured instances shipped green over nonexistent context
properties (just-akash #182 `github.organization`; #184 `job.workflow_sha` +
`job.workflow_repository`). A rule of this class is only as good as its controls:

  KNOWN-POSITIVE — both real instances MUST be flagged (a rule that cannot catch the
  defects that motivated it is decoration).

  KNOWN-NEGATIVE — valid properties (`github.sha`, `job.status`, `runner.os`) and the
  deliberately-unchecked open vocabularies (`github.event.**`, `needs.*`, `steps.*`,
  `env.*`, `vars.*`, `secrets.*`, `inputs.*`, `matrix.*`) MUST NOT be flagged — a false
  positive on a valid property is worse than a miss, which is why the checked surface
  is exactly the closed, documented vocabularies.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from akash_runner.check_context_properties_exist import offending_expressions

# ── KNOWN-POSITIVE: the two measured instances, verbatim shapes ─────────────────


def test_known_positive_instance_1_github_organization_is_flagged():
    """just-akash #182: six required contexts were green over this line."""
    text = "org: ${{ github.organization }}"
    assert (
        "github.organization",
        "${{ github.organization }}",
    ) in offending_expressions(text)


def test_known_positive_instance_2_job_workflow_sha_and_repository_are_flagged():
    """just-akash #184: every runner was provisioned from main's tip over these two."""
    text = (
        "repository: ${{ job.workflow_repository || 'Digital-Frontier-LDA/just-akash' }}\n"
        "ref: ${{ job.workflow_sha }}"
    )
    props = {prop for prop, _ in offending_expressions(text)}
    assert props == {"job.workflow_repository", "job.workflow_sha"}


# ── KNOWN-NEGATIVE: valid properties and the deliberately unchecked ────────────


@pytest.mark.parametrize(
    "expr",
    [
        "${{ github.sha }}",  # the canonical valid github leaf
        "${{ github.run_id }}",
        "${{ github.workflow_ref }}",  # the property #184's author MEANT
        "${{ job.status }}",
        "${{ runner.os }}",
        "${{ runner.tool_cache }}",
        "${{ strategy.fail-fast }}",  # hyphenated leaf — the regex must accept it
        "${{ strategy.job-index }}",
    ],
)
def test_known_negative_valid_properties_are_not_flagged(expr):
    assert offending_expressions(expr) == []


@pytest.mark.parametrize(
    "expr",
    [
        "${{ github.event.pull_request.number }}",  # event payload: open vocabulary
        "${{ github.event.inputs.dry_run || 'false' }}",
        "${{ needs.deploy.outputs.dseq }}",  # open vocabularies: deliberately
        "${{ steps.provision.outputs.wallet }}",  # not checked — a false positive
        "${{ env.SOMETHING }}",  # here would be worse than a miss
        "${{ vars.RUNNER }}",
        "${{ secrets.GH_RUNNER_PAT }}",
        "${{ inputs.github-org }}",
        "${{ matrix.provider }}",
    ],
)
def test_known_negative_open_vocabularies_are_deliberately_unchecked(expr):
    assert offending_expressions(expr) == []


# ── THE ANCHOR REGRESSION: a job NAME is not a context reference ────────────────
# Measured by TEAMLEAD 2026-08-24: 8 false findings on Blazing-Back, 7 on blazing,
# 0 on df-cicd — every one `needs.deploy-runner.outputs.*` matched as a phantom
# `runner` context because `\b` treats hyphen→letter as a boundary. The finding was
# caused by the job NAME, not the expression.


@pytest.mark.parametrize(
    "expr",
    [
        "${{ needs.deploy-runner.outputs.dseq }}",  # the measured false positive
        "${{ needs.deploy-pool.outputs.dseq }}",  # control: rename -> was already fine
        "${{ needs.setup-job.outputs.x }}",  # same class, `job` root
        "${{ needs.deploy-strategy.outputs.x }}",  # same class, `strategy` root
        "${{ needs.push-github.outputs.x }}",  # same class, `github` root
    ],
)
def test_a_job_name_containing_a_context_word_is_not_a_reference(expr):
    assert offending_expressions(expr) == []


def test_anchored_references_still_match_at_real_boundaries():
    """The anchor must not over-tighten: a context reference at an expression start,
    after `!`, inside parens, or across `&&`/`||`/`,` is still checked."""
    text = "${{ !runner.os }} ${{ (job.status) }} ${{ github.sha && runner.arch }}"
    assert offending_expressions(text) == []  # all valid — and all MATCHED (see below)
    bad = "${{ !runner.osx }} ${{ (job.statusx) }} ${{ github.shax && runner.archx }}"
    props = {prop for prop, _ in offending_expressions(bad)}
    assert props == {"runner.osx", "job.statusx", "github.shax", "runner.archx"}


def test_the_documented_github_leaf_set_matches_the_canonical_count():
    """The leaf set is transcribed from GitHub's contexts reference; a silent pruning
    would widen false positives. Pin its size and a few sentinel members."""
    from akash_runner.check_context_properties_exist import GITHUB_LEAVES

    assert len(GITHUB_LEAVES) >= 39  # transcribed 2026-08-24; pruning shrinks silently
    for sentinel in ("workflow_sha", "workflow_ref", "repository", "sha", "event"):
        assert sentinel in GITHUB_LEAVES


def test_a_full_workflow_file_with_both_instances_fails():
    """The end-to-end shape: a parsed workflow file carrying both measured defects."""
    wf = Path("/tmp/_ctx_control_wf.yml")
    wf.write_text(
        "jobs:\n"
        "  deploy:\n"
        "    steps:\n"
        "      - run: echo\n"
        "        env:\n"
        "          ORG: ${{ github.organization }}\n"
        "          REF: ${{ job.workflow_sha }}\n"
    )
    from akash_runner.check_context_properties_exist import check_workflow

    props = {prop for prop, _ in check_workflow(wf)}
    assert props == {"github.organization", "job.workflow_sha"}
    wf.unlink(missing_ok=True)
