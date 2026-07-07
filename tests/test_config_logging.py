"""Best-effort failures in Config must be visible, not silent.

Config.save() mirrors the overlay into the active profile and
Config.load() applies the profile overlay — both wrap those steps in
broad try/except so a profile problem never breaks startup or saving.
Historically the except blocks were bare ``pass``: a failed profile
write meant the user's catalogue changes quietly reverted on next
launch with no trace. These tests pin the contract: the operation
still succeeds, but a warning is logged.
"""

import logging

import pytest

from carton.core import profile_store
from carton.core.config import Config
from carton.core.log import get_logger


@pytest.fixture
def carton_log(caplog):
    """Capture the "carton" logger despite propagate=False."""
    logger = get_logger()
    logger.addHandler(caplog.handler)
    caplog.set_level(logging.WARNING, logger="carton")
    yield caplog
    logger.removeHandler(caplog.handler)


def test_mirror_save_failure_is_logged_not_raised(
        tmp_path, monkeypatch, carton_log):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr("carton.core.config.default_config_path",
                        lambda: str(config_path))

    def _boom(name, profile):
        raise OSError("disk full")

    monkeypatch.setattr(profile_store, "save_profile", _boom)

    c = Config(active_profile="default")
    c.add_catalogue("/some/path/catalogue.json", display_name="test")
    c.save()  # canonical save → profile mirror runs and fails

    # config.json itself was still written.
    assert config_path.exists()
    assert any("mirroring to profile" in r.message
               for r in carton_log.records)


def test_broken_profile_load_is_logged_and_config_values_survive(
        monkeypatch, carton_log):
    monkeypatch.setattr(profile_store, "profile_exists", lambda name: True)

    def _boom(name):
        raise ValueError("corrupt profile json")

    monkeypatch.setattr(profile_store, "load_profile", _boom)

    c = Config(active_profile="default")
    c.add_catalogue("/some/path/catalogue.json", display_name="survivor")
    c._ensure_default_profile_and_overlay()  # must not raise

    # The config.json snapshot keeps working when the overlay is broken.
    assert c.catalogues[0].display_name == "survivor"
    assert any("could not be loaded" in r.message
               for r in carton_log.records)


def test_default_profile_seed_failure_is_logged(monkeypatch, carton_log):
    monkeypatch.setattr(profile_store, "profile_exists", lambda name: False)

    def _boom(name, profile):
        raise OSError("read-only profiles dir")

    monkeypatch.setattr(profile_store, "save_profile", _boom)

    c = Config(active_profile="default")
    c.add_catalogue("/some/path/catalogue.json", display_name="test")
    c._ensure_default_profile_and_overlay()  # must not raise

    messages = [r.message for r in carton_log.records]
    assert any("'default' profile" in m for m in messages)
    assert any("could not seed profile" in m for m in messages)
