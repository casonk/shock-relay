# AI Agent Integration Guide

This guide provides instructions for AI agents, automation systems, and developers integrating shock-relay into their workflows.

## Overview

shock-relay is designed to be agent-friendly, providing simple command-line interfaces and standardized configuration patterns that make it easy for AI systems to send and receive messages across multiple platforms.

## Architecture Principles

### 1. Configuration-as-Code
All services use YAML configuration files with a consistent structure:
- `config.example.yaml` - Template showing all available options
- `config.local.yaml` - Your instance-specific configuration (never committed)

### 2. Environment Variable Support
Sensitive credentials should be provided via environment variables referenced in config files:
```yaml
telegram:
  bot_token_env: TELEGRAM_BOT_TOKEN
```

### 3. Zero Runtime Dependencies
The Signal CLI implementation uses only Python standard library, avoiding complex dependency management for agents.

## Integration Patterns

### Pattern 1: Direct Script Execution

The simplest integration - execute scripts directly:

```bash
# Send a Signal message
./services/signal-cli/send_message.py "+15551234567" "Alert: System status check"

# Listen for incoming messages
./services/signal-cli/receive_messages.py --timeout 30
```

**Pros:**
- Simple and direct
- No additional abstraction layer
- Easy to debug

**Cons:**
- Service-specific command syntax
- Must handle each service separately

### Pattern 2: Environment Variable Message Passing

Use environment variables to pass messages:

```bash
export SIGNAL_CLI_MESSAGE="Hello from automation"
./services/signal-cli/send_message.py "+15551234567"
```

**Pros:**
- Cleaner for scripting
- Avoids shell escaping issues
- Good for CI/CD pipelines

### Pattern 3: Configuration File Override

Override default config paths for multi-tenant or multi-environment setups:

```bash
./services/signal-cli/send_message.py \
  --config /path/to/custom/config.yaml \
  "+15551234567" \
  "Message text"
```

## Service-Specific Integration

### Signal CLI

**Prerequisites:**
- Install signal-cli
- Register a phone number with Signal

**Send Message:**
```bash
./services/signal-cli/send_message.py <recipient> <message> [--config <path>]
```

**Receive Messages:**
```bash
./services/signal-cli/receive_messages.py [--timeout <seconds>] [--config <path>]
```

**Test End-to-End:**
```bash
./services/signal-cli/test_send_receive_confirm.py <recipient>
```

**Configuration Required:**
```yaml
signal_cli:
  account: "+15551234567"  # Your Signal phone number
  bus_name: "org.asamk.Signal"  # Optional D-Bus name
```

### Telegram

**API Style:** HTTPS Bot API via bot token

**Interface:**
```bash
./services/telegram/send_message.py <chat_id> <message> [--config <path>]
./services/telegram/receive_messages.py [--timeout <seconds>] [--limit <count>] [--offset <value>] [--config <path>]
./services/telegram/test_send_receive_confirm.py <chat_id> [--config <path>]
```

**Configuration Required:**
```yaml
telegram:
  api_base_url: https://api.telegram.org
  bot_token_env: TELEGRAM_BOT_TOKEN
  timeout_seconds: 30
  allowed_chat_ids:
    - 123456789
  allowed_updates:
    - message
  tls:
    ca_cert_path_env: TELEGRAM_CA_CERT
    insecure_skip_verify: false
```

### WhatsApp

**API Style:** Generic HTTPS gateway (Twilio adapter or self-hosted)

**Interface:**
```bash
./services/whatsapp/send_message.py <recipient> <message> [--config <path>]
./services/whatsapp/receive_messages.py [--timeout <seconds>] [--limit <count>] [--config <path>]
./services/whatsapp/test_send_receive_confirm.py <recipient> [--config <path>]
```

**Configuration Required:**
```yaml
http:
  base_url: https://example-whatsapp-gateway.local
  send_path: /messages
  receive_path: /messages/inbound
  api_key_env: WHATSAPP_API_KEY
  api_key_header: X-API-Key
  tls:
    ca_cert_path_env: WHATSAPP_CA_CERT
    insecure_skip_verify: false

messaging:
  from_env: WHATSAPP_FROM
  allowed_recipient_envs:
    - WHATSAPP_ALLOWED_RECIPIENTS
```

