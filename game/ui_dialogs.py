# -*- coding: utf-8 -*-
"""UI 对话框：模式选择/开局设置/局域网 IP（自 ui.py 拆出，M14）。"""
from __future__ import annotations

import socket
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Dict, Optional

from .engine import COLOR_HEX
from .ui_common import FONT, FONT_S, FONT_L

# ---------------------------------------------------------------- 扩展开关

# (key, 名称, 简述)：顺序 = 牌堆/快照中的扩展开关顺序
EXPANSIONS = [
    ("inns", "客栈与大教堂", "18 张新牌，双倍/三倍计分与大型米宝"),
    ("traders", "商人与建造者", "24 张新牌，贸易商品/双回合/猪"),
    ("pd", "公主与龙", "30 张新牌，龙移动/仙女/公主/传送门"),
    ("abbey", "修道院与市长", "12 张新牌，市长/粮仓/马车"),
    ("king", "国王与强盗男爵", "5 张新牌，最大城/最长路记号"),
    ("river", "河流 II", "12 张河流起始牌，替代起始修道院"),
    ("shrine", "教堂与异端", "5 张新牌，教堂挑战修道院"),
    ("count", "卡卡颂伯爵", "城块四区，计分前可移入随从"),
    ("bcb", "桥城堡集市", "12 张新牌，木桥/城堡回响/集市拍卖"),
    ("besiegers", "围攻", "6 张新牌，被围城 1 分/牌，可脱困"),
    ("festival", "节日", "10 张新牌，可收回场上任一己方图元"),
    ("goldmines", "金矿", "9 张新牌，金块随完成特征归属多数者"),
    ("magewitch", "法师与女巫", "9 张新牌，法师加分/女巫减半"),
    ("robbers", "强盗", "9 张新牌，轨道强盗偷走得分一半"),
    ("tunnel", "隧道", "4 张新牌，同色双令牌地下接通道路"),
    ("crop", "麦田怪圈", "6 张新牌，全体部署同伴或收回随从"),
    ("phantom", "幽灵", "每色第二枚普通随从"),
    ("tower", "塔", "18 张新牌，建塔抓随从/赎金 3 分"),
    ("hillsheep", "山丘与羊", "18 张新牌，叠牌/牧羊人/葡萄园"),
    ("wheel", "命运之轮", "19 张命运牌，轮盘事件/王冠位"),
]

_BG = "#3f4a35"
_SEL_BG = "#2f3627"
_GOLD = "#e8c96a"
_GRAY = "#a89f82"


def _bind_wheel(widget: tk.Misc, canvas: tk.Canvas) -> None:
    """滚轮滚动面板（Windows delta 为 120 的倍数）。"""
    def on_wheel(e):
        canvas.yview_scroll(-1 if e.delta > 0 else 1, "units")
        return "break"
    widget.bind("<MouseWheel>", on_wheel)


def _bind_wheel_tree(widget: tk.Misc, canvas: tk.Canvas) -> None:
    _bind_wheel(widget, canvas)
    for child in widget.winfo_children():
        _bind_wheel_tree(child, canvas)


def clamp_to_screen(win: tk.Misc, margin: int = 30) -> None:
    """窗口底边超出屏幕时上移（小屏展开扩展面板后仍能看到底部按钮）。"""
    if not win.winfo_exists():
        return
    win.update_idletasks()
    # 标题栏高度：winfo_rooty 指向客户区，winfo_y 指向窗口框
    frame_extra = max(0, win.winfo_rooty() - win.winfo_y())
    h = max(win.winfo_height(), win.winfo_reqheight()) + frame_extra
    room = win.winfo_screenheight() - margin
    y = win.winfo_y()
    if y + h > room:
        target = max(20, room - h)
        if target != y:
            win.geometry("+%d+%d" % (win.winfo_x(), target))


