"""SHA256 hash verification."""

import hashlib


def compute_sha256(file_path):
    """Compute the SHA256 hash of a file."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def verify_sha256(file_path, expected_hash):
    """Check whether the file's hash matches the expected value."""
    return compute_sha256(file_path) == expected_hash
