"""
Core TelegramForwarder class for the Telegram Message Forwarder.
"""

import sys
from typing import Dict, Any, Optional

from src.logger import setup_logger
from src.config import load_json, save_json
from src.forwarder.client import create_client
from src.forwarder.entities import EntityManager
from src.forwarder.rules import RuleManager
from src.forwarder.processors import MessageProcessor
from src.forwarder.link_manager import LinkManager
from src.forwarder.forwarding import ForwardingManager
from src.forwarder.handlers import MessageHandler
from src.forwarder.debug import DebugHandler

# Setup logger
logger = setup_logger(__name__)


class TelegramForwarder:
    """
    Main class for forwarding messages between Telegram chats/topics.
    The class orchestrates all the components required for message forwarding.
    """

    def __init__(self, config_path="config.json", rules_path="forwarding_rules.json", session_file="telegram_session"):
        """
        Initialize the TelegramForwarder with configuration.

        Args:
            config_path: Path to the main configuration file
            rules_path: Path to the forwarding rules file
            session_file: Path to the Telethon session file
        """
        self.config_path = config_path
        self.rules_path = rules_path
        self.session_file = session_file

        # Load configuration
        self.config = load_json(config_path)
        self.forwarding_rules = load_json(rules_path)

        # Initialize client
        self.client = create_client(
            api_id=self.config['api_id'],
            api_hash=self.config['api_hash'],
            session_file=self.session_file,
            proxy_config=self.config.get('proxy') if 'proxy' in self.config and self.config['proxy'].get('server') else None
        )

        # Initialize components
        self.entity_manager = EntityManager(self.client)
        self.rule_manager = RuleManager(self.forwarding_rules)
        self.processor = MessageProcessor(self.client)
        self.link_manager = LinkManager(self.client, self.entity_manager)
        self.forwarding_manager = ForwardingManager(self.client, self.entity_manager, self.processor)

        # Initialize handlers
        self.message_handler = MessageHandler(
            self.client,
            self.entity_manager,
            self.rule_manager,
            self.processor,
            self.link_manager,
            self.forwarding_manager
        )

        self.debug_handler = DebugHandler(
            self.client,
            self.entity_manager,
            self.link_manager
        )

    async def check_forwarding_rules(self):
        """Check and setup forwarding rules if needed."""
        await self.rule_manager.setup_interactive(self.rules_path)

    async def start(self):
        """Start the forwarder with automatic login if needed."""
        # Verify API credentials exist
        if not self.config['api_id'] or not self.config['api_hash']:
            logger.error("API credentials missing in config.json")
            print("\nPlease update config.json with your Telegram API credentials:")
            api_id = input("Enter your Telegram API ID: ")
            api_hash = input("Enter your Telegram API hash: ")

            # Update config with new values
            self.config['api_id'] = int(api_id)
            self.config['api_hash'] = api_hash

            # Save updated config
            save_json(self.config_path, self.config)

            # Update client with new credentials
            self.client = create_client(
                api_id=self.config['api_id'],
                api_hash=self.config['api_hash'],
                session_file=self.session_file,
                proxy_config=self.config.get('proxy') if 'proxy' in self.config and self.config['proxy'].get('server') else None
            )

            # Re-initialize components with new client
            self.entity_manager = EntityManager(self.client)
            self.link_manager = LinkManager(self.client, self.entity_manager)
            self.processor = MessageProcessor(self.client)
            self.forwarding_manager = ForwardingManager(self.client, self.entity_manager, self.processor)
            self.message_handler = MessageHandler(
                self.client,
                self.entity_manager,
                self.rule_manager,
                self.processor,
                self.link_manager,
                self.forwarding_manager
            )
            self.debug_handler = DebugHandler(
                self.client,
                self.entity_manager,
                self.link_manager
            )

        # Check if forwarding rules exist and offer to create them if not
        await self.check_forwarding_rules()

        # Register event handlers
        self.debug_handler.register_handlers()
        self.message_handler.register_handlers()

        try:
            # Start client (will automatically prompt for phone/code if not logged in)
            await self.client.start()
            logger.info("Client started successfully")
            me = await self.client.get_me()
            logger.info(f"Logged in as: {me.first_name} (@{me.username})")

            print(f"\nForwarder is running for account: {me.first_name} (@{me.username})")
            print("Listening for new messages to forward based on configuration...")
            print("Press Ctrl+C to stop\n")

            # Keep the client running
            await self.client.run_until_disconnected()
        except Exception as e:
            logger.error(f"Error starting client: {str(e)}")
            sys.exit(1)
