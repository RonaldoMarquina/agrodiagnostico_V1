"""All DDL is owned by Alembic, never by application startup."""
from alembic import context
from sqlalchemy import create_engine
from app.persistence import engine

url = context.config.get_main_option("sqlalchemy.url")
if url:
    connectable = create_engine(url)
else:
    connectable = engine()

with connectable.connect() as connection:
    context.configure(connection=connection, target_metadata=None)
    with context.begin_transaction():
        context.run_migrations()
