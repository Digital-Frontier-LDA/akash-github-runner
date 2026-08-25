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


def test_no_runner_workflow_is_explicitly_not_applicable(tmp_path: Path, capsys) -> None:
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
    assert rc == 1, "the tagless digest form must be examined, not reported NOT APPLICABLE"


def test_a_digest_without_a_tag_cannot_have_its_currency_checked() -> None:
    """Pinned, but the version is unreadable from the reference — say so, do not PASS.

    Claiming PASS would assert a currency check the rule did not perform. That is the
    failure mode this whole rule exists to catch, one level up.
    """
    for ref in (JA_STALE, JA_CURRENT):
        out = mod.findings(f"image: {ref}")
        assert out, f"{ref} produced no finding"
        assert "no verifiable version tag" in out[0], out[0]
