"""Adversarial tests for runner image identity and currency."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml

RULE = Path(__file__).with_name("check_runner_image_digest_floor.py")
spec = importlib.util.spec_from_file_location("runner_image_rule", RULE)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

# Exact image reference copied from Blazing-Back akash-runner.yml:852 and
# runner-time-to-ready.yml:150 at the issue's measured good state. Defective
# fixtures below are transformations of this artifact, never hand-written lookalikes.
GOOD_IMAGE = (
    "myoung34/github-runner:2.336.0-ubuntu-jammy@"
    "sha256:8eeec3e8a4e21c229057cc4b4ba46a22d5ff24217ca6f0d984cf9be168be6520"
)
GOOD_WORKFLOW = yaml.safe_load(
    f"""
jobs:
  provision:
    steps:
      - name: runner
        with:
          image: {GOOD_IMAGE}
"""
)


def _image_workflow(image: str) -> dict:
    workflow = yaml.safe_load(yaml.safe_dump(GOOD_WORKFLOW))
    workflow["jobs"]["provision"]["steps"][0]["with"]["image"] = image
    return workflow


def test_artifact_derived_good_reference_passes() -> None:
    assert mod.findings(GOOD_WORKFLOW) == []


def test_artifact_derived_tag_without_digest_is_flagged() -> None:
    floating = GOOD_IMAGE.split("@", 1)[0]
    result = mod.findings(_image_workflow(floating))
    assert len(result) == 1 and "floating" in result[0]


def test_artifact_derived_below_floor_version_is_distinctly_flagged() -> None:
    stale = GOOD_IMAGE.replace("2.336.0", "2.334.0")
    result = mod.findings(_image_workflow(stale))
    assert len(result) == 1 and "below supported floor" in result[0]


def test_no_runner_workflow_is_explicitly_not_applicable(
    tmp_path: Path, capsys
) -> None:
    (tmp_path / "plain.yml").write_text("jobs:\n  check:\n    runs-on: ubuntu-latest\n")
    assert mod.main(["--workflows-dir", str(tmp_path)]) == 0
    assert "NOT APPLICABLE" in capsys.readouterr().out


def test_real_good_artifact_is_used_for_both_measured_call_sites() -> None:
    workflow = yaml.safe_load(
        f"""
jobs:
  akash-runner:
    steps: [{{image: {GOOD_IMAGE}}}]
  runner-time-to-ready:
    steps: [{{image: {GOOD_IMAGE}}}]
