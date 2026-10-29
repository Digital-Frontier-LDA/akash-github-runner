"""A just-akash reusable workflow called at a pre-fix sha is a pre-fix runner (df-cicd-rpi.10).

check_no_pre_emudhra_runner_digest read only the consumer's own files, so a consumer calling
just-akash runner-pool.yml@<sha> ran the image named THERE and scanned 0. Measured 2026-10-29:
df-cicd main's template (runner-pool@ca353a9c) was 0 and is now 1; df-cicd#704 (@436f091b) is 0.
Blazing-Back main 9f9b233 is now 3, and blazing main d8abebc3 is 8.
"""
from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
_spec = importlib.util.spec_from_file_location("pre_emudhra_ind", HERE / "check_no_pre_emudhra_runner_digest.py")
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)
import generate_just_akash_pre_emudhra_refs as gen  # noqa: E402

POOL = ".github/workflows/runner-pool.yml"
TEARDOWN = ".github/workflows/runner-teardown.yml"
# Measured in just-akash: each of these runner-pool.yml files runs df-akash-runner@aaf3799b.
PRE_FIX_SHAS = {
    "ca353a9c448c068a7d9a15c01ae89d27d396bf36": "df-cicd templates/akash-runner-ci.yml until #704",
    "2393294697c091344ae74a7191e0834a520a845a": "Blazing-Back (3 call sites) and blazing (4) main",
    "a85f7147c9e6d36807cff54d4823d9146b7e43d2": "blazing main (4 call sites)",
}
# just-akash#480 (d1158432) and main 436f091b: pool and probe run the fixed e71bf4be.
FIXED_SHAS = ("d115843249a7ad4fb52cd075379815e1e7cec669", "436f091b048b4522e4c12cfa23b0b38838eb5f15")
PRE_FIX = "sha256:aaf3799b5e138abef0831bb8467ded7325164316f0cfde5c183fe6e129eae79e"


def _template(sha: str, teardown_sha: str | None = None) -> str:
    """The shape of df-cicd templates/akash-runner-ci.yml: a pool and a teardown at one sha."""
    t = teardown_sha or sha
    return (
        "on: pull_request\njobs:\n"
        f"  pool:\n    uses: Digital-Frontier-LDA/just-akash/{POOL}@{sha} # runner image\n"
        f"    with:\n      just-akash-ref: {sha}\n"
        f"  teardown:\n    uses: Digital-Frontier-LDA/just-akash/{TEARDOWN}@{t}\n"
    )


def _scan(tmp_path: Path, files: dict[str, str], capsys) -> tuple[int, str]:
    root = tmp_path / "repo"
    (root / ".github" / "workflows").mkdir(parents=True)
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    rc = mod.main(["--workflows-dir", str(root / ".github" / "workflows")])
    return rc, capsys.readouterr().out


# ---- the measured list -------------------------------------------------------------------


def test_the_measured_list_names_every_consumer_pinned_pre_fix_sha_and_no_fixed_one():
    refs = mod.JUST_AKASH_PRE_EMUDHRA_REFS
    for sha, where in PRE_FIX_SHAS.items():
        assert (sha, POOL) in refs, where
    assert not {s for s, _p in refs} & {s for s in FIXED_SHAS}
    # runner-teardown.yml runs on a hosted runner and names no runner image at any sha.
    assert not any(p == TEARDOWN for _s, p in refs)


def test_the_list_is_generated_shape_sorted_unique_and_names_no_full_digest():
    text = mod.JUST_AKASH_REFS_DATA.read_text(encoding="utf-8")
    rows = [line for line in text.splitlines() if line and not line.startswith("#")]
    assert len(rows) >= 584, "the 2026-10-29 measurement (a --mirror clone) listed 584; the list only grows"
    assert rows == sorted(set(rows))
    for row in rows:
        assert re.fullmatch(r"[0-9a-f]{40}  \.github/workflows/[\w.-]+\.ya?ml  [0-9a-f]{12}", row), row
    # A full digest here would make the repo-wide scan read this data as a pin.
    assert not re.search(r"sha256:[0-9a-f]{64}", text)


