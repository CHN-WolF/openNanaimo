# 家具预览

生成器 [generate_furniture_previews.py](generate_furniture_previews.py) 从加密的 `inter._D3` 读取家具图标路径，并映射到 `images/InteriorIcon.pack` 的数字资源键。IM3 图像按 ARGB1555 解码，在 `gui_launcher/data/previews/furniture_icons.png` 中以 96×80 像素单元居中排列；同目录的 `furniture_icons.json` 按家具物品编号记录资源路径、可用状态和图集坐标。同一图标可由多个家具物品共用。

生成器依赖 PyCryptodome 和 Pillow。缺失或无法解码的资源保留 `available: false`、坐标 `-1,-1`，并记录具体的 `failure` 类别；启动器将可用条目显示为资源缩略图。预览可用状态不代表客户端家具交互已经验收。

<!-- 兼容既有章节链接 -->
<a id="furniture-previews"></a>
