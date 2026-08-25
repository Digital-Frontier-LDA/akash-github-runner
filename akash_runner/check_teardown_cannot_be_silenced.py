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
        just-akash \s+ (?:close|destroy|close-all)      # akash deployment escrow
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


def _offending_lines(block: RunBlock) -> list[tuple[int, str]]:
    """Lines that BOTH close something billable AND swallow their own failure.

    ⚠ Matched against `code` (comments blanked, line structure preserved) so a comment
    describing the defect is never reported as the defect. `script` is used only for the
    human-readable excerpt.
    """
    out: list[tuple[int, str]] = []
    stripped = block.code.splitlines()
    verbatim = block.script.splitlines()
    for i, line in enumerate(stripped):
        if _CLOSES_BILLABLE.search(line) and _SWALLOWS_FAILURE.search(line):
            excerpt = verbatim[i].strip() if i < len(verbatim) else line.strip()
            out.append((block.start_line + i, excerpt))
    return out


def check_workflow(path: Path) -> list[tuple[int, str]]:
    """Every silenced-close line in one workflow or composite action."""
    findings: list[tuple[int, str]] = []
    for block in run_blocks(path):
        findings.extend(_offending_lines(block))
    return findings


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--workflows-dir", default=".github/workflows")
    args = ap.parse_args(argv)
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
