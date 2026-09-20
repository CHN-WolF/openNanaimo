# openNanaimo

针对韩国飞行射击游戏 **Nanaimo** 的客户端行为研究项目，包含 Windows 启动器、本地协议适配器源码及工程知识库。

## 免责声明

1. 本仓库是针对韩国飞行射击游戏 **Nanaimo** 的客户端行为分析项目，用于本地运行并研究其行为逻辑，纯属个人研究所用，禁止任何盈利用途。
2. 本仓库不传播原始客户端的可执行文件、动态库与数据包；仅包含由本地资源派生的目录数据（`gui_launcher/data/*.json`）与图标预览图集，供启动器界面与本地研究使用。
3. 本仓库完全非盈利，谢绝任何打赏和任何形式的经济、利益赠与。
4. 所有内容完全从官方公开发布的客户端安装脚本内、以及互联网上公开的资源中，通过纯粹的本地测试独立获得，与该游戏任何原始开发者、组织不存在任何交集。

## 分析范围

- **已分析内容**：基础装备、商城购物、地宫、秘密地宫玩法。
- **未分析内容**：社交相关，例如竞技场、娱乐室、人际关系等。
- **需自行patch客户端内容**：5村地宫7入口等。

已分析内容包含不同深度的静态分析、协议实现和运行观察，不代表所有功能均已完整实现。具体进展见 [知识库](knowledge/知识库索引.md)。

## 环境与准备

- Windows、Windows PowerShell 和 .NET WinForms。
- Python 3.11 或兼容版本；适配器构建使用兼容的 TinyCC 工具链。
- 本地运行需要自行准备合法取得、与研究基线匹配的客户端及配套资源。启动器读取根目录的 `game.exe`，并校验文件完整性；所需文件与校验方法见 [运行依赖](docs/运行依赖.md)。
- 受游戏年代限制，本适配器默认仅支持在 **Windows XP** 环境下适配相应的 `game.exe`。若使用 **Windows 10** 等现代操作系统，需自行改动客户端，本仓库不提供这方面的信息。

源码构建与本地游戏运行是两个独立步骤。客户端、GUI 数据及资源依赖见 [运行依赖](docs/运行依赖.md)。

