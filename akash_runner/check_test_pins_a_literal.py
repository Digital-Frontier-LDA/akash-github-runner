#!/usr/bin/env python3
"""A test that pins the SHAPE of the defect it is supposed to detect.

⛔ THE DEFECT CLASS, MEASURED THREE TIMES TODAY.

The pattern is a test whose assertion message or docstring states a GENERAL
property ("a floating ref breaks the guarantee a pin exists for",
"reusable workflow must invoke the action by a local path"), while the assertion
body pins a single literal expression/path/context-property that happens to
match the buggy form. The test is then GREEN on the defect and RED on the fix,
because the literal that named the bug is no longer present after the fix.
Fixing the bug turns the test red; "fixing the test" (replacing the literal
with the property) makes the bug re-detectable next time. The test holds the
bug in place.

THREE MEASURED INSTANCES.

(1) just-akash `tests/test_runner_pool_workflow.py:339`::
    assert "job.workflow_sha" in ref, (
        f"{label}: ref={ref!r} — a floating ref breaks the guarantee a pin exists for"
    )
`job.workflow_sha` is not a real GitHub context property — the `job` context is
`{check_run_id, container, services, status}`. It resolved to "", checkout took
the default branch, the test was green on every pool it ran against. The fix
was to use `github.workflow_sha` or `github.workflow_ref` — at which point the
literal `job.workflow_sha` no longer appeared in the ref and the assertion went
red. The test was pinning the bug (#184).

(2) df-cicd `akash_runner/test_reusable_conformance_workflow.py:76` (pre-fix)::
    assert not any(u == "./.github/actions/akash-runner-conformance" for u in local), (
        "a bare `./.github/actions/...` resolves inside the CALLER's tree, which has no "
        "such directory — that is #149. Check out df-cicd to a path and reference it "
        "from there."
    )
The assertion message names a PROPERTY (do not pin a caller-relative literal),
but the body compares against the literal. When the fix used a non-caller-
relative path, the literal stopped appearing and the assertion went red on the
fix (#149).

(3) DEVOPS's blank-prefix control, which asserted on a subject that a DIFFERENT
conjunct rejected, so it passed against a mutant that deleted the guard it was
named after. Same shape — the assertion's surface (the literal in the body) is
unrelated to the property the message describes.

⇒ THE RULE. Walk every `tests/test_*.py` and `test_*.py` file under the
consumer's `workflows-dir` (the action's `--workflows-dir` input is the same
directory tree that owns the workflow under test; tests live next to it). For
each `assert` statement, look at the assertion's BODY (the expression after
`assert`) and the message/docstring (the trailing string, or the enclosing
function's docstring). If the body contains a HARD-CODED context property,
path, or `uses:` reference — AND the message/docstring describes a GENERAL
PROPERTY that the literal happens to satisfy — flag it as advisory.

⚠ SCOPE IS DELIBERATELY NARROW. Most literal assertions are legitimate
(expectations of an exact return value, assertions on a fixed test fixture).
The rule fires ONLY where ALL of the following are met:

  (a) the test file lives next to the workflow under test (i.e. it is the
      `*test*.py` form sitting in the same dir as a `*.yml` / `*.yaml` workflow);
  (b) the assertion's BODY contains a `uses:` path, a `${{ }}` expression, or
      a context property at a token boundary (`github.workflow_sha`,
      `job.workflow_repository`, etc.);
  (c) the assertion's MESSAGE or the enclosing function's DOCSTRING describes
      a property that does NOT depend on the specific literal (i.e. the
      message would still be a coherent description of a defect if the literal
      were replaced by another value of the same shape);
  (d) the literal is NOT under a negation (`not in`, `!=`, `assert not …`) —
      an assertion that FORBIDS a literal is the FIX for that defect, not the
      defect itself. Flagging it tells the reader to reintroduce the bug;
  (e) the function or module docstring does NOT declare the test as an
      INTENTIONAL CONTROL — phrases like "known-positive", "known-negative",
      "verbatim", "control", "fixture", "reproduction of a regression" signal
      that the literal is supposed to be there. A rule that flags every rule's
      known-positive fixture flags every well-tested rule, including itself.
      The function NAME (`test_known_positive_X`, `test_known_negative_X`,
      `test_fixture_X`, `test_control_X`) is the most reliable signal because
      the name is required by the test runner, while the docstring is optional.
  (f) the literal is NOT inside a `Set` or `Dict` literal on the RHS of `==`
      / `!=`. When a test compares a function's RETURN VALUE against an
      expected set (``assert props == {"X", ...}``), the literal is the
      expected output, not a defect pin. Flagging it makes the test pass for
      any function output (the expected set is what the test asserts on, so
      removing the literal makes the test vacuous).

DELIBERATELY NOT CHECKED:

  * assertions on PLANNED test fixtures (a fixture may pin a real path that
    the test then verifies; the message is "the fixture must contain X", not
    "the production code must not contain X"). A heuristic that treats every
    test path literal as suspect would flag every test that loads a fixture.
  * assertions on numeric/string return values from a function under test —
    the body and the message BOTH name the exact value being checked.
  * assertions that DO name the literal the same way the message does (a test
    that asserts `"foo" in x` and whose message says `"foo" must be in x` is
    pinning the test's own fixture, not the production code).
  * assertions outside Python `tests/test_*.py` and `test_*.py` files — shell
    tests, Go tests, JavaScript tests are each a separate rule shape.
  * assertions in production code (the rule operates on tests ONLY — a
    production-code literal that the test happens to match is the rule's
    INPUT, not its subject).

⭐ PROMOTE WHEN — a finding should be promoted from `advisory` to `required` if:

  1. A FOURTH measured regression in a different repo lands where the test's
     literal pinned the bug. Three is the budget for "this is a real class",
     four is the budget for "every test file in this org needs to clear it".
  2. The rule has been in `advisory` for one full release cycle AND no
     `required` outcome has been disputed. Until then, `advisory` is the
     deliberate starting severity — the false-positive cost on legitimate
     literal assertions is real (most tests pin literals somewhere), and a
     rule that fires on every fixture-loaded test gets switched off in a week.

⇒ Until one of these fires, the rule stays `advisory`. A rule that does not
block is decoration; a rule that blocks on a five-line idiom nobody has hit
is worse — it gets disabled in a week.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path
from typing import Any

# A ${{ ... }} expression body. Same form as check_context_properties_exist uses.
_EXPR = re.compile(r"\$\{\{(.*?)\}\}", re.S)

# A context property at a token boundary: `<root>.<leaf>` where root is in
# {github, job, runner, strategy, needs, steps, inputs, matrix, env, vars,
# secrets} and leaf is an identifier. ANCHORED — see the loader note in
# check_context_properties_exist.py about why `\b` is not enough (hyphens and
# dots are word-boundary characters too).
_CONTEXT_REF = re.compile(
    r"(?<![\w.\-])(github|job|runner|strategy|needs|steps|inputs|matrix|env|vars|secrets)"
    r"\.([A-Za-z_][A-Za-z0-9_\-]*)"
)

# A path-shaped STRING LITERAL — `./X`, `org/repo`, `org/repo/path`, with
# optional `@ref` and any suffix. The body's Python expression is
# `u == "./.github/actions/foo"` or `"my-org/my-action@v1" in step_uses` —
# there is no `uses:` keyword, only a string value that LOOKS like one.
# This regex matches the value quoted with either `'` or `"` (ast.unparse
# uses single quotes, the original source uses double quotes; we handle both).
_PATH_LITERAL = re.compile(
    r"""['"](\./[^'"]+|[\w][\w.-]*/[\w.-][^'"]*)['"]"""
)

