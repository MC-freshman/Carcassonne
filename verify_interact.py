# -*- coding: utf-8 -*-
"""交互验证：用 event_generate 模拟真实鼠标事件，驱动人类玩家完整对局。

覆盖：合法格点击放置、非法格点击提示、旋转、部署锚点点击、跳过按钮、
弃牌按钮状态、AI 回合推进、终局弹窗。
"""
from __future__ import annotations

import sys
import traceback

from game.ui import App, TILE

FAILS = []


def check(cond: bool, msg: str) -> None:
    if cond:
        print("  [ok] %s" % msg)
    else:
        FAILS.append(msg)
        print("  [FAIL] %s" % msg)


def cell_center_px(app: App, x: int, y: int):
    px, py = app.cell_px(x, y)
    return px + TILE / 2, py + TILE / 2


def click(app: App, px: float, py: float) -> None:
    """在画布坐标 (px,py) 处模拟点击：先反变换为控件坐标（滚动偏移）。"""
    wx = px - app.canvas.canvasx(0)
    wy = py - app.canvas.canvasy(0)
    app.canvas.event_generate("<Button-1>", x=int(wx), y=int(wy))
    app.update_idletasks()
    app.update()


def run() -> None:
    specs = [
        {"name": "人类"},
        {"name": "AI", "is_ai": True, "ai_level": "normal"},
    ]
    app = App(specs, seed=11)
    app.update_idletasks()
    app.update()
    app.after = lambda ms, fn, *a, **k: None  # 测试禁用定时调度，避免幽灵推进

    # --- 1) 非法格点击：远离棋盘的空格应触发提示，不崩溃
    eng = app.engine
    far_x, far_y = cell_center_px(app, 8, 8)
    click(app, far_x, far_y)
    check(eng.phase == "place", "非法格点击不改变阶段")

    # --- 2) 旋转 4 次回到 0
    r0 = app.rot
    for _ in range(4):
        app.rotate()
    check(app.rot == r0, "旋转 4 次回原朝向")

    # --- 2.5) 滚动一致性：棋盘滚动后，鼠标位置与高亮格映射仍准确
    # 先快速铺十几张牌，使 scrollregion 超过可视区
    placed_for_scroll = 0
    while placed_for_scroll < 14 and not eng.game_over:
        if not eng.current_player().is_ai:
            if eng.phase == "place":
                if not eng.legal_placements():
                    eng.discard_and_redraw()
                    continue
                x, y, rot = eng.legal_placements()[0]
                app.rot = rot
                app.refresh()
                app.update()
                px, py = cell_center_px(app, x, y)
                click(app, px, py)
                placed_for_scroll += 1
            elif eng.phase == "deploy":
                eng.skip_deploy()
        else:
            app._ai_step()
    if eng.phase == "deploy":          # 收尾：第 14 次放置可能停在部署阶段
        eng.skip_deploy()
        app.refresh()
        app.update()
    app.canvas.xview_moveto(0.4)
    app.canvas.yview_moveto(0.3)
    app.update_idletasks()
    off_x = app.canvas.canvasx(0)
    off_y = app.canvas.canvasy(0)
    for (x, y) in [(0, 0), (1, 0), (0, -1), (-1, 0), (2, 1), (-2, -1)]:
        px, py = cell_center_px(app, x, y)          # 画布坐标
        wx, wy = px - off_x, py - off_y             # 控件坐标
        got = app.cell_at(wx, wy)
        check(got == (x, y), "滚动后 cell_at 往返一致 (%d,%d)->%s" % (x, y, got))
    # 滚动后悬停（Motion 事件）也应指向正确格
    wx, wy = cell_center_px(app, 1, 0)[0] - off_x, cell_center_px(app, 1, 0)[1] - off_y
    app.canvas.event_generate("<Motion>", x=int(wx), y=int(wy))
    app.update()
    check(app.hover_cell == (1, 0), "滚动后悬停格正确: %s" % (app.hover_cell,))

    # --- 2.6) 回归：refresh 重绘后滚动位置必须保持（防"拉回中心"）
    fx0, fy0 = app.canvas.xview()[0], app.canvas.yview()[0]
    app.refresh()
    app.update_idletasks()
    fx1, fy1 = app.canvas.xview()[0], app.canvas.yview()[0]
    check(abs(fx1 - fx0) < 0.01 and abs(fy1 - fy0) < 0.01,
          "refresh 后滚动位置保持 (%.3f,%.3f)->(%.3f,%.3f)" % (fx0, fy0, fx1, fy1))
    # 恢复滚动，继续完整对局
    app.canvas.xview_moveto(0)
    app.canvas.yview_moveto(0)
    app.update_idletasks()

    # --- 3) 完整对局：人类用真实点击流打完
    human_clicks = 0
    anchor_clicks = 0
    skips = 0
    guard = 0
    while not eng.game_over and guard < 6000:
        guard += 1
        p = eng.current_player()
        if not p.is_ai:
            if eng.phase == "place":
                tries = 0
                while not eng.legal_placements():
                    state = app.btn_discard["state"]
                    check(state == "normal", "无处置牌时弃牌按钮可用")
                    app.discard(confirm=False)
                    tries += 1
                    if tries > 20 or eng.game_over:
                        break
                if eng.game_over:
                    break
                x, y, rot = eng.legal_placements()[0]
                app.rot = rot
                app.refresh()
                app.update()
                px, py = cell_center_px(app, x, y)
                click(app, px, py)
                human_clicks += 1
                check(eng.phase == "deploy", "点击合法格后进入部署阶段")
            elif eng.phase == "deploy":
                opts = eng.deploy_options()
                if opts and human_clicks % 3 != 0:   # 2/3 概率部署
                    o = opts[0]
                    # 部署面板按钮点击路径
                    app._draw_deploy_panel()
                    app.update()
                    btns = app.deploy_box.winfo_children()
                    if btns:
                        btns[0].invoke()
                        anchor_clicks += 1
                    else:
                        app.skip_deploy()
                        skips += 1
                else:
                    app.skip_deploy()
                    skips += 1
                app.update()
        else:
            if eng.phase == "place":
                app._ai_step()
            elif eng.phase == "deploy":
                app._ai_step()
            app.update()

    check(eng.game_over, "对局在限定步数内结束")
    scores = [p.score for p in eng.players]
    print("  人类点击放置 %d 次，部署按钮 %d 次，跳过 %d 次" %
          (human_clicks, anchor_clicks, skips))

    # --- 4) 终局
    app._finish()
    app.update()
    check(sum(p.meeples_left for p in eng.players) == 14, "终局米宝全部归还")
    check(any(s > 0 for s in scores), "对局有得分产生")

    app.destroy()


if __name__ == "__main__":
    try:
        run()
        if FAILS:
            print("交互验证失败 %d 项" % len(FAILS))
            sys.exit(1)
        print("INTERACT VERIFY OK")
    except Exception:
        traceback.print_exc()
        print("INTERACT VERIFY FAIL")
        sys.exit(1)
