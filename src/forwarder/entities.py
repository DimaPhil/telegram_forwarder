"""
Chat and topic entity handling for Telegram Message Forwarder.
"""

from typing import Dict, Any, Optional, Set, Union
from telethon import TelegramClient
from telethon.tl.types import Channel
from telethon.tl.functions.channels import GetFullChannelRequest, GetMessagesRequest
from telethon.tl.functions.messages import GetDiscussionMessageRequest

from src.logger import setup_logger

# Setup logger
logger = setup_logger(__name__)


class EntityManager:
    """
    Manages chat entities and topics with caching for better performance.
    """

    def __init__(self, client: TelegramClient):
        """
        Initialize the EntityManager.

        Args:
            client: Initialized TelegramClient
        """
        self.client = client
        # Cache for chat entities
        self.chat_entities = {}
        # Cache for chat topics
        self.chat_topics = {}
        # Cache for channels that don't allow forwarding
        self.no_forward_chats = set()

    async def get_entity(self, chat_id: Union[int, str]) -> Optional[Any]:
        """
        Get chat entity from cache or fetch it.

        Args:
            chat_id: Chat ID or username

        Returns:
            Chat entity or None if not found
        """
        if chat_id in self.chat_entities:
            return self.chat_entities[chat_id]

        try:
            # Try different ways to get the entity
            if str(chat_id).startswith('-100'):
                entity = await self.client.get_entity(int(chat_id))
            elif str(chat_id).startswith('@'):
                entity = await self.client.get_entity(chat_id)
            else:
                entity = await self.client.get_entity(int(chat_id))

            self.chat_entities[chat_id] = entity
            return entity
        except Exception as e:
            logger.error(f"Failed to get entity for chat {chat_id}: {str(e)}")
            return None

    async def get_chat_title(self, chat_id: Union[int, str]) -> str:
        """
        Get chat title from entity.

        Args:
            chat_id: Chat ID or username

        Returns:
            Chat title or default if not found
        """
        entity = await self.get_entity(chat_id)
        if entity:
            return getattr(entity, 'title', f"Chat {chat_id}")
        return f"Chat {chat_id}"

    async def get_topic_name(self, chat_id: Union[int, str], topic_id: int) -> Optional[str]:
        """
        Get topic name from a chat.

        Args:
            chat_id: Chat ID or username
            topic_id: Topic ID

        Returns:
            Topic name or None if not found
        """
        if not topic_id:
            return None

        # Check cache first
        if chat_id in self.chat_topics and topic_id in self.chat_topics[chat_id]:
            return self.chat_topics[chat_id][topic_id]

        # Initialize cache for this chat if needed
        if chat_id not in self.chat_topics:
            self.chat_topics[chat_id] = {}

        try:
            # Get chat entity
            entity = await self.get_entity(chat_id)

            # First method: try to get forum topics from getFullChannel
            try:
                if isinstance(entity, Channel) and getattr(entity, 'megagroup', False):
                    full_chat = await self.client(GetFullChannelRequest(channel=entity))
                    forum_topics = getattr(full_chat.full_chat, 'topics', None)

                    if forum_topics:
                        for topic in forum_topics.topics:
                            self.chat_topics[chat_id][topic.id] = topic.title
                        if topic_id in self.chat_topics[chat_id]:
                            return self.chat_topics[chat_id][topic_id]
            except Exception as e:
                logger.debug(f"Could not get forum topics via GetFullChannelRequest: {str(e)}")

            # Second method: try to directly get the message that created the topic
            try:
                result = await self.client(GetMessagesRequest(
                    channel=entity,
                    id=[topic_id]
                ))

                if result.messages and len(result.messages) > 0:
                    message = result.messages[0]
                    if hasattr(message, 'title') and message.title:
                        # Cache and return the topic title
                        self.chat_topics[chat_id][topic_id] = message.title
                        return message.title
            except Exception as e:
                logger.debug(f"Could not get topic message directly: {str(e)}")

            # Third method: try to get the discussion message
            try:
                result = await self.client(GetDiscussionMessageRequest(
                    peer=entity,
                    msg_id=topic_id
                ))

                if result and hasattr(result, 'messages') and len(result.messages) > 0:
                    for msg in result.messages:
                        if hasattr(msg, 'title') and msg.title:
                            # Cache and return the topic title
                            self.chat_topics[chat_id][topic_id] = msg.title
                            return msg.title
            except Exception as e:
                logger.debug(f"Could not get topic via GetDiscussionMessageRequest: {str(e)}")

        except Exception as e:
            logger.error(f"Failed to get topic name for chat {chat_id}, topic {topic_id}: {str(e)}")

        # If all methods failed, use a fallback name
        fallback_name = f"Topic {topic_id}"
        self.chat_topics[chat_id][topic_id] = fallback_name
        return fallback_name

    async def can_forward_from_chat(self, chat_id: Union[int, str]) -> bool:
        """
        Check if messages can be directly forwarded from this chat.

        Args:
            chat_id: Chat ID or username

        Returns:
            True if messages can be forwarded, False otherwise
        """
        # Check cache first
        if chat_id in self.no_forward_chats:
            return False

        # Try to get entity information
        entity = await self.get_entity(chat_id)
        if not entity:
            # If we can't get the entity, assume we can't forward
            self.no_forward_chats.add(chat_id)
            return False

        # Check for channel/group restrictions
        if isinstance(entity, Channel):
            # Check for noforwards flag
            if getattr(entity, 'noforwards', False):
                logger.debug(f"Chat {chat_id} has noforwards flag set")
                self.no_forward_chats.add(chat_id)
                return False

        # Assume we can forward if no restrictions found
        return True
