"""Tests for check_gate_is_not_re_derived.py and the shared gate_registry.

The rule generalises `check_funding_gate_is_not_re_derived.py` from one primitive to a
registry, because the defect it names is not about funding — it is about a consumer
computing a verdict from raw numbers when a shared primitive already answers the question.
That recurs per cloud, and copying the rule per cloud reproduces the mistake one level up.

⚠ Two of the fixtures below are REGRESSIONS FROM REAL ARTEFACTS, not invented shapes.
Both were false positives the first version produced against Blazing-Back's ci-pr.yml.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
RULE = HERE / "check_gate_is_not_re_derived.py"


@pytest.fixture(scope="module")
def gr():
    spec = importlib.util.spec_from_file_location("gr_under_test", HERE / "gate_registry.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules["gr_under_test"] = m
    spec.loader.exec_module(m)
    return m


def _wf(tmp_path: Path, body: str, name="wf.yml") -> Path:
    p = tmp_path / name
    p.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
    return p


def _run(*args):
    return subprocess.run([sys.executable, str(RULE), *map(str, args)],
                          capture_output=True, text=True)


# ----------------------------------------------------------------------------------
# non-vacuity first: the rule must fire on a real re-derivation
# ----------------------------------------------------------------------------------

REDERIVES = """
    name: bad
    on: [push]
    jobs:
      deploy:
        runs-on: ubuntu-latest
        steps:
          - run: |
              FREE=$(kubectl get nodes -o json | jq '.items[].status.allocatable.cpu')
              if [ "$FREE" -lt 2000 ]; then
                echo "::error::no capacity"
                exit 1
              fi
    """


def test_a_local_capacity_derivation_is_flagged(tmp_path):
    r = _run("--gate", "capacity", _wf(tmp_path, REDERIVES))
    assert r.returncode == 1, r.stdout
    assert "DECIDES capacity" in r.stdout


def test_the_capacity_antipatterns_are_named(tmp_path):
    r = _run("--gate", "capacity", _wf(tmp_path, REDERIVES))
    assert "ignores-the-autoscaler-ceiling" in r.stdout


def test_utilisation_gating_is_named_specifically(tmp_path):
    body = REDERIVES.replace(
        "kubectl get nodes -o json | jq '.items[].status.allocatable.cpu'",
        "kubectl top nodes --no-headers | awk '{print $3}'",
    )
    r = _run("--gate", "capacity", _wf(tmp_path, body))
    assert r.returncode == 1
    assert "gates-on-utilisation-not-requests" in r.stdout


# ----------------------------------------------------------------------------------
# ⛔ REGRESSION 1 — manifest authoring is not a capacity read
# ----------------------------------------------------------------------------------

def test_yq_setting_a_request_in_a_manifest_is_NOT_a_capacity_gate(tmp_path):
    """VERBATIM shape from Blazing-Back ci-pr.yml `canary-deploy`, which the first
    version of this rule flagged. `.resources.requests.cpu = "100m"` SETS the canary's own
    request; it does not read cluster capacity. The `-lt` / `exit 1` / `::error` that
    satisfied the DECIDES limb were unrelated error handling in the same block.

    ⚠ The count alone hid this: with the preflight wired the job becomes needs-exempt, so
    the rule went green and the before/after read like proof it worked. Only printing the
    MATCH showed the finding was never real."""
    body = """
        name: deploy
        on: [push]
        jobs:
          canary-deploy:
            runs-on: ubuntu-latest
            steps:
              - run: |
                  yq -i '
                    (.spec.template.spec.containers[] | select(.name == "api") | .resources.requests.cpu) = "100m" |
                    (.spec.template.spec.containers[] | select(.name == "api") | .resources.requests.memory) = "256Mi"
                  ' deploy.yaml
                  if ! kubectl apply -f deploy.yaml; then
                    echo "::error::apply failed"
                    exit 1
                  fi
        """
    r = _run("--gate", "capacity", _wf(tmp_path, body))
    assert r.returncode == 0, f"FALSE POSITIVE on manifest authoring:\n{r.stdout}"


def test_reading_requests_FROM_THE_CLUSTER_still_fires(tmp_path):
    """The narrowing must not make the rule inert: a real headroom computation reads pod
    requests out of `kubectl get pods` and is in scope."""
    body = """
        name: real
        on: [push]
        jobs:
          gate:
            runs-on: ubuntu-latest
            steps:
              - run: |
                  USED=$(kubectl get pods -A -o json | jq '[.items[].spec.containers[].resources.requests.cpu]|length')
                  if [ "$USED" -gt 40 ]; then
                    echo "::error::no room"
                    exit 1
                  fi
        """
    r = _run("--gate", "capacity", _wf(tmp_path, body))
    assert r.returncode == 1, r.stdout


# ----------------------------------------------------------------------------------
# ⛔ REGRESSION 2 — the exemption is a JOB property, closed over `needs:`
# ----------------------------------------------------------------------------------

TWO_JOB = """
    name: safe
    on: [push]
    jobs:
      gke-capacity-preflight:
        runs-on: ubuntu-latest
        outputs:
          capacity_ok: ${{ steps.pf.outputs.capacity_ok }}
        steps:
          - id: pf
            run: python3 scripts/gke_capacity_preflight.py
      canary-deploy:
        needs: [gke-capacity-preflight]
        runs-on: ubuntu-latest
        steps:
          - env:
              CAPACITY_OK: ${{ needs.gke-capacity-preflight.outputs.capacity_ok }}
            run: |
              USED=$(kubectl get pods -A -o json | jq '[.items[].spec.containers[].resources.requests.cpu]|length')
              if [ "$CAPACITY_OK" != "true" ] && [ "$USED" -gt 1 ]; then
                echo "::error::no room"
                exit 1
              fi
    """


def test_a_job_consuming_the_primitive_via_needs_is_exempt(tmp_path):
    """⛔ The first version matched markers against the `run:` block alone and flagged the
    consumer, because the marker lives in the step's `env:` as a `needs.*.outputs` ref.

    That false positive landed on the SAFE design specifically: running the preflight in
    its own job and consuming its output is what stops a broken preflight from skipping a
    required check. A rule that reds the recommended design and passes the discouraged one
    is worse than no rule."""
    r = _run("--gate", "capacity", _wf(tmp_path, TWO_JOB))
    assert r.returncode == 0, f"flagged a job that DOES consume the primitive:\n{r.stdout}"


def test_the_exemption_is_NOT_file_level(tmp_path):
    """An unrelated job in the same file has no `needs:` edge and stays in scope —
    otherwise one correct job would whitewash every other job beside it."""
    extra = """  unrelated:
    runs-on: ubuntu-latest
    steps:
      - run: |
          FREE=$(kubectl get nodes -o json | jq '.items[].status.allocatable.cpu')
          if [ "$FREE" -lt 2000 ]; then
            echo "::error::no capacity"
            exit 1
          fi
