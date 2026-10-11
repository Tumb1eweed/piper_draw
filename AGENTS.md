# Piper drawing repository rules

This repository controls a physical AgileX Piper arm through a candleLight USB-CAN adapter. Every motion command has real-world consequences.

## Canonical workflow

Only this workflow is maintained:

1. Windows `piper` conda environment directly opens the candleLight adapter through `python-can-candle` at 1 Mbps. Only native Windows operation is maintained.
2. `calibrate_paper.py` records four pen-tip TCP references: `origin`, `x`, `y`, and `lift`. The active, Git-ignored file is `D:\Projects\piper\paper_calibration_current_tool.json`.
3. Trazor converts clean line art into a centreline SVG document. `prepare_centerline_plan.py` filters, orders, maps and renders a **preview-only** JSON plan.
4. A human reviews the preview. `execute_plan.py` performs a fresh live feedback gate, then draws only with `--execute`, `--confirmed`, and `--approved-plan`.
5. `piper_draw_ui.py` is an optional **local-only** curated-plan picker. It must remain bound to `127.0.0.1`, use a fixed plan allowlist, require browser-side physical-workspace confirmation, and delegate motion to the same executor.

Do not reintroduce legacy raster fills, hand-authored animal trajectories, `move_c` approximations for arbitrary curves, or old bamboo/calligraphy plans into production.

## Required live connection state

Do not consider a previous successful check valid for a later motion.

1. Windows owns the candleLight USB device and `python-can-candle` discovers the expected serial/channel `002A00475547571120343930:0`.
2. `read_piper_status.py --wait 3` shows `connected: True`, `comm_error: False`, non-empty `arm_status`, non-empty joint feedback, and a real feedback rate of at least 100 Hz (normally ~200 Hz).

USB discovery alone is insufficient. If CAN RX is zero, feedback is absent, or any SDK communication error appears, do not issue drawing, teaching, gripper, reset, or joint-motion commands. Never run the Windows upper-controller and SDK concurrently.

## Safety and ownership

- Confirm arm power, released emergency stop, clear workspace, clamped paper, and secure pen before live execution.
- `calibrate_paper.py` records feedback only; it must not move the arm. Four points must use the actual pen/tool and the same zero SDK TCP offset as the executor.
- Never alter `paper_calibration_current_tool.json` implicitly while preparing an image or changing a drawing. Revalidate if the physical setup changes.
- Every pen-down path is `hover -> verified contact -> verified line targets -> verified lift`. On feedback failure, stop sending future targets.
- Piper's SDK labels `motion_status == 1` as `REACH_TARGET_POS_FAILED`, but protocol meaning is **not yet reached**. It is progress, not terminal trajectory error. Require three consecutive `motion_status == 0` samples within Cartesian tolerance; only executor timeout (`status: stopped`), lost SDK feedback, or joint/arm fault is failure. Do not kill live execution based solely on one `motion_status == 1` snapshot.
- Each curated plan has isolated, ignored `generated/run_state/<plan>-<hash>/draw_progress.json`, `draw_control.json`, and `draw_launch.json`. Inspect progress for active stroke and target; it updates before every hover/contact/line/lift command. A UI stop request is cooperative: wait for the current verified target, then verify lift before writing `status: paused`. Only this state can resume; never treat `status: stopped` (feedback loss/timeout), orphaned `status: running`, or an unconfirmed launch as resumable. Resume requires unchanged plan/calibration hashes and motion settings plus a fresh preflight. Restart begins at stroke one and may overdraw existing ink.
- UI stop is not an emergency stop. In a dangerous situation use the arm's physical emergency stop. Do not kill the executor or disconnect CAN while waiting for a cooperative stop.
- After replug, Windows should rediscover the adapter directly. Check the USB driver and adapter ownership if discovery fails.

## Dependencies

- Windows: Miniconda `piper` Python 3.12, candleLight gs_usb adapter with a Windows USB driver accessible to `python-can-candle`; this machine's adapter is discovered directly by the plugin.
- Python: official pyAgxArm 1.0.0 at commit `841a625f5f4920e776f20b934eb13048b747e6d0`, `python-can==4.6.1`, `python-can-candle==1.2.4`, `candle-api==0.0.12`, `Pillow==12.3.0`. See `requirements-sdk.txt` and `setup_windows.ps1`.
- Centreline conversion: Node.js 24.x in the same conda environment (24.21.0 tested) and Trazor commit `d5dd561830defbff379a5fba18990cf7efc0267d` in ignored `vendor/trazor`.
- Do not reintroduce alternate OS launchers or USB attachment/synchronization scripts into the Windows workflow.

## Repository hygiene

- Source and runtime live in the same local Windows checkout (this machine: `D:\Projects\piper`).
- Do not commit personal paper calibration files, generated plans/previews, copied reference images, Node modules, USB logs, or old experiments.
- Commit code and documentation changes that affect the canonical workflow.