### Twilio SMS

**API Style:** HTTPS REST API

**Interface:**
```bash
./services/twilio/send_sms.py <to_number> <message> [--config <path>]
./services/twilio/receive_messages.py [--to <number>] [--from <number>] [--page-size <count>] [--limit <count>] [--config <path>]
./services/twilio/test_send_receive_confirm.py <recipient> [--config <path>]
```

**Configuration Required:**
```yaml
twilio:
  account_sid_env: TWILIO_ACCOUNT_SID
  auth_token_env: TWILIO_AUTH_TOKEN
  from_phone_env: TWILIO_FROM_PHONE
  api_base_url: https://api.twilio.com
  timeout_seconds: 30
  sms:
    enabled: true
    allowed_recipient_envs:
      - TWILIO_ALLOWED_RECIPIENTS
  tls:
    ca_cert_path_env: TWILIO_CA_CERT
    insecure_skip_verify: false
```

### Gmail IMAP

**API Style:** IMAP/SMTP protocols

**Interface:**
```bash
./services/gmail-imap/send_email.py <to> <subject> <body> [--config <path>]
./services/gmail-imap/check_inbox.py [--mailbox <name>] [--limit <count>] [--config <path>]
./services/gmail-imap/test_connection.py [--config <path>]
```

**Configuration Required:**
```yaml
imap:
  host: imap.gmail.com
  port: 993
  username_env: GMAIL_IMAP_USERNAME
  password_env: GMAIL_IMAP_APP_PASSWORD
  mailbox: INBOX
  mailboxes:
    - INBOX
  tls:
    ca_cert_path_env: GMAIL_IMAP_CA_CERT
    insecure_skip_verify: false

smtp:
  host: smtp.gmail.com
  port: 465
  username_env: GMAIL_IMAP_USERNAME
  password_env: GMAIL_IMAP_APP_PASSWORD
  from_env: GMAIL_IMAP_FROM
  allowed_recipient_envs:
    - GMAIL_IMAP_ALLOWED_RECIPIENTS
  tls:
    ca_cert_path_env: GMAIL_SMTP_CA_CERT
    insecure_skip_verify: false
```

## Error Handling

All scripts follow consistent exit code conventions:

- `0` - Success
- `1` - General error
- `2` - Configuration error (missing config file, invalid credentials)
- Non-zero - Service-specific error (exit code from underlying tool)

**Example Error Handling in Bash:**
```bash
#!/bin/bash

if ./services/signal-cli/send_message.py "+15551234567" "Test"; then
  echo "Message sent successfully"
else
  exit_code=$?
  if [ $exit_code -eq 2 ]; then
    echo "Configuration error - check config.local.yaml"
  else
    echo "Send failed with exit code: $exit_code"
  fi
  exit $exit_code
fi
```

**Example Error Handling in Python:**
```python
import subprocess

result = subprocess.run(
    ["./services/signal-cli/send_message.py", "+15551234567", "Test"],
    capture_output=True,
    text=True
)

if result.returncode == 0:
    print("Message sent successfully")
elif result.returncode == 2:
    print("Configuration error:", result.stderr)
else:
    print(f"Failed with code {result.returncode}:", result.stderr)
```

## Best Practices for AI Agents

### 1. Configuration Management
- Store config templates in version control
- Keep actual credentials in secure secret management (e.g., environment variables, HashiCorp Vault)
- Use separate config files per environment (dev, staging, prod)

### 2. Logging and Monitoring
- Capture stdout/stderr from scripts
- Log all message sends with timestamps
- Monitor for rate limits and failures
- Implement retry logic with exponential backoff

### 3. Security Considerations
- Never log or display full phone numbers in public logs
- Rotate API tokens regularly
- Use principle of least privilege for service accounts
- Validate recipient addresses before sending

### 4. Rate Limiting
Be aware of platform-specific rate limits:
- Signal: ~100 messages per minute per account
- Telegram: 30 messages per second per bot
- Twilio: Varies by account type
- WhatsApp: Highly restricted, requires business approval

