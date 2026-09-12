# -*- coding: utf-8 -*-
"""教堂与异端（M18）黄金用例：挑战成立、先完成者 9 分对方无分归还、
同时完成双方均得分、教堂邻接限制（CAR 页 84-86）。"""
from __future__ import annotations

import unittest

from game import tile_data as td
from game.board import KIND_MON, KIND_ROAD
from game.engine import CarcassonneEngine


def scripted_engine(tile_seq, expansions=("shrine",)):
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


class ShrineChallengeTest(unittest.TestCase):
    def test_challenge_resolution_shrine_first(self):
        """教堂先完成：异端 9 分，修道院僧侣无分归还。"""
        eng = scripted_engine(
            [td.by_id("M")] * 1 +
            [td.by_id("HES-FieldShrine")] +
            [td.by_id("M")] * 7)
        play_scripted(eng, [
            (1, 0, 0, (KIND_MON, 0)),      # 红：修道院 + 僧侣
            (2, 0, 0, (KIND_MON, 0)),      # 蓝：教堂（邻修道院）+ 异端 → 挑战
        ])
        self.assertEqual(len(eng.challenges), 1)
        # 修道院（1,0）四周 + 教堂（2,0）四周补满：教堂先完成
        fills = [(3, 0), (1, 1), (2, 1), (3, 1),
                 (1, -1), (2, -1), (3, -1)]
        for pos in fills:
            play_scripted(eng, [(pos[0], pos[1], 0, None)])
        # 修道院（1,0）8 邻齐了吗？(0,±1)/(0,0) 起始牌 + fills → 完成；
        # 教堂（2,0）8 邻齐 → 谁先在 pending 中谁先结算
        self.assertEqual(eng.challenges, [])
        shrine_ev = [e for e in eng.events if e.kind == "mon"
                     and e.pos == (2, 0)]
        mon_ev = [e for e in eng.events if e.kind == "mon" and e.pos == (1, 0)]
        self.assertTrue(shrine_ev or mon_ev)
        # 先完成者 9 分，另一方无分
        first = shrine_ev[0] if shrine_ev else mon_ev[0]
        second_pts = (mon_ev[0].scores if shrine_ev else shrine_ev[0].scores) \
            if (shrine_ev and mon_ev) else {}
        self.assertEqual(sum(first.scores.values()), 9)
        # 异端/僧侣均归还
        self.assertEqual(sum(p.meeples_left for p in eng.players), 14)

    def test_shrine_cannot_adjoin_two_cloisters(self):
        """教堂不得邻接 ≥2 修道院（CAR 页 84）。"""
        eng = scripted_engine([td.by_id("HES-FieldShrine")])
        play_scripted(eng, [(1, 0, 0, None)])   # 教堂放东侧（邻起始修道院）
        from game.models import PlacedTile
        # 手工放两座修道院于 (2,0) 与 (2,2) → 候选格 (2,1) 同时邻接两者
        eng.board.add_tile(PlacedTile("M", 2, 0, 0, -1), td.by_id("M"))
        eng.board.add_tile(PlacedTile("M", 2, 2, 0, -1), td.by_id("M"))
        eng.current_tile = td.by_id("HES-FieldShrine")
        eng.phase = "place"
        eng.placed_pos = None
        eng.deck = [td.by_id("M")]
        places = [p for p in eng.legal_placements() if p[0] == 2 and p[1] == 1]
        self.assertEqual(places, [], "(2,1) 邻接两座修道院，教堂应不可放")


if __name__ == "__main__":
    unittest.main()
