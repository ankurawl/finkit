"""UUID tag generation for Beancount transactions."""

from __future__ import annotations

import uuid


TAG_PREFIX = "uuid-"


def generate_uuid_tag() -> str:
    """Generate an 8-character hex UUID tag for a transaction."""
    return TAG_PREFIX + uuid.uuid4().hex[:8]


def format_tag(tag: str) -> str:
    """Format a tag for use in Beancount syntax (with # prefix)."""
    return f"#{tag}"


def is_uuid_tag(tag: str) -> bool:
    """Check if a tag is a finkit UUID tag."""
    clean = tag.lstrip("#")
    return clean.startswith(TAG_PREFIX) and len(clean) == len(TAG_PREFIX) + 8


def extract_uuid(tag: str) -> str | None:
    """Extract the UUID portion from a tag, or None if not a UUID tag."""
    clean = tag.lstrip("#")
    if is_uuid_tag(clean):
        return clean[len(TAG_PREFIX):]
    return None