# ---- the rule, by exit code ---------------------------------------------------------------


def test_df_cicd_main_template_shape_is_one_finding_for_the_pool_only(tmp_path, capsys):
    rc, out = _scan(tmp_path, {"templates/akash-runner-ci.yml": _template(next(iter(PRE_FIX_SHAS)))}, capsys)
    assert rc == 1
    assert "1 reference(s) to a pre-fix image" in out
    assert f"{POOL}@ca353a9c" in out and TEARDOWN not in out


@pytest.mark.parametrize("sha", FIXED_SHAS)
def test_the_repinned_template_passes(tmp_path, capsys, sha):
    rc, out = _scan(tmp_path, {"templates/akash-runner-ci.yml": _template(sha)}, capsys)
    assert rc == 0, out


@pytest.mark.parametrize("sha", sorted(PRE_FIX_SHAS))
def test_a_workflow_calling_a_pre_fix_pool_is_red(tmp_path, capsys, sha):
    rc, out = _scan(tmp_path, {".github/workflows/ci.yml": _template(sha, FIXED_SHAS[1])}, capsys)
    assert rc == 1, PRE_FIX_SHAS[sha]


@pytest.mark.parametrize(
    "line",
    [
        "    uses: 'Digital-Frontier-LDA/just-akash/{p}@{s}'",
        '    uses: "digital-frontier-lda/just-akash/{p}@{s}"',
        "      - uses: Digital-Frontier-LDA/just-akash/{p}@{s}",
    ],
)
def test_quoted_and_lowercase_spellings_are_read(tmp_path, capsys, line):
    text = "jobs:\n  pool:\n" + line.format(p=POOL, s=next(iter(PRE_FIX_SHAS))) + "\n"
    assert _scan(tmp_path, {".github/workflows/ci.yml": text}, capsys)[0] == 1


@pytest.mark.parametrize(
    "text",
    [
        f"# was: uses: Digital-Frontier-LDA/just-akash/{POOL}@ca353a9c448c068a7d9a15c01ae89d27d396bf36\njobs: {{}}\n",
        "jobs:\n  pool:\n"
        f"    uses: Digital-Frontier-LDA/just-akash/{POOL}@436f091b048b4522e4c12cfa23b0b38838eb5f15"
        f" # was uses: Digital-Frontier-LDA/just-akash/{POOL}@ca353a9c448c068a7d9a15c01ae89d27d396bf36\n",
    ],
    ids=["full-line-comment", "trailing-comment"],
)
def test_a_commented_call_is_history_not_a_pin(tmp_path, capsys, text):
    assert _scan(tmp_path, {".github/workflows/ci.yml": text}, capsys)[0] == 0


def test_a_listed_sha_on_another_workflow_file_is_not_red(tmp_path, capsys):
    """The pair is (sha, file): runner-teardown.yml at a pre-fix pool's sha runs no image."""
    text = f"jobs:\n  t:\n    uses: Digital-Frontier-LDA/just-akash/{TEARDOWN}@{next(iter(PRE_FIX_SHAS))}\n"
    assert _scan(tmp_path, {".github/workflows/ci.yml": text}, capsys)[0] == 0


def test_residual_an_unlisted_sha_passes(tmp_path, capsys):
    """NAMED RESIDUAL: the rule is offline, so a just-akash commit the list does not hold passes,
    whatever its runner-pool.yml names. The scheduled just-akash-refs.yml workflow is what closes it:
    it re-measures just-akash and fails on any unlisted pair."""
    assert _scan(tmp_path, {".github/workflows/ci.yml": _template("f" * 40)}, capsys)[0] == 0


def test_another_owners_just_akash_is_not_matched(tmp_path, capsys):
    text = f"jobs:\n  p:\n    uses: someone-else/just-akash/{POOL}@{next(iter(PRE_FIX_SHAS))}\n"
    assert _scan(tmp_path, {".github/workflows/ci.yml": text}, capsys)[0] == 0


# ---- the generator, over a real git history -----------------------------------------------


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True, capture_output=True, text=True,
    ).stdout.strip()


