"""Minimal in-memory storage boundary for retained session evidence."""

from __future__ import annotations

from typing import Iterable

from lab_sync_acquisition.device_manager import DeviceRecordCollection


class InMemoryStorageManager:
    """Stores accepted device records in memory for read-back."""

    def __init__(self) -> None:
        self._stored_records: tuple[DeviceRecordCollection, ...] = ()

    @property
    def stored_records(self) -> tuple[DeviceRecordCollection, ...]:
        """Stored record collections for verification."""

        return self._stored_records

    def store_records(
        self,
        collections: Iterable[DeviceRecordCollection],
    ) -> None:
        """Store accepted record collections without transforming them."""

        self._stored_records = tuple(collections)
