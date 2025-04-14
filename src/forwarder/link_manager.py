"""
Message link extraction and handling for Telegram Message Forwarder.
"""

from typing import Dict, List, Any, Optional
from telethon import TelegramClient
from telethon.tl.functions.channels import GetMessagesRequest

from src.logger import setup_logger
from src.forwarder.utils import TG_LINK_PATTERN
from src.forwarder.entities import EntityManager

# Setup logger
logger = setup_logger(__name__)


class LinkManager:
    """
    Manages Telegram message links extraction and fetching.
    """

    def __init__(self, client: TelegramClient, entity_manager: EntityManager):
        """
        Initialize the LinkManager.

        Args:
            client: Initialized TelegramClient
            entity_manager: EntityManager instance
        """
        self.client = client
        self.entity_manager = entity_manager
        # Cache for resolved message links
        self.resolved_message_links = {}

    async def extract_message_links(self, message_text: str) -> List[Dict[str, Any]]:
        """
        Extract Telegram message links from text.

        Args:
            message_text: Text to extract links from

        Returns:
            List of extracted link data
        """
        if not message_text:
            return []

        links = []
        for match in TG_LINK_PATTERN.finditer(message_text):
            channel_id, username, msg_id, topic_id = match.groups()

            # Store the link details
            link_data = {
                'full_match': match.group(0),
                'message_id': int(msg_id)
            }

            # Handle channel ID (numeric format)
            if channel_id:
                # Note: Don't add -100 prefix here, will handle in fetch_linked_message
                link_data['chat_id'] = channel_id
            # Handle username format
            elif username:
                link_data['username'] = username

            # Handle topic ID if present
            if topic_id:
                link_data['topic_id'] = int(topic_id)

            links.append(link_data)
            logger.debug(f"Extracted message link: {link_data}")

        return links

    async def fetch_linked_message(self, link_data: Dict[str, Any]) -> Optional[Any]:
        """
        Fetch a message referenced by a Telegram link.

        Args:
            link_data: Link data from extract_message_links

        Returns:
            Message object or None if not found
        """
        # Check cache first
        cache_key = f"{link_data.get('chat_id', link_data.get('username'))}-{link_data['message_id']}"
        if cache_key in self.resolved_message_links:
            return self.resolved_message_links[cache_key]

        try:
            # Determine the chat
            chat = None
            if 'chat_id' in link_data:
                # For private/channel links with numeric IDs
                chat_id = link_data['chat_id']

                # If the chat_id is from the t.me/c/1234 format, it may need the -100 prefix
                if not str(chat_id).startswith('-100') and str(chat_id).isdigit():
                    chat_id = f"-100{chat_id}"

                chat = await self.entity_manager.get_entity(chat_id)
            else:
                # For public links with username
                chat = await self.entity_manager.get_entity(link_data['username'])

            if not chat:
                logger.warning(f"Could not resolve chat for link: {link_data['full_match']}")
                return None

            # Get the topic ID if available
            topic_id = link_data.get('topic_id')
            msg_id = link_data['message_id']

            # Try multiple approaches to fetch the message
            message = None

            # APPROACH 1: Standard get_messages
            try:
                message = await self.client.get_messages(chat, ids=msg_id)
                logger.debug(f"APPROACH 1 success for message {msg_id}: {message}")

                # Check if we got message text
                if message and (
                        (hasattr(message, 'message') and message.message) or
                        (hasattr(message, 'text') and message.text) or
                        (hasattr(message, 'raw_text') and message.raw_text)
                ):
                    logger.debug("APPROACH 1 retrieved message with text")
                else:
                    logger.debug("APPROACH 1 retrieved message without text")
            except Exception as e:
                logger.debug(f"APPROACH 1 failed: {str(e)}")

            # APPROACH 2: Use topic context if available
            if topic_id and (not message or not getattr(message, 'message', None)):
                try:
                    message_with_topic = await self.client.get_messages(
                        entity=chat,
                        ids=msg_id,
                        reply_to=topic_id
                    )
                    logger.debug(f"APPROACH 2 success for message {msg_id} in topic {topic_id}: {message_with_topic}")

                    # If we got a better result, use it
                    if message_with_topic and (
                            (hasattr(message_with_topic, 'message') and message_with_topic.message) or
                            (hasattr(message_with_topic, 'text') and message_with_topic.text) or
                            (hasattr(message_with_topic, 'raw_text') and message_with_topic.raw_text)
                    ):
                        logger.debug("APPROACH 2 retrieved message with text")
                        message = message_with_topic
                    else:
                        logger.debug("APPROACH 2 retrieved message without text")
                except Exception as e:
                    logger.debug(f"APPROACH 2 failed: {str(e)}")

            # APPROACH 3: Try to manually extract from the full message
            if not message or not (
                    getattr(message, 'message', None) or
                    getattr(message, 'text', None) or
                    getattr(message, 'raw_text', None)
            ):
                try:
                    # Get the full message without client-side processing
                    full_msg = await self.client(GetMessagesRequest(
                        peer=chat,
                        id=[msg_id]
                    ))

                    if full_msg and full_msg.messages and len(full_msg.messages) > 0:
                        raw_message = full_msg.messages[0]
                        logger.debug(f"APPROACH 3 retrieved raw message: {raw_message}")

                        # If our first message is empty but raw message has text, use it
                        if hasattr(raw_message, 'message') and raw_message.message:
                            if not message:
                                message = raw_message
                            # Otherwise, copy the text to our original message
                            elif hasattr(message, 'message'):
                                message.message = raw_message.message
                                logger.debug(f"APPROACH 3 added text from raw message: '{raw_message.message}'")
                except Exception as e:
                    logger.debug(f"APPROACH 3 failed: {str(e)}")

            # Final check
            if not message:
                logger.warning(f"Could not fetch message for link: {link_data['full_match']}")
                return None

            # Debug logging for the message we're returning
            logger.debug(f"Final message object: {message}")
            logger.debug(f"message attribute: '{getattr(message, 'message', None)}'")
            logger.debug(f"text attribute: '{getattr(message, 'text', None)}'")
            logger.debug(f"raw_text attribute: '{getattr(message, 'raw_text', None)}'")
            logger.debug(f"Has media: {message.media is not None}")

            # Let's add the message text as a custom attribute for easier access later
            if hasattr(message, 'message') and message.message:
                setattr(message, '_extracted_text', message.message)
            elif hasattr(message, 'text') and message.text:
                setattr(message, '_extracted_text', message.text)
            elif hasattr(message, 'raw_text') and message.raw_text:
                setattr(message, '_extracted_text', message.raw_text)
            else:
                setattr(message, '_extracted_text', '')

            logger.debug(f"Custom _extracted_text: '{getattr(message, '_extracted_text', '')}'")

            # Store in cache
            self.resolved_message_links[cache_key] = message
            return message

        except Exception as e:
            logger.error(f"Error fetching linked message {link_data['full_match']}: {str(e)}")
            return None
