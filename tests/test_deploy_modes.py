"""deploy/deploy.sh: one setting chooses dev, host or k3s, and only k3s may touch a cluster.

The script runs against stub commands that record every call, so nothing here needs systemd, podman or a
cluster, which is the point: a developer without K3s must be able to run and test the digest sender.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
DEPLOY = REPO / "deploy" / "deploy.sh"
K3S_STEPS = ["prepare-host.sh", "build-image.sh", "apply.sh", "verify.sh"]
TIMER = "shock-relay-gmail-digest.timer"


def _stub(path: Path, log: Path, name: str, body: str = "") -> None:
    path.write_text(f'#!/usr/bin/env bash\necho "{name} $*" >> "{log}"\n{body}\n')
    path.chmod(0o755)


@pytest.fixture
def sandbox(tmp_path):
    """A PATH of recording stubs, a stub k3s directory, and a private state folder."""
    bin_dir, k3s, log = tmp_path / "bin", tmp_path / "k3s", tmp_path / "calls.log"
    bin_dir.mkdir()
    k3s.mkdir()
    for name, body in {
        "kubectl": "exit 99",
        "podman": "exit 99",
        "curl": "exit 22",
        "systemctl": (
            'case "$*" in *is-active*) echo inactive; exit 3 ;; *is-enabled*) echo disabled; exit 1 ;; esac'
        ),
    }.items():
        _stub(bin_dir / name, log, name, body)
    for step in [*K3S_STEPS, "handover.sh"]:
        _stub(k3s / step, log, step)
    shutil.copy(REPO / "deploy" / "k3s" / "env_value.py", k3s / "env_value.py")
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "SHOCK_RELAY_K3S_DIR": str(k3s),
        "SHOCK_RELAY_DEPLOY_CONFIG": str(tmp_path / "deploy.local.env"),
        "XDG_STATE_HOME": str(tmp_path / "state"),
    }
    env.pop("SHOCK_RELAY_DEPLOY_MODE", None)
    return env, log, tmp_path


def run(env, *args):
    return subprocess.run(
        ["bash", str(DEPLOY), *args], env=env, capture_output=True, text=True, timeout=60
    )


def calls(log: Path) -> list[str]:
    return log.read_text().splitlines() if log.exists() else []


def names(log: Path) -> list[str]:
    return [c.split()[0] for c in calls(log)]


def _cluster_ready(tmp_path):
    log = tmp_path / "calls.log"
    _stub(tmp_path / "bin" / "curl", log, "curl")
    _stub(tmp_path / "bin" / "kubectl", log, "kubectl")


def _timer_not_installed(tmp_path):
    body = 'case "$*" in *" cat "*) exit 1 ;; *is-active*) echo inactive; exit 3 ;; esac'
    _stub(tmp_path / "bin" / "systemctl", tmp_path / "calls.log", "systemctl", body)


def _marker(tmp_path, value="k3s"):
    folder = tmp_path / "state" / "shock-relay"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "deploy-mode").write_text(value + "\n")
    return folder / "deploy-mode"


def test_the_default_mode_is_dev_so_a_fresh_checkout_needs_no_cluster(sandbox):
    env, _, _ = sandbox
    done = run(env, "mode")
    assert done.returncode == 0 and done.stdout.strip() == "dev (from default)"


def test_the_mode_comes_from_flag_then_environment_then_config_then_default(sandbox):
    env, _, tmp = sandbox
    config = tmp / "deploy.local.env"
    config.write_text('SHOCK_RELAY_DEPLOY_MODE="host"\n')
    from_config = run(env, "mode").stdout
    # the quoted config value is read the way systemd would read it
    assert from_config.startswith("host (from ")
    assert str(config) in from_config
    assert (
        run({**env, "SHOCK_RELAY_DEPLOY_MODE": "k3s"}, "mode").stdout.strip()
        == "k3s (from environment)"
    )
    flagged = run({**env, "SHOCK_RELAY_DEPLOY_MODE": "k3s"}, "--mode", "dev", "mode")
    assert flagged.stdout.strip() == "dev (from --mode)"


def test_an_unknown_mode_is_an_error_not_a_silent_fallback(sandbox):
    env, _, tmp = sandbox
    done = run(env, "--mode", "docker", "mode")
    assert done.returncode == 2 and "unknown deployment mode" in done.stderr
    (tmp / "deploy.local.env").write_text("SHOCK_RELAY_DEPLOY_MODE=cloud\n")
    done = run(env, "mode")
    assert done.returncode == 2 and str(tmp / "deploy.local.env") in done.stderr


def test_a_config_file_that_cannot_be_read_is_an_error_not_a_quiet_default(sandbox):
    env, _, tmp = sandbox
    config = tmp / "deploy.local.env"
    config.write_text("SHOCK_RELAY_DEPLOY_MODE=host\n")
    config.chmod(0)
    if os.access(config, os.R_OK):  # running as root: permissions do not apply
        pytest.skip("cannot make the file unreadable")
    done = run(env, "mode")
    assert done.returncode != 0
    assert "dev (from default)" not in done.stdout


def test_a_missing_command_is_a_usage_error(sandbox):
    env, _, _ = sandbox
    assert run(env).returncode == 2


@pytest.mark.parametrize("command", ["mode", "down"])
def test_dev_never_touches_kubectl_podman_or_systemd(sandbox, command):
    env, log, _ = sandbox
    run(env, "--mode", "dev", command)
    assert [n for n in names(log) if n in {"kubectl", "podman", "systemctl"}] == []


def test_host_up_enables_the_timer_and_never_touches_kubectl_or_podman(sandbox):
    env, log, _ = sandbox
    done = run(env, "--mode", "host", "up")
    assert done.returncode == 0, done.stderr
    assert f"systemctl --user enable --now {TIMER}" in calls(log)
    assert [n for n in names(log) if n in {"kubectl", "podman"}] == []


def test_host_up_without_the_timer_says_how_to_install_it_and_changes_nothing(sandbox):
    env, log, tmp = sandbox
    _timer_not_installed(tmp)
    done = run(env, "--mode", "host", "up")
    assert done.returncode == 1 and "not installed" in done.stderr and "Clockwork" in done.stderr
    assert f"systemctl --user enable --now {TIMER}" not in calls(log)


def test_host_down_disables_only_the_timer(sandbox):
    env, log, _ = sandbox
    run(env, "--mode", "host", "down")
    assert f"systemctl --user disable --now {TIMER}" in calls(log)
    assert [n for n in names(log) if n in {"kubectl", "podman"}] == []


def test_leaving_k3s_suspends_the_pod_before_the_timer_is_enabled(sandbox):
    env, log, tmp = sandbox
    _cluster_ready(tmp)
    marker = _marker(tmp)
    done = run(env, "--mode", "host", "up")
    assert done.returncode == 0, done.stderr
    seen = calls(log)
    assert seen.index("handover.sh pod-off") < seen.index(f"systemctl --user enable --now {TIMER}")
    assert not marker.exists()


def test_leaving_k3s_without_kubectl_refuses_rather_than_send_twice(sandbox):
    env, log, tmp = sandbox
    marker = _marker(tmp)
    done = run({**env, "KUBECTL": "definitely-not-installed"}, "--mode", "host", "up")
    assert done.returncode == 1 and "drop-in" in done.stderr
    assert f"systemctl --user enable --now {TIMER}" not in calls(log)
    assert marker.exists()


def test_k3s_refuses_without_kubectl_and_says_dev_and_host_do_not_need_it(sandbox):
    env, log, _ = sandbox
    done = run({**env, "KUBECTL": "definitely-not-installed"}, "--mode", "k3s", "up")
    assert done.returncode == 1
    assert (
        "k3s mode needs kubectl" in done.stderr and "dev and host modes need neither" in done.stderr
    )
    assert [n for n in names(log) if n in {"podman", "systemctl"} or n.endswith(".sh")] == []


def test_k3s_refuses_without_the_registry_and_deploys_nothing(sandbox):
    env, log, _ = sandbox
    done = run(env, "--mode", "k3s", "up")  # kubectl and podman exist (stubs); the curl stub fails
    assert done.returncode == 1 and "in-cluster registry" in done.stderr
    assert [n for n in names(log) if n.endswith(".sh") or n == "systemctl"] == []


def test_k3s_up_runs_the_steps_in_order_and_hands_over_only_after_verify(sandbox):
    env, log, tmp = sandbox
    _cluster_ready(tmp)
    done = run(env, "--mode", "k3s", "up")
    assert done.returncode == 0, done.stderr
    assert [n for n in names(log) if n.endswith(".sh") and n != "handover.sh"] == K3S_STEPS
    seen = calls(log)
    # The timer is the trigger in this mode: it is never disabled, and the unit is switched over after verify.
    assert seen.index("verify.sh ") < seen.index("handover.sh pod-on")
    assert f"systemctl --user disable --now {TIMER}" not in seen
    assert (tmp / "state" / "shock-relay" / "deploy-mode").read_text().strip() == "k3s"


@pytest.mark.parametrize("failing", K3S_STEPS)
def test_a_failed_step_leaves_the_unit_sending_from_the_host(sandbox, failing):
    env, log, tmp = sandbox
    _cluster_ready(tmp)
    _stub(tmp / "k3s" / failing, log, failing, "exit 1")
    done = run(env, "--mode", "k3s", "up")
    assert done.returncode != 0
    seen = calls(log)
    assert f"systemctl --user disable --now {TIMER}" not in seen
    assert "handover.sh pod-on" not in seen
    assert not (tmp / "state" / "shock-relay" / "deploy-mode").exists()


def test_k3s_down_is_host_up(sandbox):
    env, log, tmp = sandbox
    _cluster_ready(tmp)
    _marker(tmp)
    done = run(env, "--mode", "k3s", "down")
    assert done.returncode == 0, done.stderr
    assert "handover.sh pod-off" in calls(log)


def test_the_image_build_refuses_uncommitted_source_unless_told_otherwise(tmp_path):
    repo = tmp_path / "repo"
    (repo / "deploy" / "k3s").mkdir(parents=True)
    (repo / "services" / "gmail-imap").mkdir(parents=True)
    shutil.copy(
        REPO / "deploy" / "k3s" / "build-image.sh", repo / "deploy" / "k3s" / "build-image.sh"
    )
    (repo / "deploy" / "k3s" / "Containerfile").write_text("FROM scratch\n")
    (repo / "services" / "gmail-imap" / "send_digest.py").write_text("x = 1\n")
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.com"]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-qm", "init"], check=True)
    (repo / "services" / "gmail-imap" / "send_digest.py").write_text("x = 2\n")

    log = tmp_path / "calls.log"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _stub(bin_dir / "podman", log, "podman")
    crew = tmp_path / "crew" / "deploy" / "k3s"
    crew.mkdir(parents=True)
    _stub(crew / "push-image.sh", log, "push-image.sh")
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "CREW_CHIEF_DIR": str(tmp_path / "crew"),
    }
    script = repo / "deploy" / "k3s" / "build-image.sh"

    refused = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True)
    assert refused.returncode == 1 and "uncommitted changes" in refused.stderr
    assert "podman" not in names(log)

    allowed = subprocess.run(
        ["bash", str(script)], env={**env, "ALLOW_DIRTY": "1"}, capture_output=True, text=True
    )
    assert allowed.returncode == 0, allowed.stderr
    assert "podman" in names(log)


def test_host_scripts_use_only_python_flags_that_exist_on_the_oldest_supported_python():
    # `python3 -P` is Python 3.11+; -I (isolated) exists everywhere and keeps the script directory off sys.path.
    # A line that runs inside the pod (kubectl exec, Python 3.12 image) may use -P.
    for path in (REPO / "deploy").rglob("*.sh"):
        for line in path.read_text().splitlines():
            if "python3 -P" in line:
                assert " exec " in line, f"{path.name}: {line.strip()}"


def test_the_local_config_is_gitignored_and_the_example_and_docs_cover_every_mode(sandbox):
    env, _, _ = sandbox
    assert "config/deploy.local.env" in (REPO / ".gitignore").read_text()
    example = REPO / "config" / "deploy.example.env"
    done = run({**env, "SHOCK_RELAY_DEPLOY_CONFIG": str(example)}, "mode")
    assert done.returncode == 0 and done.stdout.startswith("dev (from ")
    docs = (REPO / "docs" / "deployment.md").read_text()
    for needle in (
        "`dev`",
        "`host`",
        "`k3s`",
        "Switching",
        "only the `k3s` mode needs a",
        "deploy/deploy.sh",
    ):
        assert needle in docs, needle
    assert "docs/deployment.md" in (REPO / "README.md").read_text()


def test_the_restore_trap_fires_for_failures_inside_functions():
    # Without `set -E` bash does not inherit an ERR trap into functions, so a failure inside a function skips the
    # restore. The portfolio's deployment-modes contract requires set -eEuo pipefail.
    assert "set -eEuo pipefail" in DEPLOY.read_text()


def test_k3s_without_the_host_timer_refuses_and_changes_nothing(sandbox):
    # The timer is the trigger (and carries the job guard and resource limits); without it nothing would run.
    env, log, tmp = sandbox
    _cluster_ready(tmp)
    body = 'case "$*" in *" cat "*) exit 1 ;; *is-active*) echo inactive; exit 3 ;; esac'
    _stub(tmp / "bin" / "systemctl", log, "systemctl", body)
    done = run(env, "--mode", "k3s", "up")
    assert done.returncode == 1 and "not installed" in done.stderr
    assert "handover.sh pod-on" not in calls(log)


def test_the_cronjob_is_only_a_template_that_never_schedules_itself():
    # The host timer triggers every run through run-job.sh; a CronJob that also ran would send twice.
    text = (REPO / "deploy" / "k3s" / "manifests" / "20-cronjob.yaml").read_text()
    assert "suspend: true" in text and 'schedule: "0 0 31 2 *"' in text


def test_the_dropin_replaces_only_execstart():
    # The job guard and resource limits live in other drop-ins and must keep applying.
    text = (REPO / "deploy" / "k3s" / "systemd" / "20-k3s-run.conf").read_text()
    body = [line for line in text.splitlines() if line and not line.startswith("#")]
    keys = {line.split("=", 1)[0] for line in body if "=" in line}
    assert keys <= {"Environment", "ExecStart"}, keys
    assert body.index("ExecStart=") < max(i for i, line in enumerate(body) if line.startswith("ExecStart=/"))


def test_handover_installs_and_removes_the_dropin(tmp_path):
    for name in ("kubectl", "systemctl"):
        stub = tmp_path / "bin" / name
        stub.parent.mkdir(exist_ok=True)
        stub.write_text("#!/bin/sh\nexit 0\n")
        stub.chmod(0o755)
    env = {**os.environ, "PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}", "XDG_CONFIG_HOME": str(tmp_path / "cfg")}
    script = str(REPO / "deploy" / "k3s" / "handover.sh")
    dropin = tmp_path / "cfg" / "systemd" / "user" / "shock-relay-gmail-digest.service.d" / "20-k3s-run.conf"
    subprocess.run(["bash", script, "pod-on"], env=env, check=True)
    text = dropin.read_text()
    assert "run-job.sh" in text and "__" not in text
    subprocess.run(["bash", script, "pod-off"], env=env, check=True)
    assert not dropin.exists()


def test_run_job_reports_the_jobs_status(tmp_path):
    log = tmp_path / "calls.log"
    kubectl = tmp_path / "bin" / "kubectl"
    kubectl.parent.mkdir()
    kubectl.write_text(
        "#!/bin/sh\n"
        f'echo "$*" >> {log}\n'
        'case "$*" in *"jsonpath={.status.failed}"*) echo 1 ;; esac\n'
    )
    kubectl.chmod(0o755)
    env = {**os.environ, "KUBECTL": str(kubectl), "KUBECONFIG": "/nonexistent"}
    done = subprocess.run(["bash", str(REPO / "deploy" / "k3s" / "run-job.sh")], env=env, capture_output=True, text=True)
    assert done.returncode == 1 and "failed" in done.stderr
    assert "create job" in log.read_text()

