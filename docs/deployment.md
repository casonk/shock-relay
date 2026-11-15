# Deployment modes: the Gmail digest sender

The hourly **digest sender** (`services/gmail-imap/send_digest.py`) drains a queue of notifications that other
jobs add to and sends them as one email. It runs three ways. You choose with one setting, and
**only the `k3s` mode needs a cluster**. If you just want the digests, you need Python and nothing else.

| Mode | What it is | Needs | Use it for |
|---|---|---|---|
| `dev` (default) | send the queued digest once, in the foreground | Python 3.10+ | trying it, developing |
| `host` | the Clockwork-managed systemd user timer, hourly | Python, systemd, Clockwork | a machine that sends day to day |
| `k3s` | a CronJob in K3s with default-deny egress | K3s, podman, kubectl, the in-cluster registry | keeping Gmail credentials out of the host's process space |

The sender's code is the same in all three. The pod differs by *configuration*: credentials arrive as
environment variables, and one setting (below) makes it ignore host paths.

## Choose a mode

```bash
deploy/deploy.sh mode                  # print the mode in effect and where it came from
deploy/deploy.sh up                    # run it in that mode
deploy/deploy.sh status | verify | down
```

The mode is read from, first match wins:

1. `--mode dev|host|k3s` on the command line
2. `SHOCK_RELAY_DEPLOY_MODE` in the environment
3. `SHOCK_RELAY_DEPLOY_MODE` in `config/deploy.local.env` (copy `config/deploy.example.env`; it is gitignored)
4. `dev`

An unknown value, or a config file that cannot be read, is an error, never a silent fallback.

## What each mode does

### dev
`up` runs `send_digest.py` once with your `services/gmail-imap/config.local.yaml`. `status` and `verify` run it
with `--dry-run --json`, which reports what is queued and **leaves the queue untouched** (it used to drain it:
see the changelog).

### host
`up` enables `shock-relay-gmail-digest.timer`. Clockwork installs it from `examples/shock-relay/gmail-digest.toml`
(copy to `*.local.toml` with real paths, then `clockwork install --manifest <that file> --target systemd-user`);
`up` tells you if it is missing.

### k3s
`up` refuses to start, and changes nothing, unless kubectl, podman and the in-cluster registry are present. Then it
runs, in order: `prepare-host.sh` (label the queue folder for containers), `build-image.sh` (refuses uncommitted
`services/gmail-imap`), `apply.sh` (resolves the Gmail credentials from your vault **on the host**, creates two
Secrets, the volume, the network policy and the CronJob **suspended**), `verify.sh` (must pass), and only then
disables the host timer and unsuspends the CronJob. A failed step changes nothing: the timer keeps sending.

## What the pod can reach

- **Network:** only `smtp.gmail.com` (465, 587) and `imap.gmail.com` (993, because the sender checks that Gmail
  kept a sent copy), plus DNS for those two names. The host, the Kubernetes API, other nodes and link-local
  addresses are denied; nothing can connect in.
- **Files:** the digest queue folder (`~/.local/share/shock-relay`), through a local volume with reclaim policy
  `Retain`. Producers on the host keep appending to it under the same lock.
- **Credentials:** `SHOCK_RELAY_IMAP_*` and `SHOCK_RELAY_SMTP_*` environment variables from a Secret. The pod's
  config file contains no credential and no vault entry, only hosts and recipients.
- **Identity:** your uid, read-only root filesystem, no capabilities, no Kubernetes token, no `fsGroup`.

## Switching

| From | To | Command |
|---|---|---|
| dev | host | `deploy/deploy.sh --mode host up` |
| host | k3s | `deploy/deploy.sh --mode k3s up` (verifies first, then hands over) |
| k3s | host | `deploy/deploy.sh --mode host up` (suspends the CronJob, re-enables the timer) |
| any | stopped | `--mode host down`, or nothing to stop in dev |

`--mode k3s down` is the same as `--mode host up`. The CronJob is left in place, suspended (`kubectl delete ns
shock-relay` removes it). A marker in `~/.local/state/shock-relay/` records that the pod was last handed the work.
Unsuspending a CronJob runs the most recent slot missed in the last 15 minutes, so one hourly slot can be sent
by both the timer and the pod around a hand-over. A queued entry is removed under a lock when it is taken, so it
is never sent twice.

## Settings that differ by mode

| Setting | Standalone (`dev`, `host`) | `k3s` | Why |
|---|---|---|---|
| `SHOCK_RELAY_DIGEST_IGNORE_ENTRY_CONFIG` | unset | `1` | each queued entry records the host path of the config that queued it; a pod cannot read it, so every entry is sent with the pod's own config |
| `SHOCK_RELAY_GMAIL_DIGEST_FILE` | `~/.local/share/shock-relay/gmail-digest.jsonl` | `/queue/gmail-digest.jsonl` | where the volume is mounted |
| `TZ` | the machine's zone | the host's zone, filled in by `apply.sh` | the digest is read in local time |
| credentials | resolved from the vault at run time | environment variables | the pod cannot reach the vault |

You never set these by hand in k3s mode.

## For contributors without K3s

- `pytest` needs no cluster: the deployment tests parse manifests, run the scripts against stub commands, and
  check the generated pod config round-trips through `parse_simple_yaml` and never contains a credential.
- Nothing under `deploy/k3s/` runs unless you select the `k3s` mode.
