# -*- coding: utf-8 -*-
"""修道院与市长（A&M 扩展）黄金用例：Abbey 缺口放置/市长旗数强度/
粮仓立即结算/马车自动移动。"""
from __future__ import annotations

import unittest

from game import tile_data as td
from game.board import KIND_CITY, KIND_FARM, KIND_MON, KIND_ROAD
from game.engine import CarcassonneEngine


def scripted_engine(tile_seq, expansions=("inns", "traders", "pd", "abbey")):
    eng = CarcassonneEngine([{"name": "红方"}, {"name": "蓝方"}], seed=7,
                            expansions=list(expansions))
    assert tile_seq
    eng.current_tile = tile_seq[0]
    eng.deck = list(reversed(tile_seq[1:]))
    return eng


class AbbeyPlacementTest(unittest.TestCase):
    def test_abbey_plays_without_edge_match(self):
        """修道院可封闭相邻城市开口，实际落牌也应成功。"""
        eng = scripted_engine([td.by_id("AM-Abbey"), td.by_id("C1s"),
                               td.by_id("AM-Abbey")])
        eng.place(1, 0, 0)
        eng.deploy(KIND_MON, 0)
        eng.place(1, -1, 0)
        eng.skip_deploy()
        from game.models import N, S
        abbey = td.by_id("AM-Abbey")
        neighbor = td.by_id("C1s")
        self.assertNotEqual(abbey.edge(S), neighbor.edge(N))
        self.assertIn((1, -2, 0), eng.legal_placements())
        eng.place(1, -2, 0)
        self.assertIn((1, -2), eng.board.tiles)


class MayorTest(unittest.TestCase):
    def test_mayor_strength_zero_scores_nothing(self):
        """市长强度 = 城内旗帜数；无旗城完成市长不得分。"""
        eng = scripted_engine([
            td.by_id("AM-CCfMayor"),   # 红 (1,0) r0：W=f 接起始 E=f；城 N,E,S
            td.by_id("C1s"),
        ])
        eng.place(1, 0, 0)
        eng.deploy_mayor(0)              # 红 市长（城 N,E,S 三口，0 旗）
        # 蓝闭城：C1s r0 @ (0,1)：N=c 接 (1,0)?? (0,1) S 邻 (0,1)?? (1,0) 的 S=c 口
        # (1,0) S=c 口朝 (1,1)：C1s r2 @ (1,1) S=c 接 (1,0) S=c ✗（S 对 S）
        # C1s r2 的城在 S——需要 (1,1) N=c：C1s r0 N=c ✓
        eng2_moves = None
        # 蓝 (1,1) r0 C1s：N=c 接 (1,0) S=c ✓ 闭 S 口；城仍开 N,E
        # 再闭 N/E：C1s r2 @ (1,-1)?? (1,-1) S=c 面 (1,0) N=c ✓ 闭 N
        #           C1s r3 @ (2,0)?? (2,0) W=c 面 (1,0) E=c ✓ 闭 E
        eng.deck.append(td.by_id("C1s"))
        eng.deck.append(td.by_id("C1s"))
        eng.deck.append(td.by_id("C1s"))
        # 蓝 (1,1,0)
        eng.place(1, 1, 0)
        eng.skip_deploy()
        # 红 (1,-1,2)
        eng.place(1, -1, 2)
        eng.skip_deploy()
        # 蓝 (2,0,3)
        eng.place(2, 0, 3)
        eng.skip_deploy()
        # 城 4 牌完成（0 旗）→ 市长强度 0 → 红不得分
        self.assertEqual(eng.players[0].score, 0, "0 旗城市长不得分")

    def test_mayor_zero_votes_not_counted(self):
        """0 旗城市的市长（0 票）不参与多数：红骑士独得。"""
        eng = scripted_engine([td.by_id("C1s"), td.by_id("AM-CCfMayor")])
        eng.place(0, -1, 0)
        eng.deploy(KIND_CITY, 0)         # 红 骑士（城 N 口）
        eng.place(0, -2, 0)              # 蓝 AM-CCfMayor r0：S=c 接红城 N 口
        eng.deploy_mayor(0)              # 蓝 市长（0 旗 → 0 票）
        meta = eng.board.meta((0, -2, KIND_CITY, 0))
        winners, top = eng._city_majority(meta)
        self.assertEqual(winners, ["红"], "市长 0 票不干扰多数")
        self.assertEqual(top, 1)
        # 城未完成（N/E 口开）→ 无结算


class BarnTest(unittest.TestCase):
    def test_barn_instant_settle(self):
        """粮仓：部署即结算农场（农夫归还、多数者 3 分/城）。"""
        eng = scripted_engine([
            td.by_id("C1s"),            # 红 (0,-1) r0 农夫（起始农场）
            td.by_id("C1s"),            # 蓝 (0,-2) r2 闭 2 牌城（毗邻农场）
            td.by_id("AM-CfffBarn"),    # 红 (1,0) r0 粮仓（farm E,S,W 并入起始农场）
        ])
        eng.place(0, -1, 0)
        eng.deploy(KIND_FARM, 0)        # 红 农夫
        eng.place(0, -2, 2)
        eng.skip_deploy()               # 蓝闭 2 牌城（毗邻起始农场）
        eng.place(1, 0, 0)              # 红 粮仓（farm 并入起始农场）
        eng.deploy_barn(0)              # 立即结算
        # 农场结算：红多数 1 农夫 → 3 分/城 × 1 城 = 3；农夫归还
        barn_evs = [e for e in eng.events if e.kind == "barn"]
        self.assertEqual(len(barn_evs), 1)
        self.assertEqual(barn_evs[0].scores, {"红": 3})
        self.assertEqual(eng.players[0].meeples_left, 7, "农夫归还")


class WagonTest(unittest.TestCase):
    def test_wagon_registered_and_auto_moves(self):
        """马车部署与完成后自动移动（集成路径简化验证）。"""
        eng = scripted_engine([
            td.by_id("AM-CRCWagon"),   # crfr：N=c,E=r,S=f,W=r + wagon
            td.by_id("C1s"),           # 尾牌
        ])
        # 红 (0,1) r0：N=c 面 (0,0) S=r?? crfr r0: N=c ✗ 与起始 S=r 不匹配
        # r3: N=base E=r ✓ 接起始 S=r；路 {N,S}；城 {W}；farm {E}? 
        # crfr r3 edges：N=base[(0-3)%4=1]=E=r, E=base[2]=S=f, S=base[3]=W=r, W=base[0]=N=c
        # → (r,f,r,c)：路 N-S；城 W；farm E
        eng.place(0, 1, 3)
        eng.deploy_wagon("road", 0)     # 马车上路（N-S）
        # 龙牌测过复杂——直接验证 wagons 登记 + 自动移动逻辑：
        meta = eng.board.meta((0, 1, KIND_ROAD, 0))
        self.assertIn("红", meta.wagons, "马车已登记")
        # 完成该路：蓝 (0,2) RT r1?? 直接用引擎的 _wagon_auto_move 验证归还路径
        # 路 N-S 完成需两端闭——此处仅验证登记与移动函数存在性
        moved = eng._wagon_auto_move("红", eng.board.find((0, 1, KIND_ROAD, 0)))
        # 相邻起始路段未完成 → 马车移入（合法移动）
        self.assertTrue(moved, "马车移入相邻未完成段")
        self.assertEqual(eng.players[0].wagon_left, 0, "马车未归还")


if __name__ == "__main__":
    unittest.main()
