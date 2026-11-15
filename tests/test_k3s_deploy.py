"""The K3s deployment of the digest sender: what it may reach, what it may touch, and how credentials get there."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

yaml = pytest.importorskip("yaml")

REPO = Path(__file__).resolve().parents[1]
DEPLOY = REPO / "deploy" / "k3s"
MANIFESTS = DEPLOY / "manifests"
GMAIL_DIR = REPO / "services" / "gmail-imap"


def docs(name: str) -> list[dict]:
    return list(yaml.safe_load_all((MANIFESTS / name).read_text()))


def _load_pod_config():
    spec = importlib.util.spec_from_file_location("make_pod_config", DEPLOY / "make_pod_config.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def common():
    sys.path.insert(0, str(GMAIL_DIR))
    sys.modules.pop("common", None)
    import common as module  # shock-relay's own loader

    yield module
    sys.path.remove(str(GMAIL_DIR))
    sys.modules.pop("common", None)


def test_the_namespace_enforces_the_restricted_pod_security_standard():
    (namespace,) = docs("00-namespace.yaml")
    assert namespace["metadata"]["labels"]["pod-security.kubernetes.io/enforce"] == "restricted"


def test_the_cronjob_is_created_suspended_hourly_and_never_overlaps_itself():
    (cron,) = docs("20-cronjob.yaml")
    assert cron["spec"]["suspend"] is True, "created suspended so it cannot race the host timer"
    assert cron["spec"]["schedule"] == "0 * * * *"
    assert cron["spec"]["concurrencyPolicy"] == "Forbid"
    assert cron["spec"]["jobTemplate"]["spec"]["activeDeadlineSeconds"] <= 900


def test_the_pod_runs_as_the_owner_unprivileged_and_never_regroups_the_queue():
    (cron,) = docs("20-cronjob.yaml")
    pod = cron["spec"]["jobTemplate"]["spec"]["template"]["spec"]
    assert (
        pod["securityContext"]["runAsUser"] == 1000
        and pod["securityContext"]["runAsNonRoot"] is True
    )
    assert "fsGroup" not in pod["securityContext"], "fsGroup would re-group the host's queue folder"
    assert pod["automountServiceAccountToken"] is False
    container = pod["containers"][0]
    assert container["securityContext"]["readOnlyRootFilesystem"] is True
    assert container["securityContext"]["capabilities"]["drop"] == ["ALL"]
    assert container["image"] == "localhost:5000/shock-relay-digest:k3s"
    assert container["envFrom"] == [{"secretRef": {"name": "shock-relay-env"}}]
    assert {"name": "TZ", "value": "__TZ__"} in container["env"]
    assert not [v for v in pod["volumes"] if "hostPath" in v]


def test_the_config_secret_is_readable_without_fsGroup_and_holds_no_credential():
    (cron,) = docs("20-cronjob.yaml")
    volume = next(
        v
        for v in cron["spec"]["jobTemplate"]["spec"]["template"]["spec"]["volumes"]
        if "secret" in v
    )
    assert volume["secret"]["defaultMode"] == 0o444
    # the credentials are environment variables from a different Secret; this file only names them
    assert volume["secret"]["secretName"] == "shock-relay-config"


def test_the_policy_allows_only_gmail_smtp_and_imap_and_denies_the_host_and_cluster():
    (policy,) = docs("30-network-policy.yaml")
    spec = policy["spec"]
    assert spec["ingressDeny"] == [{"fromEntities": ["all"]}]
    assert {"host", "remote-node", "kube-apiserver", "health"} <= set(
        spec["egressDeny"][0]["toEntities"]
    )
    by_host = {
        m["matchName"]: sorted(p["port"] for ports in rule["toPorts"] for p in ports["ports"])
        for rule in spec["egress"]
        for m in rule.get("toFQDNs", [])
    }
    assert by_host == {"smtp.gmail.com": ["465", "587"], "imap.gmail.com": ["993"]}
    assert not {"toCIDR", "toEntities"} & {k for rule in spec["egress"] for k in rule}


def test_the_queue_volume_is_rendered_per_machine_and_never_deleted_with_its_claim():
    text = (MANIFESTS / "10-volume.yaml.tmpl").read_text()
    for placeholder in ("__QUEUE_DIR__", "__NODE__"):
        assert placeholder in text
    assert "/home/" not in text and "/Users/" not in text
    rendered = text.replace("__QUEUE_DIR__", "/q").replace("__NODE__", "n")
    (volume,) = [d for d in yaml.safe_load_all(rendered) if d["kind"] == "PersistentVolume"]
    assert volume["spec"]["persistentVolumeReclaimPolicy"] == "Retain" and "local" in volume["spec"]


def test_the_image_ignores_the_host_config_paths_that_queued_entries_carry():
    containerfile = (DEPLOY / "Containerfile").read_text()
    assert "SHOCK_RELAY_DIGEST_IGNORE_ENTRY_CONFIG=1" in containerfile
    assert "SHOCK_RELAY_GMAIL_DIGEST_FILE=/queue/gmail-digest.jsonl" in containerfile
    assert "USER 1000:1000" in containerfile
    assert "config.local" not in containerfile


def test_apply_resolves_credentials_into_a_private_directory_and_never_onto_a_command_line():
    apply = (DEPLOY / "apply.sh").read_text()
    assert "trap 'rm -rf \"$SECRET_DIR\"' EXIT" in apply and "chmod 700" in apply
    assert "--from-env-file" in apply and "--from-literal" not in apply
    assert "s#__TZ__#$TZ_NAME#g" in apply and "timedatectl show -p Timezone" in apply
    assert "prepare-host.sh first" in apply and "container_file_t" in apply


def test_verify_cannot_report_success_without_running_its_checks():
    text = (DEPLOY / "verify.sh").read_text()
    assert "exit 2" in text and "nothing was verified" in text
    assert "could not run the probe" in text and "did not become ready" in text
    assert "--dry-run" in text, "the queue check must use the non-draining dry run"
    assert "the dry run removed entries" in text
    assert text.rstrip().endswith("exit $fail")


# ---- make_pod_config.py -------------------------------------------------------------------------------------


LIVE = {
    "keepass_profile": "private-profile",
    "service": {"name": "gmail-imap", "enabled": True},
    "paths": {"data_dir": "/home/someone/data"},
    "imap": {
        "host": "imap.gmail.com",
        "port": 993,
        "use_ssl": True,
        "username_keepass_entry": "email/secret-entry#imap",
        "password_keepass_entry": "email/secret-entry#imap",
        "username": "me@example.com",
        "mailboxes": ["INBOX"],
    },
    "smtp": {
        "host": "smtp.gmail.com",
        "port": 587,
        "use_ssl": False,
        "starttls": True,
        "allowed_recipients": ["me@example.com"],
    },
}


def test_the_pod_config_names_environment_variables_and_carries_no_credential_or_vault_entry():
    module = _load_pod_config()
    out = module.pod_config(LIVE)
    text = module.dump_yaml(out)
    for secret in ("secret-entry", "private-profile", "me@example.com#", "someone"):
        assert secret not in text, secret
    assert out["imap"]["username_env"] == "SHOCK_RELAY_IMAP_USERNAME"
    assert out["smtp"]["password_env"] == "SHOCK_RELAY_SMTP_PASSWORD"
    assert out["smtp"]["from_env"] == "SHOCK_RELAY_SMTP_FROM"
    assert out["paths"]["data_dir"] == "/tmp/gmail-imap"
    assert "keepass_profile" not in out
    for section in ("imap", "smtp"):
        assert not {"username", "password", "from"} & set(out[section])
    assert out["smtp"]["port"] == 587 and out["smtp"]["allowed_recipients"] == ["me@example.com"]
    assert LIVE["imap"]["username"] == "me@example.com", "the live config is not modified"


def test_the_pod_config_round_trips_through_shock_relays_own_yaml_parser(common):
    module = _load_pod_config()
    out = module.pod_config(LIVE)
    parsed = common.parse_simple_yaml(module.dump_yaml(out))
    assert parsed["imap"]["username_env"] == "SHOCK_RELAY_IMAP_USERNAME"
    assert parsed["imap"]["mailboxes"] == ["INBOX"]
    assert parsed["imap"]["port"] == 993 and parsed["imap"]["use_ssl"] is True
    assert parsed["smtp"]["allowed_recipients"] == ["me@example.com"]
    assert parsed["smtp"]["starttls"] is True and parsed["smtp"]["use_ssl"] is False
    assert parsed["paths"]["data_dir"] == "/tmp/gmail-imap"


def test_the_loader_resolves_the_pod_config_from_the_environment_like_the_pod_will(
    common, tmp_path, monkeypatch
):
    module = _load_pod_config()
    config = tmp_path / "config.yaml"
    config.write_text(module.dump_yaml(module.pod_config(LIVE)), encoding="utf-8")
    values = {
        "SHOCK_RELAY_IMAP_USERNAME": "me@example.com",
        "SHOCK_RELAY_IMAP_PASSWORD": "app-password",
        "SHOCK_RELAY_SMTP_USERNAME": "me@example.com",
        "SHOCK_RELAY_SMTP_PASSWORD": "app-password",
        "SHOCK_RELAY_SMTP_FROM": "me@example.com",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    loaded = common.load_config(str(config))
    assert (loaded.imap.username, loaded.imap.password) == ("me@example.com", "app-password")
    assert (loaded.smtp.username, loaded.smtp.password) == ("me@example.com", "app-password")
    assert loaded.smtp.from_address == "me@example.com" and loaded.smtp.host == "smtp.gmail.com"


def test_credentials_that_cannot_be_resolved_stop_the_deploy_without_writing_empty_ones():
    module = _load_pod_config()
    resolved = SimpleNamespace(
        imap=SimpleNamespace(username="me@example.com", password=""),
        smtp=SimpleNamespace(username="", password="", from_address=""),
    )
    with pytest.raises(SystemExit) as stopped:
        module.environment(resolved)
    assert "SHOCK_RELAY_IMAP_PASSWORD" in str(stopped.value) and "vault" in str(stopped.value)
    assert "me@example.com" not in str(stopped.value), "an error never echoes a credential"


def test_smtp_defaults_to_the_imap_account_as_the_loader_does():
    module = _load_pod_config()
    resolved = SimpleNamespace(
        imap=SimpleNamespace(username="me@example.com", password="pw"),
        smtp=SimpleNamespace(username="", password="", from_address=""),
    )
    values = module.environment(resolved)
    assert values["SHOCK_RELAY_SMTP_USERNAME"] == "me@example.com"
    assert values["SHOCK_RELAY_SMTP_PASSWORD"] == "pw"
    assert values["SHOCK_RELAY_SMTP_FROM"] == "me@example.com"


def test_the_generator_writes_owner_only_files_and_prints_no_value(
    tmp_path, common, capsys, monkeypatch
):
    module = _load_pod_config()
    live = tmp_path / "config.local.yaml"
    live.write_text(
        "imap:\n  host: imap.gmail.com\n  username: me@example.com\n  password: very-secret-pw\n",
        encoding="utf-8",
    )
    out = tmp_path / "out"
    assert module.main(["--live", str(live), "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "very-secret-pw" not in printed and "me@example.com" not in printed
    for name in ("config.yaml", "env"):
        assert (out / name).stat().st_mode & 0o777 == 0o600
    assert "very-secret-pw" in (out / "env").read_text()
    assert "very-secret-pw" not in (out / "config.yaml").read_text()
