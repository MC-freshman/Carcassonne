# -*- coding: utf-8 -*-
"""联机消息协议：TCP + 4 字节长度前缀 + JSON。

消息类型（t 字段）：
  C→S: join / config / start / place / deploy / skip / discard
  S→C: lobby / snap / over / error
"""
from __future__ import annotations

import json
import struct
from typing import Any, Dict, Optional

import socket

HEADER = struct.Struct(">I")
MAX_FRAME = 1 << 20   # 1MB 上限，防异常包


def send_msg(sock: socket.socket, obj: Dict[str, Any]) -> None:
    data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    sock.sendall(HEADER.pack(len(data)) + data)


def recv_exact(sock: socket.socket, n: int) -> Optional[bytes]:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


def recv_msg(sock: socket.socket) -> Optional[Dict[str, Any]]:
    """阻塞收一条消息；连接关闭返回 None。"""
    head = recv_exact(sock, HEADER.size)
    if head is None:
        return None
    (length,) = HEADER.unpack(head)
    if length > MAX_FRAME:
        raise ValueError("帧超限: %d" % length)
    body = recv_exact(sock, length)
    if body is None:
        return None
    return json.loads(body.decode("utf-8"))
