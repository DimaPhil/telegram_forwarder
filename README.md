# Telegram Message Forwarder

A Python-based tool that automatically forwards messages between Telegram chats and topics using your personal account credentials.

## Features

- **User Account Authentication**: Operates under your Telegram user credentials (not a bot)
- **Flexible Forwarding Rules**: Configure forwarding by chat or specific topics
- **Topic Support**: Full support for Telegram topics in both source and destination chats
- **User Filtering**: Forward messages only from specific users
- **Reply Content Forwarding**: Includes the original message content when forwarding replies
- **Message Link Processing**: Automatically includes content from any Telegram message links in the text
- **Media Handling**: Properly forwards media attachments from both original messages and linked content
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
    "proxy": {
        "type": "",
        "server": "",
        "port": 0
    }
}
```

`"proxy"` can be left unconfigured if not needed.

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
                "topic_id": 123,
                "user_ids": [12345678, 87654321]
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
                "chat_id": "@username",
                "topic_id": null
            }
        ]
    }
}
```

In this example:
- All messages from chat `-100123456789` will be forwarded to chat `-100987654321`
- Messages from topic `1` in chat `-100111222333` will be forwarded to topic `123` in chat `-100444555666`, but only if sent by users with IDs `12345678` or `87654321`
- Messages from topic `2` in chat `-100111222333` will be forwarded to chat `-100777888999` (no specific topic)
- Messages from topic `3` in chat `-100111222333` will be forwarded to `@username` (no specific topic)

### Special Features Configuration

#### User Filtering
Add a `user_ids` array to any forwarding rule to only forward messages from specific users:
```json
"user_ids": [12345678, 87654321]
```

#### Reply and Link Forwarding
The script automatically:
- Includes content of messages being replied to in the forwarded message
- Detects Telegram message links in the text (like `https://t.me/c/1234567890/123`) and includes the linked message content
- Handles media attachments from both the original message and any linked content

## Getting Started

### Step 1: Obtain Telegram API Credentials

1. Visit https://my.telegram.org and log in
2. Go to "API development tools"
3. Create a new application
4. Note down your API ID and API Hash

### Step 2: Configure Forwarding Rules

Edit the `forwarding_rules.json` file to specify your forwarding rules:

- Use `"*"` to forward all messages from a chat
- Specify topic IDs to forward only specific topics
- Add `user_ids` array to filter by specific users

**Finding Chat IDs:**
- Forward a message from the chat to @userinfobot
- For supergroups and channels, the ID format is `-100xxxxxxxxxx`

**Finding Topic IDs:**
- Open the topic in a web browser
- The topic ID is the number at the end of the URL (after "/topic/")

**Finding User IDs:**
- Forward a message from the user to @userinfobot
- The user ID will be displayed

### Step 3: Run the Forwarder

Start the forwarder:

```bash
python forwarder.py
```

Or use the setup mode to interactively configure the forwarder:

```bash
python forwarder.py setup
```

The script will connect to Telegram (you will have to input your phone number, code, and 2FA if enabled) and begin forwarding messages according to your rules.

### Using screen

You can also use `screen` to run your script in the background:

```bash
screen -S tg_forwarder # open a new screen

python3 forwarder.py # run the script inside the screen

# Press Ctrl+A and then D to detach the session
```

Then, when you need to see the session again, reattach:
```bash
screen -r tg_forwarder

# Press Ctrl+A and then D to detach the session again
```

## Debug Commands

The forwarder provides several debug commands when you message the bot privately:

- `/debugtopic` - Show topic information for your message
- `/debugchat -100xxxx` - Show information about a specific chat
- `/debuglinks` - Test message link extraction from your message
- `/help` - Show all available commands

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