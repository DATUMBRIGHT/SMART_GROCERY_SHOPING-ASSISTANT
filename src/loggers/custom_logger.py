import logging
import os
from pathlib import Path

import logging
print(logging.__file__)


# Create a logs directory if it doesn't exist
logging_dir = os.path.dirname(__file__)
logging_dir = os.path.join(logging_dir, 'logs')
os.makedirs(logging_dir, exist_ok=True)

# Define the log file path
log_file = os.path.join(logging_dir, 'grocery_assistant.log')

# Initialize logger
logger = logging.getLogger("grocery_agent")
logger.setLevel(logging.INFO)  # Set logging level

# Set up a file handler with a formatter
handler = logging.FileHandler(log_file)
handler.setFormatter(logging.Formatter(fmt='[%(asctime)s: %(levelname)s] %(message)s'))

# Add the handler to the logger
logger.addHandler(handler)

# Log some messages
logger.info("Logger initialized")
logger.error("Error")
logger.debug("Debug (won't appear unless logger level is set to DEBUG)")
logger.warning("Warning")
logger.critical("Critical")
