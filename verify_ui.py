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


def _buttons(widget, pred):
    out = []
    for child in widget.winfo_children():
        if isinstance(child, tk.Button) and pred(child.cget("text")):
            out.append(child)
        out.extend(_buttons(child, pred))
    return out


def _drive_dialog(fn, click_text, prep):
    """构建对话框：mainloop 打桩 → prep → 点击按钮 → 返回 (结果, 诊断)。"""
    diag = {}

    def fake_mainloop(self, *a, **k):
        self.update_idletasks()
        self.update()
        prep(self, diag)
        for btn in _buttons(self, lambda t: t == click_text):
            btn.invoke()
            return
        raise AssertionError("对话框缺少按钮：%s" % click_text)

    orig = tk.Tk.mainloop
    tk.Tk.mainloop = fake_mainloop
    try:
        result = fn()
    finally:
        tk.Tk.mainloop = orig
    return result, diag


def check_dialogs() -> None:
    """对话框：扩展开关默认折叠、展开不超屏、勾选结果正确回传。"""
    from game.ui_dialogs import EXPANSIONS, mode_dialog, setup_dialog

    def prep(dlg, diag):
        panel = getattr(dlg, "_exp_panel", None)
        assert panel is not None, "对话框缺少扩展开关面板"
        assert not panel._body.winfo_ismapped(), "扩展面板应默认折叠"
        diag["collapsed_h"] = dlg.winfo_height()
        panel.toggle()                      # 展开
        dlg.update()
        assert panel._body.winfo_ismapped(), "展开后扩展列表未显示"
        diag["expanded_h"] = dlg.winfo_height()
        diag["screen_h"] = dlg.winfo_screenheight()
        panel.set_all(True)
        assert len(panel.selected()) == len(EXPANSIONS), "全选未生效"
        panel.set_all(False)
        assert not panel.selected(), "清空未生效"
        panel.vars["tower"].set(True)       # 勾选一项
        assert "1 / %d" % len(EXPANSIONS) in panel._btn.cget("text"), \
            "标题未显示已选数：%s" % panel._btn.cget("text")
        panel.toggle()                      # 折叠
        dlg.update()
        assert not panel._body.winfo_ismapped(), "折叠后扩展列表仍显示"
        diag["re_collapsed_h"] = dlg.winfo_height()

    res, diag = _drive_dialog(setup_dialog, "开始游戏", prep)
    specs, exps = res
    assert specs and len(specs) == 2, "单机设置对话框未返回玩家"
    assert exps == ["tower"], "单机设置扩展回传异常：%s" % (exps,)
    assert diag["expanded_h"] <= diag["screen_h"], "单机设置展开后超出屏幕"
    assert diag["re_collapsed_h"] <= diag["collapsed_h"] + 2, \
        "折叠后窗口高度未收回"

    host, diag2 = _drive_dialog(mode_dialog, "创建房间", prep)
    assert host and host.get("kind") == "host", "建房对话框未返回结果"
    assert host.get("expansions") == ["tower"], \
        "建房对话框扩展回传异常：%s" % (host.get("expansions"),)
    assert diag2["expanded_h"] <= diag2["screen_h"], "建房对话框展开后超出屏幕"
    print("[UI] 对话框：扩展面板折叠 %dpx → 展开 %dpx → 折叠 %dpx（屏幕 %dpx）"
          % (diag["collapsed_h"], diag["expanded_h"], diag["re_collapsed_h"],
             diag["screen_h"]))


def run() -> bool:
    check_dialogs()      # 开局/建房对话框（扩展开关折叠）先行，独立 Tk 根

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
        # 布局不塌：棋盘/预览可见（窗口映射偶尔滞后一拍，多泵几次事件）
        for _ in range(20):
            app.update_idletasks()
            app.update()
            if app.canvas.winfo_ismapped() and app.preview.winfo_ismapped():
                break
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