# A context-property token INSIDE A STRING LITERAL. Bare `github.workflow_sha`
# in Python source is the property NAME being tested (legitimate); but
# `"github.workflow_sha"` as a quoted STRING is a fixture value, and a test
# that asserts `"github.workflow_sha" in ref` is pinning the buggy property.
# Same shape as `_PATH_LITERAL`: quoted so it works on ast.unparse output.
_CONTEXT_TOKEN = re.compile(
    r"""['"]((?:github|job|runner|strategy|needs|steps|inputs|matrix|env|vars|secrets)\.[\w-]+)['"]"""
)

# Heuristic: an assertion message that names a property (not the literal)
# contains one of these generic-property words. A test that says "must contain
# foo" is pinning; a test that says "must invoke the action locally" is naming
# a property. The word-list is short on purpose — the rule fires when BOTH the
# body contains a literal AND the message names a property. The alternative
# (a long list of property-shaped words) was tried and produced every fixture
# loader as a false positive.
_PROPERTY_WORDS = (
    "must", "should", "guarantee", "property", "invariant",
    "ensure", "ensures", "never", "always", "every", "each",
)

# Heuristic: a FIXTURE-style message names the literal as the expected value,
# using a precision word. "must equal X", "must be exactly X", "must reference
# X exactly" — these pin a single value, not a property. A test with a
# precision word in its message is asserting the test's OWN expected output,
# not pinning the shape of a defect.
#
# "must be " ALONE is NOT a precision word — "must be pinned", "must be local",
# "must be required" are all property descriptions, not value assertions.
# Only phrases that pair "must" with an equality/identity verb count.
_PRECISION_WORDS = (
    "exactly", "equal to", "equals", "must equal", "must be exactly",
    "must be equal", "matches exactly", "must reference ", "must contain ",
)

