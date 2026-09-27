"""dsh-pet 人物动画播放器（纯原生 Win32 分层窗口，逐像素 alpha）。

为什么不用 tkinter 窗口做渲染：
  tkinter 的窗口（TkTopLevel / TkChild）在设置 WS_EX_LAYERED 后调用
  UpdateLayeredWindow 不会真正渲染（窗口过程与分层机制冲突，导致白屏）。
  因此这里用 RegisterClassExW 注册一个原生窗口类，用 CreateWindowExW 直接以
  WS_EX_LAYERED 创建分层窗口，再配合 UpdateLayeredWindow 做逐像素 alpha 渲染，
  彻底解决透明边缘的品红晕/白屏问题。

功能：
- 待机呼吸循环播放
- 点击 → 随机播放一个"点击回应"动画
- 拖拽 → 播放"被鼠标拖拽悬空反馈"并跟随鼠标
- 右键 → 弹出菜单（修改属性/修改大小、开机自启、退出）
"""
import os
import sys
import json
import random
import collections
import threading
import ctypes
import winreg
from ctypes import wintypes
import numpy as np
from PIL import Image

# 无论从哪里启动，都把工作目录切到脚本所在目录，确保能找到 frames/
os.chdir(os.path.dirname(os.path.abspath(__file__)))

SRC_W, SRC_H = 640, 360     # 原始帧尺寸（webm/PNG）
CROP_LEFT, CROP_TOP = 100, 0  # 裁剪区域左上角（裁掉两侧透明留白）
FRAME_W, FRAME_H = 372, 350   # 裁剪后的有效帧尺寸
FPS_MS = 42                  # 约 24fps
MIN_SCALE = 50               # 缩放下限（%）
MAX_SCALE = 200              # 缩放上限（%）
DEFAULT_SCALE = 100          # 默认缩放（%）=> 372×350

IDLE = "待机呼吸休闲"
DRAG = "被鼠标拖拽悬空反馈"
CLICKS = ["点击回应-开心跃动", "点击回应-害羞惊讶", "点击回应-傲娇生气"]

# ---- Win32 常量 ----
WS_EX_LAYERED = 0x00080000
WS_EX_TOPMOST = 0x00000008
WS_POPUP = 0x80000000
CS_HREDRAW = 0x0002
CS_VREDRAW = 0x0001
ULW_ALPHA = 0x00000002
AC_SRC_OVER = 0
AC_SRC_ALPHA = 1
IDC_ARROW = 32512
SW_SHOW = 5

WM_DESTROY = 0x0002
WM_TIMER = 0x0113
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205
MK_LBUTTON = 0x0001

MF_STRING = 0x0000
MF_POPUP = 0x0010
MF_CHECKED = 0x0008
MF_UNCHECKED = 0x0000
TPM_RIGHTBUTTON = 0x0002
TPM_RETURNCMD = 0x0100
ID_EXIT = 1001
ID_SCALE = 1002
ID_AUTOSTART = 1003

# 开机自启（注册表 HKCU\...\Run）
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "DeskPet"

# 位置/缩放持久化（脚本同级 settings.json）
SETTINGS_FILE = "settings.json"

HWND = ctypes.c_void_p
HDC = ctypes.c_void_p
HMENU = ctypes.c_void_p
HINSTANCE = ctypes.c_void_p


def _dpi_aware():
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


# ---- Win32 API 声明（完整 argtypes，避免 64 位句柄截断）----
user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
kernel32 = ctypes.windll.kernel32

WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, HWND, ctypes.c_uint,
                             wintypes.WPARAM, wintypes.LPARAM)


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", HWND), ("message", ctypes.c_uint),
        ("wParam", wintypes.WPARAM), ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD), ("pt", POINT),
    ]


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint), ("style", ctypes.c_uint),
        ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int), ("hInstance", HINSTANCE),
        ("hIcon", ctypes.c_void_p), ("hCursor", ctypes.c_void_p),
        ("hbrBackground", ctypes.c_void_p), ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR), ("hIconSm", ctypes.c_void_p),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long), ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
        ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte),
    ]


