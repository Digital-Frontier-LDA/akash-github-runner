"""No runner digest built before the eMudhra/emSign distrust is admissible (df-cicd-rpi.1).

Judged by the checker's EXIT CODE over a real workflows directory, the way CI runs it, not by
inspecting a helper's return value. The rule is "no pre-fix digest", so a later fixed rebuild
(any digest not on the measured list) must still pass.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("pre_emudhra", HERE / "check_no_pre_emudhra_runner_digest.py")
mod = importlib.util.module_from_spec(_spec)
import sys

sys.path.insert(0, str(HERE))
_spec.loader.exec_module(mod)

FIXED = "sha256:e71bf4be0e3a59a57ff791b0fc3bc3a31f216f66807b6ac41f1a23346321baa4"
FIXED_CHILDREN = {
    "sha256:b98c339bf465919e6972e5db9891151cb987c08643b746d8ed86f15c6c24f215",  # amd64
    "sha256:7fbf29097fbf1995322d5fe89d3aa937c2d0bf2ad4301c7dbfddacd4716b7869",  # arm64
}
# The eight pre-fix digests consumers actually pinned (df-cicd controller, just-akash, blazing,
# Blazing-Back, Flynn's negative control). All must be on the measured list.
NAMED_PRE_FIX = (
    "sha256:7c9cd8cb4c515f0b047160b2dc4c4939fb1a19e4ce1199531930c7df83bbfa74",
    "sha256:ba181fa1ee0793829a2bf46cdc4d4ce05902c736c033e7aeb6b431c7ade659f0",
    "sha256:a88afbda5e9a6fc333898766c7831a25931433eb92af6ee95ddb0fa2ab2edb6b",
    "sha256:3c99f89b9b88440d40e418a2d5d74a8e8cad902e8d545504aaed23c8e9fd7a43",
    "sha256:aaf3799b5e138abef0831bb8467ded7325164316f0cfde5c183fe6e129eae79e",
    "sha256:ce1b123c98e273479e08e6315fc81f7017957c23dbf88878076e75572b7b18cc",
    "sha256:bdf7b15256a41156d1227510e4e4d8c9e28d79d685e14907132fe439b85bef64",
)


def _rc(tmp_path: Path, image: str) -> int:
    wf = tmp_path / "wf"
    wf.mkdir()
    (wf / "runner.yml").write_text(
        "jobs:\n  pool:\n    runs-on: ubuntu-latest\n    steps:\n"
        f"      - run: |\n          cat > sdl.yaml <<EOF\n          services:\n            runner:\n              image: {image}\n          EOF\n"
    )
    try:
        return mod.main(["--workflows-dir", str(wf)])
    except SystemExit as exc:  # argparse-style exits
        return int(exc.code or 0)


def test_the_measured_list_is_complete_and_excludes_the_fix():
    assert len(mod.PRE_EMUDHRA_DIGESTS) == 50
    assert FIXED not in mod.PRE_EMUDHRA_DIGESTS
    assert not (FIXED_CHILDREN & mod.PRE_EMUDHRA_DIGESTS), "the fixed index's own children are not pre-fix"


@pytest.mark.parametrize("digest", NAMED_PRE_FIX)
def test_each_named_pre_fix_digest_is_on_the_list(digest):
    assert digest in mod.PRE_EMUDHRA_DIGESTS, digest


@pytest.mark.parametrize("digest", NAMED_PRE_FIX[:6])
@pytest.mark.parametrize(
    "name",
    [
        "ghcr.io/digital-frontier-lda/df-akash-runner:2.337.0@",
        "docker.io/digitalfrontierunipessoallda/akash-runner@",  # a mirror copies the bytes
    ],
)
def test_a_pre_fix_digest_fails_the_checker_by_exit_code(tmp_path, name, digest):
    assert _rc(tmp_path, name + digest) != 0


def test_the_fixed_digest_passes(tmp_path):
    assert _rc(tmp_path, "ghcr.io/digital-frontier-lda/df-akash-runner:2.337.0@" + FIXED) == 0


def test_a_later_fixed_rebuild_is_not_rejected(tmp_path):
    """The rule is 'no pre-fix digest', not 'must equal e71bf4be'."""
    later = "sha256:" + "1" * 64
    assert _rc(tmp_path, "ghcr.io/digital-frontier-lda/df-akash-runner:2.337.0@" + later) == 0


def test_a_commented_reference_is_history_not_a_pin(tmp_path):
    wf = tmp_path / "wf"
    wf.mkdir()
    (wf / "w.yml").write_text("# was ghcr.io/digital-frontier-lda/df-akash-runner@" + NAMED_PRE_FIX[0] + "\njobs: {}\n")
    assert mod.main(["--workflows-dir", str(wf)]) == 0


def test_it_is_wired_into_the_conformance_action():
    """Advisory until every consumer is repinned; the PROMOTE WHEN lives in
    test_every_rule_has_a_call_site.ADVISORY. Promotion flips this assertion."""
    action = (HERE.parent / ".github/actions/akash-runner-conformance/action.yml").read_text()
    assert 'advisory check_no_pre_emudhra_runner_digest.py --workflows-dir "$WORKFLOWS_DIR"' in action