# Intent markers — a docstring that declares the test is a CONTROL for another
# rule. A known-positive fixture MUST pin the literal; flagging it inverts the
# conformance-suite incentive. Markers are word-boundary so a property
# description like "checkout it CONTROLS" does NOT trip the allowlist
# (`\bcontrol\b` does not match `controls`, `controlled`, `controller`).
_INTENT_PATTERNS = (
    re.compile(r"\bknown-positive\b", re.I),
    re.compile(r"\bknown-negative\b", re.I),
    re.compile(r"\bknown positive\b", re.I),
    re.compile(r"\bknown negative\b", re.I),
    re.compile(r"\bverbatim\b", re.I),
    re.compile(r"\breproduction of\b", re.I),
    # `reproduces the bug` / `reproduce a regression` / `reproduced today`
    # — phrasings authors naturally write when a test IS the control. The
    # name matcher used to cover some of these via `_function_name_indicates_control`
    # but was removed (#166 rework, OVER-SUPPRESSION); this is the docstring
    # equivalent and is OPT-IN.
    re.compile(r"\breproduce[ds]?\b", re.I),
    re.compile(r"\bcontrol test\b", re.I),
    re.compile(r"\bcontrol for\b", re.I),
    re.compile(r"\bcontrol of\b", re.I),
)

# The other limb: if the message names the LITERAL directly (e.g. the literal
# appears in the message text), the test is asserting a fixture, not pinning
# a defect shape — and we deliberately do not flag it. A literal-in-message
# assertion is the "expected value" pattern.
_LITERAL_IN_MESSAGE_FRAGMENT = re.compile(r"[\"']")


def _ast_asserts(tree: ast.AST) -> list[tuple[ast.stmt, str | None]]:
    """Walk a Python AST, yield every `assert` statement together with the
    message (the second arg of the `assert EXPR, MSG` form), or None."""
    out: list[tuple[ast.stmt, str | None]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assert):
            msg = None
            if node.msg is not None:
                msg = ast.unparse(node.msg)
            out.append((node, msg))
    return out


def _docstring_of(tree: ast.AST, target: ast.stmt) -> str | None:
    r"""Return the most relevant docstring for `target`, in priority order:

    1. the docstring of the function enclosing `target` (PEP 257);
    2. the MODULE-LEVEL docstring (the file's own triple-quoted docstring).

    The module-level case matters because tests often put the property being
    asserted in the file-level docstring rather than per-test. A test whose
    module says "the conformance action must invoke from a local path" and
    whose body pins one specific path IS a defect-pin, even if each test
    function has no docstring of its own.
    """
    # 1. Function-level.
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for child in ast.iter_child_nodes(node):
                if child is target:
                    if (node.body and isinstance(node.body[0], ast.Expr)
                            and node.body[0].value is not None
                            and isinstance(node.body[0].value, ast.Constant)
                            and isinstance(node.body[0].value.value, str)):
                        return node.body[0].value.value
    # 2. Module-level (the file's own docstring).
    if isinstance(tree, ast.Module):
        if (tree.body and isinstance(tree.body[0], ast.Expr)
                and tree.body[0].value is not None
                and isinstance(tree.body[0].value, ast.Constant)
                and isinstance(tree.body[0].value.value, str)):
            return tree.body[0].value.value
    return None


def _assert_body_text(node: ast.stmt) -> str:
    """Source-text-ish representation of the assert's first argument.

    We don't need pixel-perfect source; we need the literal expression text so
    the `uses:` and `${{ }}` matchers can run against it. `ast.unparse` is
    good enough for both: it preserves string literals, identifiers, and the
    shape of attribute accesses.
    """
    if isinstance(node, ast.Assert) and node.test is not None:
        return ast.unparse(node.test)
    return ""


def _names_property(text: str | None) -> bool:
    """True iff `text` describes a property rather than a specific literal."""
    if not text:
        return False
    lowered = text.lower()
    return any(w in lowered for w in _PROPERTY_WORDS)


