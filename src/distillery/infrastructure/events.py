"""Domain-event publishers (implementations of the ``EventPublisher`` port).

The default :class:`LoggingEventPublisher` emits a structured log line per event,
which doubles as an audit trail. Replace or compose it with a webhook/Kafka
publisher in production by implementing the same port.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import asdict

from distillery.domain.events import DomainEvent

logger = logging.getLogger("distillery.events")


class LoggingEventPublisher:
    """Publishes events to the structured log (audit trail)."""

    def publish(self, events: Sequence[DomainEvent]) -> None:
        for event in events:
            payload = {k: v for k, v in asdict(event).items() if k not in {"event_id"}}
            logger.info("domain_event", extra={"event": event.name, **_stringify(payload)})


class NullEventPublisher:
    """Discards events (useful in tests where events are asserted separately)."""

    def publish(self, events: Sequence[DomainEvent]) -> None:
        return None


class CollectingEventPublisher:
    """Stores published events in memory for inspection (test helper)."""

    def __init__(self) -> None:
        self.events: list[DomainEvent] = []

    def publish(self, events: Sequence[DomainEvent]) -> None:
        self.events.extend(events)


def _stringify(payload: dict) -> dict:
    return {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in payload.items()}
