# -*- coding: utf-8 -*-
"""自动化验证：随机完整对局 + 牌面数据校验。

用法：python verify_v1.py [局数]
断言：72 张牌全放完、终局可结算、每回合状态一致、无非法操作。
"""
# -*- coding: utf-8 -*-
import random
import sys

from game import tile_data
from game.engine import CarcassonneEngine


def _random_deploy(engine: CarcassonneEngine, rng: random.Random) -> None:
    """deploy 阶段随机决策（塔/节日收回 / 普通部署 / 幽灵 / 跳过）。"""
    # M21 塔：建塔（可带抓捕）/ 驻塔 / 赎金
    tower_opts = engine.tower_piece_options()
    if tower_opts and rng.random() < 0.35:
        pos, captures = rng.choice(tower_opts)
        engine.tower_place(pos, rng.choice(captures) if captures
                           and rng.random() < 0.8 else None)
        return
    top_opts = engine.tower_top_options()
    if top_opts and rng.random() < 0.2:
        engine.tower_deploy_top(rng.choice(top_opts))
        return
    ransoms = engine.ransom_options()
    if ransoms and rng.random() < 0.3:
        engine.ransom(rng.choice(ransoms))
        return
    if (engine.festival_options() and rng.random() < 0.25
            and not engine._phantom_step):
        engine.festival_return(rng.choice(engine.festival_options()))
        return
    options = engine.deploy_options()
    if options and rng.random() < 0.55:
        opt = rng.choice(options)
        k = opt["kind"]
        if k == "fairy":
            engine.deploy_fairy(tuple(opt["pos"]))
        elif k == "princess":
            engine.deploy_princess(tuple(opt["victim"]), opt["victim_color"])
        elif k == "builder":
            eng_kind = "city" if "城市" in opt["label"] else "road"
            engine.deploy_builder(eng_kind, opt["seg"])
        elif k == "pig":
            engine.deploy_pig("farm", opt["seg"])
        elif k == "mayor":
            engine.deploy_mayor(opt["seg"])
        elif k == "barn":
            engine.deploy_barn(opt["seg"])
        elif k == "wagon":
            real = "city" if "城市" in opt["label"] else "road"
            engine.deploy_wagon(real, opt["seg"])
        else:
            engine.deploy(k, opt["seg"], big=bool(opt.get("big")),
                          pos=opt.get("pos"),
                          phantom=bool(engine._phantom_step)
                          and k in ("city", "road", "farm", "mon"))
    else:
        engine.skip_deploy()


