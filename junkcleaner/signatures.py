"""内置「垃圾/流氓软件」特征库。

评级说明
--------
rogue     高争议流氓行为：强制捆绑、难以卸载、弹窗广告、劫持主页/浏览器、
          静默安装、难以彻底移除。扫描结果默认勾选。
bundle    以捆绑推广、诱导安装、广告推送为主，软件本身可能有正常功能，
          但安装时容易带入全家桶。扫描结果默认勾选。
disputed  存在较大争议或广告较多，但同时有大量正常用户（例如办公套件、
          网盘、输入法）。扫描结果默认「不勾选」，由用户自行判断。
normal    明确正常、用户量大的软件（如 WPS、搜狗输入法）。它们被登记进库
          只是为了「显式放行 + 记录它拉起过什么」，界面单独标注为「正常软件」，
          永远不会被清理，也不会被当作流氓软件处理。

匹配优先级（见 scanner.py）：卸载项名称 > 安装目录 > 进程/服务/计划任务。
仅凭「发行商」不会触发判定，避免误伤同厂商的正常软件（如微信、QQ）。
"""

from __future__ import annotations

from typing import Any

# 公开资料来源（库里每条判定的依据都来自这些公开信息与真实行为特征）
SOURCES = [
    "知乎/贴吧等社区长期讨论的「流氓软件/全家桶」名单",
    "各安全厂商（火绒、360、腾讯、金山）发布的捆绑与弹窗治理公告",
    "工信部/网信办关于 App 与 PC 软件捆绑、弹窗骚扰的通报与整改名单",
    "用户投诉与卸载教程中反复出现的进程名、服务名、安装目录",
    "签名判定基于真实文件名/进程名/目录名，不凭厂商名猜测",
]

# 占位：具体条目见文件末尾 SIGNATURES
SIGNATURES: list[dict[str, Any]] = []


def _sig(
    sid: str,
    name: str,
    vendor: str,
    risk: str,
    tags: list[str],
    why: str,
    uninstall: list[str] | None = None,
    publisher: list[str] | None = None,
    path: list[str] | None = None,
    process: list[str] | None = None,
    service: list[str] | None = None,
    task: list[str] | None = None,
    files: list[str] | None = None,
    generic: bool = False,
    silent_allow: bool = False,
    basis: str = "",
) -> dict[str, Any]:
    return {
        "id": sid,
        "name": name,
        "vendor": vendor,
        "risk": risk,
        "tags": tags,
        "why": why,
        "uninstall": uninstall or [],
        "publisher": publisher or [],
        "path": path or [],
        "process": process or [],
        "service": service or [],
        "task": task or [],
        "files": files or [],
        "generic": generic,
        "silent_allow": silent_allow,
        "basis": basis or "公开社区共识 + 真实进程/目录行为特征",
    }