user32.RegisterClassExW.restype = wintypes.WORD
user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
user32.CreateWindowExW.restype = HWND
user32.CreateWindowExW.argtypes = [
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    HWND, HMENU, HINSTANCE, wintypes.LPVOID,
]
user32.DefWindowProcW.restype = ctypes.c_ssize_t
user32.DefWindowProcW.argtypes = [HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM]
user32.ShowWindow.restype = ctypes.c_int
user32.ShowWindow.argtypes = [HWND, ctypes.c_int]
user32.UpdateWindow.restype = ctypes.c_int
user32.UpdateWindow.argtypes = [HWND]
user32.DestroyWindow.restype = ctypes.c_int
user32.DestroyWindow.argtypes = [HWND]
user32.UnregisterClassW.restype = ctypes.c_int
user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, HINSTANCE]
user32.GetMessageW.restype = ctypes.c_int
user32.GetMessageW.argtypes = [ctypes.POINTER(MSG), HWND, ctypes.c_uint, ctypes.c_uint]
user32.TranslateMessage.restype = ctypes.c_int
user32.TranslateMessage.argtypes = [ctypes.POINTER(MSG)]
user32.DispatchMessageW.restype = ctypes.c_ssize_t
user32.DispatchMessageW.argtypes = [ctypes.POINTER(MSG)]
user32.PostQuitMessage.restype = None
user32.PostQuitMessage.argtypes = [ctypes.c_int]
user32.MessageBoxW.restype = ctypes.c_int
user32.MessageBoxW.argtypes = [HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_uint]
user32.SetTimer.restype = ctypes.c_void_p
user32.SetTimer.argtypes = [HWND, ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p]
user32.GetCursorPos.restype = ctypes.c_int
user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
user32.GetDC.restype = HDC
user32.GetDC.argtypes = [HWND]
user32.ReleaseDC.restype = ctypes.c_int
user32.ReleaseDC.argtypes = [HWND, HDC]
user32.GetSystemMetrics.restype = ctypes.c_int
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.CreatePopupMenu.restype = HMENU
user32.CreatePopupMenu.argtypes = []
user32.AppendMenuW.restype = ctypes.c_int
user32.AppendMenuW.argtypes = [HMENU, ctypes.c_uint, ctypes.c_void_p, wintypes.LPCWSTR]
user32.TrackPopupMenu.restype = ctypes.c_int
user32.TrackPopupMenu.argtypes = [HMENU, ctypes.c_uint, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_int, HWND, ctypes.c_void_p]
user32.DestroyMenu.restype = ctypes.c_int
user32.DestroyMenu.argtypes = [HMENU]

kernel32.GetModuleHandleW.restype = HINSTANCE
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]

gdi32.CreateCompatibleDC.restype = HDC
gdi32.CreateCompatibleDC.argtypes = [HDC]
gdi32.CreateDIBSection.restype = ctypes.c_void_p
gdi32.CreateDIBSection.argtypes = [HDC, ctypes.c_void_p, ctypes.c_uint,
                                   ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, ctypes.c_uint]
gdi32.SelectObject.restype = ctypes.c_void_p
gdi32.SelectObject.argtypes = [HDC, ctypes.c_void_p]
gdi32.DeleteObject.restype = ctypes.c_int
gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
gdi32.DeleteDC.restype = ctypes.c_int
gdi32.DeleteDC.argtypes = [HDC]
user32.LoadCursorW.restype = ctypes.c_void_p
user32.LoadCursorW.argtypes = [HINSTANCE, ctypes.c_void_p]

user32.UpdateLayeredWindow.restype = ctypes.c_int
user32.UpdateLayeredWindow.argtypes = [
    HWND, HDC, ctypes.POINTER(POINT), ctypes.POINTER(wintypes.SIZE),
    HDC, ctypes.POINTER(POINT), wintypes.COLORREF,
    ctypes.POINTER(BLENDFUNCTION), wintypes.DWORD,
]


