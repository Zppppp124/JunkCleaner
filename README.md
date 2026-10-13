# JunkCleaner 净扫

Windows 垃圾 / 流氓软件识别、彻底卸载与**内核事件驱动实时拦截**工具。
原生 PySide6 图形界面，无需安装额外软件；**所有清理动作移入隔离区，可随时还原**。

![扫描与清理](docs/images/scan.png)

> **完整图文明册请见 [docs/使用说明书.md](docs/使用说明书.md)**
> —— 从安装启动到 9 个功能页的逐项说明，含 GPU 降压原理与实测数据。

## 快速开始

### 直接用打包好的 EXE

`dist\JunkCleaner.exe` —— 单文件、约 50 MB、内置管理员权限清单（启动即弹 UAC）。
拷到任意 Windows 10/11 x64 机器上即可运行，无需安装 Python。

### 从源码运行

双击 `launch.pyw`（会自动请求管理员权限），或：

```powershell
cd I:\CODEX\JunkCleaner
python junkcleaner_entry.py
```

命令行：

```powershell
python junkcleaner_entry.py scan                # 只读扫描
python junkcleaner_entry.py scan --json         # 输出 JSON
python junkcleaner_entry.py clean --risk bundle # 清理流氓+捆绑（需确认）
python junkcleaner_entry.py guard               # 后台拦截守护
python junkcleaner_entry.py status              # 查看状态
```

### 重新打包

```powershell
python build_exe.py              # 标准版（内嵌 NVAPI 调参组件与显存测试）
python build_exe.py --bundle-ab  # 旧版兼容参数；当前版本不需要 Afterburner
```

`build_exe.py` 会自动创建固定版本的构建环境 `.buildvenv`
（**PySide6 6.8.3 + PyInstaller 6.11.1**）。

> 为什么锁版本：实测 PySide6 **6.11.x 与 PyInstaller 6.x 组合会打包失败**，
> 运行时报 `ImportError: DLL load failed while importing QtCore: 找不到指定的程序`。
> 换成 6.8.3 后稳定。踩坑过程记在下面「打包踩坑记录」里。

## 五个页面

1. **扫描与清理**：识别系统中的垃圾/流氓软件，点击任意一行查看判定证据
   （卸载注册表项 / 进程 / 服务 / 计划任务 / 开机自启 / 安装目录），勾选后一键清理。
2. **拦截守护**：内核事件驱动的实时防护（见下）。
3. **可信软件**：把信任的软件加入白名单，可同时加入 Windows Defender 排除项。
4. **内存优化**：内存检测、一键释放、自动释放、进程占用排行。
5. **Defender 优化**：把 Defender「扫描」策略的性能损耗压到最低。
6. **电源 / GPU**：电源方案、GPU 锁频与功耗墙、CPU 调压能力检测。
7. **隔离与还原**：查看历次清理清单，一键把隔离文件还原回原位置。
8. **运行日志**：完整的操作与拦截日志。

界面为淡紫可爱风（`Microsoft YaHei UI` / 黑体），字号与对比度按可读性调过。

### 应用图标

图标来源为一张水晶盾牌图，处理流程见 `tools\make_icon.py`：

1. 裁掉四周白边，只保留深色方框；
2. 裁掉底部「豆包AI生成」水印（与方框底部重叠）；
3. 居中裁成正方形；
4. 生成多尺寸 `app.ico`（16 / 24 / 32 / 48 / 64 / 128 / 256）与 `app.png`。

图标用在三处：**EXE 文件图标**、**窗口标题栏 / 任务栏 / Alt-Tab**、**系统托盘**。
标题栏左上角的徽标额外做了圆角处理，和淡紫卡片更协调。

重新生成图标（需修改源图时）：

```powershell
python tools\make_icon.py [可选:新图片路径]
python tools\check_icon.py      # 检查白边/水印是否清除干净
```

## 内存检测与释放

「内存优化」页提供：

- **实时检测**：物理内存总量 / 已用 / 可用 / 系统缓存 / 已提交，环形占用图
- **一键释放**：三档力度
  - 温和：逐进程 `EmptyWorkingSet` 修剪工作集
  - 标准（推荐）：温和 + 刷新已修改页面 + **清空待机列表（缓存页）**
  - 深度：标准 + 合并内存列表 + 限制文件系统缓存
