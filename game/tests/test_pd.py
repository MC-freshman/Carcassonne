# -*- coding: utf-8 -*-
"""公主与龙（P&D 扩展）黄金用例：火山降临、龙移动吞噬、仙女保护与加分、
公主移骑士、传送门跨牌部署。"""
from __future__ import annotations

import unittest

from game import tile_data as td
from game.board import KIND_CITY, KIND_FARM, KIND_ROAD
from game.engine import CarcassonneEngine


def scripted_engine(tile_seq, expansions=("inns", "traders", "pd")):
    eng = CarcassonneEngine([{"name": "红方"}, {"name": "蓝方"}], seed=7,
                            expansions=list(expansions))
    assert tile_seq
    eng.current_tile = tile_seq[0]
    eng.deck = list(reversed(tile_seq[1:]))
    return eng


class VolcanoTest(unittest.TestCase):
    def test_volcano_summons_dragon_and_blocks_deploy(self):
        """火山牌：龙降临该牌；本回合不能部署任何图元（可移仙女）。"""
        eng = scripted_engine([td.by_id("PD-TVolcano"), td.by_id("C1s")])
        # TVolcano r1：N=base W=r 接起始 S 路 ✓
        eng.place(0, 1, 1)
        self.assertTrue(eng._volcano_turn)
        self.assertEqual(eng.dragon["pos"], (0, 1))
        opts = eng.deploy_options()
        self.assertEqual([o for o in opts if o["kind"] not in ("fairy",)], [],
                         "火山回合无随从/建造者/猪选项")
        self.assertEqual([o for o in opts if o["kind"] == "fairy"], [],
                         "起始牌无红跟随者 → 无仙女选项")
        eng.skip_deploy()
        self.assertEqual(eng.phase, "place")


class DragonMoveTest(unittest.TestCase):
    def test_dragon_eats_followers(self):
        """龙移动到强盗所在牌 → 强盗归还（无分）；6 步机制运转。"""
        eng = scripted_engine([
            td.by_id("RStraight"),          # 红 (0,1) r1 强盗（接起始 S 路）
            td.by_id("C1s"),                # 蓝 (-1,0) r0 农夫（起始农场）
            td.by_id("PD-TVolcano"),        # 蓝 (0,2) 火山激活龙
            td.by_id("PD-StraightDragon"),  # 红 (0,3) r1：N=r 接 (0,2) S=r
        ])
        eng.place(0, 1, 1)
        eng.deploy(KIND_ROAD, 0)            # 红 强盗 @ (0,1)
        eng.place(-1, 0, 0)
        eng.deploy(KIND_FARM, 0)            # 蓝 农夫 @ (-1,0)
        eng.place(0, 2, 1)                  # 蓝火山 → 龙降临 (0,2)
        eng.skip_deploy()                   # 火山回合不能部署
        eng.place(0, 3, 1)                  # 红龙牌
        self.assertEqual(eng.phase, "deploy")
        eng.skip_deploy()                   # 不部署 → 龙阶段
        self.assertEqual(eng.phase, "dragon")
        self.assertEqual(eng.dragon["steps_left"], 6)
        self.assertEqual(eng.dragon["decider"], 0)
        legal = eng.dragon_legal_steps()
        self.assertIn((0, 1), legal, "龙可移入强盗所在牌")
        eng.dragon_move((0, 1))
        self.assertEqual(eng.players[0].meeples_left, 7, "强盗被吞归还")
        self.assertEqual(eng.dragon["steps_left"], 5)
        # 剩余步由蓝/红轮流（测试驱动到结束）
        guard = 0
        while eng.phase == "dragon" and guard < 20:
            guard += 1
            legal = eng.dragon_legal_steps()
            if not legal:
                break
            eng.dragon_move(legal[0])
        self.assertNotEqual(eng.phase, "dragon", "龙阶段结束")

    def test_dragon_respects_fairy_and_visited(self):
        """仙女所在牌禁入；已访问牌禁入。"""
        eng = scripted_engine([
            td.by_id("RStraight"),          # 红 (0,1) r1 强盗
            td.by_id("C1s"),                # 蓝 (-1,0) r0 农夫
            td.by_id("PD-TVolcano"),        # 蓝 (0,2) r1 火山（龙降临）
            td.by_id("PD-StraightDragon"),  # 红 (0,3) r1 龙牌（N=r 接火山 S=r）
        ])
        eng.place(0, 1, 1)
        eng.deploy(KIND_ROAD, 0)
        eng.place(-1, 0, 0)
        eng.deploy(KIND_FARM, 0)
        eng.place(0, 2, 1)                  # 火山 → 龙降临 (0,2)
        eng.skip_deploy()                   # 火山回合不能部署
        eng.place(0, 3, 1)                  # 红龙牌 → 龙阶段
        eng.skip_deploy()
        self.assertEqual(eng.phase, "dragon")
        # 仙女移到火山牌 (0,2)（红骑士不在，直接设置验证移动约束）
        eng.fairy = {"pos": (0, 2), "node": None, "owner": None}
        legal = eng.dragon_legal_steps()
        self.assertNotIn((0, 2), legal, "仙女牌禁入")
        self.assertIn((0, 1), legal)
        first = legal[0]
        eng.dragon_move(first)
        self.assertNotIn(first, eng.dragon_legal_steps(), "已访问牌禁入")


