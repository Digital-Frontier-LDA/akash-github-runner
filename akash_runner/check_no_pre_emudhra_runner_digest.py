#!/usr/bin/env python3
"""No runner image built before the eMudhra/emSign CA distrust may be referenced (df-cicd-rpi.1).

CVE-2026-111943 (golang/go#82345): 8 intermediates whose keys were compromised are each issued
by an emSign root AND cross-signed by AAA Certificate Services, so an image built before the
distrust can trust chains through them. df-akash-runner was rebuilt with the CA floor and the
8 keys rejected (index sha256:e71bf4be..., 2026-10-22).

The rule is "no pre-fix digest is admissible", not "must equal the fix", so any later rebuild
passes. The list is MEASURED: every df-akash-runner manifest GHCR published before the fixed
index, minus that index's own children (data/df_akash_runner_pre_emudhra_digests.txt).

MODE: ADVISORY NOW, ENFORCING AT PROMOTION. It is wired `advisory` in the conformance action
with a PROMOTE WHEN in test_every_rule_has_a_call_site.ADVISORY (every consumer at 0 hits).
Unlike check_runner_image_digest_floor, which stays advisory because a version floor rots on
GitHub's deprecation dates, a pre-fix image stays pre-fix forever, so this answer cannot rot
and the rule is meant to enforce once consumers are repinned.

WHAT THIS GUARDS, AND WHAT GUARDS THE REST. This deny-list is the HISTORY guard: it knows every
digest published before the fix. It cannot know a digest that does not exist yet, so the
FUTURE guard is at build time: df-akash-runner's build-and-verify runs the distrust test
(tests/test_ca_distrust_container.sh, since #19), and publish.yml refuses to publish a commit
whose verify did not pass. The Sentinel scanner image has the same gate (#25). Residual, by
design not covered here: "published after the fixed index" is a time proxy, not proof of the
CA floor. A publish.yml dispatch on an OLD branch would gate on that branch's own older verify
(which predates the distrust test) and could publish a pre-fix build under a NEW digest.
Tracked as df-cicd-rpi.4: df-akash-runner#26 makes publish.yml refuse any ref but main (the
cheap fix); a positive check (an OCI label set by the fixed build, or a per-digest
published-image distrust run) is the stronger follow-up, not a longer deny-list.

NAMES AND PLACES. The digest is matched whatever the image name around it, because a private
mirror (docker.io/.../akash-runner) copies the bytes unchanged under a name the runner-name
extraction does not recognise. Matching is case-insensitive.

SCOPE: the workflows (*.yml, *.yaml) AND the repository's non-test code. Hard-coded runner
images live in scripts too (the owned controller's workload table, Flynn's worker verifier,
DePIN's prerequisites tool). Excluded by structure: test code, meaning any tests/ or test/
directory at any depth, fixtures/ only inside such a directory, and the Python names
test_*.py, *_test.py and conftest.py. A shipped script named test_*.sh IS scanned. Prose is
not read (only code suffixes).

COMMENTS ARE HISTORY. A full-line comment is skipped, and so is a trailing comment: anything
after whitespace + "#" on yml/yaml/py/sh/toml/cfg/ini lines. So `image: ...@<fixed>  # was
<pre-fix>` passes. Known limit: a " #" inside a quoted string also ends the scanned part of
that line.

ALLOWLIST. A file that MUST hold a pre-fix digest gets an entry: path, a line pattern, and a
reason. Generated RECORDS (SBOMs, attestations, receipts such as blazing's owned-history
proof) name pre-fix digests as history, not pins. They go in ALLOWLIST by path with `.*` and
their regeneration owner, rather than by dropping a suffix from the scan.
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
_HASH_COMMENT_SUFFIXES = _CODE_SUFFIXES - {".json"}
_NEVER_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__"}
_TEST_DIRS = {"tests", "test"}
_TRAILING_COMMENT = re.compile(r"\s#.*$")

# Flynn's negative control: the verifier executes OLD_IMAGE and requires it to FAIL, so its
# value must BE a pre-fix image. Any pre-fix digest is accepted (Flynn's repin may move it),
# but a control repointed at a fixed image stops being a control, and is flagged.
_FLYNN_CONTROL = re.compile(
    r'^OLD_IMAGE = "ghcr\.io/digital-frontier-lda/df-akash-runner@(sha256:[0-9a-f]{64})"$'
)


def _exact_lines(*lines: str) -> re.Pattern[str]:
    """Allow exactly these stripped lines, and nothing else in the file."""
    return re.compile("^(?:" + "|".join(re.escape(line) for line in lines) + ")$")


_MIGRATION_SNAPSHOT = (
    "one-shot migration snapshot; push trigger scoped to codex/...-2026100x branches: the "
    "constant is the pre-fix image being preserved, not a runner being run (decided by the "
    "team, akash-github-runner#85, 2026-10-22)."
)

# (repo-relative path, line regex, reason). A line matching the regex may name a pre-fix
# digest; nothing else in that file may. Keep each entry as narrow as the case.
ALLOWLIST: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        ".github/scripts/verify_owned_worker_image.py",
        _FLYNN_CONTROL,
        "Flynn's NEGATIVE CONTROL: only the OLD_IMAGE assignment, and only while its value IS a "
        "pre-fix digest (see negative_control_findings).",
    ),
    (
        "proofs/owned-history-approved-source.json",
        re.compile(r".*"),
        "blazing's ATTESTED owned-history baseline (byte-pinned by "
        "owned_history_migration_contract.BASELINE_SHA): a generated record of what was "
        "approved, regenerated only by blazing's owned-history migration. History, not a pin.",
    ),
    (
        # blazing: the fixed ce1 graph mirrored privately by ce1-runner-private-mirror.yml.
        "scripts/ce1_runner_private_mirror.py",
        _exact_lines(
            'ROOT = "sha256:ce1b123c98e273479e08e6315fc81f7017957c23dbf88878076e75572b7b18cc"'
            "  # public image digest"
        ),
        _MIGRATION_SNAPSHOT,
    ),
    (
        # blazing: the fixed seven-tag GHCR snapshot preserved by ghcr-runner-seven-tag-*.yml.
        "scripts/ghcr_runner_tag_migration.py",
        _exact_lines(
            'AAF = "sha256:aaf3799b5e138abef0831bb8467ded7325164316f0cfde5c183fe6e129eae79e"',
            '"candidate-3259dfc6c6221db9ade4d6e1dca423a32a785008": '
            '"sha256:a88afbda5e9a6fc333898766c7831a25931433eb92af6ee95ddb0fa2ab2edb6b",',
            '"candidate-40706a10807d39e7d31065a360b3b3ce95668464": '
            '"sha256:3c99f89b9b88440d40e418a2d5d74a8e8cad902e8d545504aaed23c8e9fd7a43",',
            '"candidate-6f5c30c4220c54ec4a9f0f2cfef472f8bb39ce9c": '
            '"sha256:588f5fa1e514343832393c1ca31b990d8586c5f7ab69035adc2ecb376502f10a",',
            '"candidate-cce642e0c1dbe1be8cbd869de2e4a1539338f291": '
            '"sha256:5b43d797d92bb081d2e085046b48579ebf0448a48fcc32f562eafa0c811b4a32",',
        ),
        _MIGRATION_SNAPSHOT,
    ),
)


def _is_test_path(rel: Path) -> bool:
    dirs = rel.parts[:-1]
    in_test_dir = bool(_TEST_DIRS & set(dirs))
    name = rel.name
    python_test = rel.suffix == ".py" and (
        name.startswith("test_") or name.endswith("_test.py") or name == "conftest.py"
    )
    # fixtures/ only counts inside a test directory: a shipped role's files/fixtures/ is code.
    return in_test_dir or python_test


def _never(rel: Path) -> bool:
    return bool(_NEVER_DIRS & set(rel.parts[:-1]))


def _code_part(line: str, suffix: str) -> str:
    stripped = line.lstrip()
    if suffix in _HASH_COMMENT_SUFFIXES:
        if stripped.startswith("#"):
            return ""
        return _TRAILING_COMMENT.sub("", line)
    return line


def _pre_fix(text: str) -> list[str]:
    return sorted(set(_DIGEST.findall(text.lower())) & PRE_EMUDHRA_DIGESTS)


def _message(digest: str) -> str:
    return (
        f"pre-fix runner digest {digest} (built before the eMudhra/emSign CA distrust, "
        f"df-cicd-rpi.1) is referenced; pin {FIXED_INDEX} or a later df-akash-runner build"
    )


def findings(text: str, suffix: str = ".yml") -> list[str]:
    """Findings for one file's text: pre-fix digests in its code (comments are history)."""
    code = "\n".join(_code_part(line, suffix) for line in text.splitlines())
    return [_message(d) for d in _pre_fix(code)]


