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

import _cli
import re
import sys
from pathlib import Path

import yaml

SUPPORTED_FLOOR = (2, 336, 0)

# ⛔ ONE FLOOR, TWO UNRELATED VERSION SERIES — and the floor belonged to only one of them.
# `SUPPORTED_FLOOR` is a GitHub Actions RUNNER BINARY version, which is what myoung34's tag
# encodes. The other image in this fleet numbers its own IMAGE RELEASES and does not put
# the binary version in the reference at all:
#
#   myoung34/github-runner:2.336.0-ubuntu-jammy@sha256:8eeec3e8…   runner binary  2.336.0
#   ghcr.io/akash-network/github-runner:0.0.3@sha256:7509763a…     image release  0.0.3
#                                                                  binary inside  2.336.0
#                                                                  (nowhere in the tag)
#
# ⚠ THAT BINARY VERSION WAS WRONG HERE UNTIL 2026-09-04, AND THE ERROR FLATTERED THE RULE.
# This block said 2.334.0 "measured with crane". 2.334.0 belonged to the digest this one
# REPLACED — sha256:030ae11a, the deprecated runner GitHub refuses to dispatch to — and was
# carried forward onto its successor. Re-measured from the registry, no crane needed:
#
#   TOK=$(curl -s "https://ghcr.io/token?scope=repository:akash-network/github-runner:pull\
#         &service=ghcr.io" | jq -r .token)
#   # resolve sha256:7509763a… -> its linux/amd64 manifest -> that manifest's config blob
#   curl -sL -H "Authorization: Bearer $TOK" \
#        "https://ghcr.io/v2/akash-network/github-runner/blobs/<config digest>" \
#     | jq -r '.history[].created_by' | grep -o 'GH_RUNNER_VERSION=[0-9.]*'
#   # -> GH_RUNNER_VERSION=2.336.0   (labels.revision 9eb893eb4bfe9950808a601bd780decad8fe60b6)
#
# ⛔ AND IT MAKES THE ARGUMENT BELOW STRONGER, NOT WEAKER. At 2.334.0 the image was one
# release BEHIND the floor, so "below supported floor" was at least directionally right by
# accident. At 2.336.0 it is EXACTLY AT the floor — so the finding a correct tag would
# produce is not merely mis-derived, it is the opposite of the truth.
#
# Comparing `0.0.3` to `2.336.0` is comparing an image release to a binary version. The
# consequence is worse than a wrong number: today the akash-network image is referenced
# TAGLESS, which this rule reports honestly as "a digest but no verifiable version tag" —
# a TRUE finding. Add the correct tag and it becomes "below supported floor 2.336.0
# (version 0.0.3)", a FALSE one, permanently, on every run. A consumer acting on it would
# hunt for a `2.336.0` tag of an image whose tags are `0.0.x`.
#
# ⚠ THIS IS THE THIRD TIME THIS RULE HAS BEEN KEYED TO ONE REPO'S TAG SHAPE. The first two
# are recorded above: a required literal `:` before the digest, and the same "a tag is
# always present" assumption encoded in three places, each of which made the rule report
# NOT APPLICABLE on the very repo whose deprecated digest motivated it. The fix each time
# was to stop assuming every publisher numbers things the same way.
#
# ⇒ A floor is meaningful only against the series it came from. An image whose reference
# cannot express currency gets NO floor and keeps the honest "not verifiable" verdict —
# which is what the tagless case already returns, so a consumer that adds the correct tag
# is not punished for it.
_FLOORS: dict[str, tuple[int, int, int]] = {
    "myoung34/github-runner": SUPPORTED_FLOOR,
}


def _repo_name(image: str) -> str:
    """The repository part of an image reference, without registry port or tag confusion.

    ⛔ A COLON IS NOT ALWAYS A TAG. `localhost:5000/myoung34/github-runner:2.336.0` has two,
    and splitting on the FIRST one yields `localhost` — which matches no floor, so a
    correctly-pinned image behind a registry port would silently lose its floor. A tag
    separator is only the colon that comes AFTER the last `/`. Raised by Copilot on #66.
    """
    ref = image.split("@", 1)[0]
    slash = ref.rfind("/")
    colon = ref.rfind(":")
    return ref[:colon] if colon > slash else ref


def _floor_for(image: str) -> tuple[int, int, int] | None:
    """The floor for this image's version series, or None if it has no comparable one.

    ⛔ MATCHED ON A PATH BOUNDARY, NOT A SUFFIX. `name.endswith(repo)` also matches
    `notmyoung34/github-runner`, applying one publisher's floor to a different publisher —
    which reintroduces exactly the false below-floor finding this change exists to remove,
    for anyone whose name merely ends in a configured one. Raised by Copilot and CodeRabbit
    on #66, independently.
    """
    name = _repo_name(image)
    for repo, floor in _FLOORS.items():
        if name == repo or name.endswith("/" + repo):
            return floor
    return None
