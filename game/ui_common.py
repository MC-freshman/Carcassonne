# -*- coding: utf-8 -*-
"""UI 共享常量与程序化绘制（自 ui.py 拆出，M14）。"""
from __future__ import annotations

import tkinter as tk
from typing import Tuple

from .board import KIND_CITY, KIND_FARM, KIND_MON, KIND_ROAD
from .models import TileDef

TILE = 84            # 棋盘上每张牌的像素尺寸
PREVIEW = 168        # 右侧当前牌预览尺寸（贴图 master 尺寸）
GRID_ORIGIN = 1024   # 网格 (0,0) 的固定画布坐标：画布坐标不随滚动变化，
                     # 滚动后 refresh 不会把视图拉回中心
FONT = ("Microsoft YaHei", 10)
FONT_S = ("Microsoft YaHei", 9)
FONT_L = ("Microsoft YaHei", 13, "bold")

COL_FIELD = "#8fae6a"
COL_FIELD_DARK = "#7d9c5b"
COL_CITY = "#cbb489"
COL_CITY_WALL = "#7a6444"
COL_ROAD = "#e7d8a7"
COL_ROAD_BORDER = "#a89460"
COL_MON = "#9c5a41"
COL_BG = "#5a6b4a"
COL_HILITE = "#ffe9a8"

EDGE_MID = {0: (0.5, 0.0), 1: (1.0, 0.5), 2: (0.5, 1.0), 3: (0.0, 0.5)}


def _pull(p: Tuple[float, float], t: float) -> Tuple[float, float]:
    """向中心 (0.5,0.5) 收缩。"""
    return (p[0] + (0.5 - p[0]) * t, p[1] + (0.5 - p[1]) * t)


def seg_anchor(kind: str, tile: TileDef, rot: int, seg: int,
               size: float, ox: float, oy: float) -> Tuple[float, float]:
    """段的锚点（部署圆钮/米宝显示位置），返回画布像素坐标。"""
    if kind == KIND_MON:
        fx, fy = 0.5, 0.62
    elif kind == KIND_CITY:
        edges = list(tile.rotated_cities(rot)[seg][0])
        mids = [EDGE_MID[e] for e in edges]
        fx = sum(m[0] for m in mids) / len(mids)
        fy = sum(m[1] for m in mids) / len(mids)
        fx, fy = _pull((fx, fy), 0.42)
    elif kind == KIND_ROAD:
        edges = tile.rotated_roads(rot)[seg][0]
        mids = [EDGE_MID[e] for e in edges]
        fx = sum(m[0] for m in mids) / len(mids)
        fy = sum(m[1] for m in mids) / len(mids)
        fx, fy = _pull((fx, fy), 0.35 if len(edges) > 1 else 0.5)
    else:  # farm
        edges = list(tile.rotated_farms(rot)[seg][0])
        mids = [EDGE_MID[e] for e in edges]
        fx = sum(m[0] for m in mids) / len(mids)
        fy = sum(m[1] for m in mids) / len(mids)
        fx, fy = _pull((fx, fy), 0.66)
    return ox + fx * size, oy + fy * size


