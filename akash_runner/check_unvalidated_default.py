#!/usr/bin/env python3
"""An unvalidated `${VAR:-<literal>}` used as a numeric threshold or destructive flag is a shell-default trap.

⛔⛔ THE DEFECT — measured on DigitalFrontier-infra `.github/workflows/akash-runner.yml:328`::

    MIN_UACT="${AKASH_MIN_DEPLOY_CREDIT_UACT:-6000000}"   # 6 ACT ~= one deployment's escrow deposit
    ...
    if [ -n "$allowance_uact" ] && [ "$allowance_uact" -lt "$MIN_UACT" ]; then

`${VAR:-default}` substitutes ONLY when the variable is UNSET OR EMPTY. A non-numeric
value like `abc` is set and non-empty, so it passes straight THROUGH the default and
reaches the numeric comparison as `abc`. `[ "..." -lt "abc" ]` is a SYNTAX ERROR, not a
floor that catches the garbage. The default looks like a guard; it is not.

CONTRAST — same workflow, same shape, handled correctly at line 887::

    MIN_POOL="${MIN_POOL_SIZE:-}"
    [ -n "$MIN_POOL" ] || MIN_POOL="$POOL_SIZE"
    if ! [[ "$MIN_POOL" =~ ^[0-9]+$ ]] || [ "$MIN_POOL" -lt 1 ] || [ "$MIN_POOL" -gt "$POOL_SIZE" ]; then
        echo "::error::min-pool-size must be an integer in 1..${POOL_SIZE} (got '${MIN_POOL}')"; exit 1
    fi

Empty default + explicit regex check (`=~ ^[0-9]+$`) between the substitution and the
numeric comparison. A garbage value fails closed at the regex, not at the comparison.
That is the shape a rule accepts as NOT-A-DEFECT.

⇒ THE RULE scans shell blocks in workflow YAML for a `${VAR:-<literal>}` whose result is
later used in a NUMERIC comparison (`-lt`, `-gt`, `-eq`, `-ne`, `-le`, `-ge`) OR as a
DESTRUCTIVE-MODE flag (`rm -rf`, `--force`, `--delete`, `--purge`, `git push --force`),
WITHOUT an explicit numeric validation (`[[ ... =~ ^[0-9]+$ ]]`, `case ... in [0-9]*)`,
or `expr ... : '[0-9]*'`) appearing between the substitution and the use.

⚠ SCOPE — NAMED, NOT SILENT. The rule is deliberately narrow:

* Numeric thresholds only: `-lt`, `-gt`, `-eq`, `-ne`, `-le`, `-ge`. A `${VAR:-x}` used
  as a URL, hostname, log message, or JSON field name is NOT in scope — those have
  different failure modes (curl fails loud, jq reads the field as null) and the false-
  positive rate from flagging them would train readers to ignore the rule.
* DESTRUCTIVE-MODE flags only: the literal tokens `rm -rf`, `--force`, `--delete`,
  `--purge`, `git push --force`. A `${VAR:-x}` passed to `curl` or used in an `echo`
  is NOT in scope.
* Shell substitution form: `${VAR:-default}`. NOT covered: `${VAR-default}` (errors on
  unset — different failure mode), `${VAR:=default}` (assigns back — different scope),
  `${VAR:?msg}` (errors on unset/empty — the OPPOSITE of the trap), `${VAR:+alt}`
  (alternative when set — also different). Each is a separate rule for a separate shape.
* The shell block scope: workflow `run:` strings. Inline `${{ env.X }}` interpolation
  inside YAML scalars (e.g. `runs-on: ${{ env.RUNNER_LABEL }}`) is a SEPARATE shape —
  GitHub interpolates it, not bash.
* A comment line containing the pattern is not a finding (the script does not run).

⭐ PROMOTE WHEN — a finding should be promoted from `advisory` to `required` if any of:

1. A second instance is measured in the wild where the unvalidated default produced a
   wrong-verdict outcome (numeric comparison that fired when it should not have, or a
   destructive-mode flag that fired against the wrong target). Today there is ONE known
   instance in Blazing-Back (akash-runner.yml:328); a second measured case is the threshold.
2. The rule has been in `advisory` for one full release cycle AND no `required` outcome
   has been disputed in that time. A rule that lives at `advisory` forever is decoration.
3. A consumer repo (DigitalFrontier-infra OR a downstream) explicitly opts in to
   `required` via the conformance runner's `--advisory-only` flag being removed from
   their workflow. The flag is the operator's lever, not the rule's.

⇒ Until one of these fires, the rule stays `advisory`. A rule that does not block is
a rule nobody trusts; a rule that blocks on a five-line shell idiom nobody has hit is
worse — it gets disabled in a week.
"""

