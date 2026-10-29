#!/usr/bin/env python3
"""No runner image built before the eMudhra/emSign CA distrust may be referenced (df-cicd-rpi.1).

CVE-2026-111943 (golang/go#82345): 8 intermediates whose keys were compromised are each issued
by an emSign root AND cross-signed by AAA Certificate Services, so an image built before the
distrust can trust chains through them. df-akash-runner was rebuilt with the CA floor and the
8 keys rejected (index sha256:e71bf4be..., 2026-10-22).

The rule is "no pre-fix digest is admissible", not "must equal the fix", so any later rebuild
passes. The list is MEASURED: every df-akash-runner manifest GHCR published before the fixed
index, minus that index's own children (data/df_akash_runner_pre_emudhra_digests.txt).

MODE: ENFORCING since 2026-10-23, promoted after every consumer scanned 0 at origin/main (the
measurement is recorded at test_every_rule_has_a_call_site.ENFORCING). Unlike
check_runner_image_digest_floor, which stays advisory because a version floor rots on GitHub's
deprecation dates, a pre-fix image stays pre-fix forever, so this answer cannot rot.

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
not read (only code suffixes). Under the workflows dir, only the direct *.yml/*.yaml children
are workflows; nested files and other suffixes there are scanned as code.

COMMENTS ARE HISTORY. A full-line comment is skipped, and so is a trailing comment: anything
after whitespace + "#" on yml/yaml/py/sh/toml/cfg/ini lines. So `image: ...@<fixed>  # was
<pre-fix>` passes. Known limit: a " #" inside a quoted string also ends the scanned part of
that line.

ALLOWLIST. A file that MUST hold a pre-fix digest gets an entry: path, a line pattern, and a
reason. Generated RECORDS (SBOMs, attestations, receipts such as blazing's owned-history
proof) name pre-fix digests as history, not pins. They go in ALLOWLIST by path with `.*` and
their regeneration owner, rather than by dropping a suffix from the scan.

ONE LEVEL OF INDIRECTION (df-cicd-rpi.10). A `uses:` of a just-akash reusable workflow at a
sha runs what just-akash's files name at THAT sha, which is not in the consumer's files.
Measured 2026-10-29: df-cicd's template pinned runner-pool.yml@ca353a9c (pre-fix aaf3799b) and
this rule said 0. Such a call is red when the sha is in data/just_akash_pre_emudhra_commits.txt:
every just-akash commit whose tree pins a pre-fix image in non-test code (a workflow, or an SDL
such as sdl/github-runner-probe.yaml), measured by generate_just_akash_pre_emudhra_refs.py.
Offline: no network at check time. A just-akash `uses:` at anything other than a 40-hex sha (a
tag or a branch) is red too, because the list cannot judge a ref that moves: v1.50.0 and 103
branches resolved to listed commits (df-grafana-7e on #88). RESIDUAL: a sha the file does not
list passes. A new just-akash commit that re-introduces a pre-fix digest is invisible here until
the generator re-runs; the scheduled just-akash-refs.yml workflow re-runs it and fails on any
unlisted commit. Only the called sha's own tree is judged, not the shas IT calls.
"""

from __future__ import annotations

import argparse
import hashlib
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
JUST_AKASH_COMMITS_DATA = Path(__file__).resolve().parent / "data" / "just_akash_pre_emudhra_commits.txt"


def load_just_akash_commits(path: Path = JUST_AKASH_COMMITS_DATA) -> frozenset[str]:
    """Listed commits; a missing file is an error, never 'none listed'."""
    return frozenset(
        fields[0]
        for fields in (line.split() for line in path.read_text(encoding="utf-8").splitlines())
        if fields and not fields[0].startswith("#")
    )


JUST_AKASH_PRE_EMUDHRA_COMMITS = load_just_akash_commits()
_JUST_AKASH_USES = re.compile(
    r"\buses:\s*['\"]?digital-frontier-lda/just-akash/(\.github/workflows/[\w.-]+\.ya?ml)@([^\s'\"]+)",
    re.IGNORECASE,
)
_SHA = re.compile(r"[0-9a-f]{40}", re.IGNORECASE)
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


class _ExactLineHashes:
    """Allow exactly the stripped lines whose sha256 is listed, and nothing else in the file.

    Stored as HASHES, not as the lines: the lines name pre-fix digests, and this file is
    non-test code that the repo-wide scan reads, so a verbatim allowlist made the checker flag
    its own source (#85 review). A hash names no digest and still matches one exact line.
    """

    def __init__(self, *sha256_hex: str) -> None:
        self._hashes = frozenset(sha256_hex)

    def match(self, line: str) -> bool:
        return hashlib.sha256(line.encode("utf-8")).hexdigest() in self._hashes


_MIGRATION_SNAPSHOT = (
    "one-shot migration snapshot; push trigger scoped to codex/...-2026100x branches: the "
    "constant is the pre-fix image being preserved, not a runner being run (decided by the "
    "team, akash-github-runner#85, 2026-10-22)."
)

