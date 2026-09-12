# -*- coding: utf-8 -*-
"""AI 验证与胜率基准。

用法：
  python verify_ai.py            # 快速验证（5 组对战）
  python verify_ai.py --bench 20 # 基准：每组 20 局统计胜率（调优用）

断言：全部决策合法、对局收敛、米宝归还；基准模式下输出胜率梯度。
"""
from __future__ import annotations

import sys
import time

from game.bot_ai import BotAI
from game.engine import CarcassonneEngine


def ai_game(level_a: str, level_b: str, seed: int,
            expansions: Optional[list] = None) -> dict:
    eng = CarcassonneEngine([
        {"name": "AI-%s" % level_a, "is_ai": True, "ai_level": level_a},
        {"name": "AI-%s" % level_b, "is_ai": True, "ai_level": level_b},
    ], seed=seed, expansions=expansions)
    bots = {0: BotAI(level_a, seed=seed), 1: BotAI(level_b, seed=seed + 1)}

    turns = 0
    while not eng.game_over:
        turns += 1
        assert turns < 5000, "对局未收敛"
        idx = eng.turn_idx
        bot = bots[idx]

        tries = 0
        while not eng.legal_placements():
            eng.discard_and_redraw()
            tries += 1
            assert tries <= 20
            if eng.game_over:
                break
        if eng.game_over:
            break

        (x, y, rot), _hint = bot.choose_move(eng)
        assert (x, y, rot) in eng.legal_placements(), "AI 非法放置"
        eng.place(x, y, rot)
        if eng.phase != "deploy":
            continue

        opt = bot.choose_deploy(eng)
        if opt is not None:
            legal = {(o["kind"], o["seg"], bool(o.get("big")))
                     for o in eng.deploy_options()}
            assert (opt["kind"], opt["seg"], bool(opt.get("big"))) in legal, "AI 非法部署"
            eng.deploy(opt["kind"], opt["seg"], big=bool(opt.get("big")))
        else:
            eng.skip_deploy()

    evs = eng.final_scoring()
    assert sum(p.meeples_left for p in eng.players) == 14, "米宝未归还"
    sa, sb = eng.players[0].score, eng.players[1].score
    return {
        "levels": (level_a, level_b),
        "turns": turns,
        "scores": [sa, sb],
        "winner": 0 if sa > sb else (1 if sb > sa else -1),  # -1 = 平局
    }


MATCHUPS = [("easy", "easy"), ("normal", "easy"), ("normal", "normal"),
            ("hard", "normal"), ("hard", "easy"), ("hard", "hard")]


def quick() -> bool:
    """快速验证：5 组对战各 1 局，确认合法性与收敛。"""
    exp = ([["inns"] if "--inns" in sys.argv else []] +
           [["traders"] if "--traders" in sys.argv else []])[0] or None
    for lv_a, lv_b in MATCHUPS[:5]:
        t0 = time.time()
        r = ai_game(lv_a, lv_b, seed=42, expansions=exp)
        print("[AI %s vs %s] 回合=%d 得分=%s 胜者=座位%d 用时=%.1fs" %
              (lv_a, lv_b, r["turns"], r["scores"], r["winner"], time.time() - t0))
    print("AI VERIFY OK")
    return True


def bench(games: int) -> bool:
    """胜率基准：每组对战 N 局（不同种子），统计胜率与平均分差。"""
    gradient_ok = True
    for lv_a, lv_b in MATCHUPS:
        wins = [0, 0]
        draws = 0
        diff_sum = 0
        t0 = time.time()
        exp = ([["inns"] if "--inns" in sys.argv else []] +
               [["traders"] if "--traders" in sys.argv else []])[0] or None
        for g in range(games):
            r = ai_game(lv_a, lv_b, seed=1000 + g, expansions=exp)
            if r["winner"] < 0:
                draws += 1
            else:
                wins[r["winner"]] += 1
            diff_sum += r["scores"][0] - r["scores"][1]
        n = games
        print("[%s vs %s] %d局  胜率 %.0f%%:%.0f%%  平 %d  平均分差 %+.1f  (%.0fs)" %
              (lv_a, lv_b, n, 100 * wins[0] / n, 100 * wins[1] / n,
               draws, diff_sum / n, time.time() - t0))
        # 梯度断言：高档位应稳定强于低档位（65%，M11 前瞻达标）
        if lv_a != lv_b:
            idx_a = {"easy": 0, "normal": 1, "hard": 2}[lv_a]
            idx_b = {"easy": 0, "normal": 1, "hard": 2}[lv_b]
            if idx_a > idx_b and wins[0] / n < 0.65:
                gradient_ok = False
                print("  ⚠ 梯度不达标：%s 对 %s 胜率仅 %.0f%%" %
                      (lv_a, lv_b, 100 * wins[0] / n))
    print("BENCH %s（梯度 %s）" % ("OK" if gradient_ok else "FAIL",
                                  "稳定" if gradient_ok else "需调优"))
    return gradient_ok


if __name__ == "__main__":
    if "--bench" in sys.argv:
        i = sys.argv.index("--bench")
        n = int(sys.argv[i + 1]) if len(sys.argv) > i + 1 else 20
        ok = bench(n)
    else:
        ok = quick()
    sys.exit(0 if ok else 1)
