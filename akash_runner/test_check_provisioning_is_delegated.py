"""§1's first mandate, and the false positives that would get the rule deleted.

★ The gap: the standard's FIRST mandate had no rule. A repo can run every rule this suite has,
at a pin level with main, and still violate it — so the gap was in the RULE SET, not in uptake.

⚠ WHAT MAKES THIS RULE HARD IS NOT DETECTION, IT IS THE THREE THINGS IT MUST *NOT* FLAG:
the provider itself, a commented-out provisioning line, and a compliant delegating consumer.
Each is tested below, because a rule that cries on those gets deleted rather than fixed.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from conformance_exit import NOT_JUDGEABLE

RULE = Path(__file__).resolve().parent / "check_provisioning_is_delegated.py"


def _run(d: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(RULE), str(d)],
                          capture_output=True, text=True, timeout=60)


def _wf(d: Path, name: str, body: str) -> None:
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(body)


LOCAL_PROVISIONER = """
name: runner
on: [push]
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - run: uv tool run just-akash deploy /tmp/sdl.yaml --deposit 1.0
"""

DELEGATING = """
name: runner
on: [push]
jobs:
  pool:
    uses: Digital-Frontier-LDA/just-akash/.github/workflows/runner-pool.yml@v1.2.3
    with:
      pool-size: 4
"""


def test_a_local_provisioner_is_a_finding(tmp_path):
    _wf(tmp_path, "akash-runner.yml", LOCAL_PROVISIONER)
    r = _run(tmp_path)
    assert r.returncode == 1, f"a repo-local provisioner passed:\n{r.stdout}{r.stderr}"
    assert "akash-runner.yml" in r.stdout


def test_the_finding_is_not_keyed_to_the_FILENAME(tmp_path):
    """⛔ A rename must not defeat it. The subject is BEHAVIOUR, not `akash-runner.yml` —
    this suite has a standing rule against finders keyed to the string under change."""
    _wf(tmp_path, "totally-innocuous-name.yml", LOCAL_PROVISIONER)
    r = _run(tmp_path)
    assert r.returncode == 1, "renaming the file defeated the rule"
    assert "totally-innocuous-name.yml" in r.stdout


def test_a_delegating_consumer_passes(tmp_path):
    _wf(tmp_path, "runner.yml", DELEGATING)
    r = _run(tmp_path)
    assert r.returncode == 0, f"a compliant consumer was flagged:\n{r.stdout}{r.stderr}"


def test_a_COMMENTED_OUT_provisioning_line_is_not_a_call_site(tmp_path):
    """⚠ MEASURED: df-cicd and akash-github-runner both carry
    `# DSEQ=$(just-akash deploy ...)`. A grep-keyed rule reports two false violations on
    repos that provision nothing at all."""
    _wf(tmp_path, "gate.yml", """
name: gate
on: [push]
jobs:
  x:
    runs-on: ubuntu-latest
    steps:
      - run: |
          # DSEQ=$(just-akash deploy gate/scanner.sdl --tag gate)
          echo "dseq=" >> "$GITHUB_OUTPUT"
""")
    r = _run(tmp_path)
    assert r.returncode == NOT_JUDGEABLE, (
        f"a commented-out provisioning line was read as a call site (exit {r.returncode})"
    )


def test_the_PROVIDER_itself_is_not_a_violation(tmp_path):
    """⛔ WITHOUT THIS THE RULE FLAGS THE ONE REPO THAT IS CORRECT. just-akash provisions and
    does not delegate, because it IS the delegate."""
    _wf(tmp_path, "runner-pool.yml", """
name: pool
on:
  workflow_call:
    inputs:
      pool-size: {required: false, type: string}
jobs:
  x:
    runs-on: ubuntu-latest
    steps:
      - run: just-akash deploy /tmp/sdl.yaml