class ExpansionPanel:
    """可折叠的扩展开关面板（20 项平铺会超出小屏）。

    折叠时只占一行标题（含已选计数）；展开时限高滚动并可全选/清空。
    选择结果按 EXPANSIONS 顺序经 selected() 返回。
    """

    def __init__(self, parent: tk.Misc, detail: bool = True,
                 reserve: int = 620) -> None:
        self.vars = {key: tk.BooleanVar(value=False)
                     for key, _name, _desc in EXPANSIONS}
        self._open = False
        # 展开高度随屏幕收缩，保证对话框整体不超屏
        self._body_h = max(120, min(200, parent.winfo_screenheight() - reserve))
        self.frame = tk.Frame(parent, bg=_BG)
        head = tk.Frame(self.frame, bg=_BG)
        head.pack(fill="x")
        self._btn = tk.Button(head, text="", font=FONT_S, bg=_BG, fg=_GOLD,
                              activebackground=_BG, activeforeground="#f0e6c8",
                              relief="flat", bd=0, anchor="w", cursor="hand2",
                              command=self.toggle)
        self._btn.pack(side="left")
        for txt, val in (("清空", False), ("全选", True)):
            tk.Button(head, text=txt, font=FONT_S, bg=_SEL_BG, fg="#cfc49f",
                      activebackground="#465239", activeforeground="white",
                      relief="flat", padx=6, cursor="hand2",
                      command=lambda v=val: self.set_all(v)
                      ).pack(side="right", padx=(4, 0))
        self._body = tk.Frame(self.frame, bg=_BG)
        self._canvas = tk.Canvas(self._body, bg=_BG, highlightthickness=0,
                                 height=self._body_h, width=480)
        vsb = ttk.Scrollbar(self._body, orient="vertical",
                            command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=vsb.set)
        self._canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        inner = tk.Frame(self._canvas, bg=_BG)
        self._win = self._canvas.create_window((0, 0), window=inner,
                                               anchor="nw")
        inner.bind("<Configure>", lambda e: self._canvas.configure(
            scrollregion=self._canvas.bbox("all")))
        self._canvas.bind("<Configure>", lambda e: self._canvas.itemconfigure(
            self._win, width=e.width))
        for key, name, desc in EXPANSIONS:
            text = "%s（%s）" % (name, desc) if detail else name
            tk.Checkbutton(inner, text=text, variable=self.vars[key],
                           font=FONT_S, bg=_BG, fg=_GOLD, activebackground=_BG,
                           selectcolor=_SEL_BG, anchor="w").pack(anchor="w",
                                                                 fill="x")
        _bind_wheel_tree(inner, self._canvas)
        _bind_wheel(self._canvas, self._canvas)
        for var in self.vars.values():
            var.trace_add("write", lambda *_: self._refresh())
        self._refresh()
        # 窗口尺寸随展开/折叠变化后若越出屏幕则上移（Configure 驱动，
        # 不用定时器：对话框销毁后不会留下悬挂回调）
        top = self.frame.winfo_toplevel()
        top.bind("<Configure>", self._on_configure, add="+")

    def _on_configure(self, event: tk.Event) -> None:
        if event.widget is self.frame.winfo_toplevel():
            clamp_to_screen(event.widget)

    def selected(self) -> list:
        return [key for key, _name, _desc in EXPANSIONS
                if self.vars[key].get()]

    def set_all(self, value: bool) -> None:
        for var in self.vars.values():
            var.set(value)

    def toggle(self) -> None:
        self._open = not self._open
        if self._open:
            self._body.pack(fill="x", pady=(2, 4))
            self._canvas.yview_moveto(0)
        else:
            self._body.pack_forget()
        self._refresh()

    def _refresh(self) -> None:
        self._btn.configure(text="%s 扩展（已选 %d / %d）" % (
            "▾" if self._open else "▸", len(self.selected()), len(EXPANSIONS)))


# ---------------------------------------------------------------- 设置界面

