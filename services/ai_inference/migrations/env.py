"""All DDL is owned by Alembic, never by application startup."""
from alembic import context
from app.persistence import engine

with engine().connect() as connection:
    context.configure(connection=connection, target_metadata=None)
    with context.begin_transaction():
        context.run_migrations()
