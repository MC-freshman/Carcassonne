# -*- coding: utf-8 -*-
"""素材生成器：用 PIL 渲染高清牌面/米宝/计分板贴图。

- 牌面：按 tile_data 的拓扑定义程序化绘制（田野纹理/城墙垛口/角塔/旗帜/
  平滑道路/修道院/村庄广场），master 尺寸 168px
- 米宝：站立小人（农夫为横躺），六色
- 计分板：双行 0–50 循环轨道（上行 0–25 左→右，下行 26–50 右→左）

输出目录 assets/；UI 通过 SpriteStore 加载，缺失时自动生成。
"""
from __future__ import annotations

import math
import os
import random
import sys
from typing import Dict, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

from .models import Center, Terrain
from . import tile_data


def _base_dir() -> str:
    """项目根目录；PyInstaller 打包后为资源解压目录 _MEIPASS。"""
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


ASSET_DIR = os.path.join(_base_dir(), "assets")
TILE_DIR = os.path.join(ASSET_DIR, "tiles")
MASTER = 168          # 牌面 master 尺寸
MEEPLE_MASTER = 40    # 米宝 master 尺寸
SCORE_W, SCORE_H = 500, 64

# ---------------------------------------------------------------- 调色板
COL_FIELD = (139, 170, 100)
COL_FIELD_DK = (118, 148, 84)
COL_CITY = (206, 182, 138)
COL_CITY_DK = (164, 137, 94)
COL_CITY_WALL = (116, 92, 62)
COL_ROAD = (229, 215, 168)
COL_ROAD_DK = (168, 147, 100)
COL_MON = (156, 90, 65)
COL_TREE = (96, 128, 62)
COL_TREE_DK = (74, 104, 50)


def _font(size: int):
    try:
        return ImageFont.truetype("arial.ttf", size)
    except OSError:
        return ImageFont.load_default()


def _shade(c: Tuple[int, int, int], k: float) -> Tuple[int, int, int]:
    return tuple(max(0, min(255, int(v * k))) for v in c)


# ---------------------------------------------------------------- 几何工具

def edge_mid(e: int) -> Tuple[float, float]:
    return ((0.5, 0.0), (1.0, 0.5), (0.5, 1.0), (0.0, 0.5))[e]


def pull(p: Tuple[float, float], t: float) -> Tuple[float, float]:
    return (p[0] + (0.5 - p[0]) * t, p[1] + (0.5 - p[1]) * t)


def P(px: float, py: float, s: int = MASTER) -> Tuple[float, float]:
    return px * s, py * s


def bezier(d: ImageDraw.ImageDraw, a, b, ctrl, w, fill, steps=24):
    pts = []
    for i in range(steps + 1):
        t = i / steps
        x = (1 - t) ** 2 * a[0] + 2 * (1 - t) * t * ctrl[0] + t ** 2 * b[0]
        y = (1 - t) ** 2 * a[1] + 2 * (1 - t) * t * ctrl[1] + t ** 2 * b[1]
        pts.append((x, y))
    d.line(pts, fill=fill, width=int(w), joint="curve")


# ---------------------------------------------------------------- 牌面