def setup_dialog():
    """返回 (specs 列表, expansions 列表) 或 (None, [])。"""
    """开局设置：人数、姓名、人机、AI 难度。返回 specs 或 None（取消）。"""
    dlg = tk.Tk()
    dlg.title("卡卡颂 · 新对局")
    dlg.configure(bg="#3f4a35")
    dlg.resizable(False, False)
    dlg.geometry("+260+160")

    tk.Label(dlg, text="🚩 卡卡颂", font=("Microsoft YaHei", 20, "bold"),
             bg="#3f4a35", fg="#f0e6c8").pack(pady=(16, 2))
    tk.Label(dlg, text="基础版 · 72 张地牌 · 依据 CAR v7.4 规则",
             font=FONT_S, bg="#3f4a35", fg="#c9c0a2").pack(pady=(0, 12))

    frame = tk.Frame(dlg, bg="#3f4a35")
    frame.pack(padx=20)

    tk.Label(frame, text="玩家数", font=FONT, bg="#3f4a35",
             fg="#e8e0c4").grid(row=0, column=0, sticky="w", padx=(0, 8))
    nvar = tk.IntVar(value=2)
    box = ttk.Combobox(frame, textvariable=nvar, values=list(range(2, 7)),
                       width=4, state="readonly")
    box.grid(row=0, column=1, sticky="w")

    rows_frame = tk.Frame(dlg, bg="#3f4a35")
    rows_frame.pack(padx=20, pady=10, fill="x")

    headers = tk.Frame(rows_frame, bg="#3f4a35")
    headers.pack(fill="x")
    for col, txt in enumerate(["颜色", "姓名", "电脑玩家", "AI 难度"]):
        tk.Label(headers, text=txt, font=FONT_S, width=10 if col == 1 else 8,
                 bg="#3f4a35", fg="#b9b092", anchor="w").grid(row=0, column=col)

    rows: List[Dict[str, object]] = []

    def rebuild(n: int) -> None:
        for w in rows_frame.winfo_children()[1:]:
            w.destroy()
        rows.clear()
        for i in range(n):
            row = tk.Frame(rows_frame, bg="#3f4a35")
            row.pack(fill="x", pady=1)
            color = ["红", "蓝", "绿", "黄", "黑", "灰"][i]
            tk.Label(row, text="●", font=("Microsoft YaHei", 14),
                     fg=COLOR_HEX[color], bg="#3f4a35", width=3).grid(row=0, column=0)
            name = tk.Entry(row, width=12, font=FONT_S)
            name.insert(0, "玩家%d" % (i + 1))
            name.grid(row=0, column=1, padx=4)
            is_ai = tk.BooleanVar(value=False)
            chk = tk.Checkbutton(row, variable=is_ai, bg="#3f4a35",
                                 activebackground="#3f4a35")
            chk.grid(row=0, column=2)
            level = tk.StringVar(value="normal")
            cmb = ttk.Combobox(row, textvariable=level, state="readonly",
                               values=["easy", "normal", "hard"], width=7)
            cmb.grid(row=0, column=3)
            rows.append({"name": name, "is_ai": is_ai, "level": level})

    rebuild(2)
    box.bind("<<ComboboxSelected>>", lambda e: rebuild(nvar.get()))

    result: List[dict] = []

    panel = ExpansionPanel(dlg, detail=True, reserve=430)
    panel.frame.pack(anchor="w", fill="x", padx=20, pady=(2, 0))
    dlg._exp_panel = panel   # 供 UI 自动化断言（verify_ui）

    def on_start() -> None:
        for i, r in enumerate(rows):
            result.append({
                "name": r["name"].get().strip() or "玩家%d" % (i + 1),
                "is_ai": r["is_ai"].get(),
                "ai_level": r["level"].get(),
            })
        dlg.expansions = panel.selected()
        dlg.destroy()

    tk.Button(dlg, text="开始游戏", font=FONT_L, command=on_start,
              bg="#b5482f", fg="white", activebackground="#c9583d",
              relief="flat", padx=28, pady=4).pack(pady=(4, 18))

    dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
    dlg.mainloop()
    if not result:
        return None, []
    return result, getattr(dlg, "expansions", [])


# ---------------------------------------------------------------- 主界面