- **自动释放**：内存占用超过阈值（默认 85%）且间隔满足（默认 300 秒）时自动执行
- **进程排行**：占用内存最高的进程及其路径

释放逻辑参考 Mem Reduct、RAMMap、Wise Memory Optimizer、Process Lasso 的公开做法：
从「工作集修剪」到「`NtSetSystemInformation(SystemMemoryListInformation)` 清理
待机列表 / 已修改列表」逐层加强。`GlobalMemoryStatusEx` +
`GetPerformanceInfo` 读取状态，`SetPriorityClass` / `EmptyWorkingSet` 执行修剪。
待机列表清理需要管理员权限。

> 实测（31.8 GB 内存，占用 47.8%）：一次标准释放回收 **5.5 GB**，修剪 352 个进程工作集。

## 控制扫描开销

扫描页有「性能」档位，**默认「低占用」**（玩游戏/办公时无感）：

| 档位 | CPU 目标 | 实测整机 CPU（16 核） | 实测磁盘读 | 扫描耗时 |
|------|---------|----------------------|-----------|---------|
| 低占用（默认） | 0.125 核 | **平均 0.68% / P95 2.78%** | 0.02 MB/s | ~37s |
| 均衡 | 0.30 核 | 平均 1.86% / P95 5.4% | 0.05 MB/s | ~15s |
| 快速 | 不限 | 平均 4.86% | 0.12 MB/s | ~5.5s |

压低开销的手段：

1. **进程优先级**降到 `BELOW_NORMAL_PRIORITY_CLASS`，结束后恢复；
2. **CPU 令牌桶限速**（`core.Throttle`）：按累计 CPU 秒数控制，
   超出目标就按比例停顿，保证**全程平均**不超过目标，而不是事后统计；
3. **去子进程**：服务用 `EnumServicesStatusEx`、计划任务用 Task Scheduler COM、
   开机自启用注册表直读，原先三次 PowerShell 子进程全部取消（这是 CPU 大户）；
4. **进程枚举节流**：`psutil.process_iter` 访问每个进程路径，每个进程都过一遍限速；
5. **读盘限速**：体积估算按累计字节数让出（`Throttle.add_bytes`），
   低占用档每 1 MB 让出一次；单目录估算有超时上限；
6. **指纹按需计算**：只有真的配置了「指纹白名单」才为进程算 SHA-256，
   且按 mtime+大小缓存，避免每个新进程都读盘。

自测工具：`python tools\measure_scan.py --intensity low --whole`

## 检测机制：流氓软件与捆绑软件怎么认出来

### 一、静态识别（扫描时）

命中即上"证据"，每条判定都能在界面上核对：

1. **卸载注册表项名**：读 HKLM/HKCU 三处 `Uninstall` 键的 `DisplayName`，
   与签名库 `uninstall` 正则匹配（如 `QQPCMgr`、`360\s*安全卫士`）；
2. **安装目录**：枚举 `Program Files`、`Program Files (x86)`、`ProgramData`
   一至两层子目录，比对 `path` 特征（如 `\360safe`、`\2345Explorer`）；
3. **进程**：比对 `process` 特征（如 `360tray.exe`、`QQPCTray.exe`）；
4. **服务**：`EnumServicesStatusEx` 拿服务名与显示名；
5. **计划任务**：Task Scheduler COM 递归枚举；
6. **开机自启**：直读五个 `Run`/`RunOnce` 注册表键。

### 二、实时拦截（守护运行时）

新进程启动走 **7 级判定链**（`guard._handle_process`），顺序即优先级：

| 顺序 | 判定 | 说明 |
|------|------|------|
| 1 | 显式拦截名单 | 用户点名要拦的，优先放行 |
| 2 | 忽略名单 | 命中即无条件放行 |
| 3 | 可信白名单 | 按路径 / **SHA-256 指纹** / 发行商 / 名称匹配 |
| 4 | 已知正常软件本体 | WPS、搜狗输入法等放行 |
| 5 | **父子进程判定** | 正常软件拉起的第三方安装 → 拒绝 |
| 6 | 签名特征匹配 | 进程名 / 命令行命中流氓签名 |
| 7 | 启发式兜底 | Temp/下载目录 + 强捆绑命名特征 |

### 三、捆绑软件怎么认出来

