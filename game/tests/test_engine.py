# -*- coding: utf-8 -*-
"""规则引擎单元测试（黄金用例，依据 CAR v7.4 计分口径）。"""
from __future__ import annotations

import unittest

from game import tile_data
from game.board import KIND_CITY, KIND_FARM, KIND_MON, KIND_ROAD
from game.engine import CarcassonneEngine
from game.models import meeple_majority


def _by_id(tile_id: str):
    for t in tile_data.all_definitions():
        if t.tile_id == tile_id:
            return t
    raise KeyError(tile_id)


def scripted_engine(tile_seq):
    """构造 2 人引擎并预设摸牌顺序（依次摸 tile_seq[0], [1], ...）。"""
    eng = CarcassonneEngine([{"name": "红方"}, {"name": "蓝方"}], seed=7)
    assert tile_seq, "至少需要一张牌"
    eng.current_tile = tile_seq[0]
    eng.deck = list(reversed(tile_seq[1:]))
    return eng


def play_scripted(eng, moves):
    """按 (x, y, rot, deploy) 逐回合执行；deploy 为 (kind, seg) 或 None。"""
    for x, y, rot, deploy in moves:
        assert (x, y, rot) in eng.legal_placements(), \
            "脚本放置不合法: (%d,%d,%d)" % (x, y, rot)
        eng.place(x, y, rot)
        if deploy is None:
            eng.skip_deploy()
        else:
            kind, seg = deploy
            opts = eng.deploy_options()
            assert any(o["kind"] == kind and o["seg"] == seg for o in opts), \
                "部署目标不可用: %r in %r" % (deploy, [(o["kind"], o["seg"]) for o in opts])
            eng.deploy(kind, seg)


class TileDataTest(unittest.TestCase):
    def test_deck_matches_car(self):
        stats = tile_data.validate()
        self.assertEqual(stats["total"], 72)
        self.assertEqual(stats["classes"], tile_data.CAR_CLASS_COUNTS)


class MajorityFunctionTest(unittest.TestCase):
    def test_majority_and_tie(self):
        self.assertEqual(meeple_majority({"红": 2, "蓝": 1}), (["红"], 2))
        self.assertEqual(meeple_majority({"红": 1, "蓝": 1}), (["红", "蓝"], 1))
        self.assertEqual(meeple_majority({"红": 2, "蓝": 2}), (["红", "蓝"], 2))
        self.assertEqual(meeple_majority({"红": 3}), (["红"], 3))
        self.assertEqual(meeple_majority({}), ([], 0))