def render_tile(tile, rot: int = 0) -> Image.Image:
    """渲染一张牌的指定朝向。"""
    s = MASTER
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    rng = random.Random(hash(tile.tile_id) & 0xFFFF)

    # ---- 田野底 + 噪点纹理
    d.rectangle([0, 0, s, s], fill=COL_FIELD)
    for _ in range(160):
        x, y = rng.uniform(0, s), rng.uniform(0, s)
        r = rng.uniform(1.5, 3.2)
        c = COL_FIELD_DK if rng.random() < 0.5 else COL_FIELD
        d.ellipse([x - r, y - r, x + r, y + r], fill=c)
    # 田埂/小径
    for _ in range(5):
        x, y = rng.uniform(0.06, 0.94) * s, rng.uniform(0.06, 0.94) * s
        d.ellipse([x - 2, y - 2, x + 2, y + 2], fill=COL_FIELD_DK)

    cities = tile.rotated_cities(rot)
    roads = tile.rotated_roads(rot)
    inn_edges = [es for es, inn in roads if inn]
    cath_segs = [cs for cs, _p, cath in cities if cath]
    farm_edges = [e for e, _ in tile.rotated_farms(rot) for e in e]
    city_edge_set = {e for es, _p, _c in cities for e in es}

    # ---- 田野装饰（树/灌木，避开城与路）
    road_pts = []
    for es, _inn in roads:
        for e in es:
            road_pts.append(edge_mid(e))
    road_pts.append((0.5, 0.5))
    for _ in range(14):
        fx, fy = rng.uniform(0.08, 0.92), rng.uniform(0.08, 0.92)
        # 离中心/路边/城边太近则跳过
        if math.dist((fx, fy), (0.5, 0.5)) < 0.24:
            continue
        if any(math.dist((fx, fy), p) < 0.22 for p in road_pts):
            continue
        if any(edge_mid(e)[0] - fx < 0.22 and abs(edge_mid(e)[1] - fy) < 0.30
               for e in city_edge_set):
            continue
        tx, ty = fx * s, fy * s
        r = rng.uniform(4.5, 7.0)
        d.ellipse([tx - r, ty - r * 0.6, tx + r, ty + r * 0.6],
                  fill=COL_TREE_DK)
        d.ellipse([tx - r * 0.8, ty - r * 1.5, tx + r * 0.8, ty + r * 0.2],
                  fill=COL_TREE)
        d.line([tx, ty + r * 0.5, tx, ty + r * 0.9], fill=(90, 72, 46), width=2)
        # 小花
        for _ in range(3):
            ax = tx + rng.uniform(-r * 1.4, r * 1.4)
            ay = ty + rng.uniform(-r * 1.4, r * 1.4)
            if 0 < ax < s and 0 < ay < s:
                d.ellipse([ax - 1.4, ay - 1.4, ax + 1.4, ay + 1.4],
                          fill=(226, 214, 130))

    # ---- M18 伯爵城：城内石板底 + 城墙（沿城边内缩一圈）+ 屋顶点缀
    if tile.count_city:
        d.rectangle([s * 0.16, s * 0.16, s * 0.84, s * 0.84],
                    fill=(198, 172, 132))
        for _ in range(40):
            x = rng.uniform(0.18, 0.82) * s
            y = rng.uniform(0.18, 0.82) * s
            d.ellipse([x - 2, y - 2, x + 2, y + 2], fill=(186, 158, 118))
        for e in sorted(city_edge_set):
            mx, my = edge_mid(e)
            # 城墙：平行于城边、内缩 0.16 的墙线
            if e == 0:
                d.line([s * 0.16, s * 0.16, s * 0.84, s * 0.16],
                       fill=(150, 122, 88), width=int(s * 0.055))
            elif e == 2:
                d.line([s * 0.16, s * 0.84, s * 0.84, s * 0.84],
                       fill=(150, 122, 88), width=int(s * 0.055))
            elif e == 3:
                d.line([s * 0.16, s * 0.16, s * 0.16, s * 0.84],
                       fill=(150, 122, 88), width=int(s * 0.055))
            else:
                d.line([s * 0.84, s * 0.16, s * 0.84, s * 0.84],
                       fill=(150, 122, 88), width=int(s * 0.055))
        for _ in range(6):
            hx = rng.uniform(0.24, 0.76) * s
            hy = rng.uniform(0.24, 0.76) * s
            r = s * 0.035
            d.polygon([(hx - r, hy), (hx + r, hy), (hx, hy - r * 1.1)],
                      fill=(178, 84, 56))
            d.rectangle([hx - r * 0.7, hy, hx + r * 0.7, hy + r * 0.9],
                        fill=(214, 190, 150))

    # ---- 河流（M18 River II）：水边经牌心连成水道（先水后路，桥面自然覆盖）
    water_edges = sorted(e for e in range(4)
                         if tile.edge(e, rot) is Terrain.WATER)
    if water_edges:
        COL_WATER = (122, 152, 202)
        COL_WATER_DK = (96, 126, 178)
        if len(water_edges) == 1:
            m = edge_mid(water_edges[0])
            bezier(d, P(*m), P(0.5, 0.5), P(0.5, 0.5), s * 0.16, COL_WATER_DK)
            bezier(d, P(*m), P(0.5, 0.5), P(0.5, 0.5), s * 0.11, COL_WATER)
            # 湖面（泉源/火山湖/湖城）
            lr = s * (0.20 if tile.spring or tile.volcano else 0.16)
            d.ellipse([s / 2 - lr, s / 2 - lr * 0.8, s / 2 + lr, s / 2 + lr * 0.8],
                      fill=COL_WATER, outline=COL_WATER_DK, width=2)
            if tile.spring:
                for _ in range(5):
                    rx = rng.uniform(s * 0.42, s * 0.58)
                    ry = rng.uniform(s * 0.44, s * 0.56)
                    d.ellipse([rx - 3, ry - 3, rx + 3, ry + 3],
                              fill=(120, 116, 108))
        else:
            for e in water_edges:
                m = edge_mid(e)
                bezier(d, P(*m), P(0.5, 0.5), P(0.5, 0.5), s * 0.16,
                       COL_WATER_DK)
            for e in water_edges:
                m = edge_mid(e)
                bezier(d, P(*m), P(0.5, 0.5), P(0.5, 0.5), s * 0.11, COL_WATER)

    # ---- 道路
    for es, _inn in roads:
        if len(es) == 2:
            a, b = edge_mid(es[0]), edge_mid(es[1])
            if {es[0], es[1]} in ({0, 2}, {1, 3}):
                bezier(d, P(*a), P(*b), P(0.5, 0.5), s * 0.135, COL_ROAD_DK)
                bezier(d, P(*a), P(*b), P(0.5, 0.5), s * 0.085, COL_ROAD)
            else:  # 弯路
                bezier(d, P(*a), P(*b), P(0.5, 0.5), s * 0.135, COL_ROAD_DK)
                bezier(d, P(*a), P(*b), P(0.5, 0.5), s * 0.085, COL_ROAD)
        else:  # 单边（城门/修道院路/断头路）
            m = edge_mid(es[0])
            end = pull(m, 0.52)
            d.line([P(*m), P(*end)], fill=COL_ROAD_DK, width=int(s * 0.135))
            d.line([P(*m), P(*end)], fill=COL_ROAD, width=int(s * 0.085))

    # ---- 客栈（I&C）：路旁小房子 + 湖水
    for es, _inn in roads:
        if not _inn:
            continue
        mids = [edge_mid(e) for e in es]
        mx = sum(m[0] for m in mids) / len(mids)
        my = sum(m[1] for m in mids) / len(mids)
        hx, hy = pull((mx, my), 0.30)
        hx, hy = hx * s, hy * s
        # 湖水
        d.ellipse([hx - s * 0.10, hy + s * 0.045, hx + s * 0.10, hy + s * 0.13],
                  fill=(110, 170, 190), outline=(70, 120, 145), width=1)
        # 客栈小屋
        d.rectangle([hx - s * 0.05, hy - s * 0.05, hx + s * 0.05, hy + s * 0.03],
                    fill=(176, 138, 92), outline=(110, 84, 52), width=1)
        d.polygon([(hx - s * 0.06, hy - s * 0.05), (hx + s * 0.06, hy - s * 0.05),
                   (hx, hy - s * 0.11)], fill=(140, 96, 60), outline=(110, 84, 52))

    # ---- 贸易商品（T&B）：城市内的小符号（酒杯紫/谷穗金/布卷青）
    for cs_edges, _p, _cath, cs_goods in (
            (es, p, cath, tile.cities[i].goods)
            for i, (es, p, cath) in enumerate(cities)):
        if not cs_goods:
            continue
        mids = [edge_mid(e) for e in cs_edges]
        gx = sum(m[0] for m in mids) / len(mids) * s
        gy = sum(m[1] for m in mids) / len(mids) * s
        gx, gy = (s / 2 + gx) / 2, (s / 2 + gy) / 2
        colors = {"wine": (150, 60, 130), "grain": (216, 178, 60),
                  "cloth": (70, 150, 160)}
        for i, gt in enumerate(cs_goods):
            ox = gx + (i - (len(cs_goods) - 1) / 2) * s * 0.12
            r = s * 0.045
            c = colors.get(gt, (100, 100, 100))
            if gt == "wine":
                d.polygon([(ox - r, gy - r), (ox + r, gy - r), (ox, gy + r * 1.2)],
                          fill=c, outline=(90, 40, 80))
            elif gt == "grain":
                d.line([(ox, gy + r), (ox, gy - r)], fill=c, width=2)
                d.ellipse([ox - r * 0.6, gy - r * 1.4, ox + r * 0.6, gy - r * 0.2],
                          fill=c)
            else:
                d.ellipse([ox - r, gy - r * 0.7, ox + r, gy + r * 0.7],
                          fill=c, outline=(40, 100, 110), width=1)

    # ---- 建造者（T&B）：路上的小人 + 锤
    if tile.builder:
        r_eds = [e for es, _i in roads for e in es]
        if r_eds:
            mids = [edge_mid(e) for e in r_eds]
            bx = sum(m[0] for m in mids) / len(mids) * s
            by = sum(m[1] for m in mids) / len(mids) * s
            bx, by = (s / 2 + bx) / 2, (s / 2 + by) / 2
            r = s * 0.05
            d.ellipse([bx - r, by - r * 1.6, bx + r, by - r * 0.4],
                      fill=(90, 110, 200), outline=(50, 65, 130), width=1)
            d.rounded_rectangle([bx - r * 0.8, by - r * 0.3, bx + r * 0.8, by + r * 1.4],
                                radius=r * 0.5, fill=(90, 110, 200),
                                outline=(50, 65, 130), width=1)
            d.line([bx + r * 0.5, by - r * 0.2, bx + r * 1.6, by + r * 0.4],
                   fill=(120, 90, 50), width=2)

    # ---- 猪（T&B）：农场上的粉色小猪
    if tile.pig:
        f_eds = [e for fs, _a in tile.rotated_farms(rot) for e in fs]
        if f_eds:
            mids = [edge_mid(e) for e in f_eds]
            px2 = sum(m[0] for m in mids) / len(mids) * s
            py2 = sum(m[1] for m in mids) / len(mids) * s
            px2, py2 = (s / 2 + px2) / 2, (s / 2 + py2) / 2
            r = s * 0.055
            d.ellipse([px2 - r * 1.3, py2 - r * 0.7, px2 + r * 1.3, py2 + r * 0.8],
                      fill=(238, 170, 170), outline=(190, 120, 120), width=1)
            d.ellipse([px2 + r * 0.9, py2 - r * 0.5, px2 + r * 1.4, py2],
                      fill=(238, 170, 170), outline=(190, 120, 120), width=1)
            d.line([px2 - r * 1.2, py2 - r * 0.2, px2 - r * 1.6, py2 - r * 0.5],
                   fill=(190, 120, 120), width=1)

    # ---- P&D 图元：火山/龙/公主/传送门
    if tile.volcano:
        cx, cy = s / 2, s / 2
        d.ellipse([cx - s * 0.09, cy - s * 0.09, cx + s * 0.09, cy + s * 0.09],
                  fill=(92, 78, 72), outline=(52, 42, 38), width=2)
        d.polygon([(cx - s * 0.045, cy), (cx + s * 0.045, cy),
                   (cx, cy - s * 0.075)], fill=(200, 90, 50))
    if tile.dragon_tile:
        cx, cy = s / 2, s / 2
        d.text((cx, cy), "🐉", font=_font(int(s * 0.16)), anchor="mm",
               fill=(60, 120, 60))
    if tile.princess:
        cx, cy = s / 2, s / 2
        d.text((cx, cy), "👸", font=_font(int(s * 0.16)), anchor="mm",
               fill=(180, 120, 160))
    if tile.portal:
        cx, cy = s / 2, s / 2
        d.ellipse([cx - s * 0.10, cy - s * 0.10, cx + s * 0.10, cy + s * 0.10],
                  outline=(150, 90, 190), width=3)
        d.ellipse([cx - s * 0.05, cy - s * 0.05, cx + s * 0.05, cy + s * 0.05],
                  fill=(190, 140, 220))

    # ---- A&M 图元：市长（礼帽）/粮仓（谷仓图形）/马车（车轮）
    if tile.mayor:
        cx, cy = s / 2, s / 2
        d.text((cx, cy), "🎩", font=_font(int(s * 0.16)), anchor="mm",
               fill=(80, 90, 160))
    if tile.barn:
        cx, cy = s / 2, s / 2
        d.text((cx, cy), "🏚", font=_font(int(s * 0.16)), anchor="mm",
               fill=(170, 120, 80))
    if tile.wagon:
        cx, cy = s / 2, s / 2
        d.text((cx, cy), "🛒", font=_font(int(s * 0.15)), anchor="mm",
               fill=(140, 100, 60))
    if tile.abbey:
        d.rounded_rectangle([s * 0.06, s * 0.06, s * 0.94, s * 0.94],
                            radius=8, outline=(90, 70, 40), width=2)

    # ---- M18 图元：教堂（S&H 神龛）/ 猪倌（RII 牧帐）
    if tile.shrine:
        cx, cy = s / 2, s / 2
        d.text((cx, cy), "⛩", font=_font(int(s * 0.17)), anchor="mm",
               fill=(150, 70, 60))
    if tile.pig_herd:
        cx, cy = s / 2, s / 2
        d.text((cx, cy), "🐑", font=_font(int(s * 0.15)), anchor="mm",
               fill=(230, 220, 200))
    if tile.bazaar:
        cx, cy = s / 2, s / 2
        d.ellipse([cx - s * 0.11, cy - s * 0.08, cx + s * 0.11, cy + s * 0.08],
                  fill=(230, 190, 70), outline=(180, 140, 40), width=2)
        d.text((cx, cy), "市", font=_font(int(s * 0.10)), anchor="mm",
               fill=(120, 80, 20))

    # ---- 大教堂（I&C）：城市内的教堂塔楼
    for ci, (es, pennant, cath) in enumerate(cities):
        if not cath:
            continue
        mids = [edge_mid(e) for e in es]
        cx2 = sum(m[0] for m in mids) / len(mids) * s
        cy2 = sum(m[1] for m in mids) / len(mids) * s
        tx, ty = (s / 2 + cx2) / 2, (s / 2 + cy2) / 2  # 偏向城市中心
        r = s * 0.075
        d.polygon([(tx - r, ty + r * 0.6), (tx + r, ty + r * 0.6),
                   (tx, ty - r * 1.1)], fill=(120, 96, 70),
                  outline=(80, 60, 42), width=1)
        d.line([tx, ty - r * 1.5, tx, ty - r * 0.9], fill=(70, 54, 38), width=2)
        d.line([tx - r * 0.35, ty - r * 1.35, tx + r * 0.35, ty - r * 1.35],
               fill=(70, 54, 38), width=2)

    # ---- 城市
    for ci, (es, pennant, _cath) in enumerate(cities):
        mids = [edge_mid(e) for e in es]
        cx = sum(m[0] for m in mids) / len(mids)
        cy = sum(m[1] for m in mids) / len(mids)
        bands = []
        for e in es:
            if e == 0:
                bands.append([(0.13, 0.0), (0.87, 0.0), (0.70, 0.30), (0.30, 0.30)])
            elif e == 1:
                bands.append([(1.0, 0.13), (1.0, 0.87), (0.70, 0.70), (0.70, 0.30)])
            elif e == 2:
                bands.append([(0.13, 1.0), (0.87, 1.0), (0.70, 0.70), (0.30, 0.70)])
            else:
                bands.append([(0.0, 0.13), (0.0, 0.87), (0.30, 0.70), (0.30, 0.30)])
        # 中心连接块
        if len(es) >= 2:
            d.ellipse([P(cx - 0.27, cy - 0.27), P(cx + 0.27, cy + 0.27)],
                      fill=COL_CITY, outline=COL_CITY_DK, width=2)
        for band in bands:
            pts = [P(*q) for q in band]
            d.polygon(pts, fill=COL_CITY, outline=COL_CITY_DK, width=2)
            # 内沿阴影
            inner = [P(*pull(q, 0.28)) for q in band]
            d.line(inner, fill=_shade(COL_CITY, 0.88), width=2)
        # 垛口 + 角塔
        for e in es:
            if e == 0:
                for i in range(6):
                    x0 = s * (0.13 + i * 0.12)
                    d.rectangle([x0, 0, x0 + s * 0.075, s * 0.045],
                                fill=COL_CITY_WALL)
                d.ellipse([s * 0.10, -2, s * 0.10 + s * 0.06, s * 0.06],
                          fill=_shade(COL_CITY_WALL, 1.25), outline=COL_CITY_WALL)
                d.ellipse([s * 0.84, -2, s * 0.84 + s * 0.06, s * 0.06],
                          fill=_shade(COL_CITY_WALL, 1.25), outline=COL_CITY_WALL)
            elif e == 1:
                for i in range(6):
                    y0 = s * (0.13 + i * 0.12)
                    d.rectangle([s - s * 0.045, y0, s, y0 + s * 0.075],
                                fill=COL_CITY_WALL)
                d.ellipse([s - s * 0.06, s * 0.10, s + 2, s * 0.16],
                          fill=_shade(COL_CITY_WALL, 1.25), outline=COL_CITY_WALL)
                d.ellipse([s - s * 0.06, s * 0.84, s + 2, s * 0.90],
                          fill=_shade(COL_CITY_WALL, 1.25), outline=COL_CITY_WALL)
            elif e == 2:
                for i in range(6):
                    x0 = s * (0.13 + i * 0.12)
                    d.rectangle([x0, s - s * 0.045, x0 + s * 0.075, s],
                                fill=COL_CITY_WALL)
                d.ellipse([s * 0.10, s - s * 0.06, s * 0.16, s + 2],
                          fill=_shade(COL_CITY_WALL, 1.25), outline=COL_CITY_WALL)
                d.ellipse([s * 0.84, s - s * 0.06, s * 0.90, s + 2],
                          fill=_shade(COL_CITY_WALL, 1.25), outline=COL_CITY_WALL)
            else:
                for i in range(6):
                    y0 = s * (0.13 + i * 0.12)
                    d.rectangle([0, y0, s * 0.045, y0 + s * 0.075],
                                fill=COL_CITY_WALL)
                d.ellipse([-2, s * 0.10, s * 0.06, s * 0.16],
                          fill=_shade(COL_CITY_WALL, 1.25), outline=COL_CITY_WALL)
                d.ellipse([-2, s * 0.84, s * 0.06, s * 0.90],
                          fill=_shade(COL_CITY_WALL, 1.25), outline=COL_CITY_WALL)
        # 旗帜
        if pennant:
            px, py = pull((cx, cy), 0.10)
            px, py = px * s, py * s
            d.line([px, py - s * 0.10, px, py + s * 0.10],
                   fill=(90, 72, 46), width=2)
            r = s * 0.055
            d.polygon([(px + r * 0.4, py - s * 0.14), (px + r * 2.0, py - s * 0.10),
                       (px + r * 0.4, py - s * 0.02)],
                      fill=(190, 60, 55))
            d.ellipse([px - r, py + s * 0.02, px + r, py + s * 0.02 + r * 2],
                      fill=(74, 105, 172), outline=(40, 60, 110), width=2)

    # ---- 修道院
    if tile.center is Center.MONASTERY:
        cx, cy = s / 2, s / 2
        d.ellipse([cx - s * 0.24, cy - s * 0.24, cx + s * 0.24, cy + s * 0.24],
                  fill=(120, 150, 88), outline=COL_FIELD_DK, width=2)
        d.rectangle([cx - s * 0.13, cy - s * 0.06, cx + s * 0.13, cy + s * 0.16],
                    fill=COL_MON, outline=_shade(COL_MON, 0.65), width=2)
        d.polygon([(cx - s * 0.17, cy - s * 0.05), (cx + s * 0.17, cy - s * 0.05),
                   (cx, cy - s * 0.20)],
                  fill=_shade(COL_MON, 1.25), outline=_shade(COL_MON, 0.65), width=2)
        d.line([cx, cy - s * 0.27, cx, cy - s * 0.20], fill=(90, 72, 46), width=2)
        d.line([cx - s * 0.035, cy - s * 0.235, cx + s * 0.035, cy - s * 0.235],
               fill=(90, 72, 46), width=2)
        d.rectangle([cx - s * 0.045, cy + s * 0.05, cx + s * 0.045, cy + s * 0.16],
                    fill=(226, 210, 176), outline=_shade(COL_MON, 0.65))
        d.ellipse([cx - s * 0.10, cy - s * 0.16, cx - s * 0.02, cy - s * 0.08],
                  fill=COL_TREE, outline=COL_TREE_DK)
        d.ellipse([cx + s * 0.02, cy - s * 0.18, cx + s * 0.11, cy - s * 0.10],
                  fill=COL_TREE, outline=COL_TREE_DK)

    # ---- 交叉口（村庄广场）
    if tile.center is Center.JUNCTION:
        cx, cy = s / 2, s / 2
        d.ellipse([cx - s * 0.13, cy - s * 0.13, cx + s * 0.13, cy + s * 0.13],
                  fill=(216, 198, 158), outline=COL_ROAD_DK, width=2)
        d.ellipse([cx - s * 0.13, cy - s * 0.13, cx + s * 0.13, cy + s * 0.13],
                  outline=(168, 147, 100), width=1)
        # 广场上的小房子
        for (hx, hy) in ((-0.07, -0.03), (0.05, 0.06)):
            hx, hy = cx + hx * s, cy + hy * s
            d.rectangle([hx - s * 0.035, hy - s * 0.02, hx + s * 0.035, hy + s * 0.03],
                        fill=(150, 110, 82), outline=(100, 72, 52), width=1)
            d.polygon([(hx - s * 0.045, hy - s * 0.02), (hx + s * 0.045, hy - s * 0.02),
                       (hx, hy - s * 0.055)], fill=(120, 84, 60))

    # ---- 边框
    d.rounded_rectangle([1, 1, s - 2, s - 2], radius=10,
                        outline=(70, 60, 40), width=3)
    d.rounded_rectangle([4, 4, s - 5, s - 5], radius=8,
                        outline=(250, 244, 224), width=1)
    return img


