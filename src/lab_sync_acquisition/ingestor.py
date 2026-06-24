"""Minimal in-memory record receiver for acquisition boundary tests."""

from __future__ import annotations

from typing import Iterable

from lab_sync_acquisition.device_manager import DeviceRecordCollection
from lab_sync_acquisition.storage import InMemoryStorageManager


class InMemoryIngestor:
    """Receives collected device records and optionally forwards them to storage."""

    def __init__(self, storage_manager: InMemoryStorageManager | None = None) -> None:
        self._storage_manager = storage_manager
        self._received_records: tuple[DeviceRecordCollection, ...] = ()

    @property
    def received_records(self) -> tuple[DeviceRecordCollection, ...]:
        """Received record collections for inspection."""

        return self._received_records

    def receive_records(
        self,
        collections: Iterable[DeviceRecordCollection],
    ) -> None:
        """Receive accepted record collections and forward them if storage is set."""

        self._received_records = tuple(collections)
        if self._storage_manager is not None:
            self._storage_manager.store_records(self._received_records)