def draw_tile(cv: tk.Canvas, tile: TileDef, rot: int, ox: float, oy: float,
              size: float, tags: str = "tile") -> None:
    """程序化绘制一张牌（ox,oy 为左上角像素）。"""
    s = size

    def P(fx: float, fy: float) -> Tuple[float, float]:
        return ox + fx * s, oy + fy * s

    cv.create_rectangle(ox, oy, ox + s, oy + s, fill=COL_FIELD,
                        outline="#3d4a30", width=1, tags=tags)
    # 田地网格纹理
    for i in (1, 2):
        cv.create_line(P(0, i / 3), P(1, i / 3), fill=COL_FIELD_DARK,
                       width=1, tags=tags)

    # 城市：每边梯形 + 多边时中心补块 + 外沿城墙
    for edges, pennant in tile.rotated_cities(rot):
        for e in edges:
            if e == 0:
                pts = [P(0.14, 0.0), P(0.86, 0.0), P(0.72, 0.36), P(0.28, 0.36)]
            elif e == 1:
                pts = [P(1.0, 0.14), P(1.0, 0.86), P(0.64, 0.72), P(0.64, 0.28)]
            elif e == 2:
                pts = [P(0.14, 1.0), P(0.86, 1.0), P(0.72, 0.64), P(0.28, 0.64)]
            else:
                pts = [P(0.0, 0.14), P(0.0, 0.86), P(0.36, 0.72), P(0.36, 0.28)]
            cv.create_polygon(pts, fill=COL_CITY, outline=COL_CITY_WALL,
                              width=1, tags=tags)
        if len(edges) >= 2:
            cv.create_oval(P(0.26, 0.26), P(0.74, 0.74), fill=COL_CITY,
                           outline=COL_CITY_WALL, width=1, tags=tags)
        for e in edges:  # 城墙垛口
            if e == 0:
                cv.create_line(P(0.12, 0.02), P(0.88, 0.02), fill=COL_CITY_WALL,
                               width=4, tags=tags)
            elif e == 1:
                cv.create_line(P(0.98, 0.12), P(0.98, 0.88), fill=COL_CITY_WALL,
                               width=4, tags=tags)
            elif e == 2:
                cv.create_line(P(0.12, 0.98), P(0.88, 0.98), fill=COL_CITY_WALL,
                               width=4, tags=tags)
            else:
                cv.create_line(P(0.02, 0.12), P(0.02, 0.88), fill=COL_CITY_WALL,
                               width=4, tags=tags)
        if pennant:
            ax, ay = P(0.5, 0.44)
            r = s * 0.08
            cv.create_polygon(ax - r, ay - r * 1.3, ax + r, ay - r * 1.3,
                              ax + r, ay + r * 0.4, ax, ay + r * 1.1,
                              ax - r, ay + r * 0.4,
                              fill="#4d6fb5", outline="#2c3f6e", width=1, tags=tags)

    # 道路：边中点 → 中心的折线（双层描边）
    for edges in tile.rotated_roads(rot):
        mids = [EDGE_MID[e] for e in edges]
        path = [P(*mids[0]), P(0.5, 0.5)]
        if len(mids) > 1:
            path.append(P(*mids[1]))
            if {edges[0], edges[1]} in ({0, 2}, {1, 3}):
                path = [P(*mids[0]), P(*mids[1])]  # 直路不绕中心
        cv.create_line(path, fill=COL_ROAD_BORDER, width=max(3, int(s * 0.16)),
                       capstyle="round", tags=tags)
        cv.create_line(path, fill=COL_ROAD, width=max(2, int(s * 0.10)),
                       capstyle="round", tags=tags)

    # 中心
    if tile.center.value == 1:  # 修道院
        cv.create_rectangle(P(0.34, 0.42), P(0.66, 0.72), fill=COL_MON,
                            outline="#5e3524", width=1, tags=tags)
        cv.create_polygon(P(0.30, 0.44), P(0.70, 0.44), P(0.5, 0.24),
                           fill="#7a4632", outline="#5e3524", width=1, tags=tags)
        cv.create_rectangle(P(0.46, 0.56), P(0.54, 0.72), fill="#e8dcc0",
                            outline="#5e3524", tags=tags)
    elif tile.center.value == 2:  # 交叉口
        cv.create_oval(P(0.42, 0.42), P(0.58, 0.58), fill=COL_ROAD,
                       outline=COL_ROAD_BORDER, width=2, tags=tags)

    # 起始牌徽记
    if tile.is_start:
        cv.create_rectangle(ox + 2, oy + 2, ox + s - 2, oy + s - 2,
                            outline="#2e2417", width=2, tags=tags)


def draw_meeple(cv: tk.Canvas, px: float, py: float, size: float, color: str,
                farmer: bool = False, tags: str = "meeple") -> None:
    """在 (px,py) 画一个米宝（农夫为横躺椭圆）。"""
    fill = COLOR_HEX.get(color, "#888")
    r = size * 0.085
    if farmer:
        cv.create_oval(px - r * 1.35, py - r * 0.7, px + r * 1.35, py + r * 0.7,
                       fill=fill, outline="white", width=1, tags=tags)
    else:
        cv.create_oval(px - r, py - r, px + r, py + r, fill=fill,
                       outline="white", width=1, tags=tags)
        cv.create_oval(px - r * 0.45, py - r * 0.95, px + r * 0.45, py - r * 0.05,
                       fill=fill, outline="white", width=1, tags=tags)

