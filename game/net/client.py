# -*- coding: utf-8 -*-
"""联机客户端：socket 读线程 + 消息队列，UI 主线程轮询消费。"""
from __future__ import annotations

import queue
import socket
import threading
import time as _time
from typing import Any, Dict, Optional, Tuple

from .protocol import recv_msg, send_msg


class NetClient:
    def __init__(self) -> None:
        self.sock: Optional[socket.socket] = None
        self.you: int = -1
        self.msgs: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        self.alive = False
        self.last_error: Optional[str] = None
        self._reader: Optional[threading.Thread] = None
        self._conn_args: Optional[Tuple[str, int, str]] = None

    # ------------------------------------------------------------ 连接

    def connect(self, host: str, port: int, name: str,
                timeout: float = 6.0) -> str:
        """加入房间。成功返回 ""，失败返回错误文本。"""
        self._conn_args = (host, port, name)
        return self._connect_now(timeout)

    def reconnect(self, timeout: float = 6.0) -> str:
        """断线后同名重连（服务器保留座位并补发快照）。"""
        if not self._conn_args:
            return "无连接参数，无法重连"
        self.close()
        return self._connect_now(timeout)

    def _connect_now(self, timeout: float) -> str:
        host, port, name = self._conn_args
        try:
            self.sock = socket.create_connection((host, port), timeout=timeout)
        except OSError as e:
            self.alive = False
            return "无法连接 %s:%d（%s）" % (host, port, e)
        self.sock.settimeout(None)
        self.alive = True
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        send_msg(self.sock, {"t": "join", "name": name})
        # 等 join 应答（含 you）；期间到达的其他消息（如重连补发的快照）放回队列
        import collections
        pending = collections.deque()
        deadline = _time.monotonic() + timeout
        while True:
            remain = deadline - _time.monotonic()
            if remain <= 0:
                self.close()
                return "加入超时"
            try:
                first = self.msgs.get(timeout=min(remain, 0.5))
            except queue.Empty:
                continue
            if first.get("t") == "error":
                self.close()
                return first.get("msg", "加入失败")
            if "you" in first:
                self.you = int(first["you"])
                break
            pending.append(first)
        while pending:      # 非应答消息按原顺序放回，交由正常轮询处理
            self.msgs.put(pending.popleft())
        return ""

    def close(self) -> None:
        self.alive = False
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass

    def _read_loop(self) -> None:
        assert self.sock is not None
        while self.alive:
            try:
                msg = recv_msg(self.sock)
            except (OSError, ValueError):
                if self.alive:
                    self.last_error = "与主机断开连接"
                    self.msgs.put({"t": "disconnected"})
                break
            if msg is None:
                if self.alive:
                    self.msgs.put({"t": "disconnected"})
                break
            self.msgs.put(msg)

    # ------------------------------------------------------------ 操作

    def send_place(self, x: int, y: int, rot: int) -> None:
        self._send({"t": "place", "x": x, "y": y, "rot": rot})

    def send_deploy(self, kind: str, seg: int, big: bool = False,
                    pos: Optional[Tuple[int, int]] = None,
                    victim: Optional[Tuple[int, int, str, int]] = None,
                    victim_color: Optional[str] = None) -> None:
        msg = {"t": "deploy", "kind": kind, "seg": seg, "big": bool(big)}
        if pos:
            msg["pos"] = list(pos)
        if victim:
            msg["victim"] = list(victim)
            msg["victim_color"] = victim_color
        self._send(msg)

    def send_drag(self, x: int, y: int) -> None:
        self._send({"t": "drag", "x": x, "y": y})

    def send_redeploy(self, move: bool) -> None:
        self._send({"t": "redeploy", "move": bool(move)})

    def send_count_deploy(self, quarter: str, fig: str,
                          count_move_to: Optional[str] = None) -> None:
        self._send({"t": "countdep", "quarter": quarter, "fig": fig,
                    "count_move_to": count_move_to})

    def send_count_skip(self) -> None:
        self._send({"t": "countskip"})

    def send_castle(self, convert: bool) -> None:
        self._send({"t": "castle", "convert": bool(convert)})

    def send_bridge(self, pos, axis: int) -> None:
        self._send({"t": "bridge", "x": int(pos[0]), "y": int(pos[1]),
                    "axis": int(axis)})

    def send_gold(self, pos) -> None:
        self._send({"t": "gold", "x": int(pos[0]), "y": int(pos[1])})

    def send_mw(self, fig: str, node) -> None:
        self._send({"t": "mw", "fig": fig,
                    "node": None if node is None else list(node)})

    def send_tunnel(self, node=None, skip: bool = False) -> None:
        if skip or node is None:
            self._send({"t": "tunnel", "skip": True})
            return
        self._send({"t": "tunnel", "x": int(node[0]), "y": int(node[1]),
                    "kind": node[2], "seg": int(node[3])})

    def send_crop(self, mode: Optional[str] = None, node=None) -> None:
        msg = {"t": "crop"}
        if mode:
            msg["mode"] = mode
        if node is not None:
            msg["node"] = list(node)
        self._send(msg)

    def send_robber(self, space: Optional[int]) -> None:
        self._send({"t": "robber", "space": space})

    def send_escape(self, node=None) -> None:
        self._send({"t": "escape", "node": None if node is None
                    else list(node)})

    def send_tower_piece(self, pos, capture=None) -> None:
        msg = {"t": "tower", "action": "piece", "x": int(pos[0]),
               "y": int(pos[1])}
        if capture is not None:
            msg["capture"] = list(capture)
        self._send(msg)

    def send_tower_top(self, pos, big: bool = False) -> None:
        self._send({"t": "tower", "action": "top", "x": int(pos[0]),
                    "y": int(pos[1]), "big": bool(big)})

    def send_ransom(self, idx: int) -> None:
        self._send({"t": "tower", "action": "ransom", "idx": int(idx)})

    def send_shepherd(self, expand: bool) -> None:
        self._send({"t": "shepherd", "expand": bool(expand)})

    def send_plague(self, node=None) -> None:
        self._send({"t": "plague", "node": None if node is None
                    else list(node)})

    def send_bazaar(self, action: str, **kw) -> None:
        msg = {"t": "bazaar", "action": action}
        msg.update(kw)
        self._send(msg)

    def send_skip(self) -> None:
        self._send({"t": "skip"})

    def send_discard(self) -> None:
        self._send({"t": "discard"})

    def send_start(self) -> None:
        self._send({"t": "start"})

    def send_ping(self, ts: float) -> None:
        self._send({"t": "ping", "ts": ts})

    def send_kick(self, seat: int) -> None:
        self._send({"t": "kick", "seat": seat})

    def _send(self, obj: Dict[str, Any]) -> None:
        if self.sock and self.alive:
            try:
                send_msg(self.sock, obj)
            except OSError:
                self.msgs.put({"t": "disconnected"})
