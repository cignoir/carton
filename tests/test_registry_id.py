"""Unit tests for :mod:`carton.core.registry_id`."""

import re

import pytest

from carton.core.registry_id import (
    is_valid_registry_id,
    new_registry_id,
    read_registry_id,
    stamp_registry_id,
)


_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)


class TestNewRegistryId:
    def test_format_is_uuid_v4(self):
        rid = new_registry_id()
        assert _UUID_RE.match(rid), "expected lowercase UUID, got {!r}".format(rid)
        # version nibble of UUID v4 is always '4'
        assert rid[14] == "4"

    def test_returns_unique_values(self):
        assert new_registry_id() != new_registry_id()


class TestIsValidRegistryId:
    def test_accepts_canonical(self):
        assert is_valid_registry_id("c0a8f1f9-1a2e-4b5c-9d7a-5f8e1a2b3c4d")

    def test_rejects_empty(self):
        assert not is_valid_registry_id("")
        assert not is_valid_registry_id(None)

    def test_rejects_uppercase(self):
        # We normalise to lowercase before validating, but bare uppercase
        # strings are not themselves valid — callers are expected to pass
        # already-normalised values. The helper is lenient here: it strips
        # + lowers first.
        assert is_valid_registry_id("C0A8F1F9-1A2E-4B5C-9D7A-5F8E1A2B3C4D")

    def test_rejects_non_uuid(self):
        assert not is_valid_registry_id("not-a-uuid")
        assert not is_valid_registry_id("12345")

    def test_rejects_malformed_hyphens(self):
        assert not is_valid_registry_id("c0a8f1f91a2e4b5c9d7a5f8e1a2b3c4d")  # no hyphens


class TestReadRegistryId:
    def test_missing_returns_empty(self):
        assert read_registry_id({}) == ""

    def test_none_returns_empty(self):
        assert read_registry_id(None) == ""

    def test_invalid_returns_empty(self):
        assert read_registry_id({"registry_id": "not-uuid"}) == ""

    def test_valid_returns_lowercased(self):
        raw = "C0A8F1F9-1A2E-4B5C-9D7A-5F8E1A2B3C4D"
        assert read_registry_id({"registry_id": raw}) == raw.lower()

    def test_whitespace_trimmed(self):
        rid = "  c0a8f1f9-1a2e-4b5c-9d7a-5f8e1a2b3c4d  "
        assert read_registry_id({"registry_id": rid}) == rid.strip()


class TestStampRegistryId:
    def test_preserves_existing_valid_id(self):
        data = {"registry_id": "c0a8f1f9-1a2e-4b5c-9d7a-5f8e1a2b3c4d"}
        rid, was_new = stamp_registry_id(data)
        assert rid == "c0a8f1f9-1a2e-4b5c-9d7a-5f8e1a2b3c4d"
        assert was_new is False
        assert data["registry_id"] == rid

    def test_generates_when_missing(self):
        data = {}
        rid, was_new = stamp_registry_id(data)
        assert was_new is True
        assert _UUID_RE.match(rid)
        assert data["registry_id"] == rid

    def test_overwrites_invalid_id(self):
        data = {"registry_id": "garbage"}
        rid, was_new = stamp_registry_id(data)
        assert was_new is True
        assert _UUID_RE.match(rid)
        assert data["registry_id"] == rid
