# Piper line-art drawing workflow

This is the maintained, feedback-gated workflow used for the tiger, crane, deer, and double-fish drawings. It does **not** include older hand-authored, fill, bamboo, or calligraphy experiments.

## Curated examples

`assets/references/` contains the clean source line art used by the maintained
animal/dragon examples. `assets/trajectory-previews/` contains the reviewed
centreline previews, and `assets/plans/` contains the matching preview-only
JSON plans. They are reproducibility artefacts only: the plans do **not** embed
the local paper calibration and remain inert unless explicitly passed to the
three-flag live executor command below.

## Dependencies

- Windows 11 with WSL2 Ubuntu and `usbipd-win`.
- candleLight USB-CAN adapter and Piper at 1 Mbps CAN.
- Miniconda under `/home/chenrui/miniconda3` and Node.js 22.

Create or update the WSL environment:

```bash
source /home/chenrui/miniconda3/etc/profile.d/conda.sh
conda env update --prefix /home/chenrui/miniconda3/envs/piper --file /mnt/d/Projects/piper/environment.yml --prune
conda activate piper
```

Install Trazor once:

```bash
mkdir -p /home/chenrui/playground/vendor
git clone https://github.com/PhenX/Trazor.git /home/chenrui/playground/vendor/trazor
cd /home/chenrui/playground/vendor/trazor
git checkout d5dd561830defbff379a5fba18990cf7efc0267d
npm ci
```

## 1. Deploy source and attach CAN

In Windows PowerShell:

```powershell
.\sync_to_wsl.ps1
.\mount_piper_can.cmd
wsl -d Ubuntu -- ip -brief link show can0
wsl -d Ubuntu -- bash -lc "source /home/chenrui/miniconda3/etc/profile.d/conda.sh && conda activate piper && python /home/chenrui/playground/read_piper_status.py --wait 3"
```

The Windows upper-controller must be closed. Continue only when `can0` is UP and live feedback is normal.

## 2. Four-point paper calibration

With the actual pen installed, manually position the pen tip at: `origin` (chosen paper origin), `x` (positive paper-X), `y` (positive paper-Y), and `lift` (directly above origin). After each manual placement and feedback check, run:

```bash
source /home/chenrui/miniconda3/etc/profile.d/conda.sh
conda activate piper
python /home/chenrui/playground/calibrate_paper.py --record origin --overwrite
python /home/chenrui/playground/calibrate_paper.py --record x --overwrite
python /home/chenrui/playground/calibrate_paper.py --record y --overwrite
python /home/chenrui/playground/calibrate_paper.py --record lift --overwrite
python /home/chenrui/playground/calibrate_paper.py
```

The final command must say the frame is valid. This script only reads TCP feedback; it never commands motion.

## 3. Image to preview-only plan

Put a high-contrast line-art PNG at `/home/chenrui/playground/references/<name>.png`, then:

```bash
cd /home/chenrui/playground/vendor/trazor
env PATH=/home/chenrui/playground/tools/node-v22.16.0-linux-x64/bin:/usr/local/bin:/usr/bin:/bin \
  TRAZOR_MAX_DIMENSION=768 TRAZOR_PRUNE_LENGTH=12 TRAZOR_SMOOTHING=0.78 \
  TRAZOR_FIT_TOLERANCE=2.1 TRAZOR_SIMPLIFY_TOLERANCE=1.0 \
  /bin/sh node_modules/.bin/tsx piper_centerline_runner.ts \
  /home/chenrui/playground/references/<name>.png /home/chenrui/playground/generated/<name>/<name>.svg

python /home/chenrui/playground/prepare_centerline_plan.py \
  --source /home/chenrui/playground/generated/<name>/<name>.svg.document.json \
  --out /home/chenrui/playground/generated/<name>/review \
  --name <name> --x-min 15 --x-max 165 --y-min 15 --y-max 150
```

Inspect `<name>_preview.png`. Do not execute if it has crop-boundary spikes, missing components, or an incorrect footprint.

## 4. Live drawing

After preview approval and a fresh connection check:

```bash
python /home/chenrui/playground/execute_plan.py \
  --plan /home/chenrui/playground/generated/<name>/review/<name>_plan.json \
  --execute --confirmed --approved-plan --speed 8
```

The executor validates feedback before movement, verifies every hover/contact/line/lift target, writes `draw_progress.json`, and stops issuing trajectory commands on communication loss. Accepted speed is 4–12%; the default is 8%.

## Local artwork picker

After running `sync_to_wsl.ps1`, double-click `start_piper_draw_ui.cmd` and
open `http://127.0.0.1:8765` if the browser does not open automatically. The
page lists only the curated, reviewed plans in `assets/plans/`; it does not
accept arbitrary paths or shell commands from the browser. "检查连接" is
read-only and the **开始作画** button remains disabled until it receives live
CAN/joint feedback and the operator has checked the physical-workspace
confirmation box. The executor repeats the live gate immediately before any
movement.

The local page is a convenience controller, not an emergency-stop device. In
an emergency, use Piper's physical emergency stop.
