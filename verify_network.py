# -*- coding: utf-8 -*-
"""联机验证：
1. 双人类客户端经真实协议完成整局（含回合校验、非法操作拒收）
2. 断线后服务器代打推进、同名重连恢复
3. 1 人 + 1 AI 组合局
"""
from __future__ import annotations

import queue
import random
import sys
import time

from game.engine import CarcassonneEngine
from game.net.client import NetClient
from game.net.server import GameServer

FAILS = []


def check(cond, msg):
    print("  [%s] %s" % ("ok" if cond else "FAIL", msg))
    if not cond:
        FAILS.append(msg)


def next_snap(client: NetClient, timeout: float = 10.0):
    """取下一条 snap/over 消息（跳过 lobby 等）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            m = client.msgs.get(timeout=0.2)
        except queue.Empty:
            continue
        if m.get("t") in ("snap", "over"):
            return m
        if m.get("t") == "error":
            return m
    return None


def drain(client: NetClient) -> None:
    while True:
        try:
            client.msgs.get_nowait()
        except queue.Empty:
            return


def play_full_game(server: GameServer, clients, label: str,
                   drop_client: NetClient = None,
                   reconnect_at_turns: int = 25, stats: dict = None,
                   final_snaps: dict = None):
    """驱动客户端按快照轮流行动直到终局（含扩展的龙阶段/特殊部署）。

    final_snaps：可选出参 dict，记录每个客户端收到的最后一份终局快照
    （玩家数组），用于跨客户端终局一致性比对——不依赖 over 消息是否
    已被本循环消费（那会造成校验竞态）。
    """
    snaps = {id(c): 1 for c in clients}   # 初始 snap
    over = None
    guard = 0
    turn_counter = 0
    rng = random.Random(7)
    while over is None and guard < 9000:
        guard += 1
        acted = False
        for c in clients:
            if over is not None:
                break
            m = None
            while True:   # 取该客户端最新 snap
                try:
                    got = c.msgs.get_nowait()
                except queue.Empty:
                    break
                if got.get("t") in ("snap", "over"):
                    m = got
                    if final_snaps is not None and got.get("snap") is not None:
                        final_snaps[id(c)] = got["snap"]
                if got.get("t") == "over":
                    over = got
            if m is None or over is not None:
                continue
            if m["t"] == "over":
                over = m
                break
            snap = m["snap"]
            last = {"phase": snap.get("phase"), "turn": snap.get("turn_idx"),
                    "you": c.you}
            if snap["game_over"]:
                over = m
                break
            # P&D：龙移动阶段——由轮值决定者发 drag（先于回合归属判断）
            if snap.get("phase") == "dragon":
                if stats is not None:
                    stats["dragon_snaps"] = stats.get("dragon_snaps", 0) + 1
                rep = CarcassonneEngine.from_dict(snap)
                dec = rep.dragon_decider_player()
                if dec is not None and dec.idx == c.you:
                    steps = sorted(rep.dragon_legal_steps())
                    if steps:
                        pos = rng.choice(steps)
                        c.send_drag(pos[0], pos[1])
                        acted = True
                continue
            # M18 伯爵城：重部署回合（当前决策者决定）
            if snap.get("phase") == "redeploy":
                rep = CarcassonneEngine.from_dict(snap)
                st = rep.redeploy_state()
                if st is not None and st["player"] == c.you:
                    c.send_redeploy(rng.random() < 0.8)
                    acted = True
                continue
            # M18 伯爵城：进城部署（放置者决定）
            if snap.get("phase") == "count_deploy":
                rep = CarcassonneEngine.from_dict(snap)
                if c.you == rep._placer_idx:
                    if rng.random() < 0.7:
                        o = rng.choice(rep.count_deploy_options())
                        c.send_count_deploy(o["quarter"], o["fig"], None)
                    else:
                        c.send_count_skip()
                    acted = True
                continue
            # M19：城堡改建
            if snap.get("phase") == "castle":
                rep = CarcassonneEngine.from_dict(snap)
                if rep._castle_queue:
                    meta = rep.board._meta[rep._castle_queue[0]]
                    from game.models import meeple_majority
                    winners, _t = (rep._city_majority(meta) if meta.mayors
                                   else meeple_majority(meta.meeples))
                    occ = rep._player_by_color(
                        winners[0] if winners else rep.current_player().color)
                    if occ.idx == c.you:
                        c.send_castle(rng.random() < 0.5)
                        acted = True
                continue
            # M19：集市拍卖
            if snap.get("phase") == "bazaar":
                rep = CarcassonneEngine.from_dict(snap)
                b = rep.bazaar
                if b:
                    if b["phase"] == "select" and c.you == b["selector"]:
                        c.send_bazaar("select", idx=0, bid=0)
                        acted = True
                    elif b["phase"] == "bid" and c.you == b.get("bid_turn"):
                        c.send_bazaar("pass")
                        acted = True
                    elif b["phase"] == "decide" and c.you == b["selector"]:
                        c.send_bazaar("resolve", keep=False)
                        acted = True
                continue
            # M20：迷你扩展阶段（决策者与消息驱动）
            ph = snap.get("phase")
            if ph in ("gold", "magewitch", "tunnel", "escape", "crop",
                      "robber"):
                if stats is not None:
                    stats["mini_phases"] = stats.get("mini_phases", 0) + 1
                rep = CarcassonneEngine.from_dict(snap)
                if ph == "gold" and c.you == rep.turn_idx:
                    c.send_gold(rng.choice(rep.gold_options()))
                    acted = True
                elif ph == "magewitch" and c.you == rep.turn_idx:
                    opts = rep.mw_options()
                    cands = [(f, n) for f in ("mage", "witch") for n in opts[f]]
                    if cands:
                        fig, node = rng.choice(cands)
                        c.send_mw(fig, node)
                    elif rep.mage is not None:
                        c.send_mw("mage", None)
                    elif rep.witch is not None:
                        c.send_mw("witch", None)
                elif ph == "tunnel" and c.you == rep.turn_idx:
                    if rep.tunnel_options() and rng.random() < 0.7:
                        c.send_tunnel(rng.choice(rep.tunnel_options()))
                    else:
                        c.send_tunnel(skip=True)
                elif ph == "escape" and c.you == rep.turn_idx:
                    o = rep.escape_options()
                    c.send_escape(rng.choice(o) if o and rng.random() < 0.5
                                  else None)
                elif ph == "crop" and rep.crop:
                    if rep.crop["mode"] is None:
                        if c.you == rep._placer_idx:
                            c.send_crop(mode=rng.choice(["A", "B"]))
                    elif c.you == rep.crop["order"][rep.crop["pos"]]:
                        o = rep.crop_options()
                        if o and (rep.crop["mode"] == "B"
                                  or rng.random() < 0.5):
                            c.send_crop(node=rng.choice(o)["node"])
                        else:
                            c.send_crop()
                elif ph == "robber" and rep.robber_phase:
                    if c.you == rep.robber_phase["order"][rep.robber_phase["pos"]]:
                        sp = rep.robber_options()
                        c.send_robber(rng.choice(sp) if sp
                                      and rng.random() < 0.7 else None)
                continue
            # M21 山丘与羊：牧羊行动
            if snap.get("phase") == "shepherd":
                if rng.random() < 0.5:
                    c.send_shepherd(True)
                else:
                    c.send_shepherd(False)
                acted = True
                continue
            # M21 命运之轮：瘟疫收回（决策者=当前玩家起顺时针，非回合门）
            if snap.get("phase") == "plague":
                rep = CarcassonneEngine.from_dict(snap)
                if c.you == rep.plague["order"][int(rep.plague["pos"])]:
                    opts = rep.plague_options()
                    c.send_plague(rng.choice(opts) if opts else None)
                    acted = True
                continue
            if snap["turn_idx"] != c.you or snap["phase"] == "over":
                continue
            # 轮到本客户端：执行动作
            turn_counter += 1
            # M21 塔：部署阶段可建塔/驻塔/赎金
            if snap.get("phase") == "deploy":
                rep = CarcassonneEngine.from_dict(snap)
                # 牧羊人部署（代替随从）
                if rng.random() < 0.15:
                    sh_opts = [o for o in rep.deploy_options()
                               if o["kind"] == "shepherd"]
                    if sh_opts:
                        o = rng.choice(sh_opts)
                        c.send_deploy("shepherd", o["seg"])
                        acted = True
                        continue
                # 王冠位上架
                if rng.random() < 0.15:
                    cr_opts = [o for o in rep.deploy_options()
                               if o["kind"] == "crown"]
                    if cr_opts:
                        o = rng.choice(cr_opts)
                        c.send_deploy("crown", o["seg"])
                        acted = True
                        continue
                # 牧羊人部署（代替随从）
                if rng.random() < 0.25:
                    sh_opts = [o for o in rep.deploy_options()
                               if o["kind"] == "shepherd"]
                    if sh_opts:
                        o = rng.choice(sh_opts)
                        c.send_deploy("shepherd", o["seg"])
                        acted = True
                        continue
                if rng.random() < 0.3:
                    tp = rep.tower_piece_options()
                    if tp:
                        pos, captures = rng.choice(tp)
                        c.send_tower_piece(pos, rng.choice(captures)
                                           if captures and rng.random() < 0.8
                                           else None)
                        acted = True
                        continue
                if rng.random() < 0.1:
                    tops = rep.tower_top_options()
                    if tops:
                        c.send_tower_top(rng.choice(tops))
                        acted = True
                        continue
                if rng.random() < 0.15:
                    rans = rep.ransom_options()
                    if rans:
                        c.send_ransom(rng.choice(rans))
                        acted = True
                        continue
            if drop_client is not None and c is drop_client and \
                    turn_counter >= reconnect_at_turns:
                c.close()          # 模拟掉线：服务器将代打
                drop_client = None
                acted = True
                break
            rep = CarcassonneEngine.from_dict(snap)
            if rep.phase in ("place", "river"):
                if not rep.legal_placements():
                    c.send_discard()
                else:
                    x, y, rot = rng.choice(rep.legal_placements())
                    c.send_place(x, y, rot)
            elif rep.phase == "deploy":
                opts = rep.deploy_options()
                if opts and rng.random() < 0.5:
                    o = rng.choice(opts)
                    if stats is not None and o["kind"] in (
                            "fairy", "princess", "mayor", "barn", "wagon",
                            "builder", "pig"):
                        stats["special_deploys"] = \
                            stats.get("special_deploys", 0) + 1
                    c.send_deploy(o["kind"], o.get("seg", 0),
                                  big=bool(o.get("big")),
                                  pos=o.get("pos"),
                                  victim=o.get("victim"),
                                  victim_color=o.get("victim_color"))
                else:
                    c.send_skip()
            acted = True
        if not acted:
            time.sleep(0.02)
    check(over is not None, "%s：对局在限定步数内完成" % label)
    return over


def main() -> None:
    # ---------- 场景 1：双人类完整对局
    srv = GameServer(total_players=2, host_name="主机", port=0, seed=42)
    print("[场景1] 双人类 @127.0.0.1:%d" % srv.port)
    a, b = NetClient(), NetClient()
    err = a.connect("127.0.0.1", srv.port, "主机")
    check(err == "", "房主加入%s" % (": " + err if err else ""))
    err = b.connect("127.0.0.1", srv.port, "客人")
    check(err == "", "客人加入%s" % (": " + err if err else ""))
    a.send_start()
    fin1: dict = {}
    over = play_full_game(srv, [a, b], "双人类", final_snaps=fin1)
    if over:
        snap = over["snap"]
        scores = [p["score"] for p in snap["players"]]
        check(any(s > 0 for s in scores), "双方得分 %s" % scores)
        # 两个客户端各自收到的终局一致（取 B 队列中实际收到的最后一份）
        fb = fin1.get(id(b))
        while True:
            try:
                got = b.msgs.get_nowait()
            except queue.Empty:
                break
            if got.get("t") in ("snap", "over") and got.get("snap"):
                fb = got["snap"]
        check(fb is not None and fb["players"] == snap["players"],
              "客户端间终局一致")
    # 回合校验：对局已结束，再发动作应被拒
    a.send_place(0, 1, 0)
    m = next_snap(a, timeout=2.0)
    check(m is not None and m.get("t") == "error", "对局结束后操作被拒")
    a.close(); b.close(); srv.close()

    # ---------- 场景 2：断线代打 + 重连
    srv = GameServer(total_players=2, host_name="主机", port=0, seed=100)
    print("[场景2] 断线与重连 @127.0.0.1:%d" % srv.port)
    a, b = NetClient(), NetClient()
    a.connect("127.0.0.1", srv.port, "主机")
    b.connect("127.0.0.1", srv.port, "客人")
    a.send_start()
    over = play_full_game(srv, [a, b], "断线重连", drop_client=b,
                          reconnect_at_turns=20)
    check(over is not None, "一端掉线后对局仍由主机推进完成")
    if over:
        scores = [p["score"] for p in over["snap"]["players"]]
        check(sum(scores) > 0, "断线局仍有得分 %s" % scores)
    a.close(); b.close(); srv.close()

    # ---------- 场景 3：1 人类 + 1 AI
    srv = GameServer(total_players=2, host_name="主机", ai_specs=[{"ai_level": "normal"}],
                     port=0, seed=7)
    print("[场景3] 人+AI @127.0.0.1:%d" % srv.port)
    a = NetClient()
    a.connect("127.0.0.1", srv.port, "主机")
    a.send_start()
    drain(a)
    over = play_full_game(srv, [a], "人+AI")
    if over:
        names = [p["name"] for p in over["snap"]["players"]]
        check(any("AI" in n for n in names), "AI 座位存在 %s" % names)
    a.close(); srv.close()

    # ---------- 场景 4：ping/pong 延迟测量
    srv = GameServer(total_players=2, host_name="主机", port=0, seed=3)
    print("[场景4] ping/pong @127.0.0.1:%d" % srv.port)
    a = NetClient()
    assert a.connect("127.0.0.1", srv.port, "主机") == ""
    import time as _t
    t0 = _t.monotonic()
    a.send_ping(t0)
    rtt = None
    deadline = _t.monotonic() + 3
    while _t.monotonic() < deadline:
        try:
            m = a.msgs.get(timeout=0.1)
        except queue.Empty:
            continue
        if m.get("t") == "pong":
            rtt = (_t.monotonic() - float(m["ts"])) * 1000
            break
    check(rtt is not None and rtt < 500, "ping/pong 往返 %.1fms" % (rtt or -1))
    a.close(); srv.close()

    # ---------- 场景 5：房主踢人（大厅）
    srv = GameServer(total_players=2, host_name="主机", port=0, seed=4)
    print("[场景5] 踢人 @127.0.0.1:%d" % srv.port)
    a, b = NetClient(), NetClient()
    assert a.connect("127.0.0.1", srv.port, "主机") == ""
    assert b.connect("127.0.0.1", srv.port, "客人") == ""
    a.send_kick(1)
    got_kick = False
    deadline = _t.monotonic() + 3
    while _t.monotonic() < deadline:
        try:
            m = b.msgs.get(timeout=0.1)
        except queue.Empty:
            continue
        if m.get("t") == "kicked":
            got_kick = True
            break
    check(got_kick, "被踢客户端收到 kicked")
    # 被踢后座位重置，新客人可再次加入
    c = NetClient()
    err = c.connect("127.0.0.1", srv.port, "客人2")
    check(err == "", "重置后的座位可再加入%s" % (": " + err if err else ""))
    a.close(); b.close(); c.close(); srv.close()

    # ---------- 场景 6：对局中断线 → 同名重连 → 继续完成对局
    srv = GameServer(total_players=2, host_name="主机", port=0, seed=5)
    print("[场景6] 重连恢复 @127.0.0.1:%d" % srv.port)
    a, b = NetClient(), NetClient()
    assert a.connect("127.0.0.1", srv.port, "主机") == ""
    assert b.connect("127.0.0.1", srv.port, "客人") == ""
    a.send_start()
    rng = random.Random(9)
    over = None
    guard = 0
    dropped = False
    rejoined = False
    while over is None and guard < 60000:
        guard += 1
        for c in (a, b):
            try:
                m = c.msgs.get_nowait()
            except queue.Empty:
                continue
            if m.get("t") == "error":
                print("  error:", m.get("msg"))
                continue
            if m.get("t") in ("snap", "over"):
                snap = m["snap"]
                if snap["game_over"]:
                    over = m
                    break
                if snap["turn_idx"] != c.you:
                    continue
                if c is b and not dropped:
                    b.close()            # 掉线
                    dropped = True
                    continue
                if c is b and dropped and not rejoined and not c.alive:
                    err = b.reconnect()  # 同名重连
                    check(err == "", "重连成功%s" % (": " + err if err else ""))
                    rejoined = True
                    continue
                rep = CarcassonneEngine.from_dict(snap)
                if rep.phase == "place":
                    if not rep.legal_placements():
                        c.send_discard()
                    else:
                        x, y, rot = rng.choice(rep.legal_placements())
                        c.send_place(x, y, rot)
                elif rep.phase == "deploy":
                    opts = rep.deploy_options()
                    if opts and rng.random() < 0.5:
                        o = rng.choice(opts)
                        c.send_deploy(o["kind"], o["seg"])
                    else:
                        c.send_skip()
        if not dropped:
            time.sleep(0.005)
        else:
            time.sleep(0.01)
            if not rejoined and not b.alive:
                err = b.reconnect()
                check(err == "", "重连成功%s" % (": " + err if err else ""))
                rejoined = True
    check(over is not None, "断线重连后对局完成")
    check(rejoined, "发生过同名重连")
    if over:
        scores = [p["score"] for p in over["snap"]["players"]]
        check(sum(scores) > 0, "重连局仍有得分 %s" % scores)
    a.close(); b.close(); srv.close()

    # ---------- 场景 7：九扩展同开完整联机对局（快照同步回归）
    srv = GameServer(total_players=2, host_name="主机", port=0, seed=99,
                     expansions=["inns", "traders", "pd", "abbey",
                                 "king", "river", "shrine", "count", "bcb"])
    print("[场景7] 九扩展联机 @127.0.0.1:%d" % srv.port)
    a, b = NetClient(), NetClient()
    err = a.connect("127.0.0.1", srv.port, "主机")
    check(err == "", "房主加入（九扩展）%s" % (": " + err if err else ""))
    err = b.connect("127.0.0.1", srv.port, "客人")
    check(err == "", "客人加入（九扩展）%s" % (": " + err if err else ""))
    a.send_start()
    stats: dict = {}
    fin7: dict = {}
    over = play_full_game(srv, [a, b], "九扩展联机", stats=stats,
                          final_snaps=fin7)
    if over:
        snap = over["snap"]
        scores = [p["score"] for p in snap["players"]]
        check(any(s > 0 for s in scores), "九扩展局得分 %s" % scores)
        fb = fin7.get(id(b))
        while True:
            try:
                got = b.msgs.get_nowait()
            except queue.Empty:
                break
            if got.get("t") in ("snap", "over") and got.get("snap"):
                fb = got["snap"]
        same = fb is not None and fb["players"] == snap["players"]
        if not same and fb is not None:   # 失败时打印分叉点便于定位
            for i, (pa, pb) in enumerate(zip(snap["players"], fb["players"])):
                if pa != pb:
                    print("    [diff] 玩家%d 主机=%s 客人=%s" % (i, pa, pb))
        check(same, "九扩展局客户端间终局一致")
    check(stats.get("dragon_snaps", 0) > 0,
          "龙阶段快照已同步（%d 帧）" % stats.get("dragon_snaps", 0))
    print("  [info] 特殊部署（仙女/公主/市长/粮仓/马车/建造者/猪）次数：%d"
          % stats.get("special_deploys", 0))
    a.close(); b.close(); srv.close()

    # ---------- 场景 8：迷你扩展合集同开联机对局（M20 快照/代打回归） ----------
    srv = GameServer(total_players=2, host_name="主机", port=0, seed=17,
                     expansions=["besiegers", "festival", "goldmines",
                                 "magewitch", "robbers", "tunnel", "crop",
                                 "phantom", "tower", "hillsheep", "wheel"])
    print("[场景8] 迷你合集+塔联机 @127.0.0.1:%d" % srv.port)
    a, b = NetClient(), NetClient()
    err = a.connect("127.0.0.1", srv.port, "主机")
    check(err == "", "房主加入（迷你）%s" % (": " + err if err else ""))
    err = b.connect("127.0.0.1", srv.port, "客人")
    check(err == "", "客人加入（迷你）%s" % (": " + err if err else ""))
    a.send_start()
    stats8: dict = {}
    fin8: dict = {}
    over = play_full_game(srv, [a, b], "迷你合集联机", stats=stats8,
                          final_snaps=fin8)
    if over:
        snap = over["snap"]
        scores = [p["score"] for p in snap["players"]]
        check(any(s > 0 for s in scores), "迷你局得分 %s" % scores)
        fb = fin8.get(id(b))
        while True:
            try:
                got = b.msgs.get_nowait()
            except queue.Empty:
                break
            if got.get("t") in ("snap", "over") and got.get("snap"):
                fb = got["snap"]
        same = fb is not None and fb["players"] == snap["players"]
        check(same, "迷你局客户端间终局一致")
    check(stats8.get("mini_phases", 0) > 0,
          "迷你阶段快照已同步（%d 帧）" % stats8.get("mini_phases", 0))
    a.close(); b.close(); srv.close()

    if FAILS:
        print("NETWORK VERIFY FAIL (%d)" % len(FAILS))
        sys.exit(1)
    print("NETWORK VERIFY OK")


if __name__ == "__main__":
    main()