def _is_precision(text: str | None) -> bool:
    """True iff `text` pins a fixture expected-value rather than a property.

    Precision words (`exactly`, `must be`, `must equal`, `must reference`)
    signal "this exact value is required" — a legitimate fixture assertion.
    A message without precision words but with a property word is the
    defect-pin shape.
    """
    if not text:
        return False
    lowered = text.lower()
    return any(w in lowered for w in _PRECISION_WORDS)


def _is_intent_marker(text: str | None) -> bool:
    """True iff `text` declares the test as a CONTROL for another rule.

    A docstring that says "this is a known-positive reproduction of a
    regression" is asserting that the literal MUST be hard-coded — flagging
    it inverts the conformance-suite incentive. The allowlist is explicit by
    design: a rule that has to GUESS whether a test is a control flags every
    control, which is the failure mode TEAMLEAD called out on #166.

    ⛔ The function NAME is NOT consulted (`test_control_plane_*` is a
    pervasive prefix in this org). A docstring marker is OPT-IN and
    deliberate; a name match is ACCIDENTAL. (#166 rework.)
    """
    if not text:
        return False
    return any(p.search(text) for p in _INTENT_PATTERNS)


def _function_name_indicates_control(tree: ast.AST, target: ast.stmt) -> bool:
    """DEPRECATED — always returns False. Kept as a no-op so callers do not
    have to be edited when the NAME matcher was removed.

    The function-name check was the source of the OVER-SUPPRESSION failure
    mode TEAMLEAD caught on #166 rework: `test_control_plane_*` is a
    pervasive prefix in this org, and a substring matcher on `control` would
    silently exempt an entire live namespace. The docstring-only check is
    OPT-IN and deliberate. The next person who adds this back MUST also add
    the `test_control_plane_name_does_not_exempt_finding` control so the
    next person who re-widens the matcher is caught.
    """
    return False


def _parent_map(root: ast.AST) -> dict[int, ast.AST]:
    """Build id(node) -> parent map for the subtree rooted at `root`."""
    out: dict[int, ast.AST] = {}
    for parent in ast.walk(root):
        for child in ast.iter_child_nodes(parent):
            out[id(child)] = parent
    return out


def _literal_is_negated(test_node: ast.expr, literal_value: str) -> bool:
    """True iff the literal at `literal_value` appears under a negation.

    Three shapes the rule deliberately skips:

      1. ``assert not any(... == LITERAL ...)`` — the assertion FORBIDS the
         literal; flagging it tells the reader to reintroduce #149.
      2. ``assert LITERAL not in container`` — the literal is on the negated
         side of ``not in``.
      3. ``assert X != LITERAL`` — the literal is on the negated side of
         ``!=``.

    A test that pins the literal on the POSITIVE side (`assert X == LITERAL`,
    `assert LITERAL in container`) is the defect-pin shape — those still fire.
    """
    pm = _parent_map(test_node)
    for node in ast.walk(test_node):
        if not (isinstance(node, ast.Constant) and node.value == literal_value):
            continue
        cur = node
        while id(cur) in pm:
            cur = pm[id(cur)]
            # `not any(...)` — UnaryOp wrapping the literal's containing
            # expression. The literal is anywhere inside the operand.
            if isinstance(cur, ast.UnaryOp) and isinstance(cur.op, ast.Not):
                return True
            # `X not in container` or `X != Y` — Compare with a negated op.
            if isinstance(cur, ast.Compare):
                for op in cur.ops:
                    if isinstance(op, ast.NotIn) and id(node) == id(cur.left):
                        return True
                    if isinstance(op, ast.NotEq) and id(node) in {
                        id(c) for c in cur.comparators
                    }:
                        return True
        return False  # only the FIRST matching literal — others are noise
    return False


