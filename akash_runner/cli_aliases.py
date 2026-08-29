"""Shared CLI aliasing for the conformance rules — ONE convention, every legacy spelling kept.

⛔ WHY (agr#30). The rules grew five CLI conventions: `--workflows-dir` (8), a positional
directory (3), a positional FILE (3), a positional `targets` (3), and a positional `repos`
(1). Every call site in the action happens to match its rule because each was matched BY
HAND — and a rule wired with the wrong spelling does not fail loudly: argparse exits 2 on an
unrecognised argument, the `advisory` wrapper swallows the non-zero, and the job goes green
having judged nothing. It already happened once (`--workflows` vs `--workflows-dir`).

⚠ THIS MODULE CONVERGES THE RULES, NOT THE CALL SITES. The canonical spellings are
`--workflows-dir`, `--workflow-file`, `--targets`, and `--repos`; every positional a rule
ever accepted STILL WORKS as an alias, because agr is public and consumed cross-org at
pinned SHAs — a pinned old call site is a contract this module must keep (never a
replacement; add, don't remove).

The argparse mechanics, once, because they are subtle and every rule repeats them:

    parser.add_argument("workflows", nargs="?", type=Path, default=None,
                        help="workflows directory (legacy positional; prefer --workflows-dir)")
    parser.add_argument("--workflows-dir", dest="workflows", type=Path,
                        default=argparse.SUPPRESS)

`dest` shares ONE namespace slot between the positional and the flag. `SUPPRESS` on the
flag is the load-bearing half: when the flag is ABSENT argparse does not touch the slot at
all, so the positional's value (set earlier) survives; without SUPPRESS the flag's default
would overwrite the positional with None on every legacy invocation. When BOTH are given
the flag wins (argparse applies optionals after positionals) — documented, deterministic.

`require_*` makes "neither given" LOUD: a required positional that became optional for
aliasing must fail explicitly, or a bare invocation would proceed with None and die deep
in the rule wearing a defect costume (or worse, not die).
"""

from __future__ import annotations

import argparse
from pathlib import Path


def add_workflows_dir(
    parser: argparse.ArgumentParser,
    positional_name: str = "workflows",
    help_extra: str = "a .github/workflows directory",
) -> None:
    """Directory-scoped input: `--workflows-dir` (canonical) + positional (legacy alias)."""
    parser.add_argument(
        positional_name,
        nargs="?",
        type=Path,
        default=None,
        help=f"{help_extra} (legacy positional; prefer --workflows-dir)",
    )
    parser.add_argument(
        "--workflows-dir",
        dest=positional_name,
        type=Path,
        default=argparse.SUPPRESS,
        help="workflows directory (canonical form)",
    )


def add_workflow_file(
    parser: argparse.ArgumentParser,
    positional_name: str = "workflow",
    help_extra: str = "a workflow file",
) -> None:
    """File-scoped input: `--workflow-file` (canonical) + positional (legacy alias).

    ⚠ DELIBERATELY A DIFFERENT NAME FROM `--workflows-dir`, not a directory flag with a
    file fallback: a caller assuming the dir convention passes a directory here and gets
    "could not read workflow" — a failure that reads like a missing file — instead of a
    confusing success on a globbed directory. The two scopes must not share a spelling.
    """
    parser.add_argument(
        positional_name,
        nargs="?",
        type=Path,
        default=None,
        help=f"{help_extra} (legacy positional; prefer --workflow-file)",
    )
    parser.add_argument(
        "--workflow-file",
        dest=positional_name,
        type=Path,
        default=argparse.SUPPRESS,
        help="a single workflow file (canonical form)",
    )


def add_multi(
    parser: argparse.ArgumentParser,
    flag: str,
    positional_name: str,
    help_extra: str,
    value_type: type | None = None,
) -> None:
    """Multi-value input: `--<flag>` (canonical, nargs='+') + positional (legacy alias)."""
    kwargs = {"type": value_type} if value_type is not None else {}
    parser.add_argument(
        positional_name,
        nargs="*",
        default=None,
        help=f"{help_extra} (legacy positional; prefer {flag})",
        **kwargs,
    )
    parser.add_argument(
        flag,
        dest=positional_name,
        nargs="+",
        default=argparse.SUPPRESS,
        help=f"{help_extra} (canonical form)",
        **kwargs,
    )


def require_dir(args: argparse.Namespace, name: str, parser: argparse.ArgumentParser) -> Path:
    """Loud when neither the flag nor the positional was given."""
    value = getattr(args, name, None)
    if value is None:
        parser.error(f"{name}: required (pass --workflows-dir or the legacy positional)")
    return value


def require_file(args: argparse.Namespace, name: str, parser: argparse.ArgumentParser) -> Path:
    value = getattr(args, name, None)
    if value is None:
        parser.error(f"{name}: required (pass --workflow-file or the legacy positional)")
    return value


def require_multi(
    args: argparse.Namespace, name: str, parser: argparse.ArgumentParser
) -> list[str]:
    value = getattr(args, name, None)
    if not value:
        parser.error(f"{name}: at least one required (pass the flag or the legacy positional)")
    return value