SIGNATURES = [
    # ================= 360 / 奇虎 =================
    _sig(
        "360.weishi", "360安全卫士", "360（奇虎）", "rogue",
        ["安全卫士", "捆绑", "弹窗", "主页劫持"],
        "国内最典型的「全家桶」源头之一：默认勾选捆绑 360 系全家桶、弹窗推广、"
        "修改浏览器主页、接管右键菜单与驱动，卸载后仍可能残留服务。",
        uninstall=[r"360\s*安全卫士", r"360\s*Total\s*Security"],
        publisher=[r"qihoo", r"奇虎", r"360"],
        path=[r"\\360safe", r"\\360\s*Security", r"\\360deepscan"],
        process=[r"360tray\.exe", r"360safe\.exe", r"360sd\.exe", r"360rp\.exe",
                 r"liveupdate360\.exe", r"360speedld\.exe"],
        service=[r"360safe", r"360rp", r"360sd", r"360deepscan"],
        task=[r"360", r"qhsafe"],
    ),
    _sig(
        "360.antivirus", "360杀毒", "360（奇虎）", "rogue",
        ["杀毒", "捆绑", "弹窗"],
        "与 360 安全卫士相互捆绑推广，静默安装、弹窗推广行为常见。",
        uninstall=[r"360\s*杀毒", r"360\s*Antivirus", r"360\s*Total\s*Security"],
        publisher=[r"qihoo", r"奇虎", r"360"],
        path=[r"\\360\s*Antivirus", r"\\360safe\\deepscan"],
        process=[r"360sd\.exe", r"360rp\.exe", r"360avm\.exe"],
        service=[r"360sd", r"360rp"],
    ),
    _sig(
        "360.browser", "360安全浏览器 / 360极速浏览器", "360（奇虎）", "rogue",
        ["浏览器", "主页劫持", "捆绑"],
        "常被静默安装并设为默认浏览器、劫持导航主页、注入广告推广。",
        uninstall=[r"360\s*(安全|极速)?浏览器", r"360\s*(Safe|Chrome|Speed)\s*Browser",
                   r"360se", r"360Chrome"],
        publisher=[r"qihoo", r"奇虎", r"360"],
        path=[r"\\360se6", r"\\360Chrome", r"\\360Browser", r"\\360se"],
        process=[r"360se\.exe", r"360chrome\.exe", r"360se6\.exe"],
    ),
    _sig(
        "360.softmgr", "360软件管家", "360（奇虎）", "rogue",
        ["软件管家", "捆绑", "推广"],
        "常随 360 全家桶静默安装，用来继续推广其他软件。",
        uninstall=[r"360\s*软件管家", r"360\s*Software\s*Manager"],
        publisher=[r"qihoo", r"奇虎", r"360"],
        path=[r"\\360safe\\softmgr", r"\\360SoftMgr"],
        process=[r"softmgr\.exe", r"360softmgr\.exe"],
    ),
    _sig(
        "360.zip", "360压缩", "360（奇虎）", "bundle",
        ["压缩", "捆绑", "右键菜单"],
        "常被捆绑安装并劫持压缩包关联、右键菜单推广。",
        uninstall=[r"360\s*压缩", r"360\s*Zip"],
        publisher=[r"qihoo", r"奇虎", r"360"],
        path=[r"\\360zip", r"\\360\s*Compress"],
        process=[r"360zip\.exe"],
    ),
    _sig(
        "360.driver", "360驱动大师", "360（奇虎）", "bundle",
        ["驱动", "捆绑", "推广"],
        "驱动类工具，安装包常捆绑 360 全家桶并推送推广软件。",
        uninstall=[r"360\s*驱动大师", r"360\s*Driver"],
        publisher=[r"qihoo", r"奇虎", r"360"],
        path=[r"\\360Drivers", r"\\360\s*Driver"],
        process=[r"360drvinst\.exe", r"drvinst\.exe"],
    ),
    _sig(
        "360.mobile", "360手机助手", "360（奇虎）", "bundle",
        ["手机助手", "捆绑"],
        "常被捆绑安装，占用后台并推送推广。",
        uninstall=[r"360\s*手机助手", r"360\s*Mobile\s*Assistant"],
        publisher=[r"qihoo", r"奇虎", r"360"],
        path=[r"\\360MobileMgr", r"\\360\s*Mobile"],
    ),
    _sig(
        "360.misc", "360影视大全 / 360壁纸 / 360导航等", "360（奇虎）", "rogue",
        ["推广", "弹窗", "壁纸"],
        "360 生态内典型的强推组件，弹窗推广、修改主页为主。",
        uninstall=[r"360\s*(影视|壁纸|导航|桌面|游戏|AI| wallpaper)",
                   r"360\s*(Video|Wallpaper|Desktop|Nav)"],
        publisher=[r"qihoo", r"奇虎", r"360"],
        path=[r"\\360\s*(Video|Wallpaper|Desktop)", r"\\360ysdq", r"\\360bizhi"],
    ),
    _sig(
        "360.other", "360 其他组件（急救箱 / 系统助手等）", "360（奇虎）", "rogue",
        ["组件", "残留"],
        "360 家族的其他组件，通常难以单独卸载、易残留驱动与服务。",
        uninstall=[r"360\s*(系统急救箱|急救箱|系统助手|软件宝库|安全云盘|WiFi)",
                   r"360\s*(System|Security)\s*(Rescue|Assistant)"],
        publisher=[r"qihoo", r"奇虎", r"360"],
        path=[r"\\360\s*System", r"\\360Rescue", r"\\360\s*Assistant"],
    ),

    # ================= 腾讯 =================
    _sig(
        "tencent.pcmgr", "腾讯电脑管家", "腾讯", "rogue",
        ["电脑管家", "捆绑", "弹窗"],
        "典型国产杀软/管家类软件：弹窗推广、捆绑安装腾讯系软件、接管驱动；"
        "与 360 冲突且均难以彻底卸载。",
        uninstall=[r"腾讯电脑管家", r"腾讯\s*电脑\s*管家", r"QQ电脑管家",
                   r"Tencent\s*PC\s*Manager", r"QQPCMgr"],
        publisher=[r"tencent", r"腾讯"],
        path=[r"\\Tencent\\QQPCMgr", r"\\QQPCMgr", r"\\Tencent\\QQPCMgr"],
        process=[r"QQPCTray\.exe", r"QQPCMgr\.exe", r"QMDL\.exe", r"QQPCRealTimeSpeedup\.exe"],
        service=[r"QQPCMgr", r"QMPersonalCenter", r"QQPC"],
        task=[r"QQPCMgr", r"Tencent"],
    ),
    _sig(
        "tencent.browser", "QQ浏览器", "腾讯", "bundle",
        ["浏览器", "捆绑", "主页"],
        "常被捆绑安装、抢占默认浏览器、推广导航主页。",
        uninstall=[r"QQ\s*浏览器", r"QQ\s*Browser", r"Tencent\s*Browser"],
        publisher=[r"tencent", r"腾讯"],
        path=[r"\\Tencent\\QQBrowser", r"\\QQBrowser"],
        process=[r"QQBrowser\.exe", r"QQBrowserSetup\.exe"],
    ),
    _sig(
        "tencent.appstore", "应用宝电脑版 / 腾讯手游助手", "腾讯", "bundle",
        ["应用宝", "手游助手", "捆绑"],
        "PC 端应用分发工具，常被捆绑安装并推广手游/软件。",
        uninstall=[r"应用宝", r"腾讯手游助手", r"腾讯游戏管家", r"Tencent\s*(AppStore|Gaming)"],
        publisher=[r"tencent", r"腾讯"],
        path=[r"\\Tencent\\AppStore", r"\\Tencent\\GameLoop", r"\\yingyongbao"],
        process=[r"AndroidEmulator\.exe", r"TxGameAssistant\.exe", r"appstore\.exe"],
    ),
    _sig(
        "tencent.lite", "腾讯柠檬清理", "腾讯", "disputed",
        ["清理", "推广"],
        "本身是清理工具，但会推送腾讯系软件；一般不需要常驻。",
        uninstall=[r"腾讯柠檬清理", r"Lemon\s*Clean", r"Tencent\s*Lemon"],
        publisher=[r"tencent", r"腾讯"],
        path=[r"\\Tencent\\Lemon"],
        process=[r"Lemon\.exe", r"LemonCleaner\.exe"],
    ),
    _sig(
        "tencent.misc", "腾讯系推广组件（腾讯视频/桌面整理等）", "腾讯", "disputed",
        ["推广", "弹窗"],
        "腾讯系客户端常用弹窗推送、捆绑更新，视个人需要保留。",
        uninstall=[r"腾讯\s*(视频|桌面整理|会议助手|文档)"],
        publisher=[r"tencent", r"腾讯"],
        path=[r"\\Tencent\\DesktopMgr", r"\\Tencent\\QQLive"],
    ),

    # ================= 微软电脑管家 =================
    _sig(
        "microsoft.pcmgr", "微软电脑管家 (Microsoft PC Manager)", "Microsoft", "disputed",
        ["电脑管家", "预装", "常驻"],
        "微软官方推出的管家类工具，功能正规，但会常驻、推送 Edge/系统推荐，"
        "对不需要的用户属于冗余预装。默认不勾选。",
        uninstall=[r"Microsoft\s*PC\s*Manager", r"微软电脑管家"],
        publisher=[r"microsoft"],
        path=[r"\\Microsoft\s*PC\s*Manager", r"\\PCManager"],
        process=[r"PCManager\.exe", r"MSPCManager\.exe"],
        service=[r"PCManager"],
    ),

    # ================= 2345 / 二三四五 =================
    _sig(
        "2345.nav", "2345 网址导航 / 2345 加速浏览器", "2345（二三四五）", "rogue",
        ["浏览器", "主页劫持", "捆绑"],
        "国内最具代表性的流氓软件家族之一：强制修改主页、桌面快捷方式无法删除、"
        "静默安装、捆绑推广。",
        uninstall=[r"2345\s*(网址导航|加速浏览器|浏览器|安全卫士|软件管家)",
                   r"2345\s*(Explorer|Browser|Safe)"],
        publisher=[r"2345", r"二三四五"],
        path=[r"\\2345\s*(Explorer|Browser|Safe)", r"\\2345Explorer", r"\\2345Soft"],
        process=[r"2345Explorer\.exe", r"2345Browser\.exe", r"2345Safe\.exe",
                 r"2345SoftMgr\.exe"],
        service=[r"2345"],
        task=[r"2345"],
    ),
    _sig(
        "2345.haozip", "2345好压 / 2345看图王", "2345（二三四五）", "rogue",
        ["压缩", "看图", "捆绑", "右键菜单"],
        "常被捆绑安装、劫持压缩包与图片关联、弹窗推广。",
        uninstall=[r"2345\s*(好压|看图王|压缩)", r"2345\s*(GoodZip|Pic)"],
        publisher=[r"2345", r"二三四五"],
        path=[r"\\2345\s*(GoodZip|Pic)", r"\\HaoZip", r"\\2345Pic"],
        process=[r"HaoZip\.exe", r"2345Pic\.exe", r"2345PIC\.exe"],
    ),
    _sig(
        "2345.misc", "2345 系列组件（天气/影视/输入法/看图）", "2345（二三四五）", "rogue",
        ["推广", "弹窗"],
        "2345 生态的其他推广组件，多随主程序静默安装。",
        uninstall=[r"2345\s*(天气|影视|输入法|桌面|日历|游戏|彩票)",
                   r"2345\s*(Weather|Video|Input)"],
        publisher=[r"2345", r"二三四五"],
        path=[r"\\2345\s*(Weather|Video|Input|Desktop)", r"\\2345Weather"],
    ),

    # ================= 金山 / 猎豹 =================
    _sig(
        "kingsoft.antivirus", "金山毒霸", "金山 / 猎豹", "rogue",
        ["杀毒", "捆绑", "弹窗"],
        "与 360、腾讯管家类似：弹窗推广、捆绑全家桶、接管系统。",
        uninstall=[r"金山毒霸", r"Kingsoft\s*Antivirus", r"Duba"],
        publisher=[r"kingsoft", r"金山", r"猎豹", r"cheetah"],
        path=[r"\\Kingsoft\\Antivirus", r"\\Duba", r"\\kingsoft\\antivirus"],
        process=[r"kxetray\.exe", r"kxescore\.exe", r"kwsprotect64\.exe"],
        service=[r"kxescore", r"kwsprotect", r"Kav"],
    ),
    _sig(
        "kingsoft.cheetah", "猎豹安全浏览器 / 猎豹清理大师", "金山 / 猎豹", "rogue",
        ["浏览器", "清理", "主页劫持", "捆绑"],
        "常被捆绑安装并劫持主页、弹窗推广。",
        uninstall=[r"猎豹(安全)?浏览器", r"猎豹清理大师", r"Cheetah\s*(Browser|Clean)"],
        publisher=[r"kingsoft", r"金山", r"猎豹", r"cheetah"],
        path=[r"\\Cheetah", r"\\liebao", r"\\Kingsoft\\Cheetah"],
        process=[r"liebao\.exe", r"CheetahBrowser\.exe", r"CheetahClean\.exe"],
    ),
    _sig(
        "kingsoft.wps", "WPS Office", "金山办公", "normal",
        ["办公", "正常软件", "广告"],
        "国内最主流的办公套件之一，正常编辑文档完全不受影响。免费版含广告与云文档"
        "推广，但软件本身不会静默安装第三方垃圾软件；真正要拦的是它可能拉起的"
        "第三方推广安装包，那种会被实时防护拦下。默认不勾选。",
        uninstall=[r"WPS\s*Office", r"金山\s*WPS"],
        publisher=[r"kingsoft", r"金山"],
        path=[r"\\Kingsoft\\WPS Office", r"\\WPS Office"],
        process=[r"wps\.exe", r"wpscloudsvr\.exe", r"wpscenter\.exe"],
        silent_allow=True,
    ),
    _sig(
        "kingsoft.other", "金山系推广组件（打字通/桌面整理等）", "金山 / 猎豹", "bundle",
        ["推广", "捆绑"],
        "金山系推广组件，多随 WPS 或毒霸捆绑安装。",
        uninstall=[r"金山\s*(打字通|桌面整理|电池医生|驱动)", r"Kingsoft\s*(Type|Desktop)"],
        publisher=[r"kingsoft", r"金山", r"猎豹"],
        path=[r"\\Kingsoft\\Desktop", r"\\Kingsoft\\Typing"],
    ),

    # ================= 鲁大师 / 驱动类 =================
    _sig(
        "ludashi.main", "鲁大师", "鲁大师", "bundle",
        ["硬件检测", "跑分", "捆绑", "弹窗"],
        "硬件检测/跑分工具，安装包与运行期推广较多、常捆绑其他软件。",
        uninstall=[r"鲁大师", r"Lu\s*Da\s*Shi", r"LuDaShi"],
        publisher=[r"ludashi", r"鲁大师", r"ludash"],
        path=[r"\\LuDaShi", r"\\鲁大师", r"\\Ludashi"],
        process=[r"ComputerZ.*\.exe", r"LuDaShi.*\.exe", r"Lds.*\.exe"],
    ),
    _sig(
        "driver.gene", "驱动精灵", "驱动精灵", "bundle",
        ["驱动", "捆绑", "推广"],
        "驱动工具，安装/更新过程中捆绑推广软件的情况较多。",
        uninstall=[r"驱动精灵", r"Driver\s*Genius"],
        publisher=[r"driver\s*genius", r"驱动精灵", r"drivergenius"],
        path=[r"\\DriverGenius", r"\\驱动精灵"],
        process=[r"DriverGenius\.exe", r"DrvGenius.*\.exe"],
    ),
    _sig(
        "driver.life", "驱动人生", "驱动人生", "bundle",
        ["驱动", "捆绑", "推广"],
        "驱动工具，安装时勾选捆绑、更新时推广告，属于常见捆绑来源。",
        uninstall=[r"驱动人生", r"Drive\s*The\s*Life", r"DriveTheLife"],
        publisher=[r"drivethe?life", r"驱动人生"],
        path=[r"\\DriveTheLife", r"\\驱动人生"],
        process=[r"DriveTheLife\.exe", r"DTL.*\.exe"],
    ),
    _sig(
        "driver.master", "驱动总裁 / 万能驱动", "驱动总裁", "bundle",
        ["驱动", "捆绑"],
        "驱动类工具，部分版本存在捆绑推广行为。",
        uninstall=[r"驱动总裁", r"万能驱动", r"Driver\s*Master"],
        publisher=[r"驱动总裁", r"driver\s*master"],
        path=[r"\\DriverMaster", r"\\驱动总裁"],
    ),

    # ================= 百度 =================
    _sig(
        "baidu.guard", "百度卫士 / 百度杀毒", "百度", "rogue",
        ["杀毒", "捆绑", "静默安装"],
        "已停止维护的百度安全产品，常被静默捆绑安装，需彻底清理。",
        uninstall=[r"百度\s*(卫士|杀毒)", r"Baidu\s*(Guard|Antivirus)"],
        publisher=[r"baidu", r"百度"],
        path=[r"\\Baidu\\BaiduAn", r"\\baidu\\baidusd", r"\\Baidu\\BaiduGuard"],
        process=[r"BaiduSd\.exe", r"BaiduAn\.exe", r"baidusdTray\.exe"],
        service=[r"BaiduSd", r"BaiduGuard"],
    ),
    _sig(
        "baidu.browser", "百度浏览器 / 百度桌面", "百度", "bundle",
        ["浏览器", "捆绑", "推广"],
        "常被捆绑安装并推广百度全家桶。",
        uninstall=[r"百度\s*(浏览器|桌面|输入法|影音)", r"Baidu\s*(Browser|Desktop)"],
        publisher=[r"baidu", r"百度"],
        path=[r"\\Baidu\\Browser", r"\\Baidu\\BaiduDesktop"],
        process=[r"baidubrowser\.exe", r"BaiduDesktop\.exe"],
    ),
    _sig(
        "baidu.netdisk", "百度网盘（含广告/下载限速）", "百度", "disputed",
        ["网盘", "广告", "常驻"],
        "用户量大、功能正规，但含广告、常驻后台、下载限速。默认不勾选。",
        uninstall=[r"百度网盘", r"百度云管家", r"Baidu\s*Netdisk"],
        publisher=[r"baidu", r"百度"],
        path=[r"\\Baidu\\BaiduNetdisk", r"\\BaiduNetdisk"],
        process=[r"BaiduNetdisk\.exe", r"BaiduNetdiskHost\.exe"],
    ),

    # ================= 搜狗 / 输入法 =================
    _sig(
        "sogou.input", "搜狗输入法", "搜狗", "normal",
        ["输入法", "正常软件", "广告"],
        "装机量最大的输入法之一，正常打字完全不受影响。含弹窗广告与热点推广，"
        "但不会静默安装第三方垃圾软件；若它试图拉起捆绑安装包，会被实时防护拦下。"
        "默认不勾选。",
        uninstall=[r"搜狗输入法", r"Sogou\s*Input", r"搜狗\s*拼音"],
        publisher=[r"sogou", r"搜狗"],
        path=[r"\\SogouInput", r"\\Sogou\\Pinyin", r"\\Sogou"],
        process=[r"SogouImeBroker\.exe", r"SGTool\.exe", r"PinyinUp\.exe",
                 r"SogouCloud\.exe"],
        silent_allow=True,
    ),
    _sig(
        "sogou.browser", "搜狗高速浏览器 / 搜狗壁纸", "搜狗", "rogue",
        ["浏览器", "壁纸", "捆绑", "主页劫持"],
        "常被捆绑安装、劫持主页、桌面强制快捷方式。",
        uninstall=[r"搜狗\s*(高速浏览器|浏览器|壁纸|桌面)", r"Sogou\s*(Browser|Wallpaper)"],
        publisher=[r"sogou", r"搜狗"],
        path=[r"\\SogouExplorer", r"\\Sogou\\Wallpaper", r"\\Sogou\\Desktop"],
        process=[r"SogouExplorer\.exe", r"SogouWallpaper\.exe"],
    ),
    _sig(
        "sogou.misc", "搜狗系推广组件（压缩/助手等）", "搜狗", "bundle",
        ["推广", "捆绑"],
        "搜狗生态推广组件，常随输入法更新捆绑安装。",
        uninstall=[r"搜狗\s*(压缩|助手|手机助手|输入法医生)"],
        publisher=[r"sogou", r"搜狗"],
        path=[r"\\Sogou\\Zip", r"\\Sogou\\Assistant"],
    ),
    _sig(
        "input.other", "其他国产输入法推广组件", "各厂商", "bundle",
        ["输入法", "推广"],
        "部分输入法安装时捆绑推广、弹窗；如无广告需求可用系统输入法。",
        uninstall=[r"百度\s*输入法", r"QQ\s*输入法", r"讯飞\s*输入法", r"手心\s*输入法"],
        publisher=[r"baidu", r"百度", r"tencent", r"腾讯", r"iflytek", r"讯飞"],
        path=[r"\\Baidu\\BaiduPinyin", r"\\QQPinyin", r"\\iFlyInput"],
    ),

    # ================= 迅雷 / 下载 =================
    _sig(
        "xunlei.main", "迅雷 / 迅雷影音", "迅雷", "bundle",
        ["下载", "广告", "捆绑"],
        "下载工具，含大量广告、捆绑推广，且后台常驻、开机自启。",
        uninstall=[r"迅雷", r"Thunder", r"迅雷影音"],
        publisher=[r"xunlei", r"迅雷", r"thunder"],
        path=[r"\\Thunder\s*Network", r"\\Thunder", r"\\迅雷"],
        process=[r"Thunder\.exe", r"ThunderPlatform\.exe", r"XLGameBox\.exe",
                 r"XLLiveUD\.exe"],
        service=[r"Thunder", r"XLServicePlatform"],
        task=[r"Thunder", r"迅雷"],
    ),
    _sig(
        "download.tools", "各类「高速下载器」/ 下载站捆绑器", "各下载站", "rogue",
        ["下载器", "捆绑", "静默安装"],
        "所谓「高速下载器」大多只负责静默安装一堆捆绑软件，"
        "文件名常含 高速下载/安全下载/极速下载。",
        uninstall=[r"高速下载", r"安全下载器", r"极速下载器", r"软件安装管家",
                   r"下载器", r"Setup.*\d{6,}"],
        path=[r"\\HighSpeedDownload", r"\\下载器", r"\\SoftDownload"],
        process=[r".*高速下载.*\.exe", r".*下载器\.exe", r".*Downloader.*\.exe"],
    ),

    # ================= 影音 / 播放器捆绑 =================
    _sig(
        "media.baofeng", "暴风影音", "暴风", "rogue",
        ["播放器", "捆绑", "广告", "弹窗"],
        "曾因强制捆绑、弹窗广告、后台推广被大量投诉。",
        uninstall=[r"暴风影音", r"Baofeng", r"Storm\s*Player"],
        publisher=[r"baofeng", r"暴风", r"storm"],
        path=[r"\\Storm", r"\\Baofeng"],
        process=[r"Storm\.exe", r"StormPlayer\.exe", r"BaiduPlayer\.exe"],
    ),
    _sig(
        "media.pplive", "PPTV / 风行 / 快剪辑等影音捆绑", "各厂商", "bundle",
        ["影音", "捆绑", "广告"],
        "影音客户端常捆绑推广、弹窗、开机自启，且有较多后台进程。",
        uninstall=[r"PPTV", r"风行", r"快剪辑", r"爱剪辑", r"迅雷看看", r"暴风"],
        publisher=[r"pplive", r"风行", r"funshion", r"kuaijianji"],
        path=[r"\\PPTV", r"\\Funshion", r"\\kuaijianji"],
    ),

    # ================= 壁纸 / 桌面 / 小工具 =================
    _sig(
        "desktop.bird", "小鸟壁纸 / 猎豹壁纸", "小鸟 / 猎豹", "rogue",
        ["壁纸", "弹窗", "捆绑"],
        "典型桌面推广软件：强制锁屏壁纸、弹窗、静默安装、难以卸载。",
        uninstall=[r"小鸟壁纸", r"猎豹壁纸", r"Bird\s*Wallpaper", r"Lepao\s*Wallpaper"],
        path=[r"\\BirdWallpaper", r"\\小鸟壁纸", r"\\LepaoWallpaper"],
        process=[r"BirdWallpaper\.exe", r"LepaoWallpaper\.exe"],
    ),
    _sig(
        "desktop.helper", "各类桌面整理 / 护眼 / 加速球小工具", "各厂商", "rogue",
        ["桌面", "加速球", "弹窗", "推广"],
        "以「桌面整理」「护眼」「加速球」「内存优化」为名的推广软件，"
        "通常无实际价值，弹窗与捆绑较多。",
        uninstall=[r"桌面整理", r"护眼宝", r"加速球", r"内存优化", r"电脑加速",
                   r"桌面助手", r"万能工具箱"],
        path=[r"\\DesktopAssistant", r"\\DesktopMgr", r"\\护眼宝", r"\\加速球"],
        process=[r".*Desktop.*Assistant.*\.exe", r"EyeProtect.*\.exe",
                 r"Accelerator.*\.exe"],
    ),
    _sig(
        "desktop.wallpaper", "各类壁纸 / 锁屏 / 日历天气软件", "各厂商", "bundle",
        ["壁纸", "锁屏", "广告"],
        "桌面美化类软件常捆绑推广、修改锁屏与浏览器主页。",
        uninstall=[r"壁纸", r"锁屏", r"日历", r"天气", r"桌面美化"],
        path=[r"\\Wallpaper", r"\\ScreenLock", r"\\Weather"],
    ),

    # ================= Flash / PDF 等广告捆绑 =================
    _sig(
        "flash.cn", "Flash 中心 / FlashHelperService（重橙）", "重橙网络", "rogue",
        ["Flash", "广告", "弹窗", "劫持"],
        "Adobe 已于 2020 年终止支持。国内「Flash 中心」被指弹窗广告、"
        "劫持游戏页、静默更新，属典型广告软件。",
        uninstall=[r"Flash\s*(中心|Center|Player)", r"FlashHelper", r"重橙"],
        publisher=[r"flash", r"重橙", r"zheng?cheng"],
        path=[r"\\Flash\s*Center", r"\\FlashHelper", r"\\Macromedia\\Flash"],
        process=[r"FlashHelperService\.exe", r"FlashCenter.*\.exe", r"flashcenter.*\.exe"],
        service=[r"FlashHelper", r"Flash\s*Center"],
        task=[r"Flash", r"重橙"],
    ),
    _sig(
        "pdf.bundled", "捆绑型 PDF/阅读器（福昕等推广版）", "各厂商", "disputed",
        ["PDF", "推广", "捆绑"],
        "部分 PDF/阅读器免费版含推广与捆绑更新，视需要保留。",
        uninstall=[r"福昕", r"Foxit.*Reader", r"PDF.*(阅读|Reader)"],
        publisher=[r"foxit", r"福昕"],
        path=[r"\\Foxit", r"\\FoxitReader"],
    ),
    _sig(
        "rar.bundled", "快压 / 好压等捆绑压缩软件", "各厂商", "rogue",
        ["压缩", "捆绑", "右键菜单", "广告"],
        "以免费压缩为名，常捆绑推广、篡改文件关联、弹窗广告。",
        uninstall=[r"快压", r"好压", r"快压压缩", r"KuaiZip", r"HaoZip"],
        path=[r"\\KuaiZip", r"\\HaoZip", r"\\快压"],
        process=[r"KuaiZip\.exe", r"HaoZip\.exe"],
    ),

    # ================= 装机 / 系统工具类捆绑 =================
    _sig(
        "system.pe", "PE 装机工具 / 一键装机（大白菜/老毛桃/U深度等）", "各厂商", "bundle",
        ["装机", "PE", "捆绑"],
        "系统重装/PE 工具常捆绑推广软件、篡改主页。仅在做 U 盘启动盘时需要。",
        uninstall=[r"大白菜", r"老毛桃", r"U深度", r"电脑店", r"一键装机",
                   r"系统之家", r"小白.*重装"],
        path=[r"\\大白菜", r"\\老毛桃", r"\\U深度", r"\\一键装机", r"\\DaBaiCai"],
    ),
    _sig(
        "system.optimizer", "各类系统优化 / 注册表清理大师", "各厂商", "bundle",
        ["优化", "注册表", "推广"],
        "以「系统优化」「注册表清理」「电脑提速」为名的工具，多数效果存疑，"
        "且常带推广与弹窗。",
        uninstall=[r"优化大师", r"系统优化", r"注册表清理", r"电脑提速",
                   r"系统瘦身", r"垃圾清理大师"],
        path=[r"\\Optimizer", r"\\SysOptimize", r"\\优化大师"],
    ),

    # ================= 其他常见流氓/捆绑 =================
    _sig(
        "other.91", "91 助手 / 豌豆荚等手机助手", "各厂商", "bundle",
        ["手机助手", "捆绑"],
        "PC 手机助手类工具常捆绑推广、后台常驻。",
        uninstall=[r"91\s*助手", r"豌豆荚", r"手机助手"],
        path=[r"\\91Assistant", r"\\Wandoujia"],
    ),
    _sig(
        "other.helper", "各类「XX管家 / XX卫士 / XX大师」", "各厂商", "rogue",
        ["管家", "卫士", "大师", "推广"],
        "名称含「管家」「卫士」「大师」且非知名正规产品的，多为推广/捆绑软件。",
        uninstall=[r"安全卫士", r"电脑管家", r"优化大师", r"清理大师",
                   r"驱动大师", r"系统管家"],
        path=[r"\\PCManager", r"\\Guard", r"\\Master"],
        generic=True,
    ),

    # ================= 更多国产流氓/捆绑家族 =================
    _sig(
        "uc.browser", "UC浏览器电脑版", "UC / 阿里", "bundle",
        ["浏览器", "捆绑", "推广"],
        "常被捆绑安装、抢占默认浏览器并推送新闻导航。",
        uninstall=[r"UC\s*浏览器", r"UC\s*Browser"],
        publisher=[r"uc", r"ucweb", r"优视"],
        path=[r"\\UCBrowser", r"\\UC\s*Browser"],
        process=[r"UCBrowser\.exe", r"UCBrowserHelper\.exe", r"UCMiniSvr\.exe"],
    ),
    _sig(
        "qihoo.driver", "360驱动大师 / 360 硬件大师", "360（奇虎）", "bundle",
        ["驱动", "硬件", "捆绑", "推广"],
        "驱动类工具，安装与扫描过程推广较多。",
        uninstall=[r"360\s*(驱动大师|硬件大师|系统急救箱)"],
        publisher=[r"qihoo", r"奇虎", r"360"],
        path=[r"\\360Drivers", r"\\360\s*Hardware"],
    ),
    _sig(
        "rising.main", "瑞星杀毒 / 瑞星安全助手", "瑞星", "bundle",
        ["杀毒", "安全助手", "推广"],
        "老牌杀软，现以推广与捆绑为主，装机量已很低但常随下载包进入系统。",
        uninstall=[r"瑞星", r"Rising\s*(Antivirus|Security|PC)"],
        publisher=[r"rising", r"瑞星"],
        path=[r"\\Rising", r"\\瑞星"],
        process=[r"Ravmond\.exe", r"RavTask\.exe", r"rsagent\.exe"],
        service=[r"Rising", r"RsRavMon"],
    ),
    _sig(
        "jiangmin.main", "江民杀毒", "江民", "bundle",
        ["杀毒", "推广"],
        "老牌杀软，常随第三方下载包捆绑安装。",
        uninstall=[r"江民", r"JiangMin"],
        publisher=[r"jiangmin", r"江民"],
        path=[r"\\JiangMin", r"\\江民"],
        process=[r"KVMonXP\.exe", r"Kvoll\.exe", r"JiangMin.*\.exe"],
    ),
    _sig(
        "yisou.helper", "亿赛通 / 各类企业管控客户端推广组件", "各厂商", "bundle",
        ["管控", "推广", "常驻"],
        "部分企业/网吧管控客户端会静默常驻并推送推广，视环境判断。",
        uninstall=[r"亿赛通", r"企业管控"],
        path=[r"\\ESafeNet", r"\\亿赛通"],
    ),
    _sig(
        "mobile.assistant", "各类手机助手 / 刷机大师 / 安卓模拟器推广版", "各厂商", "bundle",
        ["手机助手", "模拟器", "捆绑", "推广"],
        "PC 端手机助手、刷机工具、模拟器常捆绑推广软件与游戏盒子。",
        uninstall=[r"刷机大师", r"卓大师", r"安卓模拟器", r"夜神模拟器",
                   r"逍遥模拟器", r"雷电模拟器", r"MuMu模拟器", r"蓝叠"],
        path=[r"\\Shuame", r"\\Nox", r"\\LDPlayer", r"\\BlueStacks", r"\\MuMu"],
        process=[r"shuame.*\.exe", r"Nox\.exe", r"dnplayer\.exe", r"HD-Player\.exe"],
    ),
    _sig(
        "game.box", "各类游戏盒子 / 手游助手 / 游戏大厅", "各厂商", "bundle",
        ["游戏盒子", "推广", "弹窗"],
        "游戏盒子类软件普遍弹窗推广、捆绑其他游戏平台、开机自启。",
        uninstall=[r"游戏盒子", r"游戏大厅", r"手游助手", r"游戏管家",
                   r"XX游戏平台", r"页游"],
        path=[r"\\GameBox", r"\\GameHall", r"\\游戏盒子"],
        process=[r".*GameBox.*\.exe", r".*GameHall.*\.exe", r".*游戏大厅.*\.exe"],
    ),
    _sig(
        "misc.cleaner", "各类「C盘瘦身 / 一键清理 / 大文件清理」工具", "各厂商", "rogue",
        ["清理", "瘦身", "推广", "弹窗"],
        "以「C盘瘦身」「一键清理」为名的工具多为推广软件，效果存疑且弹窗多。",
        uninstall=[r"C盘瘦身", r"一键清理", r"大文件清理", r"磁盘瘦身",
                   r"电脑清理大师", r"垃圾清理"],
        path=[r"\\DiskClean", r"\\PCClean", r"\\一键清理"],
        process=[r".*CleanMaster.*\.exe", r".*DiskClean.*\.exe"],
    ),
    _sig(
        "misc.driver", "各类「一键装驱动 / 驱动管家 / 显卡驱动大师」", "各厂商", "bundle",
        ["驱动", "一键装机", "捆绑", "推广"],
        "非官方的驱动安装工具，普遍捆绑推广、静默安装软件。",
        uninstall=[r"一键装驱动", r"驱动管家", r"显卡驱动大师", r"驱动安装大师",
                   r"驱动小助手"],
        path=[r"\\DriverMaster", r"\\DriverHelper", r"\\驱动管家"],
    ),
    _sig(
        "misc.video", "各类聚合影视 / 影视大全 / 电视直播客户端", "各厂商", "bundle",
        ["影视", "直播", "广告", "捆绑"],
        "聚合影视与电视直播客户端普遍含大量广告、弹窗与后台推广。",
        uninstall=[r"影视大全", r"电视直播", r"影视盒子", r"追剧神器", r"麻花影视",
                   r"月亮播放器", r"影视工厂"],
        path=[r"\\VideoBox", r"\\影视大全", r"\\TVLive"],
        process=[r".*影视.*\.exe", r".*TVLive.*\.exe"],
    ),
    _sig(
        "misc.ebook", "各类小说阅读器 / 漫画阅读器推广版", "各厂商", "bundle",
        ["阅读器", "广告", "捆绑"],
        "小说/漫画阅读器推广版常捆绑桌面软件、弹窗广告。",
        uninstall=[r"小说阅读器", r"漫画阅读器", r"书旗小说", r"追书神器"],
        path=[r"\\NovelReader", r"\\小说阅读"],
    ),
    _sig(
        "misc.wifi", "各类 WiFi 万能钥匙 / 网络加速器 PC 版", "各厂商", "bundle",
        ["WiFi", "加速器", "捆绑", "广告"],
        "PC 版 WiFi 工具与网络加速器普遍捆绑推广、后台常驻并推送广告。",
        uninstall=[r"WiFi\s*万能钥匙", r"WIFI万能钥匙", r"网络加速器",
                   r"迅游加速器", r"网游加速器"],
        path=[r"\\WiFiMaster", r"\\WifiKey", r"\\Accelerator"],
        process=[r"WifiMaster.*\.exe", r".*Accelerator.*\.exe"],
    ),
    _sig(
        "misc.toolbox", "各类「万能工具箱 / 装机工具箱 / 电脑维修工具」", "各厂商", "rogue",
        ["工具箱", "装机", "推广", "捆绑"],
        "所谓万能工具箱/电脑维修工具多为推广聚合器，安装后弹窗与捆绑较多。",
        uninstall=[r"万能工具箱", r"装机工具箱", r"电脑维修", r"系统工具箱",
                   r"绿色工具箱"],
        path=[r"\\ToolBox", r"\\万能工具箱", r"\\SysToolBox"],
    ),
    _sig(
        "misc.pdf", "各类「PDF 转换 / 文档转换」推广版", "各厂商", "bundle",
        ["PDF", "转换", "推广", "捆绑"],
        "免费 PDF 转换工具推广版常捆绑安装、限制使用并弹窗推广。",
        uninstall=[r"PDF转换", r"文档转换", r"PDF大师", r"迅捷PDF", r"万兴PDF"],
        path=[r"\\PDFConvert", r"\\PDFMaster", r"\\迅捷PDF"],
    ),
    _sig(
        "misc.data", "各类「数据恢复 / 文件恢复」推广版", "各厂商", "bundle",
        ["数据恢复", "推广", "捆绑"],
        "数据恢复工具推广版常先骗扫描再收费，并捆绑其他软件。",
        uninstall=[r"数据恢复", r"文件恢复", r"EasyRecovery", r"FinalData"],
        path=[r"\\DataRecovery", r"\\FileRecovery", r"\\数据恢复"],
    ),
    _sig(
        "misc.recorder", "各类「录屏 / 直播录制」推广版", "各厂商", "bundle",
        ["录屏", "直播", "推广", "捆绑"],
        "录屏/直播工具推广版常捆绑安装、带水印并推送推广。",
        uninstall=[r"录屏大师", r"屏幕录制", r"直播录制", r"录屏软件"],
        path=[r"\\ScreenRecorder", r"\\录屏大师"],
    ),
    _sig(
        "misc.shortcut", "各类「桌面图标管理 / 快捷方式修复」小工具", "各厂商", "rogue",
        ["桌面", "图标", "推广", "弹窗"],
        "以修复桌面图标、快捷方式为名的工具多为推广软件。",
        uninstall=[r"桌面图标", r"快捷方式修复", r"图标管理", r"桌面管理大师"],
        path=[r"\\DesktopIcon", r"\\IconManager"],
    ),
    _sig(
        "misc.thermal", "各类「CPU降温 / 风扇控制 / 温度监控」推广工具", "各厂商", "bundle",
        ["温度", "风扇", "推广", "捆绑"],
        "非知名品牌的温度/风扇控制工具常捆绑推广、后台常驻。",
        uninstall=[r"CPU降温", r"风扇控制", r"温度监控大师", r"电脑降温"],
        path=[r"\\CoolerMaster", r"\\FanControl", r"\\降温"],
    ),
    _sig(
        "baidu.other", "百度系推广组件（百度输入法/百度HI/百度影音等）", "百度", "bundle",
        ["推广", "捆绑"],
        "百度系其他推广组件，常被捆绑安装。",
        uninstall=[r"百度\s*(输入法|HI|影音|贴吧|地图桌面|网盘客户端|手机助手)"],
        publisher=[r"baidu", r"百度"],
        path=[r"\\Baidu\\BaiduPinyin", r"\\Baidu\\BaiduHi", r"\\Baidu\\BaiduPlayer"],
    ),
    _sig(
        "kingsoft.misc2", "金山系推广组件（金山PDF/金山词霸推广版）", "金山 / 猎豹", "bundle",
        ["推广", "捆绑"],
        "金山系推广组件，多随 WPS 或毒霸静默安装。",
        uninstall=[r"金山\s*(PDF|词霸|快盘|保险箱)", r"Kingsoft\s*(PDF|PowerWord)"],
        publisher=[r"kingsoft", r"金山"],
        path=[r"\\Kingsoft\\PDF", r"\\Kingsoft\\PowerWord"],
    ),
    _sig(
        "tianqing", "天擎/网维大师/各类网吧与管控客户端", "各厂商", "bundle",
        ["管控", "网吧", "常驻"],
        "网吧与终端管控客户端会强制常驻并推送内容，视环境判断。",
        uninstall=[r"网维大师", r"万象网管", r"天擎", r"终端管控"],
        path=[r"\\Netbars", r"\\网维大师", r"\\万象"],
    ),

    # ================= 软件中心 / 应用商店类 =================
    _sig(
        "appstore.pc", "各类 PC 软件中心 / 应用商店（推广型）", "各厂商", "bundle",
        ["软件中心", "应用商店", "推广", "捆绑"],
        "预装或捆绑的软件中心/应用商店，以推广软件与广告为主要目的，常静默常驻。",
        uninstall=[r"软件中心", r"应用商店", r"软件管家", r"软件宝库",
                   r"联想应用商店", r"华为应用市场", r"小米应用商店"],
        path=[r"\\AppStore", r"\\软件中心", r"\\SoftCenter", r"\\Lenovo.*Store"],
        process=[r".*AppStore.*\.exe", r".*SoftCenter.*\.exe",
                 r".*软件中心.*\.exe", r"LenovoAppStore.*\.exe"],
    ),
    _sig(
        "lenovo.tools", "联想电脑管家 / 联想服务推广组件", "联想", "bundle",
        ["管家", "预装", "推广"],
        "联想预装的电脑管家与服务组件，弹窗推广与后台常驻较多。",
        uninstall=[r"联想.*(电脑管家|服务|管家|应用商店)", r"Lenovo.*(Manager|Service)"],
        publisher=[r"lenovo", r"联想"],
        path=[r"\\Lenovo\\Manager", r"\\LenovoPCManager", r"\\Lenovo\\AppStore"],
        process=[r"LenovoPCManager.*\.exe", r"LenovoService.*\.exe"],
    ),
    _sig(
        "asus.tools", "华硕预装推广组件（MyASUS/Armoury 推广）", "华硕", "bundle",
        ["预装", "推广", "常驻"],
        "品牌机预装推广组件，常驻后台并推送内容。",
        uninstall=[r"MyASUS", r"华硕.*(管家|中心)", r"ASUS.*(Manager|Gaming)"],
        publisher=[r"asus", r"华硕"],
        path=[r"\\ASUS\\", r"\\MyASUS"],
    ),
    _sig(
        "hp.dell.tools", "惠普/戴尔预装推广组件", "惠普 / 戴尔", "bundle",
        ["预装", "推广", "常驻"],
        "品牌机预装的推广与支持组件，弹窗推送与后台常驻。",
        uninstall=[r"HP.*(Support|Assistant|Jump)", r"Dell.*(Support|Assistant)",
                   r"惠普.*(助手|支持)", r"戴尔.*(助手|支持)"],
        publisher=[r"hp inc", r"hewlett", r"dell", r"惠普", r"戴尔"],
        path=[r"\\HP\\", r"\\Dell\\", r"\\HPSupport"],
    ),

    # ================= 壁纸 / 桌面美化 =================
    _sig(
        "wallpaper.extra", "各类第三方壁纸/动态壁纸软件", "各厂商", "bundle",
        ["壁纸", "动态壁纸", "广告", "捆绑"],
        "第三方壁纸软件普遍含广告、弹窗、锁屏劫持，并捆绑推广其他软件。",
        uninstall=[r"千千壁纸", r"壁纸精灵", r"淘壁纸", r"火萤壁纸", r"元气桌面",
                   r"壁纸社", r"彼岸壁纸", r"360壁纸", r"猎豹壁纸", r"小鸟壁纸",
                   r"Wallpaper Engine.*免费", r"动态壁纸"],
        path=[r"\\Wallpaper", r"\\壁纸", r"\\LiveWallpaper", r"\\HuoyingWallpaper"],
        process=[r".*Wallpaper.*\.exe", r".*壁纸.*\.exe", r"LiveWallpaper.*\.exe"],
    ),
    _sig(
        "desktop.beautify", "桌面美化 / 图标 / 主题类工具", "各厂商", "bundle",
        ["美化", "桌面", "推广", "弹窗"],
        "桌面美化、图标包、主题工具多为推广软件，弹窗与捆绑较多。",
        uninstall=[r"美化大师", r"桌面美化", r"图标包", r"主题大师", r"格子桌面",
                   r"萌宠桌面", r"桌面宠物"],
        path=[r"\\DesktopBeautify", r"\\美化", r"\\ThemeMaster", r"\\DesktopPet"],
    ),
    _sig(
        "calendar.desktop", "桌面天气 / 万年历 / 日历类组件", "各厂商", "bundle",
        ["天气", "日历", "弹窗", "推广"],
        "桌面天气、万年历、日历组件普遍弹窗推广、捆绑安装。",
        uninstall=[r"桌面天气", r"万年历", r"桌面日历", r"365日历", r"天气王"],
        path=[r"\\Weather", r"\\Calendar", r"\\天气", r"\\万年历"],
    ),

    # ================= 广告 / 弹窗 / 购物推广 =================
    _sig(
        "ads.shopping", "各类购物桌面 / 淘宝京东拼多多桌面组件", "各厂商", "bundle",
        ["购物", "广告", "弹窗", "常驻"],
        "购物类桌面组件以弹窗推送广告与优惠券为主，长期后台常驻。",
        uninstall=[r"淘宝桌面", r"京东桌面", r"拼多多桌面", r"天猫桌面",
                   r"购物助手", r"优惠券助手"],
        path=[r"\\TaobaoDesktop", r"\\JingdongDesktop", r"\\PddDesktop", r"\\ShopHelper"],
    ),
    _sig(
        "ads.news", "各类资讯弹窗 / 热点推送 / 头条桌面", "各厂商", "rogue",
        ["资讯", "弹窗", "推送", "广告"],
        "以热点资讯、头条推送为名，实际为强制弹窗广告来源。",
        uninstall=[r"热点资讯", r"头条桌面", r"资讯弹窗", r"新闻弹窗", r"今日热点",
                   r"资讯助手", r"热点推送"],
        path=[r"\\NewsPop", r"\\HotNews", r"\\资讯", r"\\Toutiao"],
        process=[r".*NewsPop.*\.exe", r".*HotNews.*\.exe", r".*资讯.*\.exe"],
    ),
    _sig(
        "ads.nav", "各类网址导航 / 主页劫持组件", "各厂商", "rogue",
        ["导航", "主页劫持", "广告"],
        "强制修改浏览器主页与搜索引擎的导航类插件。",
        uninstall=[r"网址导航", r"hao123", r"360导航", r"搜狗导航", r"主页守护",
                   r"导航卫士"],
        path=[r"\\hao123", r"\\Navigation", r"\\导航"],
    ),

    # ================= 影音 / 直播 / 音乐 =================
    _sig(
        "music.bundled", "第三方音乐客户端（含广告/推广版）", "各厂商", "bundle",
        ["音乐", "广告", "推广"],
        "第三方音乐客户端普遍含广告弹窗、捆绑推广与后台常驻。",
        uninstall=[r"酷狗音乐", r"酷我音乐", r"虾米音乐", r"千千静听",
                   r"咪咕音乐", r"5sing"],
        path=[r"\\Kugou", r"\\Kuwo", r"\\Xiami"],
        process=[r"KuGou\.exe", r"kwmusic\.exe", r"KuwoMusic\.exe"],
    ),
    _sig(
        "video.client", "第三方视频客户端（含广告/推广版）", "各厂商", "bundle",
        ["视频", "广告", "推广"],
        "第三方视频客户端普遍含开屏广告、弹窗推广与捆绑安装。",
        uninstall=[r"爱奇艺", r"优酷", r"腾讯视频", r"搜狐视频", r"乐视视频",
                   r"芒果TV", r"土豆视频", r"PPS"],
        path=[r"\\iqiyi", r"\\Youku", r"\\QQLive", r"\\SohuVideo", r"\\Letv"],
        process=[r"Qiyi.*\.exe", r"Youku.*\.exe", r"QQLive\.exe", r"SoHuVideo.*\.exe"],
    ),
    _sig(
        "live.stream", "直播客户端 / 语音房（含推广版）", "各厂商", "bundle",
        ["直播", "语音", "推广", "弹窗"],
        "直播与语音房客户端弹窗推广、后台常驻较多。",
        uninstall=[r"虎牙直播", r"斗鱼直播", r"YY语音", r"六间房", r"企鹅直播",
                   r"抖音直播伴侣", r"快手直播伴侣"],
        path=[r"\\Huya", r"\\Douyu", r"\\YY", r"\\LivePartner"],
        process=[r"Huya.*\.exe", r"Douyu.*\.exe", r"YY\.exe", r"LivePartner.*\.exe"],
    ),
    _sig(
        "short.video.pc", "短视频 / 社交桌面客户端推广组件", "各厂商", "bundle",
        ["短视频", "桌面", "推广"],
        "短视频与社交平台的桌面客户端常捆绑推广与后台常驻。",
        uninstall=[r"抖音桌面", r"快手桌面", r"小红书桌面", r"微博桌面"],
        path=[r"\\Douyin", r"\\Kuaishou", r"\\Xiaohongshu", r"\\Weibo"],
    ),

    # ================= 网盘 / 传输 =================
    _sig(
        "cloud.disk", "第三方网盘客户端（含广告/限速推广版）", "各厂商", "disputed",
        ["网盘", "广告", "限速", "常驻"],
        "第三方网盘客户端含广告与限速，且有正常使用需求，默认不勾选。",
        uninstall=[r"115网盘", r"腾讯微云", r"阿里云盘", r"城通网盘", r"蓝奏云",
                   r"奶牛快传"],
        publisher=[r"115", r"weiyun", r"aliyun", r"ctfile"],
        path=[r"\\115", r"\\Weiyun", r"\\AliyunDrive", r"\\CTFile"],
        process=[r"115\.exe", r"Weiyun.*\.exe", r"aDrive\.exe"],
    ),

    # ================= 游戏盒子 / 加速器 / 平台 =================
    _sig(
        "game.accelerator", "游戏加速器（含推广/捆绑版）", "各厂商", "bundle",
        ["加速器", "游戏", "推广", "捆绑"],
        "游戏加速器普遍含推广弹窗、捆绑安装与后台常驻。",
        uninstall=[r"迅游加速器", r"网易UU加速器", r"奇游加速器", r"雷神加速器",
                   r"熊猫加速器", r"网游加速器", r"游戏加速器"],
        path=[r"\\Xunyou", r"\\UU", r"\\Qiyou", r"\\Leigod"],
        process=[r"xunyou.*\.exe", r"uu\.exe", r"Qiyou.*\.exe", r"leigod.*\.exe"],
    ),
    _sig(
        "game.tool", "游戏加加 / 游戏优化 / 画质增强类工具", "各厂商", "bundle",
        ["游戏", "优化", "推广", "弹窗"],
        "游戏优化与画质工具常含广告与捆绑，且覆盖层影响游戏性能。",
        uninstall=[r"游戏加加", r"游戏优化大师", r"画质增强", r"帧数优化",
                   r"游戏加速大师"],
        path=[r"\\GamePP", r"\\GameOptimize", r"\\游戏加加"],
        process=[r"GamePP.*\.exe", r".*GameOptimize.*\.exe"],
    ),
    _sig(
        "game.wechat_box", "各类微信小游戏盒子 / 页游盒子", "各厂商", "rogue",
        ["游戏盒", "页游", "推广", "弹窗"],
        "微信小游戏与页游盒子为典型推广软件，弹窗与静默安装较多。",
        uninstall=[r"小游戏盒", r"页游盒", r"游戏大厅", r"微信小游戏"],
        path=[r"\\MiniGame", r"\\PageGame", r"\\游戏盒"],
    ),

    # ================= 阅读 / 资讯客户端 =================
    _sig(
        "reader.pc", "第三方小说/漫画阅读器（推广版）", "各厂商", "bundle",
        ["阅读器", "广告", "推广"],
        "第三方阅读器推广版含广告与捆绑安装。",
        uninstall=[r"起点读书", r"掌阅", r"QQ阅读", r"番茄小说", r"七猫小说",
                   r"书旗小说"],
        path=[r"\\Qidian", r"\\iReader", r"\\QQReader", r"\\Fanqie"],
    ),

    # ================= 系统工具 / 装机 / 优化 =================
    _sig(
        "system.reinstall", "一键重装 / 系统之家 / 装机工具推广版", "各厂商", "rogue",
        ["装机", "重装", "推广", "捆绑"],
        "一键重装与装机工具推广版普遍捆绑软件、篡改主页。",
        uninstall=[r"一键重装", r"系统之家", r"重装大师", r"装机大师", r"小白一键重装",
                   r"微PE推广版", r"系统重装"],
        path=[r"\\Reinstall", r"\\系统之家", r"\\Zhuangji", r"\\一键重装"],
    ),
    _sig(
        "system.magic", "软媒魔方 / 系统优化大师类工具", "各厂商", "bundle",
        ["优化", "魔方", "推广", "捆绑"],
        "系统优化类工具普遍含推广、捆绑与主页劫持。",
        uninstall=[r"软媒魔方", r"优化大师", r"超级兔子", r"电脑优化",
                   r"系统优化大师", r"魔方优化"],
        path=[r"\\Ruanmei", r"\\MagicBox", r"\\优化大师"],
        process=[r"PCMaster\.exe", r"ruanmei.*\.exe", r"MagicBox.*\.exe"],
    ),
    _sig(
        "system.boot", "开机加速 / 启动项管理 / 电脑提速类工具", "各厂商", "bundle",
        ["提速", "启动项", "推广", "弹窗"],
        "开机加速与提速类工具多为推广软件，效果存疑且弹窗多。",
        uninstall=[r"开机加速", r"启动项管理", r"电脑提速", r"开机优化",
                   r"开机助手"],
        path=[r"\\BootSpeed", r"\\StartupMgr", r"\\提速"],
    ),
    _sig(
        "system.repair", "系统修复 / 蓝屏修复 / DLL 修复类工具", "各厂商", "rogue",
        ["修复", "推广", "诈骗"],
        "系统修复类工具常先虚构问题再诱导付费，并捆绑推广软件。",
        uninstall=[r"系统修复", r"蓝屏修复", r"DLL修复", r"系统医生", r"电脑医生"],
        path=[r"\\SystemRepair", r"\\DllFix", r"\\系统医生"],
    ),

    # ================= 手机助手 / 模拟器 / 投屏 =================
    _sig(
        "phone.mirror", "投屏 / 手机管家 / 数据传输类工具", "各厂商", "bundle",
        ["投屏", "手机助手", "推广", "捆绑"],
        "投屏与手机管理工具常捆绑推广软件、后台常驻。",
        uninstall=[r"投屏", r"手机管家", r"数据传输", r"爱思助手", r"PP助手",
                   r"快牙", r"茄子快传"],
        path=[r"\\ScreenMirror", r"\\PhoneManager", r"\\i4Tools", r"\\PPAssistant"],
    ),

    # ================= 图片 / 视频处理推广版 =================
    _sig(
        "image.edit", "图片处理推广版（含捆绑）", "各厂商", "bundle",
        ["图片", "处理", "推广", "捆绑"],
        "免费图片处理工具推广版常捆绑安装与弹窗推广。",
        uninstall=[r"美图秀秀", r"光影魔术手", r"图片编辑器", r"抠图大师",
                   r"证件照"],
        path=[r"\\Meitu", r"\\PhotoEditor", r"\\抠图"],
    ),
    _sig(
        "video.convert", "视频转换 / 下载推广版", "各厂商", "bundle",
        ["视频", "转换", "下载", "推广"],
        "视频转换与视频下载工具推广版常捆绑安装与广告弹窗。",
        uninstall=[r"格式工厂", r"视频转换", r"视频下载", r"全能视频",
                   r"维棠", r"硕鼠"],
        path=[r"\\FormatFactory", r"\\VideoConvert", r"\\VideoDownload"],
    ),

    # ================= 百度 / 搜狗 / 腾讯系推广组件（补全） =================
    _sig(
        "baidu.tools", "百度系工具箱 / 百度桌面组件", "百度", "bundle",
        ["百度", "推广", "捆绑"],
        "百度系工具箱与桌面组件常被捆绑安装。",
        uninstall=[r"百度工具", r"百度桌面", r"百度锁屏", r"百度壁纸"],
        publisher=[r"baidu", r"百度"],
        path=[r"\\Baidu\\BaiduTools", r"\\Baidu\\Desktop"],
    ),
    _sig(
        "tencent.tools", "腾讯系推广组件（腾讯桌面/视频/新闻弹窗）", "腾讯", "bundle",
        ["腾讯", "推广", "弹窗"],
        "腾讯系桌面与资讯组件常弹窗推送、后台常驻。",
        uninstall=[r"腾讯桌面", r"腾讯新闻", r"腾讯视频桌面", r"腾讯管家桌面组件"],
        publisher=[r"tencent", r"腾讯"],
        path=[r"\\Tencent\\Desktop", r"\\Tencent\\News", r"\\Tencent\\Video"],
    ),

    # ================= 输入法补充（推广组件） =================
    _sig(
        "input.ime_extra", "第三方输入法推广组件（皮肤/热搜/资讯）", "各厂商", "bundle",
        ["输入法", "推广", "弹窗"],
        "输入法自带的皮肤商城、热搜、资讯组件多为推广入口。",
        uninstall=[r"输入法皮肤", r"输入法热搜", r"输入法资讯", r"输入法助手"],
        path=[r"\\InputSkin", r"\\InputHot", r"\\输入法助手"],
    ),
]


def all_ids() -> list[str]:
    return [s["id"] for s in SIGNATURES]


def by_id(sid: str) -> dict[str, Any] | None:
    for s in SIGNATURES:
        if s["id"] == sid:
            return s
    return None


def default_selected(risk: str) -> bool:
    """只默认勾选流氓/捆绑；争议与正常软件都不勾选。"""
    return risk in ("rogue", "bundle")
