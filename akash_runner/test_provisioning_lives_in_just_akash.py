"""Controls for "runner provisioning workflows live ONLY in just-akash" — df-wiki §1.

⛔ THE GAP THIS RULE CLOSES (df-wiki#222, gap G1). `content/platform/akash-github-runners.md`
§1 mandates that runner provisioning workflows live only in `just-akash`, consumed via
`uses:` at a pinned tag, and that "a repo-local `akash-runner.yml` is a defect, not a
customisation". Its opening sentence — "Two repos independently grew an `akash-runner.yml`"
— is STILL TRUE on both mains, and the obvious explanation (they cannot adopt) is refuted:
Blazing-Back runs this conformance suite today, cross-org, at pin a49af714. A repo can run
every rule the suite has and still violate the standard's first mandate, because no rule
checked it. This is that rule.

⛔ THE DETECTION IS CAPABILITY, NOT FILENAME. Measured 2026-08-29 on origin/main: the
defect ships as `ci.yml`/`e2e-tests.yml`-shaped names too — a finder keyed to the string
`akash-runner.yml` is disarmed by a rename (the fleet has a memory entry for exactly that).
What the rule matches is runner-REGISTRATION machinery in comment-stripped `run:` text,
reusing the discriminator `check_dereg_backstop` measured across the fleet.

★ FIXTURES BELOW ARE QUOTED FROM THE ARTEFACTS, not paraphrased:
  * BLAZING_LOCAL   — blazing/.github/workflows/akash-runner.yml @1083b71e (lines 286-291)
  * TIME_TO_READY   — Blazing-Back runner-time-to-ready.yml @a5eb173e (lines 150-155)
  * CIPR_COMMENTS   — Blazing-Back ci-pr.yml @a5eb173e — a measured FALSE-POSITIVE shape:
                      the image names appear only in full-line COMMENTS
  * REAPER          — df-cicd reusable-stale-runner-reaper.yml @1d2e7fe (lines 109/159)
  * USES_CALLER     — blazing ci.yml's real pin 017b9e0be467f7ea171ebd01d3ff760886d39844
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from akash_runner.check_dereg_backstop import CREATES_REGISTRATIONS  # noqa: E402
from akash_runner.check_provisioning_lives_in_just_akash import (  # noqa: E402
    check_directory,
    main,
)
from akash_runner.workflow_corpus import run_blocks  # noqa: E402
from conformance_exit import NOT_JUDGEABLE  # noqa: E402

PUBLISHER = "Digital-Frontier-LDA/just-akash"
CONSUMER = "Borduas-Holdings/blazing"

# blazing/.github/workflows/akash-runner.yml @1083b71e — the `image:`/`env:` lines are
# verbatim (sha256:7509763af... is the real digest floor pin).
BLAZING_LOCAL = """
on:
  workflow_dispatch:
jobs:
  deploy-runner:
    runs-on: ubuntu-latest
    steps:
      - run: |
          cat > runner.sdl.yaml <<'SDL'
          services:
            runner:
              image: ghcr.io/akash-network/github-runner@sha256:7509763af8209796f3e7fde5fb536c742075ec1a59ad1b36e3c9c27bc3bafc67
              env:
                - ACCESS_TOKEN=${GH_RUNNER_PAT}
                - ORG_NAME=Borduas-Holdings
                - RUNNER_SCOPE=org
                - RUNNER_NAME_PREFIX=df-flow-${RUNNER_LABEL}
          SDL
          uv tool run just-akash deploy --sdl runner.sdl.yaml
"""

# Blazing-Back runner-time-to-ready.yml @a5eb173e:150-155 — a SECOND inline provisioner,
# proving the class is not one file.
TIME_TO_READY = """
on:
  workflow_dispatch:
jobs:
  probe:
    runs-on: ubuntu-latest
    steps:
      - run: |
          cat > probe.sdl.yaml <<'SDL'
          services:
            runner:
              image: myoung34/github-runner:2.336.0-ubuntu-jammy@sha256:8eeec3e8a4e21c229057cc4b4ba46a22d5ff24217ca6f0d984cf9be168be6520
              env:
                - ACCESS_TOKEN=${GH_RUNNER_PAT}
                - RUNNER_SCOPE=org
                - RUNNER_NAME_PREFIX=df-core-${RUNNER_LABEL}
          SDL
