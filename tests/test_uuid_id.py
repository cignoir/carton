"""Unit tests for :mod:`carton.core.uuid_id`."""

import re

import pytest

from carton.core.uuid_id import (
    is_valid_uuid,
    new_uuid,
    read_uuid,
    stamp_uuid,
)


_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)


class TestNewUuid:
    def test_format_is_uuid_v4(self):
        rid = new_uuid()
        assert _UUID_RE.match(rid), "expected lowercase UUID, got {!r}".format(rid)
        # version nibble of UUID v4 is always '4'
        assert rid[14] == "4"

    def test_returns_unique_values(self):
        assert new_uuid() != new_uuid()


class TestIsValidUuid:
    def test_accepts_canonical(self):
        assert is_valid_uuid("c0a8f1f9-1a2e-4b5c-9d7a-5f8e1a2b3c4d")

    def test_rejects_empty(self):
        assert not is_valid_uuid("")
        assert not is_valid_uuid(None)

    def test_accepts_uppercase_after_normalisation(self):
        # The helper is lenient: it strips + lowers before validating, so
        # a callsite that didn't pre-normalise still gets the right answer.
        assert is_valid_uuid("C0A8F1F9-1A2E-4B5C-9D7A-5F8E1A2B3C4D")

    def test_rejects_non_uuid(self):
        assert not is_valid_uuid("not-a-uuid")
        assert not is_valid_uuid("12345")

    def test_rejects_malformed_hyphens(self):
        assert not is_valid_uuid("c0a8f1f91a2e4b5c9d7a5f8e1a2b3c4d")  # no hyphens


class TestReadUuid:
    def test_missing_returns_empty(self):
        assert read_uuid({}, "registry_id") == ""

    def test_none_returns_empty(self):
        assert read_uuid(None, "registry_id") == ""

    def test_invalid_returns_empty(self):
        assert read_uuid({"registry_id": "not-uuid"}, "registry_id") == ""

    def test_valid_returns_lowercased(self):
        raw = "C0A8F1F9-1A2E-4B5C-9D7A-5F8E1A2B3C4D"
        assert read_uuid({"registry_id": raw}, "registry_id") == raw.lower()

    def test_whitespace_trimmed(self):
        rid = "  c0a8f1f9-1a2e-4b5c-9d7a-5f8e1a2b3c4d  "
        assert read_uuid({"registry_id": rid}, "registry_id") == rid.strip()

    def test_picks_up_alternate_key(self):
        """The helper is key-agnostic — same logic for catalogue_id, etc."""
        rid = "c0a8f1f9-1a2e-4b5c-9d7a-5f8e1a2b3c4d"
        assert read_uuid({"catalogue_id": rid}, "catalogue_id") == rid


class TestStampUuid:
    def test_preserves_existing_valid_id(self):
        data = {"registry_id": "c0a8f1f9-1a2e-4b5c-9d7a-5f8e1a2b3c4d"}
        rid, was_new = stamp_uuid(data, "registry_id")
        assert rid == "c0a8f1f9-1a2e-4b5c-9d7a-5f8e1a2b3c4d"
        assert was_new is False
        assert data["registry_id"] == rid

    def test_generates_when_missing(self):
        data = {}
        rid, was_new = stamp_uuid(data, "registry_id")
        assert was_new is True
        assert _UUID_RE.match(rid)
        assert data["registry_id"] == rid

    def test_overwrites_invalid_id(self):
        data = {"registry_id": "garbage"}
        rid, was_new = stamp_uuid(data, "registry_id")
        assert was_new is True
        assert _UUID_RE.match(rid)
        assert data["registry_id"] == rid

    def test_stamps_into_alternate_key(self):
        data = {}
        rid, was_new = stamp_uuid(data, "catalogue_id")
        assert was_new is True
        assert "catalogue_id" in data
        assert "registry_id" not in data