本地运行游戏不需要先执行下文的构建命令：适配器部署完成后，直接双击仓库根目录的 `start_nanaimo_launcher.bat` 启动图形界面即可，见 [GUI 启动方式](#gui-启动方式)。

### 自行安装 Python 与 TinyCC

Python、TinyCC 及它们的第三方二进制、标准库和头文件不纳入开源仓库；请从项目官方入口自行下载，并保留所下载发行包的许可证材料。

- **Python**：[Python 官方 Windows 下载页](https://www.python.org/downloads/windows/)。本项目原工具基线为 Python **3.11.9（64 位）**；安装 Python 3.11 或兼容版本，并确保命令行中的 `python` 指向该解释器。常规源码检查与 GUI 库存后端不需要把 Python 复制进仓库；完整校验脚本的路径要求见下表。
- **TinyCC（TCC）**：[TinyCC 官方项目页](https://bellard.org/tcc/)，从该页进入 Windows 发行包入口。本项目原工具基线为 **TCC 0.9.27，i386 Windows 默认目标**；不要仅按宿主系统为 64 位就替换为不同的编译目标。保留完整工具链目录（包括 `include`、`lib` 和许可证），可在仓库外安装，再使用下文的 `-TccPath` 指定 `tcc.exe`。
- 构建脚本默认查找 `tools/tcc/tcc.exe`；若使用该默认位置，请自行放置完整工具链，该目录已加入 Git 忽略规则。部分本地协议测试也固定读取此位置。

以上版本是本地已观察的工具基线，不是“最新版本”推荐。构建脚本校验输出字节与哈希；换用不同编译器版本或目标时，不保证与现有构建基线一致。

### 外部工具对各入口的影响

| 入口 | 工具要求 |
|---|---|
| `python -B scripts/verify_package.py --source-only` | 使用命令行 Python；不需要 TCC、客户端或游戏资源 |
| GUI 库存后端 | 优先使用本地 `tools/python/python.exe`，不存在时使用 PATH 中的 `python` |
| `scripts/build_adapter.ps1` | 默认查找 `tools/tcc/tcc.exe`；工具链安装在其他位置时必须传入 `-TccPath` |
| `scripts/test_native_ui_protocol.py` | 当前固定查找 `tools/tcc/tcc.exe`，不继承构建脚本的 `-TccPath`；未准备该工具链时，运行整个测试集会报错，而不是全部跳过 |
| `scripts/verify_package.ps1` | 当前固定使用 `tools/python/python.exe`；仅安装 PATH 中的 Python 不满足此脚本的要求，且完整校验还需要客户端、资源和已构建适配器 |

第三方工具是使用者本地准备的依赖，不随仓库分发。自行下载工具不代表其版本、目标架构或输出哈希已经通过本项目验证。

## 构建与校验

在仓库根目录执行源码检查；下一条构建命令仅适用于已自行准备默认位置 TCC 的情况：

```powershell
python -B scripts/verify_package.py --source-only
# 需先准备 tools/tcc/tcc.exe 及配套工具链：
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build_adapter.ps1 -KeepOutputs
```

如将 TinyCC 安装在仓库外，可通过 `-TccPath` 指定编译器；请将下面的示例路径替换为实际下载位置：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build_adapter.ps1 -KeepOutputs -TccPath '..\toolchains\tcc\tcc.exe'
```

`-KeepOutputs` 保留 `build/nanaimo_adapter.exe` 与 `build/nanaimo_adapter_testports.exe`；不加该参数时只做临时重建校验。构建脚本不会自动部署产物。正式适配器使用 `adapter/nanaimo_adapter.exe`，测试端口版本用于隔离测试。

详细步骤、无需 TCC 的部分测试及完整测试前提见 [构建与验证](docs/构建与验证.md)；目录准备方式见 [运行依赖](docs/运行依赖.md#python-与-tinycc-的准备方式)。

## 启动器

图形界面启动器是运行游戏的标准入口。它按正确顺序完成保存配置、校验客户端、重启本地适配器、注册角色资料和启动客户端；不需要手工启动适配器、手工注册资料或改写连接配置。

### GUI 启动方式

在运行依赖齐备并部署适配器后：

1. 双击仓库根目录的 `start_nanaimo_launcher.bat`；
2. 在 **启动配置** 页确认用户名、角色、宠物和装扮，需要时在 **数值与道具** 和库存页调整；
3. 点击 **保存并进入游戏**；
4. 客户端启动后，按下方弹框表依次选择 **是 → 否 → 是**。

`start_nanaimo_launcher.bat` 会先把工作目录切到仓库根，再用 `-NoProfile -ExecutionPolicy Bypass -STA` 运行 `gui_launcher/nanaimo_launcher.ps1`；请从仓库根目录双击，不要单独拷贝脚本到别处运行。

点击 **保存并进入游戏** 后，启动器会依次执行：

| 顺序 | 动作 |
|---|---|
| 1 | 停止已识别的旧本地适配器进程 |
| 2 | 保存角色资料、数值、技能和五类库存 |
| 3 | 校验客户端、村庄包、Super-Boss stage 和资源补丁 |
| 4 | 生成 `StateOption/gamestartoption.ini`，重启本地适配器 |
| 5 | 通过 TCP 11999 注册角色资料，要求适配器返回 `OK` |
| 6 | 停止旧的 `game.exe`，用固定参数启动根目录 `game.exe` |

其中任何一步失败都会弹出错误框并中止，不会带着旧配置启动客户端。

进入游戏时会依次出现三个弹框，请按下表选择：

| 顺序 | 弹框内容 | 选择 |
|---|---|---|
| 1 | 是否窗口游玩（全屏需要其他图像dll，本仓库不提供） | **是** |
| 2 | 是否关闭游戏内声音 | **否**（保留声音） |
| 3 | 是否开启游戏内 log 界面 | **是** |

即依次选择 **是 → 否 → 是**。

### 启动模式

GUI 只使用一个固定模式：**Network (`-q`) + `127.0.0.1`**，连接本机适配器。启动器不显示连接方式、地址和启动参数，也不提供选择，所以不需要手工配置连接；只要启动器在运行，客户端就连到本机适配器。

| 项 | 值 |
|---|---|
| 客户端连接模式 | 固定 Network（`-q`） |
| 适配器地址 | `127.0.0.1`（本机回环） |
| 适配器端口 | 11005 登录、11999 资料注册、12050 游戏前端 |
| 启动配置生成源 | `gui_launcher/launch_modes/gamestartoption.network.ini` |

`gui_launcher/launch_modes/gamestartoption.standalone.ini` 和 `Stand_Alone` 构造器用于协议研究，不是 GUI 选项；启动器会拒绝 `standalone` 模式和非 `127.0.0.1` 地址。完整链路见 [启动链与源码索引](docs/启动流程与源码索引.md)。

### 无界面模式

`start_nanaimo_launcher.bat` 会把附加参数透传给 `nanaimo_launcher.ps1`。下表的开关用于校验、预览和自测：不打开 GUI、不启动游戏，也不是运行游戏的方式。

| 开关 | 用途 |
|---|---|
| `-ValidateOnly` | 校验目录数据、预览资源、适配器基线和固定启动参数；`scripts/verify_package.ps1` 使用该入口 |
| `-PreviewOnly` | 输出「本次启动详情」文本后退出 |
| `-SelfTestProfileIO` | 角色资料与库存写入、读回自测 |
| `-SelfTestInventoryIO` | 库存管理后端自测 |
| `-SelfTestLaunchModes` | 固定 `127.0.0.1` 模式与非法模式拒绝自测 |
| `-SelfTestLayout` | WinForms 布局、默认值和可见文案自测 |
| `-SelfTestCatalogPreview` | 目录预览页布局自测 |
| `-SelfTestTitleIO` | 称号选项读写自测 |

```powershell
start_nanaimo_launcher.bat -ValidateOnly
```

### 界面说明

| 标签页 | 用途 |
|---|---|
| 启动配置 | 用户名、角色、宠物、装扮和启动操作 |
| 本次启动详情 | 角色、数值、装备、文件校验状态、启动前动作和配置路径（不显示连接参数与客户端命令行） |
| 数值与道具 | HP/MP、攻击、防御、货币、钥匙及技能树、Z/X 装备槽 |
| 宠物查表、装扮查表 | 资源编号与预览 |
| 衣物、宠物、游戏道具、家具、卡片管理 | 库存编辑 |

- **保存配置**：保存当前设置。
- **启动本地适配器**：单独管理本地适配器，不启动客户端。
- **保存并进入游戏**：保存配置、重启本地适配器、注册角色资料后启动客户端；会中断已有本地会话。
- **打开日志目录**：用资源管理器打开仓库根目录，profile、适配器日志和状态文件都在这里。

更新启动器脚本后需关闭旧窗口再重新打开。

### 默认配置

未保存 profile 时使用内置默认值。已有配置会继续加载；点击 **恢复默认** 后保存即可重置启动器设置，不会清空角色存档。

| 字段 | 默认值 |
|---|---|
| 用户名 | `Greyrat` |
| 等级 | `25` |
| 当前／最大 MP | `500 / 500` |
| 头发（hair） | `10130337` |
| 身体（body） | `10100028` |
| 上衣（top） | `10110337` |
| 下装（bottom） | `10120352` |
| 饰品（accessory） | `10150103` |
| 效果（effect） | `10160017` |
| 宠物（pet） | `15009205` |

默认 MP 为 500，方便体验耗蓝较高的宠物。已有配置不会被自动覆盖；可在“数值与道具”中将当前 MP 和最大 MP 都设为 500 后保存，无需重置其他设置。

配置保存在根目录的 `nanaimo_launcher_profile.ini` 和 `nanaimo_launcher_profile.json`。持久化数据格式见 [角色资料与背包](knowledge/authority/03-角色资料与背包.md)。

## 文档导航

| 路径 | 内容 |
|---|---|
| [知识库](knowledge/知识库索引.md) | 协议、静态地址、调用链、实现机制与证据范围 |
| [启动链与源码索引](docs/启动流程与源码索引.md) | GUI、资料注册、适配器模块和端口 |
| [构建与验证](docs/构建与验证.md) | 构建方法、自动化测试和验证范围 |
| [运行依赖](docs/运行依赖.md) | 客户端、资源、数据与工具依赖 |
| [导出工具](docs/文件清单与导出工具.md) | 文件清单、分层导出和完整性检查 |
| [第三方与许可说明](docs/第三方与许可说明.md) | 项目使用范围及第三方组件说明 |

