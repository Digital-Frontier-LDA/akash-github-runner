#!/usr/bin/env python3
"""Org baseline conformance checker — the single definition of "is this repo compliant".

Runs against ANY Digital-Frontier-LDA repo checkout (`--root`). Consumers invoke it
through `.github/workflows/reusable-conformance.yml` pinned to a tag, so the rules live
here once instead of being vendored (and drifting) 31 times.

Every rule here exists because the invariant was broken in practice:

* ``secrets-only-sops`` — after the SOPS migration left one GitHub secret, two later PRs
  re-added a direct ``secrets.AKASH_API_KEY``. A direct reference is ordinary-looking
  YAML that *works*, so nothing surfaced it until someone re-read the workflows.
* ``action-pinning`` — a mutable tag can be repointed by its owner; a ``@main`` ref is
  strictly worse (every push to that branch changes what we execute, with no release
  in between).
* ``changelog`` — a naive merge left a repo with two sections claiming one version, in
  an order that no longer descended.

Design rules for this file:

1. **Report, never mutate.** A conformance checker that edits repos cannot be run
   safely in the inventory phase.
2. **Machine-readable first.** ``--json`` emits the per-rule verdicts that the org-wide
   matrix aggregates; the human text is a rendering of the same data.
3. **Never crash on a weird repo.** A rule that raises takes the whole matrix down, so
   an unreadable/absent input is a ``skip`` or a finding — never a traceback.

Exit: 0 = conformant (no required-rule findings), 1 = findings, 2 = usage error.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

SCHEMA_VERSION = 1

# Actions from our own org: consumers pin these by TAG, which is df-cicd's documented
# model ("consumers reference it at a pinned tag").
FIRST_PARTY_ORG = "Digital-Frontier-LDA"

# The only GitHub secrets a repo may reference directly. Everything else belongs in
# secrets/*.sops.env, read through the df-cicd sops-env action.
#   SOPS_AGE_KEY / SOPS_AGE_KEY_FILE — the bootstrap key that decrypts all the others.
#   GITHUB_TOKEN — auto-provisioned per job, never stored by us; SOPS could not hold it
#   even in principle, so forbidding it would buy nothing and force contortions.
ALLOWED_SECRETS = frozenset({"SOPS_AGE_KEY", "SOPS_AGE_KEY_FILE", "GITHUB_TOKEN"})
# GitHub resolves context and secret names case-INSENSITIVELY: ${{ SECRETS.X }} and
# ${{ secrets.sops_age_key }} both work. Matching case-sensitively would both miss
# violations and false-flag valid allowlisted spellings.
_ALLOWED_LOWER = frozenset(n.lower() for n in ALLOWED_SECRETS)

# Match `secrets.NAME` only INSIDE a ${{ }} expression. A bare `grep secrets\.` also
# matches the detect-secrets baseline FILENAME (`.secrets.baseline`), which appears in
# these very workflows — and a checker that cries wolf on its own repo gets disabled.
_EXPR = re.compile(r"\$\{\{(.*?)\}\}", re.S)
_SECRET_REF = re.compile(r"\bsecrets\.([A-Za-z_][A-Za-z_0-9]*)", re.I)
# Dot notation is not the only way to reach a secret. `secrets['NAME']` and
# `secrets["NAME"]` are equivalent, and `toJSON(secrets)` serialises the ENTIRE secret
# store into one string — the worst case, and the one a name-based rule misses most
# easily. A rule that only understands `secrets.NAME` is trivially side-stepped without
# anyone intending to.
_SECRET_INDEX = re.compile(r"\bsecrets\s*\[\s*['\"]([A-Za-z_][A-Za-z_0-9]*)['\"]\s*\]", re.I)
_SECRET_WHOLE = re.compile(r"\btojson\s*\(\s*secrets\s*\)", re.I)
# Dynamic indexing — `secrets[format('X_{0}', y)]`, `secrets[matrix.name]`. The name is
# not statically knowable, so it can never be checked against the allowlist.
_SECRET_DYNAMIC = re.compile(r"\bsecrets\s*\[\s*(?!['\"])", re.I)
# `uses:` as a block key, optionally quoted, optionally inside a flow mapping
# (`- { uses: x }`). Plain `^\s*uses:` misses both quoted keys and flow style.
_USES = re.compile(
    r"""(?:^\s*-?\s*|[{,]\s*)["']?uses["']?\s*:\s*["']?([^\s"'#,}]+)""", re.M
)
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_VERSION_HEADER = re.compile(r"^##\s*\[v?(\d+)\.(\d+)\.(\d+)\]", re.M)

_SEVERITY_ORDER = {"required": 0, "advisory": 1}


@dataclass
class Finding:
    """One conformance violation, anchored to a file/line where possible."""

    rule: str
    severity: str  # required | advisory
    message: str
    path: str | None = None
    line: int | None = None

    def location(self) -> str:
        if not self.path:
            return ""
        return f"{self.path}:{self.line}" if self.line else self.path

    def as_dict(self) -> dict:
        return {
            "rule": self.rule,
            "severity": self.severity,
            "message": self.message,
            "path": self.path,
            "line": self.line,
        }


@dataclass
class RuleResult:
    """A rule's verdict for one repo: pass / fail / n-a (rule does not apply here)."""

    rule: str
    status: str  # pass | fail | n-a
    findings: list[Finding] = field(default_factory=list)
    note: str = ""

    def as_dict(self) -> dict:
        return {
            "rule": self.rule,
            "status": self.status,
            "note": self.note,
            "findings": [f.as_dict() for f in self.findings],
        }


# --------------------------------------------------------------------------- helpers


def _status(findings: list[Finding]) -> str:
    """A rule's status. Advisory-only findings are `warn`, never `fail` — calling an
    advisory a failure trains readers to ignore the word, and only `fail` (a required
    finding) is allowed to gate."""
    if any(f.severity == "required" for f in findings):
        return "fail"
    return "warn" if findings else "pass"


def _read(path: Path) -> str:
    """File text, or '' when unreadable. Never raises — see design rule 3."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _workflow_files(root: Path) -> list[Path]:
    """Workflow + composite-action YAML, sorted for stable output."""
    out: list[Path] = []
    for rel in (".github/workflows", ".github/actions"):
        base = root / rel
        if base.is_dir():
            out.extend(p for p in base.rglob("*.y*ml") if p.is_file())
    # A composite action may also live at the repo ROOT (`action.yml`) — df-cicd's own
    # canonical action does, and was invisible to an earlier version of this scan.
    for name in ("action.yml", "action.yaml"):
        candidate = root / name
        if candidate.is_file():
            out.append(candidate)
    return sorted(set(out))


def _line_of(text: str, needle: str) -> int | None:
    # Raw text: this is also used to anchor CHANGELOG.md findings, where a leading `#`
    # is a MARKDOWN HEADING, not a comment. Comment-stripping is a YAML concern and
    # belongs only in the secret scan (see rule_secrets_only_sops).
    for i, line in enumerate(text.splitlines(), 1):
        if needle in line:
            return i
    return None


_BLOCK_SCALAR = re.compile(r":\s*[|>][+-]?\d*\s*$")


def _strip_comments(text: str) -> str:
    """Blank out YAML ``#`` comments so a ``${{ secrets.X }}`` shown in DOCUMENTATION is
    not read as a real reference.

    Real bug this fixes: latitude-api-adapter's workflows contain comments like
    ``# if: ${{ secrets.X != '' }}`` explaining a pattern, and the scanner reported a
    nonexistent secret named ``X`` — inflating the finding count and sending the
    migration worklist hunting for a secret that does not exist.

    Three correctness constraints (the last two caught by CodeRabbit on the PR that
    introduced this):

    * **Quote-aware.** A ``#`` starts a comment only at line start or after whitespace
      and only outside quotes — so ``echo "a # b"`` and ``foo#bar`` are untouched.
    * **Line-terminator-preserving.** The comment text is replaced with spaces but the
      trailing ``\\n``/``\\r\\n`` is kept, or blanked lines would MERGE and every line
      number after the first comment would shift.
    * **Block-scalar-aware.** A ``#`` inside a ``run: |`` / ``>`` block is NOT a YAML
      comment — and GitHub interpolates ``${{ }}`` everywhere, INCLUDING inside such a
      block, so a ``${{ secrets.REAL }}`` sitting in a shell comment there is a genuine
      exposure. Stripping it would be a false NEGATIVE (a real secret un-flagged),
      which is strictly worse than the false positive this function exists to remove.
      So content indented under a block-scalar header is left verbatim.
    """
    out = []
    block_indent: int | None = None  # indentation of the active block scalar's content
    for line in text.splitlines(keepends=True):
        stripped = line.lstrip(" ")
        indent = len(line) - len(stripped)
        blank = stripped in ("", "\n", "\r\n", "\r")

        # Leave the body of a `|`/`>` block scalar untouched: its `#`s are content.
        if block_indent is not None:
            if blank or indent > block_indent:
                out.append(line)
                continue
            block_indent = None  # dedented out of the block

        q = None  # active quote char, or None
        cut = None
        for i, ch in enumerate(line):
            if q:
                if ch == q:
                    q = None
            elif ch in "\"'":
                q = ch
            elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
                cut = i
                break

        if cut is None:
            out.append(line)
            # A `key: |` opens a block scalar whose more-indented lines are content.
            if _BLOCK_SCALAR.search(line):
                block_indent = indent
        else:
            # Replace only the comment TEXT with spaces; keep any line terminator.
            comment = line[cut:]
            out.append(line[:cut] + "".join(c if c in "\r\n" else " " for c in comment))
    return "".join(out)


def secret_refs(text: str) -> set[str]:
    """GitHub secret names reachable from ``${{ }}`` expressions (comments stripped).

    Covers `secrets.NAME`, `secrets['NAME']`, `toJSON(secrets)` (reported as the
    pseudo-name ``*`` because it exposes every secret at once) and dynamic indexing
    (``?``, because the name is not statically knowable and so can never be cleared
    against the allowlist).
    """
    names: set[str] = set()
    for expr in _EXPR.findall(_strip_comments(text)):
        names.update(_SECRET_REF.findall(expr))
        names.update(_SECRET_INDEX.findall(expr))
        if _SECRET_WHOLE.search(expr):
            names.add("*")
        if _SECRET_DYNAMIC.search(expr):
            names.add("?")
    return names


def classify(root: Path) -> set[str]:
    """Repo traits that decide which REQUIRED-IF rules apply.

    Traits, not a single class: a repo can be both ``versioned`` and ``iac``, and
    forcing it into one bucket would silently drop a rule that should apply.
    """
    traits: set[str] = set()
    if (root / ".github/workflows").is_dir():
        traits.add("ci")
    if any((root / f).is_file() for f in ("pyproject.toml", "package.json", "VERSION")):
        traits.add("versioned")
    if (root / "CHANGELOG.md").is_file():
        traits.add("changelog")
    if list(root.glob("**/*.tf")) or list(root.glob("**/*.hcl")):
        traits.add("iac")
    if list(root.glob("secrets/*.sops.*")) or (root / ".sops.yaml").is_file():
        traits.add("sops")
    return traits


# ----------------------------------------------------------------------------- rules


# Registry `type`s for a secret that legitimately must NOT live in git-committed SOPS —
# HSM-bound or regulatory values. The registry stores a reference/handle + fetch path, not
# the value; such a secret stays a direct `${{ secrets.X }}` by design.
_EXTERNAL_VAULT_TYPES = frozenset({"external-vault", "external-kms"})


def _external_vault_secrets(root: Path) -> set[str]:
    """Lowercased names of secrets a repo's `secrets/registry.yaml` declares as an external
    vault/KMS exception. A direct `secrets.X` for one of these is a DOCUMENTED exception, not
    a violation. Needs PyYAML; absent/malformed/PyYAML-missing → empty set (fail-CLOSED for
    safety: if we cannot read the registry we do NOT grant exceptions, so nothing is silently
    excused). Names only — never a value."""
    f = root / "secrets" / "registry.yaml"
    if not f.is_file():
        return set()
    try:
        import yaml
    except ImportError:
        return set()
    try:
        data = yaml.safe_load(f.read_text(errors="replace")) or {}
    except Exception:  # noqa: BLE001 — a malformed registry grants no exceptions, never raises
        return set()
    if not isinstance(data, dict) or not isinstance(data.get("secrets"), dict):
        return set()
    out: set[str] = set()
    for entry, meta in data["secrets"].items():
        if not isinstance(meta, dict):
            continue
        if str(meta.get("type", "")).lower() not in _EXTERNAL_VAULT_TYPES:
            continue
        # The GitHub secret name(s) this exception covers: each consumer key, plus the entry
        # name itself (registries that name the entry after the secret). Never the checker's
        # pseudo-names `*` (toJSON) / `?` (dynamic index) — those can never be excused, or a
        # whole-secret/dynamic reference could be silently downgraded.
        if isinstance(entry, str) and entry not in ("*", "?"):
            out.add(entry.lower())
        for c in (meta.get("consumers") or []):
            key = c.get("key") if isinstance(c, dict) else None
            if isinstance(key, str) and key not in ("*", "?"):
                out.add(key.lower())
    return out


def rule_secrets_only_sops(root: Path, traits: set[str]) -> RuleResult:
    """Only allowlisted GitHub secrets may be referenced; the rest live in SOPS.

    A secret the registry declares `type: external-vault`/`external-kms` is a DOCUMENTED
    exception (it cannot live in git-committed SOPS) — reported as advisory, not a required
    finding, so the repo can be conformant while keeping it a direct reference."""
    if "ci" not in traits:
        return RuleResult("secrets-only-sops", "n-a", note="no .github/workflows")
    external = _external_vault_secrets(root)
    findings: list[Finding] = []
    for path in _workflow_files(root):
        text = _read(path)
        # Anchor findings against the comment-stripped text, so a real secret that ALSO
        # appears by name in a comment can't have its line reported at the comment.
        located = _strip_comments(text)
        rel = str(path.relative_to(root))
        for name in sorted(n for n in secret_refs(text) if n.lower() not in _ALLOWED_LOWER):
            if name.lower() in external:
                findings.append(Finding(
                    "secrets-only-sops", "advisory",
                    f"references secrets.{name} directly — DOCUMENTED external secret-store "
                    "exception per secrets/registry.yaml (cannot live in git-committed SOPS; "
                    "the registry holds a reference/handle, not the value)",
                    rel, _line_of(located, name)))
                continue
            if name == "*":
                msg = (
                    "uses toJSON(secrets), which serialises EVERY GitHub secret into one "
                    "string — no allowlist can constrain it. Read the specific values "
                    "from secrets/ci.sops.env via the df-cicd sops-env action instead."
                )
                anchor = "secrets)"
            elif name == "?":
                msg = (
                    "indexes secrets[] dynamically, so the secret name is not statically "
                    "knowable and cannot be checked against the allowlist. Use an "
                    "explicit name, or read it from secrets/ci.sops.env."
                )
                anchor = "secrets["
            else:
                msg = (
                    f"references secrets.{name} directly — move it into "
                    f"secrets/ci.sops.env and read it via the df-cicd sops-env action"
                )
                anchor = name
            findings.append(
                Finding("secrets-only-sops", "required", msg, rel, _line_of(located, anchor))
            )
    return RuleResult("secrets-only-sops", _status(findings), findings)


def rule_action_pinning(root: Path, traits: set[str]) -> RuleResult:
    """Every `uses:` pinned to a 40-char SHA; branch refs are never acceptable."""
    if "ci" not in traits:
        return RuleResult("action-pinning", "n-a", note="no .github/workflows")
    findings: list[Finding] = []
    for path in _workflow_files(root):
        rel = str(path.relative_to(root))
        # Scan LINE BY LINE, not with a whole-file regex + first-match lookup: the
        # same `uses:` commonly appears several times in one workflow, and a
        # first-match line number reports every occurrence at the first one. Three
        # findings pointing at one line is the kind of noise that gets a checker
        # switched off.
        for lineno, raw in enumerate(_read(path).splitlines(), 1):
            # findall, not match: the shared _USES pattern also accepts quoted keys
            # ("uses":) and flow-style mappings (- { uses: x }), and one flow line can
            # legitimately carry more than one.
            for ref in _USES.findall(raw):
                ref = ref.strip().strip("\"'")
                # A local action (./.github/actions/x) is versioned by this repo itself.
                if ref.startswith("./"):
                    continue
                if ref.startswith("docker://"):
                    # A docker tag is as mutable as a git tag; only a digest is fixed.
                    if "@sha256:" not in ref:
                        findings.append(
                            Finding(
                                "action-pinning",
                                "advisory",
                                f"`uses: {ref}` pins a Docker TAG, which the publisher can "
                                f"repoint. Pin a digest (image@sha256:...).",
                                rel,
                                lineno,
                            )
                        )
                    continue
                if "@" not in ref:
                    findings.append(
                        Finding("action-pinning", "required", f"`uses: {ref}` has no ref at all", rel, lineno)
                    )
                    continue
                _, _, version = ref.rpartition("@")
                if version in ("main", "master", "HEAD"):
                    findings.append(
                        Finding(
                            "action-pinning",
                            "required",
                            f"`uses: {ref}` pins a BRANCH — every push to it changes what we "
                            f"execute, with no release in between. Pin a 40-char SHA.",
                            rel,
                            lineno,
                        )
                    )
                elif _SHA40.match(version):
                    continue  # correctly pinned
                elif re.fullmatch(r"[0-9a-f]{7,63}", version):
                    # Hex but not 40 chars: either an abbreviated SHA or a typo'd/invented
                    # one. `uses:` does not accept abbreviations — GitHub cannot resolve
                    # this ref, so the step fails at runtime. Distinct from a tag, and
                    # required, because it is broken rather than merely mutable.
                    findings.append(
                        Finding(
                            "action-pinning",
                            "required",
                            f"`uses: {ref}` looks like a SHA but is {len(version)} hex chars, "
                            f"not 40 — `uses:` does not accept abbreviated SHAs, so this ref "
                            f"cannot resolve. Verify it against the upstream repo.",
                            rel,
                            lineno,
                        )
                    )
                elif ref.startswith(f"{FIRST_PARTY_ORG}/"):
                    # First-party tags are exempt, by design and not by oversight. The
                    # risk a SHA pin defends against is an UPSTREAM owner silently
                    # repointing a tag; for our own org that "upstream" is us, under
                    # branch protection and the verify-action-pins gate. Flagging it
                    # would also make the baseline flag ITSELF in every repo that
                    # adopts it — and a checker that cries wolf on its own integration
                    # is the fastest way to get the whole thing switched off.
                    continue
                else:
                    findings.append(
                        Finding(
                            "action-pinning",
                            "advisory",
                            f"`uses: {ref}` pins a mutable tag — repoint-able by its owner. "
                            f"Pin a 40-char SHA with a trailing `# {version}` comment.",
                            rel,
                            lineno,
                        )
                    )
    return RuleResult("action-pinning", _status(findings), findings)


def rule_changelog(root: Path, traits: set[str]) -> RuleResult:
    """Changelog versions unique, strictly descending, and matching the package version."""
    if "changelog" not in traits:
        return RuleResult("changelog", "n-a", note="no CHANGELOG.md")
    findings: list[Finding] = []
    text = _read(root / "CHANGELOG.md")
    versions = [tuple(map(int, m)) for m in _VERSION_HEADER.findall(text)]
    if not versions:
        return RuleResult("changelog", "n-a", note="CHANGELOG.md has no '## [x.y.z]' headers")

    seen: set[tuple[int, ...]] = set()
    for v in versions:
        dotted = ".".join(map(str, v))
        if v in seen:
            findings.append(
                Finding(
                    "changelog",
                    "required",
                    f"duplicate section for {dotted} — two sections claiming one version "
                    f"(usually a merge that re-added a header instead of folding into it)",
                    "CHANGELOG.md",
                    _line_of(text, f"[{dotted}]"),
                )
            )
        seen.add(v)
    for newer, older in zip(versions, versions[1:]):
        if newer <= older:
            findings.append(
                Finding(
                    "changelog",
                    "required",
                    f"{'.'.join(map(str, newer))} is listed above "
                    f"{'.'.join(map(str, older))} but is not newer — sections must descend",
                    "CHANGELOG.md",
                )
            )

    declared = _declared_version(root)
    if declared:
        newest = ".".join(map(str, versions[0]))
        if declared.lstrip("v") != newest:
            findings.append(
                Finding(
                    "changelog",
                    "required",
                    f"version mismatch: package declares {declared} but the newest "
                    f"CHANGELOG section is {newest} — a release bumped one, not the other",
                    "CHANGELOG.md",
                    _line_of(text, f"[{newest}]"),
                )
            )
    return RuleResult("changelog", _status(findings), findings)


def _declared_version(root: Path) -> str | None:
    """The repo's own version, from whichever manifest it uses."""
    py = root / "pyproject.toml"
    if py.is_file():
        m = re.search(r'^version\s*=\s*"([^"]+)"', _read(py), re.M)
        if m:
            return m.group(1)
    pkg = root / "package.json"
    if pkg.is_file():
        try:
            v = json.loads(_read(pkg)).get("version")
            if isinstance(v, str):
                return v
        except ValueError:
            pass
    vf = root / "VERSION"
    if vf.is_file():
        v = _read(vf).strip()
        if v:
            return v
    return None


def rule_sops_hygiene(root: Path, traits: set[str]) -> RuleResult:
    """A repo using SOPS must declare recipients and block decrypted siblings."""
    if "sops" not in traits:
        return RuleResult("sops-hygiene", "n-a", note="repo does not use SOPS")
    findings: list[Finding] = []
    if not (root / ".sops.yaml").is_file():
        findings.append(
            Finding(
                "sops-hygiene",
                "required",
                "secrets/*.sops.* exist but there is no .sops.yaml — recipients are "
                "then implicit and a re-encrypt can silently drop a key",
            )
        )
    gitignore = _read(root / ".gitignore")
    # The decrypted sibling is the realistic leak: `sops -d x.sops.env > x.env`.
    if not re.search(r"^\s*secrets/\*?\.?env|^\s*secrets/\*\.env", gitignore, re.M):
        findings.append(
            Finding(
                "sops-hygiene",
                "advisory",
                "`.gitignore` does not block `secrets/*.env` — a decrypted sibling "
                "(sops -d x.sops.env > x.env) could be committed",
                ".gitignore",
            )
        )
    return RuleResult("sops-hygiene", _status(findings), findings)


def rule_dependabot_actions(root: Path, traits: set[str]) -> RuleResult:
    """Pinning without Dependabot trades supply-chain risk for staleness."""
    if "ci" not in traits:
        return RuleResult("dependabot-actions", "n-a", note="no .github/workflows")
    cfg = _read(root / ".github/dependabot.yml") or _read(root / ".github/dependabot.yaml")
    if not cfg:
        return RuleResult(
            "dependabot-actions",
            "warn",
            [
                Finding(
                    "dependabot-actions",
                    "advisory",
                    "no .github/dependabot.yml — SHA-pinned actions never get update "
                    "PRs, so pinning just trades supply-chain risk for staleness",
                )
            ],
        )
    if "github-actions" not in cfg:
        return RuleResult(
            "dependabot-actions",
            "warn",
            [
                Finding(
                    "dependabot-actions",
                    "advisory",
                    "dependabot config has no `github-actions` ecosystem entry",
                    ".github/dependabot.yml",
                )
            ],
        )
    return RuleResult("dependabot-actions", "pass")


RULES = (
    rule_secrets_only_sops,
    rule_action_pinning,
    rule_changelog,
    rule_sops_hygiene,
    rule_dependabot_actions,
)


# ------------------------------------------------------------------------- reporting


def evaluate(root: Path) -> dict:
    """Run every rule and return the machine-readable conformance record."""
    traits = classify(root)
    results = [rule(root, traits) for rule in RULES]
    findings = [f for r in results for f in r.findings]
    required = [f for f in findings if f.severity == "required"]
    return {
        "schema": SCHEMA_VERSION,
        "repo": root.name,
        "traits": sorted(traits),
        "conformant": not required,
        "counts": {
            "required": len(required),
            "advisory": len(findings) - len(required),
        },
        "rules": [r.as_dict() for r in results],
    }


def render(record: dict) -> str:
    """Human rendering of the same data `--json` emits."""
    lines = [
        f"Baseline conformance — {record['repo']}  "
        f"[traits: {', '.join(record['traits']) or 'none'}]",
        "",
    ]
    for rule in record["rules"]:
        mark = {"pass": "PASS", "fail": "FAIL", "warn": "warn", "n-a": " n/a"}[rule["status"]]
        note = f"  ({rule['note']})" if rule["note"] else ""
        lines.append(f"  [{mark}] {rule['rule']}{note}")
        for f in sorted(rule["findings"], key=lambda x: _SEVERITY_ORDER[x["severity"]]):
            loc = f"{f['path']}:{f['line']}" if f["line"] else (f["path"] or "")
            prefix = "required" if f["severity"] == "required" else "advisory"
            lines.append(f"        - [{prefix}] {loc}{': ' if loc else ''}{f['message']}")
    counts = record["counts"]
    lines += [
        "",
        f"  {counts['required']} required finding(s), {counts['advisory']} advisory.",
        "  CONFORMANT" if record["conformant"] else "  NOT CONFORMANT",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".", help="Repository root (default: cwd)")
    ap.add_argument("--json", action="store_true", help="Emit the machine-readable record")
    ap.add_argument(
        "--advisory-only",
        action="store_true",
        help="Report everything but always exit 0. Used during rollout so a repo can "
        "adopt the workflow before it is conformant (the matrix still records truth).",
    )
    args = ap.parse_args(argv)

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"error: --root {root} is not a directory", file=sys.stderr)
        return 2

    record = evaluate(root)
    print(json.dumps(record, indent=2) if args.json else render(record))

    if args.advisory_only or record["conformant"]:
        return 0
    # GitHub annotations so required findings land on the PR, not just in the log.
    # NEVER in --json mode: workflow commands share stdout with the record, and
    # appending them produced an unparseable `conformance.json` for exactly the
    # non-conformant repos the matrix most needs. The workflow already runs the
    # checker twice (once --json for the artifact, once plain for the human log),
    # so the annotations are emitted by that second run and nothing is lost.
    if args.json:
        return 1
    for rule in record["rules"]:
        for f in rule["findings"]:
            if f["severity"] != "required":
                continue
            loc = f"file={f['path']}," if f["path"] else ""
            loc += f"line={f['line']}," if f["line"] else ""
            print(f"::error {loc}title={f['rule']}::{f['message']}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
