# -*- coding: utf-8 -*-
"""商人与建造者（T&B 扩展）黄金用例：货物收发与终局 10 分、
建造者双回合、猪 4 分/城（仅猪主人且为多数）。"""
from __future__ import annotations

import unittest

from game import tile_data as td
from game.board import KIND_CITY, KIND_FARM, KIND_ROAD
from game.engine import CarcassonneEngine


def scripted_engine(tile_seq, expansions=("inns", "traders")):
    eng = CarcassonneEngine([{"name": "红方"}, {"name": "蓝方"}], seed=7,
                            expansions=list(expansions))
    assert tile_seq
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
            continue
        kind = deploy[0]
        seg = deploy[1]
        big = deploy[2] if len(deploy) > 2 else False
        if kind == "builder":
            opts = eng.deploy_options()
            assert any(o["kind"] == "builder" and o["seg"] == seg for o in opts), \
                "建造者部署不可用: %r" % (deploy,)
            eng.deploy_builder(kind_to_engine_kind(kind), seg)
        elif kind == "pig":
            opts = eng.deploy_options()
            assert any(o["kind"] == "pig" and o["seg"] == seg for o in opts), \
                "猪部署不可用: %r" % (deploy,)
            eng.deploy_pig(KIND_FARM, seg)
        else:
            opts = eng.deploy_options()
            assert any(o["kind"] == kind and o["seg"] == seg
                       and bool(o.get("big")) == big for o in opts), \
                "部署目标不可用: %r" % (deploy,)
            eng.deploy(kind, seg, big=big)


def kind_to_engine_kind(kind):
    """部署选项中的 builder 需要目标段类型（城/路）——由选项列表携带，
    这里默认城段；调用方在段类型不同时直接使用选项 kind。"""
    return KIND_CITY


class GoodsTest(unittest.TestCase):
    def test_goods_to_completer_and_ten_points(self):
        """城完成 → 完成者收商品；终局酒最多者 +10。"""
        eng = scripted_engine([
            td.by_id("TB-CornerWine"),   # (1,0)：城角 N,E + 1 酒；farm S,W
            td.by_id("C1s"),             # (1,-1) r2：S 城闭 N 口
            td.by_id("C1s"),             # (2,0) r3：W 城闭 E 口 → 城完成
        ])
        play_scripted(eng, [
            (1, 0, 0, (KIND_CITY, 0)),      # 红 骑士
            (1, -1, 2, None),
            (2, 0, 3, None),                # 红闭城 → 红收 1 酒
        ])
        red = eng.players[0]
        self.assertEqual(red.goods.get("wine", 0), 1, "完成者收商品")
        ev = eng.events[-1]
        self.assertEqual(ev.scores, {"红": 6})   # 3 牌普通城
        evs = eng.final_scoring()
        g = [e for e in evs if e.kind == "goods"]
        self.assertEqual(len(g), 1)
        self.assertEqual(g[0].scores, {"红": 10}, "酒最多者终局 +10")

    def test_goods_tie_direct(self):
        """直接构造 goods 平局：红蓝各 1 酒 → 终局各 +10。"""
        eng = scripted_engine([td.by_id("C1s")])
        eng.players[0].goods["wine"] = 1
        eng.players[1].goods["wine"] = 1
        eng.deck = []
        while not eng.game_over:
            if eng.phase == "deploy":
                eng.skip_deploy()
            else:
                eng._draw_tile()
                if eng.current_tile is None:
                    eng.game_over = True
        evs = eng.final_scoring()
        g = [e for e in evs if e.kind == "goods"]
        self.assertEqual(len(g), 1)
        self.assertEqual(g[0].scores, {"红": 10, "蓝": 10})


class BuilderDoubleTurnTest(unittest.TestCase):
    def test_builder_double_turn(self):
        """延伸含己建造者的路 → 同玩家获得第二放置（无连锁）。"""
        eng = scripted_engine([
            td.by_id("RStraight"),        # 1 红 (0,1) r1 强盗（接起始 S 路）
            td.by_id("C1s"),              # 2 蓝 (-1,0) r0
            td.by_id("TB-CurveBuilder"),  # 3 红 (0,2) r1：曲路 N-W 接强盗路 + 建造者
            td.by_id("RStraight"),        # 4 红 (-1,2) r0 延伸 W 口 → 双回合
            td.by_id("C1s"),              # 5 红 第二部分 (0,3) r1
            td.by_id("C1s"),              # 6 蓝 收尾
        ])
        play_scripted(eng, [
            (0, 1, 1, (KIND_ROAD, 0)),          # 红 强盗
            (-1, 0, 0, None),                   # 蓝
            (0, 2, 1, ("builder", 0)),          # 红 建造者上该路
            (-1, 2, 0, None),                   # 红延伸 → 触发双回合
        ])
        self.assertEqual(eng.turn_idx, 0, "双回合第二部分仍为红")
        self.assertEqual(eng.phase, "place")
        self.assertFalse(eng._extra_turn, "标志已消耗（无连锁）")
        play_scripted(eng, [(0, 3, 1, None)])  # 红第二放置
        self.assertEqual(eng.turn_idx, 1, "第二部分结束推进蓝")


class PigFarmTest(unittest.TestCase):
    def test_pig_four_per_city_for_owner(self):
        """猪主人（农场多数）4 分/城；无猪多数者 3 分/城。"""
        eng = scripted_engine([
            td.by_id("C1s"),          # 红 (0,-1) r0 农夫（起始农场）
            td.by_id("C1s"),          # 蓝 (0,-2) r2 闭 2 牌城
            td.by_id("TB-CrffPig"),   # 红 (1,0) r0 猪入同农场
        ])
        play_scripted(eng, [
            (0, -1, 0, (KIND_FARM, 0)),         # 红 农夫
            (0, -2, 2, None),                   # 蓝闭城（无骑士）
            (1, 0, 0, ("pig", 0)),              # 红 猪入农场
        ])
        evs = eng.final_scoring()
        farm = [e for e in evs if e.kind == "farm"]
        self.assertEqual(len(farm), 1)
        self.assertEqual(farm[0].scores, {"红": 4}, "猪主人 4 分/城")
        self.assertEqual(eng.players[0].pig_left, 1, "终局猪归还")


if __name__ == "__main__":
    unittest.main()
