# -*- coding: utf-8 -*-
"""M20 迷你扩展黄金用例：隧道地下接通、法师女巫计分、金矿归属、
麦田怪圈收回、强盗偷分、围攻城 1 分/牌、幽灵第二随从、节日收回
（CAR 页 120-200）。"""
from __future__ import annotations

import unittest

from game import tile_data as td
from game.board import KIND_CITY, KIND_MON, KIND_ROAD
from game.engine import CarcassonneEngine


def scripted_engine(tile_seq, expansions=()):
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
        "%s 无法放在 (%d,%d) rot%d（合法：%s）" % (
            tile.tile_id, x, y, rot,
            sorted(eng.legal_placements())[:6])
    eng.place(x, y, rot)


class TunnelTest(unittest.TestCase):
    def test_tunnel_links_two_mouths(self):
        """同色双令牌接通隧道：道路贯通只计可见段（CAR 页 199）。"""
        eng = scripted_engine(
            [td.by_id("RStraight"), td.by_id("M"), td.by_id("TUN-Nwe"),
             td.by_id("RT"), td.by_id("M")],
            ("tunnel",))
        eng.place(0, 1, 1)                # 红放南下直路
        eng.deploy(KIND_ROAD, 0)          # 红随从上路
        place_at(eng, td.by_id("M"), 1, 0, 0)         # 蓝垫一张全田
        eng.skip_deploy()
        place_at(eng, td.by_id("TUN-Nwe"), 0, 2, 1)   # 红放隧道（口朝南北）
        self.assertEqual(eng.phase, "tunnel")
        mouths = eng.tunnel_options()
        self.assertIn((0, 2, KIND_ROAD, 0), mouths)   # 北口
        self.assertIn((0, 2, KIND_ROAD, 1), mouths)   # 南口
        eng.tunnel_claim((0, 2, KIND_ROAD, 0))        # 红第一枚：仅占领
        self.assertEqual(eng.players[0].tunnels_left, 2)  # 2 人各 3 对
        self.assertNotIn((0, 2, KIND_ROAD, 0), eng.tunnel_options())
        self.assertEqual(eng.phase, "deploy")
        eng.skip_deploy()
        place_at(eng, td.by_id("RT"), 0, 3, 1)        # 蓝放丁字接南口外缘
        self.assertEqual(eng.phase, "tunnel")
        eng.tunnel_skip()                             # 蓝放弃占领
        self.assertEqual(eng.phase, "deploy")
        eng.skip_deploy()
        place_at(eng, td.by_id("M"), 1, -1, 0)        # 红垫一张全田
        self.assertEqual(eng.phase, "tunnel")         # 仍有空口 → 再问
        eng.tunnel_claim((0, 2, KIND_ROAD, 1))        # 红第二枚：同色贯通
        self.assertEqual(eng.phase, "deploy")
        eng.skip_deploy()
        # 道路完成：起始 + 直路 + 隧道牌 + 丁字 = 4 分（地下不计）
        self.assertEqual(eng.players[0].score, 4)
        self.assertEqual(eng.players[0].meeples_left, 7)
        self.assertNotIn("红", eng.tunnel_open)

    def test_tunnel_road_stays_broken_without_pair(self):
        """只占一个口：路仍断头不完成（CAR 页 198-199）。"""
        eng = scripted_engine([td.by_id("TUN-Nwe")], ("tunnel",))
        place_at(eng, td.by_id("TUN-Nwe"), 1, 0, 1)
        self.assertEqual(eng.phase, "tunnel")
        eng.tunnel_claim((1, 0, KIND_ROAD, 0))
        eng.skip_deploy()
        eng.current_tile = None
        eng.game_over = True
        for root in eng.board.roots():
            meta = eng.board._meta[root]
            if meta.kind == KIND_ROAD:
                self.assertFalse(meta.complete)


class MageWitchTest(unittest.TestCase):
    def test_mage_adds_per_tile(self):
        """城完成时法师 +1 分/牌（CAR 页 158：8 牌城 20+8）。"""
        eng = scripted_engine(
            [td.by_id("C1s"), td.by_id("MGW-N"), td.by_id("C1s")],
            ("magewitch",))
        eng.place(0, -1, 0)
        eng.deploy(KIND_CITY, 0)
        place_at(eng, td.by_id("MGW-N"), 0, 1, 1)
        self.assertEqual(eng.phase, "magewitch")
        eng.mw_move("mage", (0, -1, KIND_CITY, 0))   # 法师进城
        eng.skip_deploy()
        place_at(eng, td.by_id("C1s"), 0, -2, 2)     # 合拢完成 2 牌城
        eng.skip_deploy()
        # 2 牌 ×2 = 4，法师 +2 → 6 分
        self.assertEqual(eng.players[0].score, 6)
        self.assertIsNone(eng.mage)                  # 随完成离场

    def test_witch_halves_points(self):
        """女巫使完成路减半向上取整（CAR 页 159：5 牌路得 3）。"""
        eng = scripted_engine(
            [td.by_id("RStraight"), td.by_id("MGW-C")],
            ("magewitch",))
        eng.place(0, 1, 1)
        eng.deploy(KIND_ROAD, 0)
        place_at(eng, td.by_id("MGW-C"), 0, 2, 3)    # 南接城门路（路成 3 牌）
        self.assertEqual(eng.phase, "magewitch")
        witch_on = next(n for n in eng.mw_options()["witch"]
                        if eng.board.find(n) == eng.board.find((0, 1, KIND_ROAD, 0)))
        eng.mw_move("witch", witch_on)                # 女巫上路（计分前移动）
        eng.skip_deploy()
        # 3 分减半向上 → 2 分
        self.assertEqual(eng.players[0].score, 2)