捆绑的本质是"**A 软件在运行过程中，偷偷拉起 B 安装包**"。所以核心是
**父子进程关系 + 子进程特征**双重判定：

```
父进程是已知正常软件（wps.exe / SGTool.exe …）
        且
子进程满足以下任一：
  · 强捆绑特征命名（下载器 / 安装管家 / 游戏盒 / 推广 / 全家桶 / softmgr / tgp）
  · 命中流氓软件签名（如子进程叫 360tray.exe）
  · 通用安装器命名（setup / install / 安装）且位于 Temp/下载/桌面/INetCache
→ 结束该子进程，并记录事件
```

两个条件必须同时成立，所以 **WPS 自己的正常子进程不会被误杀**（有 6 条
决策用例覆盖：`tests/test_bundle_child.py`）。

另外文件落地侧还有一层：`ReadDirectoryChangesW` 监听下载/桌面/Temp，
可执行文件一落地就按文件名特征判定并隔离，形成"落地即拦" +
"运行即拦"两道防线。

## 实时防护如何工作

三层叠加，不是简单轮询：

1. **进程启动追踪**：订阅 WMI `Win32_ProcessStartTrace`（内核 ETW 事件），
   新进程一出现立即拿到 PID 与名称并判定，命中特征立即结束进程。
2. **目录变更通知**：`ReadDirectoryChangesW` 监听下载目录、桌面、Temp、
   INetCache 等位置，可执行文件一落地就判定，命中则移入隔离区。
3. **兜底轮询**：默认 2 秒，仅在事件源不可用时作为保险。

界面上的「防护模式」会显示当前是否为「内核事件驱动」。实测拦截响应在
毫秒到数百毫秒级，相比纯轮询显著更快。

## 计划任务（后台自动运行）

在「拦截守护」页勾选「开机自动启动」，会注册计划任务 `JunkCleaner Guard`：

- 触发条件：**登录时 + 开机时**（双触发）
- 运行账户：`SYSTEM`，`RunLevel = Highest`
- 无执行时长限制，异常退出后自动重启（最多 3 次）

查看状态：

```powershell
Get-ScheduledTask -TaskName 'JunkCleaner Guard' | Select State
python junkcleaner_entry.py status
```

## 可信软件白名单

四种加入方式：

1. 「可信软件 → 从已安装软件选择」：列出全部已安装软件，勾选后一键信任；
2. 「可信软件 → 白名单规则 → 选择文件」：**选择单个文件**（按路径）；
3. 「可信软件 → 白名单规则 → 选择压缩包内文件」：从 **zip / 7z / rar / tar**
   中选择包内单个文件，自动计算它的 **SHA-256 指纹**加入白名单；
4. 「扫描与清理」页勾选结果后点「信任此软件」，直接从扫描结果豁免。

### 压缩包内文件（按内容指纹放行）

这是「选单个文件、解压到别处也不会被误杀」的答案：

- **不整包放行**，只把你选中的那个文件按内容指纹（SHA-256）加入白名单；
- 该文件**解压 / 复制 / 改名到任何目录**后运行，指纹一致即放行；
- 压缩包里的**其他**文件仍然照常判定，不会被连带放行。

实现要点：进程启动判定原先只比对路径，现已补上指纹查询
（`trust.sha256_cached`，按 mtime+大小缓存，避免重复计算大文件），
所以解压出来的运行时也能命中指纹规则。

依赖：zip / tar 用标准库，7z 用 `py7zr`，rar 走 WinRAR 的 `UnRAR.exe`。

匹配优先级：**显式拦截名单 > 可信白名单 > 签名与启发式判定**。
被信任的软件在扫描结果中标注「可信」且不勾选，实时防护也会放行。

### Windows Defender 排除项

「可信软件 → Defender 排除项」可管理 `Get-MpPreference` 的 `ExclusionPath`。
加入排除项的路径不再被系统实时保护扫描，**会降低系统安全性**，
界面对此有明确警告，只对确实信任的软件使用。

## 判定等级

| 等级 | 含义 | 默认勾选 |
|------|------|----------|
| 流氓 | 强制捆绑、难以卸载、弹窗广告、劫持主页、静默安装 | 是 |
| 捆绑 | 以捆绑推广、诱导安装为主 | 是 |
| 争议 | 有大量正常用户，但含广告/推广/常驻（如 WPS、搜狗输入法、百度网盘、微软电脑管家） | **否** |
| 正常 | 明确正常的常用软件（WPS Office、搜狗输入法），登记进库只为**显式放行** | **否** |

