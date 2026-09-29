"""A teardown that closes a billable resource must be able to fail.

⛔ THE WORKED EXAMPLE, verified in this repo (df-cicd #1553):

    df-akash-gate.yml:56  pipx install just-akash 2>/dev/null || pip install just-akash 2>/dev/null || true
    df-akash-gate.yml:82  [ -n "${DSEQ:-}" ] && just-akash close "$DSEQ" 2>/dev/null || true

There is no `just-akash` package on PyPI (HTTP 404; control: `pypi.org/pypi/pytest/json`
-> 200), so line 56 has never installed anything and line 82 has never run a binary.
**Five silencing constructs** across the two lines, and the shell shape is worse than it
looks: `[ -n "$X" ] && cmd || true` exits 0 in ALL THREE failure modes — variable empty,
binary missing, close genuinely failed.

⇒ It is not a teardown that sometimes fails. It is a teardown that has never once run,
and it reports success every time. Meanwhile 484 ACT of Akash escrow sat in orders that
were never closed, with total rent burned of 1.97 ACT — 0.4% — because almost nothing
those orders paid for ever ran.

THE CLASS, stated so it is checkable: a `run:` block is unrepresentable-as-written when it
CLOSES a billable resource and its failure CANNOT change the step's exit status.

The silencers recognised (each was an escape on 88d4b1a0 — DF-infra dfinfra-gh1553 review):
`|| true`, `|| :` (anywhere on the line), `|| exit 0`, `|| echo/printf ...` with no
annotation, `continue-on-error` on the step or its job, an `if [!] close` with no branch that
fails or announces and no later `exit N`, and `set +e` with the close's status never read.
A trailing `||`/`&&`/`|` continues the list exactly as a backslash does. A silenced install
counts when it names the close tool OR its target is opaque (`"$whl"`, a path, a URL).

⚠ WHAT THIS RULE DELIBERATELY DOES NOT FLAG. `|| true` is not itself a defect — it is
correct on a best-effort diagnostic, a log upload, or a cleanup whose failure genuinely
does not matter. The rule fires only on the CONJUNCTION of "closes something billable" and
"cannot fail". Flagging every `|| true` would bury the real instances in noise and train
readers to ignore the rule, which is worse than not having it.
"""

from __future__ import annotations

import _cli

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from workflow_corpus import RunBlock, run_blocks  # noqa: E402

# Closing a resource that costs money. Narrow on purpose: a generic `delete` matches far
# too much (files, branches, artifacts), and a rule that fires on `rm` is a prose detector.
_CLOSES_BILLABLE = re.compile(
    r"""(?ix)
    \b(?:
        just-akash \s+ (?:close-all|close|destroy-all|destroy)  # akash deployment escrow
      | akash \s+ tx \s+ deployment \s+ close
      | provider-services \s+ tx \s+ deployment \s+ close
      | DELETE \s+ /v1/deployments                       # console api close, as documented
      # ...and as INVOKED: `curl -X DELETE "$API/v1/deployments/$DSEQ"` never contains the
      # literal `DELETE /v1/deployments`, and the Console API is this platform's close path.
      | curl \b (?=[^\n]*?(?:-X\s*|--request[\s=]+)["']?DELETE\b) (?=[^\n]*?/v1/deployments)
      | requests \. delete \s* \( [^)\n]*? /v1/deployments
      | \bclose_deployment\b | \bdestroy_deployment\b
      | gcloud \s+ compute \s+ (?:forwarding-rules|target-pools) \s+ delete
      | kubectl \s+ delete \s+ (?:namespace|ns)\b        # a tenant namespace is compute
    )
    """
)

# The failure cannot reach the step's exit status: an `||` branch that only reports.
# `|| :` is matched anywhere (`|| :; echo done` is the same swallow), and `|| echo ...`
# / `|| printf ...` swallow exactly as `|| true` does — a warning line is not a failure.
_OR_BRANCH_SWALLOWS = re.compile(
    r"\|\|\s*\{?\s*(?:true\b|:(?![\w-])|exit\s+0\b|(?P<say>echo\b|printf\b))"
)
# ...unless the same branch then fails the step anyway (`|| { echo "::error::x"; exit 1; }`).
_PROPAGATES = re.compile(r"\bexit\s+(?!0\b)\S|(?<![\w-])false\b|\breturn\s+(?!0\b)\S")
# ⚠ ANNOUNCED IS NOT SILENCED. `|| echo "::warning::destroy failed for dseq $D"` does not
# fail the step, but it does not collapse "closed" and "close failed" into one green either:
# the run summary carries the annotation. The fleet uses that shape ON PURPOSE (df-akash-gate
# "Still non-fatal on purpose ... But it now ANNOUNCES"; runner-time-to-ready.yml). A plain
# `|| echo "close failed"` lands only in the log of a green step, which nobody opens — that
# IS silenced, and is flagged.
_ANNOUNCES = re.compile(r"::(?:error|warning)\b")


def _swallows(line: str) -> bool:
    for m in _OR_BRANCH_SWALLOWS.finditer(line):
        rest = line[m.end():]
        if _PROPAGATES.search(rest) or (m.group("say") and _ANNOUNCES.search(rest)):
            continue
        return True
    return False


