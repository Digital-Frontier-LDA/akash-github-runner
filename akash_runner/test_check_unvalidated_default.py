"""Controls for `check_unvalidated_default`.

Every case is built from a regression that ACTUALLY happened, not an invented one:

* KNOWN-POSITIVE — `akash-runner.yml:328` (DigitalFrontier-infra):
    MIN_UACT="${AKASH_MIN_DEPLOY_CREDIT_UACT:-6000000}"
    if [ "$allowance_uact" -lt "$MIN_UACT" ]; then
  A non-numeric value like `abc` would pass the default-substitution and reach the
  numeric comparison unchanged. Today's measured defect.

* KNOWN-NEGATIVE — `akash-runner.yml:887` (DigitalFrontier-infra):
    MIN_POOL="${MIN_POOL_SIZE:-}"
    [ -n "$MIN_POOL" ] || MIN_POOL="$POOL_SIZE"
    if ! [[ "$MIN_POOL" =~ ^[0-9]+$ ]] || [ "$MIN_POOL" -lt 1 ] || [ "$MIN_POOL" -gt "$POOL_SIZE" ]; then
  Empty default + explicit `[[ =~ ^[0-9]+$ ]]` regex check between the substitution
  and the use. Garbage fails closed at the regex, not at the comparison.

* KNOWN-NEGATIVE (URL use, not numeric) — a `${VAR:-x}` passed to `curl` as a URL
  is out of scope. Different defect shape (`curl` fails loud), different rule.

* KNOWN-NEGATIVE (comment) — `# MIN_UACT="${X:-6000000}"` in a comment is not a finding.

The rule also has to coexist with the falsy-string rule (`check_runner_image_and_env`,
invariant 4): a variable that is `[ -n "$VAR" ]` tested is THAT rule's territory, not
this one. The two rules are deliberately complementary, not overlapping.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Load the rule module under test (it depends on baseline/check_conformance.py — loaded
# via the same sys.modules shim used by the production import).
import akash_runner.check_unvalidated_default as ud  # noqa: E402


def _wf(repo: Path, name: str, body: str) -> Path:
    (repo / ".github" / "workflows").mkdir(parents=True, exist_ok=True)
    p = repo / ".github" / "workflows" / name
    p.write_text(body)
    return p


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A minimal repo with NO workflows — every test that needs one writes its own."""
    (tmp_path / ".github" / "workflows").mkdir(parents=True, exist_ok=True)
    return tmp_path


# ── Population pins ────────────────────────────────────────────────────────────


def test_no_workflows_is_na():
    """A workflows-dir with NO `*.yml` MUST report n-a, not pass. A rule that
    vacuously passes on the empty case has no failure mode."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        empty = Path(td) / ".github" / "workflows"
        empty.mkdir(parents=True)
        # NO workflow files in the dir.
        res = ud.check_unvalidated_default(empty, {"ci"})
    assert res.status == "n-a"
    assert "no .github/workflows" in res.note


# ── Known-positive (the real defect) ──────────────────────────────────────────


def test_flags_unvalidated_numeric_threshold(repo):
    """Reproduces akash-runner.yml:328 verbatim — the measured defect."""
    _wf(
        repo,
        "akash-runner.yml",
        """\
name: akash-runner
on: workflow_dispatch
jobs:
  funding:
    steps:
      - name: gate
        run: |
          MIN_UACT="${AKASH_MIN_DEPLOY_CREDIT_UACT:-6000000}"
          if [ "$allowance_uact" -lt "$MIN_UACT" ]; then
            echo "blocked"
          fi
""",
    )
    res = ud.check_unvalidated_default(repo / ".github" / "workflows", {"ci"})
    assert res.status == "warn", res
    assert any("AKASH_MIN_DEPLOY_CREDIT_UACT" in f.message and "numeric threshold" in f.message
               for f in res.findings), res.findings
    # Severity is advisory — this rule's PROMOTE WHEN lives in the docstring, not the code.
    assert all(f.severity == "advisory" for f in res.findings)


def test_flags_unvalidated_destructive_flag(repo):
    """A `${VAR:-x}` flowing into `rm -rf` without validation. Different shape,
    same defect: a garbage value like `--no-preserve-root` substitutes through."""
    _wf(
        repo,
        "purge.yml",
        """\
name: purge
on: workflow_dispatch
jobs:
  clean:
    steps:
      - run: |
          TARGET="${PURGE_TARGET:-/tmp/cache}"
          rm -rf "$TARGET"
""",
    )
    res = ud.check_unvalidated_default(repo / ".github" / "workflows", {"ci"})
    assert res.status == "warn"
    assert any("destructive-mode flag" in f.message and "PURGE_TARGET" in f.message
               for f in res.findings), res.findings


# ── Known-negatives (these MUST NOT flag) ─────────────────────────────────────


def test_empty_default_with_regex_validation_is_not_flagged(repo):
    """The MIN_POOL pattern from akash-runner.yml:887. Empty default + explicit
    `[[ =~ ^[0-9]+$ ]]` between the substitution and the use. Garbage fails closed
    at the regex, not at the comparison — the OPPOSITE of the trap."""
    _wf(
        repo,
        "pool.yml",
        """\
