# -*- coding: utf-8 -*-
"""卡卡颂规则引擎：放置 / 米宝部署 / 完成检测 / 计分 / 终局。

纯状态对象，UI、AI、联机共用（主机权威模式）。

回合流程（CAR 基础规则）：
  1. 必须放置一张抽到的地牌（边匹配；无法放置且全员同意则弃牌重抽）
  2. 可选：从供给部署 1 个米宝到刚放的牌上（目标特征不得已有任何米宝）
  3. 立即结算本次放置完成的道路/城市/修道院（多数者得分，平局全得，米宝归还）

计分口径（CAR v7.4）：
  - 道路 1 分/牌；城市 2 分/牌 + 2 分/旗帜；修道院 9 分
  - 终局：未完成道路 1/牌；未完成城市 1/(牌+旗帜)；未完成修道院 1/(自身+邻格)
  - 农场（第三版）：多数农夫者各得 3 分 × 毗邻完成城市数；一城可被多农场计
"""
from __future__ import annotations

import random
from typing import Dict, List, Optional, Set, Tuple

from .board import Board, KIND_CITY, KIND_FARM, KIND_MON, KIND_ROAD, Node
from .models import (
    EDGE_DELTAS,
    N, E, S, W,
    OPPOSITE,
    PlacedTile,
    Player,
    ScoreEvent,
    Terrain,
    TileDef,
    meeple_majority,
)
from . import tile_data

PLAYER_COLORS = ["红", "蓝", "绿", "黄", "黑", "灰"]
COLOR_HEX = {"红": "#d64545", "蓝": "#4a6fd4", "绿": "#3f9d4f",
             "黄": "#d8b024", "黑": "#3a3a3a", "灰": "#9a9a9a"}


