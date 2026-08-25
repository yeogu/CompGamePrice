import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
SPEC = importlib.util.spec_from_file_location(
    "steam_pipeline", ROOT / "tools" / "run_steam_pipeline.py"
)
steam_pipeline = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(steam_pipeline)


class Completed:
    def __init__(self, returncode):
        self.returncode = returncode


class SteamPipelineTest(unittest.TestCase):
    def test_rejects_a_second_pipeline_using_the_same_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory) / "pipeline.lock"
            with steam_pipeline.exclusive_lock(lock):
                with self.assertRaises(steam_pipeline.PipelineAlreadyRunning):
                    with steam_pipeline.exclusive_lock(lock):
                        pass

    def test_collects_then_imports_and_writes_report(self):
        fixture = (
            ROOT / "tests" / "fixtures" / "steam_appdetails_413150.json"
        ).read_bytes()
        commands = []

        def fixture_fetch(app_id, _country, _language, _timeout):
            return fixture, 200, f"fixture://steam/{app_id}"

        def fake_runner(command, check):
            self.assertFalse(check)
            commands.append(command)
            return Completed(0)

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "snapshot"
            exit_code = steam_pipeline.run_pipeline(
                Path("build/game_price_tracker"),
                ROOT / "data" / "steam_collection_targets.json",
                output,
                request_delay=0,
                retry_delay=0,
                fetcher=fixture_fetch,
                command_runner=fake_runner,
            )

            self.assertEqual(exit_code, 0)
            self.assertEqual(len(commands), 1)
            self.assertEqual(commands[0][1], "collect-steam-all")
            report = json.loads((output / "steam_pipeline_run.json").read_text())
            self.assertEqual(report["targets"], 1)
            self.assertEqual(report["collected"], 1)
            self.assertEqual(report["failures"], [])
            self.assertEqual(report["importExitCode"], 0)

    def test_does_not_import_when_every_collection_fails(self):
        def failed_fetch(_app_id, _country, _language, _timeout):
            raise RuntimeError("offline")

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "snapshot"
            exit_code = steam_pipeline.run_pipeline(
                Path("unused"),
                ROOT / "data" / "steam_collection_targets.json",
                output,
                request_delay=0,
                retry_delay=0,
                max_attempts=1,
                fetcher=failed_fetch,
                command_runner=lambda *_args, **_kwargs: self.fail(
                    "Importer must not run without a successful snapshot"
                ),
            )
            self.assertEqual(exit_code, 1)
            report = json.loads((output / "steam_pipeline_run.json").read_text())
            self.assertEqual(report["collected"], 0)
            self.assertEqual(report["importExitCode"], None)
            self.assertEqual(report["failures"][0]["error"], "offline")


if __name__ == "__main__":
    unittest.main()