def negative_control_findings(rel: str, text: str) -> list[str]:
    """Flynn's OLD_IMAGE must stay a pre-fix image, or the negative control proves nothing."""
    if rel != ".github/scripts/verify_owned_worker_image.py":
        return []
    out = []
    for line in text.splitlines():
        match = _FLYNN_CONTROL.match(line.strip())
        if match and match.group(1).lower() not in PRE_EMUDHRA_DIGESTS:
            out.append(
                f"negative control is not pre-fix: OLD_IMAGE names {match.group(1)}, which "
                "is not a pre-eMudhra image, so executing it no longer proves the gate refuses"
            )
    return out


def _allowed(rel: str, line: str) -> bool:
    for path, pattern, _ in ALLOWLIST:
        if rel != path:
            continue
        # Only consulted for a line that already names a pre-fix digest, so a match is enough.
        # A negative control repointed at a FIXED image is caught by negative_control_findings,
        # not here (it has no pre-fix hit to exempt).
        if pattern.match(line.strip()):
            return True
    return False


def code_findings(root: Path) -> list[tuple[str, str]]:
    """(repo-relative file, finding) for non-test code outside the workflows directory."""
    out: list[tuple[str, str]] = []
    workflows = (root / ".github" / "workflows").resolve()
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in _CODE_SUFFIXES:
            continue
        rel = path.relative_to(root)
        if _never(rel) or _is_test_path(rel) or workflows in path.resolve().parents:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        posix = rel.as_posix()
        out += [(posix, f) for f in negative_control_findings(posix, text)]
        for line in text.splitlines():
            code = _code_part(line, path.suffix)
            if _pre_fix(code) and not _allowed(posix, line):
                out += [(posix, f) for f in findings(code, path.suffix)]
    return out


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
        for finding in findings(path.read_text(encoding="utf-8"), path.suffix):
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