def _literal_is_in_expected_value(test_node: ast.expr, literal_value: str) -> bool:
    """True iff the literal is inside a `Set` / `Dict` literal on the RHS of
    an equality comparison (``==`` or ``!=``).

    The expected-value shape::

        bad = "...literal..."                 # fixture
        result = func(bad)                    # function call
        assert result == {"literal", ...}     # expected output

    The literal IS the expected return value, not a defect pin. Flagging it
    makes the test pass for any function output (the expected set is what
    the test asserts on, so removing the literal from it makes the test
    vacuous). (#166 HOLD, EXPECTED-VALUE BLINDNESS.)
    """
    pm = _parent_map(test_node)
    for node in ast.walk(test_node):
        if not (isinstance(node, ast.Constant) and node.value == literal_value):
            continue
        cur = node
        while id(cur) in pm:
            cur = pm[id(cur)]
            # Walk up to a Compare whose RIGHT side contains a Set/Dict
            # literal holding this constant.
            if isinstance(cur, ast.Compare):
                op = cur.ops[0] if cur.ops else None
                if isinstance(op, (ast.Eq, ast.NotEq)):
                    for cmp in cur.comparators:
                        if (
                            isinstance(cmp, (ast.Set, ast.Dict))
                            and any(
                                id(el) == id(node)
                                for el in ast.walk(cmp)
                                if isinstance(el, ast.Constant)
                            )
                        ):
                            return True
                # Found a Compare, didn't match — stop climbing.
                return False
            if isinstance(cur, (ast.Set, ast.Dict)):
                # The literal IS inside a Set/Dict, no enclosing Compare —
                # treat as expected-value (rare; defensive).
                return True
            if isinstance(cur, ast.Call):
                # The literal is inside a function call's args — the test
                # may be using it as a key in a dict literal argument.
                # Don't keep climbing past the call.
                return False
        return False
    return False


def _names_literal(text: str | None, body_text: str) -> bool:
    """True iff `text` names the literal in `body_text` directly.

    Heuristic: any single-quoted or double-quoted fragment in the message text
    that also appears verbatim in the body. A test that says
    `'"./actions/foo" must be in u' is naming the literal; a test that says
    `"must invoke locally"` is not.
    """
    if not text:
        return False
    for m in _LITERAL_IN_MESSAGE_FRAGMENT.finditer(text):
        # Take a balanced-ish slice from each quote.
        i = m.end()
        depth = 0
        while i < len(text):
            ch = text[i]
            if ch in "\"'":
                break
            if ch in "()[]":
                depth += 1
            elif ch in ")]" and depth > 0:
                depth -= 1
            i += 1
        frag = text[m.start():i]
        if len(frag) >= 4 and frag in body_text:
            return True
    return False


def _assertion_signals(body_text: str) -> dict[str, Any]:
    """Detect the literal shape inside the assert body.

    Returns a dict with keys: has_uses_literal (str | None), has_expression (str
    | None), has_context_property (str | None). Any one being non-None is the
    condition for the body to contain a literal.

    Detection rules:

    * `has_uses_literal`: a quoted path-shaped string (matches `./X` or
      `org/repo[/...]`) — the assertion body pins a specific workflow action
      path.
    * `has_context_property`: a quoted string that IS a GitHub context-property
      token (`github.X`, `job.X`, etc.). Bare `github.workflow_sha` as a Python
      identifier is the property NAME; `"github.workflow_sha"` as a string is
      the property VALUE pinned in a fixture, which is what the test asserts on.
    * `has_expression`: a `${{ ... }}` expression literal — the assertion body
      pins a specific GitHub Actions expression.
    """
    out: dict[str, Any] = {
        "has_uses_literal": None,
        "has_expression": None,
        "has_context_property": None,
    }
    m = _PATH_LITERAL.search(body_text)
    if m:
        out["has_uses_literal"] = m.group(1)
    m = _EXPR.search(body_text)
    if m:
        out["has_expression"] = m.group(0)
    m = _CONTEXT_TOKEN.search(body_text)
    if m:
        out["has_context_property"] = m.group(1)
    return out


