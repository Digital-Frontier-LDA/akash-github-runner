"""Execute the actual reusable step with resolved caller context and an offline reader."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github/workflows/reusable-akash-escrow-reaper.yml"
)


def run_step(
    tmp_path,
    *,
    prefix="consumer-ci-",
    repository="example/caller",
    execute="false",
    rc=0,
    mutate=False,
):
    doc = yaml.safe_load(WORKFLOW.read_text())
    assert doc["permissions"]["actions"] == "read"
    step = next(s for s in doc["jobs"]["reap"]["steps"] if s.get("id") == "sweep")
    context = {
        "${{ inputs.execute }}": execute,
        "${{ inputs.placement-prefix }}": prefix,
        "${{ inputs.reap-owned }}": "false",
        "${{ secrets.AKASH_API_KEY }}": "offline-key",
        "${{ github.token }}": "offline-github-token",
        "${{ github.repository }}": repository,
    }
    env = {key: context[value] for key, value in step["env"].items()}
    script = step["run"].replace("/tmp/sweep.log", str(tmp_path / "sweep.log"))
    if mutate:
        needle = 'MODE+=(--ownership-register "$OWNERSHIP_REGISTER")'
        assert script.count(needle) == 1
        script = script.replace(needle, ":", 1)
    fake = tmp_path / "uv"
    fake.write_text(
        f"#!{sys.executable}\n"
        "import json,os,sys\n"
        "from pathlib import Path\n"
        "args=sys.argv[1:]\n"
        "record={'argv':args,'token':os.environ.get('GH_TOKEN')}\n"
        "Path(os.environ['CALL_RECORD']).write_text(json.dumps(record))\n"
        "if '--ownership-register' not in args: raise SystemExit(2)\n"
        "register=json.loads(args[args.index('--ownership-register')+1])\n"
        "assert register==json.loads(os.environ['EXPECTED_REGISTER'])\n"
        "assert record['token']=='offline-github-token'\n"
        "print('stale (closable): 0')\n"
        "print('closed=0 failed=0')\n"
        f"raise SystemExit({rc})\n"
    )
    fake.chmod(0o755)
    env.update(
        {
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "GITHUB_OUTPUT": str(tmp_path / "output"),
            "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"),
            "CALL_RECORD": str(tmp_path / "calls.json"),
            "EXPECTED_REGISTER": json.dumps({prefix: repository}),
        }
    )
    result = subprocess.run(
        ["bash", "-e", "-c", script],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    record = json.loads((tmp_path / "calls.json").read_text())
    output = (tmp_path / "output").read_text() if (tmp_path / "output").exists() else ""
    return result, record, output


@pytest.mark.parametrize("execute", ["false", "true"])
@pytest.mark.parametrize(
    "prefix,repository",
    [("borduas", "Borduas-Holdings/blazing"), ('prefix-"quoted', "example/another")],
)
def test_real_step_binds_register_to_caller_and_keeps_mode(
    tmp_path, execute, prefix, repository
):
    result, record, output = run_step(
        tmp_path, execute=execute, prefix=prefix, repository=repository
    )
    assert result.returncode == 0, result.stderr
    args = record["argv"]
    assert args[:7] == [
        "tool",
        "run",
        "--from",
        "just-akash",
        "python",
        "-m",
        "just_akash.cleanup_stale",
    ]
    assert args[args.index("--placement-prefix") + 1] == prefix
    assert json.loads(args[args.index("--ownership-register") + 1]) == {
        prefix: repository
    }
    assert record["token"] == "offline-github-token"
    assert ("--execute" in args) == (execute == "true")
    assert "--reap-runners" in args
    assert "closed=0" in output and "stale=0" in output


@pytest.mark.parametrize("rc", [1, 2])
def test_reader_failure_including_unsupported_old_runtime_propagates(tmp_path, rc):
    result, _, output = run_step(tmp_path, rc=rc)
    assert result.returncode == rc
    assert output == ""


def test_removing_exact_register_flag_breaks_successful_effect(tmp_path):
    result, record, output = run_step(tmp_path, mutate=True)
    assert "--ownership-register" not in record["argv"]
    assert result.returncode == 2
    assert output == ""
