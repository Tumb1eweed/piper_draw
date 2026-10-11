"""Select the verified Piper CAN adapter without sending motion commands."""
from __future__ import annotations

import platform
from pathlib import Path


ROOT = Path(__file__).resolve().parent
CALIBRATION = ROOT / "paper_calibration_current_tool.json"
WINDOWS_CANDLE_CHANNEL = "002A00475547571120343930:0"


def can_connection() -> tuple[str, str]:
    """Return python-can interface/channel, rejecting a missing or wrong adapter."""
    if platform.system() == "Windows":
        import can

        channels = can.detect_available_configs("candle")
        found = {str(item.get("channel")) for item in channels}
        if WINDOWS_CANDLE_CHANNEL not in found:
            raise RuntimeError(
                "Windows candleLight adapter not found. Expected "
                f"{WINDOWS_CANDLE_CHANNEL}; detected {sorted(found)}. "
                "Check the Windows USB driver and close the upper-controller app."
            )
        return "candle", WINDOWS_CANDLE_CHANNEL
    raise RuntimeError("This drawing workflow supports native Windows only.")


def arm_config():
    from pyAgxArm import ArmModel, PiperFW, create_agx_arm_config

    interface, channel = can_connection()
    return create_agx_arm_config(
        robot=ArmModel.PIPER,
        firmeware_version=PiperFW.V189,
        interface=interface,
        channel=channel,
        bitrate=1_000_000,
    )


def arm_fault_reason(status) -> str | None:
    """Describe a non-normal arm or joint fault reported by live SDK feedback."""
    if status is None:
        return "arm status missing"
    message = status.msg
    arm_state = getattr(message, "arm_status", None)
    if getattr(arm_state, "value", None) != 0:
        return f"arm status is not NORMAL: {arm_state}"
    faults = getattr(message, "err_status", None)
    if faults is None:
        return "joint fault status missing"
    active = [name for name, value in vars(faults).items() if value]
    return ", ".join(active) if active else None
