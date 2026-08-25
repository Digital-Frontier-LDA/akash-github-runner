"""Controls on the SHARED corpus, so neither funding rule can regress to raw-text windowing.

⛔ These two fixtures ARE the probes that reproduced #171 against the merged rule. They are
promoted here rather than left in an issue because a defect described in prose is a defect
that comes back. Both must fail if the extractor reverts to raw-file windowing.
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

from workflow_corpus import RunBlock, run_blocks, strip_comments  # noqa: E402

# The four conjuncts the funding-projection rule ANDs together. If any corpus lets these
# co-occur when no single script contains them, every rule built on this module is unsound.
_TOKENS = ("allowance", "sleep 30", "projected", "exit 1")


def _codes(path: Path) -> str:
    """Everything a rule is allowed to match against, concatenated PER BLOCK boundaries."""
    return "\n@@BLOCK@@\n".join(b.code for b in run_blocks(path))


# ═══════════════ THE TWO PROBES FROM #171, AS PERMANENT CONTROLS ═══════════════


def test_PROBE1_four_tokens_present_ONLY_IN_COMMENTS_reach_no_rule(tmp_path):
    """⛔ Reproduced against the merged rule: this exact file was flagged, rc=1.

    Every token a funding rule looks for is here, and the only executable line is an echo.
    """
    p = tmp_path / "prose-only.yml"
    p.write_text(textwrap.dedent("""\
        name: prose only
        on: [workflow_call]
        jobs:
          a:
            runs-on: ubuntu-latest
            steps:
              - name: a step that does nothing of the kind
                run: |
                  # HISTORY, for the reader. This job used to read the allowance, then
                  # sleep 30 and read it again, and compute a projected value from the
                  # delta, and exit 1 when that projection fell under the floor. All of
                  # that was removed. Nothing below samples anything twice.
                  echo "hello"
        """))
    corpus = _codes(p)
    for tok in _TOKENS:
        assert tok not in corpus, f"{tok!r} survived into the corpus from a COMMENT"
    assert "hello" in corpus, "the actual code must still be there — this is not vacuous"


def test_PROBE2_tokens_split_across_FOUR_JOBS_never_share_a_block(tmp_path):
    """⛔ Reproduced against the merged rule: this exact file was flagged, rc=1.

    No job does the thing. A 60-line window over the raw file spans all four.
    """
    p = tmp_path / "split.yml"
    p.write_text(textwrap.dedent("""\
        name: split across jobs
        on: [workflow_call]
        jobs:
          read_only:
            runs-on: ubuntu-latest
            steps:
              - run: echo "allowance is $(get_allowance)"
          waiter:
            runs-on: ubuntu-latest
            steps:
              - run: sleep 30
          reporter:
            runs-on: ubuntu-latest
            steps:
              - run: echo "the projected finish time is 12:00"
          unrelated_failure:
            runs-on: ubuntu-latest
            steps:
              - run: pytest -q || exit 1
        """))
    blocks = run_blocks(p)
    assert len(blocks) == 4, "one block per job, not one window over the file"
    for b in blocks:
        present = [t for t in _TOKENS if t in b.code]
        assert len(present) <= 1, (
            f"job {b.job_id!r} sees {present} — conjuncts must not meet across jobs"
        )


# ═══════════════════════ the properties rules depend on ═══════════════════════


def test_a_comment_is_BLANKED_not_deleted_so_line_numbers_survive(tmp_path):
    """⚠ Deleting comment lines shifts every later report upward: the rule would be right
    and its citation wrong. Measured against a real file, the anchor moved by 4 lines."""
    p = tmp_path / "w.yml"
    p.write_text(textwrap.dedent("""\
        name: w
        on: [workflow_call]
        jobs:
          j:
            runs-on: ubuntu-latest
            steps:
              - run: |
                  echo FIRST
                  # a comment
                  echo SECOND
        """))
    (blk,) = run_blocks(p)
    lines = blk.code.splitlines()
    assert len(lines) == 3, "comment blanked in place, not removed"
    assert lines[1].strip() == "", "the comment's content is gone"
    assert blk.start_line == 8, f"first content line is 8, got {blk.start_line}"
    assert blk.start_line + 2 == 10, "SECOND is on line 10 in the file"


def test_a_trailing_comment_is_stripped_but_the_code_before_it_is_kept():
    out = strip_comments('echo keep-me # drop-me\n')
    assert "keep-me" in out and "drop-me" not in out


def test_the_same_words_in_env_or_a_job_name_are_not_code(tmp_path):
    """Only `run:` is code. A rule must not be satisfiable by editing a description."""
    p = tmp_path / "x.yml"
    p.write_text(textwrap.dedent("""\
        name: deploy_credit spend_limit projected rate
        on: [workflow_call]
        env:
          NOTE: "allowance sleep 30 projected exit 1"
        jobs:
          j:
            name: allowance projected exit 1
            runs-on: ubuntu-latest
            steps:
              - run: echo ok
        """))
    corpus = _codes(p)
    assert corpus.strip() == "echo ok"


def test_a_composite_ACTION_is_scanned_too(tmp_path):
    """⭐ `runs.steps[]`, not `jobs[]`. A funding gate in an action.yml is the same defect
    in a file that a jobs-only extractor cannot see at all."""
    p = tmp_path / "action.yml"
    p.write_text(textwrap.dedent("""\
        name: composite
        runs:
          using: composite
          steps:
            - shell: bash
              run: echo "allowance $(x)"
        """))
    (blk,) = run_blocks(p)
    assert blk.job_id == "runs"
    assert "allowance" in blk.code


def test_unparseable_yaml_RAISES_rather_than_returning_empty(tmp_path):
    """⛔ Returning [] would report 'no findings' for a file nobody read — the vacuous
    green this repo keeps finding. Callers must be forced to decide."""
    bad = tmp_path / "bad.yml"
    bad.write_text("jobs: [unclosed\n")
    with pytest.raises(yaml.YAMLError):
        run_blocks(bad)


def test_a_workflow_with_no_run_blocks_yields_nothing(tmp_path):
    p = tmp_path / "u.yml"
    p.write_text("name: u\non: [push]\njobs:\n  j:\n    uses: ./.github/workflows/other.yml\n")
    assert run_blocks(p) == []


def test_the_block_carries_its_job_and_step_for_reporting(tmp_path):
    p = tmp_path / "w.yml"
    p.write_text(textwrap.dedent("""\
        name: w
        on: [workflow_call]
        jobs:
          alpha:
            runs-on: ubuntu-latest
            steps:
              - run: echo one
              - run: echo two
        """))
    blocks = run_blocks(p)
    assert [(b.job_id, b.step_index) for b in blocks] == [("alpha", 0), ("alpha", 1)]
    assert all(isinstance(b, RunBlock) for b in blocks)
