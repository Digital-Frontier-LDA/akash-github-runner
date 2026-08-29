"""Every flag the action PASSES, the rule must ACCEPT.

⛔ WHY THIS EXISTS. The rules do not agree on how to be called. Measured on this tree:
`--workflows-dir` (7), a positional directory (3), a positional FILE (3), a positional
`targets` (2), and rules taking none. Today every call site in
`.github/actions/akash-runner-conformance/action.yml` happens to match its rule, because
each was matched BY HAND when it was added.

That is the whole problem. A rule wired in with the wrong spelling does not fail loudly —
`argparse` exits **2** on an unrecognised argument, the `advisory` wrapper swallows a
non-zero, and the job stays green having judged nothing. It looks invoked. It is not.

It happened: `check_listing_failure_is_loud.py` was authored with `--workflows` while the
action passes `--workflows-dir` to every dir-scoped rule. Caught by a human reading the
diff, which is not a control.

⚠ This test asserts AGREEMENT, not uniformity. Converging the five conventions is a
separate and much larger change; what must never happen again is a call site passing a flag
its rule has never heard of.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[1]
ACTION = ROOT / ".github" / "actions" / "akash-runner-conformance" / "action.yml"

# A rule invocation: optionally `advisory `, optionally `python3 "$ROOT/`, then the script,
# then the rest of the line up to a `||` or end.
_INVOKE = re.compile(
    r"^\s*(?:advisory\s+|python3\s+\"\$ROOT/)?(check_[a-z_0-9]+\.py)\"?(?P<rest>[^\n]*)"
)


_OPAQUE = ("parents=", "parse_known_args")


def _accepted_flags(script: Path) -> set[str] | None:
    """Every `--flag` the module declares to argparse — or None if it cannot be read.

    ⛔ CANNOT-DETERMINE IS NOT DETERMINED-TO-BE-EMPTY. A rule building its parser via
    `parents=`, `parse_known_args`, or `add_argument(*names)` would parse to an EMPTY set,
    and every flag its call site passes would then read as a mismatch — a false positive on
    a correct rule. No rule does this today; the third state exists so the first one to try
    is reported as unanalysable instead of accused.
    """
    text = script.read_text()
    if any(tok in text for tok in _OPAQUE):
        return None
    flags: set[str] = set()
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not (isinstance(fn, ast.Attribute) and fn.attr == "add_argument"):
            continue
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                if arg.value.startswith("-"):
                    flags.add(arg.value)
            elif isinstance(arg, (ast.Starred, ast.Name)):
                return None  # add_argument(*names) — the names are not literals
    return flags


def _invocations() -> list[tuple[str, list[str]]]:
    """(script, [flags passed]) for every rule invoked by the action."""
    out: list[tuple[str, list[str]]] = []
    for line in ACTION.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue  # a commented example is not a call site
        m = _INVOKE.match(line)
        if not m:
            continue
        rest = m.group("rest")
        # ⛔ `--[a-z][a-z-]*` MIS-PARSES rather than misses, which is the worse direction:
        # `--max-2` -> `--max-`, `--workflows_dir` -> `--workflows`, `--Workflows-Dir` -> dropped.
        # A truncated flag is a string no rule declares, so a CORRECT call site is reported as a
        # mismatch — a false positive, which is how a test like this gets deleted rather than
        # fixed. Exactly one distinct flag exists today (`--workflows-dir`), so this is future
        # risk, not present risk; the character class costs nothing.
        passed = re.findall(r"(?<![\w-])(--[A-Za-z][A-Za-z0-9_-]*)", rest)
        out.append((m.group(1), passed))
    return out


def test_the_action_actually_invokes_rules():
    """NON-VACUITY, floored on the quantity that can actually regress.

    ⛔ FLOORING `len(inv)` WOULD NOT HAVE CAUGHT THIS. Measured on this tree: 34 call sites
    parse, and only **9 of them carry a flag** — the other 25 assert nothing, because a rule
    invoked with a positional argument has no flag to check. So a floor of `len(inv) >= 10`
    passes while 25 of 34 are inert, and `any(flags)` is a floor of ONE on a population of
    nine: it survives losing eight.

    The load-bearing number is the FLAG-CARRYING count, and it is floored directly.
    """
    inv = _invocations()
    assert len(inv) >= 10, (
        f"parsed only {len(inv)} invocations from {ACTION.name} — the call-site format moved "
        "and this test is now judging nothing"
    )
    carrying = [(s, f) for s, f in inv if f]
    assert len(carrying) >= 5, (
        f"only {len(carrying)} of {len(inv)} parsed call sites carry a flag (9 on the tree this "
        "was written against). Every flagless invocation asserts NOTHING, so this is the number "
        "that decides whether the suite below is a control or decoration. A drop here means the "
        "flag regex or the call-site format moved — not that the action got simpler."
    )


def test_no_rule_is_silently_unanalysable():
    """A rule whose parser cannot be read must be NAMED, not counted as accepting nothing."""
    opaque = [
        s for s, _ in _invocations()
        if (ROOT / "akash_runner" / s).is_file()
        and _accepted_flags(ROOT / "akash_runner" / s) is None
    ]
    assert not opaque, (
        f"{sorted(set(opaque))} build their argparse indirectly (parents=/parse_known_args/"
        "*names), so their accepted flags cannot be read statically. That is not a failure of "
        "the rule — it is a hole in THIS test's coverage, and it must be visible rather than "
        "silently reported as 'accepts no flags'."
    )


@pytest.mark.parametrize("script,passed", _invocations(), ids=lambda v: v if isinstance(v, str) else "")
def test_every_flag_passed_is_a_flag_the_rule_accepts(script, passed):
    path = ROOT / "akash_runner" / script
    if not path.is_file():
        pytest.skip(f"{script} is referenced but absent; that is check_every_rule's finding")
    accepted = _accepted_flags(path)
    if accepted is None:
        pytest.skip(f"{script} builds its parser indirectly — see test_no_rule_is_silently_unanalysable")
    for flag in passed:
        assert flag in accepted, (
            f"{script} is invoked with {flag!r} and its argparse declares {sorted(accepted) or 'no flags'}. "
            f"argparse exits 2 on an unrecognised argument, and the `advisory` wrapper swallows a "
            f"non-zero exit — so this rule would look invoked and judge NOTHING. Add {flag!r} "
            f"(an alias costs one line) or fix the call site."
        )


def test_a_synthetic_mismatch_is_caught():
    """ANTI-VACUITY, on a FIXTURE rather than on the tree.

    Keying the control to a real offender would make it die the moment the tree is clean —
    and it is clean today. This proves the matcher can still fire.
    """
    accepted = {"--workflows-dir"}
    passed = ["--workflows"]
    assert not all(f in accepted for f in passed), (
        "the agreement predicate accepted a flag the rule does not declare"
    )
