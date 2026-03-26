# Claude AI Integration Guide

This guide is specifically designed for Claude AI agents interacting with shock-relay. It provides patterns and examples optimized for Claude's tool-use capabilities.

## Overview

shock-relay is designed to work seamlessly with Claude's ability to execute bash commands and write files. This guide shows you how to leverage shock-relay for notifications, alerts, and two-way communication in your Claude-powered workflows.

## Quick Integration

### Using the Bash Tool

Claude can directly execute shock-relay scripts using the Bash tool:

```python
# Send a Signal message
<bash>
./services/signal-cli/send_message.py "+15551234567" "Task completed successfully"
</bash>

# Listen for incoming messages
<bash>
./services/signal-cli/receive_messages.py --timeout 30
</bash>
```

### Configuration Setup

Before using shock-relay, Claude can help set up the configuration:

1. **Copy example config:**
```python
<bash>
cp services/signal-cli/config.example.yaml services/signal-cli/config.local.yaml
</bash>
```

2. **Edit configuration with Write tool:**
```python
<write file="services/signal-cli/config.local.yaml">
service:
  name: signal-cli
  enabled: true

runtime:
  log_level: info

paths:
  data_dir: ./data/signal-cli

signal_cli:
  account: "+15551234567"  # Your phone number
  executable: signal-cli
</write>
```

## Use Cases for Claude

### 1. Task Completion Notifications

Notify users when long-running tasks complete:

```python
# After processing files, send notification
<bash>
./services/signal-cli/send_message.py "+15551234567" \
  "Analysis complete: 150 files processed, 3 errors found"
</bash>
```

### 2. Error Alerting

Send immediate alerts when errors occur:

```python
import subprocess

try:
    # Your code here
    result = process_data()
except Exception as e:
    subprocess.run([
        "./services/signal-cli/send_message.py",
        "+15551234567",
        f"⚠️ Error in data processing: {str(e)}"
    ])
    raise
```

### 3. Interactive Workflows

Create two-way communication with users:

```python
# Send question and wait for response
<bash>
./services/signal-cli/send_message.py "+15551234567" \
  "Should I proceed with deployment? Reply YES or NO"
</bash>

# Wait for and check response
<bash>
./services/signal-cli/receive_messages.py --timeout 60
</bash>
```

### 4. Status Updates

Send periodic progress updates:

```python
#!/usr/bin/env python3
import subprocess
import time

def send_status(message):
    subprocess.run([
        "./services/signal-cli/send_message.py",
        "+15551234567",
        message
    ])

# During long operation
total = 1000
for i in range(0, total, 100):
    # Process batch
    process_batch(i, i+100)
    
    # Send update every 10%
    progress = (i / total) * 100
    send_status(f"Progress: {progress:.0f}% complete")
    
send_status("✅ Processing complete!")
```

### 5. Multi-Channel Broadcasting

Send notifications to multiple platforms:

```python
#!/usr/bin/env python3
import subprocess
from typing import List

def broadcast(message: str, channels: List[str]):
    """Send message to multiple channels"""
    for channel in channels:
        if channel == "signal":
            subprocess.run([
                "./services/signal-cli/send_message.py",
                "+15551234567",
                message
            ])
        elif channel == "telegram":
            # Future implementation
            pass

# Usage
broadcast("Deployment successful!", ["signal", "telegram"])
```

## Integration Patterns

### Pattern 1: Simple Subprocess Calls

Most straightforward for one-off notifications:

```python
import subprocess

subprocess.run([
    "./services/signal-cli/send_message.py",
    "+15551234567",
    "Hello from Claude!"
])
```

### Pattern 2: Environment Variables

Cleaner for dynamic messages:

```python
import subprocess
import os

os.environ["SIGNAL_CLI_MESSAGE"] = "Dynamic message content"
subprocess.run([
    "./services/signal-cli/send_message.py",
    "+15551234567"
])
```

### Pattern 3: Helper Functions

Reusable notification layer:

```python
#!/usr/bin/env python3
import subprocess
from pathlib import Path

class ShockRelay:
    def __init__(self, service="signal-cli", recipient=None):
        self.service = service
        self.recipient = recipient
        self.base_path = Path(__file__).parent / "services" / service
    
    def send(self, message: str, recipient: str = None):
        """Send a message via configured service"""
        recipient = recipient or self.recipient
        if not recipient:
            raise ValueError("No recipient specified")
        
        script = self.base_path / "send_message.py"
        subprocess.run([str(script), recipient, message], check=True)
    
    def receive(self, timeout: int = 30):
        """Receive messages from configured service"""
        script = self.base_path / "receive_messages.py"
        result = subprocess.run(
            [str(script), "--timeout", str(timeout)],
            capture_output=True,
            text=True
        )
        return result.stdout

# Usage
relay = ShockRelay(recipient="+15551234567")
relay.send("Hello from helper function!")
messages = relay.receive(timeout=10)
```

## Error Handling for Claude

Claude should handle errors gracefully:

```python
import subprocess

def send_with_retry(recipient: str, message: str, max_retries: int = 3):
    """Send message with retry logic"""
    for attempt in range(max_retries):
        result = subprocess.run(
            ["./services/signal-cli/send_message.py", recipient, message],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            return True
        elif result.returncode == 2:
            print("Configuration error:", result.stderr)
            return False  # Don't retry config errors
        else:
            print(f"Attempt {attempt + 1} failed, retrying...")
            time.sleep(2 ** attempt)  # Exponential backoff
    
    return False
```

