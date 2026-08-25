#!/usr/bin/env python3
"""One definition of "this repo re-derived a verdict instead of consuming the primitive".

⭐ WHY A REGISTRY AND NOT A SECOND COPY OF THE FUNDING RULE.

`check_funding_gate_is_not_re_derived.py` was written for ONE primitive. The defect it
names is not about funding: it is about a consumer computing a verdict from raw numbers
when a shared primitive already answers the question. That shape recurs per cloud —

    funding   Console credit / DepositAuthorization   ->  akash-lease-core.evaluate_funding
    capacity  cluster allocatable vs requests         ->  gke-capacity-preflight

— and copying the rule per cloud is the same mistake one level up: two definitions of the
same defect, drifting apart, each fixed once.

⚠ THE CROSS-CUTTING ANTI-PATTERN IS THE POINT. Every gate in this registry is checked for
`collapses-unknown-into-declined` — reporting "no funds"/"no room" when the INSTRUMENT
failed. That is #1113, it has now been observed on three separate artefacts across two
clouds, and it is invisible to a per-cloud rule because each author sees it once.

SCOPE, inherited from the funding rule and load-bearing: a block is in scope only when it
both READS the quantity AND DECIDES on it. Printing a number for a human is not a gate,
and demanding the primitive of a diagnostic is noise that trains readers to dismiss the
rule.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

_WC_SPEC = importlib.util.spec_from_file_location(
    "akash_runner_workflow_corpus",
    Path(__file__).resolve().parent / "workflow_corpus.py",
)
assert _WC_SPEC and _WC_SPEC.loader
_wc = importlib.util.module_from_spec(_WC_SPEC)
sys.modules[_WC_SPEC.name] = _wc
_WC_SPEC.loader.exec_module(_wc)

run_blocks = _wc.run_blocks


@dataclass(frozen=True)
class Gate:
    """One (question, primitive) pair and how to recognise a local re-derivation of it."""

    name: str
    question: str
    primitive: str
    markers: tuple[str, ...]
    reads: tuple[re.Pattern[str], ...]
    decides: tuple[re.Pattern[str], ...]
    antipatterns: dict[str, tuple[re.Pattern[str], str]] = field(default_factory=dict)


# ⚠ Applies to EVERY gate. Kept here rather than in either gate so it cannot be fixed in
# one cloud and left in the other.
SHARED_ANTIPATTERNS: dict[str, tuple[re.Pattern[str], str]] = {
    "collapses-unknown-into-declined": (
        # A non-zero rc / an error path that reports the SHORTAGE vocabulary. The tell is
        # a failure branch whose message asserts a measured conclusion.
        re.compile(
            r"(\|\|\s*(true|:)\s*(;|$)[\s\S]{0,200}?(no[\s_-]?(funds|room|capacity|credit|slot))"
            r"|(catch|except|error|fail)[\s\S]{0,120}?(no[\s_-]?(funds|room|capacity|credit|slot))"
            r"|rc[^\n]{0,40}(!=|-ne)[^\n]{0,10}0[\s\S]{0,160}?(no[\s_-]?(funds|room|capacity|credit|slot)))",
            re.I,
        ),
        "reports a SHORTAGE on a path that an instrument FAILURE also reaches. "
        '"could not measure" and "measured: none left" are different states; saying the '
        "second when the first happened asserts a conclusion from a broken instrument "
        "(#1113). Emit a distinct message per state.",
    ),
}


FUNDING = Gate(
    name="funding",
    question="can this account fund a create?",
    primitive="akash-lease-core.evaluate_funding",
    markers=("akash-lease-core", "akash_lease_core", "evaluate_funding"),
    reads=(
        re.compile(r"spend_limits?\b"),
        re.compile(r"deploy_credit\b"),
        # ⚠ NO leading \b: `_` is a word character, so `\ballowance\b` misses
        # `read_allowance` / `get_allowance`.
        re.compile(r"allowance", re.I),
        re.compile(r"locked_in_escrow_uact\b"),
    ),
    decides=(
        re.compile(r"\bMIN_UACT\b"),
        re.compile(r"-lt\b|-le\b|-gt\b|-ge\b"),
        re.compile(r"\bexit\s+1\b"),
        re.compile(r"::error"),
    ),
    antipatterns={
        "extrapolates-a-step-function": (
            # ⚠ WORD BOUNDARIES ARE NOT COSMETIC. Bare `rate` matched "delibeRATEly"
            # inside an echo string on the real artefact — a correct verdict reached by a
            # wrong route. Prefer identifier-shaped tokens.
            re.compile(
                r"(projected?_[a-z]|projection|extrapolat|\bslope\b|per[_-]second"
                r"|\brate\b|delta\s*\*|\*\s*[A-Z_]*HORIZON|/\s*[A-Z_]*GAP)",
                re.I,
            ),
            "projects a rate from samples. The allowance moves in whole deposits: 30/39 "
            "intervals flat, every delta an integer multiple of 5.00 ACT. Two samples "
            "cannot tell a step from a slope; ~24% of prechecks refuse on the artefact.",
        ),
        "gates-on-console-deploy-credit": (
            re.compile(r"deploy_credit"),
            "gates on Console deploy_credit, which does not gate a create. The on-chain "
            "DepositAuthorization does. Reading one while meaning the other cost a day of "
            "provider-capacity investigation for an allowance problem.",
        ),
        "reads-the-singular-spend-limit": (
            re.compile(r"spend_limit\b(?!s)"),
            "reads the SINGULAR spend_limit, which is uakt:0 on a funded account. The "
            "uact figure is under spend_limits (PLURAL).",
        ),
        "sums-slots-instead-of-max": (
            re.compile(r"\b(sum|total)\b.*\bslot", re.I),
            "aggregates slots. A create draws its deposit from ONE account, so the gate "
            "must read max(SLOT); a sum authorises a create no single slot can fund.",
        ),
    },
)


CAPACITY = Gate(
    name="capacity",
    question="will another workload fit in this cluster?",
    primitive="df-cicd/.github/actions/gke-capacity-preflight",
    markers=(
        "gke-capacity-preflight",
        "gke_capacity_preflight",
    ),
    reads=(
        re.compile(r"kubectl\s+(get|describe)\s+nodes?\b"),
        re.compile(r"kubectl\s+top\b"),
        re.compile(r"\ballocatable\b", re.I),
        # ⛔ CO-OCCURRENCE, NOT THE BARE TOKEN. `resources.requests.cpu` on its own is
        # how you AUTHOR a manifest, not how you read capacity. Measured: the bare
        # pattern fired on Blazing-Back's canary-deploy, whose match was a yq assignment
        # — `(.spec.template.spec.containers[] | select(.name == "api")
        # | .resources.requests.cpu) = "100m"` — setting the canary's own request. The
        # `-lt` / `exit 1` / `::error` that satisfied the DECIDES limb were unrelated
        # error handling in the same block.
        #
        # ⚠ And the false positive was nearly invisible: with the preflight wired, that
        # job becomes `needs:`-exempt, so the rule went green and the before/after looked
        # like proof the rule worked. The count agreed with the story; only PRINTING THE
        # MATCH showed the story was wrong. Require the request read to sit near an
        # actual cluster query.
        re.compile(
            r"kubectl\s+get\s+pods?[\s\S]{0,400}?(resources\.requests|requests\.(cpu|memory))"
        ),
        re.compile(r"Insufficient\s+(cpu|memory)", re.I),
        re.compile(r"\bunschedulable\b", re.I),
    ),
    decides=(
        re.compile(r"-lt\b|-le\b|-gt\b|-ge\b"),
        re.compile(r"\bexit\s+1\b"),
        re.compile(r"::error"),
        re.compile(r"\bMIN_[A-Z_]*(CPU|MEM|HEADROOM|CAPACITY)"),
    ),
    antipatterns={
        "gates-on-utilisation-not-requests": (
            re.compile(r"kubectl\s+top\b|cpu(_|-)?(percent|pct|util)", re.I),
            "gates on UTILISATION. Kubernetes admits a pod by comparing REQUESTS to "
            "allocatable and never reads utilisation, so this is wrong in both "
            "directions: a 95%-utilised cluster whose pods request little schedules "
            "fine, and a 30%-utilised one with its requests committed cannot.",
        ),
        "counts-pods-instead-of-measuring-headroom": (
            # A count of canary-ish objects compared against a threshold.
            re.compile(
                r"(wc\s+-l|--no-headers[\s\S]{0,80}?\|\s*wc|\bcount\b)[\s\S]{0,120}?"
                r"(-gt|-ge|-lt|-le)",
                re.I,
            ),
            "thresholds a COUNT of pods/deployments. A count is not a population: 12 "
            "canaries on a large cluster is fine and 4 on a full one is an outage. The "
            "gate must be a headroom FRACTION of allocatable.",
        ),
        "ignores-the-autoscaler-ceiling": (
            # Reads allocatable but never the pool max — judging on current scale only.
            re.compile(r"\ballocatable\b(?![\s\S]*max[_-]?node)", re.I),
            "judges on CURRENT allocatable without reading the autoscaler ceiling. If "
            "the pool can still grow, today's allocatable understates the room and the "
            "gate blocks every run on a small-but-growable cluster. The ceiling is the "
            "DENOMINATOR (current + Σ (max_nodes − current) × per_node), not a separate "
            "signal.",
        ),
    },
)


GATES: dict[str, Gate] = {g.name: g for g in (FUNDING, CAPACITY)}


def jobs_reaching_primitive(path: Path, gate: Gate) -> set[str]:
    """Job ids whose verdict comes from the primitive — DIRECTLY or via `needs:`.

    ⛔ WHY THIS IS NOT A PER-`run:`-BLOCK CHECK, measured. The first version matched the
    exemption markers against the `run:` block alone and fired on Blazing-Back's
    `canary-deploy` — a job that DOES consume the primitive, through
    `${{ needs.gke-capacity-preflight.outputs.capacity_ok }}` bound in the step's `env:`.
    The marker is real and is simply not inside the script text.

    ⚠ That false positive lands on precisely the SAFE design. Running the preflight in
    its own job and consuming its output is what stops a broken preflight from skipping a
    required check; inlining the script in the consumer is the shape we tell people to
    avoid. A rule that reds the recommended design and passes the discouraged one is worse
    than no rule — it trains readers to dismiss it.

    ⇒ Exemption is a property of the JOB, closed transitively over `needs:`. It is
    deliberately NOT file-level: an unrelated job in the same file that re-derives the
    verdict has no `needs:` edge to the primitive and stays in scope."""
    try:
        doc = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return set()
    if not isinstance(doc, dict):
        return set()
    jobs = doc.get("jobs") or {}
    if not isinstance(jobs, dict):
        return set()

    direct: set[str] = set()
    needs: dict[str, list[str]] = {}
    for job_id, job in jobs.items():
        if not isinstance(job, dict):
            continue
        try:
            blob = yaml.safe_dump(job, default_flow_style=False)
        except Exception:  # noqa: BLE001
            blob = str(job)
        if any(m in blob for m in gate.markers):
            direct.add(job_id)
        raw_needs = job.get("needs") or []
        needs[job_id] = [raw_needs] if isinstance(raw_needs, str) else list(raw_needs)

    # Transitive closure: a job that depends on a reaching job reaches it too.
    reaching = set(direct)
    changed = True
    while changed:
        changed = False
        for job_id, deps in needs.items():
            if job_id not in reaching and any(d in reaching for d in deps):
                reaching.add(job_id)
                changed = True
    return reaching


def audit_gate(path: Path, gate: Gate) -> list[str]:
    """Findings for ONE gate over one workflow file."""
    problems: list[str] = []
    exempt = jobs_reaching_primitive(path, gate)
    for blk in run_blocks(path):
        code = blk.code
        if not any(p.search(code) for p in gate.reads):
            continue
        if not any(p.search(code) for p in gate.decides):
            continue  # reads but does not decide — reporting, not gating
        if blk.job_id in exempt or any(m in code for m in gate.markers):
            continue  # routed through the primitive, directly or via `needs:`
        named = {**gate.antipatterns, **SHARED_ANTIPATTERNS}
        hits = [f"{n}: {why}" for n, (pat, why) in named.items() if pat.search(code)]
        detail = "; ".join(hits) if hits else "no named anti-pattern, but the decision is local"
        problems.append(
            f"{path.name}: job '{blk.job_id}' DECIDES {gate.name} "
            f"({gate.question}) from raw values without {gate.primitive}. {detail}"
        )
    return problems


def audit(path: Path, gates: list[Gate]) -> list[str]:
    out: list[str] = []
    for g in gates:
        out.extend(audit_gate(path, g))
    return out