# ---------------------------------------------------------------- 米宝

def render_meeple(color: str, farmer: bool = False) -> Image.Image:
    from .engine import COLOR_HEX
    hexv = COLOR_HEX.get(color, "#888888")
    base = tuple(int(hexv[i:i + 2], 16) for i in (1, 3, 5))
    dark = _shade(base, 0.72)
    s = MEEPLE_MASTER
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx, cy = s / 2, s * 0.56
    # 阴影
    d.ellipse([cx - 10, cy + 10, cx + 10, cy + 16], fill=(0, 0, 0, 70))
    if farmer:
        # 横躺的农夫
        d.rounded_rectangle([cx - 15, cy - 6, cx + 15, cy + 6], radius=6,
                            fill=base, outline=dark, width=2)
        d.ellipse([cx - 15, cy - 10, cx - 4, cy + 1], fill=base, outline=dark, width=2)
        d.rounded_rectangle([cx - 17, cy - 12, cx - 10, cy - 2], radius=3,
                            fill=dark)
    else:
        # 站立随从：斗篷 + 头 + 帽
        d.rounded_rectangle([cx - 8, cy - 8, cx + 8, cy + 12], radius=6,
                            fill=base, outline=dark, width=2)
        d.polygon([(cx - 10, cy - 2), (cx + 10, cy - 2), (cx, cy - 16)],
                  fill=base, outline=dark, width=2)
        d.ellipse([cx - 6, cy - 18, cx + 6, cy - 7], fill=base, outline=dark, width=2)
        d.rectangle([cx - 8, cy - 19, cx + 8, cy - 15], fill=dark)
    # 高光
    d.ellipse([cx - 4, cy - 16, cx - 1, cy - 12], fill=(255, 255, 255, 120))
    return img


