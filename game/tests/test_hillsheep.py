# -*- coding: utf-8 -*-
"""山丘与羊（M21）黄金用例：牧羊人部署/抽卡/狼散群、扩群与入圈、
同草场共享羊群、山丘平局破缺、葡萄园修院加分、半边双段特殊牌合并
（CAR 页 102-109）。"""
from __future__ import annotations

import unittest

from game import tile_data as td
from game.board import KIND_CITY, KIND_FARM, KIND_MON
from game.engine import CarcassonneEngine


def scripted_engine(tile_seq, expansions=("hillsheep",)):
    eng = CarcassonneEngine([{"name": "红方"}, {"name": "蓝方"}], seed=7,
                            expansions=list(expansions))
    assert tile_seq
    eng.current_tile = tile_seq[0]
    eng.deck = list(reversed(tile_seq[1:]))
    return eng


def place_at(eng, tile, x, y, rot):
    eng.current_tile = tile
    eng.phase = "place"
    assert (x, y, rot) in eng.legal_placements(),         "%s 无法放在 (%d,%d) rot%d" % (tile.tile_id, x, y, rot)
    eng.place(x, y, rot)


class ShepherdTest(unittest.TestCase):
    def test_deploy_and_herd(self):
        """部署牧羊人抽羊；延伸草场后入圈得分（CAR 页 102-103）。"""
        eng = scripted_engine(
            [td.by_id("HS-sheepNs"), td.by_id("C1s"), td.by_id("M"),
             td.by_id("M"), td.by_id("M"), td.by_id("M")])
        eng.sheep_bag = [2]                 # 定死：先抽 2 羊
        place_at(eng, td.by_id("HS-sheepNs"), 1, 0, 0)
        eng.deploy_shepherd(0)              # 牧羊人（代替部署）
        self.assertEqual(eng.players[0].shepherd_left, 0)
        self.assertEqual([t for t in eng.shepherds[0]["tokens"]], [2])
        self.assertEqual(eng.phase, "place")
        # 蓝垫牌（不延伸）；红经起始牌草场延伸 → 牧羊行动阶段
        place_at(eng, td.by_id("C1s"), 1, -1, 2)
        eng.skip_deploy()
        place_at(eng, td.by_id("M"), 0, -1, 0)   # 延伸起始牌草场（红的）
        eng.skip_deploy()
        self.assertEqual(eng.phase, "shepherd")
        eng.sheep_bag = [3]                 # 扩群定抽 3
        eng.shepherd_act(True)
        self.assertEqual(sum(eng.shepherds[0]["tokens"]), 5)
        # 蓝垫牌；红再次延伸 → 入圈：5 羊全草场得分
        place_at(eng, td.by_id("M"), -1, -1, 0)
        eng.skip_deploy()
        place_at(eng, td.by_id("M"), -1, 0, 0)
        eng.skip_deploy()
        self.assertEqual(eng.phase, "shepherd")
        eng.shepherd_act(False)
        self.assertEqual(eng.players[0].score, 5)
        self.assertEqual(eng.players[0].shepherd_left, 1)
        self.assertEqual(eng.shepherds, [])

    def test_wolf_scatters_flock(self):
        """抽到狼：全草场羊回袋、牧羊人回家不得分（CAR 页 103）。"""
        eng = scripted_engine([td.by_id("HS-sheepNs")] + [td.by_id("M")] * 3)
        eng.sheep_bag = [0]                 # 定死：狼
        place_at(eng, td.by_id("HS-sheepNs"), 1, 0, 0)
        eng.deploy_shepherd(0)
        self.assertEqual(eng.shepherds, [])
        self.assertEqual(eng.players[0].shepherd_left, 1)
        self.assertEqual(len(eng.sheep_bag), 1)   # 狼回袋

    def test_shared_flock_scores_all_shepherds(self):
        """同草场多牧羊人共享羊群：入圈时各得全草场总分（CAR 页 103）。"""
        eng = scripted_engine(
            [td.by_id("HS-sheepNs"), td.by_id("M"), td.by_id("M")])
        eng.sheep_bag = [4]
        place_at(eng, td.by_id("HS-sheepNs"), 1, 0, 0)
        eng.deploy_shepherd(0)              # 红牧羊人（+4，抽完袋空）
        # 蓝牧羊人经草场合并进入同一特征（省略铺牌，直接入群）
        eng.players[1].shepherd_left -= 1
        eng.shepherds.append({"color": "蓝",
                              "node": eng.shepherds[0]["node"],
                              "tokens": [1]})
        roots = {eng.board.find(s["node"]) for s in eng.shepherds}
        self.assertEqual(len(roots), 1)     # 同一草场
        # 红延伸草场 → 入圈：红蓝各得 5 分
        place_at(eng, td.by_id("M"), 0, -1, 0)
        eng.skip_deploy()
        self.assertEqual(eng.phase, "shepherd")
        eng.shepherd_act(False)
        self.assertEqual([p.score for p in eng.players], [5, 5])
        self.assertEqual(eng.shepherds, [])