class CityScoringTest(unittest.TestCase):
    def test_tie_both_score_full(self):
        """两座 1 牌城由桥牌合并 → 4 牌城 8 分，红蓝平局各得全额（CAR）。"""
        t = _by_id
        eng = scripted_engine([t("C1s"), t("C1s"), t("CCorner"), t("CCorner")])
        play_scripted(eng, [
            (0, -1, 0, (KIND_CITY, 0)),   # 红 骑士占城A（北）
            (1, -1, 0, (KIND_CITY, 0)),   # 蓝 骑士占城B（北，与A独立）
            (0, -2, 1, None),             # 城A 扩为2牌，东口开放
            (1, -2, 2, None),             # 桥接A+B → 4牌城完成
        ])
        self.assertEqual(eng.players[0].score, 8)
        self.assertEqual(eng.players[1].score, 8)
        self.assertEqual([p.meeples_left for p in eng.players], [7, 7])
        ev = eng.events[-1]
        self.assertEqual(ev.kind, "city")
        self.assertEqual(ev.scores, {"红": 8, "蓝": 8})

    def test_same_color_no_double(self):
        """同色 2 骑士经合并同城：4 牌城得 8 分而非 16（CAR 脚注 21）。"""
        t = _by_id
        eng = scripted_engine([t("C1s"), t("C1s"), t("C1s"),
                               t("CCorner"), t("CCorner")])
        play_scripted(eng, [
            (1, 0, 0, (KIND_CITY, 0)),    # 红 骑士（城1 @ (1,0)）
            (-1, 0, 0, None),             # 蓝 放置不部署
            (2, 0, 0, (KIND_CITY, 0)),    # 红 第2骑士（城2，与城1独立）
            (1, -1, 1, None),             # 蓝：并入城1（东口开放）
            (2, -1, 2, None),             # 红：桥接两城 → 4牌城完成
        ])
        self.assertEqual(eng.players[0].score, 8)
        self.assertEqual(eng.players[0].meeples_left, 7)
        ev = eng.events[-1]
        self.assertEqual(ev.scores, {"红": 8})
        self.assertEqual(ev.meeples, {"红": 2})

    def test_completed_city_no_early_score(self):
        """未闭合城市不计分：桥接后东口仍开放时无事件。"""
        t = _by_id
        eng = scripted_engine([t("C1s"), t("CCorner")])
        play_scripted(eng, [
            (1, 0, 0, (KIND_CITY, 0)),    # 红 骑士
            (1, -1, 1, None),             # 2牌城，东口开放 → 不完成
        ])
        self.assertEqual(eng.events, [])
        self.assertEqual(eng.players[0].score, 0)
        # 特征未完成
        meta = eng.board.meta((1, -1, KIND_CITY, 0))
        self.assertFalse(meta.complete)


class RoadScoringTest(unittest.TestCase):
    def test_junction_terminates_road(self):
        """丁字路口终止道路：起始牌→直路→丁字支路 = 3 牌路完成，红 +3。"""
        t = _by_id
        eng = scripted_engine([t("RStraight"), t("RT")])
        play_scripted(eng, [
            (0, 1, 1, (KIND_ROAD, 0)),    # 红 强盗（直路转90°，N 边接起始牌南口）
            (0, 2, 1, None),              # 丁字 N 支路接入 → 路完成（交叉口终止）
        ])
        ev = eng.events[-1]
        self.assertEqual(ev.kind, "road")
        self.assertEqual(ev.scores, {"红": 3})
        self.assertEqual(eng.players[0].meeples_left, 7)

    def test_junction_arms_separate(self):
        """丁字的三条支路是独立道路段（CAR 脚注 15/358）。"""
        t = _by_id
        eng = scripted_engine([t("RT")])
        play_scripted(eng, [(0, 1, 1, None)])  # 丁字 N 支路接起始牌 S 路
        arm_roots = {eng.board.find((0, 1, KIND_ROAD, i)) for i in range(3)}
        self.assertEqual(len(arm_roots), 3, "丁字三支路应互相独立")
        complete_cnt = sum(1 for r in arm_roots if eng.board._meta[r].complete)
        self.assertEqual(complete_cnt, 1, "仅接入起始路的一支完成")


class MonasteryTest(unittest.TestCase):
    def test_monastery_surrounded_scores_nine(self):
        """第 1 手放修道院并部署僧侣，第 8 块邻牌落下时 +9 并归还。"""
        t = _by_id
        eng = scripted_engine([
            t("M"),        # 1: @ (1,0)，红 僧侣
            t("C1s"),      # 2: N  @ (1,-1)
            t("C1s"),      # 3: NE @ (2,-1)
            t("MR"),       # 4: E  @ (2,0)
            t("RStraight"),# 5: SE @ (2,1)
            t("C1s"),      # 6: S  @ (1,1)
            t("RStraight"),# 7: SW @ (0,1)
            t("C1s"),      # 8: NW @ (0,-1) → 修道院完成
        ])
        play_scripted(eng, [
            (1, 0, 0, (KIND_MON, 0)),
            (1, -1, 0, None),
            (2, -1, 0, None),
            (2, 0, 0, None),
            (2, 1, 1, None),
            (1, 1, 2, None),
            (0, 1, 1, None),
            (0, -1, 0, None),
        ])
        self.assertEqual(eng.players[0].score, 9)
        self.assertEqual(eng.players[0].meeples_left, 7)
        self.assertTrue(any(e.kind == "mon" and e.scores == {"红": 9}
                            for e in eng.events))