class GoldminesTest(unittest.TestCase):
    def test_gold_awards_majority(self):
        """金矿牌落 2 块金；修院完成时多数者全取（CAR 页 148）。"""
        eng = scripted_engine(
            [td.by_id("GLD-Mon2"), td.by_id("RStraight"), td.by_id("M"),
             td.by_id("M"), td.by_id("M"), td.by_id("M"), td.by_id("M"),
             td.by_id("RStraight"), td.by_id("RStraight")],
            ("goldmines",))
        place_at(eng, td.by_id("GLD-Mon2"), 1, 0, 0)
        self.assertEqual(eng.phase, "gold")
        self.assertIn((0, 0), eng.gold_options())
        eng.place_gold((0, 0))
        self.assertEqual(eng.phase, "deploy")
        eng.deploy(KIND_MON, 0)
        for tile, x, y, r in [
                (td.by_id("RStraight"), 0, 1, 1),
                (td.by_id("RStraight"), 2, 0, 0),
                (td.by_id("M"), 0, -1, 0), (td.by_id("M"), 1, -1, 0),
                (td.by_id("M"), 2, -1, 0),
                (td.by_id("M"), 2, 1, 0),
                (td.by_id("RStraight"), 1, 1, 1)]:
            place_at(eng, tile, x, y, r)
            eng.skip_deploy()
        # 修院完成：9 分；金块 2 块归多数者（红僧），终局再折分
        self.assertEqual(eng.players[0].gold_pieces, 2)
        self.assertEqual(eng.players[0].score, 9)
        self.assertEqual(eng.gold_map, {})


class CropTest(unittest.TestCase):
    def test_crop_b_removes_followers(self):
        """怪圈效果 B：各玩家必须收回一名同类型随从（CAR 页 131）。"""
        eng = scripted_engine(
            [td.by_id("RStraight"), td.by_id("RStraight"), td.by_id("CRP-we"),
             td.by_id("M"), td.by_id("M")],
            ("crop",))
        eng.place(0, 1, 1)
        eng.deploy(KIND_ROAD, 0)
        eng.players[0].meeples_left = 7
        eng.players[1].meeples_left = 7
        place_at(eng, td.by_id("RStraight"), -1, 0, 1)   # 西侧南北路（蓝用）
        eng.deploy(KIND_ROAD, 0)
        place_at(eng, td.by_id("CRP-we"), 1, 1, 1)       # 棍圈=路（红放）
        eng.skip_deploy()
        self.assertEqual(eng.phase, "crop")
        eng.crop_choose("B")
        # 左家先：蓝收回
        self.assertEqual(eng.crop["order"][0], 1)
        opts = eng.crop_options()
        self.assertTrue(opts)
        eng.crop_act(opts[0]["node"])
        self.assertEqual(eng.players[1].meeples_left, 7)   # 7-1+1
        # 轮到红：同样收回
        opts = eng.crop_options()
        self.assertTrue(opts)
        eng.crop_act(opts[0]["node"])
        self.assertEqual(eng.players[0].meeples_left, 8)
        self.assertIsNone(eng.crop)


class RobberTest(unittest.TestCase):
    def test_robber_steals_half(self):
        """强盗上轨道：他人得分时偷走一半向上取整（CAR 页 187）。"""
        eng = scripted_engine(
            [td.by_id("RStraight"), td.by_id("RBR-ns"), td.by_id("RStraight"),
             td.by_id("RT")],
            ("robbers",))
        eng.place(0, 1, 1)
        eng.deploy(KIND_ROAD, 0)          # 蓝随从上路
        place_at(eng, td.by_id("RBR-ns"), 1, 0, 0)    # 强盗牌（东侧）
        eng.skip_deploy()
        self.assertEqual(eng.phase, "robber")         # 结算后进入强盗阶段
        # 蓝（放置者）先：红有随从、红分 0 → 蓝强盗上 0 格
        self.assertIn(0, eng.robber_options())
        eng.robber_place(0)
        eng.robber_place(None)            # 轮到红：放弃
        self.assertEqual(eng.robbers, {"蓝": 0})
        self.assertEqual(eng.phase, "place")
        place_at(eng, td.by_id("RStraight"), 0, 2, 1)
        eng.skip_deploy()
        place_at(eng, td.by_id("RT"), 0, 3, 1)        # 收口：4 牌路
        eng.skip_deploy()
        self.assertEqual(eng.players[0].score, 4)     # 红 4 分（随从在路）
        self.assertEqual(eng.players[1].score, 2)     # 蓝 (4+1)//2 = 2
        self.assertEqual(eng.robbers, {})             # 强盗回供给


