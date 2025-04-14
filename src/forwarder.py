"""
Telegram Message Forwarder core implementation.
"""

import re
import sys
import asyncio
from typing import Dict, List, Any, Optional, Union, Set, Tuple

from telethon import TelegramClient, events
from telethon.sessions import StringSession, SQLiteSession
from telethon.tl.types import PeerChannel, PeerChat, PeerUser, Channel, MessageEntityTextUrl, MessageMediaWebPage
from telethon.tl.functions.channels import GetFullChannelRequest, GetMessagesRequest
from telethon.tl.functions.messages import GetFullChatRequest, GetMessagesRequest as GetMessagesRequestMsgs
from telethon.tl.functions.messages import GetDiscussionMessageRequest
from telethon.errors import ForbiddenError, ChatAdminRequiredError, ChannelPrivateError

from src.config import load_json, save_json
from src.logger import setup_logger

# Setup logger
logger = setup_logger(__name__)

# Regex pattern for Telegram message links
TG_LINK_PATTERN = re.compile(r'https?://t\.me/(?:c/(\d+)|([^/]+))/(\d+)(?:/(\d+))?')


class TelegramForwarder:
    """
    Main class for forwarding messages between Telegram chats/topics.
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
        self.config = load_json(config_path)
        self.forwarding_rules = load_json(rules_path)

        # Initialize client using SQLite session file instead of StringSession
        self.client = TelegramClient(
            self.session_file,
            self.config['api_id'],
            self.config['api_hash'],
            proxy=self._setup_proxy() if 'proxy' in self.config and self.config['proxy'].get('server') else None
        )

        # Cache for chat entities
        self.chat_entities = {}
        # Cache for chat topics
        self.chat_topics = {}
        # Cache for channels that don't allow forwarding
        self.no_forward_chats = set()
        # Cache for resolved message links
        self.resolved_message_links = {}

    def _setup_proxy(self):
        """Setup proxy from config (if available)"""
        proxy_config = self.config.get('proxy', {})

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

    async def _get_entity(self, chat_id):
        """Get chat entity from cache or fetch it"""
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

    async def _get_chat_title(self, chat_id):
        """Get chat title from entity"""
        entity = await self._get_entity(chat_id)
        if entity:
            return getattr(entity, 'title', f"Chat {chat_id}")
        return f"Chat {chat_id}"

    async def _get_topic_name(self, chat_id, topic_id):
        """Get topic name from a chat"""
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
            entity = await self._get_entity(chat_id)

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

    async def _should_forward(self, chat_id, topic_id=None, user_id=None):
        """Determine if a message from the given chat/topic and user should be forwarded"""
        # Normalize chat_id format for comparison (handle both -100xxx and -10xxx formats)
        str_chat_id = str(chat_id)

        # Check if the chat_id has the -100 format from Telethon
        if str_chat_id.startswith('-100'):
            # Try both the full ID and the version without the leading -100
            potential_ids = [
                str_chat_id,  # Full ID with -100
                str_chat_id[4:],  # Without -100
                '-' + str_chat_id[4:],  # With just a single -
            ]
        else:
            # If it doesn't start with -100, try adding it
            potential_ids = [
                str_chat_id,  # Original
                '-100' + str_chat_id.lstrip('-'),  # With -100
            ]

        # Log for debugging
        logger.debug(f"Looking for chat {str_chat_id} in rules. Checking formats: {potential_ids}")
        logger.debug(f"Available rule keys: {list(self.forwarding_rules.keys())}")

        # Check all potential ID formats
        matching_rules = None
        for potential_id in potential_ids:
            if potential_id in self.forwarding_rules:
                matching_rules = self.forwarding_rules[potential_id]
                logger.debug(f"Found matching rules using format: {potential_id}")
                break

        # If no match is found
        if matching_rules is None:
            logger.debug(f"No forwarding rules found for chat {str_chat_id}")
            return []

        result = []

        # Check for chat-level forwarding rules
        if "*" in matching_rules:
            for target in matching_rules["*"]:
                # Check if user_id filter is defined and if the message is from an allowed user
                user_ids = target.get("user_ids", [])
                if user_ids and user_id is not None and user_id not in user_ids:
                    logger.debug(f"User {user_id} not in allowed users list {user_ids} for chat {str_chat_id}")
                    continue

                result.append({
                    "to_chat": target["chat_id"],
                    "to_topic": target.get("topic_id"),
                    "include_source": True
                })

        # Check for topic-specific forwarding rules
        if topic_id is not None:
            str_topic_id = str(topic_id)
            if str_topic_id in matching_rules:
                for target in matching_rules[str_topic_id]:
                    # Check if user_id filter is defined and if the message is from an allowed user
                    user_ids = target.get("user_ids", [])
                    if user_ids and user_id is not None and user_id not in user_ids:
                        logger.debug(f"User {user_id} not in allowed users list {user_ids} for chat {str_chat_id}, topic {topic_id}")
                        continue

                    result.append({
                        "to_chat": target["chat_id"],
                        "to_topic": target.get("topic_id"),
                        "include_source": True
                    })

        logger.debug(f"Found {len(result)} forwarding rules for chat {str_chat_id}, topic {topic_id}, user {user_id}")
        return result

    async def _can_forward_from_chat(self, chat_id):
        """Check if messages can be directly forwarded from this chat"""
        # Check cache first
        if chat_id in self.no_forward_chats:
            return False

        # Try to get entity information
        entity = await self._get_entity(chat_id)
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

    async def _extract_message_links(self, message_text):
        """Extract Telegram message links from text"""
        if not message_text:
            return []

        links = []
        for match in TG_LINK_PATTERN.finditer(message_text):
            channel_id, username, topic_id, msg_id = match.groups()

            # Store the link details
            link_data = {
                'full_match': match.group(0),
                'message_id': int(msg_id)
            }

            # Handle channel ID (numeric format)
            if channel_id:
                # Note: Don't add -100 prefix here, will handle in _fetch_linked_message
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

    async def _fetch_linked_message(self, link_data):
        """Fetch a message referenced by a Telegram link"""
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

                chat = await self._get_entity(chat_id)
            else:
                # For public links with username
                chat = await self._get_entity(link_data['username'])

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

    async def _format_message_for_forwarding(self, message, is_reply=False, linked_from=None):
        """Format a message for inclusion in a forwarded message"""
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
            media_type = type(message.media).__name__.replace('MessageMedia', '')
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

    async def _handle_new_message(self, event):
        """Handle new message event"""
        chat_id = event.chat_id
        message = event.message

        # Get message text now for logging
        message_text = ""
        if hasattr(message, 'message') and message.message:
            message_text = message.message
        elif hasattr(message, 'text') and message.text:
            message_text = message.text
        elif hasattr(message, 'raw_text') and message.raw_text:
            message_text = message.raw_text

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

        # Multiple ways to get topic ID depending on Telegram client version and message type
        topic_id = None

        # Get the chat entity to check if it's a forum
        try:
            entity = await self._get_entity(chat_id)
            is_forum = getattr(entity, 'forum', False)
            logger.debug(f"Chat {chat_id} is forum: {is_forum}")

            # If not a forum, don't try to get topic_id
            if not is_forum:
                logger.debug(f"Chat {chat_id} is not a forum, skipping topic detection")
                topic_id = None
            else:
                # Check for topic attribute in modern Telegram clients
                if hasattr(event.message, 'topic_id'):
                    topic_id = event.message.topic_id
                    logger.debug(f"Found topic_id from message.topic_id: {topic_id}")
                elif hasattr(event.message, 'topic'):
                    topic_id = event.message.topic
                    logger.debug(f"Found topic_id from message.topic: {topic_id}")
                # Then try the legacy reply_to methods
                elif event.message.reply_to:
                    reply_to = event.message.reply_to
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
                elif is_forum and event.message.post:
                    # In some cases, the first message in a topic has the same ID as the topic
                    topic_id = event.message.id
                    logger.debug(f"Using message.id as topic_id for potential topic starter: {topic_id}")
                else:
                    topic_id = 1
                    logger.debug(f"Using default chat topic id: {topic_id}")
        except Exception as e:
            logger.error(f"Error detecting forum/topic: {str(e)}")

        logger.debug(f"Topic ID: {topic_id}")

        # Check if we should forward this message based on chat, topic, and user
        forwarding_info = await self._should_forward(chat_id, topic_id, sender_id)

        if forwarding_info:
            logger.info(f"Will forward message with info: {forwarding_info}")

            # Check if we can directly forward from this chat
            can_forward = await self._can_forward_from_chat(chat_id)
            logger.debug(f"Can forward directly from chat {chat_id}: {can_forward}")

            # Process and handle the message
            await self._process_and_forward_message(event, forwarding_info, topic_id, can_forward)
        else:
            logger.debug(f"No forwarding rules matched for chat {chat_id}, topic {topic_id}, user {sender_id}")

    async def _process_and_forward_message(self, event, forwarding_info, topic_id=None, can_forward_directly=True):
        """Process and forward a message with all the new features applied"""
        message = event.message
        chat_id = event.chat_id

        # Additional content to include in the forwarded message
        additional_content = []

        # 1. Check if this message is a reply to another message
        is_genuine_reply = False
        if message.reply_to and hasattr(message.reply_to, 'reply_to_msg_id'):
            # In topics: a genuine reply has reply_to_msg_id different from the topic_id
            if hasattr(message.reply_to, 'forum_topic') and message.reply_to.forum_topic and topic_id:
                # It's a genuine reply only if reply_to_msg_id != topic_id
                is_genuine_reply = message.reply_to.reply_to_msg_id != topic_id
            else:
                # Outside of topics, any reply_to is a genuine reply
                is_genuine_reply = True

            if is_genuine_reply:
                try:
                    # Get the message being replied to
                    replied_msg_id = message.reply_to.reply_to_msg_id
                    logger.debug(f"Message is a genuine reply to message ID: {replied_msg_id}")

                    replied_msg = await self.client.get_messages(chat_id, ids=replied_msg_id)

                    if replied_msg:
                        # Format the replied message
                        formatted_reply = await self._format_message_for_forwarding(replied_msg, is_reply=True)
                        additional_content.append(formatted_reply)
                        logger.debug(f"Added replied-to message {replied_msg_id} to forwarded content")
                    else:
                        logger.debug(f"Could not find replied-to message with ID {replied_msg_id}")
                except Exception as e:
                    logger.error(f"Error processing replied message: {str(e)}")
            else:
                logger.debug(f"Message in topic {topic_id} is not a genuine reply (reply_to_msg_id={message.reply_to.reply_to_msg_id})")

        # 2. Extract and process message links in the text
        message_links = []
        if message.text:
            message_links = await self._extract_message_links(message.text)

        for link_data in message_links:
            try:
                linked_msg = await self._fetch_linked_message(link_data)

                if linked_msg:
                    # Format the linked message
                    link_reference = link_data['full_match']
                    formatted_link = await self._format_message_for_forwarding(linked_msg, linked_from=link_reference)
                    additional_content.append(formatted_link)
                    logger.debug(f"Added linked message {link_data['message_id']} to forwarded content")
            except Exception as e:
                logger.error(f"Error processing message link {link_data['full_match']}: {str(e)}")

        # Now forward the message with all additional content
        for target in forwarding_info:
            try:
                to_chat = target["to_chat"]
                to_topic = target.get("to_topic")
                include_source = target.get("include_source", True)

                # If we can directly forward and there's no additional content
                if can_forward_directly and not additional_content:
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
                        self.no_forward_chats.add(chat_id)
                        # Fall through to text-based forwarding
                    except Exception as e:
                        logger.error(f"Unexpected error during direct forwarding: {str(e)}")
                        # Fall through to text-based forwarding

                # Get chat and topic names for source attribution
                chat_title = await self._get_chat_title(chat_id)
                source_info = f"📨 Forwarded from: {chat_title}"

                if topic_id:
                    topic_name = await self._get_topic_name(chat_id, topic_id)
                    if topic_name:
                        source_info += f" | {topic_name}"

                # Prepare main message text
                message_text = ""

                # Try to get message text from various attributes
                if hasattr(message, 'message') and message.message:
                    message_text = message.message
                elif hasattr(message, 'text') and message.text:
                    message_text = message.text
                elif hasattr(message, 'raw_text') and message.raw_text:
                    message_text = message.raw_text

                # Log the extracted text for debugging
                logger.debug(f"Main message text for forwarding: '{message_text}'")

                if message_text:
                    # Text message
                    text = f"{source_info}\n\n{message_text}" if include_source else message_text
                elif message.media:
                    # Media message without text
                    media_type = type(message.media).__name__.replace('MessageMedia', '')
                    text = f"{source_info}\n\n[Message with {media_type}]" if include_source else f"[Message with {media_type}]"
                else:
                    # Other message types (if any)
                    text = f"{source_info}\n\n[Empty message]" if include_source else "[Empty message]"

                # Append additional content (replied-to messages, linked messages)
                if additional_content:
                    text += "\n\n" + "\n\n".join([content["text"] for content in additional_content])

                # Check if media is a webpage preview (cannot be forwarded as a file)
                sendable_media = None
                if message.media and not isinstance(message.media, MessageMediaWebPage):
                    sendable_media = message.media

                # Process and handle additional content (linked media) separately
                # Prepare a list of media files to send
                additional_media = []

                for content in additional_content:
                    # Only include non-webpage media
                    if content["media"] and not isinstance(content["media"], MessageMediaWebPage):
                        additional_media.append({
                            "chat_id": to_chat,
                            "topic_id": to_topic,
                            "media": content["media"]
                        })

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
                            media_item["chat_id"],
                            "📎 Additional media from referenced message",
                            reply_to=media_item["topic_id"],
                            file=media_item["media"]
                        )
                        logger.info(f"Sent additional media to {to_chat}")
                    except Exception as e:
                        logger.error(f"Failed to send additional media: {str(e)}")

                logger.info(f"Forwarded message from {chat_id} to {to_chat} with additional content")
            except Exception as e:
                logger.error(f"Failed to forward message: {str(e)}")

    async def check_forwarding_rules(self):
        """Check if forwarding rules are properly configured and provide guidance if not"""
        if not self.forwarding_rules:
            print("\nNo forwarding rules found in forwarding_rules.json")
            print("Would you like to set up a simple forwarding rule now? (y/n): ", end="")
            if input().lower() == 'y':
                print("\nTo set up forwarding, we need the source and destination chat IDs.")
                print("You can get chat IDs by forwarding a message from the chat to @userinfobot\n")

                source_chat = input("Enter source chat ID (the chat you want to monitor): ")
                if not source_chat:
                    print("Skipping rule creation. You can edit forwarding_rules.json manually later.")
                    return

                dest_chat = input("Enter destination chat ID (where messages should be forwarded): ")
                if not dest_chat:
                    print("Skipping rule creation. You can edit forwarding_rules.json manually later.")
                    return

                # Ask if they want to filter by user IDs
                use_user_filter = input("Do you want to filter messages by user IDs? (y/n): ").lower() == 'y'
                user_ids = []

                if use_user_filter:
                    user_input = input("Enter comma-separated list of user IDs to forward messages from: ")
                    if user_input:
                        user_ids = [int(user_id.strip()) for user_id in user_input.split(',') if user_id.strip()]

                # Create a simple rule
                rule = {
                    "chat_id": dest_chat,
                    "topic_id": None
                }

                # Add user_ids filter if provided
                if user_ids:
                    rule["user_ids"] = user_ids

                self.forwarding_rules[source_chat] = {
                    "*": [rule]
                }

                # Save the rules
                with open(self.rules_path, 'w', encoding='utf-8') as f:
                    json.dump(self.forwarding_rules, f, indent=4)

                print("\nForwarding rule created successfully!")
                message = f"All messages from {source_chat} will be forwarded to {dest_chat}"
                if user_ids:
                    message += f" (but only from users with IDs: {user_ids})"
                print(message)
            else:
                print("\nNo problem! You can edit forwarding_rules.json manually later.")
                print("See the README.md file for examples of how to configure forwarding rules.")

    async def start(self):
        """Start the forwarder with automatic login if needed"""
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
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=4)

            # Update client with new credentials
            self.client = TelegramClient(
                self.session_file,
                self.config['api_id'],
                self.config['api_hash'],
                proxy=self._setup_proxy() if 'proxy' in self.config and self.config['proxy'].get('server') else None
            )

        # Check if forwarding rules exist and offer to create them if not
        await self.check_forwarding_rules()

        # Add debug commands for troubleshooting
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
                    entity = await self._get_entity(chat_id)

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
                    can_forward = await self._can_forward_from_chat(chat_id)
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
                message_links = await self._extract_message_links(message.text)

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
                        linked_msg = await self._fetch_linked_message(link_data)
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

        try:
            # Start client (will automatically prompt for phone/code if not logged in)
            await self.client.start()
            logger.info("Client started successfully")
            me = await self.client.get_me()
            logger.info(f"Logged in as: {me.first_name} (@{me.username})")

            # Register the new message handler
            @self.client.on(events.NewMessage)
            async def new_message_handler(event):
                await self._handle_new_message(event)

            print(f"\nForwarder is running for account: {me.first_name} (@{me.username})")
            print("Listening for new messages to forward based on configuration...")
            print("Press Ctrl+C to stop\n")

            # Keep the client running
            await self.client.run_until_disconnected()
        except Exception as e:
            logger.error(f"Error starting client: {str(e)}")
            sys.exit(1)