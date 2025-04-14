"""
Forwarding rules management and matching.
"""

import json
from typing import Dict, List, Any, Optional, Union

from src.logger import setup_logger
from src.forwarder.utils import normalize_chat_id

# Setup logger
logger = setup_logger(__name__)


class RuleManager:
    """
    Manages forwarding rules and matching.
    """

    def __init__(self, rules: Dict[str, Any]):
        """
        Initialize the RuleManager.

        Args:
            rules: Forwarding rules dictionary
        """
        self.rules = rules

    async def should_forward(self, chat_id: Union[int, str], topic_id: Optional[int] = None, user_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Determine if a message from the given chat/topic and user should be forwarded.

        Args:
            chat_id: Chat ID
            topic_id: Topic ID (optional)
            user_id: User ID (optional)

        Returns:
            List of forwarding targets or empty list if no matching rules
        """
        # Get all potential normalized chat IDs
        potential_ids = normalize_chat_id(chat_id)

        # Log for debugging
        logger.debug(f"Looking for chat {chat_id} in rules. Checking formats: {potential_ids}")
        logger.debug(f"Available rule keys: {list(self.rules.keys())}")

        # Check all potential ID formats
        matching_rules = None
        for potential_id in potential_ids:
            if potential_id in self.rules:
                matching_rules = self.rules[potential_id]
                logger.debug(f"Found matching rules using format: {potential_id}")
                break

        # If no match is found
        if matching_rules is None:
            logger.debug(f"No forwarding rules found for chat {chat_id}")
            return []

        result = []

        # Check for chat-level forwarding rules
        if "*" in matching_rules:
            for target in matching_rules["*"]:
                # Check if user_id filter is defined and if the message is from an allowed user
                user_ids = target.get("user_ids", [])
                if user_ids and user_id is not None and user_id not in user_ids:
                    logger.debug(f"User {user_id} not in allowed users list {user_ids} for chat {chat_id}")
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
                        logger.debug(f"User {user_id} not in allowed users list {user_ids} for chat {chat_id}, topic {topic_id}")
                        continue

                    result.append({
                        "to_chat": target["chat_id"],
                        "to_topic": target.get("topic_id"),
                        "include_source": True
                    })

        logger.debug(f"Found {len(result)} forwarding rules for chat {chat_id}, topic {topic_id}, user {user_id}")
        return result

    async def setup_interactive(self, rules_path: str) -> bool:
        """
        Interactive setup for forwarding rules.

        Args:
            rules_path: Path to save the rules

        Returns:
            True if rules were created, False otherwise
        """
        if self.rules:
            return False

        print("\nNo forwarding rules found in forwarding_rules.json")
        print("Would you like to set up a simple forwarding rule now? (y/n): ", end="")
        if input().lower() != 'y':
            print("\nNo problem! You can edit forwarding_rules.json manually later.")
            print("See the README.md file for examples of how to configure forwarding rules.")
            return False

        print("\nTo set up forwarding, we need the source and destination chat IDs.")
        print("You can get chat IDs by forwarding a message from the chat to @userinfobot\n")

        source_chat = input("Enter source chat ID (the chat you want to monitor): ")
        if not source_chat:
            print("Skipping rule creation. You can edit forwarding_rules.json manually later.")
            return False

        dest_chat = input("Enter destination chat ID (where messages should be forwarded): ")
        if not dest_chat:
            print("Skipping rule creation. You can edit forwarding_rules.json manually later.")
            return False

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

        self.rules[source_chat] = {
            "*": [rule]
        }

        # Save the rules
        with open(rules_path, 'w', encoding='utf-8') as f:
            json.dump(self.rules, f, indent=4)

        print("\nForwarding rule created successfully!")
        message = f"All messages from {source_chat} will be forwarded to {dest_chat}"
        if user_ids:
            message += f" (but only from users with IDs: {user_ids})"
        print(message)

        return True
