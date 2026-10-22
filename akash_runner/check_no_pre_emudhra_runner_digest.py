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
    print(f"Pre-eMudhra runner digests: {bad} reference(s) to a pre-fix image")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