class BesiegersTest(unittest.TestCase):
    def test_besieged_city_scores_one_per_tile(self):
        """被围城完成只按 1 分/牌（CAR 页 121）。"""
        eng = scripted_engine(
            [td.by_id("BES-NE"), td.by_id("C1s"), td.by_id("C1s"),
             td.by_id("M")], ("besiegers",))
        place_at(eng, td.by_id("BES-NE"), 0, -1, 0)   # 北东两向城口
        eng.deploy(KIND_CITY, 0)
        place_at(eng, td.by_id("C1s"), 1, -1, 3)      # 东口合拢
        eng.skip_deploy()
        place_at(eng, td.by_id("C1s"), 0, -2, 2)      # 北口合拢
        eng.skip_deploy()
        # 3 牌被围城 ×1 分（未被围本应 6 分）
        self.assertEqual(eng.players[0].score, 3)

    def test_escape_returns_knight(self):
        """被围城骑士可经邻格修道院脱困（CAR 页 122）。"""
        eng = scripted_engine(
            [td.by_id("BES-NWE"), td.by_id("M")], ("besiegers",))
        place_at(eng, td.by_id("BES-NWE"), 0, -1, 0)  # 城{N,W,E}
        eng.deploy(KIND_CITY, 0)
        place_at(eng, td.by_id("M"), -1, 0, 0)        # 西侧修道院（斜邻围攻牌）
        eng.skip_deploy()
        self.assertEqual(eng.phase, "escape")         # 回合末脱困询问
        opts = eng.escape_options()
        self.assertTrue(opts)
        eng.escape_move(opts[0])
        self.assertEqual(eng.players[0].meeples_left, 7)   # 6+1


class PhantomTest(unittest.TestCase):
    def test_phantom_second_follower(self):
        """幽灵可作第二随从部署到同牌另一特征（CAR 页 172）。"""
        eng = scripted_engine([td.by_id("RBR-T")] + [td.by_id("M")] * 3,
                              ("phantom",))
        eng.current_tile = td.by_id("RBR-T")
        eng.phase = "place"
        assert (0, 1, 2) in eng.legal_placements()
        eng.place(0, 1, 2)        # 丁字牌北路接起始南路
        eng.deploy(KIND_ROAD, 2)  # 普通随从上北支（转位后朝南接起始）
        self.assertEqual(eng.phase, "deploy")
        self.assertTrue(eng._phantom_step)
        opts = eng.deploy_options()
        self.assertTrue(opts)     # 东西分支空着
        o = opts[0]
        eng.deploy(o["kind"], o["seg"], pos=o.get("pos"), phantom=True)
        self.assertEqual(eng.players[0].phantom_left, 0)
        # 北支+起始南路即刻完成 2 牌路：普通随从归还，幽灵仍在场
        self.assertEqual(eng.players[0].score, 2)
        self.assertEqual(eng.players[0].meeples_left, 7)
        self.assertEqual(eng.phase, "place")


class FestivalTest(unittest.TestCase):
    def test_festival_returns_figure(self):
        """节日牌可收回场上任一己方图元，本回合不再部署（CAR 页 140）。"""
        eng = scripted_engine(
            [td.by_id("RStraight"), td.by_id("M"), td.by_id("FES-manor")] +
            [td.by_id("M")] * 3, ("festival",))
        eng.place(0, 1, 1)
        eng.deploy(KIND_ROAD, 0)
        place_at(eng, td.by_id("M"), 1, 0, 0)            # 蓝垫全田
        eng.skip_deploy()
        place_at(eng, td.by_id("FES-manor"), -1, 0, 1)   # 红放节日牌
        self.assertEqual(eng.phase, "deploy")
        opts = eng.festival_options()
        self.assertTrue(any(o["fig"] == "meeple" for o in opts))
        target = next(o for o in opts if o["fig"] == "meeple")
        eng.festival_return(target)
        self.assertEqual(eng.players[0].meeples_left, 7)   # 6+1
        # 收回即结束部署机会，直接进入下家回合
        self.assertEqual(eng.phase, "place")


if __name__ == "__main__":
    unittest.main()