def check_file(path: Path) -> list[tuple[str, int, str]]:
    """Inspect one test file. Returns a list of (kind, line, message)."""
    try:
        src = path.read_text()
        tree = ast.parse(src, filename=str(path))
    except (SyntaxError, OSError):
        return []
    out: list[tuple[str, int, str]] = []
    for assert_node, msg in _ast_asserts(tree):
        body_text = _assert_body_text(assert_node)
        if not body_text:
            continue
        signals = _assertion_signals(body_text)
        if not any(signals.values()):
            continue
        # The body pins a literal. The rule fires only if the message/docstring
        # describes a PROPERTY (not the literal) AND the message does not name
        # the literal directly (which would mean the test is asserting a
        # fixture, not pinning a defect shape).
        docstring = _docstring_of(tree, assert_node)
        # INTENT allowlist — a control test whose docstring says "this is a
        # known-positive reproduction" MUST contain the literal; flagging it
        # inverts the conformance-suite incentive (#166 HOLD). The check
        # covers two surfaces, in order of reliability:
        #
        #   1. the function docstring (PEP 257) — OPT-IN: the author had to
        #      type a phrase like "reproduces the bug" or "known-positive
        #      control", which is deliberate.
        #   2. the assertion message.
        #
        # ⛔ The function NAME is NOT consulted. `test_control_plane_*` is a
        # pervasive prefix in this org (control-plane/api/…, tests/control_plane/…,
        # test_control_plane_*); a substring match on `control` would silently
        # exempt an entire live namespace. A docstring marker is OPT-IN and
        # deliberate; a name match is ACCIDENTAL — the test runner required
        # the name, so the rule cannot tell from the code whether the author
        # meant it. (#166 rework, OVER-SUPPRESSION.)
        if _is_intent_marker(docstring) or _is_intent_marker(msg):
            continue
        prop_in_msg = _names_property(msg) or _names_property(docstring)
        if not prop_in_msg:
            continue
        # A message with a PRECISION word ("exactly", "must equal", "must be")
        # signals a fixture: the literal IS the expected value, not a pinned
        # defect. Skip these so the rule fires only on defect-pin shape.
        if _is_precision(msg) or _is_precision(docstring):
            continue
        if _names_literal(msg, body_text):
            continue
        # NEGATION guard — an assertion that FORBIDS a literal is the FIX for
        # that defect, not the defect itself. Flagging `assert not any(u == X)`
        # tells the reader to reintroduce the bug (#166 HOLD, NEGATION
        # BLINDNESS).
        literal_value = (
            signals["has_uses_literal"]
            or signals["has_context_property"]
        )
        if literal_value and _literal_is_negated(
            assert_node.test, literal_value
        ):
            continue
        # EXPECTED-VALUE guard — when the literal appears inside a `Set` or
        # `Dict` literal on the RHS of `==` / `!=`, the test is asserting the
        # function's RETURN VALUE against an expected set, not pinning a
        # defect shape. Pattern::
        #
        #     bad = "...literal..."                    # fixture
        #     props = func(bad)                        # function call
        #     assert props == {"literal", ...}         # expected output
        #
        # The literal is the EXPECTED value of the function, not the SHAPE
        # of the bug. Flagging it tells the reader to remove the literal
        # from the expected set — which makes the test pass for ANY function
        # output, breaking the test. (#166 HOLD, EXPECTED-VALUE BLINDNESS.)
        if literal_value and _literal_is_in_expected_value(
            assert_node.test, literal_value
        ):
            continue
        kind = (
            "uses-literal" if signals["has_uses_literal"] else
            "expression-literal" if signals["has_expression"] else
            "context-property"
        )
        what = (
            signals["has_uses_literal"] or signals["has_expression"]
            or signals["has_context_property"]
        )
        line = assert_node.lineno
        out.append((kind, line, what, docstring or msg or ""))
    return [(k, l, w) for k, l, w, _ in out]


def check_workflow(path: Path) -> list[tuple[str, int, str]]:
    """Conformance-action entry point: inspect the test file at `path`.

    The action globs `*.yml` and `*.yaml` under `workflows-dir`; a test file
    that lives next to a workflow is the natural input. The rule deliberately
    does NOT walk the whole repo — its subject is a test NEXT TO a workflow,
    and the action's `--workflows-dir` already names that scope.
    """
    return check_file(path)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workflows-dir", default=".github/workflows")
    args = ap.parse_args(argv)

    d = Path(args.workflows_dir)
    if not d.is_dir():
        print(f"::warning::{d} is not a directory — nothing to check")
        return 0

    files = (
        sorted(d.glob("*.yml"))
        + sorted(d.glob("*.yaml"))
        + sorted(d.glob("test_*.py"))
        + sorted(d.glob("tests/test_*.py"))
    )
    bad = 0
    for p in files:
        for kind, line, what in check_workflow(p):
            bad += 1
            print(
                f"::warning file={p}::{kind} at line {line} pins the literal {what!r} "
                f"while the message/docstring describes a property — a fix that replaces "
                f"the literal will turn the assertion red. Rewrite the assertion so its "
                f"body matches the property, not the specific token."
            )
    if bad:
        print(
            f"::warning::Found {bad} test(s) whose assertion pins the literal of the "
            f"defect it is supposed to detect. The rule is advisory — promote to "
            f"required only after a release cycle of measured behaviour per #161."
        )
    print(f"OK: scanned {len(files)} workflow/test file(s) for test-pin defects.")
    return 0


if __name__ == "__main__":
    sys.exit(main())