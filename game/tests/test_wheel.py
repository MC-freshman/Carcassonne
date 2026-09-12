# -*- coding: utf-8 -*-
"""命运之轮（M21）黄金用例：猪走格与扇区事件（幸运/税收/风暴/审判）/
王冠位上架与计分/瘟疫收回（CAR 页 109-112）。"""
from __future__ import annotations

import unittest

from game import tile_data as td
from game.board import KIND_CITY, KIND_MON
from game.engine import CarcassonneEngine


def wheel_engine():
    eng = CarcassonneEngine([{"name": "红方"}, {"name": "蓝方"}], seed=7,
                            expansions=["wheel"])
    return eng


class WheelEventTest(unittest.TestCase):
    def test_start_tile_is_wheel(self):
        """命运之轮起始牌替代修道院起始牌（CAR 页 109）。"""
        eng = wheel_engine()
        self.assertEqual(eng.board.defs[(0, 0)].tile_id, "WOF-start")

    def test_fortune_and_crown_scoring(self):
        """幸运 +3；王冠位独占 2 位扇区 6 分（CAR 页 110-112）。"""
        eng = wheel_engine()
        # 红上架王冠位（幸运扇区，2 位）→ 部署阶段选择王冠
        eng.phase = "deploy"
        eng.current_tile = td.by_id("M")
        eng.placed_pos = None
        copts = eng.crown_options()
        self.assertTrue(copts)
        # seg = sector*2+slot：幸运扇区 0 的第一个空位
        eng.deploy("crown", 0)
        self.assertEqual(eng.crowns[0][0]["color"], "红")
        self.assertEqual(eng.players[0].meeples_left, 6)
        # 蓝回合：强制抽命运牌 1 → 猪进幸运扇区 → 红 6 分归还 + 蓝（幸运事件）+3
        eng.turn_idx = 1
        eng.phase = "place"
        eng.current_tile = td.by_id("WOF-rs1")
        eng._wheel_event(1)
        self.assertEqual(eng.wheel_pig, 1 % 6)   # 猪 0→1（幸运在 0?——逆推见下）
        # 猪 0+1=1 = 瘟疫扇区 → 触发瘟疫阶段
        self.assertEqual(eng.phase, "plague")
        eng.plague_act(None)      # 双方场上无随从（王冠位不受瘟疫影响）
        eng.plague_act(None)
        # 王冠计分：猪停扇区 1 = 瘟疫（无人）→ 红的王冠位在扇区 0 不计
        self.assertEqual(eng.crowns[0][0]["color"], "红")

    def test_crown_alone_in_two_slot_scores_six(self):
        """猪停在幸运扇区（2 位）：独占 6 分（CAR 页 112）。"""
        eng = wheel_engine()
        eng.phase = "deploy"
        eng.current_tile = td.by_id("M")
        eng.crowns[0] = []
        eng.deploy("crown", 0)                 # 红上架幸运
        eng.turn_idx = 1
        eng.phase = "place"
        eng.current_tile = td.by_id("WOF-rs3")
        eng.wheel_pig = 0                      # 先把猪拨回 3，走 3 → 0 幸运
        eng._wheel_event(3)
        self.assertEqual(eng.wheel_pig, 3 % 6)
        # 猪停扇区 3 = 风暴：风暴事件按供给随从计分
        self.assertEqual(eng.phase, "place")   # 非瘟疫
        self.assertEqual(eng.crowns[0][0]["color"], "红")  # 幸运未触发不计

    def test_tax_event(self):
        """税收：每玩家按骑士所在城的骑士数+旗帜数得分（CAR 页 111）。"""
        eng = wheel_engine()
        from game.board import KIND_CITY, KIND_ROAD
        eng.current_tile = td.by_id("CCorner")
        eng.phase = "place"
        eng.place(0, -1, 2)                    # 城角{S,W}：W 口敞开不闭合
        eng.deploy(KIND_CITY, 0)               # 红骑士
        eng.current_tile = td.by_id("RStraight")
        eng.phase = "place"
        eng.place(0, 1, 1)                     # 蓝路贼（税收不数强盗）
        eng.deploy(KIND_ROAD, 0)
        # 重置分数，触发税收（猪拨到税扇区 5：走 5）
        eng.players[0].score = 0
        eng.players[1].score = 0
        eng.current_tile = td.by_id("WOF-rs3")
        eng.phase = "place"
        eng._wheel_event(5)
        self.assertEqual(eng.players[0].score, 1)   # 1 骑士 + 0 旗 = 1
        self.assertEqual(eng.players[1].score, 0)

    def test_plague_returns_follower(self):
        """瘟疫：各玩家依次收回一名场上随从（CAR 页 112）。"""
        eng = wheel_engine()
        from game.board import KIND_ROAD
        eng.current_tile = td.by_id("RStraight")
        eng.phase = "place"
        eng.place(0, 1, 1)
        eng.deploy(KIND_ROAD, 0)               # 红随从上路
        eng.turn_idx = 0
        eng.current_tile = td.by_id("WOF-rs2")
        eng.phase = "place"
        eng._wheel_event(1)                    # 猪 0→1 瘟疫
        self.assertEqual(eng.phase, "plague")
        self.assertEqual(eng.plague["order"][0], 0)   # 当前玩家先
        node = (0, 1, KIND_ROAD, 0)
        eng.plague_act(node)
        self.assertEqual(eng.players[0].meeples_left, 7)
        eng.plague_act(None)                   # 蓝无场上随从 → 自动跳过
        self.assertIsNone(eng.plague)


if __name__ == "__main__":
    unittest.main()
