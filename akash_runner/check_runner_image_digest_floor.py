#!/usr/bin/env python3
"""Runner image pins must be immutable *and current enough to run jobs.

The incident behind this rule was a deprecated runner binary that could still
REGISTER but could not receive messages. A supervisor restarted it from the
same image, producing 13.2 registrations/minute from already-closed leases.
Deploying ``:latest`` is not a fix: provider caches served different layers for
the same tag. Only a digest binds the image identity.

This is also the checker-ref defect in another costume. Both a container digest
and a checker ref are pinned for reproducibility; both can therefore go stale
silently while still satisfying a reachability-only check. A pin must be checked
for CURRENCY, not only for reachability.

The runtime half is intentionally out of scope here: ``deprecated and cannot
receive messages`` is terminal, not transient, so the supervisor must fail fast
and let the deployment die. That belongs in the runner SDL/supervisor, not this
static rule.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

SUPPORTED_FLOOR = (2, 336, 0)
_RUNNER_RE = re.compile(r"(?:^|/)github-runner:(?P<tag>[^@\s]+)(?:@(?P<digest>sha256:[0-9a-fA-F]{64}))?$")
_IMAGE_REF = re.compile(r"(?:[A-Za-z0-9_.-]+/)?github-runner:[^\s\"'<>`]+")
_VERSION_RE = re.compile(r"^(?P<version>\d+\.\d+\.\d+)(?:-|$)")


def _runner_images(value: object) -> list[str]:
    """Return runner image scalars from an arbitrarily nested YAML document."""
    if isinstance(value, str):
        return [ref.rstrip(",;)") for ref in _IMAGE_REF.findall(value)]
    if isinstance(value, dict):
        images: list[str] = []
        for key, child in value.items():
            if key == "image" and isinstance(child, str) and "github-runner:" in child:
                images.append(child.strip())
                continue
            images.extend(_runner_images(child))
        return images
    if isinstance(value, list):
        images = []
        for child in value:
            images.extend(_runner_images(child))
        return images
    return []


def _source_runner_images(text: str) -> list[str]:
    """Find references in YAML and embedded SDL, excluding prose comments."""
    return _runner_images("\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#")))


def _version(tag: str) -> tuple[int, int, int] | None:
    match = _VERSION_RE.match(tag)
    return tuple(int(part) for part in match.group("version").split(".")) if match else None


def findings(document: dict | str) -> list[str]:
    """Return floating, below-floor, or unverifiable runner-image findings."""
    out: list[str] = []
    for image in _runner_images(document):
        match = _RUNNER_RE.search(image)
        if not match:
            out.append(f"runner image {image!r} is not a valid digest-pinned reference")
            continue
        version = _version(match.group("tag"))
        if not match.group("digest"):
            out.append(f"runner image {image!r} is floating; pin it with @sha256:<digest>")
            continue
        if version is None:
            out.append(f"runner image {image!r} has a digest but no verifiable version tag")
            continue
        if version < SUPPORTED_FLOOR:
            floor = ".".join(map(str, SUPPORTED_FLOOR))
            out.append(
                f"runner image {image!r} is below supported floor "
                f"{floor} (version {'.'.join(map(str, version))})"
            )
    return out


def check_workflow(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
        yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return [f"{path}: invalid YAML: {exc}"]
    # Scan the source text as well as parsed YAML: SDL is commonly embedded in
    # a shell heredoc, where YAML parsing turns the whole block into one scalar.
    return findings("\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#")))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workflows-dir", default=".github/workflows")
    args = ap.parse_args(argv)
    root = Path(args.workflows_dir)
    if not root.is_dir():
        print(f"Runner images: NOT APPLICABLE — {root} is not a directory")
        return 0
    files = sorted(root.glob("*.yml")) + sorted(root.glob("*.yaml"))
    runner_files = 0
    bad = 0
    for path in files:
        text = path.read_text(encoding="utf-8")
        file_findings = check_workflow(path)
        if _source_runner_images(text):
            runner_files += 1
        for finding in file_findings:
            bad += 1
            print(f"::error file={path},title=Runner image pin::{finding}")
    if runner_files == 0:
        print("Runner images: NOT APPLICABLE — no runner image references found")
        return 0
    if bad:
        return 1
    print(f"Runner images: PASS — {runner_files} workflow(s) checked")
    return 0


if __name__ == "__main__":
    sys.exit(main())
