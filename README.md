# shock-relay

shock-relay is an open messaging relay for automation scripts, agents, and infrastructure. It provides a unified way to send notifications across platforms like Signal, Telegram, WhatsApp, SMS, and email through one consistent interface.

Consent reference: [`../../doc-repos/my-consent/messaging-and-email.md`](../../doc-repos/my-consent/messaging-and-email.md) documents the explicit consent covering personal messaging and email processing handled by this repo. Twilio toll-free messaging, when used, is additionally covered by [`../../doc-repos/my-consent/twilio.md`](../../doc-repos/my-consent/twilio.md).

## Overview

shock-relay simplifies cross-platform messaging by providing standardized interfaces to multiple messaging services. Whether you're building automation workflows, monitoring systems, or AI agents, shock-relay gives you a consistent way to communicate across different platforms.

The current implementation is organized as parallel provider adapters rather
than a single repo-wide relay daemon. Signal wraps `signal-cli` directly,
Telegram / WhatsApp / Twilio each expose shared HTTP helper layers plus Python
and shell entrypoints, and Gmail IMAP keeps its own IMAP/SMTP helper layer.
That service-specific CLI surface is the stable interface today.

## Supported Services

- **Signal** (via signal-cli) - Fully implemented with send/receive capabilities
- **Telegram** (Bot API) - Basic send/receive/test scripts in Python and native shell
- **WhatsApp** (generic HTTPS gateway) - Basic send/receive/test scripts in Python and native shell
- **Twilio SMS** - Basic send/receive/test scripts in Python and native shell
- **Gmail IMAP** - Basic IMAP/SMTP scaffolding in Python

## Quick Start

### Signal CLI Example

1. Copy the example configuration:
   ```bash
   cp services/signal-cli/config.example.yaml services/signal-cli/config.local.yaml
   ```

2. Edit `config.local.yaml` with your Signal account details

3. Send a message:
   ```bash
   ./services/signal-cli/send_message.py +15551234567 "Hello from shock-relay!"
   ```

4. Receive messages:
   ```bash
   ./services/signal-cli/receive_messages.py
   ```

### WhatsApp Gateway Example

1. Copy the example configuration:
   ```bash
   cp services/whatsapp/config.example.yaml services/whatsapp/config.local.yaml
   ```

2. Export the credential/sender environment variables referenced by the config
   `http.base_url` must use `https://`

3. Send a message:
   ```bash
   ./services/whatsapp/send_message.py whatsapp:+15551234567 "Hello from shock-relay!"
   ```

4. Receive messages:
   ```bash
   ./services/whatsapp/receive_messages.py --timeout 30 --pretty
   ```

5. Shell entrypoints are also available:
   ```bash
   ./services/whatsapp/send_message.sh whatsapp:+15551234567 "Hello from shock-relay!"
   ./services/whatsapp/receive_messages.sh --timeout 30 --pretty
   ```

### Telegram Bot Example

1. Copy the example configuration:
   ```bash
   cp services/telegram/config.example.yaml services/telegram/config.local.yaml
   ```

2. Export the bot token referenced by the config
   `telegram.api_base_url` must use `https://`

3. Send a message:
   ```bash
   ./services/telegram/send_message.py 123456789 "Hello from shock-relay!"
   ```

4. Receive updates:
   ```bash
   ./services/telegram/receive_messages.py --timeout 30 --pretty
   ```

5. Shell entrypoints are also available:
   ```bash
   ./services/telegram/send_message.sh 123456789 "Hello from shock-relay!"
   ./services/telegram/receive_messages.sh --timeout 30 --pretty
   ```

### Twilio SMS Example

1. Copy the example configuration:
   ```bash
   cp services/twilio/config.example.yaml services/twilio/config.local.yaml
   ```

2. Export the credentials and sender phone referenced by the config
   `twilio.api_base_url` must use `https://`

3. Send an SMS:
   ```bash
   ./services/twilio/send_sms.py +15551234567 "Hello from shock-relay!"
   ```

4. Receive recent messages:
   ```bash
   ./services/twilio/receive_messages.py --to +15557654321 --pretty
   ```

5. Shell entrypoints are also available:
   ```bash
   ./services/twilio/send_sms.sh +15551234567 "Hello from shock-relay!"
   ./services/twilio/receive_messages.sh --to +15557654321 --pretty
   ```

### Gmail IMAP Example

