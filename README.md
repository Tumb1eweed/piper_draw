# Piper 绘画：Windows 原生工作流

项目位于 `D:\Projects\piper`。Windows 直接使用 candleLight USB-CAN，不再需要日常运行 `mount_piper_can.cmd` 或 `sync_to_wsl.ps1`。这两个脚本只保留给旧 WSL 工作流。

## 一次性安装

- Windows 10/11、Miniconda（本机为 `D:\Miniconda3`）、Git。Node.js 24 由同一个 `piper` Conda 环境安装（本机已用 24.21.0 验证）。
- candleLight `1d50:606f`、1 Mbps CAN；本机适配器序列号 `002A00475547571120343930`。Windows 必须能直接识别它，不能处于 `usbipd` 的 `Attached` 状态。
- 在项目目录运行 `powershell -ExecutionPolicy Bypass -File .\setup_windows.ps1`。脚本使用 conda-forge 建立 Windows `piper`（Python 3.12）环境，安装锁定的 SDK、`python-can`、`python-can-candle`、Pillow，并在 `vendor\trazor` 安装固定提交的 npm 依赖。它不打开 CAN，也不更改标定。

SDK 版本为 1.0.0，固定官方提交 `841a625f5f4920e776f20b934eb13048b747e6d0`；Trazor 固定提交 `d5dd561830defbff379a5fba18990cf7efc0267d`。依赖清单见 `requirements-sdk.txt`、`environment.yml` 和 Trazor 仓库自身的 `package-lock.json`。

固定版 Trazor 的 `npm ci` 会提示 3 条开发依赖告警（1 high、2 critical）；`npm audit --omit=dev` 结果为 0。当前仅用于本地离线预览，不运行它的开发服务器；不要为了消除提示而未经复测执行 `npm audit fix`。

## 每次使用

1. 关闭松灵 Windows 上位机，确认机械臂上电、急停释放、工作区清空、纸张固定、笔夹紧。不要同时运行旧 WSL UI 或作画进程。
2. `usbipd list` 应显示 candleLight 为 `Shared`（不是 `Attached`）。如果被旧 WSL 自动挂载进程占用，先停止那个进程，并用实际 BUSID 执行 `usbipd detach --busid <BUSID>`；不要运行 `mount_piper_can.cmd`。正常重插后 Windows 会直接重新识别，无需挂载。
3. 运行 `& 'D:\Miniconda3\envs\piper\python.exe' .\read_piper_status.py --wait 3`。只有 `connected: True`、`comm_error: False`、非空 `arm_status` 和关节状态、反馈至少 100 Hz 时才继续。本机迁移验证曾读到约 220–230 Hz。
4. 双击 `start_piper_draw_ui.cmd`，打开 `http://127.0.0.1:8765/`，检查连接并选择经审核的画。网页仅在本机开放，不能代替物理急停。

## 四点纸面标定

当前 Windows 标定文件是项目根目录下的 `paper_calibration_current_tool.json`，由原 WSL 文件原样复制，未重新标定；文件被 Git 忽略。现有笔、纸张、装夹和零 TCP 偏移不变时可以沿用。若这些条件变了，用实际笔尖手动定位并依次录入 `origin`、`x`、`y`、`lift`，其中 `lift` 须位于原点正上方。脚本只采集反馈，不移动机械臂：

```powershell
$python = 'D:\Miniconda3\envs\piper\python.exe'
& $python .\calibrate_paper.py --record origin --overwrite
& $python .\calibrate_paper.py --record x --overwrite
& $python .\calibrate_paper.py --record y --overwrite
& $python .\calibrate_paper.py --record lift --overwrite
& $python .\calibrate_paper.py
```

只在对应点手动放好后执行那一行。最后一行必须报告 `valid four-point frame`。不要让准备图片的步骤隐式覆盖标定。

## 新图片到预览计划

用清晰的线稿 PNG。Trazor 只生成中心线 SVG 和元数据，Python 只生成供人审核的预览与 JSON；它们不连接机械臂：

```powershell
$env:TRAZOR_MAX_DIMENSION = '768'
$env:TRAZOR_PRUNE_LENGTH = '12'
$env:TRAZOR_SMOOTHING = '0.78'
$env:TRAZOR_FIT_TOLERANCE = '2.1'
$env:TRAZOR_SIMPLIFY_TOLERANCE = '1.0'
Copy-Item .\trazor_centerline_runner.ts .\vendor\trazor\piper_centerline_runner.ts -Force
& 'D:\Miniconda3\envs\piper\node.exe' .\vendor\trazor\node_modules\tsx\dist\cli.mjs .\vendor\trazor\piper_centerline_runner.ts .\references\my_art.png .\generated\my_art\my_art.svg
& 'D:\Miniconda3\envs\piper\python.exe' .\prepare_centerline_plan.py --source .\generated\my_art\my_art.svg.document.json --out .\generated\my_art\review --name my_art --x-min 15 --x-max 165 --y-min 15 --y-max 150
```

检查预览 PNG 的尺寸、轮廓、断线与越界后才允许执行。`generated/`、个人参考图和标定数据均不入 Git；审核通过的精选图、预览和计划才可作为 `assets/` 提交。

## 命令行作画

先运行不连接 CAN 的 dry-run。真人复核预览与现场，再带齐三个授权参数；执行器会重新检查实时反馈并逐点验证 `hover → contact → line → lift`。

```powershell
$python = 'D:\Miniconda3\envs\piper\python.exe'
& $python .\execute_plan.py --plan .\assets\plans\tiger_large_detail_plan.json
& $python .\execute_plan.py --plan .\assets\plans\tiger_large_detail_plan.json --execute --confirmed --approved-plan --speed 8
```

允许速度 4–12%。执行进度写在计划旁的 `draw_progress.json`。通信或反馈失效时不得继续发轨迹；真实机械臂运动需人工现场监护。Windows 迁移已验证环境、CAN 帧接收、SDK 关节反馈、预览生成和执行器预检；迁移过程中**未做任何运动测试**。
