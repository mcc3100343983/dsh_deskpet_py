# dsh-pet 桌面宠物 🐾

<p align="center">
  <img alt="license" src="https://img.shields.io/badge/license-MIT-orange">
  <img alt="platform" src="https://img.shields.io/badge/platform-Windows-0078D4">
  <img alt="python" src="https://img.shields.io/badge/python-3.8%2B-3776AB">
  <img alt="animations" src="https://img.shields.io/badge/animations-97%20available-ff69b4">
</p>

一只真正住在桌面上的透明宠物（不是网页里的小组件）——基于 **Win32 分层窗口 + 逐像素 alpha** 渲染，没有窗口边框、没有底色、鼠标穿透到透明区域之外，待机呼吸、点击回应、拖拽悬空、右键菜单、开机自启一应俱全。

```
python pet_player.py     # 就这样，宠物出现在桌面上
```

素材来自开源项目 [PC2005-cloud/dsh-pet](https://github.com/PC2005-cloud/dsh-pet) 的 97 段手绘风透明动画；本仓库用 `convert_webm.py` 把它们拆成 PNG 帧序列，再用一个纯 Win32 播放器逐帧播放。

---

## 目录

- [效果预览](#效果预览)
- [快速开始](#快速开始)
- [交互操作](#交互操作)
- [项目结构](#项目结构)
- [动画素材从哪来](#动画素材从哪来)
- [扩展新动作](#扩展新动作)
- [打包 / 交接](#打包--交接)
- [实现要点](#实现要点)
- [致谢与许可](#致谢与许可)

## 效果预览

当前支持的 5 个动作（GIF 预览，实际播放为透明背景）：

**待机** · **拖拽**

<p>
  <img src="dsh-pet-main/dsh-pet/assets/preview/daiji-huxi-xiuxian.gif" width="200" alt="待机呼吸休闲" title="待机呼吸休闲">
  <img src="dsh-pet-main/dsh-pet/assets/preview/beishubiao-tuozhuai-xuankong-fankui.gif" width="200" alt="被鼠标拖拽悬空反馈" title="被鼠标拖拽悬空反馈">
</p>

**点击回应**（随机抽一个）

<p>
  <img src="dsh-pet-main/dsh-pet/assets/preview/dianji-huiying-kaixin-yuedong.gif" width="200" alt="点击回应-开心跃动" title="点击回应-开心跃动">
  <img src="dsh-pet-main/dsh-pet/assets/preview/dianji-huiying-haixiu-jingya.gif" width="200" alt="点击回应-害羞惊讶" title="点击回应-害羞惊讶">
  <img src="dsh-pet-main/dsh-pet/assets/preview/dianji-huiying-aojiao-shengqi-ceshen-zhanshi.gif" width="200" alt="点击回应-傲娇生气" title="点击回应-傲娇生气">
</p>

仓库内还带有上游项目的完整素材（97 段动画），想要更多动作见[扩展新动作](#扩展新动作)。

## 快速开始

### 1. 环境要求

Python 3.8+（`pet_player.py` 用到 `os.chdir` / `mmap` / `ctypes` 等标准库）。仅支持 **Windows**——底层是 Win32 API（`UpdateLayeredWindow`、`RegisterClassExW`、注册表开机自启）。

### 2. 安装依赖

```powershell
pip install pillow numpy
```

| 库 | 用途 | 是否必需 |
|---|---|---|
| `Pillow`（PIL） | 解码 PNG 帧 | ✅ 必需 |
| `numpy` | 快速 RGBA→BGRA 转换、帧缓存 | ✅ 必需 |
| `imageio-ffmpeg` | 仅 `convert_webm.py` 转换新动作时用 | ⚠️ 扩展时用 |

其余 `os` / `random` / `threading` / `ctypes` / `tkinter` 均为 Python 标准库，无需额外安装。

### 3. 运行

```powershell
cd desk_pet
python pet_player.py
```

首次运行会在 `cache/` 下生成帧缓存（把 PNG 预解码成 `.npy`，降低运行时内存占用），**需要几秒**；之后启动是秒开的。`cache/` 可以随时删除，会自动重建。

> 想开机自动运行？右键宠物 → 「开机自启」即可（写入 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`，用 `pythonw.exe` 静默启动，无控制台窗口）。

## 交互操作

| 操作 | 效果 |
|---|---|
| **左键点击** | 随机播放一个「点击回应」动画（开心跃动 / 害羞惊讶 / 傲娇生气），播完回到待机 |
| **左键拖拽** | 播放「被鼠标拖拽悬空反馈」并跟随鼠标；松开后停在当前位置，位置写入 `settings.json` |
| **右键** | 弹出菜单：`修改属性 → 修改大小`（50%~200%）／`开机自启`（勾选状态实时反映注册表）／`退出` |

宠物的位置与缩放会持久化到同目录的 `settings.json`（`{"x":…, "y":…, "scale":…}`）；文件缺失或损坏时自动回落到默认值（右下角、100%），不会报错。

## 项目结构

```
desk_pet/
├── pet_player.py          # 主程序（当前运行入口）
├── convert_webm.py        # webm → PNG 帧序列转换工具（扩展新动作时用）
├── settings.json          # 窗口位置 / 缩放（运行时自动生成，不入库）
├── cache/                 # 运行时自动生成的帧缓存（*.npy，不入库，会自动重建）
├── frames/                # 已转换的动画帧（5 个动作，241 帧/动作，640×360）
│   ├── 待机呼吸休闲/
│   ├── 被鼠标拖拽悬空反馈/
│   ├── 点击回应-开心跃动/
│   ├── 点击回应-害羞惊讶/
│   └── 点击回应-傲娇生气/
└── dsh-pet-main/          # 上游素材项目（含 97 段 webm 源，扩展新动作时用）
```

`pet_player.py` 通过 `os.listdir("frames/<动作名>")` 加载帧，所以 **`frames/` 必须和 `pet_player.py` 在同一目录下**（程序启动时会自动 `chdir` 到脚本所在目录，从任何位置启动都没问题）。

### 运行必需的文件

最小可运行集合只有两样：

```
pet_player.py
frames/       （整个目录）
```

`cache/` 可选（带上可跳过对方首次运行的缓存构建），`dsh-pet-main/` 只有扩展新动作时才需要。

## 动画素材从哪来

`frames/` 里的 PNG 帧由 `convert_webm.py` 从 `dsh-pet-main/dsh-pet/assets/thumb/*.webm` 转换而来——这些是 **VP9 Alpha 编码的透明 webm**，转换时关键的一点是让 ffmpeg 用 `libvpx-vp9` 解码（否则 alpha 会丢失、变黑底）：

```powershell
python convert_webm.py                          # 转换全部动作
python convert_webm.py 待机呼吸休闲 东张西望     # 只转指定动作（可多个）
```

转换参数在 `convert_webm.py` 顶部，默认 `TARGET_W=640`、`TARGET_H=360`、`FPS=24`（与 webm 原始分辨率/帧率一致，避免缩放模糊）。

> 转换依赖 `imageio-ffmpeg` 自带的完整版 ffmpeg（系统里某些精简版 ffmpeg 缺 `libvpx` / `png` / `image2`，会转换失败）。

## 扩展新动作

四步搞定：

1. 确认 `dsh-pet-main/dsh-pet/assets/thumb/` 下有对应的 `.webm`（共 97 个动作可选，文件名即动作名）。
2. 转成帧序列：

   ```powershell
   python convert_webm.py 东张西望
   ```

3. 在 `pet_player.py` 顶部的动画列表里加入新动作名：

   ```python
   IDLE   = "待机呼吸休闲"                  # 待机循环（只有 1 个）
   DRAG   = "被鼠标拖拽悬空反馈"            # 拖拽时播放（只有 1 个）
   CLICKS = ["点击回应-开心跃动", "点击回应-害羞惊讶", "点击回应-傲娇生气"]
   ```

4. 重新运行 `pet_player.py`。动作名必须和 `frames/` 下的目录名一致。

> 新动作的帧如果和已有动作尺寸/构图一致（同一套素材链产出），无需改任何渲染参数。若要换一批不同构图的素材，调整顶部的 `SRC_W/SRC_H`、`CROP_LEFT/CROP_TOP`、`FRAME_W/FRAME_H` 即可。

## 打包 / 交接

**最小运行包**（只交付桌宠本身）：

```
pet_player.py
frames/       （整个目录，含 5 个动作）
```

对方需要 Python 环境并安装 `pip install pillow numpy`。

**完整交接包**（含扩展能力，可转更多动作）：

```
pet_player.py
convert_webm.py
frames/        （整个目录）
dsh-pet-main/  （整个目录，或至少保留 dsh-pet-main/dsh-pet/assets/thumb/ 下的 webm）
```

额外安装 `pip install pillow numpy imageio-ffmpeg`。

## 实现要点

几个踩过的坑，记下来省得再踩：

**为什么不用 tkinter 窗口做渲染？** tkinter 的窗口（`TkTopLevel` / `TkChild`）设置 `WS_EX_LAYERED` 后调用 `UpdateLayeredWindow` 不会真正渲染——窗口过程与分层机制冲突，结果是白屏。所以用 `RegisterClassExW` 注册原生窗口类，`CreateWindowExW` 直接以 `WS_EX_LAYERED` 创建分层窗口，再配合 `UpdateLayeredWindow` 做逐像素 alpha 渲染，彻底解决透明边缘的品红晕/白屏问题。

**逐像素 alpha 需要预乘。** `UpdateLayeredWindow` 的 `ULW_ALPHA` 模式要求 BGRA 且 RGB 通道**预乘**过 alpha（`premul = rgb * a / 255`），否则半透明边缘会出现白边。

**启动速度：只同步加载待机。** 启动时只同步加载待机动画（秒开），点击/拖拽动画由后台线程预加载；如果点击时目标动画还没就绪，不会阻塞，而是记下 pending，加载完自动切换。

**帧缓存用 mmap。** 帧全部预解码存成 `.npy` 后用 `mmap_mode="r"` 打开，避免把整个动画读进内存；缩放只在渲染时做，不重新生成缓存。缓存失效判定是「cache 的 mtime 不早于 frames 里最新的 PNG」，换了素材会自动重建。

**裁剪掉透明留白。** 源帧是 640×360，两侧有大量透明留白；渲染前裁掉（默认 `CROP_LEFT=100`，取 372×350），这样鼠标命中区域和窗口边界才贴合人物。

**DPI 感知。** 启动时调用 `SetProcessDPIAware()`，避免系统缩放导致坐标错位。

## 致谢与许可

动画素材（`frames/` 的源 webm、`dsh-pet-main/` 整个目录）来自开源项目 **[PC2005-cloud/dsh-pet](https://github.com/PC2005-cloud/dsh-pet)** —— 一套「提示词 → 绿幕视频 → 透明动画 → DSH 插件」的完整素材生成链，97 段手绘风透明动画由豆包生成。本仓库保留了该项目的原始授权文件：

- **代码：MIT**（原始版权声明见 [`dsh-pet-main/LICENSE`](dsh-pet-main/LICENSE)）
- **素材（动画 / 提示词 / 源视频）：允许开源使用，禁止商用**
