"""Tests for SHA256 verification."""

import os
import tempfile

from carton.core.hash_verify import compute_sha256, verify_sha256


class TestSha256:
    def test_compute(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f:
            f.write(b"hello world")
            path = f.name
        try:
            h = compute_sha256(path)
            assert h == "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"
        finally:
            os.remove(path)

    def test_verify_match(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f:
            f.write(b"test data")
            path = f.name
        try:
            h = compute_sha256(path)
            assert verify_sha256(path, h) is True
        finally:
            os.remove(path)

    def test_verify_mismatch(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f:
            f.write(b"test data")
            path = f.name
        try:
            assert verify_sha256(path, "0000" * 16) is False
        finally:
            os.remove(path)
