"""One spelling for "where are the workflows", accepted by every rule.

⛔ WHY THIS EXISTS. The rules did not agree on how to be called: `--workflows-dir`,
a positional directory, a positional FILE, and a positional `targets` were all in use
at once. A rule wired in with the wrong spelling exits **2** on argparse, the
`advisory` wrapper swallows the non-zero, and the job stays green having judged
nothing. `test_rule_cli_agrees_with_its_call_site.py` (#32) stops a CALL SITE from
passing a flag its rule never heard of; it does not make the spellings converge.

⚠ THIS IS PURELY ADDITIVE, AND IT HAS TO BE. `akash-github-runner` is public and is
consumed CROSS-ORG at a pinned SHA by a repo we do not control and cannot coordinate
with. A consumer pinning an old SHA runs the OLD file; one pinning a new SHA must keep
working with the argv it already passes. Every previously valid invocation stays valid,
and `--workflows-dir` is an ALIAS, never a replacement.

⇒ After this, a caller may use either spelling against any workflow-scoped rule. That
kills a whole error class: DEV1's own harness invoked `check_listing_failure_is_loud`
positionally while it took only the flag, and reported a correct rule BROKEN. The
divergence did not only break call sites — it broke every harness that had to invoke
the population.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

__all__ = [
    "add_dir_positional",
    "add_dir_target",
    "add_file_target",
    "add_targets_dir_alias",
    "resolve_dir_positional",
    "resolve_target",
    "resolve_targets",
]


def _passed(flag: str, argv: list[str] | None = None) -> bool:
    """Was `--flag` actually on the command line?

    ⛔ "NOT PASSED" IS NOT "IS NONE", AND IT IS NOT "EQUALS THE DEFAULT" EITHER. Rules
    declare their own defaults — `check_listing_failure_is_loud` defaults
    `--workflows-dir` to `.github/workflows`, which is also the value a caller most
    often passes explicitly. Comparing against the default therefore reports a real
    invocation as absent. Only argv knows.
    """
    args = sys.argv[1:] if argv is None else argv
    return any(a == flag or a.startswith(f"{flag}=") for a in args)


def _dir_dest(parser: argparse.ArgumentParser) -> str:
    """The dest `--workflows-dir` actually writes to — it is not always `workflows_dir`.

    ⚠ `check_listing_failure_is_loud` declares `--workflows-dir` and `--workflows`
    together with `dest="workflows"`. A helper assuming the dest matches the flag name
    aims at an attribute that is never set.
    """
    for action in parser._actions:  # noqa: SLF001 - argparse exposes no public API
        if "--workflows-dir" in getattr(action, "option_strings", ()):
            return action.dest
    return "workflows_dir"


def add_dir_target(parser: argparse.ArgumentParser, *, dest: str = "workflows") -> None:
    """Accept a workflows DIRECTORY as either a positional or `--workflows-dir`."""
    parser.add_argument(
        dest, type=Path, nargs="?", default=None, help="a .github/workflows directory"
    )
    parser.add_argument(
        "--workflows-dir",
        type=Path,
        default=None,
        dest="workflows_dir",
        help="the same directory; the fleet-wide spelling",
    )


def add_file_target(parser: argparse.ArgumentParser, *, dest: str = "workflow") -> None:
    """Accept a single workflow FILE as either a positional or `--workflow-file`.

    ⚠ Deliberately NOT `--workflows-dir`. These rules take one file, and a caller who
    assumed the directory convention would otherwise pass a directory and get an error
    that reads like a missing file rather than like the wrong kind of argument.
    """
    parser.add_argument(dest, type=Path, nargs="?", default=None, help="a workflow file")
    parser.add_argument(
        "--workflow-file",
        type=Path,
        default=None,
        dest="workflow_file",
        help="the same file; the fleet-wide spelling",
    )


def resolve_target(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
    *,
    positional: str,
    flag: str,
) -> Path:
    """Return whichever spelling was used, and refuse both-or-neither.

    ⛔ BOTH IS AN ERROR, NOT A PRECEDENCE PUZZLE. Silently preferring one would let a
    caller passing two different paths believe the other one was judged.
    """
    pos = getattr(args, positional, None)
    via_flag = getattr(args, flag, None)
    if pos is not None and via_flag is not None and pos != via_flag:
        parser.error(
            f"give the target once: got positional {pos} "
            f"and --{flag.replace('_', '-')} {via_flag}"
        )
    target = via_flag if via_flag is not None else pos
    if target is None:
        parser.error(
            f"a target is required: pass it positionally "
            f"or with --{flag.replace('_', '-')}"
        )
    setattr(args, positional, target)
    return target


def add_dir_positional(parser: argparse.ArgumentParser) -> None:
    """Give a rule that already declares `--workflows-dir` a positional alias too.

    ⭐ This is the half that kills the harness error class: after it, either spelling
    works against every workflow-scoped rule, so a harness cannot be wrong about which
    one a given rule wants.

    ⚠ Some rules declare `--workflows-dir` as `required=True`, which would refuse a
    positional-only call. That is relaxed here — a RELAXATION only, so every invocation
    that worked before still works, and the "one of the two must be given" duty moves
    to `resolve_dir_positional`.
    """
    parser.add_argument(
        "workflows_positional",
        type=Path,
        nargs="?",
        default=None,
        help="the workflows directory; same as --workflows-dir",
    )
    for action in parser._actions:  # noqa: SLF001
        if "--workflows-dir" in getattr(action, "option_strings", ()):
            action.required = False


def resolve_dir_positional(
    parser: argparse.ArgumentParser, args: argparse.Namespace
) -> None:
    """Fold the positional alias into the rule's own dir dest."""
    dest = _dir_dest(parser)
    pos = getattr(args, "workflows_positional", None)
    flag_given = _passed("--workflows-dir")
    if pos is not None and flag_given and getattr(args, dest, None) != pos:
        parser.error(
            f"give the target once: got positional {pos} "
            f"and --workflows-dir {getattr(args, dest, None)}"
        )
    if pos is not None and not flag_given:
        setattr(args, dest, pos)
    if getattr(args, dest, None) is None:
        parser.error(
            "a target is required: pass it positionally or with --workflows-dir"
        )


def add_targets_dir_alias(parser: argparse.ArgumentParser) -> None:
    """Let a `targets`-style rule also be called with `--workflows-dir`.

    ⚠ These rules already accept a directory OR files positionally, so they were never
    broken — but a caller sweeping the whole suite with one spelling had to special-case
    them. The alias removes the special case.
    """
    parser.add_argument(
        "--workflows-dir",
        type=Path,
        default=None,
        dest="workflows_dir",
        help="a workflows directory; appended to the positional targets",
    )


def resolve_targets(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    """Fold `--workflows-dir` into `targets`, and refuse an empty result.

    ⛔ `nargs="+"` used to make argparse enforce non-emptiness. Relaxing it to `"*"` so
    the flag can stand alone moves that duty here — an empty target list must stay an
    ERROR, never an empty population that every rule reports PASS over.
    """
    targets = list(getattr(args, "targets", None) or [])
    flag = getattr(args, "workflows_dir", None)
    if flag is not None:
        targets.append(flag)
    if not targets:
        parser.error(
            "a target is required: pass it positionally or with --workflows-dir"
        )
    args.targets = targets
