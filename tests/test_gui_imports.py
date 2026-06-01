import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class TestGuiModules(unittest.TestCase):
    def test_gui_modules_import_without_starting_event_loop(self):
        import sun_gui
        import sun_host
        import sun_monitor

        self.assertTrue(hasattr(sun_gui, "SunMainWindow"))
        self.assertTrue(hasattr(sun_host, "SunHost"))
        self.assertTrue(hasattr(sun_monitor, "SunMonitorWidget"))


if __name__ == "__main__":
    unittest.main()
