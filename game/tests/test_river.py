# -*- coding: utf-8 -*-
"""河流 II（M18）黄金用例：泉源单水边开局、岔流次序、单水边接触约束、
河流结束进入正常对局、火山湖降临、猪倌农场 +1 分/城（CAR 页 79-83）。"""
from __future__ import annotations

import unittest

from game import tile_data as td
from game.board import KIND_FARM
from game.engine import CarcassonneEngine
from game.models import PlacedTile, Terrain


class RiverInitTest(unittest.TestCase):
    def test_spring_replaces_start(self):
        eng = CarcassonneEngine([{"name": "红"}, {"name": "蓝"}], seed=3,
                                expansions=["river"])
        self.assertEqual(eng.phase, "river")
        self.assertEqual(len(eng.board.tiles), 1)
        start = eng.board.tiles[(0, 0)]
        self.assertEqual(start.tile_id, "RI-Spring")
        self.assertEqual(eng.current_tile.tile_id, "RI-Junction")
        # 火山湖固定最后
        self.assertTrue(eng.river_pile[-1].tile_id == "RI-VolcanoLake")

    def test_single_water_contact(self):
        eng = CarcassonneEngine([{"name": "红"}, {"name": "蓝"}], seed=3,
                                expansions=["river"])
        moves = eng.legal_placements()
        self.assertTrue(moves)
        for x, y, rot in moves:
            self.assertTrue(eng._river_contact_ok(eng.current_tile, x, y, rot),
                            "河流牌必须恰好一处水边接触: %r" % ((x, y, rot),))

    def test_river_ends_and_dragon_arrives(self):
        eng = CarcassonneEngine([{"name": "红"}, {"name": "蓝"}], seed=3,
                                expansions=["river"])
        rng_i = 0
        guard = 0
        while eng.phase == "river" and guard < 300:
            guard += 1
            moves = eng.legal_placements()
            if not moves:
                eng.discard_and_redraw()
                continue
            x, y, rot = moves[rng_i % len(moves)]
            rng_i += 1
            eng.place(x, y, rot)
            if eng.phase == "deploy":
                eng.skip_deploy()
        self.assertEqual(eng.phase, "place")
        self.assertFalse(eng._river_on)
        self.assertTrue(eng.dragon["active"])
        self.assertIsNotNone(eng.dragon["pos"])
        # 河流 12 张全部入场（泉源 + 岔流 + 9 + 火山湖）
        water_tiles = [t for t, d in eng.board.defs.items()
                       if any(e is Terrain.WATER for e in d.edges)]
        self.assertEqual(len(water_tiles), 12)


class PigHerdTest(unittest.TestCase):
    def test_herd_extra_point_per_city(self):
        """猪倌所在农场：终局农夫 3+1=4 分/城（脚注 247-251）。"""
        eng = CarcassonneEngine([{"name": "红"}, {"name": "蓝"}], seed=3,
                                expansions=["river"])
        # 猪倌牌接泉源南水边 (0,1)；东接单边城并完成 2 牌城
        eng.board.add_tile(PlacedTile("RI-PigHerd", 0, 1, 0, 0),
                           td.by_id("RI-PigHerd"))
        eng.board.add_tile(PlacedTile("C1s", 1, 1, 2, 0), td.by_id("C1s"))
        eng.board.add_tile(PlacedTile("C1s", 1, 2, 0, 0), td.by_id("C1s"))
        eng.board.deploy_meeple((0, 1, KIND_FARM, 0), "红", 1, force=True)
        eng.game_over = True
        evs = eng.final_scoring()
        farm_ev = [e for e in evs if e.kind == "farm"]
        self.assertEqual(len(farm_ev), 1)
        self.assertEqual(farm_ev[0].scores, {"红": 4})
        self.assertIn("猪倌", farm_ev[0].detail)


if __name__ == "__main__":
    unittest.main()