# ---------------------------------------------------------------- 计分板

def render_scoreboard() -> Image.Image:
    s_w, s_h = SCORE_W, SCORE_H
    img = Image.new("RGBA", (s_w, s_h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, s_w - 1, s_h - 1], radius=12,
                        fill=(58, 66, 46), outline=(120, 110, 80), width=2)
    # 双行轨道：上 0-25 左→右，下 26-50 右→左
    cell = 18
    y0, y1 = 8, 36
    for row, (lo, hi, rev) in enumerate(((0, 25, False), (26, 50, True))):
        y = y0 if row == 0 else y1
        for v in range(lo, hi + 1):
            i = v - lo
            x = i * cell if not rev else (hi - lo - i) * cell
            x += 10
            odd = v % 2
            fill = (72, 82, 56) if odd else (84, 94, 64)
            d.rounded_rectangle([x + 1, y, x + cell - 1, y + 22], radius=5,
                                fill=fill, outline=(110, 120, 86), width=1)
            if v % 5 == 0:
                d.text((x + cell // 2, y + 5), str(v), fill=(240, 232, 200),
                       font=_font(11), anchor="mm")
            else:
                d.ellipse([x + cell // 2 - 2, y + 11, x + cell // 2 + 2, y + 15],
                          fill=(200, 195, 160))
    # 50 之后的分段提示（0 格上方「×2」）
    d.text((10 + 25 * cell + 8, 4), "×2", fill=(226, 200, 120), font=_font(10))
    return img


def score_pos(score: int, w: int = SCORE_W, h: int = SCORE_H) -> Tuple[float, float]:
    """计分板轨道上分数对应的像素坐标（与 render_scoreboard 布局一致）。"""
    pos = score % 51
    lap = score // 51
    cell = 18
    if pos <= 25:
        x = 10 + pos * cell + cell / 2
        y = 8 + 11
    else:
        x = 10 + (50 - pos) * cell + cell / 2
        y = 36 + 11
    kx, ky = w / SCORE_W, h / SCORE_H
    return x * kx, y * ky + (4 if lap else 0)


# ---------------------------------------------------------------- 生成与加载

def ensure_assets(force: bool = False) -> None:
    """生成全部素材 PNG（已存在且非 force 时跳过）。牌面含 4 个旋转方向。"""
    os.makedirs(TILE_DIR, exist_ok=True)
    need = []
    tiles = tile_data.all_definitions(
        ["inns", "traders", "pd", "abbey", "king", "river", "shrine", "bcb"])
    tiles += [t for _c, _r, t in tile_data.CC_BLOCK]
    for tile in tiles:
        for rot in range(4):
            p = os.path.join(TILE_DIR, "%s_r%d.png" % (tile.tile_id, rot))
            if force or not os.path.exists(p):
                need.append((tile, rot, p))
    if need:
        for tile, rot, p in need:
            render_tile(tile, rot).save(p)
    meeple_dir = os.path.join(ASSET_DIR, "meeples")
    os.makedirs(meeple_dir, exist_ok=True)
    from .engine import PLAYER_COLORS
    for color in PLAYER_COLORS:
        for farmer in (False, True):
            p = os.path.join(meeple_dir, "%s_%s.png" % (color, "f" if farmer else "s"))
            if force or not os.path.exists(p):
                render_meeple(color, farmer).save(p)
    sb = os.path.join(ASSET_DIR, "scoreboard.png")
    if force or not os.path.exists(sb):
        render_scoreboard().save(sb)


class SpriteStore:
    """Tk 端贴图加载（需已有 Tk root）。缺失时自动生成。"""

    def __init__(self, root) -> None:
        self.root = root
        try:
            ensure_assets()
            self._tiles: Dict[Tuple[str, int], object] = {}
            self._meeples: Dict[Tuple[str, bool], object] = {}
            self._sb: Optional[object] = None
            self.ok = True
        except Exception:
            self.ok = False

    def tile(self, tile_id: str, rot: int = 0) -> Optional[object]:
        key = (tile_id, rot)
        img = self._tiles.get(key)
        if img is None:
            from tkinter import PhotoImage
            img = PhotoImage(master=self.root, file=os.path.join(
                TILE_DIR, "%s_r%d.png" % (tile_id, rot)))
            self._tiles[key] = img
        return img

    def meeple(self, color: str, farmer: bool) -> object:
        key = (color, farmer)
        img = self._meeples.get(key)
        if img is None:
            from tkinter import PhotoImage
            img = PhotoImage(master=self.root, file=os.path.join(
                ASSET_DIR, "meeples", "%s_%s.png" % (color, "f" if farmer else "s")))
            self._meeples[key] = img
        return img

    def scoreboard(self) -> object:
        if self._sb is None:
            from tkinter import PhotoImage
            self._sb = PhotoImage(master=self.root,
                                  file=os.path.join(ASSET_DIR, "scoreboard.png"))
        return self._sb


if __name__ == "__main__":
    import time
    t0 = time.time()
    ensure_assets(force=True)
    print("素材已生成到 assets/（%.1fs）" % (time.time() - t0))
