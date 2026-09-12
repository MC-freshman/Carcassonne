# -*- coding: utf-8 -*-
"""塔（M21）黄金用例：塔块射程抓人、互扣对换、赎金、驻塔完工、
终局归还（CAR 页 51-55）。塔块/驻塔/赎金都是部署阶段的替代动作。"""
from __future__ import annotations

import unittest

from game import tile_data as td
from game.board import KIND_ROAD
from game.engine import CarcassonneEngine


def scripted_engine(tile_seq, expansions=("tower",)):
    eng = CarcassonneEngine([{"name": "红方"}, {"name": "蓝方"}], seed=7,
                            expansions=list(expansions))
    assert tile_seq
    eng.current_tile = tile_seq[0]
    eng.deck = list(reversed(tile_seq[1:]))
    return eng


def place_at(eng, tile, x, y, rot):
    eng.current_tile = tile
    eng.phase = "place"
    assert (x, y, rot) in eng.legal_placements(), \
        "%s 无法放在 (%d,%d) rot%d" % (tile.tile_id, x, y, rot)
    eng.place(x, y, rot)


class TowerCaptureTest(unittest.TestCase):
    def test_piece_captures_in_range(self):
        """一层塔抓同行 1 格随从（CAR 页 52-53）。"""
        eng = scripted_engine(
            [td.by_id("TOW-field"), td.by_id("RStraight"), td.by_id("M")])
        place_at(eng, td.by_id("TOW-field"), 1, 0, 0)   # 红放塔基（正东）
        eng.skip_deploy()
        place_at(eng, td.by_id("RStraight"), 2, 0, 1)   # 蓝放南北路（塔同排）
        eng.deploy(KIND_ROAD, 0)                        # 蓝随从上路（距塔 1）
        place_at(eng, td.by_id("M"), 1, -1, 0)          # 红垫全田 → 部署阶段
        opts = dict(eng.tower_piece_options())
        self.assertIn((1, 0), opts)
        self.assertIn((2, 0, KIND_ROAD, 0), opts[(1, 0)])
        eng.tower_place((1, 0), (2, 0, KIND_ROAD, 0))   # 建塔顺手抓人
        self.assertEqual(len(eng.hostages), 1)
        self.assertEqual(eng.hostages[0]["owner"], "蓝")
        self.assertEqual(eng.hostages[0]["captor"], "红")
        self.assertEqual(eng.players[1].meeples_left, 6)   # 7-部署-被抓

    def test_range_grows_with_height(self):
        """射程 = 塔块数：首块射程 1，第二块达 2（CAR 页 53）。"""
        eng = scripted_engine(
            [td.by_id("TOW-field"), td.by_id("M"), td.by_id("M"),
             td.by_id("M"), td.by_id("RStraight"), td.by_id("M")])
        place_at(eng, td.by_id("TOW-field"), 1, 0, 0)
        eng.skip_deploy()
        place_at(eng, td.by_id("M"), 2, 0, 0)
        eng.skip_deploy()
        place_at(eng, td.by_id("RStraight"), 3, 0, 1)   # 红随从距塔 2 格
        eng.deploy(KIND_ROAD, 0)
        place_at(eng, td.by_id("M"), 1, -1, 0)          # 红垫牌 → 部署阶段
        opts = dict(eng.tower_piece_options())
        self.assertNotIn((3, 0, KIND_ROAD, 0), opts.get((1, 0), []))
        eng.tower_place((1, 0), None)                   # 首块：射程 1
        place_at(eng, td.by_id("M"), 0, -1, 0)          # 蓝垫牌
        eng.skip_deploy()
        place_at(eng, td.by_id("M"), 2, -1, 0)          # 红垫牌 → 部署阶段
        opts = dict(eng.tower_piece_options())
        self.assertIn((3, 0, KIND_ROAD, 0), opts[(1, 0)])
        eng.tower_place((1, 0), (3, 0, KIND_ROAD, 0))   # 第二块：射程 2
        self.assertEqual(eng.hostages[0]["owner"], "红")

    def test_mutual_capture_auto_exchange(self):
        """互扣人质立即自动对换归还（CAR 页 55）。"""
        eng = scripted_engine(
            [td.by_id("TOW-field"), td.by_id("RStraight"), td.by_id("M"),
             td.by_id("TOW-field"), td.by_id("RStraight"), td.by_id("M"),
             td.by_id("M"), td.by_id("M")])
        place_at(eng, td.by_id("TOW-field"), 1, 0, 0)   # 红塔基（东）
        eng.skip_deploy()
        place_at(eng, td.by_id("RStraight"), 2, 0, 1)   # 蓝路上（红射程 1）
        eng.deploy(KIND_ROAD, 0)
        place_at(eng, td.by_id("M"), 1, -1, 0)
        eng.tower_place((1, 0), (2, 0, KIND_ROAD, 0))   # 红抓蓝
        self.assertEqual(len(eng.hostages), 1)
        place_at(eng, td.by_id("TOW-field"), -1, 0, 0)  # 蓝塔基（西）
        eng.skip_deploy()
        place_at(eng, td.by_id("RStraight"), -2, 0, 1)  # 红路上（蓝射程 1）
        eng.deploy(KIND_ROAD, 0)
        place_at(eng, td.by_id("M"), -1, -1, 0)
        eng.tower_place((-1, 0), (-2, 0, KIND_ROAD, 0))  # 蓝抓红 → 互扣
        self.assertEqual(eng.hostages, [])               # 自动对换
        self.assertEqual(eng.players[0].meeples_left, 7)
        self.assertEqual(eng.players[1].meeples_left, 7)

    def test_ransom_returns_follower(self):
        """赎金 3 分：己方 -3、扣押者 +3，随从回供给（CAR 页 55）。"""
        eng = scripted_engine([td.by_id("M")])
        eng.hostages.append({"owner": "红", "captor": "蓝",
                             "size": 1, "ph": False})
        eng.players[0].meeples_left = 6
        eng.current_tile = td.by_id("M")
        eng.phase = "deploy"
        self.assertIn(0, eng.ransom_options())
        eng.ransom(0)
        self.assertEqual(eng.players[0].score, -3)
        self.assertEqual(eng.players[1].score, 3)
        self.assertEqual(eng.players[0].meeples_left, 7)
        self.assertEqual(eng.hostages, [])
        self.assertTrue(eng._ransom_used)
        self.assertEqual(eng.ransom_options(), [])


