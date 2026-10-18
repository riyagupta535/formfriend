import os


def cors_origins() -> list[str]:
    """Exact frontend origins; previews must be explicitly added by the operator."""
    configured = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:3001")
    return list(dict.fromkeys(origin.strip().rstrip("/") for origin in configured.split(",") if origin.strip()))