"""

# Blazing-Back ci-pr.yml @a5eb173e — the image names appear ONLY in full-line comments
# inside the run block. Measured: a rule that matches comments flags this file.
CIPR_COMMENTS = """
on:
  pull_request:
jobs:
  plan:
    runs-on: ubuntu-latest
    steps:
      - run: |
          # names a recognized runner repository (myoung34/github-runner, or legacy
          # ghcr.io/akash-network/github-runner); (3) profiles.placement carries the
          echo "selecting provider profile"
"""

# df-cicd reusable-stale-runner-reaper.yml @1d2e7fe:109,159 — verbatim. Touching the org
# runner API to DELETE is reaping, not registering.
REAPER = """
on:
  schedule:
    - cron: "17 * * * *"
jobs:
  reap:
    runs-on: ubuntu-latest
    steps:
      - run: |
          gh api --paginate "orgs/${ORG}/actions/runners?per_page=100" \\
            --jq '.runners[] | select(.status=="offline" and .busy==false) | "\\(.id)\\t\\(.name)"'
          gh api -X DELETE "orgs/${ORG}/actions/runners/${id}" >/dev/null 2>&1
"""

# blazing ci.yml's real, compliant consumption: job-level uses: at a 40-hex pin.
USES_CALLER = """
on:
  pull_request:
jobs:
  pool:
    uses: Digital-Frontier-LDA/just-akash/.github/workflows/runner-pool.yml@017b9e0be467f7ea171ebd01d3ff760886d39844
  work:
    needs: [pool]
    runs-on: ubuntu-latest
    steps:
      - run: pytest
"""

CALLABLE_BUT_LOCAL = BLAZING_LOCAL.replace(
    "on:\n  workflow_dispatch:",
    "on:\n  workflow_call:\n    inputs:\n      runner-label:\n        required: true\n        type: string\n  workflow_dispatch:",
)


def _dir(root: Path, repo: str | None, **files: str):
    """Write fixtures as a repo layout and judge its workflows dir."""
    workflows = root / ".github" / "workflows"
    workflows.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (workflows / name).write_text(text)
    return check_directory(workflows, repo=repo)


# --------------------------------------------------------------------------- #
# Anti-vacuity control: the fixtures must carry the signal the rule matches,
# or every test below measures nothing (a finder keyed to a drifting string
# disarms itself; pin the fixtures against the pattern directly).
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("fixture", [BLAZING_LOCAL, TIME_TO_READY], ids=["blazing", "ttr"])
def test_the_machinery_fixtures_actually_carry_the_signal(tmp_path, fixture):
    path = tmp_path / "w.yml"
    path.write_text(fixture)
    blocks = run_blocks(path)
    assert blocks, "fixture produced no run blocks — the corpus moved"
    assert any(CREATES_REGISTRATIONS.search(b.code) for b in blocks), (
        "the imported creation marker no longer matches the real machinery lines — "
        "the rule is now blind to the defect it exists to catch"
    )


@pytest.mark.parametrize("fixture", [CIPR_COMMENTS, REAPER, USES_CALLER], ids=["comments", "reaper", "uses"])
def test_the_known_negative_fixtures_carry_no_signal_in_code(tmp_path, fixture):
    path = tmp_path / "w.yml"
    path.write_text(fixture)
    assert not any(CREATES_REGISTRATIONS.search(b.code) for b in run_blocks(path)), (
        "a known-negative fixture matches the marker in comment-stripped code — either "
        "the fixture drifted from the artefact or the pattern widened"
    )


# --------------------------------------------------------------------------- #
# The rule.
# --------------------------------------------------------------------------- #


def test_a_repo_local_provisioning_workflow_is_a_finding(tmp_path):
    """★ blazing's akash-runner.yml on main today: the shape df-wiki#222 names."""
    findings = _dir(tmp_path, CONSUMER, **{"akash-runner.yml": BLAZING_LOCAL})
    assert any(
        "akash-runner.yml" in f and "just-akash" in f for f in findings
    ), f"expected a finding naming the file and the canonical home: {findings}"


