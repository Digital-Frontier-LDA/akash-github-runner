"""The listing-failure rule must separate a swallowed status from a handled one.

⛔ WHY EACH CASE IS HERE. The rule shipped on #29 with a string-based escape hatch: it
treated the mere PRESENCE of `LIST_RC` in a 200-character window as proof the status was
handled. CodeRabbit caught that `gh api … || true` followed by `LIST_RC=$?` therefore
PASSED — the capture records `true`'s zero, so the one shape the rule exists to reject was
green, and any file could disarm the rule by naming the variable in a comment.

Every case below is a DISCRIMINATOR: it must separate two shapes the rule would otherwise
conflate. A test that only asserts "the known-bad file fails" would have passed against the
broken version too.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from akash_runner.check_listing_failure_is_loud import check_file  # noqa: E402

_LIST = "gh api --paginate \"orgs/${ORG}/actions/runners?per_page=100\" \\\n  --jq '.runners[].id'"


def _wf(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "reaper.yml"
    p.write_text("name: r\njobs:\n  reap:\n    steps:\n      - run: |\n" + body)
    return p


# ── the regression CodeRabbit found ────────────────────────────────────────────────
def test_capture_after_a_constant_fallback_is_flagged(tmp_path):
    """`cmd || true` then `RC=$?` captures TRUE's zero. It must NOT read as handled."""
    f = _wf(tmp_path, f"          {_LIST} > /tmp/o.tsv || true\n          LIST_RC=$?\n")
    findings = check_file(f)
    assert findings, "a capture AFTER a constant fallback records the fallback's zero"
    assert "FALLBACK's zero" in findings[0], findings


def test_naming_the_variable_in_a_comment_does_not_disarm_the_rule(tmp_path):
    """The old rule keyed on the STRING `LIST_RC`; a comment mentioning it was enough."""
    f = _wf(
        tmp_path,
        f"          # LIST_RC is captured elsewhere\n          {_LIST} || true\n",
    )
    assert check_file(f), "a rule keyed to a name is disarmed by writing that name"


# ── shapes that must NOT be flagged ────────────────────────────────────────────────
def test_status_captured_with_set_plus_e_is_clean(tmp_path):
    f = _wf(
        tmp_path,
        f"          set +e\n          {_LIST} > /tmp/o.tsv\n          LIST_RC=$?\n          set -e\n",
    )
    assert check_file(f) == [], (
        "capturing the command's own status is the correct shape"
    )


def test_stderr_redirect_alone_is_not_a_swallow(tmp_path):
    """`2>/dev/null` hides stderr and leaves the exit status intact — under `set -e` the
    run still stops. Flagging it was a false positive CodeRabbit was right about."""
    f = _wf(tmp_path, f"          {_LIST} 2>/dev/null > /tmp/o.tsv\n")
    assert check_file(f) == [], "2>/dev/null alone does not discard the exit status"


def test_a_deliberate_fallback_that_is_emptiness_tested_is_clean(tmp_path):
    """Swallow, then refuse to trust the value, is a legitimate handling shape — it is
    what this repo's own TOTAL/AFTER reads do."""
    f = _wf(
        tmp_path,
        f'          T="$({_LIST} 2>/dev/null || echo "")"\n          if [ -z "$T" ]; then exit 1; fi\n',
    )
    assert check_file(f) == [], "an emptiness-tested fallback is handled, not swallowed"


def test_the_single_record_control_read_is_not_the_population(tmp_path):
    f = _wf(
        tmp_path,
        '          T="$(gh api "orgs/${ORG}/actions/runners?per_page=1" --jq \'.total_count\')" || true\n',
    )
    assert check_file(f) == [], "per_page=1 is a control probe, not the population read"


# ── naked swallow, and non-vacuity ─────────────────────────────────────────────────
def test_naked_constant_fallback_is_flagged(tmp_path):
    f = _wf(tmp_path, f"          {_LIST} > /tmp/o.tsv || true\n")
    findings = check_file(f)
    assert findings and "clean sweep" in findings[0], findings


def test_a_workflow_with_no_runner_listing_yields_no_findings(tmp_path):
    """NON-VACUITY GUARD IN REVERSE: silence must come from absence of the subject, not
    from the matcher failing to fire. Paired with the flagged cases above, a rule that
    matched nothing at all would fail those and be caught."""
    f = _wf(
        tmp_path,
        "          gh api rate_limit --jq '.resources.core.remaining' || true\n",
    )
    assert check_file(f) == [], "a non-runner listing is out of scope"


# ── the real tree, both directions ─────────────────────────────────────────────────
def test_this_repo_passes_and_the_pass_is_not_vacuous():
    here = Path(__file__).resolve().parents[1] / ".github" / "workflows"
    reaper = here / "reusable-stale-runner-reaper.yml"
    assert reaper.is_file(), (
        "the subject workflow must exist or this test proves nothing"
    )
    assert "actions/runners?per_page=100" in reaper.read_text(), (
        "the population listing must be present, or a PASS means the rule found nothing"
    )
    assert check_file(reaper) == [], "this repo's reaper must satisfy its own rule"
