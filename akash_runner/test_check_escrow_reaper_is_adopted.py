"""The scope predicate, and the three things it must NOT pull into scope.

★ The gap this closes: the rule reported "creates no Akash deployments — nothing to leak"
against `Borduas-Holdings/blazing`, which held 85 active deployments on 2026-09-03. It
installs the CLI into a variable and invokes that (`JA="uvx --from git+… just-akash"`,
then `$JA deploy`), and creates the rest by delegating to `runner-pool.yml`. Neither
shape matched the literal.

⚠ AND THE MISS OUTLIVED THE FIX IT WAS HIDING. blazing adopted the reaper the same day;
deleting that adoption again produced the identical verdict, rc=0. The repo this rule most
concerns had no guard before OR after — which is the "ratified mechanism with zero
executions" shape, occurring inside the guard written to prevent it.

⛔ THE HARD PART IS NOT DETECTION. This rule is ENFORCING, so a false positive fails a repo
for not adopting an Akash reaper it has no reason to own. The three below are each tested,
because a rule that cries on them gets exempted rather than fixed:
a variable holding some OTHER tool, a read-only command, and a repo that deploys nothing.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

RULE = Path(__file__).resolve().parent / "check_escrow_reaper_is_adopted.py"

ADOPTION = (
    "    uses: Digital-Frontier-LDA/akash-github-runner/.github/workflows/"
    "reusable-akash-escrow-reaper.yml@" + "a" * 40 + "\n"
)


def _run(d: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(RULE), str(d)], capture_output=True, text=True, timeout=60
    )


def _wf(d: Path, name: str, body: str) -> None:
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(body)


def _in_scope(res: subprocess.CompletedProcess) -> bool:
    """The rule prints NOT APPLICABLE when, and only when, it judged nothing."""
    return "NOT APPLICABLE" not in res.stdout


# ── the shapes that DO create deployments ────────────────────────────────────

def test_the_literal_still_counts(tmp_path):
    _wf(tmp_path, "a.yml", "jobs:\n  x:\n    steps:\n      - run: just-akash deploy --sdl s\n")
    assert _in_scope(_run(tmp_path))


def test_a_variable_holding_the_cli_counts(tmp_path):
    """blazing's shape, and the one that was invisible."""
    _wf(
        tmp_path,
        "a.yml",
        'jobs:\n  x:\n    steps:\n      - run: |\n'
        '          JA="uvx --from git+https://github.com/Digital-Frontier-LDA/just-akash@main just-akash"\n'
        "          $JA deploy --sdl /tmp/sdl.yaml\n",
    )
    assert _in_scope(_run(tmp_path))


def test_the_braced_and_array_forms_count(tmp_path):
    """`${JA} deploy` and `"${JA[@]}" deploy` — the second is how just-akash's own
    runner-pool invokes it, so a rule blind to it is blind to the mechanism repo."""
    _wf(
        tmp_path,
        "a.yml",
        "jobs:\n  x:\n    steps:\n      - run: |\n"
        "          JA=(uvx --from git+https://x/just-akash@main just-akash)\n"
        '          "${JA[@]}" deploy --sdl /tmp/sdl.yaml\n',
    )
    assert _in_scope(_run(tmp_path))


def test_delegated_creation_counts(tmp_path):
    """A repo whose deployments all come from the pool still spends escrow, and leaks it
    when the pool's own teardown does not run — which is what this reaper backstops."""
    _wf(
        tmp_path,
        "a.yml",
        "jobs:\n  pool:\n    uses: Digital-Frontier-LDA/just-akash/.github/workflows/"
        "runner-pool.yml@" + "b" * 40 + "\n",
    )
    assert _in_scope(_run(tmp_path))


# ── the shapes that MUST NOT ─────────────────────────────────────────────────

def test_a_variable_holding_another_tool_is_not_in_scope(tmp_path):
    """⛔ THE REASON THE PREDICATE IS TWO STATEMENTS AND NOT ONE. A bare `$VAR deploy`
    matches `$KUBECTL deploy`, and this rule is ENFORCING — a repo deploying something
    that is not Akash would be failed for not adopting an Akash escrow reaper."""
    _wf(
        tmp_path,
        "a.yml",
        "jobs:\n  x:\n    steps:\n      - run: |\n"
        "          KUBECTL=/usr/local/bin/kubectl\n"
        "          $KUBECTL deploy -f manifest.yaml\n",
    )
    assert not _in_scope(_run(tmp_path))


def test_a_read_only_command_is_not_in_scope(tmp_path):
    """`balance`, `list` and `tag` read or annotate. Holding the CLI is not creating."""
    _wf(
        tmp_path,
        "a.yml",
        "jobs:\n  x:\n    steps:\n      - run: |\n"
        '          JA="uvx --from git+https://x/just-akash@main just-akash"\n'
        "          $JA list --json\n",
    )
    assert not _in_scope(_run(tmp_path))


def test_a_commented_out_deploy_is_not_in_scope(tmp_path):
    """A comment is not evidence, in either direction — the rule's own stated principle."""
    _wf(
        tmp_path,
        "a.yml",
        "jobs:\n  x:\n    steps:\n      - run: |\n"
        "          # JA=\"uvx --from git+https://x/just-akash@main just-akash\"\n"
        "          # $JA deploy --sdl /tmp/sdl.yaml\n"
        "          echo nothing\n",
    )
    assert not _in_scope(_run(tmp_path))


# ── and the verdict, once in scope ───────────────────────────────────────────

def test_a_creator_without_an_adoption_fails(tmp_path):
    """Anti-vacuity for everything above: being in scope has to mean something."""
    _wf(
        tmp_path,
        "a.yml",
        "jobs:\n  x:\n    steps:\n      - run: |\n"
        '          JA="uvx --from git+https://x/just-akash@main just-akash"\n'
        "          $JA deploy --sdl /tmp/sdl.yaml\n",
    )
    res = _run(tmp_path)
    assert res.returncode != 0, res.stdout
    assert "::error" in res.stdout


def test_a_creator_with_an_adoption_passes(tmp_path):
    """⚠ The creating workflow must also STAMP the declared prefix, and that is the rule
    working rather than an awkward fixture: a `placement-prefix` appearing nowhere else in
    the repo is an inert reaper, which the rule's own input docs call worse than an absent
    one. So the fixture stamps `mine-runner`, exactly as a real consumer's SDL would."""
    _wf(
        tmp_path,
        "a.yml",
        "jobs:\n  x:\n    steps:\n      - run: |\n"
        '          JA="uvx --from git+https://x/just-akash@main just-akash"\n'
        "          cat > /tmp/sdl.yaml <<SDL\n"
        "          profiles:\n            placement:\n              mine-runner:\n"
        "          SDL\n"
        "          $JA deploy --sdl /tmp/sdl.yaml\n",
    )
    _wf(tmp_path, "reaper.yml", "jobs:\n  reap:\n" + ADOPTION + "    with:\n      placement-prefix: mine-\n")
    res = _run(tmp_path)
    assert res.returncode == 0, res.stdout + res.stderr
