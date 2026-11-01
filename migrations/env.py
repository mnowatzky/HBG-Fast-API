from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine
from sqlmodel import SQLModel

import sticker  # noqa: F401  registers the table on SQLModel.metadata
from config import config

if context.config.config_file_name is not None:
    fileConfig(context.config.config_file_name, disable_existing_loggers=False)

# Tests pass the url of their throwaway database.
url = context.config.attributes.get("url", config.db_url)

with create_engine(url).connect() as connection:
    context.configure(connection=connection, target_metadata=SQLModel.metadata)
    with context.begin_transaction():
        context.run_migrations()