内置 **97 条签名**，覆盖：

- 安全/管家全家桶：360 全家桶、腾讯电脑管家、2345 全家桶、金山毒霸/猎豹、
  瑞星、江民、百度卫士/杀毒、各类「管家/卫士/大师」
- 软件中心/应用商店：各类 PC 软件中心、联想/华硕/惠普/戴尔预装推广组件
- 壁纸/桌面：第三方壁纸与动态壁纸、桌面美化/图标/主题、桌面天气日历
- 广告/弹窗：购物桌面组件、资讯弹窗/热点推送、网址导航/主页劫持
- 影音娱乐：第三方音乐/视频客户端、直播/语音房、短视频桌面、游戏盒子/页游盒
- 游戏工具：各类加速器、游戏加加/优化工具、手游助手/模拟器推广版
- 驱动/系统工具：驱动精灵/驱动人生/驱动总裁、一键重装/装机工具、
  软媒魔方类优化工具、开机加速、系统修复/DLL 修复
- 工具类推广版：PDF 转换、数据恢复、录屏、图片处理、视频转换、C盘瘦身、
  一键清理、Wi-Fi 钥匙、网络加速器、天气日历、网络工具箱
- 其他：迅雷、暴风影音、UC浏览器、Flash 中心、小鸟壁纸、快压、
  手机助手/投屏、网盘推广版、下载站「高速下载器」等

### WPS 与搜狗输入法：本体放行，只拦第三方捆绑

WPS Office 和搜狗输入法是主流正常软件，被登记为「正常软件」档位：

- **本体正常使用**：`wps.exe` / `et.exe` / `wpp.exe` / `sogouimebroker.exe` /
  `SGTool.exe` 等进程一律放行，扫描时不勾选、清理时不处理。
- **第三方捆绑照拦**：实时防护会查这些进程拉起的**子进程**。如果 WPS 或搜狗
  拉起了来自 Temp/下载目录、名字含 installer/setup/游戏盒/推广 等特征的
  第三方安装包，直接结束进程并隔离（规则见 `guard.py` 的 `BUNDLE_HINT_PATTERNS`）。

### 忽略名单（高级）

「拦截守护 → 忽略名单」可添加进程名/路径关键词（如 `wps.exe`），命中即
**无条件放行且只记录不拦截**。适合你完全不想被打扰的软件。

## 安全设计

- **不靠厂商名判定**：仅凭「发行商」不会触发，避免误伤同厂商正常软件
  （如微信、QQ、腾讯会议）。
- **证据可核对**：每条结果都列出命中的注册表键、路径、进程名，界面上可直接看。
- **隔离而非删除**：残留文件移动到 `隔离区`，可从「隔离与还原」页还原。
- **C 盘照清**：垃圾软件绝大多数就在 C 盘，工具不会因为路径在 C 盘就放过它。
  保护的只是「系统根本身」和「正常软件目录」。
- **争议软件默认不勾选**，由用户自行决定。

### 保护规则（`cleaner.py`）

判定顺序：**垃圾特征 > 系统目录 > 正常软件厂商**。

1. `JUNK_MARKERS`：明确的垃圾路径特征（`qqpcmgr`、`360safe`、`2345explorer`、
   `thunder`、`ludashi`、`flashhelper`、`pcmanager`…）命中即可清理，
   优先级最高，可覆盖厂商保护。
2. `SYSTEM_ROOTS`：只保护系统**根本身**（`C:\Windows`、`C:\Program Files`、
   `C:\ProgramData`、`C:\Users`、`System32`）。其下子目录仍会被清理。
3. `NORMAL_VENDOR_SEGMENTS`：正常软件厂商按**路径段精确匹配**，
   例如 `C:\...\Tencent\QQ\Bin` 保护，但 `C:\...\Tencent\QQPCMgr` 不保护。

> 早期版本用裸子串匹配厂商名，导致 `tencent\qq` 误伤了 `tencent\qqpcmgr`
> （腾讯电脑管家永远清不掉），`git`/`java` 也会误伤 `Digital`/`Javascript`。
> 现已改为路径段匹配，并有 35 条用例的回归测试覆盖。

## 能力边界（请如实了解）

