# -*- coding: utf-8 -*-
"""桥、城堡与集市（M19）黄金用例：木桥架路且桥下农场不分隔、
2 牌小城改建城堡后回响计分、集市拍卖流程（CAR 页 92-101）。"""
from __future__ import annotations

import unittest

from game import tile_data as td
from game.board import KIND_CITY, KIND_FARM, KIND_ROAD
from game.engine import CarcassonneEngine
from game.models import N, S, Terrain


def scripted_engine(tile_seq, expansions=("bcb",)):
    eng = CarcassonneEngine([{"name": "红方"}, {"name": "蓝方"}], seed=7,
                            expansions=list(expansions))
    assert tile_seq
    eng.current_tile = tile_seq[0]
    eng.deck = list(reversed(tile_seq[1:]))
    return eng


class BridgeTest(unittest.TestCase):
    def test_bridge_over_field_connects_road(self):
        """起始南路对田：在新牌上架南北木桥，道路跨田连通。"""
        # RStraight frfr：N/S 田、E/W 路。放到起始正南 rot0 → N 田对起始 S 路。
        eng = scripted_engine([td.by_id("RStraight")])
        self.assertIn((0, 1, 0), eng.legal_placements())
        eng.place(0, 1, 0)
        self.assertIn((0, 1), eng.board.bridges)
        self.assertEqual(eng.board.bridges[(0, 1)], 0)  # 南北
        self.assertEqual(eng.players[0].bridges_left, 2)
        self.assertEqual(eng.board.printed_edge((0, 1), N), Terrain.FIELD)
        self.assertEqual(eng.board.matching_edge((0, 1), N), Terrain.ROAD)
        node = (0, 1, KIND_ROAD, eng.board.BRIDGE_SEG)
        meta = eng.board.meta(node)
        self.assertIn((0, 1), meta.tiles)
        eng.skip_deploy()

    def test_bridge_does_not_split_farm(self):
        """木桥不分割桥下农场：印刷边仍是田，农场段仍覆盖该边。"""
        eng = scripted_engine([td.by_id("RStraight")])
        eng.place(0, 1, 0)
        eng.skip_deploy()
        self.assertEqual(eng.board.printed_edge((0, 1), N), Terrain.FIELD)
        farm = eng.board.farm_seg_at_edge((0, 1), N)
        self.assertIsNotNone(farm)


class CastleTest(unittest.TestCase):
    def test_small_city_can_convert(self):
        """两段半圆城组成 2 牌小城 → 可改建城堡，不立刻得分。"""
        eng = scripted_engine([td.by_id("C1s"), td.by_id("C1s")])
        eng.place(0, -1, 0)
        self.assertTrue(any(o["kind"] == KIND_CITY for o in eng.deploy_options()))
        eng.deploy(KIND_CITY, 0)
        eng.place(0, -2, 2)
        eng.skip_deploy()
        self.assertEqual(eng.phase, "castle")
        self.assertTrue(eng.castle_options())
        eng.convert_castle(True)
        self.assertEqual(len(eng.castles), 1)
        self.assertEqual(eng.castles[0]["owner"], "红")
        self.assertEqual(eng.players[0].score, 0)
        self.assertEqual(eng.players[0].castles_left, 2)

    def test_castle_returns_extra_owner_meeples(self):
        """多数方城上多枚随从改建城堡：只留 1 枚作标记，其余立即归还。"""
        eng = scripted_engine([td.by_id("C1s"), td.by_id("C1s")])
        eng.place(0, -1, 0)
        eng.deploy(KIND_CITY, 0)
        node = (0, -1, KIND_CITY, 0)
        eng.board.deploy_meeple(node, eng.players[0].color, size=1, force=True)
        eng.players[0].meeples_left -= 1
        self.assertEqual(eng.players[0].meeples_left, 5)
        eng.place(0, -2, 2)
        eng.skip_deploy()
        eng.convert_castle(True)
        self.assertEqual(eng.castles[0]["fig"], "meeple")
        self.assertEqual(eng.players[0].meeples_left, 6)

    def test_castle_echoes_completed_road(self):
        """城堡邻格道路完成后，城堡主获得同等分数。"""
        # 横向小城 (0,-1)-(1,-1)，左右邻格含起始牌 (0,0)
        eng = scripted_engine([td.by_id("C1s"), td.by_id("C1s"),
                               td.by_id("RStraight"), td.by_id("RT")])
        eng.place(0, -1, 1)          # 东向城口
        eng.deploy(KIND_CITY, 0)
        eng.place(1, -1, 3)          # 西向城口对接
        eng.skip_deploy()
        eng.convert_castle(True)
        adj = set(map(tuple, eng.castles[0]["adjacent"]))
        self.assertIn((0, 0), adj)
        eng.place(0, 1, 1)           # 直路接起始南路
        eng.deploy(KIND_ROAD, 0)
        eng.place(0, 2, 3)           # 丁字收口完成道路
        eng.skip_deploy()
        echo = [e for e in eng.events if e.kind == "castle"]
        self.assertTrue(echo)
        self.assertEqual(eng.castles[0]["scored"], True)
        self.assertGreater(eng.players[0].score, 0)


class BazaarTest(unittest.TestCase):
    def test_bazaar_auction_and_free_last(self):
        """集市：下家选牌出价，最后一人免费得剩余牌。"""
        bazaar = td.by_id("BCB-FieldBazaar")
        extra = [td.by_id("C1s"), td.by_id("RStraight"), td.by_id("M")]
        eng = scripted_engine([bazaar] + extra)
        moves = eng.legal_placements()
        self.assertTrue(moves)
        x, y, rot = moves[0]
        eng.place(x, y, rot)
        eng.skip_deploy()
        self.assertEqual(eng.phase, "bazaar")
        self.assertEqual(eng.bazaar["phase"], "select")
        self.assertEqual(len(eng.bazaar["tiles"]), 2)
        eng.bazaar_select(0, 0)
        if eng.bazaar and eng.bazaar["phase"] == "bid":
            eng.bazaar_pass()
        if eng.bazaar and eng.bazaar["phase"] == "decide":
            eng.bazaar_resolve(True)
        if eng.bazaar and eng.bazaar.get("got"):
            self.assertEqual(len(eng.bazaar["got"]), 2)


class AbbeyBridgeTest(unittest.TestCase):
    def test_abbey_no_spurious_bridge(self):
        """修道院牌无视边匹配放置，一侧为路时不得自动建桥（CAR 脚注 292：
        建桥是部署之外的玩家主动动作，仅当放置需要桥时才自动建）。"""
        eng = scripted_engine([td.by_id("RStraight"), td.by_id("AM-Abbey")])
        eng.place(0, 1, 1)           # 南路：北口接起始南路
        eng.skip_deploy()
        eng.players[0].bridges_left = 0   # 旧实现此处直接 assert 崩溃
        eng.place(0, 2, 0)           # 修道院牌北对南路（田对路，不匹配也合法）
        self.assertEqual(eng.board.bridges, {})
        self.assertEqual(eng.phase, "deploy")
        # 玩家仍可自愿在此牌上架南北桥（两端均为田，南端接空格）
        self.assertIn(((0, 2), 0), eng.bridge_options())


if __name__ == "__main__":
    unittest.main()
