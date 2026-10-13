from alembic import context
from app.config import Settings
from app.db import make_engine
from app.models import Base

settings = Settings()
engine = make_engine(settings)
with engine.connect() as connection:
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        compare_type=True,
        version_table_schema=settings.database_schema,
        include_object=lambda obj, name, type_, reflected, compare_to: name != "alembic_version",
    )
    with context.begin_transaction():
        context.run_migrations()
engine.dispose()
