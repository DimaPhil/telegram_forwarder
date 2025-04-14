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
- **Docker Support**: Easy deployment with Docker and Docker Compose
- **Auto-restart Capability**: Both Docker and WSL scripts ensure the forwarder stays running

## Requirements

- Python 3.11
- Telegram account
- Telegram API credentials (API ID and API Hash)

## Installation

### Option 1: Standard Python Installation

1. Clone this repository:
   ```bash
   git clone git@github.com:DimaPhil/telegram_forwarder.git
   cd telegram-forwarder
   ```

2. Install the required dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Configure `config.json` and `forwarding_rules.json` with your implied data (more about that below)
 
4. Run the setup wizard:
   ```bash
   python main.py
   ```

### Option 2: Docker Installation

1. Clone this repository:
   ```bash
   git clone git@github.com:DimaPhil/telegram_forwarder.git
   cd telegram-forwarder
   ```

2. Create your configuration files (`config.json` and `forwarding_rules.json`) or run the setup wizard first:
   ```bash
   python main.py --setup
   ```

3. Build and start with Docker Compose:
   ```bash
   docker compose up -d
   ```

### Option 3: Windows WSL Installation

1. Clone this repository:
   ```bash
   git clone git@github.com:DimaPhil/telegram_forwarder.git
   cd telegram-forwarder
   ```

2. Install the required dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Run the setup wizard and then configure `config.json` and `forwarding_rules.json`:
   ```bash
   python main.py --setup
   ```

4. Make the WSL script executable:
   ```bash
   chmod +x run_wsl.sh
   ```

5. Run the WSL script:
   ```bash
   ./run_wsl.sh
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

## Running the Forwarder

### Option 1: Standard Python

```bash
python main.py
```

Command-line options:
- `--setup`: Run the interactive setup wizard
- `--config PATH`: Specify a custom config file path (default: `config.json`)
- `--rules PATH`: Specify a custom rules file path (default: `forwarding_rules.json`)
- `--session PATH`: Specify a custom session file path (default: `telegram_session`)
- `--log-level LEVEL`: Set logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)

### Option 2: Docker Compose

Start the forwarder:
```bash
docker compose up -d
```

Stop the forwarder:
```bash
docker compose down
```

View logs:
```bash
docker compose logs -f
```

### Option 3: WSL Script

Start the forwarder with auto-restart capability:
```bash
./run_wsl.sh
```

Stop the forwarder:
```bash
./stop_wsl.sh
```

## Logging

Logs are stored in the `logs` directory:
- `telegram_forwarder.log`: Main application logs
- `wsl_runner.log`: WSL runner logs (when using the WSL script)

When using Docker, logs are also stored in the `logs` directory on your host system, thanks to the volume mapping in the Docker Compose file.

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

Choose one of the running methods described above. When run for the first time, you'll be prompted to enter your phone number and verification code to authenticate with Telegram.

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
