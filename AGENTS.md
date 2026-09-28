# Piper drawing repository rules

This repository controls a physical AgileX Piper arm through a candleLight USB-CAN adapter. Every motion command has real-world consequences.

## Canonical workflow

Only this workflow is maintained:

1. Windows `mount_piper_can.cmd` attaches candleLight to Ubuntu WSL and brings `can0` up at 1 Mbps.
2. `calibrate_paper.py` records four pen-tip TCP references: `origin`, `x`, `y`, and `lift`. The active file is `/home/chenrui/playground/paper_calibration_current_tool.json`.
3. Trazor converts a clean line-art reference into a centreline SVG document. `prepare_centerline_plan.py` filters, orders, maps and renders a **preview-only** JSON plan.
4. A human reviews the preview. `execute_plan.py` performs a live feedback gate, then draws only with `--execute`, `--confirmed`, and `--approved-plan`.

Do not reintroduce legacy raster fills, hand-authored animal trajectories, `move_c` approximations for arbitrary curves, or old bamboo/calligraphy plans into the production workflow.

## Required live connection state

Do not consider a previous successful check valid for a later motion.

1. `usbipd` shows candleLight as Attached (or auto-attached) to Ubuntu WSL.
2. `wsl -d Ubuntu -- ip -brief link show can0` reports `UP`.
3. `read_piper_status.py --wait 3` shows `connected: True`, `comm_error: False`, non-empty `arm_status`, non-empty joint feedback, and a real feedback rate (normally about 200 Hz; production gate requires at least 100 Hz).

`can0 UP` alone is insufficient. If CAN RX is zero, feedback is absent, or any SDK communication error appears, do not issue drawing, teaching, gripper, reset, or joint-motion commands.

## Safety and ownership

- Keep the Windows upper-controller application closed while the SDK owns CAN.
- Confirm arm power, released emergency stop, clear workspace, clamped paper, and secure pen before live execution.
- `calibrate_paper.py` records feedback only; it must not move the arm. The four points must use the actual pen/tool and the same zero SDK TCP offset as the executor.
- Never alter `paper_calibration_current_tool.json` implicitly while preparing an image or changing a drawing.
- Every pen-down path is `hover -> verified contact -> verified line targets -> verified lift`. On a feedback failure, stop sending future targets.
- Piper's SDK labels `motion_status == 1` as `REACH_TARGET_POS_FAILED`, but its protocol meaning is simply **not yet reached**. It is a progress state, not a terminal trajectory error. The executor requires three consecutive `motion_status == 0` samples within its Cartesian tolerance; only an executor timeout (recorded as `status: stopped`), lost SDK feedback, or a joint/arm fault is a trajectory failure. Do not kill a live executor based solely on a `motion_status == 1` reader snapshot.
- During a draw, inspect `draw_progress.json` for the active stroke and target. It is updated before every hover, contact, line, and lift command, so a real timeout can be reproduced without guessing which coordinate failed.
- After a replug, rerun `mount_piper_can.cmd`; do not merely run `ip link set can0 up`.

## Dependencies

- Windows: WSL2 Ubuntu, `usbipd-win`, PowerShell, candleLight gs_usb adapter.
- WSL: Miniconda Python 3.12 environment named `piper` from `environment.yml`.
- Python: `pyAgxArm==1.0.0`, `python-can==4.6.1`, `Pillow==12.3.0`.
- Centreline conversion: Node.js 22 and Trazor commit `d5dd561830defbff379a5fba18990cf7efc0267d`.

## Repository hygiene

- Source lives in `D:\Projects\piper`; deploy to `/home/chenrui/playground` with `sync_to_wsl.ps1`.
- Do not commit personal paper calibration files, generated plans/previews, copied reference images, Node modules, USB logs, or old experiments.
- Commit code and documentation changes that affect the canonical workflow.
