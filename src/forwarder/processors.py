"""
Message processing functionality for Telegram Message Forwarder.
"""

from typing import Dict, List, Any, Optional, Union, Tuple
from telethon import TelegramClient
from telethon.tl.types import MessageMediaWebPage

from src.logger import setup_logger
from src.forwarder.utils import extract_message_text, get_media_type_name

# Setup logger
logger = setup_logger(__name__)


class MessageProcessor:
    """
    Processes messages for forwarding, including handling replies and formatting.
    """

    def __init__(self, client: TelegramClient):
        """
        Initialize the MessageProcessor.

        Args:
            client: Initialized TelegramClient
        """
        self.client = client

    async def format_message_for_forwarding(self, message: Any, is_reply: bool = False, linked_from: Optional[str] = None) -> Dict[str, Any]:
        """
        Format a message for inclusion in a forwarded message.

        Args:
            message: Message to format
            is_reply: Whether this is a reply message
            linked_from: Link reference if this is a linked message

        Returns:
            Formatted message data
        """
        # Get sender information
        try:
            sender = await message.get_sender()
            sender_name = getattr(sender, 'first_name', '') or ''
            if getattr(sender, 'last_name', ''):
                sender_name += f" {sender.last_name}"
            if getattr(sender, 'username', ''):
                sender_name += f" (@{sender.username})"
            if not sender_name:
                sender_name = f"User {sender.id}" if hasattr(sender, 'id') else "Unknown User"
        except Exception as e:
            logger.error(f"Error getting sender: {str(e)}")
            sender_name = "Unknown User"

        # Prepare the formatted message
        if is_reply:
            prefix = "⤴️ **In reply to:**\n"
        elif linked_from:
            # Fix the formatting - make sure the colon is before the URL, not after
            prefix = f"🔗 **Linked message:** {linked_from}\n"
        else:
            prefix = ""

        # Get message text - using multiple methods to ensure we get the content
        message_text = ""

        # First check if we have the custom extracted text
        if hasattr(message, '_extracted_text') and message._extracted_text:
            message_text = message._extracted_text
            logger.debug(f"Using _extracted_text: '{message_text}'")
        # Then try standard message attributes
        elif hasattr(message, 'message') and message.message:
            message_text = message.message
            logger.debug(f"Using message.message: '{message_text}'")
        elif hasattr(message, 'text') and message.text:
            message_text = message.text
            logger.debug(f"Using message.text: '{message_text}'")
        elif hasattr(message, 'raw_text') and message.raw_text:
            message_text = message.raw_text
            logger.debug(f"Using message.raw_text: '{message_text}'")

        # Try one more approach - directly access the internal dictionary
        if not message_text and hasattr(message, 'to_dict'):
            try:
                msg_dict = message.to_dict()
                logger.debug(f"Message dictionary: {msg_dict}")
                if 'message' in msg_dict:
                    message_text = msg_dict['message']
                    logger.debug(f"Found text in dictionary: '{message_text}'")
            except Exception as e:
                logger.debug(f"Failed to extract from dictionary: {str(e)}")

        # Handle case with media but no text
        if not message_text and message.media:
            media_type = get_media_type_name(message.media)
            message_text = f"[Message with {media_type}]"
            logger.debug(f"Using media type indicator: '{message_text}'")
        elif not message_text:
            message_text = "[Empty message]"
            logger.debug("Using empty message indicator")

        # Format the message text
        formatted_text = f"{prefix}**{sender_name}:** {message_text}"
        logger.debug(f"Final formatted text: '{formatted_text}'")

        return {
            "text": formatted_text,
            "media": message.media,
            "entities": message.entities
        }

    async def extract_topic_id(self, event: Any) -> Optional[int]:
        """
        Extract topic ID from a message event.

        Args:
            event: Message event

        Returns:
            Topic ID or None if not a topic message
        """
        message = event.message
        chat_id = event.chat_id
        topic_id = None

        # Get the chat entity to check if it's a forum
        try:
            entity = await self.client.get_entity(chat_id)
            is_forum = getattr(entity, 'forum', False)
            logger.debug(f"Chat {chat_id} is forum: {is_forum}")

            # If not a forum, don't try to get topic_id
            if not is_forum:
                logger.debug(f"Chat {chat_id} is not a forum, skipping topic detection")
                return None

            # Check for topic attribute in modern Telegram clients
            if hasattr(message, 'topic_id'):
                topic_id = message.topic_id
                logger.debug(f"Found topic_id from message.topic_id: {topic_id}")
            elif hasattr(message, 'topic'):
                topic_id = message.topic
                logger.debug(f"Found topic_id from message.topic: {topic_id}")
            # Then try the legacy reply_to methods
            elif message.reply_to:
                reply_to = message.reply_to
                logger.debug(f"Message has reply_to: {reply_to}")

                # Check for forum_topic flag
                if hasattr(reply_to, 'forum_topic') and reply_to.forum_topic:
                    logger.debug("Reply has forum_topic flag")
                    if hasattr(reply_to, 'top_msg_id'):
                        topic_id = reply_to.top_msg_id
                        logger.debug(f"Found topic_id from reply_to.top_msg_id: {topic_id}")
                    elif hasattr(reply_to, 'reply_to_top_id'):
                        topic_id = reply_to.reply_to_top_id
                        logger.debug(f"Found topic_id from reply_to.reply_to_top_id: {topic_id}")
                # Try other attributes
                elif hasattr(reply_to, 'reply_to_top_id'):
                    topic_id = reply_to.reply_to_top_id
                    logger.debug(f"Found topic_id from reply_to.reply_to_top_id: {topic_id}")
                elif hasattr(reply_to, 'top_msg_id'):
                    topic_id = reply_to.top_msg_id
                    logger.debug(f"Found topic_id from reply_to.top_msg_id: {topic_id}")

                # If we still don't have a topic_id, try to get from reply_to_msg_id for forums
                if topic_id is None and hasattr(reply_to, 'reply_to_msg_id'):
                    # In some cases, the first message in a topic has the same ID as the topic
                    reply_msg_id = reply_to.reply_to_msg_id
                    logger.debug(f"Checking if reply_to_msg_id {reply_msg_id} is a topic ID")

                    # This is more of a guess - might need additional verification
                    if is_forum:
                        topic_id = reply_msg_id
                        logger.debug(f"Using reply_to_msg_id as topic_id in forum: {topic_id}")

            # Try to get from the message ID itself for new topics or topic starters
            elif is_forum and message.post:
                # In some cases, the first message in a topic has the same ID as the topic
                topic_id = message.id
                logger.debug(f"Using message.id as topic_id for potential topic starter: {topic_id}")
            else:
                topic_id = 1
                logger.debug(f"Using default chat topic id: {topic_id}")
        except Exception as e:
            logger.error(f"Error detecting forum/topic: {str(e)}")

        return topic_id

    async def is_genuine_reply(self, message: Any, topic_id: Optional[int]) -> bool:
        """
        Determine if a message is a genuine reply (not just a topic reply).

        Args:
            message: Message to check
            topic_id: Topic ID if applicable

        Returns:
            True if it's a genuine reply to another message
        """
        if not message.reply_to or not hasattr(message.reply_to, 'reply_to_msg_id'):
            return False

        # In topics: a genuine reply has reply_to_msg_id different from the topic_id
        if hasattr(message.reply_to, 'forum_topic') and message.reply_to.forum_topic and topic_id:
            # It's a genuine reply only if reply_to_msg_id != topic_id
            return message.reply_to.reply_to_msg_id != topic_id

        # Outside of topics, any reply_to is a genuine reply
        return True

    async def process_replied_message(self, message: Any, chat_id: Union[int, str]) -> Optional[Dict[str, Any]]:
        """
        Process a message that is being replied to.

        Args:
            message: Message containing the reply
            chat_id: Chat ID where the message is

        Returns:
            Formatted reply message or None if no valid reply
        """
        try:
            # Get the message being replied to
            replied_msg_id = message.reply_to.reply_to_msg_id
            logger.debug(f"Message is a genuine reply to message ID: {replied_msg_id}")

            replied_msg = await self.client.get_messages(chat_id, ids=replied_msg_id)

            if replied_msg:
                # Format the replied message
                formatted_reply = await self.format_message_for_forwarding(replied_msg, is_reply=True)
                logger.debug(f"Added replied-to message {replied_msg_id} to forwarded content")
                return formatted_reply
            else:
                logger.debug(f"Could not find replied-to message with ID {replied_msg_id}")
                return None

        except Exception as e:
            logger.error(f"Error processing replied message: {str(e)}")
            return None

    def prepare_forwarding_content(self, message: Any, source_info: str, include_source: bool, additional_contents: List[Dict[str, Any]]) -> Tuple[str, Any, List[Dict[str, Any]]]:
        """
        Prepare the content for forwarding.

        Args:
            message: Original message
            source_info: Source chat/topic information
            include_source: Whether to include source information
            additional_contents: Additional content to include (replies, linked messages)

        Returns:
            Tuple of (text content, media to send, additional media items)
        """
        # Get the message text
        message_text = extract_message_text(message)

        # Prepare main message text
        if message_text:
            # Text message
            text = f"{source_info}\n\n{message_text}" if include_source else message_text
        elif message.media:
            # Media message without text
            media_type = get_media_type_name(message.media)
            text = f"{source_info}\n\n[Message with {media_type}]" if include_source else f"[Message with {media_type}]"
        else:
            # Other message types (if any)
            text = f"{source_info}\n\n[Empty message]" if include_source else "[Empty message]"

        # Append additional content (replied-to messages, linked messages)
        if additional_contents:
            text += "\n\n" + "\n\n".join([content["text"] for content in additional_contents])

        # Check if media is a webpage preview (cannot be forwarded as a file)
        sendable_media = None
        if message.media and not isinstance(message.media, MessageMediaWebPage):
            sendable_media = message.media

        # Prepare a list of media files to send
        additional_media = []

        for content in additional_contents:
            # Only include non-webpage media
            if content["media"] and not isinstance(content["media"], MessageMediaWebPage):
                additional_media.append({
                    "media": content["media"]
                })

        return text, sendable_media, additional_media