class FarmTest(unittest.TestCase):
    def test_farm_three_per_city_double_counted_across_farms(self):
        """完成城市毗邻两个农场：每个农场各计 3 分（CAR 脚注 32/33）。"""
        t = _by_id
        eng = scripted_engine([t("C1s"), t("C1s")])
        play_scripted(eng, [
            (1, 0, 0, (KIND_FARM, 0)),    # 红 农夫（南田，并入起始田）
            (1, -1, 2, (KIND_FARM, 0)),   # 蓝 农夫（北田，被城柱隔开）
            # 2 牌城随即完成（无骑士 → 不计分但 complete=True）
        ])
        evs = eng.final_scoring()
        farm_evs = [e for e in evs if e.kind == "farm"]
        self.assertEqual(len(farm_evs), 2, "两个农场分别计分")
        by_color = {}
        for e in farm_evs:
            for color, pts in e.scores.items():
                by_color[color] = by_color.get(color, 0) + pts
        self.assertEqual(by_color, {"红": 3, "蓝": 3})
        self.assertEqual([p.meeples_left for p in eng.players], [7, 7])

    def test_farm_zero_city_returns_farmer(self):
        """零完成城市的农场：农夫收回但 0 分（CAR 脚注 31）。"""
        t = _by_id
        eng = scripted_engine([t("RStraight")])
        play_scripted(eng, [
            (1, 0, 1, (KIND_FARM, 1)),    # 红 农夫（W 侧田，并入起始田）
        ])
        evs = eng.final_scoring()
        self.assertEqual([e for e in evs if e.kind == "farm"], [])
        self.assertEqual(eng.players[0].meeples_left, 7)


class MeepleRuleTest(unittest.TestCase):
    def test_cannot_deploy_on_occupied_farm(self):
        """农场已有红农夫时，蓝在并入同农场的牌上无农场部署选项。"""
        t = _by_id
        eng = scripted_engine([t("C1s"), t("C1s")])
        play_scripted(eng, [(1, 0, 0, (KIND_FARM, 0))])
        eng.place(0, -1, 0)   # 蓝：S=f 接起始 N=f → 农场并入红农夫所在农场
        opts = eng.deploy_options()
        self.assertFalse(any(o["kind"] == KIND_FARM for o in opts))

    def test_farmer_next_to_monastery_allowed(self):
        """修道院牌周围田地可部署农夫（CAR 脚注 13），修道院本身可再部署僧侣。"""
        t = _by_id
        eng = scripted_engine([t("M")])
        play_scripted(eng, [(1, 0, 0, (KIND_FARM, 0))])
        self.assertEqual(eng.players[0].meeples_left, 6)


class FinalScoringTest(unittest.TestCase):
    def test_incomplete_features_and_farms(self):
        """终局：未完成道路/城市按 1 分/牌（旗帜 1 分），农夫按农场结算。"""
        t = _by_id
        eng = scripted_engine([
            t("C1s"),      # 1: (1,0) 红 骑士（1牌未完成城，1分）+ 农夫入田
            t("RStraight"),# 2: (0,-1) 直路 N-S（红 强盗，2牌路? N端开放）
        ])
        play_scripted(eng, [
            (1, 0, 0, (KIND_CITY, 0)),
            (0, -1, 0, None),             # 蓝 不部署
        ])
        # 红骑士留在 1 牌未完成城市；无强盗。终局：城 +1 分
        evs = eng.final_scoring()
        city_evs = [e for e in evs if e.kind == "final_city"]
        self.assertEqual(len(city_evs), 1)
        self.assertEqual(city_evs[0].scores, {"红": 1})


if __name__ == "__main__":
    unittest.main()
