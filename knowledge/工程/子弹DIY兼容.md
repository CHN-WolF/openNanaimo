# 工程／子弹DIY兼容

本页维护可选子弹DIY的配置生命周期、篮球资源身份、反向范围、PE位点及其完整应用和回退合同。操作入口见[子弹DIY与篮球试玩](../指南/子弹DIY与篮球试玩.md)。伤害归属与其他玩法规则从[业务索引](../业务/索引.md)进入，隔离验证与客户端实机验收仍按原文分别登记。

## 参考章节

- [功能与配置](#df-10-002)
- [篮球资源与反向范围](#df-10-003)
- [可选子弹DIY二进制与资源修改](#df-11-010)

<a id="df-10-002"></a>

<!-- FUSION BEGIN df-10-002 -->
## 功能与配置

- V键连续发射采用90ms间隔，松开后停止；跨地图或战斗对象重建后，以一次松键重新取得发射资格。
- `nanaimo_projectile.ini`保存启用状态、资源选择及反向开关；客户端第一次预载时读取，配置更新在下一次启动生效。
- 配置独立于角色数据库，人物数值、背包及适配器伤害规则保持各自管理。适配器与客户端配置采用独立生命周期。
- 默认关闭此功能；启用时由启动器调用可选安装器，使用PowerShell与内置.NET完成派生。

<!-- FUSION END df-10-002 -->

<a id="df-10-003"></a>

<!-- FUSION BEGIN df-10-003 -->
## 篮球资源与反向范围

篮球采用自制球面接缝的16帧旋转图，每帧48×48；IM3为48×768竖排精灵图，GIF提供对应动画预览。球面接缝逐帧转动，形成弹体旋转效果。

篮球使用独立的`nanaimo_basketball.pon/.eff/.im3`，保留三行结构、轨迹、owner1279及PON攻击候选`[1845,0,0]`。主效果名与图片指向篮球资源，主体alpha固定255，两层辅助效果alpha固定0。原炮弹资源保持原有内容。

反向处理限定篮球、六个`mis_ep02_hd_bbm_08_00..05.pon`兼容副本及`mis_ep09_bbm_02.pon`兼容副本；其它名称沿用原生方向。复杂轨迹、伤害归属与联机可见性按各资源分别验收。

<!-- FUSION END df-10-003 -->

<a id="df-11-010"></a>

<!-- FUSION BEGIN df-11-010 -->
## 可选子弹DIY二进制与资源修改

该功能以独立配置、五个入口和一个代码／数据区实现V键发射及限定名称的反向处理，默认关闭。配方由`manifest/projectile_diy_patch.json`登记完整字节、原始输入与资源身份；安装器为`scripts/prepare_projectile_diy.ps1`。

### 二进制合同与完整修改集合

输入为x86 PE32，ImageBase为`0x00400000`，采用固定地址装载。代码／数据区`0x00B98000..0x00B99FFF`共8192字节，所在节具备读、写、执行权限。五个WinAPI导入槽为`0x00D921E8/0x00D91FAC/0x00D91EA8/0x00D91F50/0x00D91ED0`，安装器校验其导入身份。各站点接受精确原始字节或当前目标字节，采用PE节映射定位。

| 用途 | VA | 原始字节 | 目标字节 |
|---|---|---|---|
| 预载入口 | `0x006A8960` | `55 8B EC 83 EC 10` | `E9 9B F6 4E 00 90` |
| 发射入口 | `0x006A9590` | `55 8B EC 6A FF` | `E9 6B EE 4E 00` |
| 行更新入口 | `0x006B5BA0` | `55 8B EC 83 EC 78` | `E9 5B 31 4E 00 90` |
| 父对象更新 | `0x006BAE60` | `55 8B EC 83 EC 20` | `E9 9B E1 4D 00 90` |
| 行绘制调用 | `0x006B63BA` | `E8 4F 20 D5 FF` | `E8 41 37 4E 00` |
| 代码／数据区 | `0x00B98000`，8192字节 | 8192个`CC` | 配方中该VA的完整`target`字节 |

行对象私有标记位于`+0x728`：名称、规定行数、非空EFF（`+0x28`）、零trail（`+0x5C0`）、零transition（`+0x704`）和既有标记共同构成门控。872字节管理对象采用独立边界。篮球名称限定三行；绘制时复制48字节的12轨道，在副本反转rotation与scaleX；六个ep02兼容副本按row0执行一次初始几何反射。

### 资源派生与旧版迁移

1. 输入为使用者客户端的`flying/pon/mis_ep01_hd_end_02_cannon_ball.pon`及`effs/game/shootinggamebasic/mis_ep01_hd_end_02_cannon ball.eff`，七个兼容PON的精确名称与别名由`gui_launcher/data/projectile_aliases.json`登记。
2. 派生`flying/pon/nanaimo_basketball.pon`：只替换`+4..263`的主EFF字符串，保留三行参数、owner1279与攻击候选1845/0/0。
3. 派生`effs/game/shootinggamebasic/nanaimo_basketball.eff`：`+28..283`改为篮球图片名，三行第7轨道各关键帧value/delta依次为255/0、0/0、0/0；其它字段与时间边界保持原值。
4. 写入独立`nanaimo_basketball.im3`，尺寸48×768，共16帧48×48。目标SHA-256为`7E287FE9424B5812107C383812145C957AD03551DE9D013588DDD6A696277866`；可迁移旧单帧身份为`D6C3D49B57556FD15BAA64E0B3AC67D4A700D0A292B45548A03629C06D701CA3`。旧EFF按同一输入派生的仅换图版本精确识别。原输入文件保持原有内容。
5. 七个PON按登记别名保存独立副本。目标资源已匹配时保持幂等；已知旧版本先备份再升级；其它同名内容进入冲突保护。

### 安装、配置、校验与回退

1. 退出目标目录游戏客户端，适配器可继续运行。确认客户端目录与目标`game.exe`，保留文件大小及SHA-256；社交副本按各自目录执行。
2. 执行预检，校验PE、装载地址、节权限、导入槽、完整站点与资源内容：

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File scripts/prepare_projectile_diy.ps1 -ClientRoot "<client-root>"
   ```

3. 执行安装：

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File scripts/prepare_projectile_diy.ps1 -ClientRoot "<client-root>" -Apply
   ```

   安装器在`.openNanaimo-projectile-backups/<SHA-256>/`保存被替换文件，复核全部输入及目标身份，先提交资源，最后提交`game.exe`；逐文件执行并发检查，完成后复核全部目标及原输入。失败时按逆序恢复本次已提交文件；并发冲突进入保护分支。安装摘要写入`adapter_data/projectile_install_report.json`。
4. 在启动器“子弹DIY”页选择资源或“选自制篮球”，设置“启用V键连续发射”及反向开关，保存到`nanaimo_projectile.ini`后启动客户端。配置在首次预载时读取；更新配置或旧资源升级均在客户端退出后、下一次启动时生效。战斗中按住V以90ms间隔发射，松开停止；切图与战斗对象重建后以松键重新取得发射资格。
5. 再次预检确认站点、资源与配置身份，重复安装保持幂等。专项覆盖安装、旧资源升级、冲突保护、回退、栈约定、名称／行门控和动画计算；游戏内画面与联机同步按独立验收状态管理。
6. 关闭游戏后执行位点回退：

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File scripts/prepare_projectile_diy.ps1 -ClientRoot "<client-root>" -Apply -Uninstall
   ```

   回退恢复表中五处原始指令及8192个`CC`，将配置`enabled`置0，保留其它兼容位点、新增独立资源与内容寻址备份。根据当前完整文件身份再次复核；备份按所含兼容版本分别管理。

### 配方与资源构建

开发期图片生成使用Pillow，x86配方生成使用Keystone，隔离执行使用Unicorn；发布安装链使用PowerShell与内置.NET。

```powershell
python -B scripts/generate_basketball_animation.py
python -B scripts/generate_projectile_diy_recipe.py
python -B scripts/test_projectile_diy.py -v
powershell -NoProfile -STA -ExecutionPolicy Bypass -File gui_launcher/nanaimo_launcher.ps1 -SelfTestProjectile
```
<!-- FUSION END df-11-010 -->
