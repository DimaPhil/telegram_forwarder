"""
Debug command handlers for Telegram Message Forwarder.
"""

from telethon import TelegramClient, events
from telethon.tl.types import Channel
from telethon.tl.functions.channels import GetFullChannelRequest

from src.logger import setup_logger
from src.forwarder.entities import EntityManager
from src.forwarder.link_manager import LinkManager

# Setup logger
logger = setup_logger(__name__)


class DebugHandler:
    """
    Handles debug commands for the Telegram forwarder.
    """

    def __init__(self, client: TelegramClient, entity_manager: EntityManager, link_manager: LinkManager):
        """
        Initialize the DebugHandler.

        Args:
            client: Initialized TelegramClient
            entity_manager: EntityManager instance
            link_manager: LinkManager instance
        """
        self.client = client
        self.entity_manager = entity_manager
        self.link_manager = link_manager

    def register_handlers(self):
        """Register all debug command handlers."""

        @self.client.on(events.NewMessage(pattern=r'^/debugtopic$'))
        async def debug_topic_handler(event):
            """Debug command to show topic information for the current message"""
            if event.is_private:
                chat_id = event.chat_id
                message = event.message

                # Debug message
                debug_info = "Debug topic information:\n\n"
                debug_info += f"Message ID: {message.id}\n"
                debug_info += f"Chat ID: {chat_id}\n"

                # Extract potential topic ID using all methods
                potential_topic_ids = []

                if hasattr(message, 'topic_id'):
                    potential_topic_ids.append(("message.topic_id", message.topic_id))
                if hasattr(message, 'topic'):
                    potential_topic_ids.append(("message.topic", message.topic))
                if message.reply_to:
                    if hasattr(message.reply_to, 'reply_to_top_id'):
                        potential_topic_ids.append(("message.reply_to.reply_to_top_id", message.reply_to.reply_to_top_id))
                    if hasattr(message.reply_to, 'top_msg_id'):
                        potential_topic_ids.append(("message.reply_to.top_msg_id", message.reply_to.top_msg_id))
                    if hasattr(message.reply_to, 'forum_topic'):
                        potential_topic_ids.append(("message.reply_to.forum_topic", message.reply_to.forum_topic))

                debug_info += "\nPotential Topic IDs:\n"
                for name, value in potential_topic_ids:
                    debug_info += f"- {name}: {value}\n"

                debug_info += "\nMessage attributes: " + ", ".join(dir(message))
                if message.reply_to:
                    debug_info += "\nReply_to attributes: " + ", ".join(dir(message.reply_to))

                await event.respond(debug_info)

        @self.client.on(events.NewMessage(pattern=r'^/debugchat (\-\d+)$'))
        async def debug_chat_handler(event):
            """Debug command to show information about a specific chat"""
            if event.is_private:
                try:
                    chat_id = event.pattern_match.group(1)
                    entity = await self.entity_manager.get_entity(chat_id)

                    debug_info = f"Debug information for chat {chat_id}:\n\n"

                    # Basic chat info
                    debug_info += f"Title: {getattr(entity, 'title', 'N/A')}\n"
                    debug_info += f"Username: {getattr(entity, 'username', 'N/A')}\n"
                    debug_info += f"ID: {entity.id}\n"
                    debug_info += f"Is Channel: {isinstance(entity, Channel)}\n"
                    debug_info += f"Is Megagroup: {getattr(entity, 'megagroup', False)}\n"
                    debug_info += f"Is Forum: {getattr(entity, 'forum', False)}\n"
                    debug_info += f"No Forwards: {getattr(entity, 'noforwards', False)}\n"

                    # Try to get topics if it's a forum
                    if getattr(entity, 'forum', False):
                        try:
                            full_chat = await self.client(GetFullChannelRequest(channel=entity))
                            forum_topics = getattr(full_chat.full_chat, 'topics', None)

                            if forum_topics:
                                debug_info += f"\nForum Topics:\n"
                                for topic in forum_topics.topics:
                                    debug_info += f"- ID: {topic.id}, Title: {topic.title}\n"
                            else:
                                debug_info += "\nNo forum topics found via GetFullChannelRequest\n"
                        except Exception as e:
                            debug_info += f"\nError getting forum topics: {str(e)}\n"

                    # Forwarding info
                    can_forward = await self.entity_manager.can_forward_from_chat(chat_id)
                    debug_info += f"\nCan Forward Directly: {can_forward}\n"

                    await event.respond(debug_info)
                except Exception as e:
                    await event.respond(f"Error debugging chat: {str(e)}")

        @self.client.on(events.NewMessage(pattern=r'^/debuglinks$'))
        async def debug_links_handler(event):
            """Debug command to test message link extraction from the current message"""
            if event.is_private:
                message = event.message

                if not message.text:
                    await event.respond("No text in message to extract links from.")
                    return

                # Extract links from the message
                message_links = await self.link_manager.extract_message_links(message.text)

                if not message_links:
                    await event.respond("No Telegram message links found in the message.")
                    return

                # Debug message
                debug_info = "Extracted message links:\n\n"

                for idx, link_data in enumerate(message_links, 1):
                    debug_info += f"Link {idx}:\n"
                    debug_info += f"- Full match: {link_data['full_match']}\n"
                    debug_info += f"- Chat ID: {link_data.get('chat_id', 'N/A')}\n"
                    debug_info += f"- Username: {link_data.get('username', 'N/A')}\n"
                    debug_info += f"- Message ID: {link_data['message_id']}\n"
                    debug_info += f"- Topic ID: {link_data.get('topic_id', 'N/A')}\n\n"

                    # Try to fetch the message
                    try:
                        linked_msg = await self.link_manager.fetch_linked_message(link_data)
                        if linked_msg:
                            debug_info += f"Successfully fetched message content!\n"
                            debug_info += f"- Text: {linked_msg.text[:100]}{'...' if len(linked_msg.text or '') > 100 else ''}\n"
                            debug_info += f"- Has media: {linked_msg.media is not None}\n\n"
                        else:
                            debug_info += f"Could not fetch message content.\n\n"
                    except Exception as e:
                        debug_info += f"Error fetching message: {str(e)}\n\n"

                await event.respond(debug_info)

        @self.client.on(events.NewMessage(pattern=r'^/help$'))
        async def help_handler(event):
            """Show help information about available commands"""
            if event.is_private:
                help_text = "Telegram Forwarder - Debug Commands\n\n"
                help_text += "/debugtopic - Show topic information for the current message\n"
                help_text += "/debugchat -100xxxx - Show information about a specific chat\n"
                help_text += "/debuglinks - Test message link extraction from your message\n"
                help_text += "/help - Show this help message\n"

                await event.respond(help_text)

        logger.info("Debug command handlers registered")