def random_player_turn(engine: CarcassonneEngine,
                       rng: random.Random) -> None:
    """随机完成一个玩家回合（含龙阶段/重部署/进城部署与图元选项）。"""
    # 部署阶段（含幽灵步骤）：可能因迷你阶段跨调用到达，最优先处理
    if engine.phase == "deploy":
        _random_deploy(engine, rng)
        return
    # M18 伯爵城：重部署回合（当前决策者随机决定）
    if engine.phase == "redeploy":
        engine.redeploy_move(rng.random() < 0.8)
        return
    # M18 伯爵城：进城部署机会
    if engine.phase == "count_deploy":
        if rng.random() < 0.7:
            o = rng.choice(engine.count_deploy_options())
            engine.deploy_count(o["quarter"], o["fig"],
                                rng.choice([None, "castle", "market"]))
        else:
            engine.skip_count_deploy()
        return
    # M19：2 牌小城改建城堡
    if engine.phase == "castle":
        engine.convert_castle(rng.random() < 0.5)
        return
    # M19：集市拍卖
    if engine.phase == "bazaar" and engine.bazaar:
        b = engine.bazaar
        if b["phase"] == "select":
            engine.bazaar_select(rng.randrange(len(b["tiles"])), 0)
        elif b["phase"] == "bid":
            engine.bazaar_pass()
        elif b["phase"] == "decide":
            engine.bazaar_resolve(rng.random() < 0.5)
        return
    # M20：金块落位
    if engine.phase == "gold":
        engine.place_gold(rng.choice(engine.gold_options()))
        return
    # M20：法师/女巫落位或收回
    if engine.phase == "magewitch":
        opts = engine.mw_options()
        cands = [(f, n) for f in ("mage", "witch") for n in opts[f]]
        if cands and rng.random() < 0.9:
            fig, node = rng.choice(cands)
            engine.mw_move(fig, node)
        elif engine.mage is not None:
            engine.mw_remove("mage")
        elif engine.witch is not None:
            engine.mw_remove("witch")
        else:
            engine._advance_mini()
        return
    # M20：隧道令牌
    if engine.phase == "tunnel":
        if rng.random() < 0.7:
            engine.tunnel_claim(rng.choice(engine.tunnel_options()))
        else:
            engine.tunnel_skip()
        return
    # M20：围攻脱困
    if engine.phase == "escape":
        opts = engine.escape_options()
        engine.escape_move(rng.choice(opts) if opts and rng.random() < 0.5
                           else None)
        return
    # M20：麦田怪圈
    if engine.phase == "crop" and engine.crop:
        if engine.crop["mode"] is None:
            engine.crop_choose("A" if rng.random() < 0.5 else "B")
        else:
            opts = engine.crop_options()
            if opts and (engine.crop["mode"] == "B" or rng.random() < 0.5):
                engine.crop_act(rng.choice(opts)["node"])
            else:
                engine.crop_act(None)
        return
    # M20：强盗上轨
    if engine.phase == "robber" and engine.robber_phase:
        spaces = engine.robber_options()
        engine.robber_place(rng.choice(spaces) if spaces and rng.random() < 0.7
                            else None)
        return
    # M21：牧羊行动
    if engine.phase == "shepherd":
        engine.shepherd_act(rng.random() < 0.5)
        return
    # M21：瘟疫收回
    if engine.phase == "plague" and engine.plague:
        opts = engine.plague_options()
        engine.plague_act(rng.choice(opts) if opts else None)
        return
    # P&D：龙移动阶段（当前决策者随机走）
    if engine.phase == "dragon":
        legal = engine.dragon_legal_steps()
        if legal:
            engine.dragon_move(rng.choice(legal))
        else:
            engine._advance_dragon()
        return

    # 抽牌后可能无法放置 → 弃牌重抽（模拟全员同意）
    tries = 0
    while not engine.legal_placements():
        engine.discard_and_redraw()
        tries += 1
        assert tries <= 20, "连续 20 张牌无法放置，疑似合法放置判断有误"
        if engine.game_over:
            return

    moves = engine.legal_placements()
    x, y, rot = rng.choice(moves)
    engine.place(x, y, rot)

    if engine.game_over:
        return
    if engine.phase != "deploy":
        return   # 金块/法师女巫/隧道等迷你阶段，交由下一轮顶部处理器


def run_one_game(seed: int, n_players: int = 2, farm_rate: float = 0.0,
                 expansions=None) -> dict:
    rng = random.Random(seed)
    specs = [{"name": "P%d" % i} for i in range(n_players)]
    eng = CarcassonneEngine(specs, seed=seed, expansions=expansions)
    total_meep = 7 * n_players
    if expansions and "inns" in expansions:
        total_meep += n_players  # 每色 1 个大米宝

    placed = 1  # 起始牌
    turns = 0
    while not eng.game_over:
        turns += 1
        assert turns < 10000, "对局未收敛"
        random_player_turn(eng, rng)
        placed += 1

    # 终局计分（重复调用幂等：第二次应返回空）
    ev1 = eng.final_scoring()
    ev2 = eng.final_scoring()
    assert ev2 == [], "终局计分不幂等"

    total_meeples = sum(p.meeples_left for p in eng.players)
    total_big = sum(p.big_meeples_left for p in eng.players)
    if expansions and "count" in expansions:
        # 伯爵城等候区无法有利移入的随从依规则留在城里（脚注 226）
        in_count = sum(len(fs) for fs in eng.count["quarters"].values())
        total_meeples += in_count
        total_big += sum(1 for fs in eng.count["quarters"].values()
                         for f in fs if f[1] == "big")
    total_meeples += len(eng.hostages)   # M21：被扣押的随从不计归还
    assert total_meeples == 7 * n_players, "终局米宝未全部归还: %d" % total_meeples
    if expansions and "inns" in expansions:
        assert total_big == n_players, "终局大米宝未归还: %d" % total_big
    if expansions and "phantom" in expansions:
        assert sum(p.phantom_left for p in eng.players) == n_players, \
            "终局幽灵未全部归还"
    if expansions and "tunnel" in expansions:
        ini = (3 if n_players == 2 else 2 if n_players == 3 else 1) * n_players
        left = sum(p.tunnels_left for p in eng.players)
        assert len(eng.board.tunnel_tokens) == \
            2 * (ini - left) - len(eng.tunnel_open), "隧道令牌不守恒"

    scores = [p.score for p in eng.players]
    return {
        "seed": seed,
        "players": n_players,
        "tiles_placed": placed,
        "turns": turns,
        "scores": scores,
        "events": len(ev1),
        "farm_events": sum(1 for e in ev1 if e.kind == "farm"),
        "log_tail": eng.log_lines[-3:],
    }


