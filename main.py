#!/usr/bin/env python3
"""
Telegram Message Forwarder

A Python-based tool that automatically forwards messages between
Telegram chats and topics using your personal account credentials.
"""

import os
import sys
import json
import asyncio
import argparse
from pathlib import Path

from src.logger import setup_logger
from src.forwarder import TelegramForwarder
from src.config import load_json, save_json

# Setup logger
logger = setup_logger("main", "logs/telegram_forwarder.log")


async def setup_wizard():
    """Interactive setup wizard for the forwarder"""
    print("Telegram Forwarder Setup")
    print("------------------------")

    # Create config directory if it doesn't exist
    os.makedirs("config", exist_ok=True)

    # Collect API credentials
    api_id = input("Enter your Telegram API ID: ")
    api_hash = input("Enter your Telegram API hash: ")

    # Optional proxy settings
    use_proxy = input("Do you want to use a proxy? (y/n): ").lower() == 'y'
    proxy_config = {
        "type": "",
        "server": "",
        "port": 0
    }

    if use_proxy:
        proxy_config["type"] = input("Enter proxy type (socks5/mtproto): ").lower()
        proxy_config["server"] = input("Enter proxy server address: ")
        try:
            proxy_config["port"] = int(input("Enter proxy port: "))
        except ValueError:
            print("Invalid port number. Using default port 0.")
            proxy_config["port"] = 0

        if proxy_config["type"] == "socks5":
            use_auth = input("Does your SOCKS5 proxy require authentication? (y/n): ").lower() == 'y'
            if use_auth:
                proxy_config["username"] = input("Enter proxy username: ")
                proxy_config["password"] = input("Enter proxy password: ")
        elif proxy_config["type"] == "mtproto":
            proxy_config["secret"] = input("Enter MTProto secret (or leave empty): ")

    # Create config file
    config = {
        "api_id": int(api_id),
        "api_hash": api_hash,
        "proxy": proxy_config
    }

    config_path = "config.json"
    save_json(config_path, config)

    # Create empty rules file if it doesn't exist
    rules_path = "forwarding_rules.json"
    if not os.path.exists(rules_path):
        save_json(rules_path, {})

    print("\nSetup complete! Config files have been created.")
    print("Next, run the program without arguments to start the forwarder.")
    print("You'll be prompted to log in with your phone number the first time.")


async def main():
    """Main entry point for the application"""
    # Ensure logs directory exists
    os.makedirs("logs", exist_ok=True)

    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Telegram Message Forwarder")
    parser.add_argument("--setup", action="store_true", help="Run interactive setup")
    parser.add_argument("--config", type=str, default="config.json", help="Path to config file")
    parser.add_argument("--rules", type=str, default="forwarding_rules.json", help="Path to forwarding rules file")
    parser.add_argument("--session", type=str, default="telegram_session", help="Path to session file")
    parser.add_argument("--log-level", type=str, default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
                        help="Set logging level")
    args = parser.parse_args()

    # Run setup wizard if requested
    if args.setup:
        await setup_wizard()
        return

    # Start the forwarder
    try:
        logger.info("Starting Telegram Forwarder")
        forwarder = TelegramForwarder(
            config_path=args.config,
            rules_path=args.rules,
            session_file=args.session
        )
        await forwarder.start()
    except KeyboardInterrupt:
        logger.info("Forwarder stopped by user")
        print("\nForwarder stopped by user.")
    except Exception as e:
        logger.error(f"Error in main: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
