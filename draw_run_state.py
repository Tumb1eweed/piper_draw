"""Per-plan run checkpoints and cooperative stop requests (no robot I/O)."""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def paths_for_plan(plan: Path) -> tuple[Path, Path]:
    # Distinct plans must never share a checkpoint, even with the same stem.
    key = hashlib.sha256(str(plan.resolve()).encode("utf-8")).hexdigest()[:12]
    folder = ROOT / "generated" / "run_state" / f"{plan.stem}-{key}"
    return folder / "draw_progress.json", folder / "draw_control.json"


def launch_path_for_plan(plan: Path) -> Path:
    progress, _control = paths_for_plan(plan)
    return progress.with_name("draw_launch.json")


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"invalid JSON object: {path}")
    return data


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def stop_requested(control: Path, run_id: str) -> bool:
    try:
        command = read_json(control)
    except (OSError, ValueError, json.JSONDecodeError):
        # Prefer a verified lift over sending another line target when the
        # control channel is unreadable.
        return True
    return command is None or command.get("run_id") != run_id or command.get("stop_requested") is True


def set_stop(control: Path, run_id: str, requested: bool) -> None:
    write_json(control, {"run_id": run_id, "stop_requested": requested, "timestamp": time.time()})
