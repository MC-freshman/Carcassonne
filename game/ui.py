# -*- coding: utf-8 -*-
"""Tkinter 单机界面：本地热座 + 人机对战。

交互：
- 放置阶段：合法格高亮；悬停显示幽灵牌；点击放置；R 键/按钮旋转
- 部署阶段：刚放的牌上出现锚点圆钮，点击部署；「跳过」按钮
- AI 回合自动执行；终局弹出结算窗口
"""
from __future__ import annotations

import os
import queue
import re
import socket
import tkinter as tk
from tkinter import font as tkfont, messagebox, ttk
from typing import Dict, List, Optional, Tuple

from . import art, tile_data
from .board import KIND_CITY, KIND_FARM, KIND_MON, KIND_ROAD
from .bot_ai import BotAI
from .engine import COLOR_HEX, CarcassonneEngine
from .models import TileDef, meeple_majority


# M14 拆分：常量与绘制在 ui_common，对话框在 ui_dialogs（保持公开名字）
from .ui_common import (  # noqa: F401
    TILE, PREVIEW, GRID_ORIGIN, FONT, FONT_S, FONT_L,
    COL_FIELD, COL_FIELD_DARK, COL_CITY, COL_CITY_WALL, COL_ROAD,
    COL_ROAD_BORDER, COL_MON, COL_BG, COL_HILITE, EDGE_MID,
    _pull, seg_anchor, draw_tile, draw_meeple,
)
from .ui_dialogs import setup_dialog, mode_dialog, get_lan_ip  # noqa: F401

