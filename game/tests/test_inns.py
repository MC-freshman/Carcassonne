# -*- coding: utf-8 -*-
"""客栈与大教堂（I&C 扩展）黄金用例：客栈双倍/终局 0 分、
大教堂三倍/终局 0 分、大型米宝多数按 2 计、大米宝不翻倍得分。
"""
from __future__ import annotations

import unittest

from game import tile_data as td
from game.board import KIND_CITY, KIND_FARM, KIND_MON, KIND_ROAD
from game.engine import CarcassonneEngine


def scripted_engine(tile_seq, expansions=("inns",)):
    eng = CarcassonneEngine([{"name": "红方"}, {"name": "蓝方"}], seed=7,
                            expansions=list(expansions))
    assert tile_seq, "至少需要一张牌"
    eng.current_tile = tile_seq[0]
    eng.deck = list(reversed(tile_seq[1:]))
    return eng


def play_scripted(eng, moves):
    for x, y, rot, deploy in moves:
        assert (x, y, rot) in eng.legal_placements(), \
            "脚本放置不合法: (%d,%d,%d)" % (x, y, rot)
        eng.place(x, y, rot)
        if deploy is None:
            eng.skip_deploy()
        else:
            kind, seg = deploy[0], deploy[1]
            big = deploy[2] if len(deploy) > 2 else False
            opts = eng.deploy_options()
            assert any(o["kind"] == kind and o["seg"] == seg
                       and bool(o.get("big")) == big for o in opts), \
                "部署目标不可用: %r" % (deploy,)
            eng.deploy(kind, seg, big=big)


class InnFullRoadTest(unittest.TestCase):
    def _path(self):
        """构造：起始牌 S 路 → 普通直路 → 客栈直路 → 丁字终止。"""
        # 起始牌 (0,0) S=r
        # (0,1) RStraight rot0: frfr N=f 需接 r? 起始 S=r → N 必须 r → rot1
        # 简化直接放：先把起始 S 路接一条路再客栈
        eng = scripted_engine([td.by_id("RStraight"), td.by_id("IC-StraightInn"),
                               td.by_id("RT")])
        play_scripted(eng, [
            (0, 1, 1, (KIND_ROAD, 0)),     # 红：直路 N-S，N 接起始 S 路
            (0, 2, 1, None),               # 客栈直路 N-S 延伸（客栈在东段? 见结构）
            (0, 3, 1, None),               # 丁字 N 支路接入 → 完成（含客栈 → 2×）
        ])
        return eng

    def test_inn_double_points(self):
        eng = self._path()
        ev = [e for e in eng.events if e.kind == "road"][-1]
        # 4 张牌路（起始+直路+客栈路+丁字）= 客栈路 → 2×4 = 8 分
        self.assertEqual(ev.scores, {"红": 8})

    def test_inn_zero_at_end(self):
        """客栈路未完成：终局 0 分（普通路 1 分/牌对照）。"""
        eng = scripted_engine([td.by_id("RStraight"), td.by_id("IC-StraightInn")])
        play_scripted(eng, [
            (0, 1, 1, (KIND_ROAD, 0)),     # 红：直路 N-S（接起始，未完成）
            (0, 2, 1, None),               # 客栈路续接（未完成）
        ])
        evs = eng.final_scoring()
        zero = [e for e in evs if e.kind == "final_road"
                and "客栈" in (e.detail or "")]
        self.assertEqual(len(zero), 1)
        self.assertEqual(zero[0].scores, {"红": 0})
        self.assertEqual(eng.players[0].meeples_left, 7, "0 分也要归还米宝")


class CathedralTest(unittest.TestCase):
    def test_cathedral_closed(self):
        """大教堂城完成：3 分/牌（4 牌城无旗 → 12 分；普通城为 8 分）。"""
        eng = scripted_engine([td.by_id("IC-Cath3s"), td.by_id("C1s"),
                               td.by_id("C1s"), td.by_id("C1s")])
        play_scripted(eng, [
            (1, 0, 0, (KIND_CITY, 0)),      # 红 骑士（大教堂城 N,E,S 开口）
            (1, -1, 2, None),               # 闭 N 口
            (2, 0, 3, None),                # 闭 E 口
            (1, 1, 0, None),                # 闭 S 口 → 完成
        ])
        ev = eng.events[-1]
        self.assertEqual(ev.kind, "city")
        self.assertEqual(ev.scores, {"红": 12}, "大教堂 3 分/牌")
        self.assertIn("大教堂", ev.detail or ev.reason)

    def test_cathedral_zero_at_end(self):
        """大教堂城未完成：终局 0 分。"""
        eng = scripted_engine([td.by_id("IC-Cath3s"), td.by_id("C1s")])
        play_scripted(eng, [
            (1, 0, 0, (KIND_CITY, 0)),      # 红 骑士（城未完成）
            (1, -1, 2, None),               # 只闭 N 口
        ])
        evs = eng.final_scoring()
        zero = [e for e in evs if e.kind == "final_city"
                and "大教堂" in (e.detail or "")]
        self.assertEqual(len(zero), 1)
        self.assertEqual(zero[0].scores, {"红": 0})
        self.assertEqual(eng.players[0].meeples_left, 7)


class BigFollowerTest(unittest.TestCase):
    def test_big_follower_majority(self):
        """大型米宝多数按 2 计：红大 1 票 vs 蓝普通 1 票 → 红独得。"""
        eng = scripted_engine([td.by_id("C1s"), td.by_id("C1s"),
                               td.by_id("CCorner"), td.by_id("CCorner")])
        play_scripted(eng, [
            (0, -1, 0, (KIND_CITY, 0, True)),   # 红：大型骑士（权重 2）
            (1, -1, 0, (KIND_CITY, 0)),         # 蓝：普通骑士
            (0, -2, 1, None),
            (1, -2, 2, None),                   # 桥接完成 → 红独得
        ])
        ev = eng.events[-1]
        self.assertEqual(ev.scores, {"红": 8})
        self.assertEqual(eng.players[0].big_meeples_left, 1, "大米宝归还")

    def test_big_follower_tie(self):
        """大 vs 大 + 普通：权重 2 vs 2 平局 → 双方均得。"""
        eng = scripted_engine([td.by_id("C1s"), td.by_id("C1s"),
                               td.by_id("C1s"), td.by_id("CCorner"),
                               td.by_id("CCorner")])
        play_scripted(eng, [
            (0, -1, 0, (KIND_CITY, 0, True)),   # 红大（2）
            (1, -1, 0, (KIND_CITY, 0, True)),   # 蓝大（2）
            (2, -1, 0, None),                   # 蓝占位牌
            (0, -2, 1, None),
            (1, -2, 2, None),                   # 桥接 → 2v2 平局
        ])
        ev = eng.events[-1]
        self.assertEqual(ev.scores, {"红": 8, "蓝": 8})


if __name__ == "__main__":
    unittest.main()
