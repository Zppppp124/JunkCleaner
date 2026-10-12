# Afterburner 下载：实测结论

## 实测发现（2026-10）

### 1. MSI 官网的「下载」按钮不是 Afterburner

从 `https://www.msi.cn/Landing/afterburner/graphics-cards` 页面提取到的唯一下载入口是：

```
https://dls2-int.norton.com/v1/downloads?downloadTemplateId=121357
```

下载下来是 **4.38 MB 的 Norton Download Manager**，解包后的字符串里包含：

```
https://buy-download.norton.com/downloads/2022/MSI/36270/18644/N360Gmr/MUI/Setup.exe
https://buy-download.norton.com/downloads/FSD/5.37.0/1/FSDPlugin.dll
```

文件版本信息：

```
FileVersion   : 5.37.0.1
ProductName   : Norton Download Manager
CompanyName   : Gen Digital Inc.
```

**结论**：MSI 中国站那个下载按钮是**推广 Norton 360 的广告位**，
不是 Afterburner 本体。这很讽刺——一个专门清理垃圾软件的工具，
如果照抄这个按钮去自动安装，等于自己往用户电脑里装 Norton 全家桶。

**所以本工具绝不会自动安装它。**

### 2. 真正的 Afterburner 官方下载渠道

| 渠道 | 状态 |
|------|------|
| `download.msi.com/uti_exe/vga/MSIAfterburnerSetup.zip` | 403（CDN 拦截非浏览器请求） |
| MSI 全球站页面 | 200，但页面里没有直链 |
| MSI 中国站页面 | 200，但按钮指向 Norton 推广 |
| Guru3D（官方合作分发方） | 403 / 连接重置 |
| TechPowerUp 镜像 | 404 |

**结论**：没有稳定可用的**纯程序化**下载直链。
MSI 把 Afterburner 的分发做成了「必须经过浏览器 + 可能经过 Norton 推广」的流程。

### 3. 本工具采取的策略

按可靠性从高到低：

1. **自动发现已安装的 Afterburner**（多路径 + 注册表 + 进程 + 浅层搜索）。
   已安装的情况下，降压、曲线、静默卸载等**全部功能可用**。
2. **一键打开官方下载页**（系统默认浏览器）：让用户在真实浏览器里完成下载，
   避开 Cloudflare 拦截，也避开 Norton 推广陷阱。
3. **检测用户手动放进来的安装包**：如果用户在程序目录下的
   `runtime\afterburner\` 里放了 `MSIAfterburnerSetup.exe` 或 `.zip`，
   本工具会自动识别并静默安装到程序目录。
4. **下载校验**：任何自动下载都必须通过「PE 头 + 产品名」双重校验，
   确认是真正的 Afterburner 安装器才允许安装；
   若检出 Norton 或其它产品，直接拒绝并告知用户。

### 4. 为什么不做「静默安装 Norton 推广包」

技术上做得到（Norton DM 支持 `/S`），但：

* 那是**推广软件**，与用户「清理垃圾软件」的目标直接冲突
* 会给用户电脑装上 Norton 360 试用版与常驻进程
* 违背本工具的定位与用户信任

因此明确不做，并在界面上说明原因。
