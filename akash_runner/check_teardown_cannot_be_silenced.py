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
      | DELETE \s+ /v1/deployments                       # console api close
      | \bclose_deployment\b | \bdestroy_deployment\b
      | gcloud \s+ compute \s+ (?:forwarding-rules|target-pools) \s+ delete
      | kubectl \s+ delete \s+ (?:namespace|ns)\b        # a tenant namespace is compute
    )
    """
)

# The failure cannot reach the step's exit status.
_SWALLOWS_FAILURE = re.compile(r"(\|\|\s*true\b|\|\|\s*:\s*(?:$|\n)|\|\|\s*exit\s+0\b)", re.M)


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
    """Lines that install a close tool AND swallow their own failure."""
    out: list[tuple[int, str]] = []
    if not tools:
        return out
    tool_re = re.compile(r"(?<![\w-])(?:" + "|".join(re.escape(t) for t in sorted(tools)) + r")(?![\w-])")
    for i, line, excerpt in _logical_lines(block):
        if _INSTALLS.search(line) and tool_re.search(line) and _SWALLOWS_FAILURE.search(line):
            tool = tool_re.search(line).group(0)
            out.append((
                block.start_line + i,
                (
                    f"the install of `{tool}`, which a billable close in this workflow needs, "
                    f"swallows its own failure — 'tool absent' then reads as 'nothing to clean': {excerpt}"
                ),
            ))
    return out


def _offending_lines(block: RunBlock) -> list[tuple[int, str]]:
    """Lines that BOTH close something billable AND swallow their own failure.

    ⚠ Matched against `code` (comments blanked, line structure preserved) so a comment
    describing the defect is never reported as the defect. `script` is used only for the
    human-readable excerpt.
    """
    out: list[tuple[int, str]] = []
    for i, line, excerpt in _logical_lines(block):
        if _CLOSES_BILLABLE.search(line) and _SWALLOWS_FAILURE.search(line):
            out.append((block.start_line + i, excerpt))
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
        # ⛔ Absence is NOT a pass. Say so, and say which path was empty.
        print(f"::warning::{d} is not a directory — silenced-teardown rule did not run")
        return 0
    files = sorted(d.glob("*.yml")) + sorted(d.glob("*.yaml"))
    if not files:
        print(f"::warning::no workflows under {d} — nothing scanned, which is not the same as clean")
        return 0
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
