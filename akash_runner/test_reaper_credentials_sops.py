"""credentials-sops on both reaper reusables.

Digital-Frontier-LDA callers may not pass secrets.AKASH_API_KEY / secrets.GH_RUNNER_PAT
(df-cicd baseline, secrets-only-sops). Pin the opt-in shape: ciphertext only, from the
caller's exact revision, decrypted by just-akash's sops-env at a pinned SHA, before the
step that reads it, and a direct secret still wins.
"""

from pathlib import Path

import yaml

WF = Path(__file__).resolve().parents[1] / ".github/workflows"
CALLER = {
    "ref": "${{ github.sha }}",
    "path": ".akash-runner-credentials",
    "sparse-checkout": "secrets/akash-runner.sops.env",
    "sparse-checkout-cone-mode": False,
    "persist-credentials": False,
}


def _check(name, loader_ref, reader_id, reader_key, expected):
    doc = yaml.safe_load((WF / name).read_text())
    call = doc[True]["workflow_call"]
    assert call["inputs"]["credentials-sops"]["default"] is False
    assert call["secrets"]["CREDENTIALS_AGE_KEY"]["required"] is False
    steps = doc["jobs"]["reap"]["steps"]
    names = [s.get("name") for s in steps]
    caller = names.index("Check out the caller encrypted runner credentials")
    loader = names.index("Check out the pinned just-akash SOPS loader")
    load = names.index("Load the caller runner credentials from SOPS")
    reader = next(i for i, s in enumerate(steps) if s.get("id") == reader_id)
    assert caller < loader < load < reader
    for i in (caller, loader, load):
        assert steps[i]["if"] == "inputs.credentials-sops"
    assert steps[caller]["with"] == CALLER
    assert steps[loader]["with"]["repository"] == "Digital-Frontier-LDA/just-akash"
    assert steps[loader]["with"]["ref"] == loader_ref
    assert steps[loader]["with"]["persist-credentials"] is False
    assert steps[load]["uses"] == "./.just-akash/.github/actions/sops-env"
    assert steps[load]["with"]["age-key"] == "${{ secrets.CREDENTIALS_AGE_KEY }}"
    assert steps[reader]["env"][reader_key] == expected
    return steps, names


def test_escrow_reaper():
    steps, names = _check(
        "reusable-akash-escrow-reaper.yml",
        "${{ inputs.just-akash-ref }}",
        "sweep",
        "AKASH_API_KEY",
        "${{ secrets.AKASH_API_KEY || env.AKASH_API_KEY }}",
    )
    # The 40-hex ref check runs before the loader is checked out at that ref.
    assert names.index("Install just-akash at the pinned ref") < names.index(
        "Check out the pinned just-akash SOPS loader"
    )


def test_stale_runner_reaper():
    steps, names = _check(
        "reusable-stale-runner-reaper.yml",
        "${{ inputs.sops-loader-ref }}",
        "reap",
        "GH_TOKEN",
        "${{ secrets.runner-pat || env.GH_RUNNER_PAT }}",
    )
    guard = names.index("Require a pinned SOPS loader")
    assert steps[guard]["if"] == "inputs.credentials-sops"
    assert guard < names.index("Check out the pinned just-akash SOPS loader")
