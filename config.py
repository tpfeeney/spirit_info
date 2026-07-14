import os
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
OWNER_ID = int(os.environ.get("OWNER_ID", "0"))
REVIEW_CHANNEL_ID = int(os.environ["REVIEW_CHANNEL_ID"]) if os.environ.get("REVIEW_CHANNEL_ID") else None
DATA_DIR = "./data"
SUGGESTIONS_FILE = "./suggestions.json"
MASHBILL_FILE = "./data/mashbills.json"