def test_a_second_provisioning_file_is_flagged_independently(tmp_path):
    """The class is not one file — Blazing-Back carries a second inline provisioner."""
    findings = _dir(
        tmp_path,
        "Borduas-Holdings/Blazing-Back",
        **{"akash-runner.yml": BLAZING_LOCAL, "runner-time-to-ready.yml": TIME_TO_READY},
    )
    assert any("runner-time-to-ready.yml" in f for f in findings), findings
    assert any("akash-runner.yml" in f for f in findings), findings


def test_the_finding_cites_the_line_of_the_machinery(tmp_path):
    """A finding that names a file but not a place makes the reader re-derive it."""
    findings = _dir(tmp_path, CONSUMER, **{"akash-runner.yml": BLAZING_LOCAL})
    assert any("akash-runner.yml:" in f for f in findings), findings


def test_callable_does_not_exempt_a_repo_local_copy(tmp_path):
    """★★ THE EXEMPTION IS IDENTITY, NOT STRUCTURE. blazing's akash-runner.yml IS
    `workflow_call` today — if being callable sufficed, the defect the standard was
    written about would pass. df-wiki#222 asks whether the mandate should narrow for
    this case; until it does, the rule reports it."""
    findings = _dir(tmp_path, CONSUMER, **{"akash-runner.yml": CALLABLE_BUT_LOCAL})
    assert any("akash-runner.yml" in f for f in findings), findings


def test_the_publisher_is_exempt(tmp_path):
    """just-akash's runner-pool.yml carries the same machinery BY DESIGN — it is the one
    place the mandate allows it. Identity is case-insensitive (GitHub slugs are)."""
    for slug in (PUBLISHER, PUBLISHER.lower()):
        findings = _dir(tmp_path / slug.replace("/", "_"), slug, **{"runner-pool.yml": BLAZING_LOCAL})
        assert findings == [], f"{slug}: {findings}"


def test_an_unidentified_repo_cannot_claim_the_exemption(tmp_path):
    """Fail-closed: with no repo identity the machinery is reported. In CI the slug is
    platform-set (GITHUB_* cannot be overridden); absence means a local run that did
    not say what it is — and the common case is a consumer, not the publisher."""
    findings = _dir(tmp_path, None, **{"runner-pool.yml": BLAZING_LOCAL})
    assert findings, "machinery with no repo identity reported nothing"


def test_comments_about_runner_images_are_not_provisioning(tmp_path):
    """★ MEASURED FALSE POSITIVE, pinned. Blazing-Back ci-pr.yml names both runner images
    in full-line comments; a rule reading comments reds a consumer's main CI file for
    prose."""
    findings = _dir(tmp_path, "Borduas-Holdings/Blazing-Back", **{"ci-pr.yml": CIPR_COMMENTS})
    assert findings == [], findings


def test_a_compliant_uses_caller_passes(tmp_path):
    """The mandated shape: job-level `uses:` of the canonical pool at a pinned ref.
    A caller has no run-text machinery, so it must produce no finding."""
    findings = _dir(tmp_path, CONSUMER, **{"ci.yml": USES_CALLER})
    assert findings == [], findings


def test_a_reaper_is_not_a_provisioner(tmp_path):
    """Touching the org runner API to DELETE is not registering — the discriminator the
    dereg rule measured, held here too, or the repo that ships the backstop fails."""
    findings = _dir(tmp_path, "Digital-Frontier-LDA/df-cicd", **{"reusable-stale-runner-reaper.yml": REAPER})
    assert findings == [], findings


