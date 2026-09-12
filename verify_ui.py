# -*- coding: utf-8 -*-
"""UI 验证：无人工干预下驱动界面完成整局（人机混合），断言控件存在、
状态刷新正常、终局弹窗可达、窗口销毁无异常。

Tkinter 需要显示环境；Windows 桌面会话直接可用。
"""
from __future__ import annotations

import sys
import traceback

import tkinter as tk

from game.ui import App


def run() -> bool:
    specs = [
        {"name": "人类"},
        {"name": "AI-普", "is_ai": True, "ai_level": "normal"},
        {"name": "AI-难", "is_ai": True, "ai_level": "hard"},
    ]
    app = App(specs, seed=3)
    app.update_idletasks()
    app.update()
    app.after = lambda ms, fn, *a, **k: None  # 测试禁用定时调度，避免幽灵推进

    # 控件存在性
    assert app.btn_rot.winfo_exists(), "旋转按钮缺失"
    assert app.btn_skip.winfo_exists(), "跳过按钮缺失"
    assert app.btn_discard.winfo_exists(), "弃牌按钮缺失"

    steps = 0
    try:
        while not app.engine.game_over and steps < 4000:
            steps += 1
            eng = app.engine
            p = eng.current_player()
            if not p.is_ai:
                if eng.phase == "place":
                    tries = 0
                    while not eng.legal_placements():
                        eng.discard_and_redraw()
                        tries += 1
                        assert tries <= 20
                        if eng.game_over:
                            break
                    if eng.game_over:
                        continue
                    x, y, rot = eng.legal_placements()[0]
                    app.rot = rot
                    eng.place(x, y, rot)
                    app.refresh()
                elif eng.phase == "deploy":
                    # 模拟点击跳过按钮
                    app.skip_deploy()
            else:
                # AI 回合：同步驱动（绕过 after 延时，验证逻辑而非定时）
                if eng.phase in ("place", "deploy"):
                    app._ai_step()
                    app._ai_step()   # place → deploy 两段各推进一步
            # 泵事件循环：驱动 AI 的 after 回调
            app.update_idletasks()
            app.update()

        assert app.engine.game_over, "对局未在步数内结束"
        app._finish()   # 终局弹窗路径
        app.update()
        # 布局不塌：棋盘可见
        assert app.canvas.winfo_ismapped(), "棋盘未映射"
        assert app.preview.winfo_ismapped(), "预览未映射"
        # 计分板绘制过玩家标记
        app.update_idletasks()
        scores = [p.score for p in app.engine.players]
        assert any(s > 0 for s in scores), "三人对局得分为 0，可疑"
        print("[UI] 对局完成：%s 得分=%s 步数=%d" %
              (app.engine.winner_text(), scores, steps))
    finally:
        app.destroy()
    return True


if __name__ == "__main__":
    try:
        ok = run()
        print("UI VERIFY %s" % ("OK" if ok else "FAIL"))
        sys.exit(0 if ok else 1)
    except Exception:
        traceback.print_exc()
        print("UI VERIFY FAIL")
        sys.exit(1)