- **卸载**：调用软件自带的卸载程序，做不到 100% 静默。遇到需要交互的卸载器
  （点「下一步」、留「为什么要卸载」问卷、甚至挽留页面），仍需人工点几下。
  之后工具会自动清理进程、服务、计划任务、残留文件与卸载注册表项。
- **阻止安装**：采用内核事件源（ETW 进程追踪 + 文件系统通知）驱动，
  响应快、不是轮询；但仍是**用户态行为拦截**，不是文件系统微过滤驱动。
  它拦得住绝大多数从浏览器下载、下载站二次跳转、捆绑下载器投放的安装包，
  但无法阻止已获管理员权限后改名运行、或内核级安装的程序。做到真正
  驱动级阻断需要自行开发并签名 minifilter 驱动，涉及内核开发与
  WHQL/EV 代码签名，风险与成本高得多。
- 拦截守护与清理需要管理员权限；普通权限下界面能打开，但相关按钮会提示提权。

## 数据位置

## Defender 组策略优化（对应截图那一页）

「Defender 优化」页对应：

```
计算机配置 > 管理模板 > Windows 组件 > Microsoft Defender 防病毒 > 扫描
注册表: HKLM\SOFTWARE\Policies\Microsoft\Windows Defender\Scan
```

**保留扫描能力，只把性能损耗压到最低**，两档预设：

### 平衡档（推荐，几乎零安全损失，15 项）

| 策略 | 值 | 作用 |
|------|----|------|
| AvgCPULoadFactor | 5 | 扫描 CPU 上限 5%（Defender 允许的最低值） |
| LowCpuPriority | 1 | 计划扫描以低 CPU 优先级运行 |
| ScanOnlyIfIdle | 1 | 只在你不用电脑/不玩游戏时才自动扫描 |
| AllowPause | 1 | 允许随时暂停扫描 |
| DisableScanningNetworkFiles | 1 | 跳过网络位置文件 |
| DisableRemovableDriveScanning | 1 | 跳过 U 盘/移动硬盘 |
| DisableReparsePointScanning | 1 | 跳过重解析点，避免重复扫描 |
| DisableRestorePoint | 1 | 扫描前不创建还原点 |
| DisableEmailScanning | 1 | 跳过邮件文件解析 |
| DisableCatchupQuickScan / FullScan | 1 | 关闭「错过扫描后补跑」——最常见的卡顿来源 |
| CheckForSignaturesBeforeRunningScan | 0 | 不再每次扫描前都联网更新签名 |
| QuickScanInterval | 7 | 快速扫描改为每 7 天一次 |
| ScheduleQuickScantime | 720 | 安排在 12:00（避开游戏时段） |
| PurgeItemsAfterDelay | 30 | 扫描记录 30 天后清理 |

### 激进档（最低开销，+3 项，**有安全代价**）

额外关闭压缩包扫描、加壳可执行文件扫描，并把存档扫描深度压到 1 层。
界面上这些项会标红提示。

### 安全边界

- **只动「扫描」页的策略**，不碰实时保护（`DisableRealtimeMonitoring`、
  `DisableAntiSpyware` 等一律不涉及），也不会关闭 Defender 本身。
