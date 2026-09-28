#!/usr/bin/env python3
"""Record one of four manually positioned pen-tip references; never moves Piper."""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from pyAgxArm import AgxArmFactory, ArmModel, PiperFW, create_agx_arm_config

ROOT = Path("/home/chenrui/playground")
DEFAULT_FILE = ROOT / "paper_calibration_current_tool.json"
REQUIRED = ("origin", "x", "y", "lift")


def sub(a, b): return [a[index] - b[index] for index in range(3)]
def dot(a, b): return sum(a[index] * b[index] for index in range(3))
def norm(a): return math.sqrt(dot(a, a))
def cross(a, b): return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]


def validate(points):
    missing = [name for name in REQUIRED if name not in points]
    if missing:
        return "still missing: " + ", ".join(missing)
    origin = points["origin"]["tcp_pose"][:3]
    x_point = points["x"]["tcp_pose"][:3]
    y_point = points["y"]["tcp_pose"][:3]
    lift = points["lift"]["tcp_pose"][:3]
    ex, ey, up = sub(x_point, origin), sub(y_point, origin), sub(lift, origin)
    lx, ly, lh = norm(ex), norm(ey), norm(up)
    normal_length = norm(cross(ex, ey))
    if lx < 0.05 or ly < 0.05:
        raise ValueError("X and Y points must each be at least 50 mm from origin")
    if lh < 0.01:
        raise ValueError("lift point must be at least 10 mm above origin")
    if normal_length < 1e-6:
        raise ValueError("X/Y points are nearly collinear")
    if abs(dot(cross(ex, ey), up) / (normal_length * lh)) < 0.90:
        raise ValueError("lift must be directly above origin, not elsewhere on the paper")
    return f"valid four-point frame: X={lx*1000:.1f} mm, Y={ly*1000:.1f} mm, lift={lh*1000:.1f} mm"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", choices=REQUIRED, help="reference to record from current pen-tip pose")
    parser.add_argument("--file", type=Path, default=DEFAULT_FILE)
    parser.add_argument("--overwrite", action="store_true", help="required when replacing a stored point")
    parser.add_argument("--wait", type=float, default=1.0)
    args = parser.parse_args()
    path = args.file.expanduser().resolve()
    data = {"schema_version": 1, "tcp_offset": [0.0] * 6, "points": {}}
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or not isinstance(data.get("points"), dict):
        raise SystemExit("unsupported calibration file")
    if not args.record:
        print(path)
        print(validate(data["points"]))
        return 0
    if args.record in data["points"] and not args.overwrite:
        raise SystemExit(f"{args.record} exists; use --overwrite only after deliberate repositioning")

    robot = AgxArmFactory.create_arm(create_agx_arm_config(robot=ArmModel.PIPER, firmeware_version=PiperFW.V189, interface="socketcan", channel="can0"))
    try:
        robot.connect()
        robot.set_tcp_offset([0.0] * 6)
        time.sleep(args.wait)
        if robot.has_comm_error() or robot.get_arm_status() is None or robot.get_joint_angles() is None:
            raise RuntimeError("no usable arm/joint feedback; calibration was not recorded")
        tcp = robot.get_tcp_pose()
        if tcp is None or len(tcp.msg) != 6:
            raise RuntimeError("no usable TCP feedback; calibration was not recorded")
        pose = [float(value) for value in tcp.msg]
    finally:
        robot.disconnect()

    data["tcp_offset"] = [0.0] * 6
    data["points"][args.record] = {"tcp_pose": pose, "recorded_at_utc": datetime.now(timezone.utc).isoformat()}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    print(f"recorded {args.record}: {[round(value*1000, 1) for value in pose[:3]]} mm")
    print(validate(data["points"]))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"Paper calibration failed: {error}", file=sys.stderr)
        raise SystemExit(1)