class App(tk.Tk):
    def __init__(self, specs: Optional[List[dict]] = None,
                 seed: Optional[int] = None,
                 net: Optional[object] = None,
                 server: Optional[object] = None,
                 net_info: str = "",
                 poll_ms: int = 100,
                 expansions: Optional[list] = None):
        super().__init__()
        self.title("卡卡颂 · 桌游模拟器" + ("（联机）" if net else ""))
        self.configure(bg=COL_BG)
        self.net = net                      # NetClient（联机模式）
        self.server = server                # GameServer（房主持有，退出时关闭）
        self.net_mode = net is not None
        self.net_info = net_info
        self.poll_ms = poll_ms
        self._polling = False
        self.my_seat = net.you if net else -1
        self._net_over = False
        self._retries = 0
        self._reconnecting = False
        self._rtt_ms: Optional[int] = None
        self._lobby_seats: list = []
        self.engine: Optional[CarcassonneEngine] = None
        self.expansions = list(expansions or [])
        if not self.net_mode:
            self.engine = CarcassonneEngine(specs, seed=seed,
                                            expansions=self.expansions)
            self.bots = {i: BotAI(p.ai_level, seed=(seed or 0) + i)
                         for i, p in enumerate(self.engine.players) if p.is_ai}
        self.rot = 0
        self.hover_cell: Optional[Tuple[int, int]] = None
        self._logged_ev_idx = 0
        self._prompt_key = None
        self._finished = False
        self._flash_pos: Optional[Tuple[int, int]] = None
        self._img_cache: Dict[Tuple[str, int], object] = {}
        self._build()
        self.sprites = art.SpriteStore(self)
        self._restore_window()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        if self.net_mode:
            self.after(self.poll_ms, self._net_poll)
        else:
            self.refresh()
            self.maybe_ai_turn()

    # ------------------------------------------------------------ 布局

    def _build(self) -> None:
        self.geometry("1180x780+60+40")
        self.minsize(980, 640)

        top = tk.Frame(self, bg="#39422e", height=44)
        top.pack(fill="x")
        top.pack_propagate(False)
        self.lbl_turn = tk.Label(top, text="", font=FONT_L, bg="#39422e",
                                 fg="#f2e8c9")
        self.lbl_turn.pack(side="left", padx=14)
        self.lbl_left = tk.Label(top, text="", font=FONT, bg="#39422e",
                                 fg="#cfc49f")
        self.lbl_left.pack(side="left", padx=8)
        self.lbl_phase = tk.Label(top, text="", font=FONT, bg="#39422e",
                                  fg="#e8c96a")
        self.lbl_phase.pack(side="right", padx=14)
        tk.Button(top, text="?", font=FONT, width=3, relief="flat",
                  bg="#4a5a3a", fg="#e8e0c4", activebackground="#5a6a48",
                  command=self._show_help).pack(side="right", padx=(0, 8))
        self.btn_start = tk.Button(top, text="▶ 开始对局（人齐后）", font=FONT,
                                   command=self._net_start, bg="#b5482f",
                                   fg="white", activebackground="#c9583d",
                                   relief="flat")
        # 联机模式下显示；单机模式隐藏
        if self.net_mode:
            self.btn_start.pack(side="right", padx=10)
            self.lbl_rtt = tk.Label(top, text="", font=FONT_S, bg="#39422e",
                                    fg="#9fd48a")
            self.lbl_rtt.pack(side="right", padx=4)
            self._ping_loop()
            if self._is_host() and self.net_info:
                tk.Button(top, text="📋 复制联机地址", font=FONT_S,
                          command=self._copy_net_addr, bg="#4a5a3a",
                          fg="white", activebackground="#5a6a48",
                          relief="flat").pack(side="right", padx=6)

        body = tk.Frame(self, bg=COL_BG)
        body.pack(fill="both", expand=True)

        # 棋盘（滚动）
        bd = tk.Frame(body, bg=COL_BG)
        bd.pack(side="left", fill="both", expand=True, padx=(8, 4), pady=8)
        self.canvas = tk.Canvas(bd, bg="#4c5a3d", highlightthickness=0)
        xs = ttk.Scrollbar(bd, orient="horizontal", command=self.canvas.xview)
        ys = ttk.Scrollbar(bd, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=xs.set, yscrollcommand=ys.set)
        xs.pack(side="bottom", fill="x")
        ys.pack(side="right", fill="y")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Button-1>", self.on_click)
        self.canvas.bind("<Motion>", self.on_motion)
        self.canvas.bind("<Leave>", lambda e: self._set_hover(None))
        # 中键/右键拖动平移（扫描拖拽）
        for btn in ("<ButtonPress-2>", "<ButtonPress-3>"):
            self.canvas.bind(btn, self._pan_start)
        for motion in ("<B2-Motion>", "<B3-Motion>"):
            self.canvas.bind(motion, self._pan_move)
        self.canvas.bind("<Button-4>", lambda e: self.canvas.yview_scroll(-2, "units"))
        self.canvas.bind("<Button-5>", lambda e: self.canvas.yview_scroll(2, "units"))
        self.bind("<r>", lambda e: self.rotate())
        self.bind("<R>", lambda e: self.rotate())

        # 右侧面板
        side = tk.Frame(body, bg="#39422e", width=300)
        side.pack(side="right", fill="y", padx=(4, 8), pady=8)
        side.pack_propagate(False)

        tk.Label(side, text="当前地牌", font=FONT, bg="#39422e",
                 fg="#cfc49f").pack(anchor="w", padx=12, pady=(10, 2))
        self.preview = tk.Canvas(side, width=PREVIEW, height=PREVIEW,
                                  bg="#2f3627", highlightthickness=0)
        self.preview.pack(padx=12)

        btns = tk.Frame(side, bg="#39422e")
        btns.pack(fill="x", padx=12, pady=6)
        self.btn_rot = tk.Button(btns, text="↻ 旋转 (R)", font=FONT,
                                 command=self.rotate, bg="#5a6b3f",
                                 fg="white", activebackground="#6b7d4c",
                                 relief="flat")
        self.btn_rot.pack(side="left", expand=True, fill="x", ipady=3)
        self.btn_discard = tk.Button(btns, text="弃牌重抽", font=FONT,
                                     command=self.discard, bg="#7a4a35",
                                     fg="white", activebackground="#8a5a42",
                                     relief="flat", state="disabled")
        self.btn_discard.pack(side="left", expand=True, fill="x", ipady=3, padx=(6, 0))

        self.lbl_hint = tk.Label(side, text="", font=FONT_S, bg="#39422e",
                                 fg="#e8c96a", wraplength=270, justify="left")
        self.lbl_hint.pack(anchor="w", padx=12, pady=(2, 6))

        tk.Label(side, text="部署随从", font=FONT, bg="#39422e",
                 fg="#cfc49f").pack(anchor="w", padx=12)
        deploy_wrap = tk.Frame(side, bg="#39422e")
        deploy_wrap.pack(fill="x", padx=12, pady=2)
        deploy_cv = tk.Canvas(deploy_wrap, bg="#39422e", highlightthickness=0,
                              height=150)
        dsb = ttk.Scrollbar(deploy_wrap, orient="vertical", command=deploy_cv.yview)
        self.deploy_box = tk.Frame(deploy_cv, bg="#39422e")
        self.deploy_box.bind("<Configure>", lambda e: deploy_cv.configure(
            scrollregion=deploy_cv.bbox("all")))
        deploy_cv.create_window((0, 0), window=self.deploy_box, anchor="nw",
                                tags="dbo")
        self.deploy_box.bind("<Configure>", lambda e: deploy_cv.configure(
            width=250))
        deploy_cv.configure(yscrollcommand=dsb.set)
        deploy_cv.pack(side="left", fill="both", expand=True)
        dsb.pack(side="right", fill="y")
        self.btn_skip = tk.Button(side, text="跳过部署 →", font=FONT,
                                  command=self.skip_deploy, bg="#5a6b3f",
                                  fg="white", activebackground="#6b7d4c",
                                  relief="flat", state="disabled")
        self.btn_skip.pack(fill="x", ipady=3, pady=(4, 8))

        tk.Label(side, text="玩家", font=FONT, bg="#39422e",
                 fg="#cfc49f").pack(anchor="w", padx=12)
        self.players_box = tk.Frame(side, bg="#39422e")
        self.players_box.pack(fill="x", padx=12, pady=2)

        tk.Label(side, text="计分板（0–50 循环）", font=FONT_S, bg="#39422e",
                 fg="#b9b092").pack(anchor="w", padx=12, pady=(10, 0))
        self.score_cv = tk.Canvas(side, width=272, height=64, bg="#2f3627",
                                  highlightthickness=0)
        self.score_cv.pack(padx=12, pady=(0, 6))

        tk.Label(side, text="对局记录", font=FONT, bg="#39422e",
                 fg="#cfc49f").pack(anchor="w", padx=12)
        log_wrap = tk.Frame(side, bg="#39422e")
        log_wrap.pack(fill="both", expand=True, padx=12, pady=(2, 10))
        self.log_text = tk.Text(log_wrap, font=FONT_S, bg="#2b3122", fg="#d8d0b0",
                                relief="flat", height=8, state="disabled",
                                wrap="none")
        log_ys = ttk.Scrollbar(log_wrap, orient="vertical",
                               command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_ys.set)
        log_ys.pack(side="right", fill="y")
        self.log_text.pack(fill="both", expand=True)

    # ------------------------------------------------------------ 坐标

    _WIN_CFG = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "assets", "window.cfg")

    def _restore_window(self) -> None:
        """恢复上次窗口几何（存在则应用）。"""
        try:
            with open(self._WIN_CFG, encoding="utf-8") as f:
                geo = f.read().strip()
            if re.match(r"^\d+x\d+[-+]?\d+[-+]?\d+$", geo):
                self.geometry(geo)
        except (OSError, ValueError):
            pass

    def _on_close(self) -> None:
        """关闭：保存窗口几何并退出（含联机资源清理）。"""
        try:
            with open(self._WIN_CFG, "w", encoding="utf-8") as f:
                f.write(self.geometry())
        except OSError:
            pass
        if self.server:
            self.server.close()
        if self.net:
            self.net.close()
        self.destroy()

    def _origin(self) -> Tuple[int, int]:
        """网格 (0,0) 的画布坐标：固定常量。

        早期实现用 canvasx(w/2)（跟随滚动），导致每次 refresh 瓦片画布坐标
        整体漂移、视图被拉回中心、棋盘无法滚动。画布坐标是绝对坐标系，
        滚动只改变"视图窗口"位置，网格原点必须恒定。
        """
        return GRID_ORIGIN, GRID_ORIGIN

    def _center_view(self) -> None:
        """把视图定位到网格中心（首次绘制后调用一次）。"""
        try:
            w = max(self.canvas.winfo_width(), 600)
            h = max(self.canvas.winfo_height(), 400)
        except tk.TclError:
            w, h = 900, 600
        try:
            x0, y0, x1, y1 = (float(v) for v in
                              self.canvas.cget("scrollregion").split())
        except (tk.TclError, ValueError):
            return
        sw, sh = x1 - x0, y1 - y0
        if sw <= 0 or sh <= 0:
            return
        fx = max(0.0, min(1.0, (GRID_ORIGIN - w / 2 - x0) / sw))
        fy = max(0.0, min(1.0, (GRID_ORIGIN - h / 2 - y0) / sh))
        self.canvas.xview_moveto(fx)
        self.canvas.yview_moveto(fy)

    def _tile_img(self, tile_id: str, rot: int, size: int):
        """取牌面贴图（整数缩放，缓存）。"""
        scale = max(1, art.MASTER // max(size, 8))
        key = (tile_id, rot, scale)
        img = self._img_cache.get(key)
        if img is None:
            img = self.sprites.tile(tile_id, rot)
            if scale > 1:
                img = img.subsample(scale)
            self._img_cache[key] = img
        return img

    def _draw_tile_sprite(self, cv, tile: TileDef, rot: int, px: float, py: float,
                          size: float, tags: str, ghost: bool = False) -> None:
        """用贴图绘制一张牌；无贴图时回退程序化绘制。"""
        if not self.sprites.ok:
            draw_tile(cv, tile, rot, px, py, size, tags)
            return
        img = self._tile_img(tile.tile_id, rot, int(size))
        cv.create_image(px + size / 2, py + size / 2, image=img, tags=tags)
        if ghost:
            cv.create_rectangle(px, py, px + size, py + size, fill="white",
                                stipple="gray50", outline="#fff2b0", width=3,
                                tags=tags)

    def _draw_meeple_sprite(self, cv, px: float, py: float, color: str,
                            farmer: bool, big: bool = False) -> None:
        if not self.sprites.ok:
            draw_meeple(cv, px, py, TILE, color, farmer)
            return
        scale = 1 if big else 2   # 大型米宝全尺寸显示
        key = (color, farmer, scale)
        img = self._img_cache.get(key)
        if img is None:
            img = self.sprites.meeple(color, farmer)
            if scale > 1:
                img = img.subsample(scale)
            self._img_cache[key] = img
        cv.create_image(px, py, image=img)

    def _flash_placed(self, x: int, y: int) -> None:
        self._flash_pos = (x, y)
        self._draw_board()
        self.after(420, self._clear_flash)

    def _clear_flash(self) -> None:
        if self._flash_pos is not None:
            self._flash_pos = None
            self._draw_board()

    def _clear_flash_later(self) -> None:
        self.after(420, self._clear_flash)

    def _float_scores(self, events: List[Dict[str, object]]) -> None:
        """计分飘字：在完成特征位置弹出"+N"上浮渐隐。"""
        eng = self.engine
        if eng is None:
            return
        for i, ev in enumerate(events):
            pos = ev.get("pos") if isinstance(ev, dict) else getattr(ev, "pos", None)
            if not pos:
                continue
            total = sum((ev.get("scores") or {}).values())                 if isinstance(ev, dict) else sum(ev.scores.values())
            if total <= 0:
                continue
            self._spawn_float(tuple(pos), "+%d" % total, i)

    def _spawn_float(self, pos: Tuple[int, int], text: str, seq: int,
                     step: int = 0) -> None:
        if self.engine is None or pos not in self.engine.board.tiles:
            return
        px, py = self.cell_px(*pos)
        cv = self.canvas
        tag = "float%d" % seq
        if step == 0:
            cv.create_text(px + TILE / 2, py + 6, text=text,
                           font=("Microsoft YaHei", 17, "bold"),
                           fill="#ffd700", tags=tag)
        if step < 6:
            cv.move(tag, 0, -5)
            if step >= 3:
                cv.itemconfig(tag, fill="#f0c060", stipple="gray75" if step == 3
                              else "gray50" if step == 4 else "gray25")
            self.after(90, lambda: self._spawn_float(pos, text, seq, step + 1))
        else:
            cv.delete(tag)

    def cell_at(self, px: float, py: float) -> Optional[Tuple[int, int]]:
        """控件像素 → 网格坐标。

        事件坐标（e.x/e.y）是控件相对值，必须先经 canvasx/canvasy 转画布坐标，
        否则棋盘滚动后与绘制位置错位（高亮/悬停对不上鼠标）。
        """
        cx = self.canvas.canvasx(px)
        cy = self.canvas.canvasy(py)
        ox, oy = self._origin()
        x = int((cx - ox + TILE / 2) // TILE)
        y = int((cy - oy + TILE / 2) // TILE)
        return int(x), int(y)

    def cell_px(self, x: int, y: int) -> Tuple[float, float]:
        ox, oy = self._origin()
        return ox + x * TILE - TILE / 2, oy + y * TILE - TILE / 2

    # ------------------------------------------------------------ 联机

    def _is_host(self) -> bool:
        return self.net_mode and self.my_seat == 0

    def _my_turn(self) -> bool:
        if self.engine is None or self.engine.game_over:
            return False
        if self.net_mode:
            return self.engine.turn_idx == self.my_seat
        return not self.engine.current_player().is_ai

    def _ping_loop(self) -> None:
        """联机：周期 ping 测往返延迟。"""
        if not self.net_mode:
            return
        try:
            if self.net and self.net.alive and not self._reconnecting:
                import time as _t
                self.net.send_ping(_t.monotonic())
        except Exception:
            pass
        finally:
            if self.net_mode:
                self.after(5000, self._ping_loop)

    def _copy_net_addr(self) -> None:
        addr = self.net_info.strip()
        self.clipboard_clear()
        self.clipboard_append(addr)
        self._flash("已复制联机地址 %s（发给朋友即可加入）" % addr)

    def _net_start(self) -> None:
        if self.net and self.engine is None:
            self.net.send_start()

    def _net_poll(self) -> None:
        """联机模式主循环：消费网络消息。单一来源（after 驱动），可重入保护。"""
        if not self.net_mode:
            return
        if self._polling:
            return
        self._polling = True
        try:
            if self.net is None or not self.net.alive:
                return
            while True:
                try:
                    msg = self.net.msgs.get_nowait()
                except queue.Empty:
                    break
                t = msg.get("t")
                if t in ("snap", "over"):
                    self._apply_snap(msg)
                elif t == "lobby":
                    self._apply_lobby(msg)
                elif t == "error":
                    self._flash("⚠ " + str(msg.get("msg", "")))
                elif t == "disconnected":
                    self._start_reconnect()
                    return
                elif t == "pong":
                    import time as _t
                    ts = float(msg.get("ts", 0))
                    self._rtt_ms = int((_t.monotonic() - ts) * 1000)
                    self.lbl_rtt.config(text="延迟 %dms" % self._rtt_ms)
                elif t == "kicked":
                    messagebox.showinfo("移出房间", "你已被房主移出房间。")
                    self.destroy()
                    return
            if self.engine is not None:
                self.refresh()
                self._maybe_prompt_special()
        finally:
            self._polling = False
            if self.net_mode and self.net and self.net.alive:
                self.after(self.poll_ms, self._net_poll)

    def _apply_lobby(self, msg: Dict[str, object]) -> None:
        self._lobby_seats = msg.get("seats") or []
        self.lbl_left.config(text="房间座位：" + " ".join(
            ("AI·%s" % s["level"]) if s["is_ai"] else str(s["name"])
            for s in self._lobby_seats))
        self.lbl_phase.config(text="等待房主开始……"
                              if not self._is_host() else "人齐后点「开始对局」")
        self._draw_players_wait()

    def _apply_snap(self, msg: Dict[str, object]) -> None:
        from .engine import CarcassonneEngine as _E
        snap = msg["snap"]
        before = getattr(self, "_prev_tile_count", 0)
        self.engine = _E.from_dict(snap)
        n = len(self.engine.board.tiles)
        if n > before and n > 1:
            last = list(self.engine.board.tiles.values())[-1]
            self._flash_pos = (last.x, last.y)
            self._clear_flash_later()
        self._prev_tile_count = n
        self.btn_start.pack_forget()
        self._float_scores(list(msg.get("events") or []))
        for ev in msg.get("events") or []:
            self._log("🏅 %s：%s" % (ev.get("detail") or ev.get("reason", ""),
                                    "，".join("%s+%d" % (c, p)
                                              for c, p in (ev.get("scores") or {}).items())))
        if msg["t"] == "over" or snap.get("game_over"):
            self._net_over = True
            self._finish_net(list(msg.get("events") or []))

    def _start_reconnect(self) -> None:
        """断线后自动同名重连（最多 10 次，间隔 2s）；失败弹窗退出。"""
        self._reconnecting = True
        self._retries = 0
        self.lbl_phase.config(text="连接断开，正在重连……")
        self.after(2000, self._try_reconnect)

    def _try_reconnect(self) -> None:
        if not self.net_mode or not self.net:
            return
        self._retries += 1
        err = self.net.reconnect()
        if err == "":
            self._reconnecting = False
            self._retries = 0
            self._flash("重连成功")
            self.after(self.poll_ms, self._net_poll)   # 重启轮询链
            return
        if self._retries >= 10 or "座位" in err or "已开始" in err:
            messagebox.showerror("连接断开",
                                 "重连失败（%s）。与主机的连接已断开。" % err)
            self.destroy()
            return
        self.lbl_phase.config(text="连接断开，正在重连（%d/10）……" % self._retries)
        self.after(2000, self._try_reconnect)

    # ------------------------------------------------------------ 交互

    def _show_help(self) -> None:
        """游戏内操作说明。"""
        dlg = tk.Toplevel(self)
        dlg.title("操作说明")
        dlg.configure(bg="#39422e")
        dlg.resizable(False, False)
        dlg.geometry("+260+150")
        tk.Label(dlg, text="📖 操作说明", font=FONT_L, bg="#39422e",
                 fg="#f2e8c9").pack(pady=(14, 6))
        text = ("【放置】点击黄色高亮格放置；悬停显示预览\n"
                 "【旋转】旋转按钮或 R 键；朝向不可行时按钮变红\n"
                 "【弃牌】牌无处可放时「弃牌重抽」可用（需全员同意）\n"
                 "【部署】点牌上黄色圆钮或右侧按钮；「跳过部署」结束回合\n"
                 "【图元】大米宝多数按 2 计；建造者延伸己特征获双回合\n"
                 "　　　　猪让主人 4 分/城（需为多数）\n"
                 "【视图】中键/右键拖动平移；滚轮上下滚动\n"
                 "【计分】城 2/牌+2/旗（大教堂 3×）、路 1/牌（客栈 2×）、修道院 9 分\n"
                 "【联机】断线自动重连；建房后「复制联机地址」发给朋友")
        
        tk.Label(dlg, text=text, font=FONT_S, bg="#39422e", fg="#e8e0c4",
                 justify="left").pack(padx=22, pady=6)
        tk.Button(dlg, text="知道了", font=FONT, command=dlg.destroy,
                  bg="#5a6b3f", fg="white", relief="flat",
                  padx=18).pack(pady=(4, 14))

    def _pan_start(self, e) -> None:
        self.canvas.scan_mark(e.x, e.y)

    def _pan_move(self, e) -> None:
        self.canvas.scan_dragto(e.x, e.y, gain=1)

    def rotate(self) -> None:
        if self.engine.phase == "place" and self.engine.current_tile:
            self.rot = (self.rot + 1) % 4
            self.refresh()

    def discard(self) -> None:
        if self.net_mode:
            if self.engine and self.engine.phase == "place" \
                    and not self.engine.can_place_anywhere() and self._my_turn():
                self.net.send_discard()
            return
        if self.engine.phase == "place" and not self.engine.can_place_anywhere():
            self.engine.discard_and_redraw()
            self.rot = 0
            self.refresh()
            self.maybe_ai_turn()

    def on_motion(self, e) -> None:
        if self.engine.phase != "place":
            self._set_hover(None)
            return
        self._set_hover(self.cell_at(e.x, e.y))

    def _set_hover(self, cell) -> None:
        if cell != self.hover_cell:
            self.hover_cell = cell
            self._draw_board()

    def on_click(self, e) -> None:
        eng = self.engine
        if eng is None or eng.game_over:
            return
        if eng.phase == "dragon":
            cell = self.cell_at(e.x, e.y)
            if cell in eng.dragon_legal_steps():
                if self.net_mode:
                    self.net.send_drag(*cell)
                else:
                    eng.dragon_move(cell)
            return
        if self.net_mode and not self._my_turn():
            return
        if eng.phase in ("place", "river"):
            cell = self.cell_at(e.x, e.y)
            if cell is None:
                return
            x, y = cell
            if (x, y, self.rot) in eng.legal_placements():
                if self.net_mode:
                    self.net.send_place(x, y, self.rot)
                else:
                    eng.place(x, y, self.rot)
                    self.hover_cell = None
                    self.refresh()
                    self._flash_placed(x, y)
                    self.maybe_ai_turn()
            else:
                self._flash("此处不能放置（边不匹配）")
        elif eng.phase == "deploy":
            # 点击部署锚点（事件坐标同样需转画布坐标）
            opts = eng.deploy_options()
            if not opts:
                return
            ex = self.canvas.canvasx(e.x)
            ey = self.canvas.canvasy(e.y)
            best, best_d = None, 1e9
            for o in opts:
                ax, ay = seg_anchor(o["kind"], eng.current_tile,
                                    eng.board.tiles[eng.placed_pos].rot, o["seg"],
                                    TILE, *self.cell_px(*eng.placed_pos))
                d = (ex - ax) ** 2 + (ey - ay) ** 2
                if d < best_d:
                    best, best_d = o, d
            if best and best_d <= (TILE * 0.22) ** 2:
                self._deploy(best)

    def _deploy(self, opt) -> None:
        if self.net_mode:
            self.net.send_deploy(opt["kind"], opt["seg"],
                                 big=bool(opt.get("big")),
                                 pos=opt.get("pos"),
                                 victim=opt.get("victim"),
                                 victim_color=opt.get("victim_color"))
            return
        eng = self.engine
        kind = opt["kind"]
        if kind == "fairy":
            eng.deploy_fairy(tuple(opt["pos"]))
        elif kind == "princess":
            eng.deploy_princess(tuple(opt["victim"]), opt["victim_color"])
        else:
            eng.deploy(kind, opt["seg"], big=bool(opt.get("big")),
                       pos=opt.get("pos"),
                       phantom=bool(eng._phantom_step)
                       and kind in ("city", "road", "farm", "mon"))
        self._emit_events()
        self.refresh()
        self.maybe_ai_turn()

    def skip_deploy(self) -> None:
        if self.net_mode:
            if self.engine and self.engine.phase == "deploy" and self._my_turn():
                self.net.send_skip()
            return
        if self.engine.phase == "deploy":
            self.engine.skip_deploy()
            self._emit_events()
            self.refresh()
            self.maybe_ai_turn()

    # ---- M18 伯爵城：重部署回合 / 进城部署（人类决策弹窗）----

    _QNAME = {"castle": "城堡区（城）", "market": "市场区（农场）",
              "blacksmith": "铁匠区（路）", "cathedral": "大教堂区（修道院）"}

    def _maybe_prompt_special(self) -> None:
        """联机模式下：轮到本座决策重部署/进城部署时弹窗（本地走 maybe_ai_turn）。"""
        eng = self.engine
        if eng is None or eng.game_over:
            return
        if eng.phase == "redeploy":
            st = eng.redeploy_state()
            if st is None or st["player"] != self.my_seat:
                return
            key = ("rd", tuple(st["root"]), st["player"], len(eng.events))
            if key == self._prompt_key:
                return
            self._prompt_key = key
            self.after(200, self._prompt_redeploy)
        elif eng.phase == "count_deploy":
            if eng._placer_idx != self.my_seat:
                return
            key = ("cd", eng._placer_idx, len(eng.events))
            if key == self._prompt_key:
                return
            self._prompt_key = key
            self.after(200, self._prompt_count_deploy)
        elif eng.phase == "castle" and eng._castle_queue:
            meta = eng.board._meta[eng._castle_queue[0]]
            winners, _t = (eng._city_majority(meta) if meta.mayors
                           else meeple_majority(meta.meeples))
            occ = eng._player_by_color(winners[0] if winners
                                       else eng.current_player().color)
            if self.net_mode and occ.idx != self.my_seat:
                return
            key = ("cs", tuple(eng._castle_queue[0]), len(eng.events))
            if key == self._prompt_key:
                return
            self._prompt_key = key
            self.after(200, self._prompt_castle)
        elif eng.phase == "bazaar":
            b = eng.bazaar
            if not b:
                return
            seat = None
            if b["phase"] == "select":
                seat = b["selector"]
            elif b["phase"] == "bid":
                seat = b.get("bid_turn")
            elif b["phase"] == "decide":
                seat = b["selector"]
            if self.net_mode and seat != self.my_seat:
                return
            key = ("bz", b["phase"], seat, b.get("bid"), len(b.get("got") or {}))
            if key == self._prompt_key:
                return
            self._prompt_key = key
            self.after(200, self._prompt_bazaar)
        elif eng.phase == "gold":
            if self.net_mode and eng.players[eng.turn_idx].idx != self.my_seat:
                return
            key = ("gd", eng.placed_pos, len(eng.events))
            if key == self._prompt_key:
                return
            self._prompt_key = key
            self.after(200, self._prompt_gold)
        elif eng.phase == "magewitch":
            if self.net_mode and eng.players[eng.turn_idx].idx != self.my_seat:
                return
            key = ("mw", eng.mage, eng.witch, len(eng.events))
            if key == self._prompt_key:
                return
            self._prompt_key = key
            self.after(200, self._prompt_magewitch)
        elif eng.phase == "tunnel":
            if self.net_mode and eng.players[eng.turn_idx].idx != self.my_seat:
                return
            key = ("tn", tuple(eng.tunnel_options()), len(eng.events))
            if key == self._prompt_key:
                return
            self._prompt_key = key
            self.after(200, self._prompt_tunnel)
        elif eng.phase == "escape":
            if self.net_mode and eng.players[eng.turn_idx].idx != self.my_seat:
                return
            key = ("es", tuple(eng.escape_options()), len(eng.events))
            if key == self._prompt_key:
                return
            self._prompt_key = key
            self.after(200, self._prompt_escape)
        elif eng.phase == "crop" and eng.crop:
            if eng.crop["mode"] is None:
                seat = eng._placer_idx
            else:
                seat = eng.crop["order"][eng.crop["pos"]]
            if self.net_mode and seat != self.my_seat:
                return
            key = ("cr", eng.crop["kind"], eng.crop["mode"], seat,
                   eng.crop["pos"], len(eng.events))
            if key == self._prompt_key:
                return
            self._prompt_key = key
            self.after(200, self._prompt_crop)
        elif eng.phase == "robber" and eng.robber_phase:
            seat = eng.robber_phase["order"][eng.robber_phase["pos"]]
            if self.net_mode and seat != self.my_seat:
                return
            key = ("rb", seat, eng.robber_phase["pos"], len(eng.events))
            if key == self._prompt_key:
                return
            self._prompt_key = key
            self.after(200, self._prompt_robber)
        elif eng.phase == "shepherd":
            if self.net_mode and eng.players[eng.turn_idx].idx != self.my_seat:
                return
            key = ("shp", eng.turn_idx, len(eng.events))
            if key == self._prompt_key:
                return
            self._prompt_key = key
            self.after(200, self._prompt_shepherd)
        elif eng.phase == "plague" and eng.plague:
            seat = eng.plague["order"][int(eng.plague["pos"])]
            if self.net_mode and seat != self.my_seat:
                return
            key = ("plg", seat, eng.plague["pos"], len(eng.events))
            if key == self._prompt_key:
                return
            self._prompt_key = key
            self.after(200, self._prompt_plague)

    def _prompt_castle(self) -> None:
        eng = self.engine
        if eng.phase != "castle" or not eng._castle_queue:
            return
        convert = messagebox.askyesno(
            "城堡", "这座 2 牌小城可改建为城堡（改建后不得立刻得分，\n"
            "邻格下一座完成的结构会给城堡主同等分数）。要改建吗？")
        if self.net_mode:
            self.net.send_castle(convert)
        else:
            eng.convert_castle(convert)
            self._emit_events()
            self.refresh()
            self.maybe_ai_turn()

    def _prompt_bazaar(self) -> None:
        eng = self.engine
        b = eng.bazaar
        if eng.phase != "bazaar" or not b:
            return
        if b["phase"] == "select":
            names = [t.tile_id if hasattr(t, "tile_id") else t
                     for t in b["tiles"]]
            idx = 0
            if len(names) > 1:
                top = tk.Toplevel(self)
                top.title("集市 · 选牌")
                top.transient(self)
                top.grab_set()
                chosen = {"i": 0}

                def _pick(i):
                    chosen["i"] = i
                    top.destroy()

                tk.Label(top, text="选择一张牌并出价（可为 0）：").pack(padx=12, pady=6)
                for i, n in enumerate(names):
                    tk.Button(top, text="%d. %s" % (i + 1, n),
                              command=lambda i=i: _pick(i)).pack(fill="x", padx=12, pady=2)
                top.wait_window()
                idx = chosen["i"]
            if self.net_mode:
                self.net.send_bazaar("select", idx=idx, bid=0)
            else:
                eng.bazaar_select(idx, 0)
                self.refresh()
                self.maybe_ai_turn()
            return
        if b["phase"] == "bid":
            if self.net_mode:
                self.net.send_bazaar("pass")
            else:
                eng.bazaar_pass()
                self.refresh()
                self.maybe_ai_turn()
            return
        if b["phase"] == "decide":
            keep = messagebox.askyesno(
                "集市", "付给最高出价者 %d 分留下这张牌？\n选否则卖给最高出价者。"
                % int(b.get("bid") or 0))
            if self.net_mode:
                self.net.send_bazaar("resolve", keep=keep)
            else:
                eng.bazaar_resolve(keep)
                self.refresh()
                self.maybe_ai_turn()

    # ---- M20 迷你扩展：金矿/法师女巫/隧道/脱困/怪圈/强盗 ----

    def _send_or_local(self, msg, local_fn):
        """联机发消息，本地直接执行并推进（本地热座共用出口）。"""
        if self.net_mode:
            getattr(self.net, msg.pop("_api"))(**msg)
        else:
            local_fn()
            self._emit_events()
            self.refresh()
            self.maybe_ai_turn()

    def _prompt_gold(self) -> None:
        eng = self.engine
        if eng.phase != "gold":
            return
        opts = eng.gold_options()
        if not opts:
            return
        top = tk.Toplevel(self)
        top.title("金矿 · 落金块")
        top.transient(self)
        top.grab_set()
        tk.Label(top, text="第二块金子落在哪张相邻牌上？", font=FONT_S).pack(
            padx=12, pady=(10, 4))

        def _pick(pos):
            top.destroy()
            self._send_or_local({"_api": "send_gold", "pos": pos},
                                lambda: eng.place_gold(pos))

        row = tk.Frame(top)
        row.pack(padx=10, pady=(0, 10))
        for pos in opts:
            tk.Button(row, text="(%d,%d)" % pos, font=FONT_S, width=7,
                      command=lambda p=pos: _pick(p)).pack(side="left", padx=3)

    def _prompt_magewitch(self) -> None:
        eng = self.engine
        if eng.phase != "magewitch":
            return
        opts = eng.mw_options()
        cands = [(f, n) for f in ("mage", "witch") for n in opts[f]]
        top = tk.Toplevel(self)
        top.title("法师与女巫")
        top.transient(self)
        top.grab_set()
        tip = "选择一个未完成的城/路段落位（法师 +1 分/牌，女巫减半）。"
        tk.Label(top, text=tip, font=FONT_S).pack(padx=12, pady=(10, 4))
        body = tk.Frame(top)
        body.pack(padx=10, pady=(0, 6))

        def _pick(fig, node):
            top.destroy()
            self._send_or_local(
                {"_api": "send_mw", "fig": fig, "node": node},
                lambda: (eng.mw_remove(fig) if node is None
                         else eng.mw_move(fig, node)))

        if not cands:
            tk.Label(body, text="无合法目标", font=FONT_S).pack()
        for fig, node in cands[:24]:
            nm = "法师" if fig == "mage" else "女巫"
            tk.Button(body, text="%s (%d,%d)#%d" % (nm, node[0], node[1],
                                                    node[3]),
                      font=FONT_S, width=16,
                      command=lambda f=fig, n=node: _pick(f, n)
                      ).pack(side="top", anchor="w", pady=1)
        btns = tk.Frame(top)
        btns.pack(pady=(0, 10))
        for fig in ("mage", "witch"):
            if getattr(eng, fig) is not None:
                tk.Button(btns, text="收回%s" % ("法师" if fig == "mage"
                                                 else "女巫"),
                          font=FONT_S,
                          command=lambda f=fig: _pick(f, None)
                          ).pack(side="left", padx=4)

    def _prompt_tunnel(self) -> None:
        eng = self.engine
        if eng.phase != "tunnel":
            return
        top = tk.Toplevel(self)
        top.title("隧道 · 令牌")
        top.transient(self)
        top.grab_set()
        tk.Label(top, text="用一枚隧道令牌占领隧道口？（同色第二枚即贯通）",
                 font=FONT_S).pack(padx=12, pady=(10, 4))
        body = tk.Frame(top)
        body.pack(padx=10, pady=(0, 6))
        opts = eng.tunnel_options()

        def _claim(node):
            top.destroy()
            self._send_or_local({"_api": "send_tunnel", "node": node},
                                lambda: eng.tunnel_claim(node))

        def _skip():
            top.destroy()
            self._send_or_local({"_api": "send_tunnel", "node": None,
                                 "skip": True}, eng.tunnel_skip)

        if not opts:
            tk.Label(body, text="场上没有空隧道口", font=FONT_S).pack()
        for node in opts[:20]:
            tk.Button(body, text="隧道口 (%d,%d)#%d" % (node[0], node[1],
                                                       node[3]),
                      font=FONT_S, width=16,
                      command=lambda n=node: _claim(n)).pack(
                side="top", anchor="w", pady=1)
        tk.Button(top, text="本回合不放", font=FONT_S, command=_skip).pack(
            pady=(0, 10))

    def _prompt_escape(self) -> None:
        eng = self.engine
        if eng.phase != "escape":
            return
        opts = eng.escape_options()
        top = tk.Toplevel(self)
        top.title("围攻 · 脱困")
        top.transient(self)
        top.grab_set()
        tk.Label(top, text="邻格有修道院：可从被围城撤回一名骑士。", font=FONT_S
                 ).pack(padx=12, pady=(10, 4))
        body = tk.Frame(top)
        body.pack(padx=10, pady=(0, 6))

        def _go(node):
            top.destroy()
            self._send_or_local({"_api": "send_escape", "node": node},
                                lambda: eng.escape_move(node))

        for node in opts[:12]:
            tk.Button(body, text="撤回骑士 (%d,%d)#%d" % (node[0], node[1],
                                                        node[3]),
                      font=FONT_S, width=16,
                      command=lambda n=node: _go(n)).pack(
                side="top", anchor="w", pady=1)
        tk.Button(top, text="留在城里", font=FONT_S,
                  command=lambda: _go(None)).pack(pady=(0, 10))

    def _prompt_crop(self) -> None:
        eng = self.engine
        if eng.phase != "crop" or not eng.crop:
            return
        kind = {"farm": "农夫", "road": "随从", "city": "骑士"}[
            eng.crop["kind"]]
        if eng.crop["mode"] is None:
            mode = messagebox.askyesno(
                "麦田怪圈", "选择怪圈效果：\n"
                "「是」= 各玩家可部署一名同伴到己方%s所在特征\n"
                "「否」= 各玩家必须收回一名%s" % (kind, kind))
            mode = "A" if mode else "B"
            self._send_or_local({"_api": "send_crop", "mode": mode},
                                lambda: eng.crop_choose(mode))
            return
        opts = eng.crop_options()
        act = "部署同伴" if eng.crop["mode"] == "A" else "收回随从"
        top = tk.Toplevel(self)
        top.title("麦田怪圈 · %s" % act)
        top.transient(self)
        top.grab_set()
        tk.Label(top, text="对哪名%s执行「%s」？" % (kind, act),
                 font=FONT_S).pack(padx=12, pady=(10, 4))
        body = tk.Frame(top)
        body.pack(padx=10, pady=(0, 6))

        def _do(node):
            top.destroy()
            self._send_or_local({"_api": "send_crop", "node": node},
                                lambda: eng.crop_act(node))

        for o in opts[:16]:
            node = o["node"]
            tk.Button(body, text=o["label"], font=FONT_S, width=18,
                      command=lambda n=node: _do(n)).pack(
                side="top", anchor="w", pady=1)
        if eng.crop["mode"] == "A":
            tk.Button(top, text="跳过", font=FONT_S,
                      command=lambda: _do(None)).pack(pady=(0, 10))

    def _prompt_robber(self) -> None:
        eng = self.engine
        if eng.phase != "robber" or not eng.robber_phase:
            return
        top = tk.Toplevel(self)
        top.title("强盗 · 上轨道")
        top.transient(self)
        top.grab_set()
        tk.Label(top, text="把强盗放上哪格？（他人随从所在格；得分时偷走一半）",
                 font=FONT_S).pack(padx=12, pady=(10, 4))
        body = tk.Frame(top)
        body.pack(padx=10, pady=(0, 6))
        spaces = eng.robber_options()

        def _put(space):
            top.destroy()
            self._send_or_local({"_api": "send_robber", "space": space},
                                lambda: eng.robber_place(space))

        if not spaces:
            tk.Label(body, text="无可选格", font=FONT_S).pack()
        for s in spaces[:16]:
            tk.Button(body, text="第 %d 格" % s, font=FONT_S, width=10,
                      command=lambda v=s: _put(v)).pack(side="left", padx=3)
        tk.Button(top, text="不上轨道", font=FONT_S,
                  command=lambda: _put(None)).pack(pady=(0, 10))

    def _prompt_shepherd(self) -> None:
        eng = self.engine
        if eng.phase != "shepherd":
            return
        root = eng.shepherd_pending_action()
        total = 0
        if root is not None:
            total = sum(sum(s["tokens"]) for s in eng._field_shepherds(root))
        expand = messagebox.askyesno(
            "牧羊人", "当前羊群 %d 只。\n"
            "「是」= 扩群：再抽一张（狼则全草场羊群散）\n"
            "「否」= 入圈：全草场各牧羊人 + %d 分" % (total, total))
        if self.net_mode:
            self.net.send_shepherd(expand)
        else:
            eng.shepherd_act(expand)
            self._emit_events()
            self.refresh()
            self.maybe_ai_turn()

    def _prompt_plague(self) -> None:
        eng = self.engine
        if eng.phase != "plague" or not eng.plague:
            return
        opts = eng.plague_options()
        if not opts:
            eng.plague_act(None) if not self.net_mode else \
                self.net.send_plague(None)
            return
        top = tk.Toplevel(self)
        top.title("瘟疫 · 收回随从")
        top.transient(self)
        top.grab_set()
        tk.Label(top, text="瘟疫！收回一名己方场上随从：", font=FONT_S).pack(
            padx=12, pady=(10, 4))
        body = tk.Frame(top)
        body.pack(padx=10, pady=(0, 8))

        def _go(node):
            top.destroy()
            if self.net_mode:
                self.net.send_plague(node)
            else:
                eng.plague_act(node)
                self._emit_events()
                self.refresh()
                self.maybe_ai_turn()

        for node in opts[:16]:
            tk.Button(body, text="收回 (%d,%d)#%d" % (node[0], node[1],
                                                     node[3]),
                      font=FONT_S, width=16,
                      command=lambda n=node: _go(n)).pack(
                side="top", anchor="w", pady=1)

    def _prompt_redeploy(self) -> None:
        eng = self.engine
        st = eng.redeploy_state() if eng.phase == "redeploy" else None
        if st is None:
            return
        p = eng.players[st["player"]]
        move = messagebox.askyesno(
            "伯爵城 · 重部署回合",
            "%s：是否把%s的全部随从移入正在结算的特征？\n"
            "（伯爵在 %s，该区被封锁）" % (p.name, self._QNAME[st["quarter"]],
                                        self._QNAME.get(eng.count["count_pos"],
                                                        eng.count["count_pos"])))
        if self.net_mode:
            self.net.send_redeploy(move)
        else:
            eng.redeploy_move(move)
            self._emit_events()
            self.refresh()
            self.maybe_ai_turn()

    def _prompt_count_deploy(self) -> None:
        eng = self.engine
        if eng.phase != "count_deploy":
            return
        p = eng.players[eng._placer_idx]
        opts = eng.count_deploy_options()
        top = tk.Toplevel(self)
        top.title("伯爵城 · 进城部署")
        top.transient(self)
        top.grab_set()
        tk.Label(top, text="%s 触发计分但未得分——可部署 1 名随从进城，\n"
                           "并可同时把伯爵移到任一区（伯爵所在区封锁移出）。"
                 % p.name, justify="left").pack(padx=14, pady=8)
        move_var = tk.StringVar(value="")
        qfrm = tk.Frame(top)
        qfrm.pack(padx=14, pady=2)
        tk.Label(qfrm, text="伯爵移至：").pack(side="left")
        for q in ("castle", "market", "blacksmith", "cathedral"):
            tk.Radiobutton(qfrm, text=self._QNAME[q].split("（")[0],
                           variable=move_var, value=q).pack(side="left")
        btns = tk.Frame(top)
        btns.pack(padx=14, pady=6)

        def _finish(opt) -> None:
            to = move_var.get() or None
            if self.net_mode:
                self.net.send_count_deploy(opt["quarter"], opt["fig"], to)
            else:
                eng.deploy_count(opt["quarter"], opt["fig"], to)
                self._emit_events()
                self.refresh()
                self.maybe_ai_turn()
            top.destroy()

        def _skip() -> None:
            if self.net_mode:
                self.net.send_count_skip()
            else:
                eng.skip_count_deploy()
                self.refresh()
                self.maybe_ai_turn()
            top.destroy()

        for i, o in enumerate(opts):
            tk.Button(btns, text=o["label"], width=24,
                      command=lambda o=o: _finish(o)).grid(
                row=i // 2, column=i % 2, padx=4, pady=3)
        tk.Button(top, text="跳过（不部署）", command=_skip).pack(pady=6)

    def _flash(self, msg: str) -> None:
        self.lbl_phase.config(text=msg)
        self.after(1500, lambda: self.refresh())

    def _emit_events(self) -> None:
        evs = self.engine.events[self._logged_ev_idx:]
        self._logged_ev_idx = len(self.engine.events)
        self._float_scores(evs)
        for ev in evs:
            self._log("🏅 %s：%s" % (ev.detail or ev.reason,
                                    "，".join("%s+%d" % (c, p)
                                              for c, p in ev.scores.items())))

    def _log(self, line: str) -> None:
        self.log_text.config(state="normal")
        self.log_text.insert("end", line + "\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    # ------------------------------------------------------------ AI

    def maybe_ai_turn(self) -> None:
        if self.net_mode:
            return
        if self.engine.game_over:
            self._finish()
            return
        # P&D：龙阶段的 AI 决策者
        if ("pd" in self.engine.expansions
                and self.engine.phase == "dragon"):
            dec = self.engine.dragon_decider_player()
            if dec is not None and dec.is_ai:
                self.after(300, self._ai_step)
            return
        # M18 伯爵城：重部署回合 / 进城部署
        if self.engine.phase == "redeploy":
            st = self.engine.redeploy_state()
            if st is not None:
                if self.engine.players[st["player"]].is_ai:
                    self.after(300, self._ai_step)
                else:
                    self.after(250, self._prompt_redeploy)
            return
        if self.engine.phase == "count_deploy":
            if self.engine.players[self.engine._placer_idx].is_ai:
                self.after(300, self._ai_step)
            else:
                self.after(250, self._prompt_count_deploy)
            return
        if self.engine.phase == "castle" and self.engine._castle_queue:
            meta = self.engine.board._meta[self.engine._castle_queue[0]]
            winners, _t = (self.engine._city_majority(meta) if meta.mayors
                           else meeple_majority(meta.meeples))
            occ = self.engine._player_by_color(
                winners[0] if winners else self.engine.current_player().color)
            if occ.is_ai:
                self.after(300, self._ai_step)
            else:
                self.after(250, self._prompt_castle)
            return
        if self.engine.phase == "bazaar":
            b = self.engine.bazaar
            if b:
                if b["phase"] == "select":
                    idx = b["selector"]
                elif b["phase"] == "bid":
                    idx = b.get("bid_turn")
                else:
                    idx = b["selector"]
                if self.engine.players[idx].is_ai:
                    self.after(300, self._ai_step)
                else:
                    self.after(250, self._prompt_bazaar)
            return
        # M20 迷你扩展阶段（决策者=当前回合玩家或轮次玩家）
        if self.engine.phase in ("gold", "magewitch", "tunnel", "escape"):
            if self.engine.players[self.engine.turn_idx].is_ai:
                self.after(300, self._ai_step)
            else:
                self.after(250, self._maybe_prompt_special)
            return
        if self.engine.phase == "crop" and self.engine.crop:
            idx = (self.engine._placer_idx if self.engine.crop["mode"] is None
                   else self.engine.crop["order"][self.engine.crop["pos"]])
            if self.engine.players[idx].is_ai:
                self.after(300, self._ai_step)
            else:
                self.after(250, self._maybe_prompt_special)
            return
        if self.engine.phase == "robber" and self.engine.robber_phase:
            idx = self.engine.robber_phase["order"][
                self.engine.robber_phase["pos"]]
            if self.engine.players[idx].is_ai:
                self.after(300, self._ai_step)
            else:
                self.after(250, self._maybe_prompt_special)
            return
        if self.engine.phase == "shepherd":
            if self.engine.players[self.engine.turn_idx].is_ai:
                self.after(300, self._ai_step)
            else:
                self.after(250, self._maybe_prompt_special)
            return
        if self.engine.phase == "plague" and self.engine.plague:
            idx = self.engine.plague["order"][int(self.engine.plague["pos"])]
            if self.engine.players[idx].is_ai:
                self.after(300, self._ai_step)
            else:
                self.after(250, self._maybe_prompt_special)
            return
        p = self.engine.current_player()
        if p.is_ai:
            self.after(420, self._ai_step)

    def _ai_step(self) -> None:
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        if self.net_mode:
            return
        eng = self.engine
        if eng.game_over:
            self._finish()
            return
        p = eng.current_player()
        bot = self.bots.get(p.idx)
        if bot is None and eng.phase not in (
                "dragon", "redeploy", "count_deploy", "castle", "bazaar",
                "gold", "magewitch", "tunnel", "escape", "crop", "robber",
                "shepherd", "plague"):
            return
        if eng.phase == "dragon":
            legal = eng.dragon_legal_steps()
            if legal:
                pos = bot.choose_dragon_step(eng, legal)
                eng.dragon_move(pos)
            self._emit_events()
            self.refresh()
            self.after(300, self._ai_step)
            return
        if eng.phase == "redeploy":
            eng.redeploy_move(bot.choose_redeploy(eng))
            self._emit_events()
            self.refresh()
            self.maybe_ai_turn()
            return
        if eng.phase == "count_deploy":
            act = bot.choose_count_deploy(eng)
            if act is None:
                eng.skip_count_deploy()
            else:
                eng.deploy_count(act["option"]["quarter"],
                                 act["option"]["fig"],
                                 act.get("count_move_to"))
            self._emit_events()
            self.refresh()
            self.maybe_ai_turn()
            return
        if eng.phase == "castle":
            bot = self.bots.get(p.idx) or BotAI("normal")
            eng.convert_castle(bot.choose_castle(eng))
            self._emit_events()
            self.refresh()
            self.maybe_ai_turn()
            return
        # M20 迷你扩展阶段
        if eng.phase in ("gold", "magewitch", "tunnel", "escape"):
            idx = eng.turn_idx
            bot = self.bots.get(idx) or BotAI("normal")
            if eng.phase == "gold":
                eng.place_gold(bot.choose_gold(eng))
            elif eng.phase == "magewitch":
                fig, node = bot.choose_mw(eng)
                if node is None:
                    eng.mw_remove(fig)
                else:
                    eng.mw_move(fig, node)
            elif eng.phase == "tunnel":
                node = bot.choose_tunnel(eng)
                if node is None:
                    eng.tunnel_skip()
                else:
                    eng.tunnel_claim(node)
            else:
                eng.escape_move(bot.choose_escape(eng))
            self._emit_events()
            self.refresh()
            self.maybe_ai_turn()
            return
        if eng.phase == "crop" and eng.crop:
            idx = (eng._placer_idx if eng.crop["mode"] is None
                   else eng.crop["order"][eng.crop["pos"]])
            bot = self.bots.get(idx) or BotAI("normal")
            act = bot.choose_crop(eng)
            if eng.crop["mode"] is None:
                eng.crop_choose(act or "A")
            else:
                eng.crop_act(act)
            self._emit_events()
            self.refresh()
            self.maybe_ai_turn()
            return
        if eng.phase == "robber" and eng.robber_phase:
            idx = eng.robber_phase["order"][eng.robber_phase["pos"]]
            bot = self.bots.get(idx) or BotAI("normal")
            eng.robber_place(bot.choose_robber(eng))
            self._emit_events()
            self.refresh()
            self.maybe_ai_turn()
            return
        if eng.phase == "shepherd":
            idx = eng.turn_idx
            bot = self.bots.get(idx) or BotAI("normal")
            eng.shepherd_act(bot.choose_shepherd(eng))
            self._emit_events()
            self.refresh()
            self.maybe_ai_turn()
            return
        if eng.phase == "plague" and eng.plague:
            idx = eng.plague["order"][int(eng.plague["pos"])]
            bot = self.bots.get(idx) or BotAI("normal")
            eng.plague_act(bot.choose_plague(eng))
            self._emit_events()
            self.refresh()
            self.maybe_ai_turn()
            return
        if eng.phase == "bazaar":
            b = eng.bazaar
            idx = (b["selector"] if b["phase"] in ("select", "decide")
                   else b.get("bid_turn"))
            bot = self.bots.get(idx) or BotAI("normal")
            act = bot.choose_bazaar(eng)
            if not act:
                if b["phase"] == "bid":
                    eng.bazaar_pass()
                elif b["phase"] == "decide":
                    eng.bazaar_resolve(False)
                else:
                    eng.bazaar_select(0, 0)
            elif act[0] == "select":
                eng.bazaar_select(act[1], act[2] if len(act) > 2 else 0)
            elif act[0] == "pass":
                eng.bazaar_pass()
            elif act[0] == "resolve":
                eng.bazaar_resolve(bool(act[1]) if len(act) > 1 else False)
            self.refresh()
            self.maybe_ai_turn()
            return
        if eng.phase in ("place", "river"):
            tries = 0
            while not eng.legal_placements():
                eng.discard_and_redraw()
                tries += 1
                if eng.game_over:
                    self._finish()
                    return
                if tries > 20:
                    return
            (x, y, rot), _ = bot.choose_move(eng)
            self.rot = rot
            eng.place(x, y, rot)
            self._log("🤖 %s 放置 %s" % (p.name, eng.board.tiles[(x, y)].tile_id))
            self.refresh()
            self._flash_placed(x, y)
            self.after(360, self._ai_step)
        elif eng.phase == "deploy":
            # M21：塔动作优先（建塔/驻塔/赎金；无动作再常规部署）
            tpos = bot.choose_tower_piece(eng)
            if tpos is not None:
                eng.tower_place(tpos[0], tpos[1])
                self._emit_events()
                self.refresh()
                self.maybe_ai_turn()
                return
            ttop = bot.choose_tower_top(eng)
            if ttop is not None:
                eng.tower_deploy_top(ttop)
                self._emit_events()
                self.refresh()
                self.maybe_ai_turn()
                return
            ridx = bot.choose_ransom(eng)
            if ridx is not None:
                eng.ransom(ridx)
                self._emit_events()
                self.refresh()
                self.maybe_ai_turn()
                return
            opt = bot.choose_deploy(eng)
            if opt is not None:
                if opt["kind"] == "fairy":
                    eng.deploy_fairy(tuple(opt["pos"]))
                elif opt["kind"] == "princess":
                    eng.deploy_princess(tuple(opt["victim"]), opt["victim_color"])
                else:
                    eng.deploy(opt["kind"], opt["seg"], big=bool(opt.get("big")))
            else:
                eng.skip_deploy()
            self._emit_events()
            self.refresh()
            self.maybe_ai_turn()

    # ------------------------------------------------------------ 绘制

    def refresh(self) -> None:
        eng = self.engine
        if eng is None:
            # 联机等待开局
            self.lbl_turn.config(text="联机房间", fg="#f2e8c9")
            self.lbl_left.config(
                text="本机 IP %s%s" % (self.net_info,
                                      "　你是房主" if self._is_host() else ""))
            self._draw_players_wait()
            return
        p = eng.current_player()
        if eng.game_over:
            turn_text = "对局结束"
        elif self.net_mode:
            you = "（你）" if eng.turn_idx == self.my_seat else ""
            turn_text = "%s 的回合%s" % (p.name, you)
        else:
            turn_text = "%s 的回合" % p.name
        self.lbl_turn.config(text=turn_text, fg=COLOR_HEX.get(p.color, "#fff"))
        self.lbl_left.config(text="剩余地牌 %d 张" % eng.tiles_left())

        if eng.game_over:
            self.lbl_phase.config(text="终局结算")
        elif eng.phase == "dragon":
            dec = eng.dragon_decider_player()
            self.lbl_phase.config(text="🐉 龙移动：剩 %d 步 — 轮到 %s（点击相邻已放牌）"
                                  % (eng.dragon["steps_left"], dec.name))
        elif eng.phase == "redeploy":
            st = eng.redeploy_state()
            if st is not None:
                who = eng.players[st["player"]].name
                self.lbl_phase.config(
                    text="🏰 伯爵城重部署：轮到 %s 决定（%s）"
                         % (who, self._QNAME[st["quarter"]]))
            else:
                self.lbl_phase.config(text="🏰 伯爵城重部署")
        elif eng.phase == "count_deploy":
            self.lbl_phase.config(text="🏰 %s 可部署 1 名随从进伯爵城"
                                  % eng.players[eng._placer_idx].name)
        elif eng.phase == "castle":
            self.lbl_phase.config(text="🏰 2 牌小城可改建为城堡")
        elif eng.phase == "bazaar":
            b = eng.bazaar or {}
            self.lbl_phase.config(text="🛒 集市拍卖（%s）" % b.get("phase", ""))
        elif eng.phase == "gold":
            self.lbl_phase.config(text="🪙 金矿：第二块金子落在相邻牌")
        elif eng.phase == "magewitch":
            self.lbl_phase.config(text="🧙 法师与女巫：落位或移动")
        elif eng.phase == "tunnel":
            self.lbl_phase.config(text="🚇 隧道：放置令牌（可放弃）")
        elif eng.phase == "escape":
            self.lbl_phase.config(text="🏃 围攻脱困：撤回被围城骑士")
        elif eng.phase == "crop":
            c = eng.crop or {}
            self.lbl_phase.config(text="🌾 麦田怪圈（%s）"
                                  % c.get("kind", ""))
        elif eng.phase == "robber":
            self.lbl_phase.config(text="🦹 强盗上轨道")
        elif eng.phase == "shepherd":
            self.lbl_phase.config(text="🧑‍🌾 牧羊人：扩群或入圈")
        elif eng.phase == "plague":
            self.lbl_phase.config(text="🎡 瘟疫：收回一名场上随从")
        elif eng.phase in ("place", "river"):
            extra = "（建造者双回合）" if eng._extra_turn else ""
            if eng.phase == "river":
                self.lbl_phase.config(text="🌊 河流阶段：放置河流牌（剩余 %d 张）"
                                      % (len(eng.river_pile) + 1))
            else:
                self.lbl_phase.config(text="阶段：放置地牌" + extra)
        else:
            self.lbl_phase.config(text="阶段：部署随从（点击牌上圆钮）")

        self._draw_board()
        self._draw_preview()
        self._draw_deploy_panel()
        self._draw_players()
        self._draw_scoreboard()

        # 按钮
        human_turn = self._my_turn()
        placing = eng.phase in ("place", "river")
        self.btn_rot.config(state="normal" if human_turn and placing else "disabled")
        if human_turn and placing:
            ok_rots = {r for (_x, _y, r) in eng.legal_placements()}
            # 当前朝向不可行 → 旋转按钮变警示色提醒
            self.btn_rot.config(
                bg="#b5482f" if ok_rots and self.rot not in ok_rots else "#5a6b3f")
        else:
            self.btn_rot.config(bg="#5a6b3f")
        self.btn_discard.config(
            state="normal" if human_turn and placing
            and not eng.can_place_anywhere() else "disabled")
        self.btn_skip.config(state="normal" if human_turn
                             and eng.phase == "deploy" else "disabled")

        # 提示
        if eng.game_over:
            self.lbl_hint.config(text="")
        elif not human_turn:
            self.lbl_hint.config(text="等待对方玩家……" if self.net_mode
                                 else "AI 思考中……")
        elif eng.phase == "place":
            if eng.can_place_anywhere():
                ok_rots = sorted({r for (_x, _y, r) in eng.legal_placements()})
                self.lbl_hint.config(
                    text="点击高亮格放置；R 旋转（当前朝向 %s）\n可行朝向：%s" %
                         (["北", "东", "南", "西"][self.rot],
                          " ".join(str(r) for r in ok_rots)))
            else:
                self.lbl_hint.config(text="这张牌无处可放 → 点击「弃牌重抽」")
        else:
            self.lbl_hint.config(text="点击牌上的圆钮部署随从，或跳过")

    def _static_fingerprint(self, eng) -> tuple:
        """静态层指纹：牌/米宝/图元任一变化才重绘静态层。"""
        tiles = tuple(sorted((pt.tile_id, pt.x, pt.y, pt.rot, pt.placed_by)
                             for pt in eng.board.tiles.values()))
        meeples = []
        figures = []
        for root in eng.board.roots():
            meta = eng.board._meta[root]
            meeples.extend(sorted((n, c, s) for n, c, s in meta.meeple_nodes))
            for key, nodes in sorted(meta.figure_nodes.items()):
                figures.extend((key[0], key[1], tuple(nodes)))
        bridges = tuple(sorted((p[0], p[1], a)
                               for p, a in eng.board.bridges.items()))
        castles = tuple(sorted((c["owner"], tuple(c["tiles"]), c["scored"])
                               for c in eng.castles))
        gold = tuple(sorted(eng.gold_map.items()))
        tunnels = tuple(sorted((k, v) for k, v in
                               eng.board.tunnel_tokens.items()))
        twr = tuple(sorted((t["pos"], t["height"],
                            (t["top"] or {}).get("color"))
                           for t in eng.towers))
        shp = tuple(sorted((s["color"], s["node"], sum(s["tokens"]))
                           for s in eng.shepherds))
        return (tiles, tuple(meeples), tuple(figures), bridges, castles,
                gold, tunnels, eng.mage, eng.witch, twr, shp)

    def _draw_board(self) -> None:
        cv = self.canvas
        eng = self.engine

        # ---- 分层：静态层（牌/米宝/图元）指纹缓存，动态层每次重绘
        fp = self._static_fingerprint(eng)
        if fp != getattr(self, "_static_fp", None):
            self._static_fp = fp
            cv.delete("static")
            self._draw_static_layer(cv, eng)
        cv.delete("dyn")

        # 滚动区域
        if eng.board.tiles:
            xs = [t.x for t in eng.board.tiles.values()]
            ys = [t.y for t in eng.board.tiles.values()]
            ox0, oy0 = self._origin()
            m = TILE * 3
            cv.configure(scrollregion=(
                ox0 + min(xs) * TILE - TILE / 2 - m,
                oy0 + min(ys) * TILE - TILE / 2 - m,
                ox0 + max(xs) * TILE + TILE / 2 + m,
                oy0 + max(ys) * TILE + TILE / 2 + m))
            if not getattr(self, "_view_initialized", False):
                self._view_initialized = True
                self._center_view()

        # 合法格高亮（动态）
        if (eng.phase in ("place", "river") and not eng.game_over
                and self._my_turn()):
            for (x, y, r) in eng.legal_placements():
                if r != self.rot:
                    continue
                px, py = self.cell_px(x, y)
                cv.create_rectangle(px + 2, py + 2, px + TILE - 2, py + TILE - 2,
                                    fill=COL_HILITE, stipple="gray25",
                                    outline="#e8c96a", width=2, tags="dyn")

        # P&D：龙与仙女
        if "pd" in eng.expansions:
            dpos = eng.dragon.get("pos")
            if dpos and dpos in eng.board.tiles:
                px, py = self.cell_px(*dpos)
                cv.create_text(px + TILE / 2, py + TILE / 2, text="🐉",
                               font=("Segoe UI Emoji", 20), tags="dyn")
            fpos = eng.fairy.get("pos")
            if fpos and fpos in eng.board.tiles:
                px, py = self.cell_px(*fpos)
                cv.create_text(px + TILE / 2, py + TILE / 2, text="✨",
                               font=("Segoe UI Emoji", 18), tags="dyn")

        # M21 命运之轮：轮盘猪（左下角常驻显示）与王冠位随从计数
        if "wheel" in eng.expansions:
            names = {"fortune": "幸运", "plague": "瘟疫",
                     "inquisition": "审判", "storm": "风暴",
                     "famine": "饥荒", "tax": "税收"}
            riders = sum(len(v) for v in eng.crowns.values())
            cv.create_text(10, 10, anchor="nw",
                           text="🎡 %s 🐷×%d 👑%d"
                           % (names[eng.WHEEL_SECTORS[eng.wheel_pig]],
                              eng.wheel_pig + 1, riders),
                           font=FONT_S, fill="#ffe9a8", tags="dyn")
        # 刚放置的牌白色闪烁（动态）
        if self._flash_pos is not None and self._flash_pos in eng.board.tiles:
            fx, fy = self._flash_pos
            px, py = self.cell_px(fx, fy)
            cv.create_rectangle(px - 3, py - 3, px + TILE + 3, py + TILE + 3,
                                outline="white", width=4, tags="dyn")

        # 龙阶段：合法步提示（当前决策者视角）
        if (eng.phase == "dragon" and not eng.game_over
                and self.net_mode and eng.dragon["decider"] == self.my_seat
                or (eng.phase == "dragon" and not self.net_mode
                    and not eng.current_player().is_ai)):
            for pos in eng.dragon_legal_steps():
                px, py = self.cell_px(*pos)
                cv.create_rectangle(px + 4, py + 4, px + TILE - 4, py + TILE - 4,
                                    outline="#ff9060", width=3, tags="dyn")

        # 悬停幽灵牌（动态）
        if (eng.phase in ("place", "river") and self.hover_cell
                and self._my_turn()):
            x, y = self.hover_cell
            if (x, y, self.rot) in eng.legal_placements():
                px, py = self.cell_px(x, y)
                self._draw_tile_sprite(cv, eng.current_tile, self.rot,
                                       px, py, TILE, "ghost", ghost=True)

        # 部署锚点（动态）
        if eng.phase == "deploy" and self._my_turn():
            rot = eng.board.tiles[eng.placed_pos].rot
            px, py = self.cell_px(*eng.placed_pos)
            for o in eng.deploy_options():
                ax, ay = seg_anchor(o["kind"], eng.current_tile, rot, o["seg"],
                                    TILE, px, py)
                r = TILE * 0.11
                cv.create_oval(ax - r, ay - r, ax + r, ay + r,
                               fill="#ffd94d", outline="#8a6d1d", width=2,
                               tags="dyn")
                cv.create_text(ax, ay - r - 8, text=o["label"].split("·")[0],
                               font=FONT_S, fill="#ffe9a8", tags="dyn")

    def _draw_static_layer(self, cv, eng) -> None:
        """静态层：地牌 + 在场米宝 + T&B 图元（指纹变化时才重绘）。"""
        # 地牌
        for (x, y), pt in eng.board.tiles.items():
            d = eng.board.defs[(x, y)]
            px, py = self.cell_px(x, y)
            self._draw_tile_sprite(cv, d, pt.rot, px, py, TILE, "static")
            if pt.placed_by >= 0:
                cv.create_text(px + TILE - 4, py + TILE - 6,
                               text=eng.players[pt.placed_by].name[0],
                               font=FONT_S, fill=COLOR_HEX[eng.players[pt.placed_by].color],
                               anchor="e", tags="static")
        # M20 金块 / 隧道令牌 / 法师女巫
        for (gx, gy), n in eng.gold_map.items():
            if (gx, gy) not in eng.board.tiles:
                continue
            px, py = self.cell_px(gx, gy)
            cv.create_text(px + 8, py + 8, text="🪙" * min(n, 3),
                           font=("Segoe UI Emoji", 10), anchor="nw",
                           tags="static")
        for node, color in eng.board.tunnel_tokens.items():
            if node[0:2] not in eng.board.tiles:
                continue
            d0 = eng.board.defs[node[0:2]]
            pt0 = eng.board.tiles[node[0:2]]
            ax, ay = seg_anchor(node[2], d0, pt0.rot, node[3], TILE,
                                *self.cell_px(node[0], node[1]))
            cv.create_text(ax, ay - 10, text="🚇",
                           font=("Segoe UI Emoji", 11), tags="static")
            cv.create_text(ax + 12, ay + 8, text=color[0],
                           font=FONT_S, fill=COLOR_HEX.get(color, "#fff"),
                           tags="static")
        for fig, emoji in (("mage", "🧙"), ("witch", "🧙‍♀️")):
            node = getattr(eng, fig)
            if node and node[0:2] in eng.board.tiles:
                d0 = eng.board.defs[node[0:2]]
                pt0 = eng.board.tiles[node[0:2]]
                ax, ay = seg_anchor(node[2], d0, pt0.rot, node[3], TILE,
                                    *self.cell_px(node[0], node[1]))
                cv.create_text(ax + 14, ay - 12, text=emoji,
                               font=("Segoe UI Emoji", 13), tags="static")
        # M21 山丘与羊：牧羊人与羊群
        for s in eng.shepherds:
            node = s["node"]
            if node[0:2] not in eng.board.tiles:
                continue
            d0 = eng.board.defs[node[0:2]]
            pt0 = eng.board.tiles[node[0:2]]
            ax, ay = seg_anchor(node[2], d0, pt0.rot, node[3], TILE,
                                *self.cell_px(node[0], node[1]))
            cv.create_text(ax, ay, text="🧑‍🌾",
                           font=("Segoe UI Emoji", 14), tags="static")
            n = sum(s["tokens"])
            if n:
                cv.create_text(ax + 16, ay - 12, text="🐑%d" % n,
                               font=FONT_S,
                               fill=COLOR_HEX.get(s["color"], "#fff"),
                               tags="static")
        # M21 塔：塔块层数与驻塔随从
        for t in eng.towers:
            if t["pos"] not in eng.board.tiles:
                continue
            px, py = self.cell_px(*t["pos"])
            top = t.get("top")
            cv.create_text(px + TILE - 6, py + 6,
                           text="🗼×%d" % t["height"],
                           font=("Segoe UI Emoji", 11), anchor="ne",
                           fill="#fff", tags="static")
            if top:
                cv.create_text(px + 6, py + 26, text="🗼",
                               font=("Segoe UI Emoji", 13), tags="static")
                cv.create_text(px + 22, py + 30, text=top["color"][0],
                               font=FONT_S,
                               fill=COLOR_HEX.get(top["color"], "#fff"),
                               tags="static")
        # BCB 木桥
        for (bx, by), axis in eng.board.bridges.items():
            px, py = self.cell_px(bx, by)
            if axis == 0:
                cv.create_rectangle(px + TILE * 0.38, py + 4,
                                    px + TILE * 0.62, py + TILE - 4,
                                    fill="#c4a574", outline="#6b4e31", width=2,
                                    tags="static")
            else:
                cv.create_rectangle(px + 4, py + TILE * 0.38,
                                    px + TILE - 4, py + TILE * 0.62,
                                    fill="#c4a574", outline="#6b4e31", width=2,
                                    tags="static")
        # BCB 城堡标记
        for c in eng.castles:
            tiles = c["tiles"]
            mx = sum(t[0] for t in tiles) / len(tiles)
            my = sum(t[1] for t in tiles) / len(tiles)
            px, py = self.cell_px(int(round(mx)), int(round(my)))
            col = COLOR_HEX.get(c["owner"], "#fff")
            cv.create_text(px + TILE / 2, py + TILE / 2,
                           text="🏰" if not c["scored"] else "🏯",
                           font=("Segoe UI Emoji", 16), fill=col, tags="static")

        # 在场米宝
        for root in eng.board.roots():
            meta = eng.board._meta[root]
            for node, color, msize in meta.meeple_nodes:
                nx, ny, kind, seg = node
                d = eng.board.defs[(nx, ny)]
                pt = eng.board.tiles[(nx, ny)]
                ax, ay = seg_anchor(kind, d, pt.rot, seg, TILE,
                                    *self.cell_px(nx, ny))
                self._draw_meeple_sprite(cv, ax, ay, color,
                                         farmer=(kind == KIND_FARM),
                                         big=(msize > 1))

        # T&B 图元：建造者（蓝小人）/猪（粉椭圆）
        if "traders" in eng.expansions:
            for root in eng.board.roots():
                meta = eng.board._meta[root]
                for (attr, color), nodes in meta.figure_nodes.items():
                    for node in nodes:
                        nx, ny, kind, seg = node
                        if (nx, ny) not in eng.board.tiles:
                            continue
                        d = eng.board.defs[(nx, ny)]
                        pt = eng.board.tiles[(nx, ny)]
                        ax, ay = seg_anchor(kind, d, pt.rot, seg, TILE,
                                            *self.cell_px(nx, ny))
                        ox = ax + (12 if attr == "pigs" else -12)
                        oy = ay - 14
                        if attr == "builders":
                            cv.create_oval(ox - 5, oy - 9, ox + 5, oy + 1,
                                           fill="#5a72c8", outline="white",
                                           width=1, tags="static")
                            cv.create_oval(ox - 3, oy - 12, ox + 3, oy - 6,
                                           fill="#5a72c8", outline="white",
                                           width=1, tags="static")
                        else:
                            cv.create_oval(ox - 6, oy - 4, ox + 6, oy + 4,
                                           fill="#eea", outline="#c96",
                                           width=1, tags="static")

    def _draw_preview(self) -> None:
        cv = self.preview
        cv.delete("all")
        eng = self.engine
        if eng.current_tile and eng.phase == "place":
            self._draw_tile_sprite(cv, eng.current_tile, self.rot,
                                   0, 0, PREVIEW, "pv")
        elif eng.game_over:
            cv.create_text(PREVIEW / 2, PREVIEW / 2, text="牌堆已空",
                           font=FONT, fill="#cfc49f")
        else:
            cv.create_text(PREVIEW / 2, PREVIEW / 2, text="已放置",
                           font=FONT, fill="#cfc49f")

    def _draw_deploy_panel(self) -> None:
        for w in self.deploy_box.winfo_children():
            w.destroy()
        eng = self.engine
        if eng.phase != "deploy" or not self._my_turn():
            return
        if eng._phantom_step:
            tk.Label(self.deploy_box, text="👻 幽灵步骤（第二随从）",
                     font=FONT_S, fg="#cfe3ff", bg="#39422e").pack(
                fill="x", pady=(2, 4))
        # M21 塔：建塔（两步：选塔位→选抓捕）/ 驻塔 / 赎金
        if eng._tower_pending is not None:
            pos = eng._tower_pending
            tk.Label(self.deploy_box, text="🗼 抓捕目标（%d,%d）"
                     % pos, font=FONT_S, fg="#ffd0d0",
                     bg="#39422e").pack(fill="x", pady=(2, 4))
            caps = dict(eng.tower_piece_options()).get(pos, [])
            for node in caps[:12]:
                b = tk.Button(self.deploy_box,
                              text="🎯 抓 (%d,%d)#%d" % (node[0], node[1],
                                                         node[3]),
                              font=FONT_S,
                              command=lambda n=node: self._tower_place(pos, n),
                              bg="#8a3f3f", fg="white", relief="flat",
                              activebackground="#9a4f4f")
                b.pack(fill="x", pady=1, ipady=2)
            b = tk.Button(self.deploy_box, text="不抓人", font=FONT_S,
                          command=lambda: self._tower_place(pos, None),
                          bg="#8a6d3f", fg="white", relief="flat")
            b.pack(fill="x", pady=1, ipady=2)
            return
        for pos, captures in eng.tower_piece_options():
            n = len(captures)
            txt = "🗼 建塔 (%d,%d)" % pos + ("（可抓 %d 人）" % n if n else "")
            b = tk.Button(self.deploy_box, text=txt, font=FONT_S,
                          command=lambda p=pos: self._tower_pick(p),
                          bg="#6d4f8a", fg="white", relief="flat",
                          activebackground="#7d5f9a")
            b.pack(fill="x", pady=1, ipady=2)
        for pos in eng.tower_top_options():
            b = tk.Button(self.deploy_box, text="🗼 驻塔 (%d,%d)" % pos,
                          font=FONT_S,
                          command=lambda p=pos: self._tower_top(p),
                          bg="#4f6d8a", fg="white", relief="flat",
                          activebackground="#5f7d9a")
            b.pack(fill="x", pady=1, ipady=2)
        for idx in eng.ransom_options():
            h = eng.hostages[idx]
            b = tk.Button(self.deploy_box,
                          text="💰 赎回 %s 的人质（-3 分）" % h["captor"],
                          font=FONT_S,
                          command=lambda i=idx: self._ransom(i),
                          bg="#8a7a3f", fg="white", relief="flat")
            b.pack(fill="x", pady=1, ipady=2)
        # M20 节日牌：收回己方任一图元（代替部署；幽灵步骤不提供）
        if not eng._phantom_step:
            for o in eng.festival_options():
                b = tk.Button(self.deploy_box, text=o["label"], font=FONT_S,
                              command=lambda opt=o: self._festival_return(opt),
                              bg="#7a4f6d", fg="white", relief="flat",
                              activebackground="#8a5f7d")
                b.pack(fill="x", pady=1, ipady=2)
        # M19：自愿建桥（部署之外的额外动作，CAR 页 96）
        for pos, axis in eng.bridge_options():
            txt = "🌉 建桥 (%d,%d) %s" % (pos[0], pos[1],
                                          "南北" if axis == 0 else "东西")
            b = tk.Button(self.deploy_box, text=txt, font=FONT_S,
                          command=lambda p=pos, a=axis: self._build_bridge(p, a),
                          bg="#8a6d3f", fg="white", relief="flat",
                          activebackground="#9a7d4c")
            b.pack(fill="x", pady=1, ipady=2)
        for o in eng.deploy_options():
            b = tk.Button(self.deploy_box, text=o["label"], font=FONT_S,
                          command=lambda opt=o: self._deploy(opt),
                          bg="#5a6b3f", fg="white", relief="flat",
                          activebackground="#6b7d4c")
            b.pack(fill="x", pady=1, ipady=2)

    def _tower_pick(self, pos) -> None:
        eng = self.engine
        caps = dict(eng.tower_piece_options()).get(pos, [])
        if not caps:
            self._tower_place(pos, None)
            return
        eng._tower_pending = pos   # 本地两步：先记塔位，再选抓捕
        self.refresh()

    def _tower_place(self, pos, capture) -> None:
        eng = self.engine
        if self.net_mode:
            self.net.send_tower_piece(pos, capture)
            return
        eng._tower_pending = None
        eng.tower_place(pos, capture)
        self._emit_events()
        self.refresh()
        self.maybe_ai_turn()

    def _tower_top(self, pos) -> None:
        if self.net_mode:
            self.net.send_tower_top(pos)
            return
        eng = self.engine
        eng.tower_deploy_top(pos)
        self._emit_events()
        self.refresh()
        self.maybe_ai_turn()

    def _ransom(self, idx) -> None:
        if self.net_mode:
            self.net.send_ransom(idx)
            return
        eng = self.engine
        eng.ransom(idx)
        self._emit_events()
        self.refresh()

    def _festival_return(self, opt) -> None:
        if self.net_mode:
            self.net._send({"t": "deploy", "kind": "festival_ret",
                            "seg": 0, "fig": opt["fig"],
                            "pos": list(opt["node"])})
            return
        eng = self.engine
        eng.festival_return(opt)
        self._emit_events()
        self.refresh()
        self.maybe_ai_turn()

    def _build_bridge(self, pos, axis) -> None:
        if self.net_mode:
            self.net.send_bridge(pos, axis)
            return
        eng = self.engine
        eng.build_bridge(pos, axis)
        self._emit_events()
        self.refresh()   # 部署阶段继续：仍可部署随从或跳过

    def _draw_players(self) -> None:
        for w in self.players_box.winfo_children():
            w.destroy()
        for p in self.engine.players:
            row = tk.Frame(self.players_box, bg="#39422e")
            row.pack(fill="x", pady=1)
            tk.Label(row, text="●", font=("Microsoft YaHei", 13),
                     fg=COLOR_HEX[p.color], bg="#39422e", width=2).pack(side="left")
            name = p.name + (" 🤖" if p.is_ai else "")
            tk.Label(row, text=name, font=FONT_S, bg="#39422e", fg="#e8e0c4",
                     width=9, anchor="w").pack(side="left")
            tk.Label(row, text="%d 分" % p.score, font=FONT_S,
                     bg="#39422e", fg="#e8c96a", width=6).pack(side="left")
            meeple_txt = "●" * p.meeples_left + (" ★" * p.big_meeples_left
                                                if p.big_meeples_left else "")
            if p.builder_left:
                meeple_txt += " 🔨"
            if p.pig_left:
                meeple_txt += " 🐷"
            if p.mayor_left:
                meeple_txt += " 🎩"
            if p.barn_left:
                meeple_txt += " 🏚"
            if p.wagon_left:
                meeple_txt += " 🛒"
            if p.towers_left:
                meeple_txt += " 🗼×%d" % p.towers_left
            if p.shepherd_left:
                meeple_txt += " 🧑‍🌾"
            tk.Label(row, text="米宝 " + meeple_txt, font=FONT_S,
                     bg="#39422e", fg=COLOR_HEX[p.color]).pack(side="right")
            n_host = sum(1 for h in self.engine.hostages
                         if h["captor"] == p.color)
            if n_host:
                tk.Label(row, text="⛓%d" % n_host, font=FONT_S,
                         bg="#39422e", fg="#ffb0b0").pack(side="right")
            if getattr(p, "goods", None) and sum(p.goods.values()):
                parts = [("酒", p.goods.get("wine", 0)),
                         ("谷", p.goods.get("grain", 0)),
                         ("布", p.goods.get("cloth", 0))]
                gt = "，".join("%s%d" % (n, c) for n, c in parts if c)
                tk.Label(row, text="货 " + gt, font=FONT_S, bg="#39422e",
                         fg="#e8c96a").pack(side="right")

    def _draw_scoreboard(self) -> None:
        cv = self.score_cv
        cv.delete("all")
        if self.sprites.ok and self.engine:
            key = ("sb", 2)
            img = self._img_cache.get(key)
            if img is None:
                img = self.sprites.scoreboard().subsample(2)   # 500x64 -> 250x32
                self._img_cache[key] = img
            cv.create_image(10, 6, image=img, anchor="nw")
            w, h = 250, 32
            passed = []
            for p in self.engine.players:
                x, y = art.score_pos(p.score, w, h)
                r = 4.5
                cv.create_oval(10 + x - r, 6 + y - r, 10 + x + r, 6 + y + r,
                               fill=COLOR_HEX[p.color], outline="white", width=1)
                lap = p.score // 51
                if lap:
                    cv.create_text(10 + x + 9, 6 + y, text="×%d" % (lap + 1),
                                   font=("Microsoft YaHei", 7), anchor="w",
                                   fill="#e8c96a")
                    passed.append("%s %d 分" % (p.color, p.score))
            # 过 0 分牌提示（50/100…）：轨道下方显示实际总分
            if passed:
                cv.create_text(10 + w / 2, 6 + h + 4, text="过 0：" + "，".join(passed),
                               font=("Microsoft YaHei", 8), fill="#e8c96a")
        elif self.engine:
            # 程序化回退：单行 0-50 轨道
            w, h = 272, 64
            x0, y0 = 10, 6
            step = (w - 2 * x0) / 50.0
            cv.create_line(x0, y0 + 18, w - x0, y0 + 18, fill="#6b7355", width=2)
            for v in range(0, 51):
                x = x0 + v * step
                big = v % 5 == 0
                cv.create_line(x, y0 + 18, x, y0 + (10 if big else 14),
                               fill="#aab08c", width=1)
                if big:
                    cv.create_text(x, y0, text=str(v), font=("Microsoft YaHei", 7),
                                   fill="#cfc49f")
            for i, p in enumerate(self.engine.players):
                pos = p.score % 51
                x = x0 + pos * step
                y = y0 + 30 + i * 7
                r = 4.5
                cv.create_oval(x - r, y - r, x + r, y + r,
                               fill=COLOR_HEX[p.color], outline="white", width=1)

    # ------------------------------------------------------------ 终局

    def _draw_players_wait(self) -> None:
        """联机等待开局时的座位区（房主可移出人类玩家）。"""
        for w in self.players_box.winfo_children():
            w.destroy()
        if not self._lobby_seats:
            tk.Label(self.players_box, text="等待房主开始对局……", font=FONT_S,
                     bg="#39422e", fg="#e8c96a").pack(anchor="w")
            return
        for s in self._lobby_seats:
            row = tk.Frame(self.players_box, bg="#39422e")
            row.pack(fill="x", pady=1)
            name = ("AI·%s" % s["level"]) if s["is_ai"] else str(s["name"])
            tag = "（房主）" if s["idx"] == 0 else ""
            tk.Label(row, text="● %s%s" % (name, tag), font=FONT_S,
                     bg="#39422e", fg="#e8e0c4").pack(side="left")
            if (self._is_host() and not s["is_ai"] and s["idx"] != 0
                    and s.get("connected")):
                tk.Button(row, text="移出", font=FONT_S, relief="flat",
                          bg="#7a4a35", fg="white", activebackground="#8a5a42",
                          command=lambda idx=s["idx"]: self.net.send_kick(idx)
                          ).pack(side="right")

    def _finish_net(self, events: List[Dict[str, object]]) -> None:
        """联机终局：结果由主机快照给出。"""
        if self._finished or self.engine is None:
            return
        self._finished = True
        eng = self.engine
        self.lbl_turn.config(text="对局结束 · %s" % (eng.winner_text()))

        dlg = tk.Toplevel(self)
        dlg.title("终局结算")
        dlg.configure(bg="#39422e")
        dlg.geometry("+300+180")
        dlg.resizable(False, False)
        tk.Label(dlg, text="🏆 终局结算", font=FONT_L, bg="#39422e",
                 fg="#f2e8c9").pack(pady=(14, 6))
        text = "%s\n\n" % eng.winner_text()
        for p in eng.standings():
            text += "● %s（%s）　%d 分\n" % (p.name, p.color, p.score)
        if events:
            text += "\n终局计分明细：\n"
            for ev in events:
                detail = ev.get("detail") or ev.get("reason", "")
                gains = "，".join("%s +%d" % (c, v)
                                 for c, v in (ev.get("scores") or {}).items())
                text += "· %s → %s\n" % (detail, gains or "无人得分")
        tk.Label(dlg, text=text, font=FONT, bg="#39422e", fg="#e8e0c4",
                 justify="left").pack(padx=24, pady=6)
        tk.Button(dlg, text="关闭", font=FONT, command=dlg.destroy,
                  bg="#5a6b3f", fg="white", relief="flat",
                  padx=20).pack(pady=(6, 16))

    def _finish(self) -> None:
        if self._finished:
            return
        self._finished = True
        evs = self.engine.final_scoring()
        for ev in evs:
            self._log("🏁 %s：%s" % (ev.detail or ev.reason,
                                    "，".join("%s+%d" % (c, p)
                                              for c, p in ev.scores.items())))
        self.refresh()
        self.lbl_turn.config(text="对局结束 · %s" % self.engine.winner_text())

        dlg = tk.Toplevel(self)
        dlg.title("终局结算")
        dlg.configure(bg="#39422e")
        dlg.geometry("+300+180")
        dlg.resizable(False, False)
        tk.Label(dlg, text="🏆 终局结算", font=FONT_L, bg="#39422e",
                 fg="#f2e8c9").pack(pady=(14, 6))
        text = "%s\n\n" % self.engine.winner_text()
        for p in self.engine.standings():
            text += "● %s（%s）　%d 分\n" % (p.name, p.color, p.score)
        if evs:
            text += "\n终局计分明细：\n"
            for ev in evs:
                detail = ev.detail or ev.reason
                gains = "，".join("%s +%d" % (c, v) for c, v in ev.scores.items())
                text += "· %s → %s\n" % (detail, gains or "无人得分")
        tk.Label(dlg, text=text, font=FONT, bg="#39422e", fg="#e8e0c4",
                 justify="left").pack(padx=24, pady=6)
        tk.Button(dlg, text="关闭", font=FONT, command=dlg.destroy,
                  bg="#5a6b3f", fg="white", relief="flat",
                  padx=20).pack(pady=(6, 16))
