"""Controls for check_demand_scaled_funding_floor — the demand-scaled floor standard.

The rule exists because the operator asked for demand-scaled floors as a fleet
STANDARD (2026-08-25: "a concurrency limiter that costs nothing"). A rule of this
class is only as good as its controls:

  KNOWN-POSITIVE — the pre-#1617 shape (provisions, declares nothing) MUST be
  flagged; the declared-but-no-op shape (demand=1) MUST be flagged; declared-but-
  literal-floor MUST be flagged.

  KNOWN-NEGATIVE — the post-#1617 Blazing-Back shape (provisions, declares 6,
  derives floor from deposit × demand) MUST pass; a RECOVERY workflow (closer/
  sweeper) that provisions MUST be exempt — the exemption is the wedge-proofing; a
  pure-build workflow MUST be out of scope.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_demand_scaled_funding_floor import check_workflow  # noqa: E402

import yaml  # noqa: E402

TMP = Path("/tmp/_dsf_fixtures")
TMP.mkdir(exist_ok=True)


def _wf(name: str, doc: dict) -> Path:
    p = TMP / name
    p.write_text(yaml.dump(doc, sort_keys=False))
    return p


def _provisioner(env: dict | None, run_extra: str = "") -> dict:
    return {
        "on": {"push": None},
        "jobs": {
            "deploy": {
                "runs-on": "ubuntu-latest",
                "steps": [
                    {"run": f"just-akash deploy --sdl pool.yaml {run_extra}"},
                ],
                **({"env": env} if env else {}),
            }
        },
    }


def test_known_positive_no_declaration_is_flagged():
    p = _wf("pool.yml", _provisioner(env=None))
    findings = check_workflow(p)
    assert any("declares no DEMAND" in f for f in findings), findings


def test_known_positive_noop_default_of_one_is_flagged():
    p = _wf("pool.yml", _provisioner(env={"AKASH_DEPOSITS_NEEDED": "1"}))
    findings = check_workflow(p)
    assert any("demand=1" in f for f in findings), findings


def test_known_positive_literal_floor_beside_silent_demand_computes_nothing():
    p = _wf(
        "pool.yml",
        _provisioner(
            env={"AKASH_DEPOSITS_NEEDED": "6", "MIN_UACT": "5000000"},
        ),
    )
    findings = check_workflow(p)
    assert any("no floor expression derives" in f for f in findings), findings


def test_known_negative_post_1617_shape_passes():
    doc = {
        "on": {"push": None},
        "jobs": {
            "deploy": {
                "runs-on": "ubuntu-latest",
                "env": {"AKASH_DEPOSITS_NEEDED": "6"},
                "steps": [
                    {
                        # the #1617 form: floor computed FROM the declared demand
                        "run": (
                            "MIN_UACT=$(( DEPOSIT_UACT * AKASH_DEPOSITS_NEEDED ))\n"
                            "just-akash deploy --sdl pool.yaml"
                        )
                    }
                ],
            }
        },
    }
    p = _wf("pool.yml", doc)
    assert check_workflow(p) == [], check_workflow(p)


def test_known_negative_recovery_workflow_is_exempt():
    """⛔ The wedge-proofing: flooring a closer means no deposit returns, ever."""
    doc = {
        "on": {"schedule": [{"cron": "0 * * * *"}]},
        "jobs": {
            "close": {
                "runs-on": "ubuntu-latest",
                "steps": [
                    {
                        "run": "just-akash cleanup-stale --execute  # closes /v1/deployments"
                    }
                ],
            }
        },
    }
    p = _wf("cleanup-stale.yml", doc)
    assert check_workflow(p) == [], (
        "a RECOVERY workflow was flagged — flooring closers/sweepers is the deadlock, "
        "not the standard"
    )


def test_known_negative_pure_build_is_out_of_scope():
    doc = {
        "on": {"push": None},
        "jobs": {
            "build": {"runs-on": "ubuntu-latest", "steps": [{"run": "docker build ."}]}
        },
    }
    p = _wf("build.yml", doc)
    assert check_workflow(p) == []


def test_a_comment_about_deploying_is_not_deploying():
    doc = {
        "on": {"push": None},
        "jobs": {
            "docs": {
                "runs-on": "ubuntu-latest",
                "steps": [
                    # prose in a run: block about deploying — stripped before matching
                    {"run": "# this workflow used to call just-akash deploy\necho docs"}
                ],
            }
        },
    }
    p = _wf("docs.yml", doc)
    assert check_workflow(p) == []
