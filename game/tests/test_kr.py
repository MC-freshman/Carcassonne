# -*- coding: utf-8 -*-
"""国王与强盗男爵（M18）黄金用例：首次完成夺取标记、更大城/路转移、
终局持有者 1 分/完成城（路）（CAR 页 70-71）。"""
from __future__ import annotations

import unittest

from game import tile_data as td
from game.board import KIND_CITY, KIND_ROAD
from game.engine import CarcassonneEngine


def scripted_engine(tile_seq, expansions=("king",)):
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
        else:
            kind, seg = deploy[0], deploy[1]
            opts = eng.deploy_options()
            assert any(o["kind"] == kind and o["seg"] == seg for o in opts), \
                "部署目标不可用: %r" % (deploy,)
            eng.deploy(kind, seg)


class KingRobberTest(unittest.TestCase):
    def _script(self):
        """3 牌路完成（强盗男爵）→ 2 牌城（国王）→ 3 牌城（国王转移）。"""
        eng = scripted_engine([td.by_id("RStraight"), td.by_id("RT"),
                               td.by_id("C1s"), td.by_id("C1s"),
                               td.by_id("C1s"), td.by_id("CCorner"),
                               td.by_id("C1s")])
        play_scripted(eng, [
            # 1. 红：直路接起始 S 路，红随从上路
            (0, 1, 1, (KIND_ROAD, 0)),
            # 2. 蓝：丁字收口 → 3 牌路完成（蓝 +3，夺强盗男爵 size3）
            (0, 2, 3, None),
            # 3. 红：单边城（东），红骑士
            (1, 0, 0, (KIND_CITY, 0)),
            # 4. 蓝：单边城（南）与上接 → 2 牌城完成（红 +4，蓝夺国王 size2）
            (1, -1, 2, None),
            # 5. 红：单边城（北），红骑士
            (0, -1, 0, (KIND_CITY, 0)),
            # 6. 蓝：角城（NE）
            (0, -2, 1, None),
            # 7. 红：单边城（W）收口 → 3 牌城完成（红 +6，夺回国王 size3）
            #    （城内已有红骑士 → 本回合不能再部署）
            (1, -2, 3, None),
        ])
        return eng

    def test_robber_baron_award(self):
        eng = self._script()
        self.assertEqual(eng.robber, {"holder": "蓝", "size": 3})
        road_ev = [e for e in eng.events if e.kind == "road"][0]
        self.assertEqual(road_ev.scores, {"红": 3})   # 路上随从属红

    def test_king_transfer(self):
        eng = self._script()
        # 第一个完成城（2 牌）→ 国王归完成者蓝（即使得分的是红）
        self.assertEqual(eng.king["size"], 3)
        self.assertEqual(eng.king["holder"], "红")   # 3 牌城转移给红
        city_evs = [e for e in eng.events if e.kind == "city"]
        self.assertEqual(city_evs[0].scores, {"红": 4})
        self.assertEqual(city_evs[1].scores, {"红": 6})

    def test_final_king_robber_bonus(self):
        eng = self._script()
        eng.game_over = True
        evs = eng.final_scoring()
        king_ev = [e for e in evs if e.kind == "king"]
        robber_ev = [e for e in evs if e.kind == "robber"]
        # 国王：红持有 → 场上完成城 2 座 → +2；强盗：蓝 → 完成路 1 条 → +1
        self.assertEqual(king_ev[0].scores, {"红": 2})
        self.assertEqual(robber_ev[0].scores, {"蓝": 1})
        self.assertEqual([p.score for p in eng.players], [3 + 4 + 6 + 2, 0 + 1])


if __name__ == "__main__":
    unittest.main()
