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
from game import ai_turn


def assert_final_supply(eng):
    # 塔的人质与伯爵城未移入的随从按规则留在原处，仍属于玩家供给总量。
    for p in eng.players:
        held = {"meeples_left": 0, "big_meeples_left": 0, "phantom_left": 0}
        for h in eng.hostages:
            if h["owner"] == p.color:
                key = "phantom_left" if h.get("ph") else "big_meeples_left" if h["size"] == 2 else "meeples_left"
                held[key] += 1
        for figures in eng.count["quarters"].values():
            for color, fig in figures:
                if color == p.color and fig in ("meeple", "big", "phantom"):
                    held[{"meeple": "meeples_left", "big": "big_meeples_left", "phantom": "phantom_left"}[fig]] += 1
        assert p.meeples_left + held["meeples_left"] == 7, "普通随从不守恒：%s" % p.name
        if "inns" in eng.expansions:
            assert p.big_meeples_left + held["big_meeples_left"] == 1, "大型随从不守恒：%s" % p.name
        if "phantom" in eng.expansions:
            assert p.phantom_left + held["phantom_left"] == 1, "幽灵不守恒：%s" % p.name


def ai_game(level_a: str, level_b: str, seed: int,
            expansions=None, players: int = 2) -> dict:
    levels = [level_a if i % 2 == 0 else level_b for i in range(players)]
    eng = CarcassonneEngine([
        {"name": "AI-%d-%s" % (i, lv), "is_ai": True, "ai_level": lv}
        for i, lv in enumerate(levels)
    ], seed=seed, expansions=expansions)
    bots = {i: BotAI(lv, seed=seed+i) for i, lv in enumerate(levels)}
    turns = actions = 0
    maximum_ms = 0
    while not eng.game_over:
        actions += 1
        assert actions < 5000, "对局未收敛：%s" % eng.phase
        player = eng.decision_player()
        assert player is not None, "阶段没有决策者：%s" % eng.phase
        bot = bots[player.idx]
        chosen = ai_turn.choose_action(eng, bot)
        if chosen["op"] == "place":
            turns += 1
            maximum_ms = max(maximum_ms, bot.last_stats.get("elapsed_ms", 0))
        ai_turn.apply_action(eng, chosen)
        for p in eng.players:
            for attr in ("meeples_left", "big_meeples_left", "phantom_left"):
                assert getattr(p, attr) >= 0, "随从供给负数：%s %s" % (p.name, attr)
    eng.final_scoring()
    assert_final_supply(eng)
    scores = [p.score for p in eng.players]
    winner = scores.index(max(scores)) if scores.count(max(scores)) == 1 else -1
    return {"levels": levels, "turns": turns, "actions": actions,
            "scores": scores, "winner": winner, "max_ms": maximum_ms}


def all_expansion_matrix(seeds=(0, 1, 5)):
    from game.ui_dialogs import EXPANSIONS
    expansions = [key for key, _, _ in EXPANSIONS]
    count = 0
    for players in range(2, 7):
        for level in ("easy", "normal", "hard"):
            for seed in seeds:
                started = time.perf_counter()
                result = ai_game(level, level, seed, expansions, players)
                count += 1
                print("[全20扩展 %d人 %s seed=%d] %d次行动，终局供给守恒，%.2fs，最长选步%.0fms" %
                      (players, level, seed, result["actions"],
                       time.perf_counter()-started, result["max_ms"]), flush=True)
    print("ALL EXPANSIONS OK: %d games" % count, flush=True)
    return True


MATCHUPS = [("easy", "easy"), ("normal", "easy"), ("normal", "normal"),
            ("hard", "normal"), ("hard", "easy"), ("hard", "hard")]


def _expansions_from_args() -> Optional[list]:
    """--inns / --traders / --mini（迷你十件套+塔+羊+轮）任选组合。"""
    exp: list = []
    if "--inns" in sys.argv:
        exp.append("inns")
    if "--traders" in sys.argv:
        exp.append("traders")
    if "--mini" in sys.argv:
        exp += ["goldmines", "tunnel", "magewitch", "robbers", "crop",
                "festival", "besiegers", "tower", "hillsheep", "wheel"]
    return exp or None


def quick() -> bool:
    """快速验证：5 组对战各 1 局，确认合法性与收敛。"""
    exp = _expansions_from_args()
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
        exp = _expansions_from_args()
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
        # 梯度断言：高档位应稳定强于低档位（65%，M11 前瞻达标）。
        # 样本 <8 局时方差过大，只提示不断言（CI 用 ≥8）。
        if lv_a != lv_b:
            idx_a = {"easy": 0, "normal": 1, "hard": 2}[lv_a]
            idx_b = {"easy": 0, "normal": 1, "hard": 2}[lv_b]
            if idx_a > idx_b and wins[0] / n < 0.65:
                if n >= 8:
                    gradient_ok = False
                    print("  ⚠ 梯度不达标：%s 对 %s 胜率仅 %.0f%%" %
                          (lv_a, lv_b, 100 * wins[0] / n))
                else:
                    print("  （样本 %d 局过小，梯度仅供参考：%.0f%%）" %
                          (n, 100 * wins[0] / n))
    print("BENCH %s（梯度 %s）" % ("OK" if gradient_ok else "FAIL",
                                  "稳定" if gradient_ok else "需调优"))
    return gradient_ok


if __name__ == "__main__":
    if "--all" in sys.argv:
        seeds = (0, 1, 5)
        if "--seeds" in sys.argv:
            seeds = tuple(int(v) for v in sys.argv[sys.argv.index("--seeds") + 1].split(","))
        ok = all_expansion_matrix(seeds)
    elif "--bench" in sys.argv:
        i = sys.argv.index("--bench")
        n = int(sys.argv[i + 1]) if len(sys.argv) > i + 1 else 20
        ok = bench(n)
    else:
        ok = quick()
    sys.exit(0 if ok else 1)