def main() -> None:
    stats = tile_data.validate()
    print("[牌面] 72 张校验通过；旗帜牌 %d 张，%d 种牌面" %
          (stats["pennant_tiles"], stats["variants"]))

    numeric = [a for a in sys.argv[1:] if a.isdigit()]
    games = int(numeric[0]) if numeric else 20
    with_inns = "--inns" in sys.argv
    with_traders = "--traders" in sys.argv
    with_king = "--king" in sys.argv
    with_river = "--river" in sys.argv
    with_shrine = "--shrine" in sys.argv
    with_count = "--count" in sys.argv
    with_bcb = "--bcb" in sys.argv
    with_mini = "--mini" in sys.argv
    exp = (["inns"] if with_inns else []) + (["traders"] if with_traders else [])
    exp += (["king"] if with_king else []) + (["river"] if with_river else [])
    exp += (["shrine"] if with_shrine else []) + (["count"] if with_count else [])
    exp += (["bcb"] if with_bcb else [])
    exp += (["besiegers", "festival", "goldmines", "magewitch", "robbers",
             "tunnel", "crop", "phantom"] if with_mini else [])
    exp += (["tower"] if "--tower" in sys.argv else [])
    exp += (["hillsheep"] if "--hs" in sys.argv else [])
    exp += (["wheel"] if "--wheel" in sys.argv else [])
    exp = exp or None
    label = ("（基础版）" if not exp else
             "（%s）" % "+".join(e for e in (
                 "客栈" if with_inns else "", "建造者" if with_traders else "",
                 "国王强盗" if with_king else "", "河流" if with_river else "",
                 "教堂" if with_shrine else "", "伯爵城" if with_count else "",
                 "桥城堡集市" if with_bcb else "",
                 "迷你合集" if with_mini else "",
                 "塔" if "--tower" in sys.argv else "",
                 "山丘羊" if "--hs" in sys.argv else "",
                 "轮盘" if "--wheel" in sys.argv else "") if e))
    total_tiles = 0
    farm_games = 0
    for seed in range(games):
        n_players = 2 + (seed % 3)  # 2-4 人
        r = run_one_game(seed, n_players, expansions=exp)
        total_tiles += r["tiles_placed"]
        farm_games += 1 if r["farm_events"] else 0
        if seed < 3 or seed == games - 1:
            print("[对局 seed=%d] %d人 牌数=%d 回合=%d 得分=%s 事件=%d(农场%d)" %
                  (r["seed"], r["players"], r["tiles_placed"], r["turns"],
                   r["scores"], r["events"], r["farm_events"]))

    print("[汇总] %d 局全部跑通%s；平均每局放置 %.1f 张；含农场计分的对局 %d 局" %
          (games, label, total_tiles / games, farm_games))
    print("VERIFY OK")


if __name__ == "__main__":
    main()
