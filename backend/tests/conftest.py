import pytest


@pytest.fixture(autouse=True)
def disable_gemini_cache_by_default(monkeypatch):
    """Tests opt into a temporary cache explicitly to avoid cross-test state."""
    monkeypatch.setenv("GEMINI_CACHE_TTL_SECONDS", "0")