class CarcassonneEngine:
    """一局游戏的权威状态与规则实现。"""

    def __init__(self, player_specs: List[dict], seed: Optional[int] = None,
                 expansions: Optional[List[str]] = None):
        """player_specs: [{"name": str, "is_ai": bool, "ai_level": str}, ...] 2-6 人。

        expansions: 已启用扩展列表（当前支持 "inns" = 客栈与大教堂）。
        未启用时行为与基础版完全一致。
        """
        assert 2 <= len(player_specs) <= 6
        self.expansions = list(expansions or [])
        self.rng = random.Random(seed)
        self.board = Board()
        self.players: List[Player] = []
        for i, spec in enumerate(player_specs):
            self.players.append(Player(
                idx=i,
                name=spec.get("name") or PLAYER_COLORS[i],
                color=PLAYER_COLORS[i],
                is_ai=spec.get("is_ai", False),
                ai_level=spec.get("ai_level", "normal"),
            ))

        self.deck: List[TileDef] = tile_data.build_deck(self.expansions)
        if "inns" in self.expansions:
            for p in self.players:
                p.big_meeples_left = 1
        if "traders" in self.expansions:
            for p in self.players:
                p.builder_left = 1
                p.pig_left = 1
        if "abbey" in self.expansions:
            for p in self.players:
                p.mayor_left = 1
                p.barn_left = 1
                p.wagon_left = 1
        if "bcb" in self.expansions:
            nfig = 2 if len(self.players) >= 5 else 3
            for p in self.players:
                p.bridges_left = nfig
                p.castles_left = nfig
        if "phantom" in self.expansions:
            for p in self.players:
                p.phantom_left = 1
        if "tunnel" in self.expansions:
            npairs = (3 if len(self.players) == 2
                      else 2 if len(self.players) == 3 else 1)
            for p in self.players:
                p.tunnels_left = npairs
        if "tower" in self.expansions:
            npieces = {2: 10, 3: 9, 4: 7, 5: 6, 6: 5}[len(self.players)]
            for p in self.players:
                p.towers_left = npieces
        if "hillsheep" in self.expansions:
            for p in self.players:
                p.shepherd_left = 1
        self.castles: List[Dict[str, object]] = []   # BCB 城堡
        self.bazaar: Optional[Dict[str, object]] = None
        self._built_bridge = False
        self._needed_bridge: Dict[Tuple[int, int, int], Tuple[Tuple[int, int], int]] = {}
        self._bazaar_ignore = False
        self._pending_bazaar = False
        self._castle_queue: List[Node] = []
        self._extra_turn = False   # T&B 建造者双回合（第二部分消耗）
        # M20 迷你扩展状态
        self.mage: Optional[Node] = None            # 法师所在段节点
        self.witch: Optional[Node] = None           # 女巫所在段节点
        self.robbers: Dict[str, int] = {}           # 色名 -> 计分轨道格
        self.gold_map: Dict[Tuple[int, int], int] = {}  # 金块落牌 -> 数量
        self.crop: Optional[Dict[str, object]] = None    # 麦田怪圈阶段状态
        self.robber_phase: Optional[Dict[str, object]] = None
        self.tunnel_open: Dict[str, Node] = {}      # 色名 -> 已占未接通隧道口
        self._mini_queue: List[str] = []   # 放置后/结算后的迷你阶段队列
        self._phantom_step = False         # 幽灵第二随从步骤中
        self._phantom_done = False         # 本回合幽灵机会已给出
        self._escape_offered = False       # 本回合脱困机会已给出
        self._crop_offered = False         # 本回合怪圈已触发
        self._robber_offered = False       # 本回合强盗已触发
        # M21 塔：塔列表 / 人质 / 两步建塔抓人 / 赎金（每回合一次）
        self.towers: List[Dict[str, object]] = []   # {pos, height, top}
        self.hostages: List[Dict[str, object]] = []  # {owner, captor, size, ph}
        self._tower_pending: Optional[Tuple[int, int]] = None
        self._ransom_used = False
        # M21 命运之轮：猪位置 / 王冠位（扇区 -> [随从]）/ 瘟疫阶段
        self.wheel_pig = 0            # 0..5（顺时针，0=幸运）
        self.crowns: Dict[int, List[Dict[str, object]]] = {i: [] for i in range(6)}
        self.plague: Optional[Dict[str, object]] = None
        # M21 山丘与羊：山丘牌位 / 牧羊人 / 羊袋（0=狼）
        self.hills: Set[Tuple[int, int]] = set()
        self.shepherds: List[Dict[str, object]] = []  # {color, node, tokens}
        # 羊袋只在启用时初始化（避免无条件消耗 rng 改变牌堆次序）
        self.sheep_bag: List[int] = []
        if "hillsheep" in self.expansions:
            self.sheep_bag = ([1] * 4 + [2] * 5 + [3] * 5
                              + [4] * 2 + [0] * 2)
            self.rng.shuffle(self.sheep_bag)
        self._shepherd_pending: List[Node] = []   # 本放置触发的牧羊行动草场根
        # P&D：仙女（中立，绑定某跟随者）与龙（中立，共享）
        self.fairy = {"pos": None, "node": None, "owner": None}
        self.dragon = {"pos": None, "active": False, "steps_left": 0,
                       "decider": 0, "visited": []}
        self._volcano_turn = False
        self._aside_tiles: List[TileDef] = []   # P&D：龙激活前搁置的龙牌
        # M18 国王与强盗男爵：持有者 + 纪录（只随玩家完成更新；CAR 页 70）
        self.king = {"holder": None, "size": 0}
        self.robber = {"holder": None, "size": 0}
        # M18 教堂与异端：挑战对（shrine 节点 ↔ monastery 节点；CAR 页 84-86）
        self.challenges: List[Dict[str, Node]] = []
        # M18 伯爵城：四区等候随从 [color, fig] + 伯爵所在区（CAR 页 72-77）
        self.count = {
            "quarters": {"castle": [], "market": [],
                         "blacksmith": [], "cathedral": []},
            "count_pos": "castle",
        }
        self.redeploy: Optional[Dict[str, object]] = None   # 重部署回合状态
        self._count_queue: List[Node] = []
        self._placer_idx = 0
        self._count_trigger = False
        self._placer_scored = False
        self._river_volcano = False
        self.rng.shuffle(self.deck)
        self.turn_idx = 0
        # M18 河流 II / 伯爵城：起始布置（CAR 页 72/79）
        self._river_on = "river" in self.expansions
        self.river_pile: List[TileDef] = []
        if "count" in self.expansions:
            for c, r, cc in tile_data.CC_BLOCK:
                self.board.add_tile(PlacedTile(cc.tile_id, c, r, 0, -1), cc)
            self._count_block: Set[Tuple[int, int]] = {
                (c, r) for c, r, _ in tile_data.CC_BLOCK}
            self._count_city_root = self.board.find((0, 0, KIND_CITY, 0))
        else:
            self._count_block = set()
            self._count_city_root = None
        if self._river_on:
            self.river_pile = tile_data.river_deck(self.expansions, self.rng)
            spring = tile_data.by_id("RI-Spring")
            if "count" in self.expansions:
                # 泉源接伯爵城水边（(3,0) 北），河流引离城去（CAR 脚注 206）
                self.board.add_tile(PlacedTile(spring.tile_id, 3, -1, 0, -1),
                                    spring)
            else:
                self.board.add_tile(PlacedTile(spring.tile_id, 0, 0, 0, -1),
                                    spring)
            self.phase = "river"          # river / place / deploy / over
        else:
            if "count" not in self.expansions:
                # 伯爵城启用时不放修道院起始牌（CAR 页 72）
                start = tile_data.start_tile(self.expansions)
                self.board.add_tile(PlacedTile(start.tile_id, 0, 0, 0, -1),
                                    start)
            self.phase = "place"          # place / deploy / over
        self.current_tile: Optional[TileDef] = None
        self.placed_pos: Optional[Tuple[int, int]] = None   # 本回合放置位置
        self.pending_completions: List[Node] = []           # 待结算特征根
        self.events: List[ScoreEvent] = []                  # 全局计分流水
        self.log_lines: List[str] = []
        self.game_over = False
        self.round_count = 0
        self._final_done = False
        self._draw_tile()

    # ------------------------------------------------------------ 内部工具

    def _draw_tile(self) -> None:
        self.current_tile = None
        # M18 河流阶段：从河流序列摸牌（岔流→洗匀→火山湖收尾）
        if self.phase == "river" and self.river_pile:
            self.current_tile = self.river_pile.pop(0)
            self.pending_completions = []
            self.placed_pos = None
            return
        if self.phase == "river" and not self.river_pile:
            # 河流序列耗尽（火山湖已放置或被弃）→ 回到正常对局
            self._river_on = False
            self.phase = "place"
        while self.deck:
            t = self.deck.pop()
            # P&D：龙未激活前抽到龙牌 → 搁置一边，重抽（CAR 规则）
            if ("pd" in self.expansions and t.dragon_tile
                    and self.dragon.get("pos") is None):
                self._aside_tiles.append(t)
                continue
            self.current_tile = t
            if "wheel" in self.expansions and t.fate:
                self._wheel_event(int(t.fate))
            break
        if self.current_tile is None:
            # 火山已出 → 搁置的龙牌混回牌堆继续（CAR 规则）
            if self._aside_tiles and self.dragon.get("pos") is not None:
                self.deck.extend(self._aside_tiles)
                self.rng.shuffle(self.deck)
                self._aside_tiles = []
                return self._draw_tile()
            self.phase = "over"
            self.game_over = True
        self.pending_completions = []
        self.placed_pos = None

    def _log(self, line: str) -> None:
        self.log_lines.append(line)

    def current_player(self) -> Player:
        return self.players[self.turn_idx]

    def tiles_left(self) -> int:
        return (len(self.deck) + len(self.river_pile)
                + (1 if self.phase in ("place", "river") and self.current_tile
                   else 0))

    # ------------------------------------------------------------ 放置

    def legal_placements(self) -> List[Tuple[int, int, int]]:
        """当前牌全部合法放置 (x, y, rot) 列表。"""
        tile = self.current_tile
        if tile is None or self.phase not in ("place", "river"):
            return []
        self._needed_bridge = {}
        cells: Set[Tuple[int, int]] = set()
        for x, y in list(self.board.tiles):
            for side in range(4):
                dx, dy = EDGE_DELTAS[side]
                npos = (x + dx, y + dy)
                if not self.board.has(*npos):
                    cells.add(npos)
        out: List[Tuple[int, int, int]] = []
        for nx, ny in sorted(cells):
            # S&H：教堂不得邻接 ≥2 修道院；修道院/修道院牌不得邻接 ≥2 教堂
            if not self._shrine_place_ok(tile, nx, ny):
                continue
            for rot in range(4):
                # A&M：修道院牌可放任意相邻空格（无需边匹配）
                if tile.abbey or self._fits(tile, nx, ny, rot):
                    if self.phase == "river" and not self._river_contact_ok(
                            tile, nx, ny, rot):
                        continue
                    out.append((nx, ny, rot))
                    continue
                # BCB：恰好一座木桥即可使本放置合法
                if ("bcb" in self.expansions
                        and self.current_player().bridges_left > 0
                        and self.phase == "place"):
                    fix = self._bridge_fix(tile, nx, ny, rot)
                    if fix is not None:
                        out.append((nx, ny, rot))
                        self._needed_bridge[(nx, ny, rot)] = fix
        return out

    def _shrine_place_ok(self, tile: TileDef, x: int, y: int) -> bool:
        """教堂/修道院放置的邻接限制（CAR 页 84：不得同时邻接多个对手建筑）。"""
        is_shrine = bool(tile.shrine)
        is_cloister = (not is_shrine) and (
            tile.center.value == 1 or tile.abbey)
        if not (is_shrine or is_cloister):
            return True
        mon_n = shr_n = 0
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if not (dx or dy):
                    continue
                pos = (x + dx, y + dy)
                if pos not in self.board.tiles:
                    continue
                d = self.board.defs[pos]
                if d.shrine:
                    shr_n += 1
                elif self.board.monastery_pos(pos):
                    mon_n += 1
        if is_shrine and mon_n >= 2:
            return False
        if is_cloister and shr_n >= 2:
            return False
        return True

    def _river_contact_ok(self, tile: TileDef, x: int, y: int, rot: int) -> bool:
        """河流牌放置：与已放置水边恰好接触一处（CAR 页 80 两条例外）。"""
        contacts = 0
        for side in range(4):
            if tile.edge(side, rot) is not Terrain.WATER:
                continue
            npos = self.board.neighbor(x, y, side)
            if npos is None:
                continue
            nb = self.board.defs[npos].edge(OPPOSITE[side],
                                            self.board.tiles[npos].rot)
            if nb is Terrain.WATER:
                contacts += 1
        return contacts == 1

    def _fits(self, tile: TileDef, x: int, y: int, rot: int) -> bool:
        """至少一边邻接、所有相邻边地形匹配（角对角不算连接）。"""
        touches = False
        for side in range(4):
            npos = self.board.neighbor(x, y, side)
            my_terr = tile.edge(side, rot)
            if npos is None:
                continue
            touches = True
            nb_terr = self.board.matching_edge(npos, OPPOSITE[side])
            if my_terr != nb_terr:
                return False
        return touches

    def _bridge_fix(self, tile: TileDef, x: int, y: int,
                    rot: int) -> Optional[Tuple[Tuple[int, int], int]]:
        """若恰好一座木桥能让本放置合法，返回 (桥位, 轴向 0=NS/1=EW)。"""
        mismatches = []
        touches = False
        for side in range(4):
            npos = self.board.neighbor(x, y, side)
            my = tile.edge(side, rot)
            if npos is None:
                continue
            touches = True
            nb = self.board.matching_edge(npos, OPPOSITE[side])
            if my != nb:
                mismatches.append((side, my, npos, nb))
        if not touches or not mismatches:
            return None
        cand = None
        for side, my, npos, nb in mismatches:
            if my is Terrain.ROAD and nb is Terrain.FIELD:
                bpos, edge = npos, OPPOSITE[side]
            elif my is Terrain.FIELD and nb is Terrain.ROAD:
                bpos, edge = (x, y), side
            else:
                return None
            axis = 0 if edge in (N, S) else 1
            if cand is None:
                cand = (bpos, axis)
            elif cand != (bpos, axis):
                return None
        if cand is None:
            return None
        bpos, axis = cand
        ends = (N, S) if axis == 0 else (E, W)
        if bpos == (x, y):
            if any(tile.edge(e, rot) is not Terrain.FIELD for e in ends):
                return None
            if (x, y) in self.board.bridges:
                return None
            for e in ends:
                npos = self.board.neighbor(x, y, e)
                if npos is None:
                    continue
                if self.board.matching_edge(npos, OPPOSITE[e]) is not Terrain.ROAD:
                    return None
        else:
            if not self.board.can_build_bridge(bpos, axis):
                return None
        return cand

    def can_place_anywhere(self) -> bool:
        return bool(self.legal_placements())

    def place(self, x: int, y: int, rot: int) -> None:
        """放置当前牌。之后进入 deploy 阶段（或自动跳过）。"""
        tile = self.current_tile
        assert tile is not None and self.phase in ("place", "river")
        assert (x, y, rot) in self.legal_placements(), "非法放置"
        player = self.current_player()
        self._placer_idx = self.turn_idx
        self._count_trigger = False
        self._placer_scored = False

        need = None
        self._built_bridge = False
        if "bcb" in self.expansions:
            need = self._needed_bridge.get((x, y, rot))
            # 兜底仅限需要桥才合法的放置；修道院牌无视边匹配，若其两侧
            # 恰为路会误算出一座桥（CAR 脚注 292：建桥是玩家主动选择）
            if need is None and not tile.abbey:
                need = self._bridge_fix(tile, x, y, rot)
            if need is not None and need[0] != (x, y):
                self.build_bridge(need[0], need[1])
                need = None
        placed = PlacedTile(tile.tile_id, x, y, rot, player.idx)
        self.board.add_tile(placed, tile)
        self.placed_pos = (x, y)
        self._pending_bazaar = bool(tile.bazaar and "bcb" in self.expansions
                                    and not self._bazaar_ignore)
        if need is not None:
            self.build_bridge(need[0], need[1])
        self.phase = "deploy"

        # 完成检测：本牌各段所在特征 + 周围 8 格的修道院
        pending: List[Node] = []
        for kind, n_segs in ((KIND_CITY, len(tile.cities)), (KIND_ROAD, len(tile.roads))):
            for i in range(n_segs):
                node = (x, y, kind, i)
                meta = self.board.meta(node)
                if meta.complete and not meta.scored:
                    pending.append(self.board.find(node))
        if tile.center.value == 1 and self.board.monastery_complete((x, y)):
            pending.append(self.board.find((x, y, KIND_MON, 0)))
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if not (dx or dy):
                    continue
                pos = (x + dx, y + dy)
                if pos in self.board.tiles and self.board.monastery_pos(pos):
                    node = (pos[0], pos[1], KIND_MON, 0)
                    if self.board.monastery_complete(pos):
                        pending.append(self.board.find(node))
        self.pending_completions = list(dict.fromkeys(pending))

        # M20 迷你扩展：放置后前置阶段（金块落位 → 法师女巫 → 隧道令牌）
        self._mini_queue = []
        self._phantom_step = False
        self._phantom_done = False
        self._escape_offered = False
        self._crop_offered = False
        self._robber_offered = False
        self._ransom_used = False
        self._tower_pending = None
        self.plague = None
        # M21 山丘：先从牌堆抽一张暗置垫在山丘下（不看、不计特征；CAR 页 104）
        if tile.hill and self.deck:
            under = self.deck.pop()
            self._log("⛰ %s 抽到山丘——一张暗牌垫底" % player.name)
            _ = under
        if tile.gold and "goldmines" in self.expansions:
            self._mini_queue.append("gold")
        if "magewitch" in self.expansions and (
                tile.mage
                or (self.mage is not None and self.witch is not None
                    and self.board.find(self.mage)
                    == self.board.find(self.witch))):
            self._mini_queue.append("magewitch")
        if ("tunnel" in self.expansions
                and self.current_player().tunnels_left > 0
                and self.tunnel_options()):
            self._mini_queue.append("tunnel")
        if self._mini_queue:
            self._advance_mini()
            return
        # M21 山丘与羊：山丘登记；本牌延伸己方牧羊人草场 → 部署后牧羊行动
        if tile.hill:
            self.hills.add((x, y))
        self._shepherd_pending = []
        if "hillsheep" in self.expansions:
            for i in range(len(tile.farms)):
                node = (x, y, KIND_FARM, i)
                root = self.board.find(node)
                for sh in self.shepherds:
                    if sh["color"] == player.color                             and self.board.find(sh["node"]) == root:
                        self._shepherd_pending.append(root)
                        break

        # T&B：若本牌延伸了含己方建造者的城/路 → 该玩家获得双回合第二部分
        if "traders" in self.expansions:
            extra = False
            for kind, n_segs in ((KIND_CITY, len(tile.cities)),
                                 (KIND_ROAD, len(tile.roads))):
                for i in range(n_segs):
                    meta = self.board.meta((x, y, kind, i))
                    if meta.builders.get(player.color, 0) > 0:
                        extra = True
                        break
                if extra:
                    break
            self._extra_turn = extra
        if self._river_on and tile.volcano:
            # 河流阶段的火山湖（末张）：龙降临湖面、本回合不能部署、
            # 放置者立即再摸一张普通牌开始正常对局（CAR 页 80 脚注 244-245）
            self.dragon["pos"] = (x, y)
            self.dragon["active"] = True
            self._river_volcano = True
            self._log("🌋 %s 放置火山湖——龙降临 (%d,%d)，河流阶段结束"
                      % (player.name, x, y))
            if "count" in self.expansions:
                self._count_queue = list(self.pending_completions)
                self._count_advance()
                return
            events = self._score_completions()
            self.events.extend(events)
            self._finish_turn()
            return
        if "pd" in self.expansions:
            self._volcano_turn = bool(tile.volcano)
            if tile.volcano:
                self.dragon["pos"] = (x, y)
                if not self.dragon["active"]:
                    self.dragon["active"] = True
                self._log("🌋 %s 放置火山牌——龙降临 (%d,%d)" % (player.name, x, y))
        self._log("%s 放置 %s @(%d,%d) rot=%d" % (player.name, tile.tile_id, x, y, rot))

    def discard_and_redraw(self) -> None:
        """无法合法放置时，经全员同意弃牌重抽（CAR 规则；河流阶段同）。"""
        assert self.phase in ("place", "river") and self.current_tile is not None
        self._log("牌 %s 无法放置，弃牌重抽" % self.current_tile.tile_id)
        self._draw_tile()

    # ------------------------------------------------------------ 米宝

    def shepherd_options(self) -> List[Dict[str, object]]:
        """牧羊人部署选项：刚放牌上无其他牧羊人的草场段（幽灵步骤除外）。"""
        if self.phase != "deploy" or self.placed_pos is None                 or self.current_tile is None                 or self._phantom_step                 or self.current_player().shepherd_left <= 0                 or "hillsheep" not in self.expansions:
            return []
        x, y = self.placed_pos
        tile = self.current_tile
        rot = self.board.tiles[(x, y)].rot
        out: List[Dict[str, object]] = []
        for i, (edges, _adj) in enumerate(tile.rotated_farms(rot)):
            node = (x, y, KIND_FARM, i)
            root = self.board.find(node)
            if any(self.board.find(s["node"]) == root for s in self.shepherds):
                continue
            out.append({"kind": "shepherd", "seg": i,
                        "label": "🧑‍🌾 牧羊人（草场段 %d）" % i,
                        "node": node, "big": False})
        return out

    def deploy_shepherd(self, seg: int) -> None:
        """部署牧羊人（代替随从）并立即抽一张羊/狼。"""
        assert self.phase == "deploy", "当前不是部署阶段"
        opts = [o for o in self.shepherd_options() if o["seg"] == seg]
        assert opts, "非法牧羊人部署"
        player = self.current_player()
        player.shepherd_left -= 1
        node = opts[0]["node"]
        sh = {"color": player.color, "node": node, "tokens": []}
        self.shepherds.append(sh)
        self._log("🧑‍🌾 %s 部署牧羊人 @(%d,%d)#%d"
                  % (player.name, node[0], node[1], node[3]))
        self._draw_sheep_token(sh)
        self._after_deploy()

    def _draw_sheep_token(self, sh: Dict[str, object]) -> None:
        """牧羊人抽一张羊/狼：狼则全草场羊群散、牧羊人回家。"""
        token = self.sheep_bag.pop()
        if token > 0:
            sh["tokens"].append(token)
            self._log("🐑 %s 的牧羊人抽到 %d 只羊（共 %d）"
                      % (self._player_by_color(sh["color"]).name,
                         token, sum(sh["tokens"])))
        else:
            self.sheep_bag.append(0)
            self._scatter_flock(sh)
            self._log("🐺 狼来了！%s 的羊群散了" %
                      self._player_by_color(sh["color"]).name)

    def _field_shepherds(self, root: Node) -> List[Dict[str, object]]:
        return [s for s in self.shepherds
                if self.board.find(s["node"]) == root]

    def _scatter_flock(self, trigger: Dict[str, object]) -> None:
        """狼：全草场羊令牌回袋、全部牧羊人回家（不得分）。"""
        root = self.board.find(trigger["node"])
        for s in self._field_shepherds(root):
            self.sheep_bag.extend(s["tokens"])
            s["tokens"] = []
            self.shepherds.remove(s)
            self._player_by_color(s["color"]).shepherd_left += 1

    # 牧羊行动（展开羊群 / 赶羊入圈）
    def shepherd_pending_action(self) -> Optional[Node]:
        """本放置触发的牧羊行动草场（须仍有己方牧羊人在场）。"""
        for root in self._shepherd_pending:
            me = self.current_player().color
            for s in self._field_shepherds(root):
                if s["color"] == me:
                    return root
        return None

    def shepherd_act(self, expand: bool) -> None:
        """牧羊行动：抽卡扩群 or 赶羊入圈（同草场全体牧羊人均分/均失）。"""
        assert self.phase == "shepherd", "当前不是牧羊行动阶段"
        root = self.shepherd_pending_action()
        assert root is not None, "无待行动牧羊人"
        me = self.current_player().color
        mine = next(s for s in self._field_shepherds(root) if s["color"] == me)
        if expand:
            self._log("🐑 %s 选择扩群" % self._player_by_color(me).name)
            self._draw_sheep_token(mine)
        else:
            total = sum(sum(s["tokens"]) for s in self._field_shepherds(root))
            for s in self._field_shepherds(root):
                self._player_by_color(s["color"]).score += total
            for s in list(self._field_shepherds(root)):
                self.sheep_bag.extend(s["tokens"])
                s["tokens"] = []
                self.shepherds.remove(s)
                self._player_by_color(s["color"]).shepherd_left += 1
            self._log("🐏 %s 赶羊入圈：全草场 %d 只 → 各牧羊人 + %d 分"
                      % (self._player_by_color(me).name, total, total))
        self._shepherd_pending = []
        self._after_deploy()

    def deploy_options(self) -> List[Dict[str, object]]:
        """本回合刚放牌上可部署的段列表（特征上无任何米宝）。"""
        if self.phase != "deploy" or self.placed_pos is None or self.current_tile is None:
            return []
        player = self.current_player()
        if player.meeples_left <= 0 and player.big_meeples_left <= 0:
            return self.shepherd_options()   # 无随从仍可部署牧羊人
        x, y = self.placed_pos
        tile = self.current_tile
        rot = self.board.tiles[(x, y)].rot
        options: List[Dict[str, object]] = []
        # M21 山丘与羊：牧羊人部署（代替随从；随时可选）
        options.extend(self.shepherd_options())
        # M21 命运之轮：空闲王冠位（代替随从上架）
        options.extend(self.crown_options())
        # P&D：火山回合不能部署任何图元，仅可移动仙女
        if self._volcano_turn:
            return self._fairy_options(options)
        big_ok = player.big_meeples_left > 0

        def add(kind: str, i: int, label: str, node) -> None:
            options.append({"kind": kind, "seg": i, "label": label,
                            "node": node, "big": False})
            if big_ok:
                options.append({"kind": kind, "seg": i,
                                "label": label.replace("·", "（大）·", 1),
                                "node": node, "big": True})

        for i, (edges, _p, _c) in enumerate(tile.rotated_cities(rot)):
            node = (x, y, KIND_CITY, i)
            if not self.board.meta(node).meeples:
                add(KIND_CITY, i, "骑士·城市段", node)
        for i, (_edges, _inn) in enumerate(tile.rotated_roads(rot)):
            node = (x, y, KIND_ROAD, i)
            if not self.board.meta(node).meeples:
                add(KIND_ROAD, i, "强盗·道路", node)
        for i, (_edges, _adj) in enumerate(tile.rotated_farms(rot)):
            node = (x, y, KIND_FARM, i)
            if not self.board.meta(node).meeples:
                add(KIND_FARM, i, "农夫·农场", node)
        if tile.center.value == 1:
            node = (x, y, KIND_MON, 0)
            if not self.board.meta(node).meeples:
                add(KIND_MON, 0, "僧侣·修道院", node)

        # A&M：市长（城段需无任何随从）；马车（城/路段需无随从）；粮仓（农场段需无随从）
        if "abbey" in self.expansions:
            if tile.mayor and player.mayor_left > 0:
                for i, (edges, _p, _c) in enumerate(tile.rotated_cities(rot)):
                    node = (x, y, KIND_CITY, i)
                    if not self.board.meta(node).meeples:
                        options.append({"kind": "mayor", "seg": i,
                                        "label": "市长·城市段", "node": node,
                                        "big": False})
            if tile.wagon and player.wagon_left > 0:
                for i, (edges, _inn) in enumerate(tile.rotated_roads(rot)):
                    node = (x, y, KIND_ROAD, i)
                    if not self.board.meta(node).meeples:
                        options.append({"kind": "wagon", "seg": i,
                                        "label": "马车·道路", "node": node,
                                        "big": False})
                for i, (edges, _p, _c) in enumerate(tile.rotated_cities(rot)):
                    node = (x, y, KIND_CITY, i)
                    if not self.board.meta(node).meeples:
                        options.append({"kind": "wagon", "seg": i,
                                        "label": "马车·城市段", "node": node,
                                        "big": False})
            if tile.barn and player.barn_left > 0:
                for i, (_fedges, _adj) in enumerate(tile.rotated_farms(rot)):
                    node = (x, y, KIND_FARM, i)
                    if not self.board.meta(node).meeples:
                        options.append({"kind": "barn", "seg": i,
                                        "label": "粮仓·农场（立即结算）",
                                        "node": node, "big": False})

        # P&D：公主——移走所延伸城中的一个骑士（任意玩家）
        if tile.princess:
            for kind in (KIND_CITY,):
                for i in range(len(tile.cities)):
                    node = (x, y, kind, i)
                    meta = self.board.meta(node)
                    for victim_node, color, size in meta.meeple_nodes:
                        options.append({"kind": "princess", "seg": i,
                                        "label": "公主·移走 %s 骑士" % color,
                                        "node": node, "big": False,
                                        "victim": victim_node,
                                        "victim_color": color})
                    if meta.meeples:
                        break   # 只在该牌第一个含骑士的城段提供
        # P&D：传送门——随从可部署到场上任意合法空段
        if tile.portal:
            self._portal_options(options, player, big_ok)
            return options
        # T&B：建造者（需该段所在城/路已有己方随从）与猪（农场已有己方农夫）
        if "traders" in self.expansions:
            if tile.builder and player.builder_left > 0:
                for kind in (KIND_CITY, KIND_ROAD):
                    n_segs = len(tile.cities) if kind == KIND_CITY else len(tile.roads)
                    for i in range(n_segs):
                        node = (x, y, kind, i)
                        meta = self.board.meta(node)
                        if meta.meeples.get(player.color, 0) > 0:
                            lbl = "建造者·%s" % ("城市段" if kind == KIND_CITY else "道路")
                            options.append({"kind": "builder", "seg": i,
                                            "label": lbl, "node": node,
                                            "big": False, "fig": "builder"})
            if tile.pig and player.pig_left > 0:
                for i, (_edges, _adj) in enumerate(tile.rotated_farms(rot)):
                    node = (x, y, KIND_FARM, i)
                    meta = self.board.meta(node)
                    if meta.meeples.get(player.color, 0) > 0:
                        options.append({"kind": "pig", "seg": i, "label": "猪·农场",
                                        "node": node, "big": False, "fig": "pig"})
        return options

    def deploy(self, kind: str, seg: int, big: bool = False,
               pos: Optional[Tuple[int, int]] = None,
               victim: Optional[Node] = None,
               victim_color: Optional[str] = None,
               phantom: bool = False) -> None:
        """通用部署入口：普通米宝直达，图元/仙女/公主路由到专用方法。"""
        assert self.phase == "deploy"
        if phantom:
            # M20 幽灵：第二随从（或本回合唯一随从），目标特征须无人占据
            assert self._phantom_step, "当前不是幽灵部署步骤"
            assert kind in (KIND_CITY, KIND_ROAD, KIND_FARM, KIND_MON), \
                "幽灵只能部署为普通随从"
            player = self.current_player()
            base = tuple(pos) if pos else self.placed_pos
            node = (base[0], base[1], kind, seg)
            assert not self.board.meta(node).meeples, "目标特征已有米宝"
            self.board.deploy_meeple(node, player.color, 1, phantom=True)
            player.phantom_left -= 1
            self._phantom_step = False
            self._log("👻 %s 部署幽灵（%s）" % (player.name, kind))
            self._after_deploy()
            return
        if kind == "shepherd":
            return self.deploy_shepherd(seg)
        if kind == "crown":
            player = self.current_player()
            assert player.meeples_left > 0, "没有可用米宝"
            sector, slot = divmod(seg, 2)
            assert self.WHEEL_SLOTS.get(sector) is not None, "非法王冠位"
            riders = self.crowns[sector]
            assert len(riders) <= slot, "该王冠位已被占用"
            riders.append({"color": player.color, "size": 1})
            player.meeples_left -= 1
            self._log("🎡 %s 的随从上架王冠位（%s）"
                      % (player.name, self.WHEEL_SECTORS[sector]))
            self._after_deploy()
            return
        if kind == "fairy":
            assert pos is not None, "仙女部署需坐标"
            return self.deploy_fairy(tuple(pos))
        if kind == "princess":
            if victim is None:
                opt = next((o for o in self.deploy_options()
                            if o["kind"] == "princess" and o["seg"] == seg),
                           None)
                assert opt is not None, "非法公主部署"
                victim, victim_color = opt["victim"], opt["victim_color"]
            return self.deploy_princess(tuple(victim), victim_color)
        if kind in ("mayor", "barn", "wagon", "builder", "pig"):
            opt = next((o for o in self.deploy_options()
                        if o["kind"] == kind and o["seg"] == seg
                        and bool(o.get("big")) == bool(big)
                        and (o.get("pos") or None) == (pos or None)), None)
            assert opt is not None, "非法%s部署" % kind
            if kind == "mayor":
                return self.deploy_mayor(seg)
            if kind == "barn":
                return self.deploy_barn(seg)
            if kind == "wagon":
                real = (KIND_CITY if opt["node"][2] == KIND_CITY
                        else KIND_ROAD)
                return self.deploy_wagon(real, seg)
            if kind == "builder":
                real = (KIND_CITY if opt["node"][2] == KIND_CITY
                        else KIND_ROAD)
                return self.deploy_builder(real, seg)
            return self.deploy_pig(KIND_FARM, seg)
        player = self.current_player()
        base = tuple(pos) if pos else self.placed_pos
        node = (base[0], base[1], kind, seg)
        self.board.deploy_meeple(node, player.color, size=2 if big else 1)
        if big:
            player.big_meeples_left -= 1
        else:
            player.meeples_left -= 1
        self._log("%s 部署%s米宝（%s）" % (player.name, "大型" if big else "", kind))
        if kind == KIND_MON:
            self._create_challenges(node)
        self._after_deploy()

    def _create_challenges(self, node: Node) -> None:
        """教堂 ↔ 修道院挑战（S&H，CAR 页 85）：部署后双方有随从即成对。"""
        pos = (node[0], node[1])
        here_shrine = self.board.defs[pos].shrine
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if not (dx or dy):
                    continue
                npos = (pos[0] + dx, pos[1] + dy)
                if npos not in self.board.tiles:
                    continue
                d = self.board.defs[npos]
                if d.shrine == here_shrine:
                    continue   # 教堂只与修道院成对（反之亦然）
                if not self.board.monastery_pos(npos):
                    continue
                other = (npos[0], npos[1], KIND_MON, 0)
                if not self.board.meta(other).meeples:
                    continue   # 对方须已有随从（僧侣/异端）
                pair = {"shrine": node if here_shrine else other,
                        "monastery": other if here_shrine else node}
                if pair not in self.challenges:
                    self.challenges.append(pair)
                    self._log("⚔️ 挑战成立：教堂 (%d,%d) ↔ 修道院 (%d,%d)"
                              % (pair["shrine"][0], pair["shrine"][1],
                                 pair["monastery"][0], pair["monastery"][1]))

    def _fairy_options(self, options: List[Dict[str, object]]) -> List[Dict[str, object]]:
        """仙女选项：移到己方任一跟随者所在牌（去重）。"""
        player = self.current_player()
        seen = set()
        for root in self.board.roots():
            meta = self.board._meta[root]
            for node, color, _size in meta.meeple_nodes:
                if color != player.color:
                    continue
                pos = (node[0], node[1])
                if pos in seen:
                    continue
                seen.add(pos)
                options.append({"kind": "fairy", "seg": node[3], "pos": pos,
                                "label": "仙女·保护 (%d,%d)" % pos,
                                "node": node, "big": False})
        return options

    def _portal_options(self, options: List[Dict[str, object]], player,
                        big_ok: bool) -> None:
        """传送门：扫描全场合法空段（不含刚放的牌、不含伯爵大城）。"""
        px, py = self.placed_pos
        for pos, d in self.board.defs.items():
            if pos == self.placed_pos:
                continue
            pt = self.board.tiles[pos]
            for i, (edges, _p, _c) in enumerate(d.rotated_cities(pt.rot)):
                node = (pos[0], pos[1], KIND_CITY, i)
                if self._count_city_root is not None and \
                        self.board.find(node) == self._count_city_root:
                    continue   # 随从不得经传送门进伯爵城（脚注 202）
                meta = self.board.meta(node)
                if meta.meeples or meta.complete:
                    continue
                options.append({"kind": KIND_CITY, "seg": i, "pos": pos,
                                "label": "传送门·骑士 (%d,%d)" % pos,
                                "node": node, "big": big_ok and
                                player.big_meeples_left > 0})
            for i, (_edges, _inn) in enumerate(d.rotated_roads(pt.rot)):
                node = (pos[0], pos[1], KIND_ROAD, i)
                meta = self.board.meta(node)
                if meta.meeples or meta.complete:
                    continue
                options.append({"kind": KIND_ROAD, "seg": i, "pos": pos,
                                "label": "传送门·强盗 (%d,%d)" % pos,
                                "node": node, "big": False})
            for i, (_fedges, _adj) in enumerate(d.rotated_farms(pt.rot)):
                node = (pos[0], pos[1], KIND_FARM, i)
                meta = self.board.meta(node)
                if meta.meeples:
                    continue
                options.append({"kind": KIND_FARM, "seg": i, "pos": pos,
                                "label": "传送门·农夫 (%d,%d)" % pos,
                                "node": node, "big": False})
            if d.center.value == 1 and not self.board.monastery_complete(pos):
                options.append({"kind": KIND_MON, "seg": 0, "pos": pos,
                                "label": "传送门·僧侣 (%d,%d)" % pos,
                                "node": node, "big": False})

    def _after_deploy(self) -> None:
        """部署完成后的分流：牧羊行动 → 龙牌 → 幽灵步骤 → 结算。"""
        tile = self.current_tile
        # M21 山丘与羊：本牌延伸己方牧羊人草场 → 先行动（脚注 317/318）
        if "hillsheep" in self.expansions \
                and self.shepherd_pending_action() is not None:
            self.phase = "shepherd"
            self._log("🧑‍🌾 %s 的羊群扩展——选择扩群或入圈"
                      % self.current_player().name)
            return
        if "pd" in self.expansions and tile is not None and tile.dragon_tile \
                and self.dragon.get("pos") is not None:
            self._start_dragon_phase()
            return
        if self._maybe_phantom_step():
            return
        self._resolve_turn()

    def _start_dragon_phase(self) -> None:
        """龙移动阶段：共 6 步，从当前玩家开始轮流各移 1 步。"""
        self.dragon.update({"active": True, "steps_left": 6,
                            "decider": self.turn_idx,
                            "visited": [tuple(self.dragon["pos"])]})
        self.phase = "dragon"
        self._log("🐉 龙开始移动（6 步）")
        self._advance_dragon()

    def dragon_legal_steps(self) -> List[Tuple[int, int]]:
        """当前决策者的合法龙步（正交邻格、已放置、未访问、非仙女、非伯爵城）。"""
        from .models import EDGE_DELTAS
        pos = self.dragon["pos"]
        fairy_pos = self.fairy.get("pos")
        out = []
        for dx, dy in EDGE_DELTAS.values():
            npos = (pos[0] + dx, pos[1] + dy)
            if npos not in self.board.tiles:
                continue
            if npos in self.dragon["visited"]:
                continue
            if npos in self._count_block:
                continue   # 龙不得进入伯爵城 12 张牌（CAR 页 76）
            if fairy_pos and npos == tuple(fairy_pos):
                continue
            out.append(npos)
        return out

    def dragon_move(self, pos: Tuple[int, int]) -> None:
        """当前决策者移动龙 1 步（吞噬进入牌上的全部图元）。"""
        assert self.phase == "dragon"
        assert pos in self.dragon_legal_steps(), "非法龙步"
        self.dragon["pos"] = tuple(pos)
        self.dragon["visited"].append(tuple(pos))
        self.dragon["steps_left"] -= 1
        self._dragon_devour(pos)
        self._advance_dragon()

    def _dragon_devour(self, pos: Tuple[int, int]) -> None:
        """龙进入牌：该牌上全部随从归还（无分）；同牌建造者/猪一并归还。"""
        eaten = []
        for root in self.board.roots():
            meta = self.board._meta[root]
            keep = []
            for node, color, size in meta.meeple_nodes:
                if (node[0], node[1]) == pos:
                    p = self._player_by_color(color)
                    if node in meta.phantoms:
                        p.phantom_left += 1
                        meta.phantoms.discard(node)
                    elif size == 2:
                        p.big_meeples_left += 1
                    else:
                        p.meeples_left += 1
                    # 同步扣减多数判定权重（否则幽灵米宝参与判定）
                    meta.meeples[color] = meta.meeples.get(color, 0) - size
                    if meta.meeples[color] <= 0:
                        meta.meeples.pop(color, None)
                    eaten.append(color)
                else:
                    keep.append((node, color, size))
            meta.meeple_nodes = keep
            # M21 山丘与羊：该牌上的牧羊人被吞（羊令牌回袋，脚注 325）
            for s in [s for s in self.shepherds
                      if (self.board.find(s["node"])[0],
                          self.board.find(s["node"])[1]) == pos
                      or (s["node"][0], s["node"][1]) == pos]:
                self.sheep_bag.extend(s["tokens"])
                s["tokens"] = []
                self.shepherds.remove(s)
                self._player_by_color(s["color"]).shepherd_left += 1
                eaten.append(s["color"])
            # M21：该牌上的驻塔随从同样被吞（归还供给，塔可继续加高）
            for t in self.towers:
                if t["pos"] == pos and t.get("top"):
                    top = t["top"]
                    tp = self._player_by_color(top["color"])
                    if top.get("big"):
                        tp.big_meeples_left += 1
                    else:
                        tp.meeples_left += 1
                    t["top"] = None
                    eaten.append(top["color"])
            if eaten:
                pass
            # 同牌上的建造者/猪/市长/马车也被吞
            for attr, left in (("builders", "builder_left"), ("pigs", "pig_left"),
                               ("mayors", "mayor_left"), ("wagons", "wagon_left")):
                d = getattr(meta, attr)
                for color in list(d):
                    nodes = meta.figure_nodes.get((attr, color), [])
                    if any((n[0], n[1]) == pos for n in nodes):
                        self._player_by_color(color).__setattr__(
                            left, getattr(self._player_by_color(color), left) + d.pop(color))
        if eaten:
            self._log("🐉 龙吞噬 (%d,%d)：%s" %
                      (pos[0], pos[1], "、".join(sorted(set(eaten)))))
            # 被吞一方失去随从的挑战自然解除（CAR 未定，从合理：无挑战者）
            self.challenges = [
                ch for ch in self.challenges
                if self.board.meta(ch["shrine"]).meeples
                and self.board.meta(ch["monastery"]).meeples]

    def _advance_dragon(self) -> None:
        """龙阶段推进：步数尽/死路 → 结束并结算；否则交给下一位决策者。"""
        if self.dragon["steps_left"] <= 0 or not self.dragon_legal_steps():
            self.phase = "place"
            self.dragon["active"] = False
            self._log("🐉 龙移动结束")
            self._resolve_turn()
            return
        self.dragon["decider"] = (self.dragon["decider"] + 1) % len(self.players)
        # AI/断线决策者由外部驱动；人类等待输入

    def dragon_decider_player(self):
        """当前应移动龙的玩家（UI/AI 用）。"""
        if self.phase != "dragon":
            return None
        return self.players[self.dragon["decider"]]

    def deploy_fairy(self, pos: Tuple[int, int]) -> None:
        """移动仙女到己方跟随者所在牌（本回合替代部署图元）。"""
        assert self.phase == "deploy"
        player = self.current_player()
        node = None
        for root in self.board.roots():
            meta = self.board._meta[root]
            for n, color, _s in meta.meeple_nodes:
                if color == player.color and (n[0], n[1]) == pos:
                    node = n
                    break
            if node:
                break
        assert node is not None, "仙女目标牌上无己方跟随者"
        self.fairy = {"pos": tuple(pos), "node": node, "owner": player.color}
        self._log("%s 移动仙女至 (%d,%d)" % (player.name, pos[0], pos[1]))
        self._after_deploy()

    def deploy_princess(self, victim_node: Node, victim_color: str) -> None:
        """公主移走所延伸城中的一个骑士（归还其主人）。"""
        assert self.phase == "deploy"
        player = self.current_player()
        root = self.board.find(victim_node)
        meta = self.board._meta[root]
        assert meta.meeples.get(victim_color, 0) > 0, "公主目标骑士不在特征中"
        meta.meeples[victim_color] -= 1
        if meta.meeples[victim_color] <= 0:
            meta.meeples.pop(victim_color, None)
        # 从 meeple_nodes 移除该受害者（同色任取其一）
        for i, (n, c, s) in enumerate(meta.meeple_nodes):
            if c == victim_color:
                meta.meeple_nodes.pop(i)
                break
        p = self._player_by_color(victim_color)
        if any(n2 == victim_node for n2, _c, _s in []) or True:
            # victim_node 本身就是被移除者所在节点
            pass
        p.meeples_left += 1
        # 该色骑士归零 → 其建造者连带归还（CAR 脚注 112）
        if meta.meeples.get(victim_color, 0) == 0:
            p.builder_left += meta.builders.pop(victim_color, 0)
        self._log("%s 公主移走 %s 的骑士" % (player.name, victim_color))
        self._resolve_turn()

    def deploy_mayor(self, seg: int) -> None:
        """部署市长到刚放的牌的城段（本回合替代随从）。"""
        assert self.phase == "deploy"
        player = self.current_player()
        node = (self.placed_pos[0], self.placed_pos[1], KIND_CITY, seg)
        self.board.deploy_mayor(node, player.color)
        player.mayor_left -= 1
        self._log("%s 部署市长" % player.name)
        self._after_deploy()

    def deploy_barn(self, seg: int) -> None:
        """部署粮仓到刚放的牌的农场段：立即结算该农场（农夫归还）。"""
        assert self.phase == "deploy"
        player = self.current_player()
        node = (self.placed_pos[0], self.placed_pos[1], KIND_FARM, seg)
        self.board.deploy_barn(node, player.color)
        player.barn_left -= 1
        self._log("%s 部署粮仓——农场立即结算" % player.name)
        if "count" in self.expansions:
            root = self.board.find(node)
            if self.count["count_pos"] != "market" and any(
                    f[0] for f in self.count["quarters"]["market"]):
                # 市场区有人等候：先重部署再结算（CAR 脚注 224-225）
                self._count_queue = [root]
                self._count_advance()
                return
        self.events.extend(self._score_farm_barn(node))
        self._after_deploy()

    def _score_farm_barn(self, node: Node) -> List[ScoreEvent]:
        """粮仓农场立即结算：多数农夫 3 分/城（猪主人 4），猪倌 +1（脚注 250）。"""
        events: List[ScoreEvent] = []
        root = self.board.find(node)
        meta = self.board._meta[root]
        if not meta.meeples:
            return events
        winners, _t = meeple_majority(meta.meeples)
        city_roots = set()
        for fnode, cnode in self.board.farm_city_pairs:
            if self.board.find(fnode) == root:
                city_roots.add(self.board.find(cnode))
        n_cities = sum(1 for cr in city_roots
                       if self.board._meta[cr].complete)
        herd = any(self.board.defs[p].pig_herd
                   for p in meta.tiles if p in self.board.defs)
        scores = {}
        for w in winners:
            per = (4 if meta.pigs.get(w, 0) > 0 else 3) + (1 if herd else 0)
            scores[w] = per * n_cities
            self._player_by_color(w).score += per * n_cities
        taken = self.board.return_meeples(node)
        self._clear_fairy_if_returned(taken)
        self._return_taken(taken, self.board.pop_phantoms(node))
        ev = ScoreEvent(kind="barn", reason="粮仓结算",
                        scores=scores,
                        detail="粮仓：农场毗邻 %d 个完成城市%s" % (
                            n_cities, "（含猪倌 +1/城）" if herd else ""),
                        pos=(node[0], node[1]))
        events.append(ev)
        self._log("🌾 粮仓结算：%s" % scores)
        meta.scored = True
        if scores:
            self._count_trigger = True
            if self.players[self._placer_idx].color in scores:
                self._placer_scored = True
        return events

    def deploy_wagon(self, kind: str, seg: int) -> None:
        """部署马车到刚放的牌的城/路段（完成后自动移动）。"""
        assert self.phase == "deploy"
        player = self.current_player()
        node = (self.placed_pos[0], self.placed_pos[1], kind, seg)
        self.board.deploy_wagon(node, player.color)
        player.wagon_left -= 1
        self._log("%s 部署马车" % player.name)
        self._after_deploy()

    def _wagon_auto_move(self, color: str, root: Node) -> bool:
        """结算后马车自动移到相邻（共边）的未完成城/路空段。
        返回是否移动成功（无候选则归还马车）。"""
        meta = self.board._meta[root]
        if color not in meta.wagons:
            return False
        from .models import EDGE_DELTAS
        for (tx, ty) in sorted(meta.tiles):
            for dx, dy in EDGE_DELTAS.values():
                npos = (tx + dx, ty + dy)
                if npos not in self.board.tiles:
                    continue
                d = self.board.defs[npos]
                pt = self.board.tiles[npos]
                for kind, segs in ((KIND_CITY, d.rotated_cities(pt.rot)),
                                   (KIND_ROAD, d.rotated_roads(pt.rot))):
                    for i, es in enumerate(segs):
                        edges = es[0] if kind == KIND_CITY else es[0]
                        node = (npos[0], npos[1], kind, i)
                        m = self.board.meta(node)
                        if m.meeples or m.complete:
                            continue
                        if not any(e in edges for e in
                                   (0, 1, 2, 3)):
                            continue
                        # 相邻特征需与本特征共边——简化：接本特征已放牌即可
                        self.board._meta[self.board.find(node)].wagons.pop(color, None)
                        self.board.deploy_wagon(node, color)
                        self._log("🚚 %s 的马车移至 (%d,%d)" %
                                  (self._player_by_color(color).name,
                                   npos[0], npos[1]))
                        return True
        self._player_by_color(color).wagon_left += 1
        meta2 = self.board._meta[self.board.find(root)]
        meta2.wagons.pop(color, None)
        return False

    def deploy_builder(self, kind: str, seg: int) -> None:
        """部署建造者到刚放的牌（本回合不再部署随从）。"""
        assert self.phase == "deploy"
        player = self.current_player()
        node = (self.placed_pos[0], self.placed_pos[1], kind, seg)
        self.board.deploy_builder(node, player.color)
        player.builder_left -= 1
        self._log("%s 部署建造者" % player.name)
        self._resolve_turn()

    def deploy_pig(self, kind: str, seg: int) -> None:
        """部署猪到刚放的牌（本回合不再部署随从）。"""
        assert self.phase == "deploy"
        player = self.current_player()
        node = (self.placed_pos[0], self.placed_pos[1], kind, seg)
        self.board.deploy_pig(node, player.color)
        player.pig_left -= 1
        self._log("%s 部署猪" % player.name)
        self._resolve_turn()

    def skip_deploy(self) -> None:
        assert self.phase == "deploy"
        if self._phantom_step:
            # 幽灵步骤跳过：不再二次提供（机会每回合一次）
            self._phantom_step = False
            self._phantom_done = True
        self._after_deploy()

    # ------------------------------------------------------------ 结算

    def _resolve_turn(self) -> None:
        """部署阶段结束：结算完成特征 → 下一位玩家抽牌（或建造者双回合）。"""
        if "bcb" in self.expansions:
            self._castle_queue = []
            for r in self.pending_completions:
                if not self._is_small_town(r):
                    continue
                meta = self.board._meta[r]
                if not meta.meeples:
                    continue
                winners, _t = (self._city_majority(meta) if meta.mayors
                               else meeple_majority(meta.meeples))
                if winners and self._player_by_color(winners[0]).castles_left > 0:
                    self._castle_queue.append(r)
            if self._castle_queue:
                self.pending_completions = [
                    r for r in self.pending_completions
                    if r not in self._castle_queue]
                self.phase = "castle"
                return
        if "count" in self.expansions:
            self._count_queue = list(self.pending_completions)
            self.pending_completions = []
            self._count_advance()
            return
        events = self._score_completions()
        self.events.extend(events)
        self._finish_turn()

    def _finish_turn(self) -> None:
        """结算收尾：河流火山 / 建造者双回合 / 回合推进 / 摸牌。"""
        # M20：回合末迷你阶段（围攻脱困 → 麦田怪圈 → 强盗）
        if not self._mini_queue:
            self._mini_queue = self._build_end_queue()
        if self._mini_queue:
            self._advance_mini()
            return
        if self._river_volcano:
            # 河流阶段结束：火山湖放置者立即再摸一张普通牌（CAR 脚注 245）
            self._river_volcano = False
            self._river_on = False
            self.phase = "place"
            self._draw_tile()
            self._log("河流阶段结束：%s 开始正常对局"
                      % self.players[self.turn_idx].name)
            return
        if self._extra_turn and not self.game_over:
            # 建造者双回合第二部分：同一玩家继续（无连锁：标志消耗）
            self._extra_turn = False
            self.phase = "place"
            self._draw_tile()
            self._log("%s 获得建造者双回合" % self.players[self.turn_idx].name)
            return
        self.turn_idx = (self.turn_idx + 1) % len(self.players)
        if self.turn_idx == 0:
            self.round_count += 1
        # P&D：新玩家回合开始，仙女与其跟随者同牌 → +1（双回合不重复计）
        if ("pd" in self.expansions and self.fairy.get("owner")
                and self.fairy.get("node")):
            self._player_by_color(self.fairy["owner"]).score += 1
            self._log("✨ 仙女加分：{} +1".format(self.fairy["owner"]))
        if self._pending_bazaar and not self.game_over:
            self._pending_bazaar = False
            if self._start_bazaar():
                return
        if self.bazaar and self.bazaar.get("phase") == "place":
            if self._bazaar_next_place():
                return
        if self._river_on and self.river_pile:
            self.phase = "river"
        else:
            self._river_on = False
            self.phase = "place"
        self._draw_tile()

    def _build_end_queue(self) -> List[str]:
        """回合末可选阶段：围攻脱困 → 麦田怪圈 → 强盗上轨（各至多一次/回合）。"""
        out: List[str] = []
        tile = self.current_tile
        if "besiegers" in self.expansions and not self._escape_offered \
                and self._siege_escape_nodes():
            self._escape_offered = True
            out.append("escape")
        if tile is not None:
            if "crop" in self.expansions and tile.crop and not self._crop_offered:
                self._crop_offered = True
                out.append("crop")
            if "robbers" in self.expansions and tile.robber \
                    and not self._robber_offered:
                self._robber_offered = True
                out.append("robber")
        return out

    # ---- M18 伯爵城：重部署回合 + 伯爵部署（CAR 页 73-77）----

    def _quarter_for_root(self, root: Node) -> Optional[str]:
        kind = self.board._meta[root].kind
        return {KIND_CITY: "castle", KIND_ROAD: "blacksmith",
                KIND_MON: "cathedral", KIND_FARM: "market"}.get(kind)

    def _count_advance(self) -> None:
        """逐个结算待完成特征；四区有人等候且伯爵不在该区 → 挂起重部署回合。"""
        while self._count_queue:
            root = self._count_queue[0]
            meta = self.board._meta[root]
            if meta.scored:
                self._count_queue.pop(0)
                continue
            q = self._quarter_for_root(root)
            # 空特征也允许移入（脚注 218：可借此收回随从并立即得分）
            waiting = q and self.count["count_pos"] != q and any(
                f[0] for f in self.count["quarters"][q])
            if waiting:
                order = [(self._placer_idx + i + 1) % len(self.players)
                         for i in range(len(self.players))]
                self.phase = "redeploy"
                self.redeploy = {"root": root, "order": order, "pos": 0}
                return
            self._count_queue.pop(0)
            self.events.extend(self._score_one(root))
        self._after_count_scoring()

    def redeploy_state(self) -> Optional[Dict[str, object]]:
        if self.phase != "redeploy" or not self.redeploy:
            return None
        st = self.redeploy
        return {"root": list(st["root"]),
                "player": st["order"][st["pos"]],
                "quarter": self._quarter_for_root(st["root"])}

    def redeploy_move(self, move_all: bool) -> None:
        """重部署回合当前玩家的决定：把本区随从全部移入被计分特征（或不移）。

        规则允许移任意子集；移入即将结算的特征只会增加己方份额或造成平局，
        不存在更差结果，故实现为"全移/不移"二选一（与 AI、联机共用）。
        """
        assert self.phase == "redeploy" and self.redeploy
        st = self.redeploy
        idx = st["order"][st["pos"]]
        player = self.players[idx]
        q = self._quarter_for_root(st["root"])
        if move_all:
            moved = [f for f in self.count["quarters"][q]
                     if f[0] == player.color]
            self.count["quarters"][q] = [f for f in self.count["quarters"][q]
                                         if f[0] != player.color]
            for _color, fig in moved:
                self._count_figure_into(st["root"], fig, player.color)
            if moved:
                self._log("🏰 %s 从%s区移入 %d 名随从参与结算"
                          % (player.name, q, len(moved)))
        st["pos"] += 1
        if st["pos"] >= len(st["order"]):
            root = st["root"]
            self.redeploy = None
            self._count_queue.pop(0)
            self.events.extend(self._score_one(root))
            self._count_advance()
        return

    def _count_figure_into(self, root: Node, fig: str, color: str) -> None:
        if fig == "meeple":
            self.board.deploy_meeple(root, color, 1, force=True)
        elif fig == "big":
            self.board.deploy_meeple(root, color, 2, force=True)
        elif fig == "mayor":
            self.board.deploy_mayor(root, color)
        elif fig == "wagon":
            self.board.deploy_wagon(root, color)

    def _after_count_scoring(self) -> None:
        """伯爵部署机会：本放置触发计分而放置者未得分（CAR 页 73-74）。"""
        if (self._count_trigger and not self._placer_scored
                and not self.game_over):
            p = self.players[self._placer_idx]
            if (p.meeples_left > 0 or p.big_meeples_left > 0
                    or p.mayor_left > 0 or p.wagon_left > 0):
                self.phase = "count_deploy"
                return
        self._finish_turn()

    def count_deploy_options(self) -> List[Dict[str, object]]:
        """进城部署选项：区 × 可用图元（市长→城堡区；马车→城/路/修道院区）。"""
        if self.phase != "count_deploy":
            return []
        p = self.players[self._placer_idx]
        figs: List[Tuple[str, Optional[List[str]]]] = []
        if p.meeples_left > 0:
            figs.append(("meeple", None))
        if p.big_meeples_left > 0:
            figs.append(("big", None))
        if p.mayor_left > 0:
            figs.append(("mayor", ["castle"]))
        if p.wagon_left > 0:
            figs.append(("wagon", ["castle", "blacksmith", "cathedral"]))
        qnames = {"castle": "城堡区（城）", "market": "市场区（农场）",
                  "blacksmith": "铁匠区（路）", "cathedral": "大教堂区（修道院）"}
        fnames = {"meeple": "随从", "big": "大型米宝", "mayor": "市长",
                  "wagon": "马车"}
        out: List[Dict[str, object]] = []
        for fig, only in figs:
            for q in ("castle", "market", "blacksmith", "cathedral"):
                if only and q not in only:
                    continue
                out.append({"quarter": q, "fig": fig,
                            "label": "%s → %s" % (fnames[fig], qnames[q])})
        return out

    def deploy_count(self, quarter: str, fig: str,
                     count_move_to: Optional[str] = None) -> None:
        """部署 1 名随从进伯爵城（可同时把伯爵移到任一区）。"""
        assert self.phase == "count_deploy"
        assert quarter in self.count["quarters"]
        p = self.players[self._placer_idx]
        if fig == "meeple":
            assert p.meeples_left > 0
            p.meeples_left -= 1
        elif fig == "big":
            assert p.big_meeples_left > 0
            p.big_meeples_left -= 1
        elif fig == "mayor":
            assert quarter == "castle" and p.mayor_left > 0
            p.mayor_left -= 1
        elif fig == "wagon":
            assert quarter in ("castle", "blacksmith", "cathedral")
            assert p.wagon_left > 0
            p.wagon_left -= 1
        else:
            raise AssertionError(fig)
        self.count["quarters"][quarter].append([p.color, fig])
        if count_move_to in self.count["quarters"]:
            self.count["count_pos"] = count_move_to
        self._log("🏰 %s 部署%s进%s区%s" % (
            p.name, {"meeple": "随从", "big": "大型米宝", "mayor": "市长",
                     "wagon": "马车"}[fig], quarter,
            "，伯爵移至 %s 区" % count_move_to if count_move_to else ""))
        self._finish_turn()

    def skip_count_deploy(self) -> None:
        assert self.phase == "count_deploy"
        self._finish_turn()

    # ---- M18 教堂挑战结算（CAR 页 85-86）----

    def _resolve_challenges(self, root: Node, concurrent: Set[Node]) -> None:
        for ch in list(self.challenges):
            s_root = self.board.find(ch["shrine"])
            m_root = self.board.find(ch["monastery"])
            if root not in (s_root, m_root):
                continue
            other = ch["monastery"] if root == s_root else ch["shrine"]
            other_root = self.board.find(other)
            if other_root in concurrent:
                # 同一放置同时完成双方 → 双方均得分（脚注 266）
                self.challenges.remove(ch)
                self._log("⚔️ 双方同时完成——教堂与修道院均得 9 分")
                continue
            # 先完成者得 9 分（已计）；另一方随从无分归还（CAR 页 86）
            ometa = self.board._meta[other_root]
            taken = self.board.return_meeples(other)
            self._clear_fairy_if_returned(taken)
            self._return_taken(taken, self.board.pop_phantoms(other))
            self.challenges.remove(ch)
            self._log("⚔️ 挑战结束：%s 完成在先，对方随从无分归还"
                      % ("教堂" if root == s_root else "修道院"))
            _ = ometa

    def _score_completions(self) -> List[ScoreEvent]:
        events: List[ScoreEvent] = []
        pending = list(self.pending_completions)
        for root in pending:
            events.extend(self._score_one(root, concurrent=set(pending)))
        self.pending_completions = []
        return events

    def _return_taken(self, taken, ph_nodes) -> None:
        """归还随从集合：幽灵回幽灵池，大型回大池，普通回常规池。

        ph_nodes 按次消费（怪圈 A 可与幽灵同节点叠放）。
        """
        ph = list(ph_nodes)
        for color, size, node in taken:
            p = self._player_by_color(color)
            if node in ph:
                ph.remove(node)
                p.phantom_left += 1
            elif size == 2:
                p.big_meeples_left += 1
            else:
                p.meeples_left += 1

    def _score_one(self, root: Node,
                   concurrent: Optional[Set[Node]] = None) -> List[ScoreEvent]:
        events: List[ScoreEvent] = []
        meta = self.board._meta[root]
        if meta.scored:
            return events
        concurrent = concurrent or set()
        if not meta.meeples:
            # 无人占据的完成特征仍可为城堡回响（CAR 脚注 307）
            pts = self._feature_pts(meta, root)
            # M20 法师/女巫随无主完成特征离场
            for fig in ("mage", "witch"):
                fnode = getattr(self, fig)
                if fnode is not None and meta.kind in (KIND_ROAD, KIND_CITY) \
                        and self.board.find(fnode) == root:
                    setattr(self, fig, None)
                    self._log("🧙 %s 随无主特征离场"
                              % ("法师" if fig == "mage" else "女巫"))
            self._echo_castles(root, pts, events, meta)
            meta.scored = True
            return events
        if meta.kind == KIND_FARM:
            # 粮仓触发的农场结算（经伯爵重部署队列进入）
            evs = self._score_farm_barn(root)
            meta.scored = True
            return evs
        # I&C 扩展：客栈路完成 2 分/牌；大教堂城完成 3 分/（牌+旗帜）
        if meta.kind == KIND_ROAD:
            pts = (2 if meta.inns else 1) * len(meta.tiles)
        elif meta.kind == KIND_CITY:
            pts = (3 if meta.cathedrals else 2) * (len(meta.tiles)
                                                   + meta.pennants)
        else:
            pts = 9
        # M20 围攻城：完成只按 1 分/（牌+旗），大教堂 2 分（脚注 341-343）
        if meta.kind == KIND_MON and "hillsheep" in self.expansions:
            pos0 = sorted(meta.tiles)[0]
            vyd = sum(1 for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                      if (dx or dy)
                      and (pos0[0] + dx, pos0[1] + dy) in self.board.tiles
                      and self.board.defs[(pos0[0] + dx,
                                           pos0[1] + dy)].vineyard)
            if vyd:
                pts = 9 + 3 * vyd
        if meta.kind == KIND_CITY and meta.sieged:
            pts = (2 if meta.cathedrals else 1) * (len(meta.tiles)
                                                   + meta.pennants)
        # M20 法师/女巫：法师 +1 分/牌；女巫减半向上取整（脚注 418）
        mage_here = (self.mage is not None and meta.kind in (KIND_ROAD, KIND_CITY)
                     and self.board.find(self.mage) == root)
        witch_here = (self.witch is not None and meta.kind in (KIND_ROAD, KIND_CITY)
                      and self.board.find(self.witch) == root)
        if mage_here:
            pts += len(meta.tiles)
        if witch_here:
            pts = (pts + 1) // 2
        pts_map = {KIND_ROAD: pts, KIND_CITY: pts, KIND_MON: pts}
        if meta.kind == KIND_CITY and meta.mayors:
            winners, top = self._city_majority(meta)
        else:
            winners, top = meeple_majority(meta.meeples)
        winners = self._hill_tiebreak(meta, winners)
        scores = {w: pts for w in winners}
        detail = {
            KIND_ROAD: "道路完成：%d 张牌%s" % (
                len(meta.tiles), "（含客栈 ×2）" if meta.inns else ""),
            KIND_CITY: "城市完成：%d 张牌%s%s" % (
                len(meta.tiles),
                " + %d 旗帜" % meta.pennants if meta.pennants else "",
                "（含大教堂 ×3）" if meta.cathedrals else ""),
            KIND_MON: "修道院完成：周围 8 格齐",
        }[meta.kind]
        pos = sorted(meta.tiles)[0] if meta.tiles else None
        ev = ScoreEvent(kind=meta.kind, reason=detail, scores=scores,
                        meeples=dict(meta.meeples), detail=detail, pos=pos)
        # P&D：仙女 +3（跟随者与仙女同牌即得，独立于多数结算）
        if ("pd" in self.expansions and self.fairy.get("node")
                and self.fairy.get("owner")):
            fn = self.fairy["node"]
            if (fn[0], fn[1]) in meta.tiles:
                fairy_owner = self._player_by_color(self.fairy["owner"])
                fairy_owner.score += 3
                events.append(ScoreEvent(
                    kind="fairy", reason="仙女加分",
                    scores={self.fairy["owner"]: 3},
                    detail="仙女 +3（%s 跟随者受保护得分）" % self.fairy["owner"],
                    pos=(fn[0], fn[1])))
                self._log("✨ 仙女 +3 → %s" % self.fairy["owner"])
        for w in winners:
            # M20 强盗：得分者起点格上的强盗偷走一半（向上取整）
            if "robbers" in self.expansions and pts > 0:
                self._steal_for_robbers(w, pts, events)
            else:
                self._player_by_color(w).score += pts
        # M18 国王与强盗男爵：完成更大城/路者夺标记（CAR 页 70-71）
        placer_color = self.players[self._placer_idx].color
        if meta.kind == KIND_CITY and len(meta.tiles) > self.king["size"]:
            self.king = {"holder": placer_color, "size": len(meta.tiles)}
            self._log("👑 %s 完成 %d 张城——夺得国王" % (placer_color,
                                                      len(meta.tiles)))
        if meta.kind == KIND_ROAD and len(meta.tiles) > self.robber["size"]:
            self.robber = {"holder": placer_color, "size": len(meta.tiles)}
            self._log("🗡 %s 完成 %d 张路——夺得强盗男爵" % (placer_color,
                                                          len(meta.tiles)))
        # M18 伯爵部署触发判定：本放置触发计分 & 放置者是否得分
        if scores:
            self._count_trigger = True
            if placer_color in scores:
                self._placer_scored = True
        # M20 金矿：完成特征上的金块归多数者（修院含 9 格；农场除外）
        if "goldmines" in self.expansions and meta.kind != KIND_FARM:
            self._award_gold(meta, winners, events)
        # M20 法师/女巫随特征计分离场
        if mage_here:
            self.mage = None
            self._log("🧙 法师随特征计分离场")
        if witch_here:
            self.witch = None
            self._log("🧙 女巫随特征计分离场")
        taken = self.board.return_meeples(root)
        ph_nodes = self.board.pop_phantoms(root)
        self._clear_fairy_if_returned(taken)
        self._return_taken(taken, ph_nodes)
        for color in list(meta.builders):
            self._player_by_color(color).builder_left += meta.builders.pop(color)
        # A&M：市长随城结算归还
        if meta.kind == KIND_CITY:
            for color in list(meta.mayors):
                self._player_by_color(color).mayor_left +=                     (1 if meta.mayors.pop(color, None) is not None else 0)
        # A&M：马车移到相邻未完成特征（自动）
        for color in list(meta.wagons):
            self._wagon_auto_move(color, root)
        # T&B：城完成 → 完成者（放置者）收全部贸易商品
        if meta.kind == KIND_CITY and meta.goods and self.placed_pos is not None:
            receiver = self.current_player()
            got = []
            for g, n in meta.goods.items():
                receiver.goods[g] = receiver.goods.get(g, 0) + n
                got.append("%s×%d" % ({"wine": "酒", "grain": "谷",
                                       "cloth": "布"}.get(g, g), n))
            if got:
                self._log("🏅 %s 收到贸易商品：%s" % (receiver.name, "，".join(got)))
        meta.scored = True
        events.append(ev)
        self._log("计分：%s → %s" % (detail, scores))
        if meta.kind == KIND_MON:
            self._resolve_challenges(root, concurrent)
        self._echo_castles(root, pts, events, meta)
        return events

    def _feature_pts(self, meta, root: Optional[Node] = None) -> int:
        if meta.kind == KIND_ROAD:
            pts = (2 if meta.inns else 1) * len(meta.tiles)
        elif meta.kind == KIND_CITY:
            mult = (3 if meta.cathedrals else
                    1 if meta.sieged else 2)   # M20 围攻城 1 分/（牌+旗）
            pts = mult * (len(meta.tiles) + meta.pennants)
        else:
            return 9
        # M20 法师/女巫修正（需 root 判定图元是否在该特征上）
        if root is not None and meta.kind in (KIND_ROAD, KIND_CITY):
            if self.mage is not None and self.board.find(self.mage) == root:
                pts += len(meta.tiles)
            if self.witch is not None and self.board.find(self.witch) == root:
                pts = (pts + 1) // 2
        return pts

    # ---- M19 桥 / 城堡 / 集市（CAR 页 92-101）----

    def build_bridge(self, pos: Tuple[int, int], axis: int) -> None:
        """本回合建造一座木桥（轴向 0=南北 / 1=东西）。"""
        assert "bcb" in self.expansions
        player = self.current_player()
        assert player.bridges_left > 0, "没有木桥"
        assert not self._built_bridge, "本回合已建一座桥"
        node = self.board.add_bridge(pos, axis)
        player.bridges_left -= 1
        self._built_bridge = True
        meta = self.board.meta(node)
        if meta.complete and not meta.scored:
            root = self.board.find(node)
            if root not in self.pending_completions:
                self.pending_completions.append(root)
        self._log("🌉 %s 在 (%d,%d) 架%s桥" % (
            player.name, pos[0], pos[1], "南北" if axis == 0 else "东西"))

    def bridge_options(self) -> List[Tuple[Tuple[int, int], int]]:
        """部署阶段可选的额外木桥（刚放牌或其邻牌）。"""
        if ("bcb" not in self.expansions or self._built_bridge
                or self.placed_pos is None
                or self.current_player().bridges_left <= 0):
            return []
        out = []
        seen = set()
        cells = [self.placed_pos]
        x, y = self.placed_pos
        for side in range(4):
            npos = self.board.neighbor(x, y, side)
            if npos is not None:
                cells.append(npos)
        for pos in cells:
            for axis in (0, 1):
                key = (pos, axis)
                if key in seen:
                    continue
                if self.board.can_build_bridge(pos, axis):
                    seen.add(key)
                    out.append((pos, axis))
        return out

    # ---- M20 迷你扩展（CAR 页 120-200）----

    def _advance_mini(self) -> None:
        """推进迷你阶段队列；耗尽后按所处阶段回到部署或结算收尾。"""
        while self._mini_queue:
            what = self._mini_queue.pop(0)
            if what == "gold":
                self.phase = "gold"
                return
            if what == "magewitch":
                opts = self.mw_options()
                if not opts["mage"] and not opts["witch"]:
                    # 无合法目标：收回在场图元（脚注 415），否则直接跳过
                    if self.mage is not None:
                        self.mage = None
                        self._log("🧙 无可落目标——法师收回")
                    elif self.witch is not None:
                        self.witch = None
                        self._log("🧙 无可落目标——女巫收回")
                    else:
                        continue
                self.phase = "magewitch"
                return
            if what == "tunnel":
                self.phase = "tunnel"
                return
            if what == "escape":
                self.phase = "escape"
                return
            if what == "crop":
                self._start_crop(self.current_tile.crop)
                return
            if what == "robber":
                self._start_robber_phase()
                return
        if self.phase in ("gold", "magewitch", "tunnel"):
            self.phase = "deploy"
            return
        self._finish_turn()

    # ---- 金矿（CAR 页 148-150）----

    def gold_options(self) -> List[Tuple[int, int]]:
        """第二块金子可落的相邻牌（8 向含对角；须已放置）。"""
        assert self.phase == "gold" and self.placed_pos is not None
        x, y = self.placed_pos
        return [(x + dx, y + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                if (dx or dy) and (x + dx, y + dy) in self.board.tiles]

    def place_gold(self, npos: Tuple[int, int]) -> None:
        """金矿牌放置后：牌上 +1 块，相邻指定牌 +1 块。"""
        assert self.phase == "gold" and npos in self.gold_options(), "非法金块落位"
        self.gold_map[self.placed_pos] = self.gold_map.get(self.placed_pos, 0) + 1
        self.gold_map[npos] = self.gold_map.get(npos, 0) + 1
        self._log("🪙 %s 落金块：(%d,%d) 与 (%d,%d)"
                  % (self.current_player().name, self.placed_pos[0],
                     self.placed_pos[1], npos[0], npos[1]))
        self._advance_mini()

    def _award_gold(self, meta, winners: List[str],
                    events: List[ScoreEvent]) -> None:
        """完成特征上的金块归属多数者（农场除外；脚注 396-398）。

        平局时从主动玩家起顺时针轮流各取一块；修院含周围 8 格。
        """
        if not winners:
            return
        tiles = set(meta.tiles)
        if meta.kind == KIND_MON and meta.tiles:
            px, py = sorted(meta.tiles)[0]
            tiles = {(px + dx, py + dy) for dx in (-1, 0, 1)
                     for dy in (-1, 0, 1)}
        total = sum(self.gold_map.get(t, 0) for t in tiles)
        if not total:
            return
        n = len(self.players)
        order = [self.players[(self._placer_idx + i) % n].color
                 for i in range(n)]
        takers = [c for c in order if c in winners]
        got: Dict[str, int] = {}
        for i in range(total):
            c = takers[i % len(takers)]
            got[c] = got.get(c, 0) + 1
        for c, k in got.items():
            self._player_by_color(c).gold_pieces += k
        for t in tiles:
            self.gold_map.pop(t, None)
        ev = ScoreEvent(kind="gold", reason="金块",
                        scores=dict(got),
                        detail="完成特征上的 %d 块金子" % total,
                        pos=sorted(tiles)[0] if tiles else None)
        events.append(ev)
        self._log("🪙 %s 分金：%s" % (ev.detail, got))

    # ---- 法师与女巫（CAR 页 157-159）----

    def mw_options(self) -> Dict[str, List[Node]]:
        """法师/女巫可放置或移动的目标段（未完成城/路；不得与另一图元同特征）。"""
        out: Dict[str, List[Node]] = {"mage": [], "witch": []}
        seen_roots: Set[Node] = set()
        for pos, d in self.board.defs.items():
            pt = self.board.tiles[pos]
            for kind, segs in ((KIND_CITY, d.rotated_cities(pt.rot)),
                               (KIND_ROAD, d.rotated_roads(pt.rot))):
                for i in range(len(segs)):
                    node = (pos[0], pos[1], kind, i)
                    root = self.board.find(node)
                    if root in seen_roots:
                        continue
                    seen_roots.add(root)
                    meta = self.board._meta[root]
                    # 未完成特征；本轮刚完成待计分的也可放（脚注 417：
                    # 计分前移动，可落在本轮完成的特征上）
                    if meta.scored or (meta.complete
                                       and root not in self.pending_completions):
                        continue
                    for fig, other in (("mage", self.witch),
                                       ("witch", self.mage)):
                        if other is not None and self.board.find(other) == root:
                            continue
                        cur = getattr(self, fig)
                        if cur is not None and self.board.find(cur) == root:
                            continue   # 在场图元必须换特征（脚注 413）
                        out[fig].append(node)
        return out

    def mw_move(self, fig: str, node: Node) -> None:
        assert self.phase == "magewitch" and fig in ("mage", "witch")
        assert node in self.mw_options()[fig], "非法法师/女巫目标"
        setattr(self, fig, tuple(node))
        self._log("🧙 %s 落位 (%d,%d)#%d"
                  % ("法师" if fig == "mage" else "女巫",
                     node[0], node[1], node[3]))
        self._advance_mini()

    def mw_remove(self, fig: str) -> None:
        """无合法目标时收回场上图元（脚注 415）。"""
        assert self.phase == "magewitch" and fig in ("mage", "witch")
        assert getattr(self, fig) is not None
        setattr(self, fig, None)
        self._log("🧙 %s 收回" % ("法师" if fig == "mage" else "女巫"))
        self._advance_mini()

    # ---- 隧道（CAR 页 198-200）----

    def tunnel_options(self) -> List[Node]:
        """全部未占隧道口（路段节点）。"""
        out: List[Node] = []
        for pos, d in self.board.defs.items():
            pt = self.board.tiles[pos]
            for i, (_edges, _inn) in enumerate(d.rotated_roads(pt.rot)):
                if i not in d.tunnels:
                    continue
                node = (pos[0], pos[1], KIND_ROAD, i)
                if node not in self.board.tunnel_tokens:
                    out.append(node)
        return out

    def tunnel_skip(self) -> None:
        """本回合不占领隧道口（放置令牌是可选动作）。"""
        assert self.phase == "tunnel"
        self._advance_mini()

    def tunnel_claim(self, node: Node) -> None:
        """占领隧道口；同色第二枚令牌将两条路地下接通（仅计可见段）。"""
        assert self.phase == "tunnel" and node in self.tunnel_options(), "非法隧道口"
        player = self.current_player()
        assert player.tunnels_left > 0, "没有隧道令牌"
        color = player.color
        node = tuple(node)
        self.board.tunnel_tokens[node] = color
        prev = self.tunnel_open.pop(color, None)
        if prev is None:
            player.tunnels_left -= 1
            self.tunnel_open[color] = node
            self._log("🚇 %s 占领隧道口 (%d,%d)#%d"
                      % (player.name, node[0], node[1], node[3]))
        else:
            r1, r2 = self.board.find(node), self.board.find(prev)
            if r1 != r2:
                root = self.board._union(r1, r2)
                meta = self.board._meta[root]
                meta.open_edges = max(0, meta.open_edges - 2)
                if meta.open_edges == 0:
                    meta.complete = True
                if meta.complete and not meta.scored \
                        and root not in self.pending_completions:
                    self.pending_completions.append(root)
            self._log("🚇 %s 的隧道贯通 (%d,%d)#%d ↔ (%d,%d)#%d"
                      % (player.name, node[0], node[1], node[3],
                         prev[0], prev[1], prev[3]))
        self._advance_mini()

    # ---- 麦田怪圈（CAR 页 130-133）----

    def _start_crop(self, kind: str) -> None:
        n = len(self.players)
        order = [(self._placer_idx + i + 1) % n for i in range(n)]
        self.crop = {"kind": kind, "mode": None, "order": order, "pos": 0}
        self.phase = "crop"
        self._log("🌾 麦田怪圈（%s）：%s 选择效果"
                  % ({"farm": "草叉", "road": "棍棒",
                      "city": "盾徽"}[kind], self.players[self._placer_idx].name))

    def crop_choose(self, mode: str) -> None:
        """主动玩家决定效果：A=可部署同伴 / B=必须收回。"""
        assert self.phase == "crop" and self.crop and self.crop["mode"] is None
        assert mode in ("A", "B"), "非法怪圈效果"
        assert self.turn_idx == self._placer_idx, "只有主动玩家能选效果"
        self.crop["mode"] = mode
        self._log("🌾 怪圈效果 %s（%s）"
                  % (mode, "部署同伴" if mode == "A" else "收回随从"))

    def _crop_player(self):
        return self.players[self.crop["order"][self.crop["pos"]]]

    def crop_options(self) -> List[Dict[str, object]]:
        """当前轮到玩家的怪圈动作选项（A：部署到己同类型随从所在特征；B：移除）。"""
        if not self.crop or self.crop["mode"] is None:
            return []
        p = self._crop_player()
        k = {"farm": KIND_FARM, "road": KIND_ROAD,
             "city": KIND_CITY}[self.crop["kind"]]
        out: List[Dict[str, object]] = []
        if self.crop["mode"] == "A":
            if p.meeples_left <= 0:
                return out
            for root in self.board.roots():
                meta = self.board._meta[root]
                if meta.kind != k:
                    continue
                for node, color, _size in meta.meeple_nodes:
                    if color == p.color:
                        out.append({"node": node, "label": "部署同伴 (%d,%d)#%d"
                                    % (node[0], node[1], node[3])})
                        break
        else:
            for root in self.board.roots():
                meta = self.board._meta[root]
                if meta.kind != k:
                    continue
                for node, color, _size in meta.meeple_nodes:
                    if color == p.color:
                        out.append({"node": node, "remove": True,
                                    "label": "收回 (%d,%d)#%d"
                                    % (node[0], node[1], node[3])})
        return out

    def crop_act(self, node: Optional[Node] = None) -> None:
        """当前玩家执行怪圈动作；A 可跳过，B 有随从则必须移除。"""
        assert self.phase == "crop" and self.crop and self.crop["mode"]
        p = self._crop_player()
        opts = self.crop_options()
        if self.crop["mode"] == "A":
            if node is not None:
                assert any(o["node"] == tuple(node) for o in opts), "非法怪圈部署"
                self.board.deploy_meeple(tuple(node), p.color, 1, force=True)
                p.meeples_left -= 1
                self._log("🌾 %s 部署同伴随从至 (%d,%d)#%d"
                          % (p.name, node[0], node[1], node[3]))
        else:
            if opts:
                assert node is not None and \
                    any(o["node"] == tuple(node) for o in opts), "必须移除一个随从"
                color, size, ph = self.board.remove_meeple(tuple(node))
                if ph:
                    p.phantom_left += 1
                elif size == 2:
                    p.big_meeples_left += 1
                else:
                    p.meeples_left += 1
                self._log("🌾 %s 收回随从 (%d,%d)#%d"
                          % (p.name, node[0], node[1], node[3]))
        self.crop["pos"] += 1
        if self.crop["pos"] >= len(self.crop["order"]):
            self.crop = None
            self._advance_mini()

    # ---- 强盗（CAR 页 186-192）----

    def _start_robber_phase(self) -> None:
        n = len(self.players)
        order = [(self._placer_idx + i) % n for i in range(n)]
        self.robber_phase = {"order": order, "pos": 0}
        self.phase = "robber"
        self._log("🦹 强盗牌：各玩家可把强盗放上计分轨道")

    def _has_counting_figure(self, color: str) -> bool:
        for root in self.board.roots():
            meta = self.board._meta[root]
            for _node, c, _s in meta.meeple_nodes:
                if c == color:
                    return True
            if color in meta.mayors or color in meta.wagons:
                return True
        return False

    def robber_options(self) -> List[int]:
        """当前玩家可放/移强盗的计分格（他人随从所在格；不能上己方格）。"""
        assert self.phase == "robber" and self.robber_phase
        rp = self.robber_phase
        p = self.players[rp["order"][rp["pos"]]]
        active = rp["order"][rp["pos"]] == self._placer_idx
        if p.color in self.robbers and not active:
            return []   # 非主动玩家的强盗已在轨上 → 跳过
        spaces = {q.score for q in self.players
                  if q.idx != p.idx and self._has_counting_figure(q.color)}
        return sorted(spaces)

    def robber_place(self, space: Optional[int]) -> None:
        """当前玩家放置（或主动玩家移动）强盗到指定格；None 为放弃。"""
        assert self.phase == "robber" and self.robber_phase
        rp = self.robber_phase
        p = self.players[rp["order"][rp["pos"]]]
        if space is not None:
            assert space in self.robber_options(), "非法强盗格"
            self.robbers[p.color] = int(space)
            self._log("🦹 %s 的强盗上轨道格 %d" % (p.name, space))
        rp["pos"] += 1
        if rp["pos"] >= len(rp["order"]):
            self.robber_phase = None
            self._advance_mini()

    def _steal_for_robbers(self, color: str, pts: int,
                           events: List[ScoreEvent]) -> None:
        """先正常得分；起点格上的强盗偷走一半（向上取整）后回到供给。

        Rogue：得分来自偷窃时，起点格上的其他强盗随行不移除（脚注 187）。
        """
        p = self._player_by_color(color)
        if pts <= 0:
            return
        start = p.score
        p.score += pts
        here = [(owner, space) for owner, space in self.robbers.items()
                if space == start and owner != color]
        if not here:
            return
        steal = (pts + 1) // 2
        for owner, _space in here:
            op = self._player_by_color(owner)
            op.score += steal
            self.robbers.pop(owner, None)
            events.append(ScoreEvent(kind="robber", reason="强盗分赃",
                                     scores={owner: steal},
                                     detail="强盗偷走 %s 的 %d 分一半（%d 分）"
                                     % (color, pts, steal)))
            self._log("🦹 强盗（%s）偷走 %s 的 %d 分 → +%.0f"
                      % (owner, color, pts, steal))

    # ---- 围攻脱困（CAR 页 122）----

    def _siege_escape_nodes(self) -> List[Node]:
        """己方骑士可脱困的节点：被围城 + 8 邻有修道院型建筑。"""
        out: List[Node] = []
        me = self.current_player().color
        for root in self.board.roots():
            meta = self.board._meta[root]
            if meta.kind != KIND_CITY or not meta.sieged:
                continue
            has_cloister = False
            for pos in meta.tiles:
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        npos = (pos[0] + dx, pos[1] + dy)
                        if not (dx or dy) or npos not in self.board.tiles:
                            continue
                        nd = self.board.defs[npos]
                        if nd.center.value == 1 or nd.abbey or nd.shrine:
                            has_cloister = True
                            break
                    if has_cloister:
                        break
                if has_cloister:
                    break
            if not has_cloister:
                continue
            for node, color, _size in meta.meeple_nodes:
                if color == me:
                    out.append(node)
        return out

    def escape_options(self) -> List[Node]:
        return self._siege_escape_nodes() if self.phase == "escape" else []

    def escape_move(self, node: Optional[Node]) -> None:
        """回合末脱困：从被围城收回一名己骑士（可选；每回合一名）。"""
        assert self.phase == "escape"
        if node is not None:
            assert node in self._siege_escape_nodes(), "非法脱困"
            color, _size, ph = self.board.remove_meeple(tuple(node))
            p = self._player_by_color(color)
            if ph:
                p.phantom_left += 1
            else:
                p.meeples_left += 1
            self._log("🏃 %s 的骑士从被围城逃出 (%d,%d)#%d"
                      % (p.name, node[0], node[1], node[3]))
        self._advance_mini()

    def _escape_eligible(self) -> bool:
        return (self.phase in ("place", "deploy", "crop", "robber", "over")
                and not self._escape_offered
                and bool(self._siege_escape_nodes()))

    # ---- 幽灵（CAR 页 172-173）与节日（CAR 页 140）----

    def _maybe_phantom_step(self) -> bool:
        if "phantom" not in self.expansions or self._phantom_step \
                or self._phantom_done:
            return False
        player = self.current_player()
        if player.phantom_left <= 0 or not self.deploy_options():
            return False
        self._phantom_step = True
        self._phantom_done = True
        self.phase = "deploy"
        self._log("👻 %s 可部署幽灵（第二随从）" % player.name)
        return True

    def festival_options(self) -> List[Dict[str, object]]:
        """节日牌：可收回的己方任一图元（全场；不含仙女/龙）。"""
        tile = self.current_tile
        if not (tile is not None and tile.festival
                and "festival" in self.expansions):
            return []
        if self.phase != "deploy" or self._phantom_step:
            return []
        player = self.current_player()
        kind_name = {KIND_CITY: "骑士", KIND_ROAD: "随从",
                     KIND_FARM: "农夫", KIND_MON: "僧侣"}
        out: List[Dict[str, object]] = []
        for root in self.board.roots():
            meta = self.board._meta[root]
            for node, color, size in meta.meeple_nodes:
                if color != player.color:
                    continue
                ghost = node in meta.phantoms
                label = "👻幽灵" if ghost else kind_name.get(meta.kind, "随从")
                out.append({"fig": "meeple", "node": node,
                            "label": "🎪 收回%s (%d,%d)"
                            % (label, node[0], node[1])})
            for (attr, color), nodes in meta.figure_nodes.items():
                if color != player.color:
                    continue
                for node in nodes:
                    nm = "建造者" if attr == "builders" else "猪"
                    out.append({"fig": attr.rstrip("s"), "node": node,
                                "label": "🎪 收回%s (%d,%d)"
                                % (nm, node[0], node[1])})
            if player.color in meta.mayors:
                node = meta.mayors[player.color]
                out.append({"fig": "mayor", "node": node,
                            "label": "🎪 收回市长 (%d,%d)" % node[:2]})
            if player.color in meta.wagons:
                node = meta.wagons[player.color]
                out.append({"fig": "wagon", "node": node,
                            "label": "🎪 收回马车 (%d,%d)" % node[:2]})
            if player.color in meta.barns:
                pos2 = meta.barns[player.color]
                out.append({"fig": "barn", "node": (pos2[0], pos2[1]),
                            "label": "🎪 收回粮仓 (%d,%d)" % pos2})
        return out

    def festival_return(self, opt: Dict[str, object]) -> None:
        """节日牌效果：收回指定己方图元（本回合不再部署、不可移仙女）。"""
        assert self.phase == "deploy", "当前不是部署阶段"
        assert opt in self.festival_options(), "非法节日收回"
        player = self.current_player()
        node = tuple(opt["node"])   # type: ignore[assignment]
        fig = opt["fig"]
        if fig == "meeple":
            color, size, ph = self.board.remove_meeple(node)
            if ph:
                player.phantom_left += 1
            elif size == 2:
                player.big_meeples_left += 1
            else:
                player.meeples_left += 1
        else:
            root = self.board.find(node)
            meta = self.board._meta[root]
            if fig == "builder":
                nodes = meta.figure_nodes.get(("builders", player.color), [])
                if node in nodes:
                    nodes.remove(node)
                player.builder_left += 1
            elif fig == "pig":
                nodes = meta.figure_nodes.get(("pigs", player.color), [])
                if node in nodes:
                    nodes.remove(node)
                player.pig_left += 1
            elif fig == "mayor":
                meta.mayors.pop(player.color, None)
                player.mayor_left += 1
            elif fig == "wagon":
                meta.wagons.pop(player.color, None)
                player.wagon_left += 1
            elif fig == "barn":
                meta.barns.pop(player.color, None)
                player.barn_left += 1
        self._log("🎪 %s 节日收回图元 @(%d,%d)" % (player.name, node[0], node[1]))
        self._resolve_turn()

    # ---- M21 塔（CAR 页 51-55）----

    def _tower_at(self, pos: Tuple[int, int]) -> Optional[Dict[str, object]]:
        for t in self.towers:
            if t["pos"] == tuple(pos):
                return t
        return None

    def _followers_on(self, pos: Tuple[int, int]) -> List[Node]:
        """某牌上全部可被抓的随从节点（普通/大型/幽灵；建造者/猪不算）。"""
        out: List[Node] = []
        seen_roots: Set[Node] = set()
        for root in self.board.roots():
            if root in seen_roots:
                continue
            seen_roots.add(root)
            for node, _c, _s in self.board._meta[root].meeple_nodes:
                if (node[0], node[1]) == tuple(pos):
                    out.append(node)
        return out

    def tower_piece_options(self) -> List[Tuple[Tuple[int, int], List[Node]]]:
        """可放塔块的位置（塔基石牌未建塔 / 未完工塔）及各自抓捕目标。"""
        if self.phase != "deploy" or self.current_player().towers_left <= 0:
            return []
        out: List[Tuple[Tuple[int, int], List[Node]]] = []
        for pos, d in self.board.defs.items():
            if not d.tower:
                continue
            t = self._tower_at(pos)
            if t is not None and t["top"] is not None:
                continue   # 已有随从驻塔 → 完工
            captures: List[Node] = []
            height = t["height"] if t is not None else 0
            new_height = height + 1
            x, y = pos
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                for dist in range(1, new_height + 1):
                    tpos = (x + dx * dist, y + dy * dist)
                    if tpos in self.board.tiles:
                        captures.extend(self._followers_on(tpos))
            out.append((pos, captures))
        return out

    def tower_top_options(self) -> List[Tuple[int, int]]:
        """可部署随从驻塔的塔（已建 ≥1 块且无人驻塔）。"""
        if self.phase != "deploy":
            return []
        player = self.current_player()
        if player.meeples_left <= 0 and player.big_meeples_left <= 0:
            return []
        return [t["pos"] for t in self.towers if t["top"] is None]

    def ransom_options(self) -> List[int]:
        """可赎回的己方人质下标（每回合一次；买回后当回合可部署）。"""
        if self.phase != "deploy" or self._ransom_used:
            return []
        me = self.current_player().color
        return [i for i, h in enumerate(self.hostages) if h["owner"] == me]

    def tower_place(self, pos: Tuple[int, int],
                    capture: Optional[Node] = None) -> None:
        """放置一块塔（代替部署随从），可顺手抓一名射线内随从。"""
        assert self.phase == "deploy", "当前不是部署阶段"
        opts = dict((p, c) for p, c in self.tower_piece_options())
        assert tuple(pos) in opts, "非法塔位"
        if capture is not None:
            assert tuple(capture) in opts[tuple(pos)], "非法抓捕目标"
        player = self.current_player()
        player.towers_left -= 1
        t = self._tower_at(pos)
        if t is None:
            t = {"pos": tuple(pos), "height": 0, "top": None}
            self.towers.append(t)
        t["height"] = int(t["height"]) + 1
        self._log("🗼 %s 在 (%d,%d) 建塔至 %d 层"
                  % (player.name, pos[0], pos[1], t["height"]))
        if capture is not None:
            self._capture_follower(tuple(capture), player.color)
        self._resolve_turn()

    def tower_deploy_top(self, pos: Tuple[int, int], big: bool = False) -> None:
        """部署随从驻塔顶：塔完工（随从留至终局，可被龙吞/他塔抓走）。"""
        assert self.phase == "deploy", "当前不是部署阶段"
        assert tuple(pos) in self.tower_top_options(), "非法驻塔"
        player = self.current_player()
        if big:
            assert player.big_meeples_left > 0, "没有大型米宝"
            player.big_meeples_left -= 1
        elif player.meeples_left > 0:
            player.meeples_left -= 1
        else:
            # 普通米宝耗尽时改用大型米宝（选项在仅剩大米宝时仍合法）
            assert player.big_meeples_left > 0, "没有可用米宝"
            big = True
            player.big_meeples_left -= 1
        t = self._tower_at(pos)
        t["top"] = {"color": player.color, "big": bool(big)}   # type: ignore[index]
        self._log("🗼 %s 部署随从驻塔 (%d,%d)——塔完工"
                  % (player.name, pos[0], pos[1]))
        self._resolve_turn()

    def ransom(self, idx: int) -> None:
        """赎回人质：己方 -3 分、扣押者 +3 分，随从回供给（本回合可部署）。"""
        assert self.phase == "deploy" and not self._ransom_used, "本回合已赎金"
        assert idx in self.ransom_options(), "非法赎回"
        h = self.hostages.pop(idx)
        owner = self._player_by_color(h["owner"])
        captor = self._player_by_color(h["captor"])
        owner.score -= 3
        captor.score += 3
        if h.get("ph"):
            owner.phantom_left += 1
        elif h.get("size") == 2:
            owner.big_meeples_left += 1
        else:
            owner.meeples_left += 1
        self._ransom_used = True
        self._log("💰 %s 花 3 分赎回随从（%s +3）" % (owner.name, captor.name))

    def _capture_follower(self, node: Node, captor: str) -> None:
        """抓走随从：己方直接回供给，对手成为人质；随后自动对换。"""
        color, size, ph = self.board.remove_meeple(node)
        player = self._player_by_color(color)
        if color == captor:
            if ph:
                player.phantom_left += 1
            elif size == 2:
                player.big_meeples_left += 1
            else:
                player.meeples_left += 1
            self._log("🗼 %s 收回己方随从 (%d,%d)#%d"
                      % (player.name, node[0], node[1], node[3]))
        else:
            self.hostages.append({"owner": color, "captor": captor,
                                  "size": size, "ph": ph})
            self._log("🗼 %s 抓走 %s 的随从 (%d,%d)#%d —— 人质！"
                      % (captor, color, node[0], node[1], node[3]))
        # 特征上该色随从清空 → 其建造者/猪一并归还（脚注 123）
        root = self.board.find(node)
        meta = self.board._meta[root]
        if not meta.meeples or meta.meeples.get(color, 0) == 0:
            if color in meta.builders:
                player.builder_left += meta.builders.pop(color)
            if color in meta.pigs:
                player.pig_left += meta.pigs.pop(color)
        self._auto_exchange()

    def _auto_exchange(self) -> None:
        """互扣人质立即对换归还（CAR 页 55）。"""
        changed = True
        while changed:
            changed = False
            for i, h1 in enumerate(self.hostages):
                for j, h2 in enumerate(self.hostages):
                    if i != j and h1["owner"] == h2["captor"]                             and h2["owner"] == h1["captor"]:
                        for h in (h1, h2):
                            p = self._player_by_color(h["owner"])
                            if h.get("ph"):
                                p.phantom_left += 1
                            elif h.get("size") == 2:
                                p.big_meeples_left += 1
                            else:
                                p.meeples_left += 1
                        self._log("🤝 互扣人质自动对换：%s ↔ %s"
                                  % (h1["owner"], h2["owner"]))
                        for k in sorted((i, j), reverse=True):
                            self.hostages.pop(k)
                        changed = True
                        break
                if changed:
                    break

    def _towers_return_tops(self) -> None:
        """终局/龙吞后：驻塔随从归还得主供给。"""
        for t in self.towers:
            top = t.get("top")
            if top:
                p = self._player_by_color(top["color"])
                if top.get("big"):
                    p.big_meeples_left += 1
                else:
                    p.meeples_left += 1
                t["top"] = None

    # ---- M21 命运之轮（CAR 页 109-112）----

    WHEEL_SECTORS = ["fortune", "plague", "inquisition", "storm",
                     "famine", "tax"]
    WHEEL_SLOTS = {0: 2, 1: 2, 2: 2, 3: 1, 4: 1, 5: 2}   # 各扇区王冠位数

    def _wheel_event(self, fate: int) -> None:
        """抽到命运牌：猪走 fate 格 → 触发扇区事件 → 王冠位计分归还。"""
        self.wheel_pig = (self.wheel_pig + fate) % 6
        sector = self.WHEEL_SECTORS[self.wheel_pig]
        name = {"fortune": "幸运", "plague": "瘟疫", "inquisition": "审判",
                "storm": "风暴", "famine": "饥荒", "tax": "税收"}[sector]
        self._log("🎡 轮盘转到 %s（猪前进 %d 格）" % (name, fate))
        if sector == "fortune":
            me = self.current_player()
            me.score += 3
            self._log("🎡 幸运：%s +3" % me.name)
        elif sector == "tax":
            for p in self.players:
                pts = 0
                for root in self.board.roots():
                    meta = self.board._meta[root]
                    if meta.kind != KIND_CITY:
                        continue
                    knights = meta.meeples.get(p.color, 0)
                    if not knights:
                        continue
                    pts += knights + meta.pennants
                if pts:
                    p.score += pts
                    self._log("🎡 税收：%s + %d（骑士与旗帜）" % (p.name, pts))
        elif sector == "famine":
            # 每个农夫按其草场终局价值计（无多数要求；粮仓不算，脚注 332/333）
            normalized: Dict[Node, Set[Node]] = {}
            for fnode, cnode in self.board.farm_city_pairs:
                normalized.setdefault(self.board.find(fnode),
                                      set()).add(self.board.find(cnode))
            for p in self.players:
                pts = 0
                for root in self.board.roots():
                    meta = self.board._meta[root]
                    if meta.kind != KIND_FARM or not meta.meeples:
                        continue
                    if meta.meeples.get(p.color, 0) <= 0:
                        continue
                    city_roots = normalized.get(root, set())
                    n_cities = sum(1 for cr in city_roots
                                   if self.board._meta[cr].complete)
                    n_castles = 0
                    if "bcb" in self.expansions:
                        for c in self.castles:
                            cr = c.get("city_root")
                            if cr is not None and self.board.find(cr) \
                                    in city_roots:
                                n_castles += 1
                    pig = meta.pigs.get(p.color, 0) > 0
                    herd = any(self.board.defs[t].pig_herd
                               for t in meta.tiles if t in self.board.defs)
                    per_city = (4 if pig else 3) + (1 if herd else 0)
                    per_castle = (5 if pig else 4) + (1 if herd else 0)
                    pts += per_city * n_cities + per_castle * n_castles
                if pts:
                    p.score += pts
                    self._log("🎡 饥荒：%s 的农夫 + %d" % (p.name, pts))
        elif sector == "storm":
            for p in self.players:
                n = p.meeples_left + p.big_meeples_left
                if n:
                    p.score += n
                    self._log("🎡 风暴：%s 供给随从 %d → +%d" % (p.name, n, n))
        elif sector == "inquisition":
            for p in self.players:
                n = 0
                for root in self.board.roots():
                    meta = self.board._meta[root]
                    if meta.kind == KIND_MON:
                        n += meta.meeples.get(p.color, 0)
                if n:
                    p.score += 2 * n
                    self._log("🎡 审判：%s 修士 %d → +%d" % (p.name, n, 2 * n))
        elif sector == "plague":
            order = [(self.turn_idx + i) % len(self.players)
                     for i in range(len(self.players))]
            self.plague = {"order": order, "pos": 0}
            self.phase = "plague"
            self._log("🎡 瘟疫：各玩家依次收回一名场上随从")
            return   # 瘟疫阶段由 _advance_plague 推进；王冠计分延后
        # 王冠位计分（瘟疫阶段结束后由 _advance_plague 调用）
        self._score_crowns()

    def _score_crowns(self) -> None:
        """猪所停扇区的王冠位计分：1 位扇区独占 3 分；2 位扇区独占 6、
        双人各 3；计分后随从归还。"""
        sector = self.wheel_pig
        riders = self.crowns.get(sector) or []
        if not riders:
            return
        if len(riders) == 1:
            pts = 6 if self.WHEEL_SLOTS[sector] == 2 else 3
        else:
            pts = 3
        for r in riders:
            p = self._player_by_color(r["color"])
            p.score += pts
            if r.get("size") == 2:
                p.big_meeples_left += 1
            else:
                p.meeples_left += 1
            self._log("🎡 王冠位：%s + %d" % (p.name, pts))
        self.crowns[sector] = []

    def crown_options(self) -> List[Dict[str, object]]:
        """空闲王冠位（部署阶段代替随从上架）。"""
        if self.phase != "deploy" or self.current_player().meeples_left <= 0 \
                or "wheel" not in self.expansions:
            return []
        out: List[Dict[str, object]] = []
        for sector in range(6):
            for slot in range(self.WHEEL_SLOTS[sector]):
                if len(self.crowns.get(sector) or []) > slot:
                    continue
                out.append({"kind": "crown", "seg": sector * 2 + slot,
                            "label": "🎡 王冠位·%s"
                            % self.WHEEL_SECTORS[sector],
                            "node": None, "big": False})
        return out

    def plague_options(self) -> List[Node]:
        """瘟疫：当前玩家可收回的己方场上随从（王冠位除外）。"""
        if self.phase != "plague" or not self.plague:
            return []
        me = self.players[self.plague["order"][self.plague["pos"]]].color
        out: List[Node] = []
        for root in self.board.roots():
            for node, c, _s in self.board._meta[root].meeple_nodes:
                if c == me:
                    out.append(node)
        return out

    def plague_act(self, node: Optional[Node]) -> None:
        """瘟疫：收回一名己方随从（场上无随从则自动跳过）。"""
        assert self.phase == "plague" and self.plague
        opts = self.plague_options()
        if opts:
            assert node is not None and tuple(node) in opts, "非法瘟疫收回"
            color, size, ph = self.board.remove_meeple(tuple(node))
            p = self._player_by_color(color)
            if ph:
                p.phantom_left += 1
            elif size == 2:
                p.big_meeples_left += 1
            else:
                p.meeples_left += 1
            self._log("🎡 瘟疫：%s 收回随从" % p.name)
        self.plague["pos"] = int(self.plague["pos"]) + 1
        if int(self.plague["pos"]) >= len(self.plague["order"]):
            self.plague = None
            self._score_crowns()
            self.phase = "place"

    def _is_small_town(self, root: Node) -> bool:
        """两段半圆城组成的 2 牌小城（可改建城堡；排除三角城，CAR 脚注 299）。"""
        meta = self.board._meta[root]
        if meta.kind != KIND_CITY or len(meta.tiles) != 2:
            return False
        for pos in meta.tiles:
            d = self.board.defs[pos]
            rot = self.board.tiles[pos].rot
            hit = False
            for i, (edges, _p, _c) in enumerate(d.rotated_cities(rot)):
                if self.board.find((pos[0], pos[1], KIND_CITY, i)) != root:
                    continue
                if len(edges) != 1:
                    return False
                hit = True
            if not hit:
                return False
        return True

    def castle_options(self) -> List[Node]:
        if self.phase != "castle":
            return []
        return list(self._castle_queue)

    def convert_castle(self, convert: bool = True) -> None:
        """小城完成：改建城堡或按常规划分。"""
        assert self.phase == "castle" and self._castle_queue
        root = self._castle_queue.pop(0)
        if convert:
            self._do_convert_castle(root)
        else:
            self.events.extend(self._score_one(root))
        if self._castle_queue:
            return
        if self.pending_completions:
            self.events.extend(self._score_completions())
        self._finish_turn()

    def _do_convert_castle(self, root: Node) -> None:
        meta = self.board._meta[root]
        winners, _t = (self._city_majority(meta) if meta.mayors
                       else meeple_majority(meta.meeples))
        owner = winners[0] if winners else self.current_player().color
        p = self._player_by_color(owner)
        assert p.castles_left > 0
        p.castles_left -= 1
        taken = self.board.return_meeples(root)
        self._clear_fairy_if_returned(taken)
        ph_nodes = self.board.pop_phantoms(root)
        owner_figs: List[str] = []
        for color, size, nd in taken:
            if color != owner:
                pl = self._player_by_color(color)
                if nd in ph_nodes:
                    pl.phantom_left += 1
                elif size == 2:
                    pl.big_meeples_left += 1
                else:
                    pl.meeples_left += 1
            elif nd in ph_nodes:
                owner_figs.append("phantom")
            else:
                owner_figs.append("big" if size == 2 else "meeple")
        for color in list(meta.builders):
            self._player_by_color(color).builder_left += meta.builders.pop(color)
        # 城堡只留 1 枚图元作标记；多数方其余随从立即归还（作物圈/幽灵叠放）
        extras: List[str] = []
        if owner in meta.wagons:
            fig = "wagon"
            meta.wagons.pop(owner)
            extras = owner_figs
        elif owner in meta.mayors:
            fig = "mayor"
            meta.mayors.pop(owner)
            extras = owner_figs
        elif owner_figs:
            fig = owner_figs[0]
            extras = owner_figs[1:]
        else:
            fig = "meeple"
        for f in extras:
            if f == "phantom":
                p.phantom_left += 1
            elif f == "big":
                p.big_meeples_left += 1
            else:
                p.meeples_left += 1
        tiles = sorted(meta.tiles)
        adj = self._castle_adjacent(tiles)
        self.castles.append({
            "owner": owner, "fig": fig, "tiles": tiles, "adjacent": sorted(adj),
            "city_root": root, "scored": False,
            "built_turn": (self.round_count, self._placer_idx),
        })
        meta.scored = True
        meta.complete = False
        self._log("🏰 %s 将 2 牌小城改建为城堡" % p.name)

    def _castle_adjacent(self, tiles) -> Set[Tuple[int, int]]:
        t = sorted(tiles)
        (x1, y1), (x2, y2) = t[0], t[1]
        if y1 == y2:
            return {(x1, y1 - 1), (x2, y1 - 1), (x1, y1), (x2, y1),
                    (x1, y1 + 1), (x2, y1 + 1)}
        return {(x1 - 1, y1), (x1, y1), (x1 + 1, y1),
                (x2 - 1, y2), (x2, y2), (x2 + 1, y2)}

    def _echo_castles(self, root: Node, pts: int, events: List[ScoreEvent],
                      meta) -> None:
        if "bcb" not in self.expansions or pts <= 0:
            return
        hits = []
        for c in self.castles:
            if c["scored"]:
                continue
            if c["built_turn"] == (self.round_count, self._placer_idx):
                continue
            if meta.kind == KIND_MON:
                if (root[0], root[1]) not in c["adjacent"]:
                    continue
            elif not (meta.tiles & set(c["adjacent"])):
                continue
            hits.append(c)
        if not hits:
            return
        # 同时多个结构：城堡取本特征（调用方已按完成顺序）；一座城堡只回响一次
        c = hits[0]
        owner = c["owner"]
        self._player_by_color(owner).score += pts
        fig = c["fig"]
        p = self._player_by_color(owner)
        if fig == "big":
            p.big_meeples_left += 1
        elif fig == "wagon":
            p.wagon_left += 1
        elif fig == "mayor":
            p.mayor_left += 1
        elif fig == "phantom":
            p.phantom_left += 1
        else:
            p.meeples_left += 1
        c["scored"] = True
        # M20 金矿（脚注 396）：城堡回响时堡主可索 vicinity（2 城牌+左右）金块
        if "goldmines" in self.expansions:
            vic = set(c["tiles"]) | set(c["adjacent"])
            total = sum(self.gold_map.get(t, 0) for t in vic)
            if total:
                for t in vic:
                    self.gold_map.pop(t, None)
                p.gold_pieces += total
                events.append(ScoreEvent(
                    kind="gold", reason="城堡索金", scores={owner: total},
                    detail="城堡 vicinity %d 块金子" % total,
                    pos=c["tiles"][0]))
                self._log("🪙 城堡索金：%s + %d 块" % (owner, total))
        events.append(ScoreEvent(
            kind="castle", reason="城堡回响", scores={owner: pts},
            detail="城堡获得同等 %d 分" % pts, pos=c["tiles"][0]))
        self._log("🏰 城堡回响：%s +%d" % (owner, pts))
        # 相邻未结算城堡视此为完成结构（CAR 页 100）
        for other in self.castles:
            if other is c or other["scored"]:
                continue
            if set(c["tiles"]) & set(other["adjacent"]):
                o = other["owner"]
                self._player_by_color(o).score += pts
                of = other["fig"]
                op = self._player_by_color(o)
                if of == "big":
                    op.big_meeples_left += 1
                elif of == "wagon":
                    op.wagon_left += 1
                elif of == "mayor":
                    op.mayor_left += 1
                elif of == "phantom":
                    op.phantom_left += 1
                else:
                    op.meeples_left += 1
                other["scored"] = True
                events.append(ScoreEvent(
                    kind="castle", reason="城堡回响", scores={o: pts},
                    detail="相邻城堡同等 %d 分" % pts, pos=other["tiles"][0]))

    def _start_bazaar(self) -> bool:
        n = len(self.players)
        if len(self.deck) < n:
            self._log("集市：牌不够，跳过拍卖")
            return False
        tiles = [self.deck.pop() for _ in range(n)]
        nxt = (self._placer_idx + 1) % n
        self.bazaar = {
            "phase": "select", "tiles": tiles, "selector": nxt,
            "bid": 0, "bidder": nxt, "passed": [],
            "got": {}, "trigger": self._placer_idx,
        }
        self._bazaar_ignore = True
        self.phase = "bazaar"
        self._log("🛒 集市开张：拍卖 %d 张牌" % n)
        return True

    def bazaar_select(self, idx: int, bid: int = 0) -> None:
        assert self.phase == "bazaar" and self.bazaar["phase"] == "select"
        tiles = self.bazaar["tiles"]
        assert 0 <= idx < len(tiles)
        self.bazaar["choice"] = idx
        self.bazaar["bid"] = max(0, int(bid))
        self.bazaar["bidder"] = self.bazaar["selector"]
        self.bazaar["passed"] = []
        self.bazaar["phase"] = "bid"
        self.bazaar["bid_turn"] = (self.bazaar["selector"] + 1) % len(self.players)
        self._bazaar_skip_done()
        self._bazaar_maybe_decide()

    def bazaar_bid(self, amount: int) -> None:
        assert self.phase == "bazaar" and self.bazaar["phase"] == "bid"
        amount = int(amount)
        assert amount > self.bazaar["bid"]
        self.bazaar["bid"] = amount
        self.bazaar["bidder"] = self.bazaar["bid_turn"]
        self.bazaar["bid_turn"] = (self.bazaar["bid_turn"] + 1) % len(self.players)
        self._bazaar_skip_done()
        self._bazaar_maybe_decide()

    def bazaar_pass(self) -> None:
        assert self.phase == "bazaar" and self.bazaar["phase"] == "bid"
        self.bazaar["passed"].append(self.bazaar["bid_turn"])
        self.bazaar["bid_turn"] = (self.bazaar["bid_turn"] + 1) % len(self.players)
        self._bazaar_skip_done()
        self._bazaar_maybe_decide()

    def bazaar_resolve(self, keep: bool) -> None:
        """选择者决定：True=付给最高出价者留下；False=卖给最高出价者。"""
        assert self.phase == "bazaar" and self.bazaar["phase"] == "decide"
        b = self.bazaar
        sel, high, pts = b["selector"], b["bidder"], b["bid"]
        tile = b["tiles"].pop(b["choice"])
        if keep:
            buyer, seller = sel, high
        else:
            buyer, seller = high, sel
        if pts and buyer != seller:
            self.players[buyer].score -= pts
            self.players[seller].score += pts
        elif pts and buyer == seller:
            self.players[buyer].score -= pts
        b["got"][buyer] = tile.tile_id
        self._log("🛒 %s 得牌 %s（%d 分）" % (self.players[buyer].name,
                                            tile.tile_id, pts))
        self._bazaar_after_lot()

    def _bazaar_skip_done(self) -> None:
        b = self.bazaar
        n = len(self.players)
        guard = 0
        while b["phase"] == "bid" and guard < n:
            guard += 1
            i = b["bid_turn"]
            if i == b["selector"] or i in b["got"] or i in b["passed"]:
                b["bid_turn"] = (i + 1) % n
                continue
            break

    def _bazaar_maybe_decide(self) -> None:
        b = self.bazaar
        n = len(self.players)
        remaining = [i for i in range(n)
                     if i != b["selector"] and i not in b["got"]
                     and i not in b["passed"]]
        if remaining:
            return
        if b["bidder"] == b["selector"] and b["bid"] == 0:
            # 无人加价：选择者以 0 分拿走
            b["phase"] = "decide"
            self.bazaar_resolve(True)
            return
        b["phase"] = "decide"

    def _bazaar_after_lot(self) -> None:
        b = self.bazaar
        left_players = [i for i in range(len(self.players)) if i not in b["got"]]
        if len(b["tiles"]) == 1 and len(left_players) == 1:
            tid = b["tiles"].pop().tile_id
            b["got"][left_players[0]] = tid
            self._log("🛒 %s 免费得最后一张 %s" % (
                self.players[left_players[0]].name, tid))
        if b["tiles"] and left_players:
            b["selector"] = left_players[0]
            b["phase"] = "select"
            b["bid"] = 0
            b["passed"] = []
            return
        order = []
        i = (b["trigger"] + 1) % len(self.players)
        for _ in range(len(self.players)):
            if i in b["got"]:
                order.append(i)
            i = (i + 1) % len(self.players)
        b["place_order"] = order
        b["phase"] = "place"
        self._bazaar_next_place()

    def _bazaar_next_place(self) -> bool:
        b = self.bazaar
        if not b or b.get("phase") != "place":
            return False
        if not b.get("place_order"):
            self.bazaar = None
            self._bazaar_ignore = False
            return False
        idx = b["place_order"].pop(0)
        tid = b["got"][idx]
        self.turn_idx = idx
        self.current_tile = tile_data.by_id(tid)
        self.phase = "place"
        self.placed_pos = None
        self.pending_completions = []
        self._log("🛒 %s 放置拍卖所得 %s" % (self.players[idx].name, tid))
        return True

    def _player_by_color(self, color: str) -> Player:
        for p in self.players:
            if p.color == color:
                return p
        raise KeyError(color)

    # ------------------------------------------------------------ 终局

    def final_scoring(self) -> List[ScoreEvent]:
        """终局计分：未完成特征 → 农场。幂等（重复调用返回空列表）。"""
        assert self.game_over
        if self._final_done:
            return []
        self._final_done = True
        events: List[ScoreEvent] = []

        # M18 伯爵城：终局计分前，等候区随从轮流移入（CAR 脚注 226）
        if "count" in self.expansions:
            self._count_final_redeploy()

        # 1) 未完成道路 / 城市 / 修道院
        for root in list(self.board.roots()):
            meta = self.board._meta[root]
            if meta.kind == KIND_ROAD and not meta.complete and meta.tiles:
                mage_here = (self.mage is not None
                             and self.board.find(self.mage) == root)
                witch_here = (self.witch is not None
                              and self.board.find(self.witch) == root)
                if meta.inns and not mage_here:
                    self._final_award(meta, 0, "final_road",
                                      "未完成客栈路：0 分（客栈）", events, root)
                else:
                    # M20：法师 +1 分/牌（客栈路被法师加持则 1 分/牌，脚注 419）
                    pts = len(meta.tiles) * (2 if mage_here else 1)
                    if witch_here:
                        pts = (pts + 1) // 2
                    self._final_award(meta, pts, "final_road",
                                      "未完成道路：%d 张牌%s%s" % (
                                          len(meta.tiles),
                                          "（法师 +1/牌）" if mage_here else "",
                                          "（女巫减半）" if witch_here else ""),
                                      events, root)
            elif meta.kind == KIND_CITY and not meta.complete and meta.tiles:
                # M20 围攻城终局 0 分（CAR 页 121）
                if meta.sieged:
                    self._final_award(meta, 0, "final_city",
                                      "未完成被围城：0 分（围攻）", events, root)
                    continue
                if meta.cathedrals:
                    self._final_award(meta, 0, "final_city",
                                      "未完成大教堂城：0 分（大教堂）", events, root)
                    continue
                mage_here = (self.mage is not None
                             and self.board.find(self.mage) == root)
                witch_here = (self.witch is not None
                              and self.board.find(self.witch) == root)
                pts = len(meta.tiles) + meta.pennants
                if mage_here:
                    pts += len(meta.tiles)   # 法师 +1 分/牌（旗帜不加）
                if witch_here:
                    pts = (pts + 1) // 2
                self._final_award(meta, pts, "final_city",
                                  "未完成城市：%d 张牌%s%s%s" % (
                                      len(meta.tiles),
                                      " + %d 旗帜" % meta.pennants
                                      if meta.pennants else "",
                                      "（法师 +1/牌）" if mage_here else "",
                                      "（女巫减半）" if witch_here else ""),
                                  events, root)
            elif meta.kind == KIND_MON:
                pos = (root[0], root[1])
                if not self.board.monastery_complete(pos):
                    pts = 1 + self.board.occupied_around(pos[0], pos[1])
                    self._final_award(meta, pts, "final_monastery",
                                      "未完成修道院：%d 张" % pts, events, root)

        # 2) 贸易商品：酒/谷/布各自最多者各得 10 分（平局均得）
        if "traders" in self.expansions:
            for g, gname in (("wine", "酒"), ("grain", "谷"), ("cloth", "布")):
                owned = {p.color: p.goods.get(g, 0) for p in self.players
                         if p.goods.get(g, 0) > 0}
                if not owned:
                    continue
                winners, _top = meeple_majority(owned)
                for w in winners:
                    self._player_by_color(w).score += 10
                ev = ScoreEvent(kind="goods", reason="贸易商品",
                                scores={w: 10 for w in winners},
                                meeples=dict(owned),
                                detail="%s商品最多：%d 个 → 10 分" % (gname,
                                                              max(owned.values())))
                events.append(ev)
                self._log("🏁 %s" % ev.detail)

        # 3) 农场（第三版口径）
        # 归一化 farm-city 相邻对到当前根
        normalized: Dict[Node, Set[Node]] = {}
        for fnode, cnode in self.board.farm_city_pairs:
            froot = self.board.find(fnode)
            croot = self.board.find(cnode)
            normalized.setdefault(froot, set()).add(croot)
        for root in list(self.board.roots()):
            meta = self.board._meta[root]
            if meta.kind != KIND_FARM or not meta.meeples:
                continue
            city_roots = normalized.get(root, set())
            n_cities = 0
            for croot in city_roots:
                if self.board._meta[croot].complete:
                    n_cities += 1
            # BCB：城堡按完成城计（4 分/座，猪 5；脚注 312）
            n_castles = 0
            if "bcb" in self.expansions:
                for c in self.castles:
                    cr = c.get("city_root")
                    if cr is not None and self.board.find(cr) in city_roots:
                        n_castles += 1
            # M18 猪倌：所在农场终局农夫 +1 分/城（脚注 247-251，每农场一次）
            herd = any(self.board.defs[p].pig_herd
                       for p in meta.tiles if p in self.board.defs)
            winners, _top = meeple_majority(meta.meeples)
            winners = self._hill_tiebreak(meta, winners)
            scores = {}
            for w in winners:
                per_city = (4 if meta.pigs.get(w, 0) > 0 else 3) + (1 if herd else 0)
                per_castle = (5 if meta.pigs.get(w, 0) > 0 else 4) + (1 if herd else 0)
                scores[w] = per_city * n_cities + per_castle * n_castles
                self._player_by_color(w).score += scores[w]
            scores = scores if (n_cities or n_castles) else {}
            taken = self.board.return_meeples(root)
            self._clear_fairy_if_returned(taken)
            from collections import Counter as _C
            self._return_taken(taken, self.board.pop_phantoms(root))
            taken_w = {c: n for (c, _s, _nd), n in _C(taken).items()}
            if not scores:
                continue  # 零分农场：农夫照样收回，但不产生计分事件
            ev = ScoreEvent(kind="farm", reason="农场计分", scores=scores,
                            meeples=taken_w,
                            detail="农场毗邻 %d 个完成城市" % n_cities +
                                   ("（含猪 +1/城）" if meta.pigs else "") +
                                   ("（含猪倌 +1/城）" if herd else ""))
            events.append(ev)
            self._log("终局农场：%s → %s" % (ev.detail, scores))
        # T&B：终局归还全部猪/建造者（对局结束，图形回 supply）
        if "traders" in self.expansions:
            for root in list(self.board.roots()):
                meta = self.board._meta[root]
                for color in list(meta.pigs):
                    self._player_by_color(color).pig_left += meta.pigs.pop(color)
                for color in list(meta.builders):
                    self._player_by_color(color).builder_left += meta.builders.pop(color)
        # A&M：终局归还市长/马车（粮仓留农场）
        if "abbey" in self.expansions:
            for root in list(self.board.roots()):
                meta = self.board._meta[root]
                for color in list(meta.mayors):
                    self._player_by_color(color).mayor_left += 1
                    meta.mayors.pop(color)
                for color in list(meta.wagons):
                    self._player_by_color(color).wagon_left += 1
                    meta.wagons.pop(color)
        # BCB：未完成城堡无分，随从归还（CAR 页 100）
        if "bcb" in self.expansions:
            for c in self.castles:
                if c["scored"]:
                    continue
                p = self._player_by_color(c["owner"])
                fig = c["fig"]
                if fig == "big":
                    p.big_meeples_left += 1
                elif fig == "wagon":
                    p.wagon_left += 1
                elif fig == "mayor":
                    p.mayor_left += 1
                elif fig == "phantom":
                    p.phantom_left += 1
                else:
                    p.meeples_left += 1
                c["scored"] = True
        # M18 国王与强盗男爵：持有者 1 分/场上完成城（CAR 页 70，含伯爵城；
        # 脚注 198 城堡不算）
        if "king" in self.expansions:
            castle_roots = set()
            for c in self.castles:
                if c.get("city_root") is not None:
                    castle_roots.add(self.board.find(c["city_root"]))
            n_city = sum(1 for root in self.board.roots()
                         if self.board._meta[root].kind == KIND_CITY
                         and self.board._meta[root].tiles
                         and self.board._meta[root].open_edges == 0
                         and root not in castle_roots)
            n_road = sum(1 for root in self.board.roots()
                         if self.board._meta[root].kind == KIND_ROAD
                         and self.board._meta[root].tiles
                         and self.board._meta[root].open_edges == 0)
            if self.king.get("holder") and n_city:
                w = self.king["holder"]
                self._player_by_color(w).score += n_city
                events.append(ScoreEvent(
                    kind="king", reason="国王", scores={w: n_city},
                    meeples={}, detail="国王持有者：%d 个完成城 ×1 分" % n_city))
                self._log("👑 终局国王：%s + %d" % (w, n_city))
            if self.robber.get("holder") and n_road:
                w = self.robber["holder"]
                self._player_by_color(w).score += n_road
                events.append(ScoreEvent(
                    kind="robber", reason="强盗男爵", scores={w: n_road},
                    meeples={}, detail="强盗男爵持有者：%d 条完成路 ×1 分" % n_road))
                self._log("🗡 终局强盗男爵：%s + %d" % (w, n_road))
        # M20 金矿：拾得金块按数量梯价计分（1-3:1 / 4-6:2 / 7-9:3 / 10+:4）
        if "goldmines" in self.expansions:
            for p in self.players:
                k = p.gold_pieces
                if not k:
                    continue
                per = 1 if k <= 3 else 2 if k <= 6 else 3 if k <= 9 else 4
                pts = k * per
                p.score += pts
                events.append(ScoreEvent(
                    kind="gold", reason="金块", scores={p.color: pts},
                    meeples={}, detail="%d 块金子 × %d 分" % (k, per)))
                self._log("🪙 终局金子：%s %d 块 × %d = %d 分"
                          % (p.name, k, per, pts))
        # M21 命运之轮：王冠位随从归还（不计分）
        if "wheel" in self.expansions:
            for sector, riders in self.crowns.items():
                for r in riders:
                    p = self._player_by_color(r["color"])
                    p.meeples_left += 1
                self.crowns[sector] = []
        # M21 山丘与羊：终局牧羊人不计分，回家（CAR 页 104）
        if "hillsheep" in self.expansions:
            for s in list(self.shepherds):
                self.sheep_bag.extend(s["tokens"])
                s["tokens"] = []
                self.shepherds.remove(s)
                self._player_by_color(s["color"]).shepherd_left += 1
        # M21 塔：驻塔随从归还供给（人质不归还，CAR 页 55）
        if "tower" in self.expansions:
            self._towers_return_tops()
        # M20 强盗：仍在轨上的强盗各 +3 分后归还（脚注 487）
        if "robbers" in self.expansions and self.robbers:
            for color in list(self.robbers):
                self._player_by_color(color).score += 3
                self._log("🦹 终局强盗：%s +3" % color)
            self.robbers = {}
        return events

    def _count_final_redeploy(self) -> None:
        """终局计分前的伯爵城重部署（CAR 脚注 226）。

        从放置末牌者的下家开始轮流，每人每轮移 1 名随从，直到无人再移；
        目标 = 同类未完成特征且移入后己方构成多数/平局（有利才移）。
        """
        qkind = {"castle": KIND_CITY, "blacksmith": KIND_ROAD,
                 "cathedral": KIND_MON, "market": KIND_FARM}
        start = (self._placer_idx + 1) % len(self.players)
        progressed = True
        rounds = 0
        while progressed and rounds < 64:
            rounds += 1
            progressed = False
            for i in range(len(self.players)):
                idx = (start + i) % len(self.players)
                p = self.players[idx]
                for q, kind in qkind.items():
                    if self.count["count_pos"] == q:
                        continue
                    fs = self.count["quarters"][q]
                    mine = [f for f in fs if f[0] == p.color]
                    if not mine:
                        continue
                    hit = self._best_final_target(kind, p.color, mine[0][1])
                    if hit is None:
                        continue
                    fs.remove(mine[0])
                    self._count_figure_into(hit, mine[0][1], p.color)
                    self._log("🏁 终局重部署：%s 1 名随从 %s区 → (%s)"
                              % (p.name, q, hit))
                    progressed = True
                    break

    def _best_final_target(self, kind: str, color: str, fig: str) -> Optional[Node]:
        """终局重部署目标：移入后己方构成多数/平局的同类未完成特征。"""
        best, best_key = None, None
        for root in self.board.roots():
            meta = self.board._meta[root]
            if meta.kind != kind or meta.scored:
                continue
            if kind == KIND_ROAD and meta.inns:
                continue   # 未完成客栈路终局 0 分
            if kind == KIND_CITY and meta.cathedrals:
                continue   # 未完成大教堂城终局 0 分
            if kind == KIND_MON and self.board.monastery_complete(
                    (root[0], root[1])):
                continue
            votes: Dict[str, int] = {}
            for node, c, size in meta.meeple_nodes:
                votes[c] = votes.get(c, 0) + (2 if size == 2 else 1)
            votes[color] = votes.get(color, 0) + (2 if fig == "big" else 1)
            top = max(votes.values())
            if votes[color] < top:
                continue   # 移入仍非多数/平局 → 无益
            key = (votes[color], len(meta.tiles))
            if best_key is None or key > best_key:
                best, best_key = root, key
        return best

    def _final_award(self, meta, pts: int, kind: str, detail: str,
                     events: List[ScoreEvent], root: Optional[Node] = None) -> None:
        if not meta.meeples:
            return
        winners, _top = meeple_majority(meta.meeples)
        winners = self._hill_tiebreak(meta, winners)
        scores = {w: pts for w in winners}
        for w in winners:
            if "robbers" in self.expansions and pts > 0:
                self._steal_for_robbers(w, pts, events)
            else:
                self._player_by_color(w).score += pts
        rep_node = meta.meeple_nodes[0][0]
        taken = self.board.return_meeples(rep_node)
        self._clear_fairy_if_returned(taken)
        from collections import Counter as _C
        self._return_taken(taken, self.board.pop_phantoms(rep_node))
        pos = (root[0], root[1]) if root else None
        ev = ScoreEvent(kind=kind, reason=detail, scores=scores,
                        meeples={c: n for (c, _s, _nd), n in _C(taken).items()},
                        detail=detail, pos=pos)
        events.append(ev)
        self._log("终局：%s → %s" % (detail, scores))

    # ------------------------------------------------------------ 快照（联机）

    def snapshot_dict(self, log_tail: int = 40) -> Dict[str, object]:
        """序列化为 JSON 可传输的快照（权威状态 → 客户端渲染副本）。

        摸牌堆只传剩余数量（不泄露牌序）；current_tile 为公共信息。
        """
        meeples = []
        figures = []
        for root in self.board.roots():
            meta = self.board._meta[root]
            for node, color, size in meta.meeple_nodes:
                meeples.append({"x": node[0], "y": node[1], "kind": node[2],
                                "seg": node[3], "color": color, "size": size,
                                "ph": node in meta.phantoms})
            for node, color in self._iter_figure_nodes(root, "builders"):
                figures.append({"x": node[0], "y": node[1], "kind": node[2],
                                "seg": node[3], "color": color, "fig": "builder"})
            for node, color in self._iter_figure_nodes(root, "pigs"):
                figures.append({"x": node[0], "y": node[1], "kind": node[2],
                                "seg": node[3], "color": color, "fig": "pig"})
            for attr, fig in (("mayors", "mayor"), ("wagons", "wagon")):
                meta = self.board._meta[root]
                d = getattr(meta, attr, {})
                for color, node in d.items():
                    figures.append({"x": node[0], "y": node[1], "kind": node[2],
                                    "seg": node[3], "color": color, "fig": fig})
        return {
            "players": [{
                "name": p.name, "color": p.color, "is_ai": p.is_ai,
                "ai_level": p.ai_level, "score": p.score,
                "meeples_left": p.meeples_left,
                "big_meeples_left": p.big_meeples_left,
                "builder_left": p.builder_left, "pig_left": p.pig_left,
                "mayor_left": p.mayor_left, "barn_left": p.barn_left,
                "wagon_left": p.wagon_left,
                "bridges_left": p.bridges_left, "castles_left": p.castles_left,
                "phantom_left": p.phantom_left,
                "tunnels_left": p.tunnels_left,
                "towers_left": p.towers_left,
                "shepherd_left": p.shepherd_left,
                "gold_pieces": p.gold_pieces,
                "goods": dict(p.goods),
            } for p in self.players],
            "expansions": list(self.expansions),
            "figures": figures,
            "fairy": dict(self.fairy),
            "dragon": {"pos": list(self.dragon["pos"]) if self.dragon["pos"] else None,
                       "active": self.dragon["active"],
                       "steps_left": self.dragon["steps_left"],
                       "decider": self.dragon["decider"],
                       "visited": [list(v) for v in self.dragon["visited"]]},
            "volcano_turn": self._volcano_turn,
            "extra_turn": self._extra_turn,
            "turn_idx": self.turn_idx,
            "placer_idx": self._placer_idx,
            "phase": self.phase,
            "game_over": self.game_over,
            "deck_len": len(self.deck),
            "river_left": len(self.river_pile),
            "king": dict(self.king),
            "robber": dict(self.robber),
            "challenges": [{"shrine": list(ch["shrine"]),
                            "monastery": list(ch["monastery"])}
                           for ch in self.challenges],
            "count": {"quarters": {q: [list(f) for f in fs]
                                   for q, fs in self.count["quarters"].items()},
                      "count_pos": self.count["count_pos"]},
            "redeploy": ({"root": list(self.redeploy["root"]),
                          "order": list(self.redeploy["order"]),
                          "pos": self.redeploy["pos"]}
                         if self.redeploy else None),
            "bridges": [{"x": p[0], "y": p[1], "axis": a}
                        for p, a in self.board.bridges.items()],
            "castles": [{
                "owner": c["owner"], "fig": c["fig"],
                "tiles": [list(t) for t in c["tiles"]],
                "adjacent": [list(t) for t in c["adjacent"]],
                "city_root": list(c["city_root"]) if c.get("city_root") else None,
                "scored": c["scored"],
                "built_turn": list(c["built_turn"]),
            } for c in self.castles],
            "castle_queue": [list(r) for r in self._castle_queue],
            "bazaar": (None if not self.bazaar else {
                "phase": self.bazaar["phase"],
                "tiles": [t.tile_id if hasattr(t, "tile_id") else t
                          for t in self.bazaar.get("tiles", [])],
                "selector": self.bazaar.get("selector"),
                "bid": self.bazaar.get("bid", 0),
                "bidder": self.bazaar.get("bidder"),
                "passed": list(self.bazaar.get("passed") or []),
                "got": {str(k): v for k, v in (self.bazaar.get("got") or {}).items()},
                "trigger": self.bazaar.get("trigger"),
                "choice": self.bazaar.get("choice"),
                "bid_turn": self.bazaar.get("bid_turn"),
                "place_order": list(self.bazaar.get("place_order") or []),
            }),
            "current_tile": self.current_tile.tile_id if self.current_tile else None,
            "placed": [{
                "x": t.x, "y": t.y, "rot": t.rot, "tile": t.tile_id,
                "by": t.placed_by,
            } for t in self.board.tiles.values()],   # dict 保持放置顺序
            "meeples": meeples,
            "mage": list(self.mage) if self.mage else None,
            "witch": list(self.witch) if self.witch else None,
            "robbers": dict(self.robbers),
            "gold_map": {("%d,%d" % k): v for k, v in self.gold_map.items()},
            "tunnel_tokens": {("%d,%d,%d,%s" % (k[0], k[1], k[3], k[2])): v
                              for k, v in self.board.tunnel_tokens.items()},
            "tunnel_open": {c: list(n) for c, n in self.tunnel_open.items()},
            "crop": (None if not self.crop else {
                "kind": self.crop["kind"], "mode": self.crop["mode"],
                "order": list(self.crop["order"]), "pos": self.crop["pos"]}),
            "robber_phase": (None if not self.robber_phase else {
                "order": list(self.robber_phase["order"]),
                "pos": self.robber_phase["pos"]}),
            "mini_queue": list(self._mini_queue),
            "phantom_step": self._phantom_step,
            "wheel_pig": self.wheel_pig,
            "crowns": {str(k): [dict(r) for r in v]
                       for k, v in self.crowns.items()},
            "plague": (None if not self.plague else
                       {"order": list(self.plague["order"]),
                        "pos": self.plague["pos"]}),
            "towers": [{"pos": list(t["pos"]), "height": t["height"],
                        "top": (dict(t["top"]) if t.get("top") else None)}
                       for t in self.towers],
            "hills": [list(h) for h in self.hills],
            "shepherds": [{"color": s["color"], "node": list(s["node"]),
                           "tokens": list(s["tokens"])}
                          for s in self.shepherds],
            "sheep_bag": {str(v): self.sheep_bag.count(v)
                          for v in set(self.sheep_bag)},
            "shepherd_phase": self.phase == "shepherd",
            "hostages": [dict(h) for h in self.hostages],
            "ransom_used": self._ransom_used,
            "log_tail": self.log_lines[-log_tail:],
            "winner": self.winner_text() if self.game_over else None,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, object]) -> "CarcassonneEngine":
        """从快照重建显示副本：按放置顺序重放并查集，再重放在场米宝。

        只用于客户端渲染与本地交互预判，不用于权威结算。
        """
        from . import tile_data as td
        eng = cls.__new__(cls)
        eng.rng = random.Random(0)
        eng.board = Board()
        eng.players = []
        for i, p in enumerate(d["players"]):
            eng.players.append(Player(
                idx=i, name=p["name"], color=p["color"], is_ai=p["is_ai"],
                ai_level=p.get("ai_level", "normal"), score=p["score"],
                meeples_left=p["meeples_left"],
                big_meeples_left=p.get("big_meeples_left", 0),
                builder_left=p.get("builder_left", 0),
                pig_left=p.get("pig_left", 0),
                mayor_left=p.get("mayor_left", 0),
                barn_left=p.get("barn_left", 0),
                wagon_left=p.get("wagon_left", 0),
                bridges_left=p.get("bridges_left", 0),
                castles_left=p.get("castles_left", 0),
                phantom_left=p.get("phantom_left", 0),
                tunnels_left=p.get("tunnels_left", 0),
                towers_left=p.get("towers_left", 0),
                shepherd_left=p.get("shepherd_left", 0),
                gold_pieces=p.get("gold_pieces", 0),
                goods=dict(p.get("goods") or {})))
        eng.deck = [td.start_tile()] * int(d["deck_len"])   # 占位，客户端不摸牌
        eng.expansions = list(d.get("expansions") or [])
        eng._extra_turn = bool(d.get("extra_turn"))
        eng._aside_tiles = []
        eng._volcano_turn = bool(d.get("volcano_turn"))
        eng.fairy = dict(d.get("fairy") or {"pos": None, "node": None, "owner": None})
        if eng.fairy.get("node"):
            eng.fairy["node"] = tuple(eng.fairy["node"])
        if eng.fairy.get("pos"):
            eng.fairy["pos"] = tuple(eng.fairy["pos"])
        dg = d.get("dragon") or {}
        eng.dragon = {"pos": tuple(dg["pos"]) if dg.get("pos") else None,
                      "active": bool(dg.get("active")),
                      "steps_left": int(dg.get("steps_left", 0)),
                      "decider": int(dg.get("decider", 0)),
                      "visited": [tuple(v) for v in dg.get("visited", [])]}
        eng._volcano_turn = bool(d.get("volcano_turn"))
        eng.current_tile = td.by_id(d["current_tile"]) if d["current_tile"] else None
        eng.turn_idx = int(d["turn_idx"])
        eng._placer_idx = int(d.get("placer_idx", eng.turn_idx))
        eng.phase = d["phase"]
        eng.game_over = bool(d["game_over"])
        eng.king = dict(d.get("king") or {"holder": None, "size": 0})
        eng.robber = dict(d.get("robber") or {"holder": None, "size": 0})
        eng.challenges = [
            {"shrine": tuple(ch["shrine"]),
             "monastery": tuple(ch["monastery"])}
            for ch in d.get("challenges") or []]
        ct = d.get("count") or {}
        eng.count = {"quarters": {q: [list(f) for f in fs]
                                  for q, fs in (ct.get("quarters") or
                                                eng.count["quarters"]).items()},
                     "count_pos": ct.get("count_pos", "castle")}
        rd = d.get("redeploy")
        eng.redeploy = ({"root": tuple(rd["root"]), "order": list(rd["order"]),
                         "pos": int(rd["pos"])} if rd else None)
        eng._count_queue = []
        eng._count_trigger = False
        eng._placer_scored = False
        eng._river_volcano = False
        # 河流：副本只保留剩余数量（占位牌，不参与客户端摸牌）
        eng.river_pile = []
        if "river" in eng.expansions:
            eng._river_on = True
            eng.river_pile = [td.by_id("RI-Junction")] * int(d.get("river_left", 0))
        else:
            eng._river_on = False
        eng.pending_completions = []
        eng.events = []
        eng.log_lines = list(d["log_tail"])
        eng.round_count = 0
        eng._final_done = bool(d.get("game_over"))
        for t in d["placed"]:
            eng.board.add_tile(PlacedTile(t["tile"], t["x"], t["y"], t["rot"],
                                          t["by"]), td.by_id(t["tile"]),
                               loose=True)
        for br in d.get("bridges") or []:
            eng.board.add_bridge((br["x"], br["y"]), int(br["axis"]), force=True)
        eng.castles = []
        for c in d.get("castles") or []:
            cr = c.get("city_root")
            eng.castles.append({
                "owner": c["owner"], "fig": c["fig"],
                "tiles": [tuple(t) for t in c["tiles"]],
                "adjacent": [tuple(t) for t in c.get("adjacent") or []],
                "city_root": tuple(cr) if cr else None,
                "scored": bool(c.get("scored")),
                "built_turn": tuple(c.get("built_turn") or (0, 0)),
            })
        bz = d.get("bazaar")
        if bz:
            tiles = []
            for tid in bz.get("tiles") or []:
                tiles.append(td.by_id(tid) if isinstance(tid, str) else tid)
            got = {}
            for k, v in (bz.get("got") or {}).items():
                got[int(k)] = v
            eng.bazaar = dict(bz)
            eng.bazaar["tiles"] = tiles
            eng.bazaar["got"] = got
        else:
            eng.bazaar = None
        eng._castle_queue = [tuple(r) for r in d.get("castle_queue") or []]
        eng._needed_bridge = {}
        # M20 迷你扩展状态恢复
        eng.mage = tuple(d["mage"]) if d.get("mage") else None
        eng.witch = tuple(d["witch"]) if d.get("witch") else None
        eng.robbers = dict(d.get("robbers") or {})
        eng.gold_map = {tuple(int(v) for v in k.split(",")): n
                        for k, n in (d.get("gold_map") or {}).items()}
        eng.board.tunnel_tokens = {}
        for k, c in (d.get("tunnel_tokens") or {}).items():
            xs, ys, seg, kind = k.split(",")
            eng.board.tunnel_tokens[(int(xs), int(ys), kind, int(seg))] = c
        eng.tunnel_open = {c: tuple(n)
                           for c, n in (d.get("tunnel_open") or {}).items()}
        cp = d.get("crop")
        eng.crop = None if not cp else dict(cp)
        rp = d.get("robber_phase")
        eng.robber_phase = None if not rp else dict(rp)
        eng._mini_queue = list(d.get("mini_queue") or [])
        eng._phantom_step = bool(d.get("phantom_step"))
        eng._phantom_done = bool(eng._phantom_step)
        eng.towers = [{"pos": tuple(t["pos"]), "height": int(t["height"]),
                       "top": (dict(t["top"]) if t.get("top") else None)}
                      for t in d.get("towers") or []]
        eng.hostages = [dict(h) for h in d.get("hostages") or []]
        eng._ransom_used = bool(d.get("ransom_used"))
        eng._tower_pending = None
        eng.wheel_pig = int(d.get("wheel_pig", 0))
        eng.crowns = {i: [] for i in range(6)}
        for k, riders in (d.get("crowns") or {}).items():
            eng.crowns[int(k)] = [dict(r) for r in riders]
        pl = d.get("plague")
        eng.plague = None if not pl else dict(pl)
        eng.hills = set(tuple(h) for h in d.get("hills") or [])
        eng.shepherds = [{"color": s["color"], "node": tuple(s["node"]),
                          "tokens": list(s["tokens"])}
                         for s in d.get("shepherds") or []]
        bag = d.get("sheep_bag") or {}
        eng.sheep_bag = []
        for v, n in bag.items():
            eng.sheep_bag.extend([int(v)] * int(n))
        eng._built_bridge = False
        eng._bazaar_ignore = bool(eng.bazaar)
        eng._pending_bazaar = False
        eng._count_block = {(t["x"], t["y"]) for t in d["placed"]
                            if td.by_id(t["tile"]).count_city}
        eng._count_city_root = (eng.board.find((0, 0, KIND_CITY, 0))
                                if eng._count_block else None)
        for m in d["meeples"]:
            # force：快照中的米宝可能属于已合并的特征，重放时不做占用检查
            eng.board.deploy_meeple((m["x"], m["y"], m["kind"], m["seg"]),
                                    m["color"], size=m.get("size", 1),
                                    force=True, phantom=bool(m.get("ph")))
        for f in d.get("figures") or []:
            node = (f["x"], f["y"], f["kind"], f["seg"])
            if f["fig"] == "builder":
                eng.board.deploy_builder(node, f["color"])
            elif f["fig"] == "mayor":
                eng.board.deploy_mayor(node, f["color"])
            elif f["fig"] == "wagon":
                eng.board.deploy_wagon(node, f["color"])
            else:
                eng.board.deploy_pig(node, f["color"])
        if eng.phase in ("deploy", "gold", "magewitch", "tunnel", "escape",
                         "crop", "robber", "shepherd") and eng.board.tiles:
            last = list(eng.board.tiles.values())[-1]
            eng.placed_pos = (last.x, last.y)
        else:
            eng.placed_pos = None
        # 牧羊行动阶段：重建待行动草场
        eng._shepherd_pending = []
        if eng.phase == "shepherd" and "hillsheep" in eng.expansions                 and eng.current_tile is not None and eng.placed_pos:
            from .board import KIND_FARM as _KF
            for i in range(len(eng.current_tile.farms)):
                node = (eng.placed_pos[0], eng.placed_pos[1], _KF, i)
                root = eng.board.find(node)
                for s in eng.shepherds:
                    if s["color"] == eng.players[eng.turn_idx].color                             and eng.board.find(s["node"]) == root:
                        eng._shepherd_pending.append(root)
                        break
        return eng

    def _hill_tiebreak(self, meta, winners: List[str]) -> List[str]:
        """山丘平局破缺（CAR 页 105）：平局中恰有一方有山丘随从 → 独得。"""
        if len(winners) <= 1:
            return winners
        hill_hits = []
        for w in winners:
            n = sum(1 for node, c, _s in meta.meeple_nodes
                    if c == w and (node[0], node[1]) in self.hills)
            hill_hits.append(n > 0)
        if sum(1 for h in hill_hits if h) == 1:
            return [winners[hill_hits.index(True)]]
        return winners

    def _city_majority(self, meta) -> Tuple[List[str], int]:
        """城特征多数（A&M）：普通米宝 1、大 2、市长 = 所在段旗数。"""
        from collections import Counter as _C
        votes: Dict[str, int] = {}
        for node, color, size in meta.meeple_nodes:
            votes[color] = votes.get(color, 0) + (2 if size == 2 else 1)
        for color, mnode in meta.mayors.items():
            pos = (mnode[0], mnode[1])
            seg = mnode[3]
            d = self.board.defs.get(pos)
            rot = self.board.tiles[pos].rot if pos in self.board.tiles else 0
            penn = 0
            if d:
                try:
                    penn = 1 if d.rotated_cities(rot)[seg][1] else 0
                except (IndexError, AssertionError):
                    penn = 0
            votes[color] = votes.get(color, 0) + penn
        if not votes:
            return [], 0
        top = max(votes.values())
        return [c for c, n in votes.items() if n == top], top

    def _clear_fairy_if_returned(self, taken) -> None:
        """归还的米宝中含仙女绑定者 → 仙女留原地但解除绑定（效果失效）。"""
        if "pd" not in self.expansions or not self.fairy.get("node"):
            return
        fn = self.fairy["node"]
        for _color, _size, node in taken:
            if node == fn:
                self.fairy["node"] = None
                self._log("✨ 仙女的跟随者离开，仙女仍在原地但失去绑定")
                return

    def _iter_figure_nodes(self, root: Node, attr: str):
        """遍历特征上某图元的 (节点, 色名)。图元不跟随并查集移动，
        以登记时节点为准（渲染与快照用）。"""
        meta = self.board._meta[root]
        d = getattr(meta, attr, None) or {}
        for color in list(d):
            nodes = meta.figure_nodes.get((attr, color), [])
            for node in nodes:
                yield node, color

    # ------------------------------------------------------------ 结果

    def standings(self) -> List[Player]:
        return sorted(self.players, key=lambda p: -p.score)

    def winner_text(self) -> str:
        top = self.standings()[0].score
        winners = [p.name for p in self.players if p.score == top]
        return "、".join(winners) + (" 共同获胜" if len(winners) > 1 else " 获胜")
