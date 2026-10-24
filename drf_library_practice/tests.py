import os
from pathlib import Path
import runpy
from unittest.mock import patch

from django.test import SimpleTestCase


class EnvironmentSettingsTests(SimpleTestCase):
    def read_settings(self, **values):
        with patch.dict(os.environ, {"SECRET_KEY": "test-settings-key"}):
            os.environ.pop("DEBUG", None)
            os.environ.pop("ALLOWED_HOSTS", None)
            os.environ.update(values)
            with patch("dotenv.load_dotenv"):
                return runpy.run_path(str(Path(__file__).with_name("settings.py")))

    def test_defaults_disable_debug_and_allow_local_hosts(self):
        configured = self.read_settings()
        self.assertFalse(configured["DEBUG"])
        self.assertEqual(configured["ALLOWED_HOSTS"], ["127.0.0.1", "localhost"])

    def test_environment_enables_debug_and_parses_host_names(self):
        configured = self.read_settings(
            DEBUG="True",
            ALLOWED_HOSTS=" api.example.com, localhost, ,127.0.0.1 ",
        )
        self.assertTrue(configured["DEBUG"])
        self.assertEqual(
            configured["ALLOWED_HOSTS"],
            ["api.example.com", "localhost", "127.0.0.1"],
        )

    def test_false_strings_do_not_enable_debug(self):
        for value in ("False", "0", "off"):
            with self.subTest(value=value):
                self.assertFalse(self.read_settings(DEBUG=value)["DEBUG"])
