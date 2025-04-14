"""
Message forwarding logic for Telegram Message Forwarder.
"""

from typing import Dict, List, Any, Optional, Union
from telethon import TelegramClient
from telethon.errors import ForbiddenError, ChatAdminRequiredError, ChannelPrivateError

from src.logger import setup_logger
from src.forwarder.entities import EntityManager
from src.forwarder.processors import MessageProcessor

# Setup logger
logger = setup_logger(__name__)


class ForwardingManager:
    """
    Manages message forwarding operations.
    """

    def __init__(self, client: TelegramClient, entity_manager: EntityManager, processor: MessageProcessor):
        """
        Initialize the ForwardingManager.

        Args:
            client: Initialized TelegramClient
            entity_manager: EntityManager instance
            processor: MessageProcessor instance
        """
        self.client = client
        self.entity_manager = entity_manager
        self.processor = processor

    async def forward_message(self, event: Any, message_contents: List[Dict[str, Any]], topic_id: Optional[int], can_forward_directly: bool, forwarding_info: List[Dict[str, Any]]):
        """
        Forward a message to all defined targets.

        Args:
            event: Message event
            message_contents: List of additional message contents (replies, linked messages)
            topic_id: Topic ID if applicable
            can_forward_directly: Whether direct forwarding is possible
            forwarding_info: List of forwarding targets
        """
        message = event.message
        chat_id = event.chat_id

        # Now forward the message with all additional content
        for target in forwarding_info:
            try:
                to_chat = target["to_chat"]
                to_topic = target.get("to_topic")
                include_source = target.get("include_source", True)

                # If we can directly forward and there's no additional content
                if can_forward_directly and not message_contents:
                    try:
                        logger.debug(f"Attempting direct forwarding from {chat_id} to {to_chat}")

                        # Direct forward (preserves original message formatting, attachments, etc.)
                        forwarded_msg = await self.client.forward_messages(
                            int(to_chat),
                            message
                        )

                        # If we need to set it as a reply in a topic, do it as a separate step
                        if to_topic and forwarded_msg:
                            # Get the first forwarded message if it's a list
                            first_msg = forwarded_msg[0] if isinstance(forwarded_msg, list) else forwarded_msg

                            try:
                                # Edit the message to make it a reply in the topic
                                await self.client.edit_message(
                                    entity=int(to_chat),
                                    message=first_msg,
                                    reply_to=to_topic
                                )
                            except Exception as e:
                                logger.warning(f"Couldn't set forwarded message as reply to topic: {str(e)}")

                        logger.info(f"Directly forwarded message from {chat_id} to {to_chat}")
                        continue  # Skip to next target as this one succeeded
                    except (ForbiddenError, ChatAdminRequiredError, ChannelPrivateError) as e:
                        # Remember that this chat doesn't allow forwarding
                        logger.warning(f"Direct forwarding failed from {chat_id}, marking as no-forward: {str(e)}")
                        self.entity_manager.no_forward_chats.add(chat_id)
                        # Fall through to text-based forwarding
                    except Exception as e:
                        logger.error(f"Unexpected error during direct forwarding: {str(e)}")
                        # Fall through to text-based forwarding

                # Get chat and topic names for source attribution
                chat_title = await self.entity_manager.get_chat_title(chat_id)
                source_info = f"📨 Forwarded from: {chat_title}"

                if topic_id:
                    topic_name = await self.entity_manager.get_topic_name(chat_id, topic_id)
                    if topic_name:
                        source_info += f" | {topic_name}"

                # Prepare the content for forwarding
                text, sendable_media, additional_media = self.processor.prepare_forwarding_content(
                    message,
                    source_info,
                    include_source,
                    message_contents
                )

                # Send the main message first
                await self.client.send_message(
                    to_chat,
                    text,
                    reply_to=to_topic,
                    formatting_entities=message.entities,
                    file=sendable_media
                )

                # Then send any additional media from linked messages as separate messages
                for media_item in additional_media:
                    try:
                        await self.client.send_message(
                            to_chat,
                            "📎 Additional media from referenced message",
                            reply_to=to_topic,
                            file=media_item["media"]
                        )
                        logger.info(f"Sent additional media to {to_chat}")
                    except Exception as e:
                        logger.error(f"Failed to send additional media: {str(e)}")

                logger.info(f"Forwarded message from {chat_id} to {to_chat} with additional content")
            except Exception as e:
                logger.error(f"Failed to forward message: {str(e)}")
