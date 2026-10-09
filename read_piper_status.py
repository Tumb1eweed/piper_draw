#!/usr/bin/env python3
"""Read Piper feedback through the platform CAN adapter without motion."""
from __future__ import annotations

import argparse
import math
import sys
import time
from pyAgxArm import AgxArmFactory
from piper_runtime import arm_config, arm_fault_reason, can_connection


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wait", type=float, default=1.0)
    args = parser.parse_args()
    interface, channel = can_connection()
    print(f"can_adapter: {interface}:{channel}")
    robot = AgxArmFactory.create_arm(arm_config())
    try:
        robot.connect()
        effector = robot.init_effector(robot.OPTIONS.EFFECTOR.AGX_GRIPPER)
        time.sleep(args.wait)
        print(f"connected:  {robot.is_connected()}")
        print(f"comm_error: {robot.has_comm_error()}")
        arm_status = robot.get_arm_status()
        print(f"arm_status: {arm_status}")
        fault = arm_fault_reason(arm_status)
        print(f"arm_fault: {fault or 'none'}")
        motion_status = None if arm_status is None else getattr(arm_status.msg, "motion_status", None)
        if motion_status == 0:
            print("motion_target: reached")
        elif motion_status == 1:
            print("motion_target: moving / not yet reached")
        else:
            print(f"motion_target: unknown ({motion_status})")
        joints = robot.get_joint_angles()
        if joints is None:
            print("joint_angles: no feedback received")
        else:
            print(f"joint_feedback_hz: {joints.hz}")
            for index, radians in enumerate(joints.msg, 1):
                print(f"  joint_{index}: {math.degrees(radians):.2f} deg")
        gripper = effector.get_gripper_status()
        print("gripper: no feedback received" if gripper is None else f"gripper_hz: {gripper.hz}")
        if (not robot.is_connected() or robot.has_comm_error() or arm_status is None or
                arm_status.hz < 100 or joints is None or joints.hz < 100 or fault is not None):
            return 2
        return 0
    except Exception as error:
        print(f"Unable to read Piper status: {error}", file=sys.stderr)
        return 1
    finally:
        robot.disconnect()


if __name__ == "__main__":
    raise SystemExit(main())
