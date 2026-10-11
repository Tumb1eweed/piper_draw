# 新 Windows 机器安装与部署

## 安装基础软件与项目

安装 Windows 64 位 Miniconda 和 Git for Windows。记下 Miniconda 安装目录，可以不添加到全局 PATH；Git 安装时允许命令行使用 Git。下面以 Miniconda 安装到 `D:\Miniconda3`、项目位于 `D:\Projects\piper` 为例，没有 D 盘时换成 C 盘目录。

在 PowerShell 中运行（HTTPS 克隆不要求配置 SSH 密钥；私有仓库需登录有访问权限的 GitHub 账号）：

```powershell
New-Item -ItemType Directory -Path D:\Projects -Force
git clone https://github.com/Tumb1eweed/piper_draw.git D:\Projects\piper
Set-Location D:\Projects\piper
powershell -ExecutionPolicy Bypass -File .\setup_windows.ps1 -CondaRoot D:\Miniconda3
```

安装需要访问 conda-forge、PyPI、GitHub。脚本创建 `piper` Conda 环境，安装 Python 3.12、Node.js 24 和固定版 Python SDK 依赖，并克隆固定版 Trazor、执行 `npm ci`。版本清单见 `environment.yml`、`requirements-sdk.txt`；SDK 和 Trazor 固定提交见 README。脚本不连接 CAN、不移动机械臂、不修改标定。网络失败时可在恢复后重新执行；遇到已有 Trazor 提交不一致时脚本会报错而不重置文件。

不要复制旧电脑的 Conda 环境、`node_modules` 或 `vendor`，在新机器重新安装即可。

## 环境验证（无机械臂运动）

```powershell
$python = 'D:\Miniconda3\envs\piper\python.exe'
& $python -m pip check
& $python -c "import pyAgxArm, can, PIL; print('Python dependencies OK')"
& 'D:\Miniconda3\envs\piper\node.exe' --version
& $python -m unittest discover -s tests -v
& $python .\execute_plan.py --plan .\assets\plans\tiger_large_detail_plan.json
```

最后一行应显示 `mode: dry-run`，只检查计划。单元测试使用模拟机械臂，不打开 CAN。

## USB-CAN 与设备检查

使用 candleLight（VID/PID `1d50:606f`）和 1 Mbps CAN。Windows 必须安装可供 `candle-api` 访问的 USB 驱动；Python 安装脚本不会自动安装设备驱动。枚举失败或驱动报错时，检查设备管理器和适配器厂商驱动说明，不要给无关 USB 设备替换驱动。

关闭 Windows 上位机和其他 CAN 程序，机械臂上电并释放急停，再执行只读检查：

```powershell
& $python -c "import can; print(can.detect_available_configs('candle'))"
& $python .\read_piper_status.py --wait 3
```

同一适配器搬到新电脑，序列号不变，默认通道 `002A00475547571120343930:0` 可沿用。换适配器时，先核对枚举结果中的真实设备，再修改 `piper_runtime.py` 中的 `WINDOWS_CANDLE_CHANNEL`，不得自动选择未知设备。当前 `arm_config()` 使用 `PiperFW.V189`，不同机械臂/固件需先核对 SDK 协议版本。

只有 connected 为 True、comm_error 为 False、机械臂和关节反馈非空、无故障、反馈频率至少 100 Hz 时才允许作画。设备枚举成功不代表机械臂通信已就绪。

## 四点纸面标定

仓库保存了一份历史四点参考文件 `assets/calibration/paper_calibration_four_points_2026-09-27.json`，其中的四个 TCP 位姿、记录时间与原始文件一致；已去掉旧电脑的备份路径。实际执行器读取项目根目录的 `paper_calibration_current_tool.json`，克隆仓库不会自动启用参考文件。重新布置笔、纸、底座后，应使用实际笔尖重新录入四点。手动定位好对应点后，关闭上位机再执行对应一行；录点脚本只采集反馈：

```powershell
& $python .\calibrate_paper.py --record origin --overwrite
& $python .\calibrate_paper.py --record x --overwrite
& $python .\calibrate_paper.py --record y --overwrite
& $python .\calibrate_paper.py --record lift --overwrite
& $python .\calibrate_paper.py
```

origin 为落笔原点，x/y 为纸面两个方向，lift 是原点上方的抬笔参考。最后应报告 `valid four-point frame`。只有机械臂、工具、纸张、底座和零 TCP 偏移完全不变、仅更换电脑时，才可在检查现场后手动启用仓库中的参考文件：

```powershell
Copy-Item -LiteralPath .\assets\calibration\paper_calibration_four_points_2026-09-27.json -Destination .\paper_calibration_current_tool.json
& $python .\calibrate_paper.py
```

不要复制 `generated/run_state/` 的旧运行断点。只要物理装夹或纸面位置有变化，就重新录入四点，不要复用参考坐标。

## 启动前端与后端

前端在 `ui/`，后端为 `piper_draw_ui.py`，执行器为 `execute_plan.py`。Python 后端同时提供页面、画稿与 API，不需要 npm 构建前端或额外安装 Web 服务器。五幅画的参考图、轨迹预览和计划都在 `assets/`，克隆即可获得。

默认 Conda 路径可双击 `start_piper_draw_ui.cmd`。其他安装路径可以传入 Python 路径：

```powershell
.\start_piper_draw_ui.cmd 'C:\Users\你的用户名\miniconda3\envs\piper\python.exe'
```

或直接启动后端：

```powershell
& $python .\piper_draw_ui.py --port 8765
```

保持服务窗口打开，在同一电脑访问 `http://127.0.0.1:8765/`。电脑重启后重新运行启动脚本。后端仅监听本机，保持 `127.0.0.1`，不要开放到局域网。

网页中检查连接和轨迹预览、确认现场后开始作画。停止会等当前目标确认到达后抬笔；继续恢复安全断点；从头开始重画第一笔，先换纸或确认允许覆盖。危险时使用物理急停。运行规则见 AGENTS.md 和 README。

## 更新与排错

确认无作画任务后停止网页服务，运行 `git pull --ff-only`；依赖有变化时重新运行 `setup_windows.ps1`，然后启动页面。

- 页面打不开：启动后端并检查服务窗口报错；127.0.0.1 指向浏览器所在电脑，浏览器和后端应在同一机器。
- 缺少 Python/模块：确认使用 piper 环境的 Python，重新运行安装脚本及 pip check。
- 8765 端口被占用：确认是否已经启动服务，避免重复启动；也可用 `--port 8766` 并访问对应端口。
- 找不到 CAN：检查 USB 驱动、实际序列号、适配器占用、上位机是否关闭。
- 不能继续：计划/标定变化、故障停止、未确认结束的旧任务都会阻止恢复。先检查现场和残留执行器，不要强行把失败断点改成已暂停。
