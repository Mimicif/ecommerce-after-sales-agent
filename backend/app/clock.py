from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy.orm import Session

from app.errors import BusinessError
from app.models import SeedImport


def utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Business timestamps must be timezone-aware")
    return value.astimezone(UTC)


class Clock(Protocol):
    def now(self, session: Session) -> datetime: ...


class SystemClock:
    def now(self, session: Session) -> datetime:
        return datetime.now(UTC)


class FixtureClock:
    def now(self, session: Session) -> datetime:
        seed = session.get(SeedImport, "base")
        if seed is None:
            raise BusinessError("CLOCK_UNAVAILABLE", 503)
        return utc(seed.fixture_clock)


@dataclass(frozen=True)
class FixedClock:
    """Only injected by trusted Python test code; no HTTP clock mutation endpoint."""

    value: datetime

    def __post_init__(self):
        object.__setattr__(self, "value", utc(self.value))

    def now(self, session: Session) -> datetime:
        return self.value