class TowerTopTest(unittest.TestCase):
    def test_deploy_top_finishes_tower(self):
        """驻塔随从完工：塔不再可加块，随从留至终局（CAR 页 54）。"""
        eng = scripted_engine(
            [td.by_id("TOW-field"), td.by_id("M"), td.by_id("M"),
             td.by_id("M")])
        place_at(eng, td.by_id("TOW-field"), 1, 0, 0)
        eng.skip_deploy()
        place_at(eng, td.by_id("M"), 2, 0, 0)
        eng.skip_deploy()
        place_at(eng, td.by_id("M"), 1, -1, 0)
        eng.tower_place((1, 0), None)                   # 红 1 层
        place_at(eng, td.by_id("M"), 0, -1, 0)
        eng.skip_deploy()
        place_at(eng, td.by_id("M"), 2, -1, 0)          # 红垫牌 → 部署阶段
        self.assertIn((1, 0), eng.tower_top_options())
        eng.tower_deploy_top((1, 0))                    # 驻塔代替部署
        self.assertEqual(eng.towers[0]["top"]["color"], "红")
        self.assertEqual(eng.players[0].meeples_left, 6)
        # 完工后不再可建块/驻塔
        self.assertNotIn((1, 0), [p for p, _c in eng.tower_piece_options()])
        self.assertNotIn((1, 0), eng.tower_top_options())

    def test_tower_top_returned_at_end(self):
        """终局驻塔随从归还供给。"""
        eng = scripted_engine([td.by_id("TOW-field")])
        place_at(eng, td.by_id("TOW-field"), 1, 0, 0)
        eng.tower_place((1, 0), None)                   # 放牌后直接建塔
        eng.current_tile = None
        eng.phase = "deploy"
        eng.tower_deploy_top((1, 0))
        eng.game_over = True
        eng.final_scoring()
        self.assertEqual(eng.players[0].meeples_left, 7)
        self.assertIsNone(eng.towers[0]["top"])

    def test_deploy_top_falls_back_to_big(self):
        """普通米宝耗尽时驻塔自动改用大型米宝。"""
        eng = scripted_engine([td.by_id("TOW-field")])
        place_at(eng, td.by_id("TOW-field"), 1, 0, 0)
        eng.tower_place((1, 0), None)
        eng.current_tile = None
        eng.phase = "deploy"
        eng.turn_idx = 0
        eng.players[0].meeples_left = 0
        eng.players[0].big_meeples_left = 1
        self.assertIn((1, 0), eng.tower_top_options())
        eng.tower_deploy_top((1, 0))
        self.assertTrue(eng.towers[0]["top"]["big"])
        self.assertEqual(eng.players[0].big_meeples_left, 0)
        eng.game_over = True
        eng.final_scoring()
        self.assertEqual(eng.players[0].big_meeples_left, 1)


if __name__ == "__main__":
    unittest.main()
