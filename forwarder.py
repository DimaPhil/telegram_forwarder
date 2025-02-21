"""
Telegram Message Forwarder
--------------------------
This script automatically listens to Telegram messages and forwards messages
from specific chats/topics to other chats/topics based on configuration.
"""

import os
import sys
import json
import logging
import asyncio
from telethon import TelegramClient, events
from telethon.sessions import StringSession, SQLiteSession
from telethon.tl.types import PeerChannel, PeerChat, PeerUser, Channel
from telethon.tl.functions.channels import GetFullChannelRequest, GetMessagesRequest
from telethon.tl.functions.messages import GetFullChatRequest, GetMessagesRequest as GetMessagesRequestMsgs
from telethon.tl.functions.messages import GetDiscussionMessageRequest
from telethon.errors import ForbiddenError, ChatAdminRequiredError, ChannelPrivateError

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler("telegram_forwarder.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Set debug level for development/troubleshooting
# Already enabled for better troubleshooting
logger.setLevel(logging.INFO)

# Configuration file path
CONFIG_FILE = 'config.json'
FORWARDING_RULES_FILE = 'forwarding_rules.json'
SESSION_FILE = 'telegram_session'

class TelegramForwarder:
    def __init__(self, config_path=CONFIG_FILE, rules_path=FORWARDING_RULES_FILE, session_file=SESSION_FILE):
        self.config_path = config_path
        self.rules_path = rules_path
        self.session_file = session_file
        self.config = self._load_json(config_path)
        self.forwarding_rules = self._load_json(rules_path)
        
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
    
    @staticmethod
    def _load_json(file_path):
        """Load JSON configuration file or create default if not found"""
        try:
            with open(file_path, 'r', encoding='utf-8') as file:
                return json.load(file)
        except FileNotFoundError:
            logger.warning(f"Configuration file not found: {file_path}")
            
            # Create default config file if it's the main config
            if file_path == CONFIG_FILE:
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
            elif file_path == FORWARDING_RULES_FILE:
                logger.info("Creating empty forwarding rules file.")
                empty_rules = {}
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(empty_rules, f, indent=4)
                return empty_rules
            
            sys.exit(1)
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON in configuration file: {file_path}")
            sys.exit(1)
    
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
    
    async def _should_forward(self, chat_id, topic_id=None):
        """Determine if a message from the given chat/topic should be forwarded"""
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
                    result.append({
                        "to_chat": target["chat_id"],
                        "to_topic": target.get("topic_id"),
                        "include_source": True
                    })
        
        logger.debug(f"Found {len(result)} forwarding rules for chat {str_chat_id}, topic {topic_id}")
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
    
    async def _handle_new_message(self, event):
        """Handle new message event"""
        chat_id = event.chat_id
        
        # More detailed logging for message investigation
        logger.debug(f"Received message: {event.message}")
        logger.debug(f"Chat ID: {chat_id}")
        
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
        logger.debug(f"Forwarding rules: {self.forwarding_rules}")
        
        # Check if we should forward this message
        forwarding_info = await self._should_forward(chat_id, topic_id)
        
        if forwarding_info:
            logger.info(f"Will forward message with info: {forwarding_info}")
            
            # Check if we can directly forward from this chat
            can_forward = await self._can_forward_from_chat(chat_id)
            logger.debug(f"Can forward directly from chat {chat_id}: {can_forward}")
            
            await self._forward_message(event, forwarding_info, topic_id, can_forward)
        else:
            logger.debug(f"No forwarding rules matched for chat {chat_id}, topic {topic_id}")
    
    async def _forward_message(self, event, forwarding_info, topic_id=None, can_forward_directly=True):
        """Forward a message to the target chat/topic"""
        message = event.message
        chat_id = event.chat_id
        
        for target in forwarding_info:
            try:
                to_chat = target["to_chat"]
                to_topic = target.get("to_topic")
                include_source = target.get("include_source", True)
                
                # Try direct forwarding first if channel allows it
                # if can_forward_directly and not include_source:
                if can_forward_directly:
                    try:
                        logger.debug(f"Attempting direct forwarding from {chat_id} to {to_chat}")
                        
                        # Direct forward (preserves original message formatting, attachments, etc.)
                        # Note: forward_messages() doesn't support reply_to, so we need to handle it separately
                        forwarded_msg = await self.client.forward_messages(
                            to_chat,
                            message
                        )
                        
                        # If we need to set it as a reply in a topic, do it as a separate step
                        if to_topic and forwarded_msg:
                            # Get the first forwarded message if it's a list
                            first_msg = forwarded_msg[0] if isinstance(forwarded_msg, list) else forwarded_msg
                            
                            try:
                                # Edit the message to make it a reply in the topic
                                await self.client.edit_message(
                                    entity=to_chat,
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
                
                # Text-based forwarding (for channels with restrictions or when source info needed)
                # Get chat and topic names for source attribution
                chat_title = await self._get_chat_title(chat_id)
                source_info = f"📨 Forwarded from: {chat_title}"
                
                if topic_id:
                    topic_name = await self._get_topic_name(chat_id, topic_id)
                    if topic_name:
                        source_info += f" | {topic_name}"
                
                # Forward content based on message type
                if message.text:
                    # Text message
                    text = f"{source_info}\n\n{message.text}" if include_source else message.text
                    await self.client.send_message(
                        to_chat, 
                        text, 
                        reply_to=to_topic,
                        formatting_entities=message.entities,
                        file=message.media if message.media else None
                    )
                elif message.media:
                    # Media message without text
                    text = source_info if include_source else ""
                    await self.client.send_message(
                        to_chat,
                        text if text else None,
                        reply_to=to_topic,
                        file=message.media
                    )
                else:
                    # Other message types (if any)
                    logger.warning(f"Unsupported message type from {chat_id}, skipping")
                    continue
                
                logger.info(f"Forwarded message from {chat_id} to {to_chat} via text-based method")
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
                
                # Create a simple rule
                self.forwarding_rules[source_chat] = {
                    "*": [
                        {
                            "chat_id": dest_chat,
                            "topic_id": None
                        }
                    ]
                }
                
                # Save the rules
                with open(self.rules_path, 'w', encoding='utf-8') as f:
                    json.dump(self.forwarding_rules, f, indent=4)
                
                print("\nForwarding rule created successfully!")
                print(f"All messages from {source_chat} will be forwarded to {dest_chat}")
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
        
        @self.client.on(events.NewMessage(pattern=r'^/help$'))
        async def help_handler(event):
            """Show help information about available commands"""
            if event.is_private:
                help_text = "Telegram Forwarder - Debug Commands\n\n"
                help_text += "/debugtopic - Show topic information for the current message\n"
                help_text += "/debugchat -100xxxx - Show information about a specific chat\n"
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

async def main():
    # Check command line arguments for any additional options
    if len(sys.argv) > 1 and sys.argv[1] == "setup":
        print("Telegram Forwarder Setup")
        print("------------------------")
        
        # Collect API credentials
        api_id = input("Enter your Telegram API ID: ")
        api_hash = input("Enter your Telegram API hash: ")
        
        # Optional proxy settings
        use_proxy = input("Do you want to use a proxy? (y/n): ").lower() == 'y'
        proxy_config = {}
        
        if use_proxy:
            proxy_type = input("Enter proxy type (socks5/mtproto): ").lower()
            proxy_server = input("Enter proxy server address: ")
            proxy_port = int(input("Enter proxy port: "))
            
            proxy_config = {
                "type": proxy_type,
                "server": proxy_server,
                "port": proxy_port
            }
            
            if proxy_type == "socks5":
                use_auth = input("Does your SOCKS5 proxy require authentication? (y/n): ").lower() == 'y'
                if use_auth:
                    proxy_config["username"] = input("Enter proxy username: ")
                    proxy_config["password"] = input("Enter proxy password: ")
            elif proxy_type == "mtproto":
                proxy_config["secret"] = input("Enter MTProto secret (or leave empty): ")
        
        # Create config file
        config = {
            "api_id": int(api_id),
            "api_hash": api_hash,
            "proxy": proxy_config
        }
        
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4)
        
        # Create empty rules file if it doesn't exist
        if not os.path.exists(FORWARDING_RULES_FILE):
            with open(FORWARDING_RULES_FILE, 'w', encoding='utf-8') as f:
                json.dump({}, f, indent=4)
        
        print("\nSetup complete! Config files have been created.")
        print("Next, run the program without arguments to start the forwarder.")
        print("You'll be prompted to log in with your phone number the first time.")
    else:
        # Start the forwarder
        try:
            forwarder = TelegramForwarder()
            await forwarder.start()
        except KeyboardInterrupt:
            print("\nForwarder stopped by user.")
        except Exception as e:
            logger.error(f"Error in main: {str(e)}")
            sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())