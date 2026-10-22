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


# ---- the non-test code scan (scripts hold hard-coded images too) ----------------------------

GHCR = "ghcr.io/digital-frontier-lda/df-akash-runner@"


def _repo(tmp_path: Path, files: dict[str, str]) -> int:
    root = tmp_path / "repo"
    (root / ".github" / "workflows").mkdir(parents=True)
    (root / ".github" / "workflows" / "ci.yml").write_text("jobs: {}\n")
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return mod.main(["--workflows-dir", str(root / ".github" / "workflows")])


@pytest.mark.parametrize("digest", NAMED_PRE_FIX[:6])
@pytest.mark.parametrize(
    "where",
    [
        ".github/actions/owned-akash-controller/runtime/scripts/owned_akash_canary.py",  # df-cicd
        "scripts/owned_akash_canary.py",  # guardian
        "tools/owned_cpu_prerequisites.py",  # DePIN
    ],
)
def test_a_pre_fix_digest_in_a_script_is_red(tmp_path, where, digest):
    assert _repo(tmp_path, {where: f'IMAGE = "{GHCR}{digest}"\n'}) != 0


def test_flynns_negative_control_is_allowed_but_only_that_constant(tmp_path):
    verifier = ".github/scripts/verify_owned_worker_image.py"
    control = f'OLD_IMAGE = "{GHCR}{NAMED_PRE_FIX[1]}"\n'
    assert _repo(tmp_path, {verifier: f'IMAGE = "{GHCR}{FIXED}"\n' + control}) == 0
    # The allowlist must not cover the live IMAGE in the same file.
    assert _repo(tmp_path / "b", {verifier: f'IMAGE = "{GHCR}{NAMED_PRE_FIX[0]}"\n' + control}) != 0


def test_test_code_prose_comments_and_the_attested_proof_are_not_pins(tmp_path):
    old = NAMED_PRE_FIX[0]
    assert _repo(
        tmp_path,
        {
            "tests/test_pins.py": f'BANNED = ("{old}",)\n',
            "pkg/test_image.py": f'X = "{old}"\n',
            "tests/fixtures/sdl.yaml": f"image: {GHCR}{old}\n",
            "docs/history.md": f"was {GHCR}{old}\n",
            "tools/tool.py": f"# previously {GHCR}{old}\nIMAGE = \"{GHCR}{FIXED}\"\n",
            "proofs/owned-history-approved-source.json": f'{{"akash-runner": {{"qualified": "{old}"}}}}\n',
        },
    ) == 0


# ---- blazing's migration snapshots: allowed line by line, and nothing else -------------------
# Verbatim from Borduas-Holdings/blazing d18a178d (and the #1656 head e068ed0e), copied by hand
# rather than built from ALLOWLIST, so a loosened pattern cannot agree with itself.
CE1_ROOT = 'ROOT = "sha256:ce1b123c98e273479e08e6315fc81f7017957c23dbf88878076e75572b7b18cc"  # public image digest\n'
SEVEN_TAG = (
    'AAF = "sha256:aaf3799b5e138abef0831bb8467ded7325164316f0cfde5c183fe6e129eae79e"\n'
    "CANDIDATES = {\n"
    '    "candidate-3259dfc6c6221db9ade4d6e1dca423a32a785008": "sha256:a88afbda5e9a6fc333898766c7831a25931433eb92af6ee95ddb0fa2ab2edb6b",\n'
    '    "candidate-40706a10807d39e7d31065a360b3b3ce95668464": "sha256:3c99f89b9b88440d40e418a2d5d74a8e8cad902e8d545504aaed23c8e9fd7a43",\n'
    '    "candidate-6f5c30c4220c54ec4a9f0f2cfef472f8bb39ce9c": "sha256:588f5fa1e514343832393c1ca31b990d8586c5f7ab69035adc2ecb376502f10a",\n'
    '    "candidate-cce642e0c1dbe1be8cbd869de2e4a1539338f291": "sha256:5b43d797d92bb081d2e085046b48579ebf0448a48fcc32f562eafa0c811b4a32",\n'
    "}\n"
)


def test_blazings_migration_snapshots_are_history(tmp_path):
    assert _repo(
        tmp_path,
        {"scripts/ce1_runner_private_mirror.py": CE1_ROOT, "scripts/ghcr_runner_tag_migration.py": SEVEN_TAG},
    ) == 0


