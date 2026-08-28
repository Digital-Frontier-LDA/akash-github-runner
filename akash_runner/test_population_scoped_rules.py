"""POPULATION_SCOPED rules must fail on the 2026-08-28 shapes, and pass otherwise.

Every rule here is judged against a FAKE population, not the live org — a test that needs
credentials is a test that gets skipped, and a skipped rule is one of the two vacuous
outcomes this suite already warns about. The live read is exercised separately by the
scheduled monitor.
"""

from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "baseline"))

from check_population import (  # noqa: E402
    Unreadable,
    rule_claimed_population_shrinks,
    rule_reaper_matches_its_population,
)
import check_population  # noqa: E402


def _fake_names(monkeypatch, names):
    monkeypatch.setattr(check_population, "_gh", lambda args: "\n".join(names))


def _raises(monkeypatch, exc=Unreadable("boom")):
    def blow(args):
        raise exc

    monkeypatch.setattr(check_population, "_gh", blow)


class TestTotalMiss:
    """The 2026-08-28 shape: a reaper aimed at a prefix absent from the population."""

    POP = [f"akash-e2epool-3304846129{i}-aaaaaaaaaaaaa" for i in range(9)] + [
        f"akash-fast-pool-3301369859{i}-1-bbbbbbbbbbbb" for i in range(9)
    ]

    def test_zero_matches_over_a_nonempty_population_is_not_clean(self, monkeypatch):
        _fake_names(monkeypatch, self.POP)
        r = rule_reaper_matches_its_population("org", ["df-core-"])
        assert r.status == "warn", "matched=0 over a real population reported as clean"
        assert r.findings and "matched 0 of" in r.findings[0].message

    def test_it_names_the_dominant_prefix_so_the_reader_can_resolve_OWNERSHIP(
        self, monkeypatch
    ):
        """⛔ THE DIAGNOSIS MATTERS MORE THAN THE VERDICT. A bare 'you matched nothing'
        invites widening the prefix — which on 2026-08-28 would have deleted a sibling
        repo's LIVE runners. Naming the dominant prefix is what sends the reader to
        resolve an embedded run id instead."""

        _fake_names(monkeypatch, self.POP)
        r = rule_reaper_matches_its_population("org", ["df-core-"])
        msg = r.findings[0].message
        assert "akash-e2epool" in msg or "akash-fast-pool" in msg
        assert "another repo" in msg and "run id" in msg

    def test_it_passes_when_the_prefix_is_right(self, monkeypatch):
        """BOTH DIRECTIONS: a rule that always warned would satisfy the tests above."""

        _fake_names(monkeypatch, self.POP)
        r = rule_reaper_matches_its_population(
            "org", ["akash-e2epool-", "akash-fast-pool-"]
        )
        assert r.status == "pass", r.note

    def test_an_unreadable_population_is_NA_not_zero(self, monkeypatch):
        """⛔ UNREADABLE IS NOT ZERO. Reporting 'matched 0' on a failed read manufactures
        the exact false-clean this module exists to catch."""

        _raises(monkeypatch)
        r = rule_reaper_matches_its_population("org", ["df-core-"])
        assert r.status == "n-a"
        assert "unreadable" in r.note

    def test_an_empty_population_is_NA_not_a_failure(self, monkeypatch):
        """Nothing to reap is not a misaimed reaper."""

        _fake_names(monkeypatch, [])
        assert rule_reaper_matches_its_population("org", ["df-core-"]).status == "n-a"


class TestShrinkage:
    def test_growth_fails(self):
        r = rule_claimed_population_shrinks({"count": 50}, 80, "org runners")
        assert r.status == "fail"
        assert r.findings[0].severity == "required"

    def test_shrinkage_passes(self):
        assert (
            rule_claimed_population_shrinks({"count": 80}, 50, "org runners").status
            == "pass"
        )

    def test_first_observation_is_NA(self):
        assert rule_claimed_population_shrinks(None, 10, "org runners").status == "n-a"

    def test_AT_THE_CAP_IS_CENSORED_NOT_STABLE(self):
        """⛔ THE TRAP THIS RULE MUST NOT FALL INTO. `total_count` saturates at 10000, so
        deletions do not move it until the true figure drops below the ceiling. Reading
        10000 -> 10000 as 'stable, pass' would be a confident answer from a blind probe;
        reading it as 'did not shrink, fail' would be equally unfounded. Only n-a is honest."""

        r = rule_claimed_population_shrinks({"count": 10000}, 10000, "org runners")
        assert r.status == "n-a", "a censored reading was scored as a verdict"
        assert "CAP" in r.note and "censored" in r.note

    def test_below_the_cap_the_same_numbers_DO_get_a_verdict(self):
        """BOTH DIRECTIONS for the cap exemption: it must apply ONLY at the ceiling, or it
        would silently excuse every stalled reaper."""

        r = rule_claimed_population_shrinks({"count": 9000}, 9000, "org runners")
        assert r.status == "pass", "the cap exemption leaked below the cap"
