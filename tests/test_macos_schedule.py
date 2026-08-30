import importlib.util
from pathlib import Path
import plistlib
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "macos_schedule", ROOT / "tools" / "generate_macos_schedule.py"
)
macos_schedule = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(macos_schedule)


class MacOsScheduleTest(unittest.TestCase):
    def test_generates_daily_pipeline_schedule_with_absolute_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            output = Path(directory) / "schedule.plist"
            macos_schedule.write_schedule(project, output, 9, 30)

            with output.open("rb") as source:
                schedule = plistlib.load(source)
            self.assertEqual(schedule["Label"], macos_schedule.LABEL)
            self.assertEqual(
                schedule["StartCalendarInterval"], {"Hour": 9, "Minute": 30}
            )
            self.assertEqual(schedule["WorkingDirectory"], str(project.resolve()))
            arguments = schedule["ProgramArguments"]
            self.assertIn(str(project.resolve() / "tools" / "run_daily_operations.py"), arguments)
            self.assertIn(str(project.resolve() / "build" / "game_price_tracker"), arguments)
            self.assertIn(str(project.resolve() / "snapshots" / "notification-outbox.jsonl"), arguments)
            self.assertIn("--catalog-batch-size", arguments)
            self.assertNotIn("--targets", arguments)
            self.assertTrue(Path(schedule["StandardOutPath"]).is_absolute())
            self.assertTrue((project / "snapshots" / "logs").is_dir())

    def test_rejects_invalid_schedule_time(self):
        with self.assertRaisesRegex(ValueError, "valid hour"):
            macos_schedule.schedule_definition(ROOT, 24, 0)
        with self.assertRaisesRegex(ValueError, "valid hour"):
            macos_schedule.schedule_definition(ROOT, 9, 60)


if __name__ == "__main__":
    unittest.main()
