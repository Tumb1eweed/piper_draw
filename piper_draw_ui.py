#!/usr/bin/env python3
"""Local-only artwork picker and safety-gated Piper drawing launcher.

This server deliberately binds to 127.0.0.1.  It never accepts a user-supplied
shell command or path: browser requests select only from the reviewed plan
registry below, and the existing execute_plan.py process performs the final
live feedback gate before any physical motion.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from draw_run_state import launch_path_for_plan, paths_for_plan, read_json, set_stop, write_json
from piper_runtime import can_connection


ROOT = Path(__file__).resolve().parent

# These are the only plans the UI can ever start.  Add an item only after the
# preview has been reviewed; client-provided names and paths are never trusted.
DRAWINGS: dict[str, dict[str, str]] = {
    "tiger": {
        "title": "行虎",
        "subtitle": "大尺寸细节线稿",
        "reference": "assets/references/tiger_walking_line_art_reference_v1.png",
        "preview": "assets/trajectory-previews/tiger_large_detail_preview.png",
        "plan": "assets/plans/tiger_large_detail_plan.json",
    },
    "crane": {
        "title": "丹顶鹤",
        "subtitle": "简洁轮廓与水波",
        "reference": "assets/references/crane_line_art_reference_v1.png",
        "preview": "assets/trajectory-previews/crane_detailed_trajectory_preview.png",
        "plan": "assets/plans/crane_detailed_paths_preview.json",
    },
    "deer": {
        "title": "鹿",
        "subtitle": "角、蹄与斑点细节",
        "reference": "assets/references/deer_line_art_reference_v1.png",
        "preview": "assets/trajectory-previews/deer_detailed_trajectory_preview.png",
        "plan": "assets/plans/deer_detailed_paths_preview.json",
    },
    "fish": {
        "title": "双鱼",
        "subtitle": "双鱼环游线稿",
        "reference": "assets/references/double_fish_line_art_reference_v1.png",
        "preview": "assets/trajectory-previews/fish_detailed_trajectory_preview.png",
        "plan": "assets/plans/fish_detailed_paths_preview.json",
    },
    "dragon": {
        "title": "龙",
        "subtitle": "纵向展开版",
        "reference": "assets/references/dragon_simple_lineart_reference_v2.png",
        "preview": "assets/trajectory-previews/dragon_simple_wide_preview.png",
        "plan": "assets/plans/dragon_simple_wide_plan.json",
    },
}


class DrawManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._probe_lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None
        self._drawing_id: str | None = None
        self._started_at: float | None = None
        self._returncode: int | None = None
        self._run_id: str | None = None
        self._stop_pending = False
        self._lines: deque[str] = deque(maxlen=24)

    @staticmethod
    def _checkpoint(drawing_id: str, active: bool = False) -> dict[str, Any] | None:
        plan = ROOT / DRAWINGS[drawing_id]["plan"]
        progress, _control = paths_for_plan(plan)
        try:
            state = read_json(progress)
            launch = read_json(launch_path_for_plan(plan))
            if launch and launch.get("status") == "launching" and not active:
                return {"status": "interrupted", "detail": "上次启动尚未确认结束；请检查是否有残留执行器。"}
            return state
        except (OSError, ValueError, json.JSONDecodeError):
            return {"status": "invalid", "detail": "断点文件损坏，请人工检查；已禁止继续作画。"}

    def status(self) -> dict[str, Any]:
        with self._lock:
            active = self._process is not None and self._process.poll() is None
            states = {key: self._checkpoint(key, active and key == self._drawing_id) for key in DRAWINGS}
            return {
                "active": active,
                "stop_pending": active and self._stop_pending,
                "drawing_id": self._drawing_id,
                "started_at": self._started_at,
                "returncode": self._returncode,
                "log": list(self._lines),
                "states": states,
            }

    def start(self, drawing_id: str, mode: str = "start") -> tuple[bool, str]:
        if drawing_id not in DRAWINGS:
            return False, "未知画作。"
        if mode not in ("start", "resume", "restart"):
            return False, "未知操作。"
        with self._probe_lock:
            with self._lock:
                if self._process is not None and self._process.poll() is None:
                    return False, "已有作画任务正在运行；请先等待受控停止，紧急情况使用物理急停。"
                plan = ROOT / DRAWINGS[drawing_id]["plan"]
                state = self._checkpoint(drawing_id)
                prior_status = state.get("status") if state else None
                if prior_status in ("running", "invalid", "interrupted"):
                    return False, "上次执行状态未安全结束或断点损坏；请人工确认没有残留执行器，再处理断点。"
                if mode == "resume" and prior_status != "paused":
                    return False, "只有受控停止且抬笔成功的任务可以继续。"
                if prior_status == "stopped":
                    return False, "上次执行失败，笔尖位置可能不安全；请人工排查并处理断点，网页禁止直接重画。"
                if mode == "start" and prior_status in ("paused", "complete"):
                    return False, "已有历史任务；请选择“继续”或“从头开始”。"
                run_id = uuid.uuid4().hex
                _progress, control = paths_for_plan(plan)
                launch = launch_path_for_plan(plan)
                try:
                    set_stop(control, run_id, False)
                    write_json(launch, {"run_id": run_id, "status": "launching", "timestamp": time.time()})
                except OSError as error:
                    return False, f"无法建立停止控制文件：{error}"
                command = [sys.executable, str(ROOT / "execute_plan.py"), "--plan", str(plan),
                           "--execute", "--confirmed", "--approved-plan", "--speed", "8",
                           "--run-id", run_id]
                if mode == "resume":
                    command.append("--resume")
                elif mode == "restart":
                    command.append("--restart")
                try:
                    process = subprocess.Popen(
                        command, text=True, encoding="utf-8", errors="replace",
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=ROOT,
                    )
                except OSError as error:
                    write_json(launch, {"run_id": run_id, "status": "failed_to_start", "timestamp": time.time()})
                    return False, f"无法启动执行器：{error}"
                self._lines.clear()
                self._drawing_id = drawing_id
                self._started_at = time.time()
                self._returncode = None
                self._run_id = run_id
                self._stop_pending = False
                self._process = process
                threading.Thread(target=self._capture, args=(self._process, launch, run_id), daemon=True).start()
        return True, "已启动。执行器将重新检查 CAN 与关节反馈，再执行轨迹。"

    def stop(self) -> tuple[bool, str]:
        with self._lock:
            if self._process is None or self._process.poll() is not None or not self._run_id or not self._drawing_id:
                return False, "当前没有正在作画的任务。"
            if self._stop_pending:
                return True, "停止请求已发送，请等待当前目标确认到达并抬笔。"
            _progress, control = paths_for_plan(ROOT / DRAWINGS[self._drawing_id]["plan"])
            try:
                set_stop(control, self._run_id, True)
            except OSError as error:
                return False, f"停止请求未送达：{error}；紧急情况请按物理急停。"
            self._stop_pending = True
            return True, "已请求受控停止；当前目标确认到达后将抬笔。紧急情况请按物理急停。"

    def _capture(self, process: subprocess.Popen[str], launch: Path, run_id: str) -> None:
        assert process.stdout is not None
        for line in process.stdout:
            with self._lock:
                self._lines.append(line.rstrip())
        code = process.wait()
        with self._lock:
            self._returncode = code
            self._stop_pending = False
            write_json(launch, {"run_id": run_id, "status": "finished", "returncode": code, "timestamp": time.time()})

    def connection_status(self) -> dict[str, Any]:
        """Read-only idle check; never run alongside a live drawing."""
        with self._probe_lock:
            if self.status()["active"]:
                return {"available": False, "message": "作画进行中；请查看执行日志，不并发打开第二个 SDK 连接。"}
            try:
                interface, channel = can_connection()
                reader = subprocess.run(
                    [sys.executable, str(ROOT / "read_piper_status.py"), "--wait", "3"],
                    text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=15, cwd=ROOT,
                )
            except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
                return {"available": False, "message": f"无法读取连接状态：{error}"}
            report = ((reader.stdout or "") + "\n" + (reader.stderr or "")).strip()
            match = re.search(r"joint_feedback_hz:\s*([0-9.]+)", report)
            usable = (
                reader.returncode == 0 and "connected:  True" in report
                and "comm_error: False" in report and "arm_status: None" not in report
                and "arm_fault: none" in report
                and match is not None and float(match.group(1)) >= 100.0
            )
            return {"available": usable, "can": f"{interface}:{channel}", "report": report}


MANAGER = DrawManager()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def _json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:  # noqa: N802
        endpoint = urlparse(self.path).path
        if endpoint == "/api/gallery":
            self._json({"drawings": [{"id": key, **{k: v for k, v in value.items() if k != "plan"}} for key, value in DRAWINGS.items()]})
            return
        if endpoint == "/api/job":
            self._json(MANAGER.status())
            return
        if endpoint == "/api/status":
            self._json(MANAGER.connection_status())
            return
        if endpoint == "/":
            self.path = "/ui/index.html"
            endpoint = self.path
        static_paths = {"/ui/index.html", "/ui/app.js", "/ui/styles.css"}
        static_paths.update("/" + value[k] for value in DRAWINGS.values() for k in ("reference", "preview"))
        if endpoint not in static_paths:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        return super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        endpoint = urlparse(self.path).path
        if endpoint not in ("/api/draw", "/api/stop", "/api/resume", "/api/restart"):
            self._json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
            return
        try:
            host = urlparse("http://" + self.headers.get("Host", ""))
            origin_header = self.headers.get("Origin")
            origin = urlparse(origin_header) if origin_header else None
            local_request = (host.hostname in ("127.0.0.1", "localhost") and
                             host.port == self.server.server_port and
                             (origin is None or (origin.hostname in ("127.0.0.1", "localhost") and
                                                 origin.port == self.server.server_port)))
        except ValueError:
            local_request = False
        if not local_request:
            self._json({"error": "只接受本机页面的控制请求。"}, HTTPStatus.FORBIDDEN)
            return
        if endpoint == "/api/stop":
            ok, message = MANAGER.stop()
            self._json({"stopping": ok, "message": message}, HTTPStatus.ACCEPTED if ok else HTTPStatus.CONFLICT)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > 4096:
                raise ValueError("invalid body size")
            body = json.loads(self.rfile.read(length))
            drawing_id = body["drawing_id"]
            confirmed = body["confirmed"] is True
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            self._json({"error": "请求格式无效。"}, HTTPStatus.BAD_REQUEST)
            return
        if not isinstance(drawing_id, str):
            self._json({"error": "画作编号无效。"}, HTTPStatus.BAD_REQUEST)
            return
        if not confirmed:
            self._json({"error": "必须确认工作区已清空、纸张固定且毛笔夹紧。"}, HTTPStatus.BAD_REQUEST)
            return
        mode = {"/api/draw": "start", "/api/resume": "resume", "/api/restart": "restart"}[endpoint]
        ok, message = MANAGER.start(drawing_id, mode)
        self._json({"started": ok, "message": message}, HTTPStatus.ACCEPTED if ok else HTTPStatus.CONFLICT)

    def log_message(self, format: str, *args: Any) -> None:
        print("[ui] " + format % args)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Piper Draw UI: http://127.0.0.1:{args.port}")
    print("Local-only. Keep this terminal open while using the page.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