# Two reference forms exist in this fleet and BOTH must match:
#   name:TAG@DIGEST   myoung34/github-runner:2.336.0-ubuntu-jammy@sha256:8eeec3e8...   (Blazing-Back)
#   name@DIGEST       ghcr.io/akash-network/github-runner@sha256:7509763a...           (just-akash)
# ⛔ The first version of this regex required a literal ":" before the digest, so the
# TAGLESS form never matched and the rule reported NOT APPLICABLE on the very repo whose
# deprecated digest motivated it -- on both the defective AND the fixed state. The tag
# group is therefore OPTIONAL, and a digest with no tag is its own case: pinned, but the
# version is not readable from the reference, so currency cannot be checked here.
_RUNNER_RE = re.compile(
    r"(?:^|/)github-runner"
    r"(?::(?P<tag>[^@\s]+))?"
    r"(?:@(?P<digest>sha256:[0-9a-fA-F]{64}))?"
    r"(?=$|\s)"
)
# ⛔ THE SAME "a tag is always present" ASSUMPTION WAS ENCODED IN THREE PLACES:
# this extractor, the dict-path string test below, and _RUNNER_RE. Fixing one left
# the other two blind, so the rule reported NOT APPLICABLE on just-akash -- whose
# reference is ghcr.io/akash-network/github-runner@sha256:... with NO tag -- on both
# its defective and its fixed state. All three now accept name@digest.
# ⛔ #18: the prefix group is OPTIONAL and there was NO LEFT ANCHOR, so `github-runner`
# matched INSIDE `akash-github-runner` -- this rule's own repo name. Every consumer that
# referenced the canonical repo by path got 2 advisory findings on its own conformance
# workflow, on every run. Widening the three sites in #16 to accept name@digest fixed a
# false NEGATIVE and created this false POSITIVE: a matcher has two error rates and only
# one was measured.
# The fix is BOTH SIDES, and symmetric -- a negative lookahead for identifier characters
# rather than a list of permitted terminators, because enumerating terminators is what
# makes a boundary miss `github-runner` at the end of an interior line.
# ⚠ The tag and digest groups MUST stay INSIDE the match. Replacing them with a
# lookahead also kills the substring, but strips the digest from every extracted
# reference -- and _RUNNER_RE then reports the canonical refs as FLOATING. Measured.
_IMAGE_REF = re.compile(
    r"(?<![A-Za-z0-9_\-])"
    r"(?:[A-Za-z0-9_.\-]+(?:/[A-Za-z0-9_.\-]+)*/)?"
    r"github-runner"
    r"(?::[^\s\"'<>`@]+)?"
    r"(?:@sha256:[0-9a-fA-F]{64})?"
    r"(?![A-Za-z0-9_\-])"
)
_VERSION_RE = re.compile(r"^(?P<version>\d+\.\d+\.\d+)(?:-|$)")


def _runner_images(value: object) -> list[str]:
    """Return runner image scalars from an arbitrarily nested YAML document."""
    if isinstance(value, str):
        return [ref.rstrip(",;)") for ref in _IMAGE_REF.findall(value)]
    if isinstance(value, dict):
        images: list[str] = []
        for key, child in value.items():
            # ⛔ #18: this was a bare `"github-runner" in child` substring test -- the SAME
            # defect as _IMAGE_REF, in the second of the three sites. Use the one
            # predicate so all sites agree on what a runner reference IS.
            if key == "image" and isinstance(child, str) and _IMAGE_REF.search(child):
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
    return _runner_images(
        "\n".join(
            line for line in text.splitlines() if not line.lstrip().startswith("#")
        )
    )


def _version(tag: str) -> tuple[int, int, int] | None:
    match = _VERSION_RE.match(tag)
    return (
        tuple(int(part) for part in match.group("version").split("."))
        if match
        else None
    )


def findings(document: dict | str) -> list[str]:
    """Return floating, below-floor, or unverifiable runner-image findings."""
    out: list[str] = []
    for image in _runner_images(document):
        match = _RUNNER_RE.search(image)
        if not match:
            out.append(f"runner image {image!r} is not a valid digest-pinned reference")
            continue
        # A tagless name@digest reference has no tag group at all, so the version is
        # not readable from the reference. That is NOT a pass: it falls through to the
        # "digest but no verifiable version tag" finding below, because claiming PASS
        # would assert a currency check this rule did not perform.
        tag = match.group("tag")
        version = _version(tag) if tag else None
        if not match.group("digest"):
            out.append(
                f"runner image {image!r} is floating; pin it with @sha256:<digest>"
            )
            continue
        floor_for_image = _floor_for(image)
        if version is None or floor_for_image is None:
            # Two different reasons, one honest verdict: either the reference carries no
            # version, or it carries one from a series this rule has no floor for. Both
            # mean currency was NOT checked, and saying so is the point — claiming PASS
            # would assert a check that did not happen.
            out.append(
                f"runner image {image!r} has a digest but no verifiable version tag"
            )
            continue
        if version < floor_for_image:
            floor = ".".join(map(str, floor_for_image))
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
    return findings(
        "\n".join(
            line for line in text.splitlines() if not line.lstrip().startswith("#")
        )
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workflows-dir", default=".github/workflows")
    _cli.add_dir_positional(ap)
    args = ap.parse_args(argv)
    _cli.resolve_dir_positional(ap, args)
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
    # ⛔ FINDINGS ARE CHECKED BEFORE NOT-APPLICABLE, AND THE ORDER IS THE POINT.
    # A directory with an unparseable workflow and no runner image produced findings,
    # printed them as ::error, and then returned 0 through the not-applicable branch --
    # so the advisory check reported PASS while having emitted errors. NOT APPLICABLE
    # means "the axis does not apply here", which cannot be true once something has
    # already gone wrong on that axis.
    if bad:
        return 1
    if runner_files == 0:
        print("Runner images: NOT APPLICABLE — no runner image references found")
        return 0
    print(f"Runner images: PASS — {runner_files} workflow(s) checked")
    return 0


if __name__ == "__main__":
    sys.exit(main())
