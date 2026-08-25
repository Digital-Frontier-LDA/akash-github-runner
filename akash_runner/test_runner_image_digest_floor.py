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
