"""
Logger configuration for the Telegram Message Forwarder.
"""

import logging
import os
from typing import Optional


def setup_logger(name: str, log_file: str = "telegram_forwarder.log", level: int = logging.INFO) -> logging.Logger:
    """
    Configure and return a logger that writes to both console and file.

    Args:
        name: Logger name
        log_file: Path to the log file
        level: Logging level

    Returns:
        Configured logger instance
    """
    # Create logs directory if it doesn't exist
    log_dir = os.path.dirname(log_file)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir)

    # Get or create logger
    logger = logging.getLogger(name)

    # Only add handlers if they don't exist yet
    if not logger.handlers:
        logger.setLevel(level)

        # Format for log messages
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

        # File handler
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)

        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)

        # Add handlers to logger
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

    return logger
