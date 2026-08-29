"""Every rule must actually RUN, under both spellings, and agree with itself.

⛔ WHY THIS EXISTS — it caught a real break in the change that introduced it. While
converging the CLI conventions, three rules ended up calling `_cli` without importing
it (their `import argparse` is inside a function, so an import inserted at module
level went in the wrong place). `python -m pytest akash_runner` still reported
**523 passed**.

It passed because every other test in this suite reads the rules as TEXT — `ast.parse`,
regex over source, registry membership. Nothing executed `main()`. A rule can therefore
be syntactically perfect, pass its own unit tests, satisfy the call-site registry and
the flag-agreement guard, and still raise `NameError` the moment CI invokes it.

⚠ And the failure would have been invisible in production: the `advisory` wrapper
swallows a non-zero exit, so a rule that crashes on import reports nothing and the job
stays green — the exact "looks invoked, is not" shape this repo exists to detect, one
level up, in the instrument itself.

⇒ A rule that cannot be executed is not a rule. This test executes all of them.
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
FIXTURE_DIR = REPO / ".github" / "workflows"

# `check_sibling_prefix_collisions` takes repo ROOTS, not workflows. It is a different
# KIND of input, not a different spelling of the same one, and giving it the workflows
# convention would be a rule pointed at the wrong population. Exempt, deliberately.
_NOT_WORKFLOW_SCOPED = {"check_sibling_prefix_collisions.py"}


def _kind(script: Path) -> str:
    """dir | file | targets | other — read from the rule's own declaration.

    ⛔ THIS MUST RECOGNISE THE HELPER CALLS, NOT ONLY THE RAW LITERALS. The first
    version of this function keyed on `add_argument("workflows", ...)` string
    constants — the very literals the CLI convergence replaced with
    `_cli.add_dir_target(parser)`. It therefore classified the six converted rules as
    "other" and SKIPPED them: the finder was keyed to the string under change, so it
    disarmed itself on exactly the population it was written for, and reported
    `6 skipped` as though that were coverage.
    """
    text = script.read_text()
    if "_cli.add_file_target" in text:
        return "file"
    if "_cli.add_dir_target" in text or "_cli.add_dir_positional" in text:
        return "dir"
    if "_cli.add_targets_dir_alias" in text:
        return "targets"
    tree = ast.parse(text)
    names: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_argument"
        ):
            names += [a.value for a in node.args if isinstance(a, ast.Constant)]
    if "targets" in names:
        return "targets"
    if "workflow" in names:
        return "file"
    if "--workflows-dir" in names or "workflows" in names:
        return "dir"
    return "other"


RULES = sorted(
    p for p in ROOT.glob("check_*.py") if p.name not in _NOT_WORKFLOW_SCOPED
)


def _run(script: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *args], capture_output=True, text=True, timeout=120
    )


@pytest.mark.parametrize("script", RULES, ids=lambda p: p.name)
def test_rule_runs_under_both_spellings(script: Path) -> None:
    kind = _kind(script)
    if kind == "file":
        target = sorted(FIXTURE_DIR.glob("*.yml"))[0]
        spellings = [[str(target)], ["--workflow-file", str(target)]]
    elif kind in ("dir", "targets"):
        spellings = [[str(FIXTURE_DIR)], ["--workflows-dir", str(FIXTURE_DIR)]]
    else:
        pytest.skip(f"{script.name}: no workflow-scoped target ({kind})")

    codes = []
    for args in spellings:
        proc = _run(script, args)
        # ⛔ 2 is argparse's refusal AND python's uncaught-exception path. Either means
        # the rule did not judge anything. A rule's own verdict is 0 or 1.
        assert proc.returncode != 2, (
            f"{script.name} {' '.join(args)} exited 2 — it judged nothing.\n"
            f"{proc.stderr[-800:]}"
        )
        assert "Traceback" not in proc.stderr, (
            f"{script.name} {' '.join(args)} raised:\n{proc.stderr[-800:]}"
        )
        codes.append(proc.returncode)

    assert codes[0] == codes[1], (
        f"{script.name}: positional gave {codes[0]}, flag gave {codes[1]} — the two "
        f"spellings must be the same call, not two different ones."
    )


def test_the_exclusion_list_cannot_swallow_an_INVOKED_rule() -> None:
    """⛔ THE ONE WAY THIS SUITE'S POPULATION CAN SILENTLY SHRINK.

    `RULES` is `glob("check_*.py")` minus `_NOT_WORKFLOW_SCOPED`. Nothing stopped a
    name from being added to that set — and the cheapest way to make a failing
    invocability test go away is to add the failing rule's name to it. The suite
    then stays green over a population one rule smaller, which is the exact shape
    `test_every_rule_is_invocable` was written to prevent one level down.

    An exclusion is only legitimate for a rule the conformance action does not call.
    If `action.yml` invokes it, it must be covered here — no reason justifies
    excluding a rule that actually runs against consumers.
    """
    action = ROOT.parent / ".github/actions/akash-runner-conformance/action.yml"
    assert action.is_file(), f"the action moved: {action} — re-read this test"
    invoked = set(re.findall(r"(check_[a-z0-9_]+\.py)", action.read_text()))
    assert invoked, "no rule call sites found in action.yml — the shape changed"

    swallowed = sorted(invoked & _NOT_WORKFLOW_SCOPED)
    assert not swallowed, (
        "these rules are INVOKED by the conformance action but excluded from the "
        f"invocability population: {swallowed}. Either cover them here, or remove "
        "the call site — a rule that runs against consumers cannot be exempt from "
        "the test that proves it can be called at all."
    )


def test_the_fixture_is_a_real_population() -> None:
    """Non-vacuity: if the fixture directory were empty every rule above could pass
    while judging nothing, which is the failure mode this file exists to prevent."""
    assert len(list(FIXTURE_DIR.glob("*.yml"))) >= 2, FIXTURE_DIR


def test_there_are_rules_to_run() -> None:
    """The parametrize list must not be silently empty."""
    assert len(RULES) >= 15, [p.name for p in RULES]


def test_no_workflow_scoped_rule_is_classified_other() -> None:
    """⛔ THE ANTI-VACUITY CONTROL FOR THE CLASSIFIER ITSELF.

    A rule that `_kind` cannot classify is SKIPPED above, and a skip reads like a pass.
    Every rule outside the documented exemption must therefore classify to something
    runnable — if a future change alters how targets are declared, this fails rather
    than quietly shrinking the population.
    """
    unclassified = [p.name for p in RULES if _kind(p) == "other"]
    assert not unclassified, (
        f"{len(unclassified)} rule(s) cannot be classified and would be silently "
        f"skipped: {unclassified}"
    )


@pytest.mark.parametrize(
    "script", [p for p in RULES if _kind(p) == "targets"], ids=lambda p: p.name
)
def test_a_targets_rule_refuses_an_empty_target_list(script: Path) -> None:
    """⛔ AN EMPTY POPULATION MUST BE AN ERROR, NOT A PASS.

    These rules declared `nargs="+"`, so argparse itself enforced non-emptiness.
    Adding `--workflows-dir` required relaxing that to `"*"`, which moves the duty into
    `resolve_targets`. If that check is ever lost, the rule runs over ZERO targets and
    reports success — the exact "judged nothing, looked green" shape this suite exists
    to catch. A mutation removing the guard survived until this test existed.
    """
    proc = _run(script, [])
    assert proc.returncode == 2, (
        f"{script.name} accepted an empty target list and exited {proc.returncode} — "
        f"it judged nothing.\n{proc.stdout[-400:]}"
    )
    # ⚠ AND IT MUST BE THE CLI LAYER THAT REFUSED. These rules ALSO carry their own
    # non-vacuity floor ("no workflow files found — the scan is broken, not the repo"),
    # which returns 2 as well. Asserting only the exit code cannot tell the two apart:
    # a mutation deleting the CLI guard SURVIVED that assertion, because the second
    # guard produced the same code. Two independent refusals is good defence in depth —
    # but a test that cannot distinguish them is not testing the one it names.
    # ⛔ WHY A MESSAGE STRING AND NOT THE MACHINE-READABLE MARKER (conformance_exit.py,
    # #35), WHICH EXISTS FOR EXACTLY THIS PROBLEM. Emitting a marker means NOT calling
    # `parser.error()` — and `parser.error()` is what preserves argparse's OWN exit code
    # and stderr shape. That byte-identical refusal is the strongest compatibility
    # property this change has, and agr is consumed CROSS-ORG at a pinned SHA by a repo
    # we cannot coordinate with. The compat is worth more than the brittleness costs.
    #
    # ⚠ AND THE BRITTLENESS IS THE ACCEPTABLE KIND: rewording the message turns this test
    # RED, loudly, rather than silently un-guarding. Do not "improve" this into a marker
    # without first re-proving the argparse-shape compatibility it would forfeit.
    combined = proc.stderr + proc.stdout
    assert "a target is required" in combined, (
        f"{script.name} exited 2, but not from the argument guard this test covers — "
        f"the CLI-level refusal may have been lost:\n{combined[-400:]}"
    )


@pytest.mark.parametrize(
    "script", [p for p in RULES if _kind(p) == "dir"], ids=lambda p: p.name
)
def test_two_different_targets_are_refused(script: Path) -> None:
    """⛔ BOTH SPELLINGS, TWO DIFFERENT PATHS, IS AN ERROR — NOT A PRECEDENCE PUZZLE.

    Silently preferring one would let a caller believe the other path was judged.
    Detecting this needs to know whether the flag was really PASSED, which is not the
    same as whether it is non-None: rules carry their own defaults. A mutation that
    reverted that detection survived until this test existed.
    """
    other = script.parent
    proc = _run(script, [str(FIXTURE_DIR), "--workflows-dir", str(other)])
    assert proc.returncode == 2, (
        f"{script.name} accepted two different targets and exited "
        f"{proc.returncode} — one of them was silently ignored."
    )