""")
    r = _run(tmp_path)
    assert r.returncode == 0, f"the provider was flagged as a violator:\n{r.stdout}{r.stderr}"


def test_the_provider_exemption_is_behavioural_not_by_name(tmp_path):
    """★ The control that keeps the exemption honest: same FILENAME, no `workflow_call`, so it
    publishes nothing to anyone — and must still be a finding."""
    _wf(tmp_path, "runner-pool.yml", LOCAL_PROVISIONER)
    r = _run(tmp_path)
    assert r.returncode == 1, "a file merely NAMED runner-pool.yml earned the exemption"


def test_a_repo_that_provisions_nothing_is_NOT_JUDGEABLE(tmp_path):
    """⚠ Not a PASS. This rule cannot tell you whether provisioning is delegated in a repo
    that never provisions — measured on df-cicd, agr and df-wiki."""
    _wf(tmp_path, "ci.yml", "name: ci\non: [push]\njobs:\n  x:\n    runs-on: u\n    steps:\n      - run: echo hi\n")
    r = _run(tmp_path)
    assert r.returncode == NOT_JUDGEABLE, f"exit {r.returncode}, expected NOT_JUDGEABLE"


def test_a_missing_directory_is_a_usage_error_not_a_verdict(tmp_path):
    r = _run(tmp_path / "nope")
    assert r.returncode == 2


def test_the_SDL_signal_alone_is_enough(tmp_path):
    """⛔ FOUND BY MUTATION, and my first suite MISSED IT.

    Blinding the rule to `RUNNER_NAME_PREFIX` — leaving only the `just-akash deploy` signal —
    changed a finding into NOT-JUDGEABLE and **every test still passed**, because every fixture
    happened to use the deploy verb. The real population hides it too: both Blazing-Back
    provisioners carry BOTH signals, so no live repo would have exposed the gap either.

    A workflow that renders a runner SDL without invoking the deploy verb in the same `run:`
    block is provisioning just as surely, and this is the only test that says so.
    """
    _wf(tmp_path, "renders-sdl.yml", """
name: r
on: [push]
jobs:
  j:
    runs-on: ubuntu-latest
    steps:
      - run: |
          cat > /tmp/sdl.yaml <<'SDL'
          services:
            runner:
              env:
                - RUNNER_NAME_PREFIX=df-core-${RUNNER_LABEL}
          SDL
""")
    r = _run(tmp_path)
    assert r.returncode == 1, (
        f"a workflow rendering a runner SDL was not detected (exit {r.returncode}). The deploy "
        f"verb is not the only provisioning signal.\n{r.stdout}{r.stderr}"
    )


def test_the_DEPLOY_signal_alone_is_enough(tmp_path):
    """The complement, so neither signal can be dropped silently."""
    _wf(tmp_path, "deploys.yml", LOCAL_PROVISIONER)
    r = _run(tmp_path)
    assert r.returncode == 1, f"the deploy verb alone was not detected (exit {r.returncode})"


def test_a_NOOP_runner_pool_does_not_earn_the_exemption(tmp_path):
    """⛔ THE THREE-LINE DECOY, found by DEVOPS-core in review and reproduced before fixing.

    A repo could exempt itself from §1 permanently by adding a `runner-pool.yml` that
    declares `on: workflow_call` and does NOTHING:

        build.yml        RUNNER_NAME_PREFIX=evil-  +  just-akash deploy
        runner-pool.yml  name / on: workflow_call / jobs: {noop}   -> PASS, exit 0

    The predicate tested whether a repo CLAIMS to be the provider, not whether it IS one.
    A provider PROVISIONS — so the exemption now requires the pool workflow to carry the
    provisioning signal the rule already computes.
    """
    _wf(tmp_path, "build.yml", LOCAL_PROVISIONER)
    _wf(tmp_path, "runner-pool.yml", """
name: runner-pool
on:
  workflow_call:
jobs:
  noop:
    runs-on: ubuntu-latest
    steps:
      - run: echo nothing
""")
    r = _run(tmp_path)
    assert r.returncode == 1, (
        f"a NO-OP runner-pool.yml earned the provider exemption (exit {r.returncode}) — "
        f"the rule's own escape hatch is a three-line file.\n{r.stdout}{r.stderr}"
    )
    assert "build.yml" in r.stdout


def test_a_REAL_provider_pool_still_earns_the_exemption(tmp_path):
    """★ THE OTHER DIRECTION, and the one that makes the fix safe to apply.

    Verified against the REAL just-akash `runner-pool.yml`, which carries
    `- RUNNER_NAME_PREFIX=just-akash-${RUNNER_LABEL}` in its pool job. The obvious version
    of this fix would flag just-akash if its pool delegated the deploy to a script; it does
    not, and that was checked rather than assumed.
    """
    _wf(tmp_path, "runner-pool.yml", """
name: pool
on:
  workflow_call:
    inputs:
      runner-label: {required: true, type: string}
jobs:
  pool:
    runs-on: ubuntu-latest
    steps:
      - run: |
          cat > /tmp/sdl.yaml <<'SDL'
                - RUNNER_NAME_PREFIX=just-akash-${RUNNER_LABEL}
          SDL
""")
    r = _run(tmp_path)
    assert r.returncode == 0, (
        f"the real provider shape lost its exemption (exit {r.returncode}) — the fix must "
        f"kill the decoy WITHOUT flagging just-akash.\n{r.stdout}{r.stderr}"
    )
