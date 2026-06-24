"""Reusable test-only fake adapters."""

from lab_sync_acquisition import DeviceAdapter


class ReadyFakeAdapter(DeviceAdapter):
    """Test-only adapter that reports ready after initialization."""

    def check_ready(self):
        return self._mark_ready()
