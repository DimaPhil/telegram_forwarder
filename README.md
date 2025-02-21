# Telegram Message Forwarder

A Python-based tool that automatically forwards messages between Telegram chats and topics using your personal account credentials.

## Features

- **User Account Authentication**: Operates under your Telegram user credentials (not a bot)
- **Flexible Forwarding Rules**: Configure forwarding by chat or specific topics
- **Topic Support**: Full support for Telegram topics in both source and destination chats
- **MTProto Proxy Support**: Connect through MTProto proxy for enhanced privacy/accessibility
- **Source Attribution**: Automatically includes source chat/topic information in forwarded messages
- **Performance Optimized**: Caches chat entities and topic information for faster operation
- **Detailed Logging**: Comprehensive logging for monitoring and troubleshooting

## Requirements

- Python 3.11
- Telegram account
- Telegram API credentials (API ID and API Hash)

## Installation

1. Clone this repository:
   ```bash
   git clone https://github.com/yourusername/telegram-forwarder.git
   cd telegram-forwarder
   ```

2. Install the required dependencies:
   ```bash
   pip install telethon
   ```

## Configuration

The forwarder requires two configuration files:

### 1. `config.json`

Contains your Telegram API credentials and proxy settings:

```json
{
    "api_id": 123456,
    "api_hash": "your_api_hash_here",
}
```

`"proxy"` can be left unconfigured.

### 2. `forwarding_rules.json`

Defines which messages should be forwarded and where:

```json
{
    "-100123456789": {
        "*": [
            {
                "chat_id": "-100987654321",
                "topic_id": null
            }
        ]
    },
    "-100111222333": {
        "1": [
            {
                "chat_id": "-100444555666",
                "topic_id": 123
            }
        ],
        "2": [
            {
                "chat_id": "-100777888999",
                "topic_id": null
            }
        ],
        "3": [
            {
                "chat_id": "lilfeel",
                "topic_id": null
            }
        ]
    }
}
```

In this example:
- All messages from chat `-100123456789` will be forwarded to chat `-100987654321`
- Messages from topic `1` in chat `-100111222333` will be forwarded to topic `123` in chat `-100444555666`
- Messages from topic `2` in chat `-100111222333` will be forwarded to chat `-100777888999` (no specific topic)
- Messages from topic `3` in chat `-100111222333` will be forwarded to `@lilfeel` (no specific topic)

## Getting Started

### Step 1: Obtain Telegram API Credentials

1. Visit https://my.telegram.org and log in
2. Go to "API development tools"
3. Create a new application
4. Note down your API ID and API Hash

### Step 2: Configure Forwarding Rules

Edit the `forwarding_rules.json` file to specify your forwarding rules:

- Use `"*"` to forward all messages from a chat
- Or specify topic IDs to forward only specific topics

**Finding Chat IDs:**
- Forward a message from the chat to @userinfobot
- For supergroups and channels, the ID format is `-100xxxxxxxxxx`

**Finding Topic IDs:**
- Open the topic in a web browser
- The topic ID is the number at the end of the URL (after "/topic/")

### Step 4: Run the Forwarder

Start the forwarder:

```bash
python forwarder.py
```

The script will connect to Telegra (you will have to input your phone number, code, and 2fa) and begin forwarding messages according to your rules.

## Running as a Service

For 24/7 operation, it's recommended to run the forwarder as a service.

### Using systemd (Linux)

Create a systemd service file:

```bash
sudo nano /etc/systemd/system/telegram-forwarder.service
```

Add the following content:

```
[Unit]
Description=Telegram Message Forwarder
After=network.target

[Service]
User=yourusername
WorkingDirectory=/path/to/telegram-forwarder
ExecStart=/usr/bin/python3 /path/to/telegram-forwarder/telegram_forwarder.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start the service:

```bash
sudo systemctl enable telegram-forwarder
sudo systemctl start telegram-forwarder
```

Check status:

```bash
sudo systemctl status telegram-forwarder
```

### Using screen

You can also use `screen` to run your script.

```bash
screen -S tg_forwarder # open a new screen

python3 forwarder.py # run the script inside the screen

# Press Ctrl+A and then D to detach the session
```

Then, when you need to see the session again, reattach
```bash
screen -r tg_forwarder

# Press Ctrl+A and then D to detach the session again
```

## Security Considerations

- The script uses your Telegram user account credentials
- Keep your `config.json` file secure as it contains sensitive information
- Consider restricting file permissions:
  ```bash
  chmod 600 config.json
  ```

## License

[MIT License](LICENSE)

## Disclaimer

This tool is for personal use only. It uses your user account, not a bot account. Please ensure your usage complies with Telegram's Terms of Service.