1. Copy the example configuration:
   ```bash
   cp services/gmail-imap/config.example.yaml services/gmail-imap/config.local.yaml
   ```

2. Export the Gmail username and app password referenced by the config
   `imap.host` and `smtp.host` default to Gmail, and the SMTP sender defaults to the same username

3. Check connectivity:
   ```bash
   ./services/gmail-imap/test_connection.py --pretty
   ```

4. Check inbox messages:
   ```bash
   ./services/gmail-imap/check_inbox.py --limit 10 --pretty
   ```

5. Send an email:
   ```bash
   ./services/gmail-imap/send_email.py you@example.com "Hello from shock-relay" "This is a test."
   ```

## Project Structure

```
shock-relay/
├── services/
│   ├── signal-cli/       # Direct signal-cli wrappers + end-to-end confirm scripts
│   ├── telegram/         # Bot API helpers + Python/shell send/receive/test flows
│   ├── whatsapp/         # HTTPS gateway helpers + Python/shell send/receive/test flows
│   ├── twilio/           # REST SMS helpers + Python/shell send/receive/test flows
│   └── gmail-imap/       # IMAP/SMTP helper layer + inbox/send/connectivity scripts
├── README.md             # This file
├── AGENTS.md             # Guide for AI agents
├── CLAUDE.md             # Claude-specific integration guide
├── docs/                 # Contributor architecture docs and rendered diagrams
└── LICENSE               # Apache 2.0 License
```

## Architecture Notes

- Each service keeps a tracked `config.example.yaml` and a local
  `config.local.yaml`, with secrets resolved from environment variables where
  possible.
- `services/signal-cli/` is intentionally dependency-light: the Python and shell
  entrypoints extract a small amount of YAML and invoke `signal-cli`
  subprocesses.
- `services/telegram/`, `services/whatsapp/`, and `services/twilio/` each pair
  `common.py` with `common.sh` so Python and shell entrypoints share the same
  config parsing, TLS/auth validation, request helpers, and normalized
  send/receive/test flows.
- `services/gmail-imap/common.py` owns the IMAP/SMTP configuration, TLS, inbox
  filtering, and send logic for the Gmail scripts.
- Confirmation scripts such as `test_send_receive_confirm.py` are the closest
  thing to an integration harness today: they send a tagged message, poll for a
  reply, and then send a confirmation message with the observed response.

## Configuration

Each service uses a standardized YAML configuration pattern:

- `config.example.yaml` - Template configuration (committed to git)
- `config.local.yaml` - Your actual credentials (git-ignored for security)

All services follow a consistent structure:
```yaml
service:
  name: service-name
  enabled: true

runtime:
  log_level: info

paths:
  data_dir: ./data/service-name
```

## Security

- **Never commit credentials** - All `config.local.yaml` files are automatically ignored by git
- **Use environment variables** - Services support environment variable references for sensitive data
- **Local data directories** - Each service can store state locally in git-ignored directories

## Development Status

- ✅ **Signal CLI** - Fully functional with send, receive, and test scripts
- ⚙️ **Telegram** - Bot API send/receive/test scripts implemented in Python and native shell
- ⚙️ **WhatsApp** - Generic HTTPS gateway send/receive/test scripts implemented in Python and native shell
- ⚙️ **Twilio** - SMS send/receive/test scripts implemented in Python and native shell
- ⚙️ **Gmail IMAP** - IMAP inbox checks, SMTP sends, and connection tests implemented in Python

## Use Cases

- **Automation Scripts** - Send notifications from cron jobs, CI/CD pipelines
- **AI Agents** - Enable LLM-powered agents to communicate via messaging platforms
- **Monitoring** - Alert on system events through your preferred channel
- **Infrastructure** - Unified notification layer for distributed systems

## Requirements

- Python 3.7+
- `curl` and `jq` for native shell Telegram, WhatsApp, and Twilio scripts
- signal-cli (for Signal integration)
- Service-specific credentials/API keys

## Contributing

Contributions are welcome! This project is in active development. Priority areas:

1. Add unified relay API layer
2. Docker containerization
3. Additional service integrations
4. Expand Gmail workflows beyond the initial IMAP/SMTP scaffolding

## License

Apache 2.0 - See LICENSE file for details

## Documentation

- [AGENTS.md](AGENTS.md) - Integration guide for AI agents and automation systems
- [CLAUDE.md](CLAUDE.md) - Specific guidance for Claude AI integration