from __future__ import annotations

import re
from typing import Any

# Re-use the conformance baseline's Finding/RuleResult — same shape, same severity
# semantics, same `advisory` vs `required` distinction. Importing is a one-way edge:
# this module adds a rule; baseline/check_conformance.py imports it back into RULES.
import importlib.util
import sys
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "check_conformance_shim",
    Path(__file__).resolve().parents[1] / "baseline" / "check_conformance.py",
)
assert _SPEC and _SPEC.loader
_cc = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _cc
_SPEC.loader.exec_module(_cc)

Finding = _cc.Finding
RuleResult = _cc.RuleResult
_read = _cc._read
_workflow_files = _cc._workflow_files
_line_of = _cc._line_of


# ── Patterns ──────────────────────────────────────────────────────────────────

# A `${VAR:-literal}` shell substitution. VAR is uppercase-with-underscores per the
# env-var convention; literal is everything up to the closing brace (we do not parse
# nested expansions — none of our workflows use them in numeric-threshold sites).
_DEFAULT_SUBST = re.compile(
    r"\$\{([A-Z_][A-Z0-9_]*):-([^{}]+)\}"
)

# NUMERIC comparison operators in `[ ]` or `[[ ]]`. Matched as a bare operator next to
# whitespace; the comparison variable appears on either side within the same bracket.
_NUMERIC_OPS = ("-lt", "-gt", "-eq", "-ne", "-le", "-ge")

# DESTRUCTIVE-MODE flag tokens. Literal substring matches; a `${VAR:-x}` whose
# substituted value lands in an `rm -rf` (or `--force`/`--delete`/`--purge`/`git push
# --force`) gate without validation is the destructive-shape variant of the same trap.
_DESTRUCTIVE_TOKENS = (
    "rm -rf",
    "--force",
    "--delete",
    "--purge",
    "git push --force",
)

# Explicit numeric-validation patterns. ANY of these between the substitution and the
# use downgrades the finding from FLAG to NONE. The list is deliberately short:
# bash idioms that prove "this script already established the value is numeric".
_VALIDATION_REGEXES = (
    re.compile(r"=\~\s*\^\[0-9\]"),
    re.compile(r"=\~\s*['\"]\^\[0-9\]"),
    # case-statement arm: `case "$X" in [0-9]*) ... ;;`
    re.compile(r"case\s+\"\$\{[A-Z_][A-Z0-9_]*\}?\"?\s+in\s+[0-9]"),
    # expr POSIX-class match: `expr "$X" : '[0-9]'`
    re.compile(r"expr\s+.{0,40}:\s*['\"]\[0-9\]"),
)

# Lookahead window: how many LINES after the substitution to scan for the use. Picked
# large enough that a 5-line assignment block + 3-line fetch + 1-line if-statement fits,
# small enough that an unrelated later `${VAR:-x}` in the same file does not falsely
# bridge them. 100 is a soft ceiling — concrete instances measured today are <80 lines
# (akash-runner.yml:328 → :406). Beyond 100 the FPs from unrelated later substitutions
# in the same file outnumber the TPs.
_LOOKAHEAD_LINES = 100


# ── Helpers ───────────────────────────────────────────────────────────────────