## Configuration Management

### Reading Current Config

Claude can read and verify configuration:

```python
<read file="services/signal-cli/config.local.yaml">
```

### Updating Config

Use MultiEdit for surgical updates:

```python
<multiedit file="services/signal-cli/config.local.yaml">
- old: "log_level: info"
  new: "log_level: debug"
</multiedit>
```

## Best Practices for Claude

### 1. Validate Before Sending

```python
import re

def is_valid_phone(phone: str) -> bool:
    """Validate phone number format"""
    pattern = r'^\+\d{10,15}$'
    return bool(re.match(pattern, phone))

# Use before sending
if is_valid_phone(recipient):
    send_message(recipient, message)
else:
    print(f"Invalid phone number: {recipient}")
```

### 2. Format Messages for Mobile

```python
def format_mobile_message(title: str, items: List[str]) -> str:
    """Format message for mobile viewing"""
    message = f"*{title}*\n\n"
    for item in items:
        message += f"• {item}\n"
    return message

# Usage
msg = format_mobile_message(
    "Task Results",
    ["3 files processed", "0 errors", "Runtime: 2.3s"]
)
```

### 3. Handle Long Messages

```python
def split_message(text: str, max_length: int = 1000) -> List[str]:
    """Split long messages into chunks"""
    if len(text) <= max_length:
        return [text]
    
    chunks = []
    while text:
        if len(text) <= max_length:
            chunks.append(text)
            break
        
        # Find last space before max_length
        split_at = text.rfind(' ', 0, max_length)
        if split_at == -1:
            split_at = max_length
        
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip()
    
    return chunks

# Send in parts
for i, chunk in enumerate(split_message(long_text), 1):
    send_message(recipient, f"[{i}/{len(chunks)}] {chunk}")
```

### 4. Log All Notifications

```python
import logging
from datetime import datetime

logging.basicConfig(
    filename='shock-relay.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def send_logged(recipient: str, message: str):
    """Send message with logging"""
    logging.info(f"Sending to {recipient[:8]}...: {message[:50]}...")
    result = subprocess.run([
        "./services/signal-cli/send_message.py",
        recipient,
        message
    ])
    if result.returncode == 0:
        logging.info("Message sent successfully")
    else:
        logging.error(f"Failed with code {result.returncode}")
```

## Testing

### Test Configuration

```bash
# Verify config exists
<bash>
test -f services/signal-cli/config.local.yaml && echo "Config found" || echo "Config missing"
</bash>

# Check if signal-cli is installed
<bash>
which signal-cli
</bash>
```

### Test End-to-End

```bash
# Send test message and verify
<bash>
./services/signal-cli/test_send_receive_confirm.py "+15551234567"
</bash>
```

## Troubleshooting

### Common Issues Claude May Encounter

**Issue: "Cannot read config file"**
```bash
# Check if config exists
<bash>
ls -la services/signal-cli/config.local.yaml
</bash>

# Create from example if missing
<bash>
cp services/signal-cli/config.example.yaml services/signal-cli/config.local.yaml
</bash>
```

**Issue: "signal-cli command not found"**
```bash
# Check installation
<bash>
which signal-cli || echo "signal-cli not installed"
</bash>
```

**Issue: "Permission denied"**
```bash
# Make scripts executable
<bash>
chmod +x services/signal-cli/*.py
</bash>
```

## Advanced Patterns

### Async Notifications

For long-running Claude tasks:

```python
import subprocess
import threading

def send_async(recipient: str, message: str):
    """Send message without blocking"""
    thread = threading.Thread(
        target=subprocess.run,
        args=([
            "./services/signal-cli/send_message.py",
            recipient,
            message
        ],)
    )
    thread.start()

# Won't block Claude's main thread
send_async("+15551234567", "Processing started...")
do_long_running_task()
send_async("+15551234567", "Processing complete!")
```

### Message Queue

For batch notifications:

```python
from queue import Queue
import threading

class NotificationQueue:
    def __init__(self, recipient: str):
        self.queue = Queue()
        self.recipient = recipient
        self.thread = threading.Thread(target=self._worker)
        self.thread.daemon = True
        self.thread.start()
    
    def _worker(self):
        while True:
            message = self.queue.get()
            if message is None:
                break
            subprocess.run([
                "./services/signal-cli/send_message.py",
                self.recipient,
                message
            ])
            self.queue.task_done()
    
    def send(self, message: str):
        self.queue.put(message)

# Usage
notifier = NotificationQueue("+15551234567")
notifier.send("First message")
notifier.send("Second message")
notifier.send("Third message")
```

## Security Considerations

1. **Never log full phone numbers** - Redact in logs
2. **Validate all inputs** - Check recipient format before sending
3. **Use environment variables** - For credentials and sensitive config
4. **Sanitize message content** - Escape special characters if needed

## Resources

- [Main README](README.md) - Project overview
- [AGENTS.md](AGENTS.md) - General AI agent integration
- [Signal CLI Docs](https://github.com/AsamK/signal-cli)

## Getting Help

If Claude encounters issues:

1. Check configuration files exist and are valid YAML
2. Verify external dependencies (signal-cli) are installed
3. Test with simple send/receive operations first
4. Check error codes and stderr output for diagnostics

Remember: shock-relay is designed to be simple and scriptable, making it ideal for Claude's tool-use capabilities!
