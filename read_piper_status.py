#!/usr/bin/env python3
"""Read Piper feedback through SocketCAN without sending control commands."""
from __future__ import annotations

import argparse
import math
import sys
import time
from pyAgxArm import AgxArmFactory, ArmModel, PiperFW, create_agx_arm_config


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel", default="can0")
    parser.add_argument("--wait", type=float, default=1.0)
    args = parser.parse_args()
    robot = AgxArmFactory.create_arm(create_agx_arm_config(robot=ArmModel.PIPER, firmeware_version=PiperFW.V189, interface="socketcan", channel=args.channel))
    try:
        robot.connect()
        effector = robot.init_effector(robot.OPTIONS.EFFECTOR.AGX_GRIPPER)
        time.sleep(args.wait)
        print(f"connected:  {robot.is_connected()}")
        print(f"comm_error: {robot.has_comm_error()}")
        arm_status = robot.get_arm_status()
        print(f"arm_status: {arm_status}")
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
        return 0
    except Exception as error:
        print(f"Unable to read Piper status: {error}", file=sys.stderr)
        return 1
    finally:
        robot.disconnect()


if __name__ == "__main__":
    raise SystemExit(main())