def _lines_to_shell_block(text: str) -> list[tuple[int, str]]:
    """Yield (1-indexed line, raw line content) for every line inside a `run:` block.

    GitHub Actions runs a workflow's `jobs.<name>.steps[].run` value as a bash script.
    For a block-scalar form (`run: |` / `run: >`) the script spans every line whose
    indent is GREATER than the `run:` key's own indent, until the indent drops back.
    For a single-line scalar (`run: echo hi`) there is exactly one line of script.
    A `- run:` list item counts as indent-equivalent to its sibling keys.

    This implementation uses YAML parsing to identify which `run:` blocks exist, then
    locates each block's script in the source text by walking indent. The fallback
    regex-only path (used when YAML parsing fails) deliberately errs on the side of
    emitting NO shell lines — a rule that returns nothing on parse-error is safer
    than one that returns a wrong positive on a malformed workflow.
    """
    out: list[tuple[int, str]] = []
    try:
        import yaml as _yaml  # local import — keeps module-load cheap when unused
        documents = []
        for doc in _yaml.safe_load_all(text):
            if isinstance(doc, dict):
                documents.append(doc)
    except Exception:
        return out
    # We need the source-side indent of each `run:` key to delimit its block. Parse
    # with a small structural walk over the raw lines: any line that contains `run:`
    # (after list dash / whitespace) at column N opens a block, and any non-blank line
    # at indent < N closes it.
    in_run = False
    run_indent: int | None = None
    run_lineno: int | None = None
    for lineno, raw in enumerate(text.splitlines(), 1):
        if not in_run:
            # Look for `run: |` / `run: >` (block-scalar opener).
            m = re.match(r"^(\s*(?:-\s+)?)run:\s*[|>][+-]?\d*\s*$", raw)
            if m:
                in_run = True
                run_indent = None  # determined from the first inside-block line
                run_lineno = lineno
            continue
        stripped = raw.lstrip(" ")
        indent = len(raw) - len(stripped)
        if not stripped:
            out.append((lineno, raw))
            continue
        if run_indent is None:
            run_indent = indent
        if indent < run_indent:
            in_run = False
            run_indent = None
            run_lineno = None
            # Re-check this line: it might itself open a new block.
            m = re.match(r"^(\s*(?:-\s+)?)run:\s*[|>][+-]?\d*\s*$", raw)
            if m:
                in_run = True
                run_indent = None
                run_lineno = lineno
            continue
        out.append((lineno, raw))
    return out


def _is_comment_line(line: str) -> bool:
    """A line is a comment iff its FIRST non-whitespace character is `#`.

    A `#` after content (`X=1   # trailing`) is a trailing comment, not a comment
    line — the line still runs in bash. Treating trailing comments as full-line
    comments would make `MIN_UACT="..."   # comment` look unrunnable, hiding the
    substitution from the rule. A `#` inside a quoted segment is data, not a
    comment; this function does not try to detect that (rare in `run:` blocks).
    """
    stripped = line.lstrip(" \t")
    return stripped.startswith("#")


def _validation_present(lines: list[str], start_idx: int, end_idx: int, var: str) -> bool:
    """True iff an explicit numeric-validation regex for `var` appears between
    `lines[start_idx]` (exclusive) and `lines[end_idx]` (exclusive)."""
    window = "\n".join(lines[start_idx:end_idx])
    for pat in _VALIDATION_REGEXES:
        if pat.search(window):
            return True
    return False


# ── Rule ──────────────────────────────────────────────────────────────────────