class PetPlayer:
    def __init__(self):
        _dpi_aware()

        data = self._load_settings()

        scale = data.get("scale")
        self.scale = scale if isinstance(scale, int) and MIN_SCALE <= scale <= MAX_SCALE else DEFAULT_SCALE
        self.w = FRAME_W * self.scale // 100
        self.h = FRAME_H * self.scale // 100
        self._lock = threading.Lock()
        self.anims = {}           # name -> mmap 帧数组（(n, 360, 640, 4) RGBA）
        self._loading = set()     # 后台正在加载的动画名
        self._todo = collections.deque()
        self._cv = threading.Condition()
        self._pending = None      # 点击/拖拽时目标动画未就绪，先记下待切换 (mode, anim)
        self._ensure_loaded(IDLE)  # 启动只同步加载待机，秒开
        self._start_preload()      # 其余动画后台预加载

        self.mode = "idle"
        self.anim = IDLE
        self.idx = 0

        self.dragging = False
        self._drag_ox = 0
        self._drag_oy = 0
        self._press_cx = 0
        self._press_cy = 0
        self._pressed = False

        sw = user32.GetSystemMetrics(0)
        sh = user32.GetSystemMetrics(1)
        x = data.get("x")
        y = data.get("y")
        if isinstance(x, int) and isinstance(y, int):
            self.x = max(0, min(x, sw - self.w))
            self.y = max(0, min(y, sh - self.h))
        else:
            self.x = sw - self.w - 200
            self.y = sh - self.h - 300

        self.hwnd = self._create_window()
        user32.ShowWindow(self.hwnd, SW_SHOW)
        user32.UpdateWindow(self.hwnd)

        self._render()
        user32.SetTimer(self.hwnd, 1, FPS_MS, None)

        self._message_loop()

    # ---- 资源加载 ----
    def _cache_path(self, name):
        return os.path.join("cache", name + ".npy")

    def _cache_valid(self, name):
        """缓存存在且不比 frames 里的 PNG 旧，则有效。"""
        cache = self._cache_path(name)
        if not os.path.exists(cache):
            return False
        d = os.path.join("frames", name)
        try:
            files = sorted(os.listdir(d))
        except FileNotFoundError:
            return False
        if not files:
            return False
        newest = max(os.path.getmtime(os.path.join(d, f)) for f in files)
        return os.path.getmtime(cache) >= newest

    def _build_cache(self, name):
        """把 PNG 帧裁剪后预解码成 RGBA 数组存盘（仅首次/素材更新时执行）。"""
        d = os.path.join("frames", name)
        files = sorted(os.listdir(d))
        box = (CROP_LEFT, CROP_TOP, CROP_LEFT + FRAME_W, CROP_TOP + FRAME_H)
        frames = [np.asarray(Image.open(os.path.join(d, f)).convert("RGBA").crop(box),
                             dtype=np.uint8) for f in files]
        arr = np.stack(frames)                       # (n, FRAME_H, FRAME_W, 4)
        cache = self._cache_path(name)
        os.makedirs("cache", exist_ok=True)
        tmp = cache + ".tmp.npy"
        np.save(tmp, arr)
        os.replace(tmp, cache)

    def _open_cache(self, name):
        """以 mmap 方式打开帧缓存，避免把整个动画读进内存。"""
        if not self._cache_valid(name):
            self._build_cache(name)
        return np.load(self._cache_path(name), mmap_mode="r")

    def _ensure_loaded(self, name):
        """主线程同步加载指定动画（启动/缩放后立即显示用）。"""
        with self._lock:
            if name in self.anims:
                return
        arr = self._open_cache(name)
        with self._lock:
            self.anims.setdefault(name, arr)

    def _request_async(self, name):
        """把动画加入后台加载队列（点击目标插队优先）。"""
        with self._lock:
            if name in self.anims or name in self._loading:
                return
        with self._cv:
            if name not in self._todo:
                self._todo.appendleft(name)
            self._cv.notify()

    def _worker(self):
        """后台线程：按队列顺序打开动画缓存。"""
        while True:
            with self._cv:
                while not self._todo:
                    self._cv.wait()
                name = self._todo.popleft()
            with self._lock:
                if name in self.anims or name in self._loading:
                    continue
                self._loading.add(name)
            arr = self._open_cache(name)
            with self._lock:
                self._loading.discard(name)
                self.anims.setdefault(name, arr)

    def _start_preload(self):
        """启动后台加载线程，并预加载点击/拖拽动画。"""
        threading.Thread(target=self._worker, daemon=True).start()
        for name in CLICKS + [DRAG]:
            self._request_async(name)

    def _set_scale(self, scale):
        scale = max(MIN_SCALE, min(MAX_SCALE, int(scale)))
        if scale == self.scale:
            return
        self.scale = scale
        self.w = FRAME_W * scale // 100
        self.h = FRAME_H * scale // 100
        # 缓存是原始分辨率，缩放只在渲染时做，无需重载缓存
        self.idx = 0
        self._render()
        self._save_settings()

    @staticmethod
    def _to_bgra(im):
        """PIL RGBA -> premultiplied BGRA 字节串（UpdateLayeredWindow 需要）。"""
        w, h = im.size
        arr = np.asarray(im, dtype=np.uint8)          # (h, w, 4) RGBA
        a = arr[..., 3:4].astype(np.uint16)
        rgb = arr[..., :3].astype(np.uint16)
        premul = (rgb * a // 255).astype(np.uint8)    # 预乘 RGB
        bgra = np.concatenate(
            [premul[..., 2:3], premul[..., 1:2], premul[..., 0:1], arr[..., 3:4]],
            axis=2)
        return bgra.tobytes(), w, h

    def _frame_to_bgra(self, frame):
        """mmap 读出的原始 RGBA 帧 -> 按当前 scale 缩放并转 premultiplied BGRA。"""
        w = FRAME_W * self.scale // 100
        h = FRAME_H * self.scale // 100
        im = Image.fromarray(frame, "RGBA")
        if (w, h) != (FRAME_W, FRAME_H):
            im = im.resize((w, h), Image.LANCZOS)
        return self._to_bgra(im)

    # ---- 窗口创建 ----
    def _create_window(self):
        cls_name = "DeskPetLayeredWindow"
        hinst = kernel32.GetModuleHandleW(None)

        # 把窗口过程方法包装成 ctypes 回调并保留引用（避免被垃圾回收）
        self._wnd_proc_cb = WNDPROC(self._wnd_proc)

        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.style = CS_HREDRAW | CS_VREDRAW
        wc.lpfnWndProc = self._wnd_proc_cb
        wc.hInstance = hinst
        wc.hCursor = user32.LoadCursorW(None, IDC_ARROW)
        wc.lpszClassName = cls_name
        user32.RegisterClassExW(ctypes.byref(wc))

        hwnd = user32.CreateWindowExW(
            WS_EX_LAYERED | WS_EX_TOPMOST, cls_name, None, WS_POPUP,
            self.x, self.y, self.w, self.h, None, None, hinst, None)
        return hwnd

    # ---- 渲染 ----
    def _render(self):
        frame = self.anims[self.anim][self.idx]   # mmap 读当前帧 (FRAME_H, FRAME_W, 4) RGBA
        bgra, w, h = self._frame_to_bgra(frame)
        hdc_screen = user32.GetDC(0)
        hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)

        bmi = BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.biWidth = w
        bmi.biHeight = -h
        bmi.biPlanes = 1
        bmi.biBitCount = 32
        bmi.biCompression = 0

        pbits = ctypes.c_void_p()
        hbm = gdi32.CreateDIBSection(hdc_mem, ctypes.byref(bmi), 0,
                                     ctypes.byref(pbits), None, 0)
        ctypes.memmove(pbits, bgra, len(bgra))
        old = gdi32.SelectObject(hdc_mem, hbm)

        pt_dst = POINT(self.x, self.y)
        size = wintypes.SIZE(w, h)
        pt_src = POINT(0, 0)
        blend = BLENDFUNCTION()
        blend.BlendOp = AC_SRC_OVER
        blend.BlendFlags = 0
        blend.SourceConstantAlpha = 255
        blend.AlphaFormat = AC_SRC_ALPHA

        user32.UpdateLayeredWindow(self.hwnd, hdc_screen, ctypes.byref(pt_dst),
                                   ctypes.byref(size), hdc_mem, ctypes.byref(pt_src),
                                   0, ctypes.byref(blend), ULW_ALPHA)

        gdi32.SelectObject(hdc_mem, old)
        gdi32.DeleteObject(hbm)
        gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(0, hdc_screen)

    # ---- 动画逻辑 ----
    def _switch(self, mode, anim):
        """切换动画；目标未就绪时不阻塞，先记 pending，加载完自动切换。"""
        self._pending = None
        with self._lock:
            ready = anim in self.anims
        if ready:
            self.mode = mode
            self.anim = anim
            self.idx = 0
            self._render()
        else:
            self._pending = (mode, anim)
            self._request_async(anim)
            # 保持当前动画继续播放，等目标加载完成后再切

    def _tick(self):
        # 若有等待中的切换且目标已就绪，立即完成切换
        if self._pending is not None:
            mode, anim = self._pending
            with self._lock:
                ready = anim in self.anims
            if ready:
                self._pending = None
                self.mode = mode
                self.anim = anim
                self.idx = 0
                self._render()
                return
        self.idx += 1
        if self.idx >= len(self.anims[self.anim]):
            if self.mode == "click":
                if self._pending is not None:
                    self.idx -= 1   # 停在最后一帧，等 pending 目标就绪
                else:
                    self._switch("idle", IDLE)
                    return
            else:
                self.idx = 0
        self._render()

    # ---- 窗口过程 ----
    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == WM_TIMER:
            self._tick()
            return 0

        if msg == WM_LBUTTONDOWN:
            pt = POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            self._pressed = True
            self.dragging = False
            self._press_cx = pt.x
            self._press_cy = pt.y
            self._drag_ox = pt.x - self.x
            self._drag_oy = pt.y - self.y
            return 0

        if msg == WM_MOUSEMOVE:
            if self._pressed and (wparam & MK_LBUTTON):
                pt = POINT()
                user32.GetCursorPos(ctypes.byref(pt))
                dx = pt.x - self._press_cx
                dy = pt.y - self._press_cy
                if not self.dragging and (abs(dx) + abs(dy)) > 6:
                    self.dragging = True
                    self._switch("drag", DRAG)
                if self.dragging:
                    self.x = pt.x - self._drag_ox
                    self.y = pt.y - self._drag_oy
                    self._render()
            return 0

        if msg == WM_LBUTTONUP:
            if self._pressed:
                self._pressed = False
                if self.dragging:
                    self.dragging = False
                    self._switch("idle", IDLE)
                    self._save_settings()
                else:
                    self._switch("click", random.choice(CLICKS))
            return 0

        if msg == WM_RBUTTONUP:
            pt = POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            menu = user32.CreatePopupMenu()
            sub = user32.CreatePopupMenu()
            user32.AppendMenuW(sub, MF_STRING, ID_SCALE, "修改大小")
            user32.AppendMenuW(menu, MF_POPUP, sub, "修改属性")
            autostart_checked = MF_CHECKED if self._is_autostart_enabled() else MF_UNCHECKED
            user32.AppendMenuW(menu, MF_STRING | autostart_checked, ID_AUTOSTART, "开机自启")
            user32.AppendMenuW(menu, MF_STRING, ID_EXIT, "退出")
            cmd = user32.TrackPopupMenu(menu, TPM_RIGHTBUTTON | TPM_RETURNCMD,
                                        pt.x, pt.y, 0, hwnd, None)
            user32.DestroyMenu(menu)
            if cmd == ID_SCALE:
                self._prompt_scale()
            elif cmd == ID_AUTOSTART:
                self._toggle_autostart()
            elif cmd == ID_EXIT:
                user32.DestroyWindow(hwnd)
                user32.PostQuitMessage(0)
            return 0

        if msg == WM_DESTROY:
            self._save_settings()
            user32.PostQuitMessage(0)
            return 0

        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _prompt_scale(self):
        """弹出「修改大小」输入框，范围 50~200（%）。"""
        import tkinter as tk
        from tkinter import simpledialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        try:
            val = simpledialog.askinteger(
                "修改大小",
                f"缩放百分比（{MIN_SCALE}~{MAX_SCALE}），当前 {self.scale}%：",
                minvalue=MIN_SCALE, maxvalue=MAX_SCALE,
                initialvalue=self.scale, parent=root)
        finally:
            root.destroy()
        if val is not None:
            self._set_scale(val)

    # ---- 设置持久化 ----
    @staticmethod
    def _load_settings():
        """读取 settings.json（不存在或损坏时返回空）。"""
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save_settings(self):
        """把当前位置和缩放写入 settings.json。"""
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump({"x": int(self.x), "y": int(self.y), "scale": int(self.scale)}, f)
        except OSError:
            pass

    # ---- 开机自启 ----
    @staticmethod
    def _autostart_command():
        """构造开机启动命令：优先用 pythonw.exe 无窗口静默运行本脚本。"""
        exe = sys.executable
        exe_w = exe[:-len("python.exe")] + "pythonw.exe"
        if exe.lower().endswith("python.exe") and os.path.exists(exe_w):
            exe = exe_w
        script = os.path.abspath(__file__)
        return f'"{exe}" "{script}"'

    def _is_autostart_enabled(self):
        """检查 HKCU\\...\\Run 下是否存在本应用的自启项。"""
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ)
        except FileNotFoundError:
            return False
        try:
            winreg.QueryValueEx(key, APP_NAME)
            return True
        except FileNotFoundError:
            return False
        finally:
            winreg.CloseKey(key)

    def _toggle_autostart(self):
        """切换开机自启状态，并用消息框提示结果。"""
        enabled = self._is_autostart_enabled()
        try:
            if enabled:
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE)
                try:
                    winreg.DeleteValue(key, APP_NAME)
                finally:
                    winreg.CloseKey(key)
                user32.MessageBoxW(self.hwnd, "已关闭开机自启。", APP_NAME, 0x40)
            else:
                key = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE)
                try:
                    winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, self._autostart_command())
                finally:
                    winreg.CloseKey(key)
                user32.MessageBoxW(self.hwnd, "已开启开机自启。", APP_NAME, 0x40)
        except OSError as exc:
            user32.MessageBoxW(self.hwnd, f"操作失败：{exc}", APP_NAME, 0x10)

    # ---- 消息循环 ----
    def _message_loop(self):
        msg = MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))


def _main():
    PetPlayer()


if __name__ == "__main__":
    _main()
