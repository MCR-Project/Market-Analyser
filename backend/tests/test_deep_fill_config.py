"""
Tests for the Deep-fill settings (issue #171): ALLOW_DEEP_FILL, DEEP_FILL_TTL_SECONDS,
DEEP_FILL_MAX_FUNDS and DEEP_FILL_BATCH_SIZE.

Two things are pinned. The defaults are the ones the issue names - off, a day,
three funds, fifty tickers a batch - and a malformed value falls back to its
default instead of crashing boot: these are read from the environment by people
editing a Render dashboard, and a typo there must never stop the API starting
(the same reason `get_client_optional` never raises).

They are read when asked, not once at import: main.py loads `.env` *after*
importing the routes, so a module-level read would see an environment without
the file's values.

Run with:   pytest   (from the repo root)
"""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config

_NAMES = ("ALLOW_DEEP_FILL", "DEEP_FILL_TTL_SECONDS", "DEEP_FILL_MAX_FUNDS", "DEEP_FILL_BATCH_SIZE")


def _env(**values):
    """The environment with the four settings cleared, then `values` set."""
    cleaned = {k: v for k, v in os.environ.items() if k not in _NAMES}
    return patch.dict(os.environ, {**cleaned, **values}, clear=True)


class DefaultsTests(unittest.TestCase):
    def test_every_setting_has_the_documented_default(self):
        with _env():
            self.assertFalse(config.deep_fill_enabled())
            self.assertEqual(config.deep_fill_ttl_seconds(), 86400)
            self.assertEqual(config.deep_fill_max_funds(), 3)
            self.assertEqual(config.deep_fill_batch_size(), 50)


class EnabledTests(unittest.TestCase):
    def test_the_usual_spellings_of_yes_turn_it_on(self):
        for spelling in ("1", "true", "TRUE", "yes", "On", " true "):
            with self.subTest(spelling), _env(ALLOW_DEEP_FILL=spelling):
                self.assertTrue(config.deep_fill_enabled())

    def test_anything_else_leaves_it_off(self):
        for spelling in ("", "0", "false", "no", "off", "banana"):
            with self.subTest(spelling), _env(ALLOW_DEEP_FILL=spelling):
                self.assertFalse(config.deep_fill_enabled())


class NumbersTests(unittest.TestCase):
    def test_a_valid_value_is_used(self):
        with _env(DEEP_FILL_TTL_SECONDS="600", DEEP_FILL_MAX_FUNDS="5", DEEP_FILL_BATCH_SIZE="20"):
            self.assertEqual(config.deep_fill_ttl_seconds(), 600)
            self.assertEqual(config.deep_fill_max_funds(), 5)
            self.assertEqual(config.deep_fill_batch_size(), 20)

    def test_a_malformed_value_falls_back_to_its_default(self):
        for bad in ("", "abc", "1.5", "0", "-3"):
            with self.subTest(bad), _env(
                DEEP_FILL_TTL_SECONDS=bad, DEEP_FILL_MAX_FUNDS=bad, DEEP_FILL_BATCH_SIZE=bad
            ):
                self.assertEqual(config.deep_fill_ttl_seconds(), 86400)
                self.assertEqual(config.deep_fill_max_funds(), 3)
                self.assertEqual(config.deep_fill_batch_size(), 50)


if __name__ == "__main__":
    unittest.main()
