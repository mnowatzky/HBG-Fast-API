import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    sticker_db_name = os.getenv("STICKER_DB_NAME", "sticker")
    sticker_db_user = os.getenv("STICKER_DB_USER", "malte")
    sticker_db_password = os.getenv("STICKER_DB_PASSWORD")
    sticker_db_host = os.getenv("STICKER_DB_HOST", "sticker-db")
    sticker_db_port = os.getenv("STICKER_DB_PORT", "5432")
    sticker_db_type = os.getenv("STICKER_DB_TYPE", "postgresql")