def _commit(repo: Path, files: dict[str, str], msg: str) -> str:
    for rel, text in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", msg)
    return _git(repo, "rev-parse", "HEAD")


def _pool(image: str, comment: bool = False) -> str:
    return f"jobs:\n  p:\n    steps:\n      - run: echo\n        {'# ' if comment else ''}image: {image}\n"


@pytest.fixture
def history(tmp_path):
    repo = tmp_path / "just-akash"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    pre = _commit(repo, {POOL: _pool("ghcr.io/x/df-akash-runner@" + PRE_FIX)}, "pre-fix pool")
    fixed = _commit(repo, {POOL: _pool("ghcr.io/x/df-akash-runner@" + mod.FIXED_INDEX)}, "fixed")
    history_only = _commit(repo, {POOL: _pool("ghcr.io/x/df-akash-runner@" + PRE_FIX, comment=True)}, "comment")
    _git(repo, "checkout", "-q", "-b", "old-branch", pre)
    side = _commit(repo, {".github/workflows/probe.yaml": _pool(PRE_FIX), "README.md": "x"}, "side")
    _git(repo, "checkout", "-q", "main")
    return repo, {"pre": pre, "fixed": fixed, "history_only": history_only, "side": side}


def test_the_generator_lists_exactly_the_pre_fix_pairs_over_every_ref(history):
    repo, c = history
    got = {(sha, path) for sha, path, _d in gen.measure(repo)}
    assert got == {
        (c["pre"], POOL),
        (c["side"], POOL),  # the side branch inherits the pre-fix pool
        (c["side"], ".github/workflows/probe.yaml"),  # .yaml, on a branch other than main
    }
    assert all(d == "aaf3799b5e13" for _s, _p, d in gen.measure(repo))


def test_check_passes_on_its_own_output_and_on_a_superset(history, tmp_path):
    repo, _c = history
    out = tmp_path / "refs.txt"
    assert gen.main(["--repo", str(repo), "--write", "--out", str(out)]) == 0
    assert gen.main(["--repo", str(repo), "--check", "--out", str(out)]) == 0
    out.write_text(out.read_text() + "e" * 40 + "  .github/workflows/gone.yml  aaf3799b5e13\n")
    assert gen.main(["--repo", str(repo), "--check", "--out", str(out)]) == 0  # the list only grows


def test_check_fails_when_just_akash_gains_an_unlisted_pre_fix_pair(history, tmp_path, capsys):
    repo, _c = history
    out = tmp_path / "refs.txt"
    gen.main(["--repo", str(repo), "--write", "--out", str(out)])
    new = _commit(repo, {POOL: _pool("ghcr.io/x/df-akash-runner@" + PRE_FIX)}, "a regression")
    capsys.readouterr()
    assert gen.main(["--repo", str(repo), "--check", "--out", str(out)]) == 1
    assert f"just-akash {new} {POOL} pins a pre-fix runner and is not listed" in capsys.readouterr().out


def test_a_shallow_clone_refuses_to_answer(history, tmp_path):
    repo, _c = history
    shallow = tmp_path / "shallow"
    subprocess.run(["git", "clone", "-q", "--depth", "1", f"file://{repo}", str(shallow)], check=True)
    assert gen.main(["--repo", str(shallow), "--check", "--out", str(tmp_path / "x.txt")]) == 2


def test_the_extract_fixture_allows_only_its_one_line(tmp_path, capsys):
    """caller.yml is allowlisted by the exact hash of its pool line. A second pre-fix call in
    the same file, or the same line in another file, is still red."""
    fixture = HERE / "fixtures" / "pool_handoff" / "caller.yml"
    text = fixture.read_text(encoding="utf-8")
    rel = "akash_runner/fixtures/pool_handoff/caller.yml"
    assert _scan(tmp_path / "a", {rel: text}, capsys)[0] == 0
    extra = f"  more:\n    uses: Digital-Frontier-LDA/just-akash/{POOL}@2393294697c091344ae74a7191e0834a520a845a\n"
    assert _scan(tmp_path / "b", {rel: text + extra}, capsys)[0] == 1
    assert _scan(tmp_path / "c", {"templates/caller.yml": text}, capsys)[0] == 1