def get_lan_ip() -> str:
    """取局域网 IP（用于告诉朋友连哪个地址）。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def mode_dialog() -> Optional[Dict[str, object]]:
    """模式选择：单机 / 建立联机 / 加入联机。"""
    dlg = tk.Tk()
    dlg.title("卡卡颂 · 选择模式")
    dlg.configure(bg="#3f4a35")
    dlg.resizable(False, False)
    dlg.geometry("+300+170")

    tk.Label(dlg, text="🚩 卡卡颂", font=("Microsoft YaHei", 22, "bold"),
             bg="#3f4a35", fg="#f0e6c8").pack(pady=(18, 2))
    tk.Label(dlg, text="基础版 · 72 张地牌 · 单机 / 人机 / 局域网联机",
             font=FONT_S, bg="#3f4a35", fg="#c9c0a2").pack(pady=(0, 14))

    result: Dict[str, object] = {}

    def _close() -> None:
        dlg.destroy()

    def _local() -> None:
        result["kind"] = "local"
        _close()

    body = tk.Frame(dlg, bg="#3f4a35")
    body.pack(padx=24, pady=(4, 10))

    # ---- 单机
    tk.Button(body, text="单机对局（热座 / 人机）", font=FONT_L, command=_local,
              bg="#5a6b3f", fg="white", activebackground="#6b7d4c",
              relief="flat", width=26, pady=6).pack(fill="x", pady=4)

    # ---- 建房
    host_box = tk.LabelFrame(body, text=" 建立联机房间（做主机） ", font=FONT,
                             bg="#3f4a35", fg="#cfc49f")
    host_box.pack(fill="x", pady=8)
    row = tk.Frame(host_box, bg="#3f4a35")
    row.pack(fill="x", padx=10, pady=4)
    tk.Label(row, text="总人数", font=FONT_S, bg="#3f4a35",
             fg="#e8e0c4").pack(side="left")
    seats_var = tk.IntVar(value=2)
    ttk.Combobox(row, textvariable=seats_var, values=list(range(2, 7)),
                 width=3, state="readonly").pack(side="left", padx=(4, 12))
    tk.Label(row, text="AI 数", font=FONT_S, bg="#3f4a35",
             fg="#e8e0c4").pack(side="left")
    ai_var = tk.IntVar(value=0)
    ai_cmb = ttk.Combobox(row, textvariable=ai_var,
                          values=list(range(0, 6)), width=3, state="readonly")
    ai_cmb.pack(side="left", padx=4)
    tk.Label(row, text="你的名字", font=FONT_S, bg="#3f4a35",
             fg="#e8e0c4").pack(side="left", padx=(12, 4))
    host_name = tk.Entry(row, width=10, font=FONT_S)
    host_name.insert(0, "房主")
    host_name.pack(side="left")

    def _host() -> None:
        seats = seats_var.get()
        if ai_var.get() >= seats:
            messagebox.showwarning("提示", "AI 数必须小于总人数（至少房主是真人）",
                                   parent=dlg)
            return
        result.update({"kind": "host", "seats": seats,
                       "ai_count": ai_var.get(),
                       "name": host_name.get().strip() or "房主",
                       "expansions": host_panel.selected()})
        _close()

    tk.Label(host_box, text="扩展（需全员统一，创建房间后不可更改）",
             font=FONT_S, bg=_BG, fg=_GRAY, anchor="w").pack(
                 anchor="w", padx=10, pady=(2, 0))
    host_panel = ExpansionPanel(host_box, detail=False, reserve=700)
    host_panel.frame.pack(anchor="w", fill="x", padx=10, pady=(2, 0))
    dlg._exp_panel = host_panel   # 供 UI 自动化断言（verify_ui）
    tk.Label(host_box, text="AI 座位由主机代打；好友随时可加入替换空位。"
             "人手不够就调高 AI 数，凑齐了想纯人对战可重建房间。",
             font=FONT_S, bg="#3f4a35", fg="#a89f82", wraplength=440,
             justify="left").pack(anchor="w", padx=10)
    tk.Button(host_box, text="创建房间", font=FONT, command=_host,
              bg="#b5482f", fg="white", activebackground="#c9583d",
              relief="flat", width=22).pack(pady=(2, 8))

    # ---- 加入
    join_box = tk.LabelFrame(body, text=" 加入联机房间 ", font=FONT,
                             bg="#3f4a35", fg="#cfc49f")
    join_box.pack(fill="x", pady=(2, 10))
    row2 = tk.Frame(join_box, bg="#3f4a35")
    row2.pack(fill="x", padx=10, pady=4)
    tk.Label(row2, text="主机 IP", font=FONT_S, bg="#3f4a35",
             fg="#e8e0c4").pack(side="left")
    ip_var = tk.StringVar(value=get_lan_ip())
    tk.Entry(row2, textvariable=ip_var, width=14,
             font=FONT_S).pack(side="left", padx=4)
    tk.Label(row2, text="端口", font=FONT_S, bg="#3f4a35",
             fg="#e8e0c4").pack(side="left", padx=(8, 4))
    port_var = tk.StringVar(value="37241")
    tk.Entry(row2, textvariable=port_var, width=7, font=FONT_S).pack(side="left")
    row3 = tk.Frame(join_box, bg="#3f4a35")
    row3.pack(fill="x", padx=10, pady=(0, 8))
    tk.Label(row3, text="你的名字", font=FONT_S, bg="#3f4a35",
             fg="#e8e0c4").pack(side="left")
    join_name = tk.Entry(row3, width=10, font=FONT_S)
    join_name.insert(0, "客人")
    join_name.pack(side="left", padx=4)

    def _join() -> None:
        try:
            port = int(port_var.get())
        except ValueError:
            messagebox.showwarning("提示", "端口必须是数字", parent=dlg)
            return
        result.update({"kind": "join", "ip": ip_var.get().strip(),
                       "port": port,
                       "name": join_name.get().strip() or "客人"})
        _close()

    tk.Button(join_box, text="加入房间", font=FONT, command=_join,
              bg="#4a6fb5", fg="white", activebackground="#5a7fc5",
              relief="flat", width=22).pack(pady=(0, 8))

    tk.Label(dlg, text="提示：主机端口随机分配，创建后会显示在窗口标题处；"
             "同一局域网内朋友用该 IP+端口加入。",
             font=FONT_S, bg="#3f4a35", fg="#a89f82", wraplength=460,
             justify="left").pack(padx=18, pady=(0, 14))

    dlg.protocol("WM_DELETE_WINDOW", _close)
    dlg.mainloop()
    return result or None


