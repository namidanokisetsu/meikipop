import logging
import io
import runpy
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from meikipop.utils import logger


class LoggerTests(unittest.TestCase):
    def test_mac_bundle_keeps_diagnostics_when_launch_services_provides_streams(self):
        with tempfile.TemporaryDirectory() as directory:
            original = io.StringIO()
            with patch("sys.platform", "darwin"), patch("sys.stderr", original), \
                    patch("platformdirs.user_cache_dir", return_value=directory):
                state = runpy.run_path(str(Path(__file__).resolve().parents[1] / "packaging/runtime.py"))
                logger.sys.stderr.write("macOS packaged diagnostic\n")
                logger.sys.stderr.flush()
                state["stream"].close()
            self.assertIn("macOS packaged diagnostic", original.getvalue())
            self.assertIn("macOS packaged diagnostic", (Path(directory) / "meikipop-runtime.log").read_text())

    def tearDown(self):
        root_logger = logging.getLogger()
        for handler in root_logger.handlers[:]:
            handler.close()
            root_logger.removeHandler(handler)

    def test_windowed_mode_logs_to_file_without_stdout(self):
        with tempfile.TemporaryDirectory() as temp_dir, \
                patch.object(logger.sys, "stdout", None), \
                patch.object(logger, "paths", types.SimpleNamespace(cache_dir=temp_dir)):
            logger.setup_logging()
            logging.getLogger().info("windowed logging works")
            for handler in logging.getLogger().handlers:
                handler.flush()

            log_text = (Path(temp_dir) / "meikipop.log").read_text(encoding="utf-8")
            for handler in logging.getLogger().handlers:
                handler.close()

        self.assertIn("windowed logging works", log_text)


if __name__ == "__main__":
    unittest.main()
