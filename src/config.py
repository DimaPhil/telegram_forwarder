"""
Configuration handling for the Telegram Message Forwarder.
"""

import json
import os
import sys
from typing import Dict, Any, Optional

from src.logger import setup_logger

# Setup logger
logger = setup_logger(__name__)


def load_json(file_path: str) -> Dict[str, Any]:
    """
    Load JSON configuration file or create default if not found.

    Args:
        file_path: Path to the JSON file

    Returns:
        Loaded JSON data as dictionary

    Raises:
        SystemExit: If file has invalid JSON format
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            return json.load(file)
    except FileNotFoundError:
        logger.warning(f"Configuration file not found: {file_path}")

        # Create default config file if it's the main config
        if os.path.basename(file_path) == 'config.json':
            logger.info("Creating default config file. You'll need to update it with your API credentials.")
            default_config = {
                "api_id": 0,
                "api_hash": "",
                "proxy": {
                    "type": "",
                    "server": "",
                    "port": 0
                }
            }
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(default_config, f, indent=4)
            return default_config

        # Create empty rules file if it's the rules file
        elif os.path.basename(file_path) == 'forwarding_rules.json':
            logger.info("Creating empty forwarding rules file.")
            empty_rules = {}
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(empty_rules, f, indent=4)
            return empty_rules

        logger.error(f"Unknown configuration file: {file_path}")
        sys.exit(1)
    except json.JSONDecodeError:
        logger.error(f"Invalid JSON in configuration file: {file_path}")
        sys.exit(1)


def save_json(file_path: str, data: Dict[str, Any]) -> None:
    """
    Save dictionary to JSON file.

    Args:
        file_path: Path to save the JSON file
        data: Dictionary to save
    """
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4)
        logger.debug(f"Successfully saved data to {file_path}")
    except Exception as e:
        logger.error(f"Failed to save data to {file_path}: {str(e)}")
