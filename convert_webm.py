"""把 dsh-pet 的透明 WebM 动画拆成 PNG 帧序列，供 tkinter 桌宠播放。

用法：
  python convert_webm.py                 # 转换全部动作
  python convert_webm.py 待机呼吸休闲     # 只转指定动作（可多个）
"""
import subprocess
import sys
from pathlib import Path

import imageio_ffmpeg

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "dsh-pet-main" / "dsh-pet" / "assets" / "thumb"
OUT = ROOT / "frames"

# 使用 imageio-ffmpeg 自带的完整版 ffmpeg（Trae CN 自带的是精简版，缺 PNG/image2/libvpx）
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

# 播放用参数（可调）
TARGET_W = 640      # 帧宽（保持原始 640×360 分辨率，避免缩放模糊）
TARGET_H = 360      # 帧高
FPS = 24            # 帧率（与原始一致，动画更流畅）


def convert(name: str, src: Path) -> Path:
    dst_dir = OUT / name
    dst_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
        "-c:v", "libvpx-vp9",              # 关键：libvpx 解码保留 VP9 alpha
        "-i", str(src),
        "-vf", f"fps={FPS},scale={TARGET_W}:{TARGET_H}:flags=lanczos,format=rgba",
        str(dst_dir / "frame_%04d.png"),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip())
    return dst_dir


def main() -> int:
    args = sys.argv[1:]
    names = [a for a in args if not a.startswith("--")] or sorted(p.stem for p in SRC.glob("*.webm"))
    total = len(names)
    for i, name in enumerate(names, start=1):
        src = SRC / f"{name}.webm"
        if not src.exists():
            print(f"[{i}/{total}] {name}  MISSING", flush=True)
            continue
        try:
            dst_dir = convert(name, src)
            n_frames = len(list(dst_dir.glob("*.png")))
            print(f"[{i}/{total}] {name}  -> {n_frames} 帧", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[{i}/{total}] {name}  FAIL: {exc}", flush=True)
            return 1
    print(f"\n=== 完成，输出目录：{OUT} ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