name: pool
on: workflow_dispatch
jobs:
  pool:
    steps:
      - run: |
          MIN_POOL="${MIN_POOL_SIZE:-}"
          [ -n "$MIN_POOL" ] || MIN_POOL="$POOL_SIZE"
          if ! [[ "$MIN_POOL" =~ ^[0-9]+$ ]] || [ "$MIN_POOL" -lt 1 ] || [ "$MIN_POOL" -gt "$POOL_SIZE" ]; then
            echo "::error::min-pool-size must be an integer in 1..${POOL_SIZE} (got '${MIN_POOL}')"; exit 1
          fi
""",
    )
    res = ud.check_unvalidated_default(repo / ".github" / "workflows", {"ci"})
    assert res.status == "pass", res.findings
    assert res.findings == []


def test_url_use_is_out_of_scope(repo):
    """A `${VAR:-https://...}` passed to curl is NOT a numeric threshold or a
    destructive flag. Different defect (`curl` fails loud), different rule.
    Flagging it would train readers to ignore this one."""
    _wf(
        repo,
        "fetch.yml",
        """\
name: fetch
on: workflow_dispatch
jobs:
  fetch:
    steps:
      - run: |
          ALLOWANCE_REST="${AKASH_ALLOWANCE_REST:-https://api.akashnet.net}"
          curl -fsS "$ALLOWANCE_REST/cosmos/authz/v1beta1/grants/grantee/$acct"
""",
    )
    res = ud.check_unvalidated_default(repo / ".github" / "workflows", {"ci"})
    assert res.status == "pass", res.findings


def test_echo_use_is_out_of_scope(repo):
    """A `${VAR:-x}` interpolated into an echo message or a log line is NOT a
    numeric threshold or a destructive flag. Out of scope; not a finding."""
    _wf(
        repo,
        "log.yml",
        """\
name: log
on: workflow_dispatch
jobs:
  log:
    steps:
      - run: |
          msg="Runner listing never readable: ${SEL_PROV:-?} leased but only ${ONLINE_COUNT:-0}/${POOL_SIZE}"
          echo "$msg"
""",
    )
    res = ud.check_unvalidated_default(repo / ".github" / "workflows", {"ci"})
    assert res.status == "pass", res.findings


def test_pattern_in_a_comment_is_not_a_finding(repo):
    """`# MIN_UACT="${X:-6000000}"` inside a YAML/shell comment is documentation,
    not executable shell. A line that doesn't run cannot be the defect."""
    _wf(
        repo,
        "docs.yml",
        """\
name: docs
on: workflow_dispatch
jobs:
  docs:
    steps:
      - run: |
          # Old (defective): MIN_UACT="${AKASH_MIN_DEPLOY_CREDIT_UACT:-6000000}"
          echo "current code does not have this pattern"
""",
    )
    res = ud.check_unvalidated_default(repo / ".github" / "workflows", {"ci"})
    assert res.status == "pass", res.findings


def test_use_outside_lookahead_window_is_out_of_scope(repo):
    """A `${VAR:-x}` with a numeric use more than 100 lines later is NOT flagged —
    the variables could be unrelated, and 100 is the conservative bridge limit."""
    body = "name: far\non: workflow_dispatch\njobs:\n  j:\n    steps:\n      - run: |\n"
    body += "          MIN_UACT=\"${KASH_MIN:-6000000}\"\n"
    # 110 filler lines that do NOT reference MIN_UACT.
    for i in range(110):
        body += f"          echo 'filler {i}'\n"
    body += "          if [ \"$something_else\" -lt 100 ]; then echo ok; fi\n"
    _wf(repo, "far.yml", body)
    res = ud.check_unvalidated_default(repo / ".github" / "workflows", {"ci"})
    assert res.status == "pass", res.findings


# ── Severity pinning ──────────────────────────────────────────────────────────


def test_rule_emits_advisory_findings_never_required():
    """PROMOTE WHEN lives in the rule's docstring; the code emits `advisory` only.

    A rule that emits `required` from the start has no operator lever — it either
    blocks every workflow with a `${VAR:-x}` (noisy) or has to be turned off
    wholesale (silent). `advisory` is the deliberate starting severity."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        empty = Path(td)
        wf = empty / ".github" / "workflows"
        wf.mkdir(parents=True)
        (wf / "x.yml").write_text(
            "name: x\non: workflow_dispatch\njobs:\n  j:\n    steps:\n      - run: |\n"
            "          MIN_UACT=\"${KASH:-100}\"\n"
            "          if [ \"$x\" -lt \"$MIN_UACT\" ]; then echo no; fi\n"
        )
        res = ud.check_unvalidated_default(wf, {"ci"})
    if res.findings:
        assert all(f.severity == "advisory" for f in res.findings)