# (repo-relative path, line regex, reason). A line matching the regex may name a pre-fix
# digest; nothing else in that file may. Keep each entry as narrow as the case.
ALLOWLIST: tuple[tuple[str, re.Pattern[str] | _ExactLineHashes, str], ...] = (
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
        # sha256 of: ROOT = "<ce1b123c... public digest>"  # public image digest
        _ExactLineHashes("33af5dbb9a7eea3f7c62bc494ac6038c7ca5fa557cf4751e4cb3150bd5d6a7da"),
        _MIGRATION_SNAPSHOT,
    ),
    (
        # blazing: the fixed seven-tag GHCR snapshot preserved by ghcr-runner-seven-tag-*.yml.
        "scripts/ghcr_runner_tag_migration.py",
        # sha256 of the AAF constant (aaf3799b) and the 4 "candidate-<sha>": "<digest>",
        # lines (a88afbda, 3c99f89b, 588f5fa1, 5b43d797), each stripped, at blazing 5ad80fa9.
        _ExactLineHashes(
            "49f16c4001b6e86a2ca3387d820ae7cf166699697f2226530d52a382061d4044",
            "39fcb64834a91b3a8b401978088b5d216a7934f2791d32147f96e614c0ff9dd1",
            "54e5161e6e9d282404b730576d77904c643d42885d941d8c3045a9c42b6aadb9",
            "67c9edad8d2069e2e6698e6241d80f2aaf142129b491a536bd7833f09eaac550",
            "718d1725a774d8634d7649ef621b391bcc81d50c7c20219f141e3c3fc1d0873e",
        ),
        _MIGRATION_SNAPSHOT,
    ),
    (
        # this repo: test_pool_handoff_lifetime's caller, an offline extract of df-cicd@061d2d09's
        # template. Only its two `uses:` lines (pool and teardown, both at the listed ca353a9c).
        "akash_runner/fixtures/pool_handoff/caller.yml",
        # sha256 of: uses: Digital-Frontier-LDA/just-akash/.github/workflows/runner-{pool,teardown}.yml@ca353a9c...
        _ExactLineHashes(
            "550ea51dcffaaff5a15a08cc5780a5a2e2663fdb8952dfccc9324e67c4899f5c",
            "39a679dd025773b89fbd5f8657c709cd7a79210b3fa05aa354657f45a79bdcc4",
        ),
        "An EXTRACT, never executed: test_pool_handoff_lifetime models the reusable call offline, "
        "and its header names the df-cicd commit it was copied from, so repinning would falsify "
        "that provenance (df-cicd-rpi.10).",
    ),
    (
        # this repo: the callee side of the same extract, copied from just-akash@0b16405e's
        # runner-pool.yml. Only its teardown `uses:` line (85f85970, a listed sha).
        "akash_runner/fixtures/pool_handoff/callee.yml",
        # sha256 of: uses: Digital-Frontier-LDA/just-akash/.github/workflows/runner-teardown.yml@85f85970...
        _ExactLineHashes("6b5409862b474b2de674202e6ee20592e22f67353233032dc3f7f4ed3407982f"),
        "An EXTRACT, never executed, of just-akash@0b16405e: its header names that commit, so "
        "repinning would falsify that provenance (df-cicd-rpi.10).",
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


def indirect_findings(text: str, suffix: str = ".yml") -> list[str]:
    """A just-akash reusable workflow called at a listed sha, or at a ref that is not a sha."""
    out = []
    for line in text.splitlines():
        for match in _JUST_AKASH_USES.finditer(_code_part(line, suffix)):
            path, ref = match.group(1), match.group(2)
            if not _SHA.fullmatch(ref):
                out.append(
                    f"just-akash {path}@{ref} is not pinned to a 40-hex sha, so whether it runs "
                    f"a pre-fix runner image cannot be judged (df-cicd-rpi.10); pin the sha"
                )
            elif ref.lower() in JUST_AKASH_PRE_EMUDHRA_COMMITS:
                out.append(
                    f"just-akash {path}@{ref.lower()} is a commit whose tree pins a pre-fix runner "
                    f"image (built before the eMudhra/emSign CA distrust, df-cicd-rpi.10), whether "
                    f"or not this file is the one that names it; move every just-akash pin to a sha "
                    f"whose tree names {FIXED_INDEX} or a later build"
                )
    return out


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
        # Skip only what main() already scans as a workflow: DIRECT *.yml/*.yaml children. Anything
        # else under the workflows dir (scripts/run.sh, sdl/x.yaml, helper.py) is code.
        scanned_as_workflow = path.suffix in {".yml", ".yaml"} and path.resolve().parent == workflows
        if _never(rel) or _is_test_path(rel) or scanned_as_workflow:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        posix = rel.as_posix()
        out += [(posix, f) for f in negative_control_findings(posix, text)]
        for line in text.splitlines():
            if not _allowed(posix, line):
                out += [(posix, f) for f in indirect_findings(line, path.suffix)]
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
        text = path.read_text(encoding="utf-8")
        for finding in findings(text, path.suffix) + indirect_findings(text, path.suffix):
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