"""
    )
    assert mod.findings(workflow) == []


def test_a_finding_beats_not_applicable(tmp_path) -> None:
    """A parse error must FAIL even when no runner image is present.

    The not-applicable branch used to return 0 before findings were checked, so a
    directory holding an unparseable workflow AND no runner image printed its
    ::error annotations and then reported NOT APPLICABLE — which the conformance
    action renders as PASS. NOT APPLICABLE asserts "this axis does not apply
    here"; that cannot be true once something has already gone wrong on the axis.
    """
    d = tmp_path / "workflows"
    d.mkdir()
    # invalid YAML, and deliberately NO runner image reference anywhere
    # genuinely unparseable: an unclosed flow sequence raises yaml.YAMLError.
    # ⚠ a DUPLICATE KEY does NOT — safe_load silently keeps the last — so a
    # duplicate-key fixture would leave this test passing vacuously.
    (d / "broken.yml").write_text("jobs:\n  a: [1, 2\n", encoding="utf-8")
    rc = mod.main(["--workflows-dir", str(d)])
    assert rc in (1, 2), f"a directory with findings must not return 0, got {rc}"


# ⛔ SECOND REAL ARTEFACT. The first version of this rule drew every fixture from
# Blazing-Back's reference, which carries a TAG, so the regex required one — and the
# rule reported NOT APPLICABLE on just-akash, the repo whose deprecated digest caused
# the incident, on BOTH its defective and its fixed state. Fixtures from one artefact
# cannot reveal a form that only exists in another.
JA_STALE = (
    "ghcr.io/akash-network/github-runner@"
    "sha256:030ae11a6b597c5db28b12375461e35f694d74ceb06a1b73c90545b1adef16da"
)
JA_CURRENT = (
    "ghcr.io/akash-network/github-runner@"
    "sha256:7509763af8209796f3e7fde5fb536c742075ec1a59ad1b36e3c9c27bc3bafc67"
)


def test_the_tagless_digest_form_is_seen_at_all(tmp_path: Path) -> None:
    """A name@digest reference with no tag must not read as 'no runner image'.

    This is the retrospective check: run the rule over the shape just-akash actually
    had when its runners were registering and being refused, and confirm the rule
    says something rather than NOT APPLICABLE.
    """
    d = tmp_path / "workflows"
    d.mkdir()
    (d / "runner-pool.yml").write_text(
        f"jobs:\n  pool:\n    steps:\n      - run: |\n          image: {JA_STALE}\n",
        encoding="utf-8",
    )
    rc = mod.main(["--workflows-dir", str(d)])
    assert rc == 1, (
        "the tagless digest form must be examined, not reported NOT APPLICABLE"
    )


def test_a_digest_without_a_tag_cannot_have_its_currency_checked() -> None:
    """Pinned, but the version is unreadable from the reference — say so, do not PASS.

    Claiming PASS would assert a currency check the rule did not perform. That is the
    failure mode this whole rule exists to catch, one level up.
    """
    for ref in (JA_STALE, JA_CURRENT):
        out = mod.findings(f"image: {ref}")
        assert out, f"{ref} produced no finding"
        assert "no verifiable version tag" in out[0], out[0]


# ---------------------------------------------------------------------------
# #18 — the rule's own repo name contains its own image name.
#
# `github-runner` is a substring of `akash-github-runner`. #16 made the ":" after
# `github-runner` optional in _IMAGE_REF, and that group's prefix is optional with no
# left anchor — so the substring became extractable and every consumer referencing the
# canonical repo BY PATH got advisory findings on its own conformance workflow.
#
# ⚠ These fixtures are drawn from THE RULE'S OWN REPO PATH, not from a consumer's.
# Every fixture in #15 and #16 came from a consumer artifact, and no consumer referenced
# the canonical repo's path until adoption — so the fixture population COULD NOT EXHIBIT
# the defect. A rule meant to be adopted needs a fixture of the shape adoption creates.
# ---------------------------------------------------------------------------

CANONICAL_USES = (
    "Digital-Frontier-LDA/akash-github-runner/.github/workflows/"
    "reusable-akash-runner-conformance.yml@297ec"
)


def test_the_rules_own_repo_path_is_not_a_runner_image() -> None:
    """The substring in `akash-github-runner` must not be extracted as an image."""
    assert mod._runner_images(CANONICAL_USES) == []
    assert (
        mod.findings(yaml.safe_load(f"jobs:\n  c:\n    uses: {CANONICAL_USES}\n")) == []
    )


def test_the_substring_is_rejected_even_under_an_image_key() -> None:
    """The dict-path site used a bare `in` test and had the same defect."""
    assert mod._runner_images({"image": CANONICAL_USES}) == []


def test_a_real_reference_beside_the_substring_is_still_found() -> None:
    """⭐ Discrimination, not suppression — a rule that rejected BOTH would also pass
    the two tests above and be useless."""
    found = mod._runner_images(f"{CANONICAL_USES}\n          image: {GOOD_IMAGE}")
    assert found == [GOOD_IMAGE]


def test_the_extracted_reference_still_carries_its_digest() -> None:
    """⛔ THE AXIS A MATCH/NO-MATCH TABLE CANNOT SEE.

    A boundary built as a *lookahead* (`(?=[@:/\\s\"']|$)`) instead of a trailing
    negative lookbehind also kills the substring — and strips the tag and digest from
    every extracted reference, because they fall outside the match. `_RUNNER_RE` then
    sees a bare name and reports the CANONICAL references as floating. Measured: the
    lookahead form extracts 'myoung34/github-runner' from the artifact above.

    Asserting "does it match" would pass for both designs. Assert the payload.
    """
    assert mod._runner_images(GOOD_IMAGE) == [GOOD_IMAGE]
    assert mod._runner_images(
        f"ghcr.io/akash-network/github-runner@sha256:{'7' * 64}"
    ) == [f"ghcr.io/akash-network/github-runner@sha256:{'7' * 64}"]


def test_a_bare_reference_at_the_end_of_an_interior_line_is_still_seen() -> None:
    """The mirror defect: a terminator LIST plus `$` misses this without re.M."""
    assert mod._runner_images("image: github-runner\nnext: 1") == ["github-runner"]


def test_a_longer_image_name_ending_in_the_runner_name_is_not_a_match() -> None:
    assert mod._runner_images("github-runner-extra:1.0") == []


# ── two publishers, two version series, one floor that belonged to one of them ──

_DIGEST = "@sha256:" + "a" * 64
_AKASH = "ghcr.io/akash-network/github-runner"
_MYOUNG34 = "myoung34/github-runner"


def test_the_floor_still_applies_to_the_series_it_came_from() -> None:
    """Anti-vacuity for everything below: making the floor per-repository must not have
    made it per-nobody. 2.336.0 is a GitHub Actions runner BINARY version and myoung34's
    tag encodes exactly that."""
    assert mod.findings(f"{_MYOUNG34}:2.336.0-ubuntu-jammy{_DIGEST}") == []
    below = mod.findings(f"{_MYOUNG34}:2.300.0-ubuntu-jammy{_DIGEST}")
    assert below and "below supported floor" in below[0]


def test_a_correct_tag_on_the_other_publisher_is_not_a_false_below_floor() -> None:
    """⛔ THE DEFECT. `ghcr.io/akash-network/github-runner` numbers its own IMAGE RELEASES
    — `0.0.3`, `0.0.3-20260810` — and does not put the runner binary version in the
    reference at all (it is 2.334.0, measured with crane). Comparing `0.0.3` to `2.336.0`
    compares an image release to a binary version.

    The consequence was worse than a wrong number. Tagless, the rule says "a digest but no
    verifiable version tag" — TRUE. Add the correct tag and it said "below supported floor
    2.336.0 (version 0.0.3)" — FALSE, permanently, on every run, sending a consumer to hunt
    for a `2.336.0` tag of an image whose tags are `0.0.x`. Recording the release a pin
    refers to is good practice and the rule punished it.
    """
    result = mod.findings(f"{_AKASH}:0.0.3{_DIGEST}")
    assert result, "a reference whose currency cannot be checked must not read as a pass"
    assert "below supported floor" not in result[0], result[0]
    assert "no verifiable version tag" in result[0], result[0]


def test_the_tagless_reference_is_unchanged() -> None:
    """The honest verdict for that image was already correct and must stay identical, so
    adding the tag neither improves nor worsens the finding — which is the point: the tag
    documents the release for a human without the rule pretending to have checked it."""
    tagless = mod.findings(f"{_AKASH}{_DIGEST}")
    tagged = mod.findings(f"{_AKASH}:0.0.3{_DIGEST}")
    assert tagless and tagged
    assert "no verifiable version tag" in tagless[0]
    assert tagless[0].replace(_AKASH + _DIGEST, "") == tagged[0].replace(
        _AKASH + ":0.0.3" + _DIGEST, ""
    )


def test_an_unfloored_publisher_is_still_held_to_the_digest_rule() -> None:
    """Having no floor is not having no rules. `:latest` is still floating, and floating is
    the incident this whole rule exists for — provider caches served different layers for
    the same tag."""
    floating = mod.findings(f"{_AKASH}:latest")
    assert floating and "floating" in floating[0]


def test_a_similarly_named_publisher_does_not_inherit_the_floor() -> None:
    """⛔ `notmyoung34/github-runner` is a different publisher.

    A suffix match applies one publisher's binary-version floor to another's numbering —
    reintroducing, for them, the precise false "below supported floor" this change exists
    to remove. Raised independently by Copilot and CodeRabbit on #66.
    """
    result = mod.findings(f"notmyoung34/github-runner:2.300.0{_DIGEST}")
    assert result
    assert "below supported floor" not in result[0], result[0]
    assert "no verifiable version tag" in result[0], result[0]


def test_a_registry_port_does_not_strip_the_floor() -> None:
    """A colon is not always a tag separator: `localhost:5000/myoung34/github-runner` has
    two, and splitting on the first yields `localhost`. The image is correctly pinned and
    correctly named, and would have silently lost its floor."""
    assert mod.findings(f"localhost:5000/{_MYOUNG34}:2.336.0-ubuntu-jammy{_DIGEST}") == []
    below = mod.findings(f"localhost:5000/{_MYOUNG34}:2.300.0-ubuntu-jammy{_DIGEST}")
    assert below and "below supported floor" in below[0], below
