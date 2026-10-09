# -*- coding: utf-8 -*-
"""事件音效：winsound 内存 wav 异步播放（零依赖、不阻塞 UI 线程）。

音色由正弦+衰减包络即时合成（SND_MEMORY），仅 Windows 生效，其余平台
静默跳过。UI 通过菜单开关控制 enabled；播放失败一律吞掉（音效永不
影响对局）。
"""
from __future__ import annotations

import math
import os
import struct
import sys
import tempfile
from typing import Optional

enabled = True


def _wav(notes, vol: float = 0.30, rate: int = 22050) -> bytes:
    """合成一段内存 wav。notes: [(freq_hz, ms), ...] 顺序播放。"""
    chunks = []
    for freq, ms in notes:
        n = max(1, int(rate * ms / 1000))
        frames = bytearray()
        for i in range(n):
            env = (1.0 - i / n) ** 1.6          # 指数式衰减包络
            v = int(vol * env * 32767 * math.sin(2 * math.pi * freq * i / rate))
            frames += struct.pack("<h", v)
        chunks.append(bytes(frames))
    data = b"".join(chunks)
    return (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
            + b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
            + b"data" + struct.pack("<I", len(data)) + data)


_SOUNDS = {
    "place": _wav([(660, 70)]),                        # 落牌：短促木鱼感
    "deploy": _wav([(880, 60)]),                       # 部署随从
    "score": _wav([(784, 80), (1046, 110)]),           # 得分：上行双音
    "big": _wav([(523, 90), (659, 90), (784, 90), (1046, 170)]),  # 终局号角
    "bad": _wav([(196, 130)]),                         # 非法操作：低沉短音
}


def _cached_file(name: str, data: bytes) -> Optional[str]:
    """把合成 wav 缓存为临时目录文件（SND_ASYNC 不支持内存播放）。"""
    d = os.path.join(tempfile.gettempdir(), "carcassonne-snd")
    try:
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, "%s.wav" % name)
        if not os.path.isfile(path):
            with open(path, "wb") as f:
                f.write(data)
        return path
    except OSError:
        return None


def play(name: str) -> None:
    if not enabled or sys.platform != "win32":
        return
    data = _SOUNDS.get(name)
    if data is None:
        return
    try:
        import winsound
        path = _cached_file(name, data)
        if path:
            winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC
                               | winsound.SND_NODEFAULT)
    except Exception:
        pass
