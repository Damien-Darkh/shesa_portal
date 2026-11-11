from datetime import datetime, timezone


def utcnow() -> datetime:
    """Naive UTC timestamp (same storage format as the old datetime.utcnow())."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
