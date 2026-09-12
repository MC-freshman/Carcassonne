# -*- coding: utf-8 -*-
"""卡卡颂桌面端启动器：python game/main.py 或双击运行。

模式：单机热座 / 人机对战 / 局域网联机（建房 / 加入）。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _quick() -> None:
    from game.ui import App
    specs = [{"name": "玩家1"},
             {"name": "AI", "is_ai": True, "ai_level": "normal"}]
    app = App(specs, seed=1)
    app.mainloop()


def _demo() -> None:
    from game.ui import App
    specs = [{"name": "AI-红", "is_ai": True, "ai_level": "normal"},
             {"name": "AI-蓝", "is_ai": True, "ai_level": "hard"}]
    exp = []
    if "--demo-inns" in sys.argv:
        exp.append("inns")
    if "--demo-traders" in sys.argv:
        exp.append("traders")
    app = App(specs, seed=5, expansions=exp)
    app.mainloop()


def main() -> None:
    if "--quick" in sys.argv:
        _quick()
        return
    if "--demo" in sys.argv or "--demo-inns" in sys.argv             or "--demo-traders" in sys.argv:
        _demo()
        return

    from game.ui import setup_dialog, mode_dialog
    mode = mode_dialog()
    if mode is None:
        return

    if mode["kind"] == "local":
        specs, expansions = setup_dialog()
        if not specs:
            return
        from game.ui import App
        App(specs, expansions=expansions).mainloop()
        return

    from game.net.client import NetClient
    from game.net.server import GameServer
    from game.ui import App, get_lan_ip

    if mode["kind"] == "host":
        srv = GameServer(total_players=mode["seats"], host_name=mode["name"],
                         ai_specs=[{"ai_level": "normal"}] * mode["ai_count"],
                         expansions=mode.get("expansions") or [])
        client = NetClient()
        err = client.connect("127.0.0.1", srv.port, mode["name"])
        if err:
            srv.close()
            from tkinter import messagebox
            import tkinter as tk
            root = tk.Tk(); root.withdraw()
            messagebox.showerror("建房失败", err)
            root.destroy()
            return
        info = " %s:%d" % (get_lan_ip(), srv.port)
        app = App(net=client, server=srv, net_info=info)
        app.protocol("WM_DELETE_WINDOW", lambda: (client.close(), srv.close(),
                                                  app.destroy()))
        app.mainloop()
        return

    # join
    client = NetClient()
    err = client.connect(mode["ip"], mode["port"], mode["name"])
    if err:
        from tkinter import messagebox
        import tkinter as tk
        root = tk.Tk(); root.withdraw()
        messagebox.showerror("加入失败", err)
        root.destroy()
        return
    app = App(net=client)
    app.protocol("WM_DELETE_WINDOW", lambda: (client.close(), app.destroy()))
    app.mainloop()


if __name__ == "__main__":
    main()