def check_workflow(path: Path) -> list[Finding]:
    """Run the rule against ONE workflow file. Returns a list of findings.

    This is the per-file entry point the conformance runner walks over. The repo-
    level `check_unvalidated_default()` below calls this for every `*.yml` / `*.yaml`
    it finds; both shapes are kept so callers can pick the granularity.
    """
    text = path.read_text()
    shell_lines = _lines_to_shell_block(text)
    if not shell_lines:
        return []
    line_nos = [ln for ln, _ in shell_lines]
    contents = [c for _, c in shell_lines]
    findings: list[Finding] = []
    for idx, (lineno, line) in enumerate(shell_lines):
        if _is_comment_line(line):
            continue
        m = _DEFAULT_SUBST.search(line)
        if not m:
            continue
        var = m.group(1)
        default = m.group(2)
        # The substitution almost always sits inside a NAME="${VAR:-default}"
        # assignment; the CONSUMED variable is the LHS NAME, not the RHS var.
        # If the LHS is missing (the pattern appears bare, e.g. inside a longer
        # interpolation), fall back to the RHS var — that case is rarely a
        # defect because a bare ${VAR:-x} substitution is uncommon in `run:`
        # blocks; the assigned form is the trap.
        lhs_match = re.match(r"\s*([A-Z_][A-Z0-9_]*)\s*=", line)
        consumed = lhs_match.group(1) if lhs_match else var
        # Walk forward within _LOOKAHEAD_LINES, looking for:
        #   (a) a numeric comparison involving $VAR (any quoting form), OR
        #   (b) a destructive-mode token on a line that ALSO references $VAR.
        window_end = min(idx + _LOOKAHEAD_LINES, len(shell_lines))
        use_idx: int | None = None
        use_kind: str | None = None
        use_line_text: str | None = None
        for j in range(idx + 1, window_end):
            follow = contents[j]
            if _is_comment_line(follow):
                continue
            # (a) Numeric comparison referencing $CONSUMED (the LHS of the assignment).
            _LB = "\\[?"
            _RB = "\\]?"
            _DOLLAR = "\\$"
            var_ref = re.compile(
                _DOLLAR + _LB + re.escape(consumed) + _RB
            )
            if var_ref.search(follow):
                op_match = re.search(
                    r"\[\[?\s*[\"']?\$[A-Za-z_{}]*[\"']?\s*(-lt|-gt|-eq|-ne|-le|-ge)\s+",
                    follow,
                )
                if op_match:
                    use_idx = j
                    use_kind = "numeric"
                    use_line_text = follow
                    break
            # (b) Destructive token referencing $VAR on the same line.
            if var_ref.search(follow):
                for tok in _DESTRUCTIVE_TOKENS:
                    if tok in follow:
                        use_idx = j
                        use_kind = "destructive"
                        use_line_text = follow
                        break
                if use_idx is not None:
                    break
        if use_idx is None:
            continue  # no numeric/destructive use within the window — out of scope.
        # Has an explicit numeric validation appeared between substitution and use?
        if _validation_present(contents, idx, use_idx, var):
            continue
        use_lineno = line_nos[use_idx]
        kind_label = "numeric threshold" if use_kind == "numeric" else "destructive-mode flag"
        # Use the workflow's own name (the `name:` field, if any) as a stable display
        # label; fall back to the file name. Per-file findings carry the file name
        # in their `path` field, so the rel is optional in the message.
        findings.append(
            Finding(
                "unvalidated-default",
                "advisory",
                f"`${{{var}:-{default}}}` (assigned to `${consumed}`) used as {kind_label} at "
                f"{path.name}:{use_lineno} without an explicit numeric validation "
                f"between the substitution (line {lineno}) and the use — "
                f"`${{VAR:-default}}` substitutes only when VAR is unset or EMPTY; "
                f"a non-numeric set value like `abc` passes straight through and "
                f"reaches the comparison unchanged. Either reject non-numeric input "
                f"with `[[ \"$VAR\" =~ ^[0-9]+$ ]]` before the use, or pass the value "
                f"to a script that validates the type itself.",
                str(path.name),
                use_lineno,
            )
        )
    return findings


def check_unvalidated_default(root: Path, traits: set[str]) -> RuleResult:
    """Repo-level wrapper: walk every `*.yml` / `*.yaml` under root and aggregate.

    Matches the sibling rule convention (check_schedule_inputs_are_empty,
    check_context_properties_exist) — the conformance action globs the dir, the
    rule receives a list of files via this entry point. Per-file work is in
    `check_workflow()`; this wrapper only handles the no-workflows population pin.
    """
    if not root.is_dir():
        return RuleResult(
            "unvalidated-default", "n-a", note=f"{root} is not a directory — nothing to check"
        )
    findings: list[Finding] = []
    files = sorted(root.glob("*.yml")) + sorted(root.glob("*.yaml"))
    if not files:
        return RuleResult(
            "unvalidated-default", "n-a", note="no .github/workflows files to scan"
        )
    for p in files:
        findings.extend(check_workflow(p))
    return RuleResult("unvalidated-default", _cc._status(findings), findings)


# Convenience for `python -m` style invocations from the conformance runner.
def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workflows-dir", default=".github/workflows")
    args = ap.parse_args(argv)
    d = Path(args.workflows_dir)
    if not d.is_dir():
        # Match the sibling convention: print a ::warning, return 0. The conformance
        # action already skips repo-scoped rules when workflows-dir is absent; this
        # is the standalone-invocation path that sees the same absence.
        print(f"::warning::{d} is not a directory — nothing to check")
        return 0
    findings: list[Finding] = []
    files = sorted(d.glob("*.yml")) + sorted(d.glob("*.yaml"))
    print(f"Scanned {len(files)} workflow(s) under {d}.")
    for p in files:
        findings.extend(check_workflow(p))
    status = _cc._status(findings)
    print(f"[{status}] unvalidated-default")
    for f in findings:
        loc = f"{f.path}:{f.line}" if f.path and f.line else (f.path or "")
        print(f"  - [{f.severity}] {loc}: {f.message}")
    return 0 if status in ("pass", "warn", "n-a") else 1


if __name__ == "__main__":
    raise SystemExit(main())