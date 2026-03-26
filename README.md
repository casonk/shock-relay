# shock-relay

shock-relay is an open messaging relay for automation scripts, agents, and infrastructure. It provides a unified way to send notifications across platforms like Signal, Telegram, WhatsApp, SMS, and email through one consistent interface.

## Overview

shock-relay simplifies cross-platform messaging by providing standardized interfaces to multiple messaging services. Whether you're building automation workflows, monitoring systems, or AI agents, shock-relay gives you a consistent way to communicate across different platforms.

## Supported Services

- **Signal** (via signal-cli) - Fully implemented with send/receive capabilities
- **Telegram** (Bot API) - Basic send/receive/test scripts in Python and native shell
- **WhatsApp** (generic HTTPS gateway) - Basic send/receive/test scripts in Python and native shell
- **Twilio SMS** - SMS messaging (configured)
- **Gmail IMAP** - Email monitoring and sending (configured)

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

## Project Structure

```
shock-relay/
├── services/
│   ├── signal-cli/       # Signal messaging (Python scripts)
│   ├── telegram/         # Telegram bot integration
│   ├── whatsapp/         # WhatsApp gateway
│   ├── twilio/           # SMS via Twilio
│   └── gmail-imap/       # Gmail email integration
├── README.md             # This file
├── AGENTS.md             # Guide for AI agents
├── CLAUDE.md             # Claude-specific integration guide
└── LICENSE               # Apache 2.0 License
```

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
- ⚙️ **Twilio** - Configuration complete, implementation pending
- ⚙️ **Gmail IMAP** - Configuration complete, implementation pending

## Use Cases

- **Automation Scripts** - Send notifications from cron jobs, CI/CD pipelines
- **AI Agents** - Enable LLM-powered agents to communicate via messaging platforms
- **Monitoring** - Alert on system events through your preferred channel
- **Infrastructure** - Unified notification layer for distributed systems

## Requirements

- Python 3.7+
- `curl` and `jq` for native shell WhatsApp scripts
- signal-cli (for Signal integration)
- Service-specific credentials/API keys

## Contributing

Contributions are welcome! This project is in active development. Priority areas:

1. Complete implementations for Twilio and Gmail
2. Add unified relay API layer
3. Docker containerization
4. Additional service integrations

## License

Apache 2.0 - See LICENSE file for details

## Documentation

- [AGENTS.md](AGENTS.md) - Integration guide for AI agents and automation systems
- [CLAUDE.md](CLAUDE.md) - Specific guidance for Claude AI integration
