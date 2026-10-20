import uuid
from collections.abc import Callable

import structlog

PricesUpdatedHandler = Callable[[frozenset[uuid.UUID]], None]

logger = structlog.get_logger()


class PriceEvents:
    def __init__(self) -> None:
        self._handlers: list[PricesUpdatedHandler] = []

    def subscribe(self, handler: PricesUpdatedHandler) -> None:
        self._handlers.append(handler)

    def publish(self, asset_ids: frozenset[uuid.UUID]) -> None:
        for handler in self._handlers:
            # Prices are already committed; a failing consumer must not fail the tick.
            try:
                handler(asset_ids)
            except Exception as exc:
                logger.error("price_event_handler_failed", error_type=type(exc).__name__)
