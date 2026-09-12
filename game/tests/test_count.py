# -*- coding: utf-8 -*-
"""卡卡颂伯爵（M18）黄金用例：城块开局即完整大城、农场毗邻大城 3 分、
重部署回合（伯爵封锁/移入结算）、进城部署触发、终局国王含大城
（CAR 页 72-78，脚注 199/201/226）。"""
from __future__ import annotations

import unittest

from game import tile_data as td
from game.board import KIND_CITY, KIND_FARM, KIND_ROAD
from game.engine import CarcassonneEngine
from game.models import PlacedTile


def make_engine(expansions=("count",)):
    return CarcassonneEngine([{"name": "红方"}, {"name": "蓝方"}], seed=7,
                             expansions=list(expansions))


class CountInitTest(unittest.TestCase):
    def test_block_placed_and_complete(self):
        eng = make_engine()
        self.assertEqual(len(eng.board.tiles), 12)
        self.assertNotIn((0, 0), [])  # 起始修道院不存在：只有城块
        ids = {t.tile_id for t in eng.board.tiles.values()}
        self.assertTrue(all(i.startswith("CC-") for i in ids))
        root = eng.board.find((0, 0, KIND_CITY, 0))
        meta = eng.board._meta[root]
        self.assertEqual(len(meta.tiles), 12)
        self.assertEqual(meta.open_edges, 0)
        self.assertEqual(eng.count["count_pos"], "castle")

    def test_farm_scores_count_city(self):
        """边界草地农夫：终局 3 分（大城为毗邻完成城，脚注 201）。"""
        eng = make_engine()
        eng.board.deploy_meeple((0, 0, KIND_FARM, 0), "红", 1, force=True)
        eng.game_over = True
        evs = eng.final_scoring()
        farm_ev = [e for e in evs if e.kind == "farm"]
        self.assertEqual(len(farm_ev), 1)
        self.assertEqual(farm_ev[0].scores, {"红": 3})

    def test_king_counts_count_city(self):
        """国王终局计分包含伯爵城（脚注 199）。"""
        eng = make_engine(("count", "king"))
        eng.king = {"holder": "红", "size": 2}
        eng.game_over = True
        evs = eng.final_scoring()
        king_ev = [e for e in evs if e.kind == "king"]
        self.assertEqual(king_ev[0].scores, {"红": 1})   # 仅大城 1 座


class RedeployTest(unittest.TestCase):
    def _two_tile_city(self, eng):
        """脱离脚本：直接并入一张 2 牌完成城（绕过放置合法性）。"""
        eng.board.add_tile(PlacedTile("C1s", 6, 0, 0, 0), td.by_id("C1s"))
        eng.board.add_tile(PlacedTile("C1s", 6, -1, 2, 1), td.by_id("C1s"))
        return eng.board.find((6, 0, KIND_CITY, 0))

    def test_redeploy_round_moves_follower(self):
        eng = make_engine()
        eng.count["quarters"]["castle"].append(["红", "meeple"])
        eng.count["count_pos"] = "market"      # 伯爵不在城堡区 → 可移出
        root = self._two_tile_city(eng)
        eng.pending_completions = [root]
        eng._resolve_turn()
        self.assertEqual(eng.phase, "redeploy")
        st = eng.redeploy_state()
        self.assertIsNotNone(st)
        self.assertEqual(st["quarter"], "castle")
        # 依序决策：先 (placer+1)%2 = 1（蓝，无随从→不移），再红（移入）
        eng.redeploy_move(False)               # 蓝
        eng.redeploy_move(True)                # 红：全移入
        self.assertIsNone(eng.redeploy_state())
        self.assertEqual(eng.count["quarters"]["castle"], [])
        self.assertEqual(eng.players[0].score, 4)   # 2 牌城 4 分
        # 红（放置者）因移入的随从而得分 → 无进城部署机会（脚注 213）
        self.assertEqual(eng.phase, "place")

    def test_count_blocks_quarter(self):
        """伯爵所在区不可移出（CAR 页 77）。"""
        eng = make_engine()
        eng.count["quarters"]["castle"].append(["红", "meeple"])
        root = self._two_tile_city(eng)
        eng.pending_completions = [root]
        eng._resolve_turn()                    # 伯爵初始在城堡区
        self.assertNotEqual(eng.phase, "redeploy")
        self.assertEqual(eng.count["quarters"]["castle"], [["红", "meeple"]])

    def test_count_deploy_trigger(self):
        """放置触发计分而放置者未得分 → 可部署 1 名随从进城（CAR 页 73）。"""
        eng = make_engine()
        eng._count_trigger = True
        eng._placer_scored = False
        eng._placer_idx = 0
        eng._after_count_scoring()
        self.assertEqual(eng.phase, "count_deploy")
        opts = eng.count_deploy_options()
        self.assertTrue(any(o["quarter"] == "market" and o["fig"] == "meeple"
                            for o in opts))
        self.assertTrue(any(o["quarter"] == "castle" and o["fig"] == "mayor"
                            for o in opts) is False)  # 市长未启用（无 A&M）
        eng.deploy_count("market", "meeple", "castle")
        self.assertEqual(eng.count["quarters"]["market"], [["红", "meeple"]])
        self.assertEqual(eng.count["count_pos"], "castle")
        self.assertEqual(eng.phase, "place")


if __name__ == "__main__":
    unittest.main()