class HillTest(unittest.TestCase):
    def test_hill_breaks_tie(self):
        """山丘平局破缺：平局中恰一方有山丘骑士 → 独得（CAR 页 105）。"""
        eng = scripted_engine(
            [td.by_id("HS-hillNE"), td.by_id("C1s"), td.by_id("M"),
             td.by_id("M")])
        place_at(eng, td.by_id("HS-hillNE"), 0, -1, 0)   # 山丘城{N,E}
        eng.deploy(KIND_CITY, 0)                          # 红骑士在山丘
        place_at(eng, td.by_id("C1s"), 1, -1, 3)          # 东口合拢（蓝回合）
        eng.skip_deploy()
        # 蓝骑士强制入邻牌城段（同特征平地；实战中由合并产生）
        eng.board.deploy_meeple((1, -1, KIND_CITY, 0), "蓝", 1, force=True)
        place_at(eng, td.by_id("C1s"), 0, -2, 2)          # 北口合拢（红回合）
        eng.skip_deploy()
        self.assertEqual(eng.players[0].score, 6)         # 红独得 3×2
        self.assertEqual(eng.players[1].score, 0)

    def test_no_break_without_hill(self):
        """双方都无山丘 → 平局均得。"""
        eng = scripted_engine(
            [td.by_id("C1s"), td.by_id("C1s"), td.by_id("M"), td.by_id("M")])
        place_at(eng, td.by_id("C1s"), 0, -1, 0)
        eng.deploy(KIND_CITY, 0)
        eng.board.deploy_meeple((0, -1, KIND_CITY, 0), "蓝", 1, force=True)
        place_at(eng, td.by_id("C1s"), 0, -2, 2)
        eng.skip_deploy()
        self.assertEqual([p.score for p in eng.players], [4, 4])

    def test_under_tile_drawn_from_deck(self):
        """山丘放置时从牌堆抽一张暗牌垫底（CAR 页 104）。"""
        eng = scripted_engine(
            [td.by_id("HS-hillNE"), td.by_id("M"), td.by_id("M")])
        place_at(eng, td.by_id("HS-hillNE"), 1, 0, 0)
        eng.skip_deploy()
        self.assertEqual(len(eng.deck), 0)   # 放置 1 + 垫底 1
        self.assertIn((1, 0), eng.hills)


class VineyardTest(unittest.TestCase):
    def test_vineyard_bonus(self):
        """修院完成：周围每座葡萄园 +3（CAR 页 106）。"""
        eng = scripted_engine(
            [td.by_id("M"), td.by_id("HS-vydES"), td.by_id("M")] +
            [td.by_id("M")] * 11)
        place_at(eng, td.by_id("M"), 1, 0, 0)            # 修院（正东）
        eng.deploy(KIND_MON, 0)
        place_at(eng, td.by_id("HS-vydES"), 1, 1, 0)     # 葡萄园（修院南邻）
        eng.skip_deploy()
        for tile, x, y, r in [
                (td.by_id("RStraight"), 0, 1, 1),
                (td.by_id("M"), 2, 0, 0),
                (td.by_id("RStraight"), 2, 1, 0),
                (td.by_id("RStraight"), 0, 2, 1),
                (td.by_id("RStraight"), 1, 2, 1),
                (td.by_id("M"), 2, 2, 0),
                (td.by_id("M"), 0, -1, 0),
                (td.by_id("M"), 1, -1, 0),
                (td.by_id("M"), 2, -1, 0)]:
            place_at(eng, tile, x, y, r)
            eng.skip_deploy()
        # 修院 9 分 + 葡萄园 3 分 = 12
        self.assertEqual(eng.players[0].score, 12)


class SplitEdgeTest(unittest.TestCase):
    def test_citysplit_connects_both_segments(self):
        """半边双段"城侧"牌：邻牌城段与两个城段同时合并（CAR 页 107）。"""
        eng = scripted_engine(
            [td.by_id("HS-citysplit"), td.by_id("C1s"), td.by_id("M"),
             td.by_id("M")])
        place_at(eng, td.by_id("HS-citysplit"), 0, -1, 0)  # 北侧（东边双城段）
        eng.skip_deploy()
        place_at(eng, td.by_id("C1s"), 1, -1, 3)           # 西向城口贴上
        eng.deploy(KIND_CITY, 0)
        # 三个城段（特殊牌×2 + 邻牌×1）应合并为一个特征
        roots = {eng.board.find(n) for n in
                 [(0, -1, KIND_CITY, 1), (0, -1, KIND_CITY, 2),
                  (1, -1, KIND_CITY, 0)]}
        self.assertEqual(len(roots), 1)


if __name__ == "__main__":
    unittest.main()