"""
    body = textwrap.dedent(TWO_JOB).lstrip() + extra
    r = _run("--gate", "capacity", _wf(tmp_path, body))
    assert r.returncode == 1, r.stdout
    assert "'unrelated'" in r.stdout
    assert "'canary-deploy'" not in r.stdout


def test_transitive_needs_are_closed(tmp_path, gr):
    extra = """  downstream:
    needs: [canary-deploy]
    runs-on: ubuntu-latest
    steps:
      - run: |
          kubectl get pods -A -o json | jq '.items[].spec.containers[].resources.requests.cpu'
          [ "$X" -gt 1 ] && exit 1
"""
    p = _wf(tmp_path, textwrap.dedent(TWO_JOB).lstrip() + extra)
    reaching = gr.jobs_reaching_primitive(p, gr.GATES["capacity"])
    assert {"gke-capacity-preflight", "canary-deploy", "downstream"} <= reaching


# ----------------------------------------------------------------------------------
# scope, shared anti-pattern, and CLI
# ----------------------------------------------------------------------------------

def test_reading_without_deciding_is_out_of_scope(tmp_path):
    """Printing a number for a human is not a gate. Demanding the primitive of a
    diagnostic is noise that trains readers to dismiss the rule."""
    body = """
        name: diag
        on: [push]
        jobs:
          report:
            runs-on: ubuntu-latest
            steps:
              - run: kubectl get nodes -o json | jq '.items[].status.allocatable'
        """
    r = _run("--gate", "capacity", _wf(tmp_path, body))
    assert r.returncode == 0, r.stdout


COLLAPSE_CAPACITY = """
    name: collapse-cap
    on: [push]
    jobs:
      gate:
        runs-on: ubuntu-latest
        steps:
          - run: |
              FREE=$(kubectl get nodes -o json | jq '.items[].status.allocatable.cpu') || true
              if [ -z "$FREE" ]; then
                echo "::error::no capacity available"
                exit 1
              fi
    """

COLLAPSE_FUNDING = """
    name: collapse-fund
    on: [push]
    jobs:
      gate:
        runs-on: ubuntu-latest
        steps:
          - run: |
              CREDIT=$(curl -s "$API/allowance" | jq .spend_limits) || true
              if [ -z "$CREDIT" ]; then
                echo "::error::no funds available"
                exit 1
              fi
    """


@pytest.mark.parametrize("gate,body", [
    ("capacity", COLLAPSE_CAPACITY),
    ("funding", COLLAPSE_FUNDING),
])
def test_the_shared_antipattern_FIRES_on_both_gates(tmp_path, gate, body):
    """⭐ The reason this is a registry and not two rules. #1113 has now been seen on
    three artefacts across two clouds, and a per-cloud rule cannot see it — each author
    meets it once and fixes it locally.

    ⛔ THIS ASSERTS BEHAVIOUR, NOT A CONSTANT. The first version of this test read
    SHARED_ANTIPATTERNS and merged it ITSELF, so it passed with the production merge
    deleted — it was testing the dict's existence, not that any gate applies it. A mutant
    that stopped merging survived. Fire the rule and read what it reports instead."""
    r = _run("--gate", gate, _wf(tmp_path, body, f"{gate}.yml"))
    assert r.returncode == 1, r.stdout
    assert "collapses-unknown-into-declined" in r.stdout, (
        f"the shared #1113 anti-pattern is not applied to the {gate} gate:\n{r.stdout}"
    )


def test_both_gates_are_registered(gr):
    assert set(gr.GATES) == {"funding", "capacity"}
    assert "collapses-unknown-into-declined" in gr.SHARED_ANTIPATTERNS


def test_gate_all_covers_every_registered_gate(gr):
    assert set(gr.GATES) == {"funding", "capacity"}


def test_gate_selection_narrows_the_scan(tmp_path):
    p = _wf(tmp_path, REDERIVES)
    assert _run("--gate", "capacity", p).returncode == 1
    assert _run("--gate", "funding", p).returncode == 0, "capacity code is not a funding gate"


def test_an_empty_corpus_is_a_BROKEN_SCAN_not_a_clean_repo(tmp_path):
    """⛔ Exiting 0 here would report 'no gates re-derived' for a path never read."""
    empty = tmp_path / "none"
    empty.mkdir()
    r = _run("--gate", "capacity", empty)
    assert r.returncode == 2
    assert "scan is broken" in r.stderr


def test_the_funding_gate_still_behaves_as_before(tmp_path):
    """The registry must not have changed the older gate's semantics."""
    body = """
        name: fund
        on: [push]
        jobs:
          precheck:
            runs-on: ubuntu-latest
            steps:
              - run: |
                  CREDIT=$(curl -s "$API/deploy_credit" | jq .deploy_credit)
                  if [ "$CREDIT" -lt 5000000 ]; then exit 1; fi
        """
    r = _run("--gate", "funding", _wf(tmp_path, body))
    assert r.returncode == 1
    # ⚠ COLON-SPACE, not the bare name. The rule renders `f"{name}: {why}"`, so a bare
    # substring assertion also matches a RENAMED key like
    # "gates-on-console-deploy-credit-DISABLED" — measured: a mutant that renamed the key
    # survived this test until the delimiter was pinned. A substring that passes for the
    # wrong reason is indistinguishable from one that passes for the right one.
    assert "gates-on-console-deploy-credit: " in r.stdout, r.stdout


