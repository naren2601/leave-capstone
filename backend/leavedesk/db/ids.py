"""UUIDv7 ids, generated in the app because PostgreSQL 16 has no uuidv7().

A UUIDv7 starts with a 48-bit millisecond timestamp, followed by random bits.
New ids therefore sort roughly by creation time, so inserts land at the end
of a B-tree index (like an identity column) instead of at random places
(like UUIDv4), while the random part keeps them hard to guess.
See RFC 9562, section 5.7.
"""

import secrets
import time
import uuid


def uuid7() -> uuid.UUID:
    milliseconds = time.time_ns() // 1_000_000
    raw = bytearray(milliseconds.to_bytes(6, "big") + secrets.token_bytes(10))
    raw[6] = (raw[6] & 0x0F) | 0x70  # version 7
    raw[8] = (raw[8] & 0x3F) | 0x80  # RFC 9562 variant
    return uuid.UUID(bytes=bytes(raw))
