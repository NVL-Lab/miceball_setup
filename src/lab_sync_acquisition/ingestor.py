"""Minimal in-memory record receiver for acquisition boundary tests."""

from __future__ import annotations

from typing import Iterable

from lab_sync_acquisition.device_manager import DeviceRecordCollection


class InMemoryIngestor:
    """Receives collected device records in memory without storing to disk."""

    def __init__(self) -> None:
        self._received_records: tuple[DeviceRecordCollection, ...] = ()

    @property
    def received_records(self) -> tuple[DeviceRecordCollection, ...]:
        """Received record collections for inspection."""

        return self._received_records

    def receive_records(
        self,
        collections: Iterable[DeviceRecordCollection],
    ) -> None:
        """Receive record collections without transforming them."""

        self._received_records = tuple(collections)