# ----------------------------------------------------------------------------------
# ⛔⛔ REGRESSION — a partial scan must never report a pass
#
# Caught by CodeRabbit on #21. `unreadable` was counted and PRINTED, then ignored by the
# exit path: an unparseable workflow plus no findings printed "OK" and returned 0.
#
# This is the rule's OWN `collapses-unknown-into-declined` inverted — a could-not-measure
# collapsing into a measured verdict, in the permissive direction. A rule that exists to
# catch false all-clears was emitting one, which is why it needed an outside reader.
# ----------------------------------------------------------------------------------

MALFORMED = "name: broken\non: [push]\njobs:\n  a: :\n    - oops\n"


def test_an_unreadable_workflow_never_reports_a_pass(tmp_path):
    (tmp_path / "ok.yml").write_text(
        "name: fine\non: [push]\njobs:\n  a:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo hi\n",
        encoding="utf-8",
    )
    (tmp_path / "broken.yml").write_text(MALFORMED, encoding="utf-8")
    r = _run("--gate", "capacity", tmp_path)
    assert r.returncode == 2, f"a partial scan returned {r.returncode}:\n{r.stdout}"
    assert "PARTIAL SCAN" in r.stdout
    assert "OK: every in-scope gate routes" not in r.stdout, "printed a clean bill on a partial scan"


def test_unreadable_dominates_even_when_findings_exist(tmp_path):
    """rc=1 would tell a consumer 'these are all of them'. The unaudited files may carry
    more, so the incompleteness outranks the findings — but the findings still PRINT,
    because an unreadable neighbour does not make them untrue."""
    (tmp_path / "bad.yml").write_text(textwrap.dedent(REDERIVES).lstrip(), encoding="utf-8")
    (tmp_path / "broken.yml").write_text(MALFORMED, encoding="utf-8")
    r = _run("--gate", "capacity", tmp_path)
    assert r.returncode == 2, r.stdout
    assert "DECIDES capacity" in r.stdout, "findings must still be reported"
    assert "PARTIAL SCAN" in r.stdout


def test_a_fully_readable_clean_scan_still_passes(tmp_path):
    """The control: the fix must not make every scan a 2."""
    (tmp_path / "ok.yml").write_text(
        "name: fine\non: [push]\njobs:\n  a:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo hi\n",
        encoding="utf-8",
    )
    r = _run("--gate", "capacity", tmp_path)
    assert r.returncode == 0, r.stdout
    assert "OK: every in-scope gate routes" in r.stdout
