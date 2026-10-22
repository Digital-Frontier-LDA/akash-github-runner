#!/usr/bin/env python3
"""No runner image built before the eMudhra/emSign CA distrust may be referenced (df-cicd-rpi.1).

CVE-2026-111943 (golang/go#82345): 8 intermediates whose keys were compromised are each issued
by an emSign root AND cross-signed by AAA Certificate Services, so an image built before the
distrust can trust chains through them. df-akash-runner was rebuilt with the CA floor and the
8 keys rejected (index sha256:e71bf4be..., 2026-10-22).

The rule is "no pre-fix digest is admissible", not "must equal the fix", so any later rebuild
passes. The list is MEASURED: every df-akash-runner manifest GHCR published before the fixed
index, minus that index's own children (data/df_akash_runner_pre_emudhra_digests.txt).

ENFORCING, unlike check_runner_image_digest_floor (advisory because a version floor rots on
GitHub's deprecation dates): a pre-fix image stays pre-fix forever, so this answer cannot rot.
The digest is matched anywhere in a workflow's code, whatever the image name around it,
because a private mirror (docker.io/.../akash-runner) copies the bytes unchanged under a name
the runner-name extraction does not recognise. Comment lines are excluded, so history may
still name them.

SCOPE: the workflows AND the repository's non-test code. Hard-coded runner images live in
scripts too (the owned controller's workload table, Flynn's worker verifier, DePIN's
prerequisites tool), and a regression there would otherwise pass. Excluded by structure: test
code (tests/, test_*.py, *_test.py, conftest.py, fixtures/), which names pre-fix digests on
purpose as negative fixtures, and prose (only code suffixes are read). The few non-test files
that MUST hold a pre-fix digest are in ALLOWLIST, each narrowed to one line pattern and a
reason.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import _cli

FIXED_INDEX = "sha256:e71bf4be0e3a59a57ff791b0fc3bc3a31f216f66807b6ac41f1a23346321baa4"
DATA = Path(__file__).resolve().parent / "data" / "df_akash_runner_pre_emudhra_digests.txt"
PRE_EMUDHRA_DIGESTS: frozenset[str] = frozenset(
    line.split()[0]
    for line in DATA.read_text(encoding="utf-8").splitlines()
    if line.startswith("sha256:")
)
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_CODE_SUFFIXES = {".py", ".sh", ".bash", ".yml", ".yaml", ".json", ".toml", ".cfg", ".ini"}
_SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "tests", "test", "fixtures"}
# (repo-relative path, line regex, reason). A line matching the regex may name ONE pre-fix
# digest; nothing else in that file may. Keep each entry as narrow as the case it exempts.
ALLOWLIST: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        ".github/scripts/verify_owned_worker_image.py",
        re.compile(r'^OLD_IMAGE = "ghcr\.io/digital-frontier-lda/df-akash-runner@sha256:[0-9a-f]{64}"$'),
        "Flynn's NEGATIVE CONTROL: the verifier executes OLD_IMAGE and requires it to FAIL, so it "
        "must be a pre-fix image by design. Exempt only the OLD_IMAGE assignment.",
    ),
    (
        "proofs/owned-history-approved-source.json",
        re.compile(r".*"),
        "blazing's ATTESTED owned-history baseline (byte-pinned by "
        "owned_history_migration_contract.BASELINE_SHA): a record of what was approved, which "
        "cannot be edited without forging it. It is history, not a pin.",
    ),
)


def _is_test_path(rel: Path) -> bool:
    name = rel.name
    return (
        bool(_SKIP_DIRS & set(rel.parts[:-1]))
        or name.startswith("test_")
        or name.endswith("_test.py")
        or name == "conftest.py"
    )


def _allowed(rel: str, line: str) -> bool:
    return any(rel == path and pattern.match(line.strip()) for path, pattern, _ in ALLOWLIST)


def code_findings(root: Path) -> list[tuple[str, str]]:
    """(repo-relative file, finding) for pre-fix digests in non-test code outside workflows."""
    out: list[tuple[str, str]] = []
    workflows = (root / ".github" / "workflows").resolve()
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in _CODE_SUFFIXES:
            continue
        rel = path.relative_to(root)
        if _is_test_path(rel) or workflows in path.resolve().parents:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        comment = "#" if path.suffix != ".json" else None
        for line in text.splitlines():
            if comment and line.lstrip().startswith(comment):
                continue
            hits = set(_DIGEST.findall(line.lower())) & PRE_EMUDHRA_DIGESTS
            if hits and not _allowed(rel.as_posix(), line):
                out += [(rel.as_posix(), finding) for finding in findings(line) if any(h in finding for h in hits)]
    return out


def findings(text: str) -> list[str]:
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    return [
        f"pre-fix runner digest {digest} (built before the eMudhra/emSign CA distrust, "
        f"df-cicd-rpi.1) is referenced; pin {FIXED_INDEX} or a later df-akash-runner build"
        for digest in sorted(set(_DIGEST.findall(code.lower())) & PRE_EMUDHRA_DIGESTS)
    ]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workflows-dir", default=".github/workflows")
    ap.add_argument(
        "--repo-root",
        default=None,
        help="repository root for the non-test code scan (default: two levels above a "
        ".github/workflows directory; skipped otherwise)",
    )
    _cli.add_dir_positional(ap)
    args = ap.parse_args(argv)
    _cli.resolve_dir_positional(ap, args)
    root = Path(args.workflows_dir)
    if not root.is_dir():
        print(f"Pre-eMudhra runner digests: NOT APPLICABLE — {root} is not a directory")
        return 0
    bad = 0
    for path in sorted(root.glob("*.yml")) + sorted(root.glob("*.yaml")):
        for finding in findings(path.read_text(encoding="utf-8")):
            bad += 1
            print(f"::error file={path},title=Pre-eMudhra runner image::{finding}")
    repo = Path(args.repo_root) if args.repo_root else (
        root.resolve().parent.parent if root.resolve().parts[-2:] == (".github", "workflows") else None
    )
    if repo is None:
        print("Pre-eMudhra runner digests: code scan SKIPPED (no repo root; pass --repo-root)")
    else:
        for rel, finding in code_findings(repo):
            bad += 1
            print(f"::error file={rel},title=Pre-eMudhra runner image::{finding}")
    print(f"Pre-eMudhra runner digests: {bad} reference(s) to a pre-fix image")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
