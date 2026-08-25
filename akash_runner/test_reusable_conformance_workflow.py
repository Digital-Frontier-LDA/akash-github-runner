"""Structural tests for the reusable Akash runner conformance workflow.

The reusable workflow at .github/workflows/reusable-akash-runner-conformance.yml
is a thin YAML wrapper around ./.github/actions/akash-runner-conformance. These
tests guard the wrapper shape so a future edit cannot silently break the
workflow_call contract that consumer repos depend on.
"""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "reusable-akash-runner-conformance.yml"
ACTION_DIR = REPO_ROOT / ".github" / "actions" / "akash-runner-conformance"


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


def _action() -> dict:
    return yaml.safe_load((ACTION_DIR / "action.yml").read_text())


def _triggers(document: dict) -> dict:
    return document.get(True) or document.get("on") or {}



def test_workflow_exists_and_parses():
    document = _workflow()
    assert isinstance(document, dict), "workflow must be a YAML mapping"


def test_workflow_uses_workflow_call_trigger():
    triggers = _triggers(_workflow())
    assert "workflow_call" in triggers, (
        "reusable workflow MUST expose workflow_call so consumer repos can `uses:` it"
    )


def test_workflow_inputs_MIRROR_the_action_they_wrap():
    """The reusable must not be stricter than the action it delegates to.

    ⛔ THIS TEST USED TO ASSERT `workflow.required is True`, AND THAT PINNED A
    MISWIRING. `action.yml` declares `workflow` as `required: false, default: ""`
    and guards check_standard with `if [ -n "${WORKFLOW:-}" ]` -- i.e. the action
    already supports directory-scoped-only adoption. Requiring it HERE meant a
    consumer calling the supported path could not SELECT a mode the action
    implements.

    Measured cost on df-cicd: check_standard is ENFORCING and exits 1 on every one
    of its workflows, because that repo is neither the canonical pool nor a pool
    consumer. Requiring `workflow` forced a choice between adopting with a
    PERMANENT FALSE RED, or not adopting at all -- while 10 dir-scoped rules over
    25 workflows were sitting there, 8 passing non-vacuously and 2 reporting real
    advisory defects.

    ⚠ The property that actually matters is NOT metadata -- it is that the action
    never green-ticks without examining something. That is asserted where it is
    enforced, at runtime, by `test_conformance_action_cannot_judge_NOTHING`, which
    also covers the both-inputs-absent case `required: true` never covered at all.
    """
    triggers = _triggers(_workflow())
    inputs = (triggers.get("workflow_call") or {}).get("inputs") or {}
    action = _action().get("inputs") or {}

    assert "workflow" in inputs, "the reusable must still ACCEPT a workflow target"
    for name in ("workflow", "workflows-dir"):
        assert inputs[name].get("required") == action[name].get("required"), (
            f"reusable and action disagree on `{name}.required`: "
            f"reusable={inputs[name].get('required')} action={action[name].get('required')}. "
            "The reusable must not be stricter than the action it wraps."
        )

    assert inputs["checker-ref"].get("required") is True, (
        "checker-ref MUST stay required: a default lets the checker drift from the "
        "contract its @ pin names"
    )


def test_workflow_calls_the_conformance_action():
    """The workflow must invoke the conformance action from a checkout it CONTROLS.

    ⛔ THIS TEST USED TO PIN `./.github/actions/akash-runner-conformance`, AND THAT
    PINNED THE BUG. A reusable workflow's job runs in the CALLER's context, so a
    bare `./` resolves inside the CALLER's tree — where that directory does not
    exist in any consumer. The job could therefore never be created and every
    consumer run died with `jobs=0` (#149). Asserting the caller-relative literal
    made the broken form mandatory: green on the defect, red on the fix.

    ⇒ Assert the PROPERTY — the conformance action is invoked, by a local path —
    not the one literal that happened to be there. The companion
    `test_workflow_checks_out_akash_github_runner_itself` pins WHERE that path must come from.
    """
    jobs = _workflow().get("jobs") or {}
    assert jobs, "reusable workflow must define at least one job"
    step_uses = [
        step.get("uses")
        for job in jobs.values()
        for step in (job.get("steps") or [])
        if isinstance(step.get("uses"), str)
    ]
    local = [u for u in step_uses if u.startswith("./")]
    assert any(u.endswith("/.github/actions/akash-runner-conformance") for u in local), (
        "reusable workflow must invoke the akash-runner-conformance action by a local "
        f"path (found uses: {step_uses})"
    )
    assert not any(u == "./.github/actions/akash-runner-conformance" for u in local), (
        "a bare `./.github/actions/...` resolves inside the CALLER's tree, which has no "
        "such directory — that is #149. Check out akash-github-runner to a path and reference it "
        "from there."
    )