def test_minting_a_registration_token_directly_is_provisioning(tmp_path):
    """The second creation route from the measured marker set."""
    wf = """
on:
  workflow_dispatch:
jobs:
  mint:
    runs-on: ubuntu-latest
    steps:
      - run: gh api -X POST repos/${{ github.repository }}/actions/runners/registration-token
"""
    findings = _dir(tmp_path, CONSUMER, **{"mint.yml": wf})
    assert any("mint.yml" in f for f in findings), findings


def test_machinery_delegated_to_a_script_is_seen(tmp_path):
    """⛔ DELEGATION BLINDNESS bit the dereg rule (blazing's reaper is `bash scripts/...`).
    A provisioner that hides its SDL in a script is the same shape pointed the other way."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "provision.sh").write_text(
        "cat > r.sdl <<'SDL'\n"
        "  image: ghcr.io/akash-network/github-runner@sha256:7509763af8209796f3e7fde5fb536c742075ec1a59ad1b36e3c9c27bc3bafc67\n"
        "SDL\n"
    )
    wf = "on:\n  push:\njobs:\n  p:\n    steps:\n      - run: bash scripts/provision.sh\n"
    findings = _dir(tmp_path, CONSUMER, **{"provision.yml": wf})
    assert any("provision.yml" in f and "provision.sh" in f for f in findings), findings


def test_a_delegated_script_that_only_COMMENTS_about_prefixes_is_not_provisioning(tmp_path):
    """★ blazing's registration reaper, verbatim comment line — the measured delegated FP."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "akash-runner-reaper.sh").write_text(
        "# RUNNER_NAME_PREFIX values misses that, which is how it got in. Resolve values built at\n"
        'gh api -X DELETE "orgs/${ORG}/actions/runners/${id}"\n'
    )
    wf = (
        "on:\n  schedule:\n    - cron: '5 * * * *'\n"
        "jobs:\n  reap:\n    steps:\n      - run: bash scripts/akash-runner-reaper.sh\n"
    )
    findings = _dir(tmp_path, CONSUMER, **{"akash-runner-registration-reaper.yml": wf})
    assert findings == [], findings


def test_an_unreadable_delegation_in_a_runner_adjacent_workflow_is_reported(tmp_path):
    """Unreadable is not empty — but only where the workflow already shows machinery;
    unconditionally reported, this measured 4 false findings across two repos."""
    wf = BLAZING_LOCAL + "      - run: bash scripts/missing.sh\n"
    findings = _dir(tmp_path, CONSUMER, **{"akash-runner.yml": wf})
    assert any("missing.sh" in f and "could not be read" in f for f in findings), findings


def test_an_unreadable_delegation_in_a_clean_workflow_is_NOT_a_finding(tmp_path):
    wf = "on:\n  push:\njobs:\n  t:\n    steps:\n      - run: bash scripts/missing.sh\n"
    findings = _dir(tmp_path, CONSUMER, **{"ci.yml": wf})
    assert findings == [], findings


# --------------------------------------------------------------------------- #
# The floor (main(), the path CI invokes — see test_no_vacuous_pass.py, which
# also runs this rule by subprocess via its DIR_CHECKERS list).
# --------------------------------------------------------------------------- #


def test_main_reports_NOT_JUDGEABLE_on_an_empty_population(tmp_path, capsys):
    """★★ THE FLOOR, third-state form: 'I found nothing to check' is not 'you comply',
    and since #35 it is also not a DEFECT — it is NOT-JUDGEABLE (3)."""
    rc = main([str(tmp_path)])
    out = capsys.readouterr()
    assert rc == NOT_JUDGEABLE
    assert rc != 0
    assert "found 0 WORKFLOW documents" in (out.out + out.err)


def test_main_passes_a_benign_workflow_and_says_what_it_examined(tmp_path, capsys):
    (tmp_path / "ci.yml").write_text(
        "on:\n  push:\njobs:\n  t:\n    steps:\n      - run: pytest\n"
    )
    rc = main([str(tmp_path)])
    out = capsys.readouterr()
    assert rc == 0, out.err
    assert "1 workflow file(s) examined" in out.out


def test_main_errors_on_a_missing_path(capsys):
    rc = main(["/definitely/not/here"])
    assert rc == 2