def test_a_new_pin_in_a_snapshot_file_is_still_red(tmp_path):
    extra = f'IMAGE = "{GHCR}{NAMED_PRE_FIX[0]}"\n'
    assert _repo(tmp_path, {"scripts/ce1_runner_private_mirror.py": CE1_ROOT + extra}) != 0
    assert _repo(tmp_path / "b", {"scripts/ghcr_runner_tag_migration.py": SEVEN_TAG + extra}) != 0


def test_a_snapshot_constant_moved_to_another_pre_fix_digest_is_red(tmp_path):
    moved = CE1_ROOT.replace("ce1b123c98e273479e08e6315fc81f7017957c23dbf88878076e75572b7b18cc", NAMED_PRE_FIX[0].split(":", 1)[1])
    assert moved != CE1_ROOT
    assert _repo(tmp_path, {"scripts/ce1_runner_private_mirror.py": moved}) != 0


def test_a_snapshot_line_in_another_file_is_red(tmp_path):
    assert _repo(tmp_path, {"scripts/other.py": CE1_ROOT}) != 0


def test_blazings_live_private_mirror_pin_is_red(tmp_path):
    """private_runner_mirror.DIGEST is the RUNTIME runner of owned-private-podman-images.yml:
    found by the 2026-10-22 promotion scan and deliberately NOT allowlisted."""
    live = 'DIGEST = "sha256:aaf3799b5e138abef0831bb8467ded7325164316f0cfde5c183fe6e129eae79e"\n'
    assert _repo(tmp_path, {"scripts/private_runner_mirror.py": live}) != 0


def test_the_code_scan_is_announced_when_it_cannot_run(tmp_path, capsys):
    wf = tmp_path / "loose"
    wf.mkdir()
    (wf / "w.yml").write_text("jobs: {}\n")
    assert mod.main(["--workflows-dir", str(wf)]) == 0
    assert "code scan SKIPPED" in capsys.readouterr().out


# ---- d3's review of a8def223: each surface must be able to fail ------------------------------


def test_a_yaml_suffixed_workflow_is_scanned(tmp_path):
    wf = tmp_path / "wf"
    wf.mkdir()
    (wf / "runner.yaml").write_text(f"image: {GHCR}{NAMED_PRE_FIX[0]}\n")
    assert mod.main(["--workflows-dir", str(wf)]) != 0


def test_json_outside_the_allowlist_is_scanned(tmp_path):
    assert _repo(tmp_path, {"deploy/sdl.json": f'{{"image": "{GHCR}{NAMED_PRE_FIX[0]}"}}\n'}) != 0


def test_matching_is_case_insensitive(tmp_path):
    upper = "sha256:" + NAMED_PRE_FIX[0].split(":", 1)[1].upper()
    assert _repo(tmp_path, {"tools/tool.py": f'IMAGE = "{GHCR}{upper}"\n'}) != 0


def test_a_shipped_test_named_shell_script_is_scanned(tmp_path):
    """The test_*/_test name rule is Python-only: a production test_*.sh is code."""
    assert _repo(tmp_path, {".github/scripts/test_runner_pool.sh": f"IMAGE={GHCR}{NAMED_PRE_FIX[0]}\n"}) != 0


def test_fixtures_outside_a_test_dir_are_scanned(tmp_path):
    """A role's shipped files/fixtures/ is code; only fixtures/ under tests/ is test data."""
    assert _repo(tmp_path, {"roles/runner/files/fixtures/sdl.yaml": f"image: {GHCR}{NAMED_PRE_FIX[0]}\n"}) != 0


def test_a_trailing_comment_is_history_not_a_pin(tmp_path):
    line = f"image: {GHCR}{FIXED}  # was {GHCR}{NAMED_PRE_FIX[0]}\n"
    wf = tmp_path / "wf"
    wf.mkdir()
    (wf / "w.yml").write_text(line)
    assert mod.main(["--workflows-dir", str(wf)]) == 0
    # ...but the same digest as the VALUE is still a pin.
    (wf / "w.yml").write_text(f"image: {GHCR}{NAMED_PRE_FIX[0]}  # was {GHCR}{FIXED}\n")
    assert mod.main(["--workflows-dir", str(wf)]) != 0


def test_a_negative_control_repointed_at_a_fixed_image_is_flagged(tmp_path, capsys):
    verifier = ".github/scripts/verify_owned_worker_image.py"
    rc = _repo(tmp_path, {verifier: f'IMAGE = "{GHCR}{FIXED}"\nOLD_IMAGE = "{GHCR}{FIXED}"\n'})
    assert rc != 0
    assert "negative control is not pre-fix" in capsys.readouterr().out
