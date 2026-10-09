"""Motion-free regression tests for cooperative stop/resume/restart."""
from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import execute_plan
import piper_draw_ui
from draw_run_state import read_json, set_stop


class DummyArm:
    def connect(self):
        pass

    def disconnect(self):
        pass

    def set_motion_mode(self, _mode):
        pass

    def set_speed_percent(self, _speed):
        pass


class DrawControlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        folder = Path(self.temp.name)
        self.plan = folder / "plan.json"
        self.calibration = folder / "calibration.json"
        self.progress = folder / "progress.json"
        self.control = folder / "control.json"
        self.calibration.write_text('{"points":{}}', encoding="utf-8")
        self.plan.write_text(json.dumps({
            "status": "preview_only_no_robot_motion",
            "strokes": [
                {"id": "a", "points": [[0, 0], [10, 0]], "length_mm": 10,
                 "recommended_contact_depth_mm": 0.8},
                {"id": "b", "points": [[0, 10], [10, 10]], "length_mm": 10,
                 "recommended_contact_depth_mm": 0.8},
            ],
        }), encoding="utf-8")
        self.moves = []

    def run_executor(self, run_id, extra=(), stop_on=None, fail_on=None):
        set_stop(self.control, run_id, False)
        self.moves.clear()

        def fake_move(_robot, target, where, linear=False):
            self.moves.append((where, target[:3], linear))
            if where == stop_on:
                set_stop(self.control, run_id, True)
            if where == fail_on:
                raise TimeoutError("simulated verified-arrival timeout")

        factory = types.SimpleNamespace(create_arm=lambda _config: DummyArm())
        fake_sdk = types.SimpleNamespace(AgxArmFactory=factory)
        argv = ["execute_plan.py", "--plan", str(self.plan), "--execute", "--confirmed",
                "--approved-plan", "--run-id", run_id, *extra]
        with (patch.object(sys, "argv", argv),
              patch.object(execute_plan, "CALIBRATION", self.calibration),
              patch.object(execute_plan, "paths_for_plan", return_value=(self.progress, self.control)),
              patch.object(execute_plan, "status_preflight", return_value={"can_adapter": "fake:0", "joint_feedback_hz": 220}),
              patch.object(execute_plan, "paper_mapper", return_value=(
                  lambda xy, height: [xy[0] / 1000, xy[1] / 1000, height / 1000, 0, 0, 0], [0, 0, 1])),
              patch.object(execute_plan, "arm_config", return_value={}),
              patch.object(execute_plan, "feedback_or_fail"),
              patch.object(execute_plan, "move_verified", side_effect=fake_move),
              patch.object(execute_plan.time, "sleep"),
              patch.dict(sys.modules, {"pyAgxArm": fake_sdk})):
            execute_plan.main()
        return read_json(self.progress)

    def test_stop_lifts_then_resume_from_last_verified_point(self):
        paused = self.run_executor("first", stop_on="stroke 1 point 1")
        self.assertEqual(paused["status"], "paused")
        self.assertEqual((paused["next_stroke"], paused["next_point"]), (0, 2))
        self.assertEqual(self.moves[-1][0], "stroke 1 stop lift")
        self.assertAlmostEqual(self.moves[-1][1][2], 0.022)

        complete = self.run_executor("second", extra=("--resume",))
        self.assertEqual(complete["status"], "complete")
        self.assertEqual(self.moves[0][0], "stroke 1 hover")
        self.assertAlmostEqual(self.moves[0][1][0], 0.005)
        self.assertTrue(any(name == "stroke 2 point 2" for name, _target, _linear in self.moves))

    def test_restart_ignores_checkpoint_and_starts_at_first_point(self):
        self.run_executor("first", stop_on="stroke 1 point 1")
        result = self.run_executor("restart", extra=("--restart",))
        self.assertEqual(result["status"], "complete")
        self.assertEqual(self.moves[0][0], "stroke 1 hover")
        self.assertAlmostEqual(self.moves[0][1][0], 0.0)

    def test_changed_calibration_blocks_resume_before_motion(self):
        self.run_executor("first", stop_on="stroke 1 point 1")
        self.calibration.write_text('{"points":{"changed":true}}', encoding="utf-8")
        with self.assertRaises(SystemExit):
            self.run_executor("second", extra=("--resume",))
        self.assertEqual(self.moves, [])

    def test_failed_lift_is_not_resumable(self):
        with self.assertRaises(TimeoutError):
            self.run_executor("first", stop_on="stroke 1 point 1", fail_on="stroke 1 stop lift")
        self.assertEqual(read_json(self.progress)["status"], "stopped")
        with self.assertRaises(SystemExit):
            self.run_executor("second", extra=("--resume",))
        self.assertEqual(self.moves, [])
        with self.assertRaises(SystemExit):
            self.run_executor("third", extra=("--restart",))
        self.assertEqual(self.moves, [])


class DrawManagerTests(unittest.TestCase):
    def test_stop_and_resume_are_scoped_to_one_run(self):
        with tempfile.TemporaryDirectory() as folder_name:
            folder = Path(folder_name)
            plan = folder / "plan.json"
            plan.write_text("{}", encoding="utf-8")
            progress = folder / "progress.json"
            control = folder / "control.json"
            launch = folder / "launch.json"
            processes = []

            class FakeProcess:
                stdout = None

                def __init__(self, command, **_kwargs):
                    self.command = command
                    self.code = None
                    processes.append(self)

                def poll(self):
                    return self.code

            manager = piper_draw_ui.DrawManager()
            with (patch.object(piper_draw_ui, "ROOT", folder),
                  patch.object(piper_draw_ui, "DRAWINGS", {"test": {"plan": "plan.json"}}),
                  patch.object(piper_draw_ui, "paths_for_plan", return_value=(progress, control)),
                  patch.object(piper_draw_ui, "launch_path_for_plan", return_value=launch),
                  patch.object(piper_draw_ui.subprocess, "Popen", side_effect=FakeProcess),
                  patch.object(piper_draw_ui.threading, "Thread")):
                self.assertTrue(manager.start("test")[0])
                self.assertFalse(manager.start("test", "restart")[0])
                self.assertTrue(manager.stop()[0])
                self.assertTrue(read_json(control)["stop_requested"])
                self.assertTrue(manager.status()["stop_pending"])
                restarted_server = piper_draw_ui.DrawManager()
                self.assertEqual(restarted_server.status()["states"]["test"]["status"], "interrupted")
                self.assertFalse(restarted_server.start("test", "resume")[0])
                processes[-1].code = 0
                launch.write_text('{"status":"finished"}', encoding="utf-8")
                progress.write_text('{"status":"paused"}', encoding="utf-8")
                self.assertTrue(manager.start("test", "resume")[0])
                self.assertIn("--resume", processes[-1].command)
                self.assertFalse(read_json(control)["stop_requested"])


if __name__ == "__main__":
    unittest.main()