# A line ending in one of these is continued by bash WITHOUT a backslash: `cmd ||` NEWLINE
# `true` is one list (bash: `false ||` NEWLINE `true` -> rc=0).
_CONTINUES = re.compile(r"(?:\|\||&&|\|)\s*$")
_SET_PLUS_E = re.compile(r"(?<![\w-])set\s+(?:\+[a-zA-Z]*e[a-zA-Z]*|\+o\s+errexit)\b")
_SET_MINUS_E = re.compile(r"(?<![\w-])set\s+(?:-[a-zA-Z]*e[a-zA-Z]*|-o\s+errexit)\b")
_CAPTURES_STATUS = re.compile(r"\$\{?\?|PIPESTATUS")
_KW = lambda w: re.compile(r"(?<![\w-])" + w + r"(?![\w-])")  # noqa: E731
_IF, _FI, _THEN = _KW("if"), _KW("fi"), _KW("then")


# Criterion 2 of #1553: the close depends on a tool whose INSTALLATION is silenced, so
# "tool absent" and "nothing to clean" read the same. Measured on df-akash-gate.yml:56 —
# `pipx install just-akash 2>/dev/null || pip install just-akash 2>/dev/null || true`
# never installed anything (just-akash is not on PyPI), for as long as the gate existed.
# Only tools some billable close in the SAME workflow invokes are considered: a silenced
# install of anything else is a best-effort convenience, not a teardown hazard.
_CLOSE_TOOL = re.compile(
    r"\b(just-akash|akash|provider-services|gcloud|kubectl)\b(?=\s+(?:close|destroy|tx|compute|delete))"
)
_INSTALLS = re.compile(r"\b(?:pipx|pip3?|uv\s+(?:tool|pip))\s+install\b")
# Where an install's argument list ends.
_ARGS_END = re.compile(r"\|\||&&|[;|&]|\d?>")


def _install_targets(line: str) -> list[str]:
    """Non-flag arguments of every install on the line, quotes removed."""
    out: list[str] = []
    for m in _INSTALLS.finditer(line):
        rest = line[m.end():]
        end = _ARGS_END.search(rest)
        for tok in (rest[: end.start()] if end else rest).split():
            if not tok.startswith("-"):
                out.append(tok.strip("'\""))
    return out


def _opaque(target: str) -> bool:
    """A target whose identity is not visible in the text: a variable, path, URL or file.

    The pinned remedy installs `"$whl"`, so requiring the tool's literal name let the remedy
    itself be silenced unflagged. A literal package name (`rich`) can be judged; these can't.
    """
    return bool(re.search(r"[$/]|\.(?:whl|tar\.gz|zip|txt)$|^git\+|://", target))


def _logical_lines(block: RunBlock) -> list[tuple[int, str, str]]:
    """(first physical line index, code, verbatim) per LOGICAL shell line.

    A trailing backslash continues a command, so `pipx install just-akash || \\` with
    `true` on the next line is ONE invocation whose failure is swallowed. Matching
    physical lines alone would split the install from its `|| true` and miss it — the
    "select the whole invocation, not a line" constraint #1553 records. Reported at the
    command's first line.
    """
    code = block.code.splitlines()
    verbatim = block.script.splitlines()
    out: list[tuple[int, str, str]] = []
    i = 0
    while i < len(code):
        start, parts, vparts = i, [], []
        while True:
            line = code[i]
            vline = verbatim[i] if i < len(verbatim) else line
            if line.rstrip().endswith("\\") and i + 1 < len(code):
                parts.append(line.rstrip()[:-1])
                vparts.append(vline.rstrip()[:-1].rstrip())
                i += 1
                continue
            if _CONTINUES.search(line) and i + 1 < len(code):
                parts.append(line.rstrip())
                vparts.append(vline.strip())
                i += 1
                continue
            parts.append(line)
            vparts.append(vline.strip())
            i += 1
            break
        out.append((start, " ".join(parts), " ".join(p.strip() for p in vparts if p.strip())))
    return out


def _close_tools(blocks: list[RunBlock]) -> set[str]:
    """Tools the workflow invokes on a billable-close line (comments excluded)."""
    tools: set[str] = set()
    for block in blocks:
        for _, line, _ in _logical_lines(block):
            if _CLOSES_BILLABLE.search(line):
                tools.update(m.group(1) for m in _CLOSE_TOOL.finditer(line))
    return tools


