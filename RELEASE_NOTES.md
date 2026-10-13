## JunkCleaner 净扫 v1.0.4

Windows 垃圾 / 流氓软件识别、彻底卸载与**内核事件驱动实时拦截**工具，含 GPU 降压调优。

### 直接使用

下载 `JunkCleaner.exe`，双击运行即可（单文件，无需安装 Python）。
程序内置管理员权限清单，启动时会弹 UAC，**请点「是」**。

支持 Windows 10 / 11 x64。

### 主要功能

- **扫描与清理** —— 识别流氓软件与捆绑程序，逐条列出判定证据；所有清理动作先移入隔离区，可随时还原
- **拦截守护** —— WMI 内核事件 + 目录变更监听 + 兜底轮询三层防护，7 级判定链，父子进程联动拦截捆绑安装
- **开机自启** —— 登录启动项 + 静默驻留右下角托盘（不使用计划任务）
- **可信软件** —— 按路径 / SHA-256 指纹 / 发行商加白名单，支持从压缩包内选单个文件按内容指纹放行
- **内存优化** —— 三档力度释放，实测单次可回收 5.5 GB
- **Defender 优化** —— 降低扫描性能损耗，改动前自动备份策略
- **GPU 降压调优** —— 直接走 NVAPI 指定频率自动搜索最低稳定电压，应用并注册开机自动重应用，不再依赖 Afterburner
- **硬件检测** —— CPU / 内存信息、跑分、压力与图案测试（自研，不内嵌专有软件）

### 本次版本要点

- **修复软件运行卡顿**：电源方案、GPU 状态、实时读数、硬件检测、守护自检、Defender 策略等所有阻塞子进程/PowerShell 调用全部移出 UI 主线程。实测 20 秒事件循环中位 10.0ms、P99 10.6ms、超过 50ms 次数 0；切页耗时从约 900ms 降到 6-10ms
- **修复进程退出崩溃**：`PowerFetchWorker` 改为 Python 守护线程 + Qt 信号封装，避免阻塞于子进程时被 Qt 析构导致 `0xc0000409`
- **CPU 实时频率修正**：`% Processor Performance` 改用 PDH API 直读，首次 109ms 建立基线，之后约 0.1ms；实测睿频 5210/5263MHz，而基准 3401MHz
- **瞬态 GPU 负载修复**：`high_ms` 参数此前未真正生效，满载占空比仅约 8%，GPU 最高只到 42% 占用；现在满载窗口持续推进 kernel，真正压满后再制造电流突变
- **NVAPI 降压后端**：内嵌 MIT 许可的 `simple-nvidia-undervolt`，直接通过 NVAPI Pstates20 读写 V/F 曲线，读得到真实核心电压
- **阶梯搜索**：从已知稳定电压起每档 -25mV，每档做频率达标 + 无掉频 + 数值损坏三重校验；失败立即回退上一稳定档并停止
- 目标频率输入保持用户填写值，不再自动跳回 3150MHz；电压/频率实时状态改为从 NVAPI 直读
- 应用结果注册为登录重应用任务，驱动重置或重启后自动恢复；不需要 MSI Afterburner
- 隔离区目录可自定义，不再默认落在 C 盘；开机自启为静默托盘，不使用计划任务
- 界面排版优化，修复文字重叠与状态显示不同步

详细图文说明见仓库内 [docs/使用说明书.md](https://github.com/Zppppp124/JunkCleaner/blob/main/docs/%E4%BD%BF%E7%94%A8%E8%AF%B4%E6%98%8E%E4%B9%A6.md)。

### 关于第三方组件

GPU 调参使用 [simple-nvidia-undervolt](https://github.com/vuplea/simple-nvidia-undervolt)
官方发布二进制（MIT License，Release v1.0.9），未做修改；
许可证与 SHA-256 见 `junkcleaner/assets/LICENSE-simple-nvidia-undervolt.txt`。
显存测试使用 `memtest_vulkan`（zlib License）。两者均允许随程序分发。

### 实测数据（RTX 4070 Ti SUPER）

- 2850MHz 原厂需要 1100mV；逐步下探后最低稳定为 955mV，930/935mV 会导致 CUDA 负载启动失败
- 955mV 满载实测 960mV / 2850MHz / 45°C，功耗从 208W 降到 176W
- NVAPI 调参会在驱动重置后丢失，因此应用时同步注册登录重应用任务

### 校验

下载附件后可用 `Get-FileHash .\JunkCleaner.exe -Algorithm SHA256` 校验。