### 5. Message Formatting
- Keep messages concise and actionable
- Use markdown when supported (Telegram, Signal)
- Consider character limits (SMS: 160 chars per segment)
- Format for mobile screens (short lines, clear structure)

## Example Agent Implementations

### Simple Monitoring Agent

```python
#!/usr/bin/env python3
import subprocess
import time

def send_alert(message):
    """Send alert via Signal"""
    subprocess.run([
        "./services/signal-cli/send_message.py",
        "+15551234567",
        f"🚨 ALERT: {message}"
    ], check=True)

def check_system():
    """Monitor system and send alerts"""
    while True:
        # Your monitoring logic here
        disk_usage = get_disk_usage()
        if disk_usage > 90:
            send_alert(f"Disk usage at {disk_usage}%")
        time.sleep(300)  # Check every 5 minutes

if __name__ == "__main__":
    check_system()
```

### Multi-Channel Notification Agent

```python
#!/usr/bin/env python3
import subprocess
from typing import List

class NotificationRelay:
    def __init__(self, channels: List[str]):
        self.channels = channels
    
    def send(self, message: str):
        """Send message to all configured channels"""
        for channel in self.channels:
            if channel == "signal":
                self._send_signal(message)
            elif channel == "telegram":
                self._send_telegram(message)
            # Add more channels as needed
    
    def _send_signal(self, message: str):
        subprocess.run([
            "./services/signal-cli/send_message.py",
            "+15551234567",
            message
        ])
    
    def _send_telegram(self, message: str):
        # Future implementation
        pass

# Usage
relay = NotificationRelay(channels=["signal", "telegram"])
relay.send("System deployed successfully")
```

## Testing

Each service includes test scripts to verify end-to-end functionality:

```bash
# Test Signal CLI send/receive
./services/signal-cli/test_send_receive_confirm.py "+15551234567"
```

For automated testing:
1. Use test phone numbers or accounts
2. Verify message delivery within timeout periods
3. Clean up test messages after verification
4. Mock external services in CI/CD environments

## Troubleshooting

### Common Issues

**Issue:** `ERROR: Cannot read config file`
- **Solution:** Copy `config.example.yaml` to `config.local.yaml` and configure

**Issue:** `ERROR: Missing signal_cli.account in config.local.yaml`
- **Solution:** Add your Signal phone number to the config file

**Issue:** `signal-cli failed with exit code`
- **Solution:** Verify signal-cli is installed and account is registered
- Run `signal-cli --version` to check installation

### Debug Mode

Enable verbose output:
```bash
# For Python scripts with logging support
LOGLEVEL=DEBUG ./services/signal-cli/send_message.py ...

# For shell scripts
bash -x ./services/signal-cli/send_message.sh ...
```

## Contributing

When implementing new services:

1. Follow the established patterns (config files, error codes, CLI interface)
2. Include both Python and shell script versions where practical
3. Add comprehensive test scripts
4. Update this guide with integration examples
5. Document service-specific rate limits and constraints

## Resources

- [Signal CLI Documentation](https://github.com/AsamK/signal-cli)
- [Telegram Bot API](https://core.telegram.org/bots/api)
- [Twilio API Docs](https://www.twilio.com/docs)
- [WhatsApp Business API](https://developers.facebook.com/docs/whatsapp)

## Support

For issues, questions, or contributions, please open an issue on the project repository.

## Agent Memory

Use `./LESSONSLEARNED.md` as the tracked durable lessons file for this repo.
Use `./CHATHISTORY.md` as the standard local handoff file for this repo.

- `LESSONSLEARNED.md` is tracked and should capture only reusable lessons.
- `CHATHISTORY.md` is local-only, gitignored, and should capture transient handoff context.
- Read `LESSONSLEARNED.md` and `CHATHISTORY.md` after `AGENTS.md` when resuming work.
- Add durable lessons to `LESSONSLEARNED.md` when they should influence future sessions.
- Keep transient entries brief and focused on service configs, script behavior, blockers, and next steps.
- Do not record live service tokens, credentials, or private endpoints in either file.