class FairyBonusTest(unittest.TestCase):
    def test_fairy_one_point(self):
        """红回合开始，仙女与红骑士同牌 → 红 +1。"""
        eng = scripted_engine([td.by_id("C1s"), td.by_id("C3s")])
        eng.place(0, -1, 0)
        eng.deploy(KIND_CITY, 0)            # 红骑士 @ (0,-1)（城 N 口）
        eng.fairy = {"pos": (0, -1), "node": (0, -1, KIND_CITY, 0), "owner": "红"}
        # 蓝 (0,-2) r2 C3s：S=W=N 三口城延伸（城未闭合 → 无 +3/城分干扰）
        eng.place(0, -2, 2)
        eng.skip_deploy()                   # 蓝不部署 → 推进红回合开始 → 红 +1
        self.assertEqual(eng.players[0].score, 1)

    def test_fairy_three_at_scoring(self):
        """城完成时，仙女旁跟随者主人 +3（独立结算）。"""
        eng = scripted_engine([
            td.by_id("C1s"),            # 红 (0,-1) r0 骑士
            td.by_id("C1s"),            # 蓝 (0,-2) r2 闭城
        ])
        eng.place(0, -1, 0)
        eng.deploy(KIND_CITY, 0)
        eng.fairy = {"pos": (0, -1), "node": (0, -1, KIND_CITY, 0), "owner": "红"}
        eng.place(0, -2, 2)
        eng.skip_deploy()               # 城完成
        fairy_evs = [e for e in eng.events if e.kind == "fairy"]
        self.assertEqual(len(fairy_evs), 1)
        self.assertEqual(fairy_evs[0].scores, {"红": 3})
        # 城分照常：2 牌 4 分
        city_evs = [e for e in eng.events if e.kind == "city"]
        self.assertEqual(city_evs[0].scores, {"红": 4})


class PortalTest(unittest.TestCase):
    def test_portal_cross_tile_deploy(self):
        """传送门：随从可部署到场上远处合法空段。"""
        eng = scripted_engine([
            td.by_id("C1s"),               # 红 (0,-1) r0 骑士（城 N 口）
            td.by_id("C3s"),               # 蓝 (0,-2) r2 城延伸（S,W,N 开口）
            td.by_id("PD-StraightPortal"), # 红 (-1,0) r0 传送门
        ])
        eng.place(0, -1, 0)
        eng.deploy(KIND_CITY, 0)           # 红 骑士
        eng.place(0, -2, 2)
        eng.skip_deploy()                  # 蓝不部署（城未完成：N,W 开）
        eng.place(-1, 0, 1)                # 红传送门（W=f 接起始 W=f）
        portal_opts = [o for o in eng.deploy_options() if o.get("pos")]
        far = [o for o in portal_opts
               if o.get("pos") == (0, -2) and o["kind"] == KIND_FARM]
        self.assertTrue(far, "传送门可部署到远处农场空段")
        eng.deploy(far[0]["kind"], far[0]["seg"], pos=far[0]["pos"])
        meta = eng.board.meta((0, -2, KIND_FARM, 0))
        self.assertEqual(meta.meeples.get("红"), 1, "跨牌部署成功")


class PrincessTest(unittest.TestCase):
    def test_princess_removes_opponent_knight(self):
        """公主牌延伸含红骑士的城 → 蓝可移走红骑士（归还其主人）。"""
        eng = scripted_engine([
            td.by_id("C1s"),               # 红 (0,-1) r0 骑士（城 N 口）
            td.by_id("PD-CCfPrincess"),    # 蓝 (0,-2) r0：S=c 接红城 N 口 + 公主
            td.by_id("C1s"),               # 尾牌
        ])
        eng.place(0, -1, 0)
        eng.deploy(KIND_CITY, 0)           # 红 骑士
        eng.place(0, -2, 0)                # 蓝 放公主牌（延伸含红骑士的城）
        pri = [o for o in eng.deploy_options()
               if o["kind"] == "princess" and o.get("victim_color") == "红"]
        self.assertTrue(pri, "蓝可用公主移走红骑士")
        eng.deploy_princess(tuple(pri[0]["victim"]), "红")
        self.assertEqual(eng.players[0].meeples_left, 7, "红骑士归还")
        # 移走骑士后本回合结束（蓝不能再部署）——轮到红
        self.assertEqual(eng.turn_idx, 0, "移走骑士后回合结束，推进红")


if __name__ == "__main__":
    unittest.main()
