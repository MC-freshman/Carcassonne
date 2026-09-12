# -*- coding: utf-8 -*-
"""联机 UI 验证：同进程创建两个真实 App（房主+客人），经本机 TCP 完整对局。

注意：驱动方式为手动轮询 _net_poll()，避免调用 update()——
Tk 的 update() 会持续触发自调度的 after 轮询定时器（处理耗时 ≥ 轮询间隔时
定时器永远到期），导致 update() 永不返回。生产环境 mainloop() 无此问题。
覆盖：大厅等待→房主开始→快照渲染→各自回合操作→终局弹窗→双端一致。
"""
from __future__ import annotations

import random
import sys
import time
import traceback

from game.net.client import NetClient
from game.net.server import GameServer
from game.ui import App

POLL_MS = 10


def pump(app: App, loops: int = 2, ms: float = 1.0) -> None:
    for _ in range(loops):
        app.update_idletasks()
        app._net_poll()
        time.sleep(ms / 1000.0)


def wait_engine(app: App, timeout: float = 8.0):
    t0 = time.time()
    while app.engine is None and time.time() - t0 < timeout:
        pump(app)
    return app.engine is not None


def act(app: App, rng: random.Random) -> None:
    """轮到该 App 时执行一个动作（经网络发送）。"""
    eng = app.engine
    if eng.phase == "place":
        tries = 0
        while not eng.legal_placements():
            app.net.send_discard()
            t0 = time.time()
            while time.time() - t0 < 1.5:
                pump(app)
                if app.engine.phase == "place" and app.engine.legal_placements():
                    break
            tries += 1
            if tries > 10 or app.engine.game_over:
                return
        if app.engine.game_over or app.engine.turn_idx != app.my_seat:
            return
        eng = app.engine
        x, y, rot = rng.choice(eng.legal_placements())
        app.rot = rot
        app.net.send_place(x, y, rot)
    elif eng.phase == "deploy":
        opts = eng.deploy_options()
        if opts and rng.random() < 0.5:
            o = rng.choice(opts)
            app.net.send_deploy(o["kind"], o["seg"])
        else:
            app.net.send_skip()


def run() -> None:
    srv = GameServer(total_players=2, host_name="房主", port=0, seed=77)
    a = NetClient()
    b = NetClient()
    assert a.connect("127.0.0.1", srv.port, "房主") == ""
    assert b.connect("127.0.0.1", srv.port, "客人") == ""

    host_app = App(net=a, server=srv, net_info=" 127.0.0.1:%d" % srv.port,
                   poll_ms=POLL_MS)
    join_app = App(net=b, poll_ms=POLL_MS)
    pump(host_app)
    pump(join_app)
    assert host_app.engine is None and join_app.engine is None, "开局前应为等待状态"

    host_app._net_start()
    assert wait_engine(host_app) and wait_engine(join_app), "未收到开局快照"
    print("  [ok] 双端收到开局快照（%d 座位）" % len(host_app.engine.players))

    rng = random.Random(5)
    t0 = time.time()
    guard = 0
    while not (host_app._net_over and join_app._net_over) and guard < 30000:
        guard += 1
        progressed = False
        for app in (host_app, join_app):
            pump(app, 1)
            eng = app.engine
            if eng is None or eng.game_over or app._net_over:
                continue
            if eng.turn_idx == app.my_seat:
                act(app, rng)
                progressed = True
        if not progressed:
            time.sleep(0.005)
    assert guard < 30000, "对局未收敛"
    pump(host_app, 10)
    pump(join_app, 10)

    sa = [p.score for p in host_app.engine.players]
    sb = [p.score for p in join_app.engine.players]
    assert sa == sb, "双端终局分数不一致: %s vs %s" % (sa, sb)
    assert any(s > 0 for s in sa), "无得分产生"
    assert host_app._net_over and join_app._net_over, "双端未都收到终局"
    print("  [ok] 双端终局一致：%s（用时 %.1fs）" %
          (host_app.engine.winner_text(), time.time() - t0))

    host_app.destroy()
    join_app.destroy()
    srv.close()


if __name__ == "__main__":
    try:
        run()
        print("NETUI VERIFY OK")
    except Exception:
        traceback.print_exc()
        print("NETUI VERIFY FAIL")
        sys.exit(1)