- 每次应用前**自动完整备份**（`%ProgramData%\JunkCleaner\defender_backups\`），
  可一键还原；也能「全部恢复未配置」。
- 已实测：应用 15 项 → 还原后注册表与原始状态**逐字节一致**。
- 若系统开启「篡改防护」，页面会给出明确提示（写入会被拒绝），
  需先在 Windows 安全中心关闭。
- 「每次启动本程序时自动应用」为可选，默认关闭。

## 打包踩坑记录（单文件 EXE）

## 电源 / GPU 调优

### 电源方案（Win10 / Win11 自动识别）

启动时读取 `Win32_OperatingSystem`，**Build ≥ 22000 判定为 Windows 11**。

「卓越性能」(Ultimate Performance) 的处理要点：

- 它对应的模板 GUID 是 `e9a42b02-d5df-448d-aa00-03f14749eb61`，但
  **用 `powercfg -duplicatescheme` 创建后会生成一个全新的 GUID**
  （本机实测得到 `34a6798b-...`）。所以代码里**按名称**查找，
  不能按模板 GUID 找，否则永远找不到。
- 一笔 `powercfg /setactive` 就会持久化到注册表，**重启后依然生效**，
  不需要额外交互。
- 可选「性能项调优」：把最大/最小处理器状态、系统散热方式调到性能优先。
- Windows 11 默认隐藏该方案，需要先创建；本工具会自动处理。

### GPU（NVIDIA，走 nvidia-smi）

**实测本机 nvidia-smi 能力**（RTX 4070 Ti SUPER / 驱动 617.42）：

| 能力 | 支持 | 说明 |
|------|------|------|
| 锁定核心/显存频率 | ✅ | `--lock-gpu-clocks` / `--lock-memory-clocks` |
| 功耗墙 | ✅ | `--power-limit` |
| 恢复默认 | ✅ | `--reset-gpu-clocks` |
| **设置电压** | ❌（nvidia-smi） | nvidia-smi **没有任何电压接口**；改走 NVAPI 后端，见下节 |
| **设置风扇转速** | ❌ | nvidia-smi **无法设置风扇** |

「稳定性验证」会锁定目标频率并持续采样，输出**实际频率 / 温度 / 功耗 /
真实降频原因**。注意区分：`0x1` 是 GpuIdle（空闲自动降频，属正常），
工具只统计去掉 GpuIdle 之后的真实节流原因。

**开机固化**：nvidia-smi 的设置重启后会丢失，所以提供「固化」——
把配置存到 `gpu_profile.json`，并注册计划任务 `JunkCleaner GPU Tune`
在登录时用 `--gpu-apply` 重新应用。已实测：保存 → 注册 → 模拟开机应用
（功耗墙 + 锁频都成功）→ 移除，全流程通过。

### CPU 调压：为什么没有做自动搜索

这一项我**没有实现**，不是偷懒，是三个硬性障碍：

1. **需要内核级 MSR 驱动**。CPU 电压通过 `MSR 0x150`（Voltage Offset）调节，
   用户态无法访问，需要 WinRing0 / inpoutx64 这类**内核驱动**。
   实测本机**没有任何这类驱动**，ThrottleStop / XTU 也都没装。
2. **13 代 Intel 已被固件锁死**。你的 i7-13700KF 属于 Raptor Lake，
   2023 年微码更新加入了 **Undervolt Protection**，`MSR 0x150` 写入会被
   固件直接拒绝——这是 Intel 针对降级事件的官方对策。
3. **自动找最低电压 = 故意让系统崩溃**。正确做法是逐档降压并跑压测，
   直到崩溃；每次崩溃都是**硬重启，可能损坏文件系统或正在保存的文件**。
   把它做成自动化循环，风险与收益完全不成比例。

所以「电源 / GPU」页只提供**只读的能力检测**，并给出可行路径：
在 BIOS 用 Offset 模式降压（最稳妥、开机即持久），或用 XTU / ThrottleStop
手动逐步测试。

## GPU 降压调优（NVAPI，无需 Afterburner）

GPU 降压现在由内嵌的 MIT 许可工具 **simple-nvidia-undervolt** 直接走
NVAPI（Pstates20）完成，不再依赖 Afterburner。它和 CPU 的关键区别在于
失败代价：电压不够时 NVIDIA 驱动会**重置显卡驱动**（黑一下、事件日志
Display 41），系统本身不受影响；CPU 降压失败则是整机硬重启。

### 接入方式

工具通过 NVAPI 的 Pstates20 接口直接读写显卡 V/F 曲线：把目标电压以上
的点拉成水平平台，低电压段保持原样，所以待机仍会自然降频。它可以读取
真实核心电压，而 Afterburner 监控共享内存和 `nvidia-smi` 在部分驱动上
都拿不到这项数据。

工具为官方发布二进制（Release v1.0.9），未做修改，许可证与哈希见
`junkcleaner/assets/LICENSE-simple-nvidia-undervolt.txt`。

### 自动搜索最低稳定电压

在「电源 / GPU」页设置：目标频率、每档降压（默认 25mV）、电压下限（默认 800mV）、
单档验证时长（默认 300 秒 = 5 分钟）。

流程：

1. 读取当前已应用电压；不可读时从 NVAPI 曲线按目标频率取参考值
2. 先把曲线锁成「目标频率 @ 起始电压」，并验证起始档本身稳定
3. 每档 -25mV，直接用 NVAPI 写入并应用
4. 每档用 **PyTorch CUDA 满载压测**，校验频率达标、无掉频、无数值损坏
5. 通过 → 记录为新的回退点继续降；不通过 → 立即回退到上一档稳定值并停止
6. 搜索结束后，点「**一键应用并固化**」写入显卡，并注册登录重应用任务，
   下次开机或驱动重置后自动恢复

> 搜索阶段不会自动改开机配置；只有你明确点「一键应用并固化」才会固化。

### 实测结果（本机 RTX 4070 Ti SUPER）

```
目标 2850MHz，原厂 1100mV
 1050mV  满载 99%，0 掉频   ✓ 稳定
 1025mV  满载 99%，0 掉频   ✓ 稳定
  ...
  955mV  满载 99%，0 掉频，45°C，176W   ✓ 稳定
  930mV  CUDA 负载启动失败                  ✗ 不稳定，回退 955mV
