"""
Utility functions for the Telegram Message Forwarder.
"""

import re
from typing import Optional, Any, Dict, List, Union

# Regex pattern for Telegram message links
# Matches formats like:
# - https://t.me/c/1234567890/12345 (private/channel messages)
# - https://t.me/username/12345 (public channel/group messages)
# - https://t.me/c/1234567890/12345/67890 (topic messages)
TG_LINK_PATTERN = re.compile(r'https?://t\.me/(?:c/(\d+)|([^/]+))/(\d+)(?:/(\d+))?')


def extract_message_text(message: Any) -> str:
    """
    Extract text from a message object using multiple methods.

    Args:
        message: Telethon message object

    Returns:
        Extracted message text or empty string if not found
    """
    # Try to get message text from various attributes
    if hasattr(message, 'message') and message.message:
        return message.message
    elif hasattr(message, 'text') and message.text:
        return message.text
    elif hasattr(message, 'raw_text') and message.raw_text:
        return message.raw_text
    return ""


def normalize_chat_id(chat_id: Union[int, str]) -> List[str]:
    """
    Normalize chat_id format for comparison (handle both -100xxx and -10xxx formats).

    Args:
        chat_id: Original chat ID

    Returns:
        List of potential normalized chat ID formats to check
    """
    str_chat_id = str(chat_id)

    # Check if the chat_id has the -100 format from Telethon
    if str_chat_id.startswith('-100'):
        # Try both the full ID and the version without the leading -100
        return [
            str_chat_id,  # Full ID with -100
            str_chat_id[4:],  # Without -100
            '-' + str_chat_id[4:],  # With just a single -
        ]
    else:
        # If it doesn't start with -100, try adding it
        return [
            str_chat_id,  # Original
            '-100' + str_chat_id.lstrip('-'),  # With -100
        ]


def get_media_type_name(media: Any) -> Optional[str]:
    """
    Get a user-friendly name for a media type.

    Args:
        media: Telethon media object

    Returns:
        Media type name or None if media is None
    """
    if media is None:
        return None
    return type(media).__name__.replace('MessageMedia', '')