def _silenced_installs(block: RunBlock, tools: set[str]) -> list[tuple[int, str]]:
    """Lines that install a close tool (or an opaque target) AND cannot fail."""
    out: list[tuple[int, str]] = []
    if not tools:
        return out
    tool_re = re.compile(r"(?<![\w-])(?:" + "|".join(re.escape(t) for t in sorted(tools)) + r")(?![\w-])")
    for i, line, excerpt in _logical_lines(block):
        if not _INSTALLS.search(line):
            continue
        how = "swallows its own failure" if _swallows(line) else (
            "sits in a `continue-on-error` step" if block.continue_on_error else None
        )
        if how is None:
            continue
        targets = _install_targets(line)
        named = next((t for t in targets if tool_re.search(t)), None)
        if named:
            what = f"the install of `{tool_re.search(named).group(0)}`, which a billable close in this workflow needs,"
        elif any(_opaque(t) for t in targets):
            what = (
                f"an install of `{next(t for t in targets if _opaque(t))}` — a target that cannot be "
                f"shown unrelated to the close tool this workflow needs —"
            )
        else:
            continue
        out.append((
            block.start_line + i,
            f"{what} {how} — 'tool absent' then reads as 'nothing to clean': {excerpt}",
        ))
    return out


def _offending_lines(block: RunBlock) -> list[tuple[int, str]]:
    """Lines that BOTH close something billable AND swallow their own failure.

    ⚠ Matched against `code` (comments blanked, line structure preserved) so a comment
    describing the defect is never reported as the defect. `script` is used only for the
    human-readable excerpt.
    """
    out: list[tuple[int, str]] = []
    lines = _logical_lines(block)
    flagged: set[int] = set()

    def add(i: int, text: str) -> None:
        if i not in flagged:
            flagged.add(i)
            out.append((block.start_line + i, text))

    for i, line, excerpt in lines:
        if not _CLOSES_BILLABLE.search(line):
            continue
        if _swallows(line):
            add(i, excerpt)
        elif block.continue_on_error:
            add(i, f"(step or job has continue-on-error) {excerpt}")

    # `if [!] close ...; then ...; fi` with no failing branch: the `if` compound returns 0
    # whichever way the close went.
    for n, (i, line, excerpt) in enumerate(lines):
        m = re.match(r"\s*(?:el)?if\s", line)
        if not m:
            continue
        head = _THEN.split(line, maxsplit=1)[0]
        if not _CLOSES_BILLABLE.search(head):
            continue
        # `elif` is not counted by _IF, but it sits INSIDE an open `if`: start one level deep.
        depth, body = (1 if line.lstrip().startswith("elif") else 0), []
        for _, later, _ in lines[n:]:
            depth += len(_IF.findall(later)) - len(_FI.findall(later))
            body.append(later)
            if depth <= 0:
                break
        inside = "\n".join(body)[len(head):]
        after = "\n".join(t[1] for t in lines[n + len(body):])
        # A retry loop (`if close; then break; fi` ... verify ... `exit 1`) is handled AFTER
        # the `if`; judging the `if` alone called blazing's retry+verify teardown silenced.
        if not (_PROPAGATES.search(inside) or _ANNOUNCES.search(inside) or _PROPAGATES.search(after)):
            add(i, f"(an `if` on the close with no branch that fails or announces) {excerpt}")

    # `set +e` then a close whose status nobody reads: the step exits with whatever ran last.
    errexit, nonempty = True, [t for t in lines if t[1].strip()]
    for n, (i, line, excerpt) in enumerate(nonempty):
        if _SET_PLUS_E.search(line):
            errexit = False
        elif _SET_MINUS_E.search(line):
            errexit = True
        if errexit or not _CLOSES_BILLABLE.search(line) or re.match(r"\s*(?:el)?if\s|\s*while\s|\s*until\s", line):
            continue
        tail = line[_CLOSES_BILLABLE.search(line).end():]
        is_last = n == len(nonempty) - 1
        read_next = n + 1 < len(nonempty) and _CAPTURES_STATUS.search(nonempty[n + 1][1])
        if not (is_last or read_next or _CAPTURES_STATUS.search(tail) or "||" in tail):
            add(i, f"(after `set +e`, nothing reads the close's status) {excerpt}")
    return out


def check_workflow(path: Path) -> list[tuple[int, str]]:
    """Every silenced-close line, and every silenced install of a close tool, in one file."""
    findings: list[tuple[int, str]] = []
    blocks = list(run_blocks(path))
    tools = _close_tools(blocks)
    for block in blocks:
        findings.extend(_offending_lines(block))
        findings.extend(_silenced_installs(block, tools))
    return sorted(findings)


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--workflows-dir", default=".github/workflows")
    _cli.add_dir_positional(ap)
    args = ap.parse_args(argv)
    _cli.resolve_dir_positional(ap, args)
    d = Path(args.workflows_dir)
    if not d.is_dir():
        # ⛔ Absence is NOT a pass — so it must not exit like one. This rule is ENFORCING and
        # the action never checks that `workflows-dir` exists: a typo would read as clean.
        print(f"::error::{d} is not a directory — silenced-teardown rule did not run")
        return 2
    files = sorted(d.glob("*.yml")) + sorted(d.glob("*.yaml"))
    if not files:
        print(f"::error::no workflows under {d} — nothing scanned, which is not the same as clean")
        return 2
    findings = 0
    for f in files:
        for line, excerpt in check_workflow(f):
            findings += 1
            print(
                f"::error file={f},line={line}::a teardown that closes a billable resource "
                f"cannot fail as written — its failure never reaches the step's exit status, "
                f"so 'closed successfully' and 'never ran' are indistinguishable: {excerpt}"
            )
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