```

满载实测 960mV / 2850MHz / 45°C，功耗从 208W 降到 176W。

### 安全设计

- 每档失败**立即回退**到上一个经过验证的稳定配置，不会停在危险电压
- 驱动无响应时会等待恢复再继续
- 支持随时「停止搜索」，停下时固定在最后一档稳定值
- 一键「恢复原厂」清空调参并移除登录重应用任务
- 满载负载不可用时不会给出“最低稳定电压”的假结论，会直接中止并说明原因
- **主动校验计算结果**：降压不稳常表现为「时钟正常但算错」（花屏 / 静默
  数据损坏），这类错误不抛异常，只能靠校验发现。程序每轮都会检查输出
  是否为有限值、峰值是否异常，命中即判为不稳定
- **每档就是 25mV 安全间距**：搜索停在的稳定档时，下一档已经实测失败，
  因此该档天然带一档余量；如需额外余量界面仍提供可调项

> 注意：风扇策略不在本工具范围内，自动改动风扇曲线与机箱风道强相关，
> 风险大于收益。

打包过程中排掉的问题，记录下来避免重复踩：

1. **`ucrtbase.dll` 被误打包**：这台机器的 PATH 上有 5 个外来 `ucrtbase.dll`
   （v10.0.26100，系统是 10.0.19041），PyInstaller 会把它收进包，
   导致 Qt 解析出错。已在 spec 里过滤。
2. **PATH 上有旧版 Qt**：`STM32CubeProgrammer` 自带 Qt 6.6.1，会被优先加载。
   `junkcleaner_entry.py` 的 `_prepare_frozen_dll_path()` 会把含冲突 DLL 的
   目录移出搜索路径，并把自带库前置。
3. **❌ 真正的主因：版本不兼容**。PySide6 **6.11.1 + PyInstaller 6.22.3**
   在本机必然失败（连最小 PySide6 样例都跑不起来），且**与 PATH 无关**
   （仅 System32 的干净 PATH 下同样失败）。换成
   **PySide6 6.8.3 + PyInstaller 6.11.1** 后一次通过。
4. **`uac_admin=True`**：`manifest=` 参数会被 PyInstaller 自带的 `asInvoker`
   清单覆盖，必须用 `uac_admin=True` 才能真正请求管理员权限。

## 数据位置

默认 `%ProgramData%\JunkCleaner`（无写权限时回退到 `%LOCALAPPDATA%\JunkCleaner`），
可用环境变量 `JUNKCLEANER_DATA` 覆盖。包含：

- `quarantine\`　　隔离区（清理的残留、拦截的安装包）
- `manifests\`　　每次清理的还原清单
- `last_scan.json`　上次扫描结果
- `events.jsonl`　　拦截/清理事件流
- `logs\`　　　　　按天日志
- `config.json`　　守护开关、轮询间隔、自定义拦截规则
- `trust.json`　　可信白名单
- `blocked.json`　　显式拦截名单

## 自检

```powershell
运行自检.cmd
```

单独运行：

```powershell
python tests\test_signatures.py   # 签名匹配（含正常软件不误报）
python tests\test_clean.py        # 隔离 → 删注册表 → 清单 → 还原
python tests\test_guard.py        # 内核事件拦截 + 白名单放行
python tests\test_trust.py        # 信任后扫描跳过、拦截名单优先
python tests\test_protection.py   # C 盘垃圾可清 / 正常软件不被误伤
python tests\test_gui_smoke.py    # 各页签与表格渲染
```
