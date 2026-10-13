from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import Settings


def make_engine(settings: Settings):
    return create_engine(
        settings.database_url.get_secret_value(),
        pool_pre_ping=True,
        hide_parameters=True,
        connect_args={
            "connect_timeout": 5,
            "options": f"-c timezone=UTC -c search_path={settings.database_schema}",
        },
    )


def make_session_factory(engine):
    return sessionmaker(engine, expire_on_commit=False)
