"""
Telegram client setup and configuration.
"""

from telethon import TelegramClient
from typing import Dict, Any, Optional

from src.logger import setup_logger

# Setup logger
logger = setup_logger(__name__)


def create_client(api_id: int, api_hash: str, session_file: str, proxy_config: Optional[Dict[str, Any]] = None) -> TelegramClient:
    """
    Create and initialize a Telegram client.

    Args:
        api_id: Telegram API ID
        api_hash: Telegram API hash
        session_file: Path to the session file
        proxy_config: Optional proxy configuration

    Returns:
        Initialized TelegramClient
    """
    proxy = setup_proxy(proxy_config) if proxy_config else None

    # Initialize client using SQLite session file
    client = TelegramClient(
        session_file,
        api_id,
        api_hash,
        proxy=proxy
    )

    return client


def setup_proxy(proxy_config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Setup proxy from config.

    Args:
        proxy_config: Proxy configuration from config.json

    Returns:
        Proxy configuration for TelegramClient or None if invalid
    """
    # Skip if proxy server is not defined
    if not proxy_config.get('server'):
        return None

    proxy_type = proxy_config.get('type', '').lower()

    if proxy_type == 'mtproto':
        return {
            'proxy_type': 'mtproto',
            'addr': proxy_config['server'],
            'port': proxy_config['port'],
            'secret': proxy_config.get('secret', '')
        }
    elif proxy_type == 'socks5':
        return {
            'proxy_type': 'socks5',
            'addr': proxy_config['server'],
            'port': proxy_config['port'],
            'username': proxy_config.get('username', None),
            'password': proxy_config.get('password', None)
        }
    else:
        logger.warning(f"Unsupported proxy type: {proxy_type}")
        return None
