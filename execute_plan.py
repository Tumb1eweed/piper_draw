#!/usr/bin/env python3
"""Safely execute a reviewed centreline plan on Piper.

This program is deliberately inert unless all three execution flags are
present.  Its normal use is ``--dry-run`` (the default), which validates the
trajectory without opening CAN or moving the robot.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

from draw_run_state import file_hash, paths_for_plan, read_json, set_stop, stop_requested, write_json
from piper_runtime import CALIBRATION, arm_config, arm_fault_reason, can_connection


ROOT = Path(__file__).resolve().parent
HOVER_MM = 22.0
MAX_POINT_STEP_MM = 5.0
ARRIVAL_TOLERANCE_MM = 2.5
MIN_FEEDBACK_HZ = 100.0


def add(a, b):
    return [a[i] + b[i] for i in range(3)]


def sub(a, b):
    return [a[i] - b[i] for i in range(3)]


def scale(a, k):
    return [value * k for value in a]


def dot(a, b):
    return sum(a[i] * b[i] for i in range(3))


def unit(a):
    length = math.sqrt(dot(a, a))
    if length < 1e-9:
        raise RuntimeError("invalid calibrated paper plane")
    return scale(a, 1.0 / length)


def record(progress, **data):
    data["timestamp"] = time.time()
    write_json(progress, data)


def load_plan(path):
    if not path.exists():
        raise RuntimeError(f"trajectory plan missing: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    strokes = data.get("strokes")
    if data.get("status") != "preview_only_no_robot_motion" or not isinstance(strokes, list) or not strokes:
        raise RuntimeError("unexpected centreline plan format; regenerate/review the preview first")
    for index, stroke in enumerate(strokes, 1):
        points = stroke.get("points")
        if not isinstance(points, list) or len(points) < 2:
            raise RuntimeError(f"stroke {index} has too few points")
        for point in points:
            if (not isinstance(point, list) or len(point) != 2 or
                    not all(isinstance(value, (float, int)) and math.isfinite(value) for value in point)):
                raise RuntimeError(f"stroke {index} contains an invalid point")
        depth = stroke.get("recommended_contact_depth_mm")
        if not isinstance(depth, (float, int)) or not 0.4 <= depth <= 1.4:
            raise RuntimeError(f"stroke {index} has unsafe contact-depth metadata")
    return data


def paper_mapper():
    """Return local-paper-mm -> current calibrated TCP pose; never edits calibration."""
    if not CALIBRATION.exists():
        raise RuntimeError(f"paper calibration missing: {CALIBRATION}")
    points = json.loads(CALIBRATION.read_text(encoding="utf-8"))["points"]
    origin, x_point, y_point, lift = (points[name]["tcp_pose"] for name in ("origin", "x", "y", "lift"))
    planar_origin = [origin[0], origin[1], 0.0]
    ex = unit(sub([x_point[0], x_point[1], 0.0], planar_origin))
    raw_y = sub([y_point[0], y_point[1], 0.0], planar_origin)
    ey = unit(sub(raw_y, scale(ex, dot(raw_y, ex))))
    normal = unit([
        (x_point[1] - origin[1]) * (y_point[2] - origin[2]) - (x_point[2] - origin[2]) * (y_point[1] - origin[1]),
        (x_point[2] - origin[2]) * (y_point[0] - origin[0]) - (x_point[0] - origin[0]) * (y_point[2] - origin[2]),
        (x_point[0] - origin[0]) * (y_point[1] - origin[1]) - (x_point[1] - origin[1]) * (y_point[0] - origin[0]),
    ])
    if dot(normal, sub(lift[:3], origin[:3])) < 0:
        normal = scale(normal, -1.0)

    def pose(local_mm, height_mm):
        planar = add(add(planar_origin, scale(ex, local_mm[0] / 1000.0)), scale(ey, local_mm[1] / 1000.0))
        xyz = add([planar[0], planar[1], origin[2]], scale(normal, height_mm / 1000.0))
        return [*xyz, *origin[3:]]

    return pose, normal


def status_preflight():
    """Perform the required non-motion CAN and SDK feedback gate."""
    interface, channel = can_connection()

    reader = subprocess.run(
        [sys.executable, str(ROOT / "read_piper_status.py"), "--wait", "3"],
        text=True,
        capture_output=True,
        timeout=12,
    )
    output = (reader.stdout + "\n" + reader.stderr).strip()
    hz_match = re.search(r"joint_feedback_hz:\s*([0-9.]+)", output)
    has_bad_feedback = "no feedback received" in output.lower()
    if (reader.returncode != 0 or has_bad_feedback or "arm_status: None" in output or
            "connected:  True" not in output or "comm_error: False" not in output or
            "arm_fault: none" not in output or not hz_match):
        raise RuntimeError("status reader did not receive usable arm and joint feedback:\n" + output)
    hz = float(hz_match.group(1))
    if hz < MIN_FEEDBACK_HZ:
        raise RuntimeError(f"joint feedback is only {hz:.1f} Hz (need at least {MIN_FEEDBACK_HZ:.0f} Hz)")
    return {"can_adapter": f"{interface}:{channel}", "joint_feedback_hz": hz, "reader": output}


def distance_mm(a, b):
    return 1000.0 * math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


def feedback_or_fail(robot, where):
    arm_status = robot.get_arm_status()
    joints = robot.get_joint_angles()
    if (robot.has_comm_error() or arm_status is None or joints is None or
            arm_status.hz < MIN_FEEDBACK_HZ or joints.hz < MIN_FEEDBACK_HZ or
            robot.get_tcp_pose() is None):
        raise RuntimeError(f"SDK feedback unavailable at {where}; no further trajectory commands will be issued")
    fault = arm_fault_reason(arm_status)
    if fault is not None:
        raise RuntimeError(f"SDK arm/joint fault at {where}: {fault}; no further trajectory commands will be issued")


def wait_arrival(robot, target, where, timeout=35.0):
    """Wait for three consecutive in-tolerance, successful feedback samples.

    Piper encodes ``motion_status == 1`` as *not yet reached*, although this
    SDK renders the enum as ``REACH_TARGET_POS_FAILED``.  It is a progress
    state, not a terminal fault.  Only a lost SDK feedback stream or
    exhaustion of this bounded wait may stop a drawing.
    """
    deadline = time.monotonic() + timeout
    stable = 0
    while time.monotonic() < deadline:
        feedback_or_fail(robot, where)
        status = robot.get_arm_status()
        actual = robot.get_tcp_pose()
        arrived = getattr(status.msg, "motion_status", None) == 0 and distance_mm(actual.msg, target) <= ARRIVAL_TOLERANCE_MM
        stable = stable + 1 if arrived else 0
        if stable >= 3:
            return
        time.sleep(0.07)
    raise TimeoutError(f"could not verify arrival at {where}")


def move_verified(robot, target, where, linear=False):
    (robot.move_l if linear else robot.move_p)(target)
    wait_arrival(robot, target, where)


def rdp(points, epsilon=0.65):
    if len(points) < 3:
        return points
    first, last = points[0], points[-1]
    vx, vy = last[0] - first[0], last[1] - first[1]
    denominator = vx * vx + vy * vy
    farthest, split = -1.0, 0
    for index, point in enumerate(points[1:-1], 1):
        if denominator == 0:
            distance = math.dist(point, first)
        else:
            distance = abs(vx * (first[1] - point[1]) - (first[0] - point[0]) * vy) / math.sqrt(denominator)
        if distance > farthest:
            farthest, split = distance, index
    if farthest > epsilon:
        return rdp(points[:split + 1], epsilon)[:-1] + rdp(points[split:], epsilon)
    return [first, last]


def bounded_steps(points, max_step=MAX_POINT_STEP_MM):
    result = [points[0]]
    for start, end in zip(points, points[1:]):
        steps = max(1, math.ceil(math.dist(start, end) / max_step))
        result.extend([
            [start[0] + (end[0] - start[0]) * step / steps, start[1] + (end[1] - start[1]) * step / steps]
            for step in range(1, steps + 1)
        ])
    return result


def plan_summary(plan):
    strokes = plan["strokes"]
    draw_length = sum(float(stroke["length_mm"]) for stroke in strokes)
    travel_length = sum(float(stroke.get("travel_from_previous_mm", 0.0)) for stroke in strokes)
    points = sum(len(bounded_steps(rdp(stroke["points"]))) for stroke in strokes)
    return {"strokes": len(strokes), "draw_length_mm": round(draw_length, 1), "pen_up_travel_mm": round(travel_length, 1), "verified_line_targets": points}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="allow real robot motion")
    parser.add_argument("--confirmed", action="store_true", help="confirm a person has cleared the robot and paper")
    parser.add_argument("--approved-plan", action="store_true", help="confirm the trajectory preview was reviewed")
    parser.add_argument("--plan", type=Path, required=True, help="reviewed preview-only plan.json to run")
    parser.add_argument("--speed", type=int, default=8, help="motion speed percent (4..12; default 8)")
    parser.add_argument("--depth-offset-mm", type=float, default=0.0, help="add -0.4..+0.4 mm to reviewed contact depths")
    parser.add_argument("--resume", action="store_true", help="resume a verified user-paused checkpoint")
    parser.add_argument("--restart", action="store_true", help="explicitly discard a prior checkpoint and start at stroke one")
    parser.add_argument("--run-id", help="opaque control token supplied by the local UI")
    args = parser.parse_args()

    if not 4 <= args.speed <= 12:
        raise SystemExit("--speed must be between 4 and 12 percent")
    if not -0.4 <= args.depth_offset_mm <= 0.4:
        raise SystemExit("--depth-offset-mm must be between -0.4 and +0.4")
    if args.resume and args.restart:
        raise SystemExit("--resume and --restart are mutually exclusive")
    plan_path = args.plan.expanduser().resolve()
    progress, control = paths_for_plan(plan_path)
    plan_sha = file_hash(plan_path)
    plan = load_plan(plan_path)
    if file_hash(plan_path) != plan_sha:
        raise SystemExit("Plan changed while loading; refuse motion")
    summary = plan_summary(plan)
    print(json.dumps({"mode": "execute" if args.execute else "dry-run", "plan": str(plan_path), **summary}, ensure_ascii=False, indent=2))
    if not args.execute:
        return
    if not (args.confirmed and args.approved_plan):
        raise SystemExit("Refusing physical motion: require --execute --confirmed --approved-plan.")

    calibration_sha = file_hash(CALIBRATION)
    previous = read_json(progress)
    if args.resume:
        if not previous or previous.get("status") != "paused":
            raise SystemExit("Only a verified paused checkpoint can be resumed")
        if previous.get("plan_sha256") != plan_sha or previous.get("calibration_sha256") != calibration_sha:
            raise SystemExit("Plan or paper calibration changed; cannot resume")
        if previous.get("speed") != args.speed or previous.get("depth_offset_mm") != args.depth_offset_mm:
            raise SystemExit("Motion parameters changed; cannot resume")
        start_stroke = previous.get("next_stroke")
        start_point = previous.get("next_point")
        if (not isinstance(start_stroke, int) or not 0 <= start_stroke < len(plan["strokes"]) or
                not isinstance(start_point, int) or start_point < 1 or
                start_point >= len(bounded_steps(rdp(plan["strokes"][start_stroke]["points"])))):
            raise SystemExit("Paused checkpoint is invalid; refuse motion")
    else:
        if previous and previous.get("status") == "stopped":
            raise SystemExit("Previous run failed; inspect the arm and resolve the checkpoint manually before new motion")
        if previous and previous.get("status") in ("paused", "running") and not args.restart:
            raise SystemExit("Existing checkpoint needs --resume or explicit --restart")
        start_stroke, start_point = 0, 1

    run_id = args.run_id or uuid.uuid4().hex
    if args.run_id:
        control_data = read_json(control)
        if not control_data or control_data.get("run_id") != run_id:
            raise SystemExit("UI control token is missing or stale")
    else:
        set_stop(control, run_id, False)

    base = {"run_id": run_id, "plan_sha256": plan_sha, "calibration_sha256": calibration_sha,
            "speed": args.speed, "depth_offset_mm": args.depth_offset_mm, "total": summary["strokes"], **summary}

    def checkpoint(status, phase, stroke_idx, next_point, **details):
        record(progress, **base, status=status, phase=phase, completed=stroke_idx,
               next_stroke=stroke_idx, next_point=next_point, **details)

    preflight = status_preflight()
    print(json.dumps({"preflight": {"can_adapter": preflight["can_adapter"], "joint_feedback_hz": preflight["joint_feedback_hz"]}}, ensure_ascii=False))
    pose, _normal = paper_mapper()
    if file_hash(CALIBRATION) != calibration_sha:
        raise SystemExit("Paper calibration changed during preflight; refuse motion")

    from pyAgxArm import AgxArmFactory
    robot = AgxArmFactory.create_arm(arm_config())
    started = False
    try:
        robot.connect()
        time.sleep(2.0)
        feedback_or_fail(robot, "SDK startup")
        robot.set_motion_mode("p")
        robot.set_speed_percent(args.speed)
        if stop_requested(control, run_id):
            # No trajectory command has been sent; preserve the previous safe checkpoint.
            checkpoint("paused", "stopped_before_motion", start_stroke, start_point)
            return
        checkpoint("running", "preflight_passed", start_stroke, start_point)
        started = True

        for stroke_idx in range(start_stroke, len(plan["strokes"])):
            index = stroke_idx + 1
            stroke = plan["strokes"][stroke_idx]
            points = bounded_steps(rdp(stroke["points"]))
            first_target = start_point if stroke_idx == start_stroke else 1
            anchor_index = first_target - 1
            contact_depth = float(stroke["recommended_contact_depth_mm"]) + args.depth_offset_mm
            contact_depth = min(1.4, max(0.4, contact_depth))
            hover = pose(points[anchor_index], HOVER_MM)
            contact = pose(points[anchor_index], -contact_depth)

            def pause_at(next_point, pen_down):
                if not stop_requested(control, run_id):
                    return False
                if pen_down:
                    lift_here = pose(points[next_point - 1], HOVER_MM)
                    checkpoint("running", "command_pending", stroke_idx, next_point,
                               active_stroke=index, active_stroke_id=stroke["id"],
                               active_command="stop_lift", target_tcp=lift_here[:3])
                    move_verified(robot, lift_here, f"stroke {index} stop lift")
                if next_point >= len(points):
                    finished = stroke_idx + 1 == len(plan["strokes"])
                    checkpoint("complete" if finished else "paused",
                               "done" if finished else "stopped_by_user", stroke_idx + 1, 1,
                               last_stroke=stroke["id"])
                else:
                    checkpoint("paused", "stopped_by_user", stroke_idx, next_point,
                               active_stroke=index, active_stroke_id=stroke["id"])
                return True

            if pause_at(first_target, False):
                return
            checkpoint("running", "command_pending", stroke_idx, first_target,
                       active_stroke=index, active_stroke_id=stroke["id"], active_command="hover",
                       target_tcp=hover[:3])
            move_verified(robot, hover, f"stroke {index} hover")
            if pause_at(first_target, False):
                return
            checkpoint("running", "command_pending", stroke_idx, first_target,
                       active_stroke=index, active_stroke_id=stroke["id"], active_command="contact",
                       target_tcp=contact[:3])
            move_verified(robot, contact, f"stroke {index} contact")
            if pause_at(first_target, True):
                return
            for point_index in range(first_target, len(points)):
                point = points[point_index]
                target = pose(point, -contact_depth)
                checkpoint("running", "command_pending", stroke_idx, point_index,
                           active_stroke=index, active_stroke_id=stroke["id"],
                           active_command=f"line point {point_index}", target_tcp=target[:3])
                move_verified(robot, target, f"stroke {index} point {point_index}", linear=True)
                if pause_at(point_index + 1, True):
                    return
            lift = pose(points[-1], HOVER_MM)
            checkpoint("running", "command_pending", stroke_idx, len(points),
                       active_stroke=index, active_stroke_id=stroke["id"], active_command="lift",
                       target_tcp=lift[:3])
            move_verified(robot, lift, f"stroke {index} lift")
            if stop_requested(control, run_id) and index < len(plan["strokes"]):
                checkpoint("paused", "stopped_by_user", index, 1, last_stroke=stroke["id"])
                return
            checkpoint("running", "drawing", index, 1, last_stroke=stroke["id"])
            print(f"stroke {index}/{summary['strokes']} verified: {stroke['id']}", flush=True)
        checkpoint("complete", "done", summary["strokes"], 1)
    except Exception as error:
        if started:
            checkpoint("stopped", "error", stroke_idx if "stroke_idx" in locals() else start_stroke,
                       first_target if "first_target" in locals() else start_point, detail=str(error))
        raise
    finally:
        robot.disconnect()


if __name__ == "__main__":
    main()
