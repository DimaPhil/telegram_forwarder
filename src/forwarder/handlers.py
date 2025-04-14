"""
Message event handlers for Telegram Message Forwarder.
"""

from typing import Dict, List, Any
from telethon import TelegramClient, events

from src.logger import setup_logger
from src.forwarder.utils import extract_message_text
from src.forwarder.entities import EntityManager
from src.forwarder.rules import RuleManager
from src.forwarder.processors import MessageProcessor
from src.forwarder.link_manager import LinkManager
from src.forwarder.forwarding import ForwardingManager

# Setup logger
logger = setup_logger(__name__)


class MessageHandler:
    """
    Handles incoming messages and coordinates processing and forwarding.
    """

    def __init__(
            self,
            client: TelegramClient,
            entity_manager: EntityManager,
            rule_manager: RuleManager,
            processor: MessageProcessor,
            link_manager: LinkManager,
            forwarding_manager: ForwardingManager
    ):
        """
        Initialize the MessageHandler.

        Args:
            client: Initialized TelegramClient
            entity_manager: EntityManager instance
            rule_manager: RuleManager instance
            processor: MessageProcessor instance
            link_manager: LinkManager instance
            forwarding_manager: ForwardingManager instance
        """
        self.client = client
        self.entity_manager = entity_manager
        self.rule_manager = rule_manager
        self.processor = processor
        self.link_manager = link_manager
        self.forwarding_manager = forwarding_manager

    def register_handlers(self):
        """Register message event handler."""

        @self.client.on(events.NewMessage)
        async def new_message_handler(event):
            await self.handle_new_message(event)

        logger.info("Message event handler registered")

    async def handle_new_message(self, event):
        """
        Handle new message event.

        Args:
            event: Message event
        """
        chat_id = event.chat_id
        message = event.message

        # Get message text for logging
        message_text = extract_message_text(message)

        # Log full message details for debugging
        logger.debug(f"Received message object: {message}")
        logger.debug(f"Message text (message attr): '{getattr(message, 'message', None)}'")
        logger.debug(f"Message text (text attr): '{getattr(message, 'text', None)}'")
        logger.debug(f"Message text (raw_text attr): '{getattr(message, 'raw_text', None)}'")
        logger.debug(f"Extracted message text: '{message_text}'")

        # Add the extracted text as a custom attribute for later use
        setattr(message, '_extracted_text', message_text)

        # Get sender ID for user filtering
        sender_id = None
        try:
            sender = await message.get_sender()
            if sender:
                sender_id = sender.id
        except Exception as e:
            logger.error(f"Error getting sender: {str(e)}")

        # Log detailed info for message investigation
        logger.debug(f"Chat ID: {chat_id}")
        logger.debug(f"Sender ID: {sender_id}")

        # Get topic ID
        topic_id = await self.processor.extract_topic_id(event)
        logger.debug(f"Topic ID: {topic_id}")

        # Check if we should forward this message based on chat, topic, and user
        forwarding_info = await self.rule_manager.should_forward(chat_id, topic_id, sender_id)

        if forwarding_info:
            logger.info(f"Will forward message with info: {forwarding_info}")

            # Check if we can directly forward from this chat
            can_forward = await self.entity_manager.can_forward_from_chat(chat_id)
            logger.debug(f"Can forward directly from chat {chat_id}: {can_forward}")

            # Process and handle the message
            await self.process_and_forward_message(event, forwarding_info, topic_id, can_forward)
        else:
            logger.debug(f"No forwarding rules matched for chat {chat_id}, topic {topic_id}, user {sender_id}")

    async def process_and_forward_message(self, event, forwarding_info, topic_id=None, can_forward_directly=True):
        """
        Process and forward a message with all features applied.

        Args:
            event: Message event
            forwarding_info: List of forwarding targets
            topic_id: Topic ID if applicable
            can_forward_directly: Whether direct forwarding is possible
        """
        message = event.message
        chat_id = event.chat_id

        # Additional content to include in the forwarded message
        additional_content = []

        # 1. Check if this message is a reply to another message
        is_genuine_reply = await self.processor.is_genuine_reply(message, topic_id)

        if is_genuine_reply:
            replied_content = await self.processor.process_replied_message(message, chat_id)
            if replied_content:
                additional_content.append(replied_content)

        # 2. Extract and process message links in the text
        message_links = []
        if message.text:
            message_links = await self.link_manager.extract_message_links(message.text)

        for link_data in message_links:
            try:
                linked_msg = await self.link_manager.fetch_linked_message(link_data)

                if linked_msg:
                    # Format the linked message
                    link_reference = link_data['full_match']
                    formatted_link = await self.processor.format_message_for_forwarding(linked_msg, linked_from=link_reference)
                    additional_content.append(formatted_link)
                    logger.debug(f"Added linked message {link_data['message_id']} to forwarded content")
            except Exception as e:
                logger.error(f"Error processing message link {link_data['full_match']}: {str(e)}")

        # Forward the message with additional content
        await self.forwarding_manager.forward_message(
            event,
            additional_content,
            topic_id,
            can_forward_directly,
            forwarding_info
        )