def test_workflow_checks_out_akash_github_runner_itself():
    """The action must come from akash-github-runner, at a revision the CALLER pins.

    Without an explicit `repository:` the checkout fetches the caller's repo, and the
    action is simply absent. And the ref cannot be derived — no context exposes a
    reusable workflow's own revision to itself (`github.workflow_*` names the CALLER's
    entry workflow; `job.*` carries only check_run_id/container/services/status), which
    is the same root as just-akash#184. So it must be a required input, or the CHECKER
    floats to a branch tip while the consumer believes their `@<sha>` governs it.
    """
    wf = _workflow()
    inputs = (_triggers(wf).get("workflow_call") or {}).get("inputs") or {}
    assert "checker-ref" in inputs, "the checker revision must be an explicit input"
    assert inputs["checker-ref"].get("required") is True, "checker-ref must be required"
    assert "default" not in inputs["checker-ref"], (
        "a default makes the CHECKER float while looking pinned from the caller's side"
    )
    steps = [s for job in (wf.get("jobs") or {}).values() for s in (job.get("steps") or [])]
    ck = [s for s in steps if isinstance(s.get("uses"), str) and "actions/checkout" in s["uses"]]
    ours = [s for s in ck if (s.get("with") or {}).get("repository", "").endswith("/akash-github-runner")]
    assert ours, f"one checkout must name akash-github-runner explicitly (found {[(s.get('with') or {}).get('repository') for s in ck]})"
    w = ours[0]["with"]
    assert "checker-ref" in str(w.get("ref", "")), "the akash-github-runner checkout must use inputs.checker-ref"
    assert w.get("path"), "the akash-github-runner checkout needs its own path so it does not clobber the caller's tree"


def test_conformance_action_is_a_composite_action():
    action = _action()
    assert action.get("runs", {}).get("using") == "composite", (
        "conformance action must be composite (it shells out to check_standard.py)"
    )


def test_conformance_action_cannot_judge_NOTHING():
    """The action must never green-tick without examining something.

    ⚠ This replaced `assert inputs["workflow"]["required"] is True`. That assertion pinned
    action METADATA, and metadata is not the property anyone cared about — a green job
    that judged nothing is. `workflow` is now optional on purpose: this repo hosts the
    reusables and has no canonical-pool consumer to point at, and several rules judge the
    DIRECTORY and need no single file. Naming a non-consumer to satisfy `required: true`
    is exactly the false claim that put a wrong target in the dogfood in the first place.

    So the guarantee is asserted where it is actually enforced — in the script, at
    runtime — instead of in a field. This is strictly stronger: it fails the build, and
    it covers the case `required: true` never did, which is BOTH inputs absent.
    """
    inputs = _action().get("inputs") or {}
    assert "workflow" in inputs, "the action must still accept a workflow path"
    assert "workflows-dir" in inputs, "the action must still accept a workflows directory"

    script = _action()["runs"]["steps"][0]["run"]
    assert 'if [ -z "${WORKFLOW:-}" ] && [ -z "${WORKFLOWS_DIR:-}" ]; then' in script, (
        "no guard rejecting the both-inputs-absent case — the action would run zero rules "
        "and exit 0, certifying a repo it never examined"
    )
    guard = script.split('if [ -z "${WORKFLOW:-}" ] && [ -z "${WORKFLOWS_DIR:-}" ]; then', 1)[1]
    guard = guard.split("fi", 1)[0]
    assert "::error" in guard, "the both-absent guard must ERROR, not warn"
    assert "exit 1" in guard, "the both-absent guard must fail the build, not merely report"
