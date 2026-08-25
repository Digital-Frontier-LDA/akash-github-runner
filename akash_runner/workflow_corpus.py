#!/usr/bin/env python3
"""The corpus a workflow rule is allowed to match against: `run:` scripts, comment-free.

⛔ WHY THIS EXISTS, MEASURED 2026-08-24 (#171). `check_funding_projection_is_quantised`
sliced the RAW FILE into 60-line half-overlapping windows. Its four conjuncts then only had
to co-occur somewhere in a 60-line SPAN — not inside one shell script, not inside one job,
and not in code at all. Two probes reproduced it:

  1. All four tokens present ONLY inside a comment, with the code reading `echo "hello"`
     — flagged, `rc=1`.
  2. The four tokens split across FOUR SEPARATE JOBS (an echo, a `sleep 30`, the words
     "projected finish time", an unrelated `pytest || exit 1`) — flagged, `rc=1`.

A rule written to catch "an artefact asserting a property it does not have" that fires on a
sentence describing the defect IS that defect. The same shape bit a sibling guard in
Blazing-Back, which flagged a DOCSTRING as an unclassified DELETE call site and demanded a
comment be registered in a registry of things that actually close deployments.

⇒ Every workflow rule imports THIS. Neither rule owns the other's corpus: two rules with one
importing the other is the two-sources-of-truth shape that has `ci_merge_gate_c_tier.py`
carrying its own EXPECTED_LEGS while never reading the roster, which is why two required
contexts disagree about one leg on the same run.

★ CORPUS AND PATTERN ARE TWO DEFENCES, NOT ONE. This module removes `#` comments; it cannot
remove English that lives inside a quoted string. Run against the real akash-runner.yml, a
bare `rate` pattern matched "delibeRATEly" inside an `echo`. Patterns still need their word
boundaries after this module has done its job.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class RunBlock:
    """One `run:` script, with everything a rule needs to report against it."""

    job_id: str
    step_index: int
    start_line: int
    """1-based line of the script's FIRST CONTENT line — not the `|` indicator."""
    script: str
    """Verbatim, comments included. For reporting only; do not match against it."""
    code: str
    """Comments BLANKED IN PLACE. Same line count as `script`, so offsets still map."""


def strip_comments(script: str) -> str:
    """Blank shell comments, preserving line structure.

    ⚠ BLANKS rather than DELETES, deliberately. A rule that reports a line number computes
    it by counting newlines before the match; deleting comment lines silently shifts every
    subsequent report upward, so the rule would be correct and its citation wrong.
    """
    out: list[str] = []
    for line in script.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#"):
            out.append("")
            continue
        idx = line.find(" #")
        out.append(line[:idx] if idx != -1 else line)
    return "\n".join(out)


def _child(node: yaml.Node | None, key: str) -> yaml.Node | None:
    if not isinstance(node, yaml.MappingNode):
        return None
    for k, v in node.value:
        if isinstance(k, yaml.ScalarNode) and k.value == key:
            return v
    return None


def _steps_of(node: yaml.Node | None) -> yaml.Node | None:
    return _child(node, "steps")


def run_blocks(path: str | Path) -> list[RunBlock]:
    """Every `run:` script in a workflow OR a composite action, structurally.

    Raises `yaml.YAMLError` on unparseable input — callers must treat that as an ERROR and
    never as a pass. Returning [] there would report "no findings" for a file nobody read.
    """
    root = yaml.compose(Path(path).read_text())
    out: list[RunBlock] = []

    containers: list[tuple[str, yaml.Node]] = []
    jobs = _child(root, "jobs")
    if isinstance(jobs, yaml.MappingNode):
        for job_key, job_node in jobs.value:
            if isinstance(job_key, yaml.ScalarNode):
                containers.append((str(job_key.value), job_node))
    # ⭐ Composite actions too: `runs.steps[]`. A funding gate in an action.yml is the same
    # defect in a file `jobs:`-only extraction cannot see.
    runs = _child(root, "runs")
    if runs is not None:
        containers.append(("runs", runs))

    for job_id, container in containers:
        steps = _steps_of(container)
        if not isinstance(steps, yaml.SequenceNode):
            continue
        for i, step in enumerate(steps.value):
            run = _child(step, "run")
            if not isinstance(run, yaml.ScalarNode) or not isinstance(run.value, str):
                continue
            # A block scalar's start_mark sits on the `|`/`>` indicator, so the first line
            # of actual script is the next one. A plain scalar starts where it is marked.
            first = run.start_mark.line + (2 if run.style in ("|", ">") else 1)
            out.append(
                RunBlock(
                    job_id=job_id,
                    step_index=i,
                    start_line=first,
                    script=run.value,
                    code=strip_comments(run.value),
                )
            )
    return out
