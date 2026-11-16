import time

from leavedesk.db.ids import uuid7


def test_uuid7_has_version_7_and_rfc_variant():
    value = uuid7()

    assert value.version == 7
    assert value.variant == "specified in RFC 4122"


def test_uuid7_starts_with_the_current_time():
    before = time.time_ns() // 1_000_000
    value = uuid7()
    after = time.time_ns() // 1_000_000

    milliseconds = int.from_bytes(value.bytes[:6], "big")
    assert before <= milliseconds <= after


def test_uuid7_sorts_by_creation_time():
    first = uuid7()
    time.sleep(0.002)
    second = uuid7()

    assert first < second


def test_uuid7_values_are_unique():
    assert len({uuid7() for _ in range(10_000)}) == 10_000
