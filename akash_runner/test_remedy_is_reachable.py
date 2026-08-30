"""A remedy printed to a consumer must be performable BY that consumer.

⛔ MEASURED 2026-08-30 (DEV2-blazing, G4). `check_schedule_inputs_are_empty` told its reader:

    "... or add the workflow to SCHEDULE_INPUT_EXEMPT with a reason."

`SCHEDULE_INPUT_EXEMPT` is a module-level dict in THIS repo's rule file. A consumer repo runs
the rule through the composite action and cannot edit it. So half the advertised remedy did
not exist on the side of the boundary where the message is read, and nothing failed — no test
asserted the message text at all, which is why it survived.

⚠ These tests are keyed to the PROPERTY, not to today's wording. A test that pinned the exact
old string would have gone permanently red the moment the string was fixed, and a test that
greps for the current sentence disarms itself the next time someone rewords it.
"""

from __future__ import annotations

import re
from pathlib import Path

RULE = Path(__file__).with_name("check_schedule_inputs_are_empty.py")
UPSTREAM = "akash-github-runner"


def _emitted_message_text() -> str:
    """Only the string literals the rule actually PRINTS, via AST.

    ⛔ NOT a grep of the file, and not "the file minus comment lines". Measured while writing
    this test: both of those match the module DOCSTRING, which quotes the vulnerable pattern
    on purpose —

        line 2:  \"\"\"A schedule supplies no inputs, so `inputs.X || \'false\'` means "destroy"...
        line 7:  DRY_RUN: ${{ github.event.inputs.dry_run || \'false\' }}

    — so the guard fired on the rule's own illustration of the bug it detects. A rule that
    cannot quote its subject cannot document it. The emitted message is the only surface a
    consumer reads, so it is the only surface this asserts against.
    """
    import ast

    tree = ast.parse(RULE.read_text())
    out: list[str] = []
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call) and getattr(node.func, "id", None) == "print"
        ):
            continue
        for arg in ast.walk(node):
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                out.append(arg.value)
    assert out, (
        "no print() string literals found — the extractor is broken, not the rule"
    )
    return "\n".join(out)


def test_the_exemption_is_advertised_with_where_it_lives() -> None:
    """If the message names the exemption, it must also say it is upstream-only."""
    text = _emitted_message_text()
    if "SCHEDULE_INPUT_EXEMPT" not in text:
        return  # the message no longer offers it at all — also a valid resolution
    assert UPSTREAM in text, (
        "the message offers SCHEDULE_INPUT_EXEMPT as a remedy but never says the dict lives "
        f"in {UPSTREAM}. A consumer cannot edit it, so the remedy is unreachable from where "
        "the message is read."
    )


def test_the_suggested_boolean_expression_does_not_invert_an_explicit_false() -> None:
    """`inputs.X || 'true'` turns a deliberate "go live" into a dry run.

    For `type: boolean`, an unchecked box is the value `false`, and `false || 'true'` is
    `'true'`. The safe chain spells both arms: `(inputs.X && 'true' || 'false')`.
    """
    text = _emitted_message_text()
    bad = re.findall(r"inputs\.[A-Za-z0-9_-]+\s*\|\|\s*'(?:true|false)'", text)
    assert not bad, (
        f"suggested expression inverts an operator's explicit choice: {bad}. "
        "For a boolean input use (inputs.X && 'true' || 'false')."
    )


def test_the_control_can_actually_fire() -> None:
    """⛔ NON-VACUITY, against a FIXTURE — never against the live rule file.

    Keying this to the real offenders would make it die the moment they are fixed. The
    fixture is permanent, so the matcher stays proven for every future rewording.
    """
    unreachable = "or add the workflow to SCHEDULE_INPUT_EXEMPT with a reason."
    assert UPSTREAM not in unreachable, "fixture must reproduce the unreachable shape"

    inverting = "${{ github.event_name == 'schedule' && 'false' || (inputs.dry-run || 'true') }}"
    assert re.findall(r"inputs\.[A-Za-z0-9_-]+\s*\|\|\s*'(?:true|false)'", inverting), (
        "the inversion matcher does not fire on the exact expression measured in blazing#786"
    )

    safe = "${{ github.event_name == 'schedule' && 'false' || (inputs.dry-run && 'true' || 'false') }}"
    assert not re.findall(r"inputs\.[A-Za-z0-9_-]+\s*\|\|\s*'(?:true|false)'", safe), (
        "the matcher fires on the CORRECT form — it would block the fix it is asking for"
    )


# ── agr#54: the rule read its own subject's COMMENTS as evidence ────────────────────────


def _write(tmp_path, body: str):
    p = tmp_path / "reaper.yml"
    p.write_text(body)
    return p


_SCHEDULED = """on:
  schedule:
    - cron: "0 * * * *"
  workflow_dispatch:
    inputs:
      dry-run:
        type: boolean
jobs:
  sweep:
    runs-on: ubuntu-latest
    steps:
      - run: echo hi
        env:
"""


def test_a_comment_quoting_the_defect_is_not_the_defect(tmp_path) -> None:
    """The documented FIX must not be reported as the bug it documents."""
    from check_schedule_inputs_are_empty import check_workflow

    p = _write(
        tmp_path,
        _SCHEDULED
        + "          # ⛔ the previous `${{ inputs.dry-run || 'false' }}` selected the\n"
        "          # DESTRUCTIVE path on every cron firing.\n"
        "          DRY_RUN: ${{ github.event_name == 'schedule' && 'false'"
        " || (inputs.dry-run && 'true' || 'false') }}\n",
    )
    assert check_workflow(p) == [], (
        "a comment quoting the old expression was reported as the finding — the rule's "
        "verdict depends on how the fix is described, and the workaround is to not explain it"
    )


def test_the_real_defect_is_still_caught(tmp_path) -> None:
    """⛔ NON-VACUITY. Stripping comments must not blind the rule to a live expression."""
    from check_schedule_inputs_are_empty import check_workflow

    p = _write(
        tmp_path, _SCHEDULED + "          DRY_RUN: ${{ inputs.dry-run || 'false' }}\n"
    )
    assert check_workflow(p), (
        "comment stripping silenced a REAL fall-through expression — the fix is worse "
        "than the bug it replaces"
    )


def test_an_expression_sharing_a_line_with_a_trailing_hash_survives(tmp_path) -> None:
    """Only WHOLE-LINE comments are dropped; a trailing `#` must not eat the line."""
    from check_schedule_inputs_are_empty import check_workflow

    p = _write(
        tmp_path,
        _SCHEDULED + "          DRY_RUN: ${{ inputs.dry-run || 'false' }} # legacy\n",
    )
    assert check_workflow(p), (
        "a trailing comment removed the whole line, hiding a real defect"
    )
