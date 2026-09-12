# -*- coding: utf-8 -*-
"""AI 玩家：三档难度（easy / normal / hard）。

接口：choose_move(engine) -> ((x, y, rot), deploy | None)
- easy:   随机合法放置，30% 概率随机部署
- normal: 静态启发式贪心（即时得分 > 延伸己方 > 高价值新区 > 修道院 > 农夫）
- hard:   normal + 阻断对手（争夺多数/平局）+ 农场终局估值 + 避免送分

全部通过 engine 公开接口决策，不修改引擎状态；出牌保证合法。
"""
from __future__ import annotations

import random
from typing import Dict, List, Optional, Tuple

from .board import KIND_CITY, KIND_FARM, KIND_MON, KIND_ROAD
from .engine import CarcassonneEngine
from .models import OPPOSITE, TileDef

Move = Tuple[Tuple[int, int, int], Optional[Tuple[str, int]]]


class BotAI:
    def __init__(self, level: str = "normal", seed: Optional[int] = None):
        assert level in ("easy", "normal", "hard")
        self.level = level
        self.rng = random.Random(seed)

    # ------------------------------------------------------------ 入口

    def choose_move(self, eng: CarcassonneEngine) -> Move:
        placements = eng.legal_placements()
        assert placements, "无合法放置（应由引擎弃牌重抽流程处理）"
        if self.level == "easy":
            return self._easy(eng, placements)
        return self._greedy(eng, placements)

    def choose_redeploy(self, eng: CarcassonneEngine) -> bool:
        """伯爵城重部署回合：本区有己方随从则全部移入（移入只会增益）。"""
        st = eng.redeploy_state()
        if not st:
            return False
        color = eng.players[st["player"]].color
        return any(f[0] == color for f in eng.count["quarters"][st["quarter"]])

    def choose_count_deploy(self, eng: CarcassonneEngine) -> Optional[dict]:
        """进城部署启发：随从充裕时优先放市场区/城堡区；伯爵移向等候最少的区。"""
        opts = eng.count_deploy_options()
        if not opts:
            return None
        p = eng.players[eng._placer_idx]
        if p.meeples_left <= 2:
            return None
        for o in opts:
            if o["fig"] == "meeple" and o["quarter"] == "market":
                return {"option": o, "count_move_to": None}
        for o in opts:
            if o["fig"] == "meeple" and o["quarter"] == "castle":
                return {"option": o, "count_move_to": None}
        return None

    def choose_castle(self, eng: CarcassonneEngine) -> bool:
        """小城改建：hard/normal 改建（延迟得分），easy 立即结算。"""
        return self.level != "easy"

    # ---- M20 迷你扩展决策 ----

    def choose_gold(self, eng: CarcassonneEngine) -> Tuple[int, int]:
        """金块第二落位：优先落在己方随从所在/邻近的牌（简化：随机邻牌）。"""
        return self.rng.choice(eng.gold_options())

    def choose_mw(self, eng: CarcassonneEngine):
        """法师/女巫落位：优先己方占多数的未完成城/路（女巫优先对手特征）。"""
        opts = eng.mw_options()
        player = eng.current_player()
        best = None
        for fig in ("mage", "witch"):
            for node in opts[fig]:
                meta = eng.board._meta[eng.board.find(node)]
                mine = meta.meeples.get(player.color, 0)
                opp = sum(n for c, n in meta.meeples.items()
                          if c != player.color)
                score = mine if fig == "mage" else opp * 2
                if best is None or score > best[0]:
                    best = (score, fig, node)
        if best is not None:
            return (best[1], best[2])
        # 无目标：收回在场图元（引擎阶段推进要求）
        if eng.mage is not None:
            return ("mage", None)
        return ("witch", None)

    def choose_tunnel(self, eng: CarcassonneEngine) -> Optional[Node]:
        """隧道令牌：优先占刚放牌上的口（简化：取第一个）。"""
        opts = eng.tunnel_options()
        return opts[0] if opts else None

    def choose_crop(self, eng: CarcassonneEngine):
        """怪圈：主动玩家随从少于 3 时选 A（补充兵力）否则 B（削弱全场）。"""
        if not eng.crop:
            return None
        if eng.crop["mode"] is None:
            me = eng.current_player()
            return "A" if me.meeples_left < 3 else "B"
        opts = eng.crop_options()
        if not opts:
            return None   # A 可跳过 / B 无随从自动过
        return opts[0]["node"]

    def choose_robber(self, eng: CarcassonneEngine) -> Optional[int]:
        """强盗上轨：挑对手最高分格（对手随从在场的最高分）。"""
        spaces = eng.robber_options()
        if not spaces:
            return None
        return max(spaces)

    def choose_escape(self, eng: CarcassonneEngine) -> Optional[Node]:
        """围攻脱困：有机会就撤。"""
        opts = eng.escape_options()
        return opts[0] if opts else None

    def choose_tower_piece(self, eng: CarcassonneEngine):
        """建塔：优先能抓到对手随从的塔位；无目标也可建（防御）。"""
        opts = eng.tower_piece_options()
        if not opts:
            return None
        me = eng.current_player().color
        best = None
        for pos, captures in opts:
            gain = 0
            for node in captures:
                meta = eng.board._meta[eng.board.find(node)]
                for n, c, _s in meta.meeple_nodes:
                    if n == node and c != me:
                        gain += 1
            if best is None or gain > best[0]:
                best = (gain, pos, captures)
        gain, pos, captures = best
        if gain > 0:
            victim = next(n for n in captures
                          if eng.board._meta[eng.board.find(n)].meeples.get(
                              [m for m in eng.players
                               if m.color != me][0].color, 0) > 0)
            return (pos, victim)
        # 无目标：50% 概率仍建塔（占位防御）
        return (pos, None) if self.rng.random() < 0.5 else None

    def choose_tower_top(self, eng: CarcassonneEngine) -> Optional[Tuple[int, int]]:
        """驻塔：己方随从 ≤2 时留一人驻塔防抓。"""
        opts = eng.tower_top_options()
        if not opts:
            return None
        me = eng.current_player()
        return opts[0] if me.meeples_left <= 2 and self.rng.random() < 0.6             else None

    def choose_plague(self, eng: CarcassonneEngine) -> Optional[Node]:
        """瘟疫：收回第一枚己方场上随从（无则跳过）。"""
        opts = eng.plague_options()
        return opts[0] if opts else None

    def choose_shepherd(self, eng: CarcassonneEngine) -> bool:
        """牧羊行动：羊群 ≥4 只先入圈落袋；否则扩群博一把。"""
        root = eng.shepherd_pending_action()
        if root is None:
            return True
        total = sum(sum(s["tokens"]) for s in eng._field_shepherds(root))
        return total < 4

    def choose_ransom(self, eng: CarcassonneEngine) -> Optional[int]:
        """赎金：随从紧缺（≤2）时赎回第一名人质。"""
        opts = eng.ransom_options()
        if not opts:
            return None
        me = eng.current_player()
        return opts[0] if me.meeples_left + me.big_meeples_left <= 2 else None

    def choose_bazaar(self, eng: CarcassonneEngine):
        """集市决策：选第一张可用牌；出价阶段过；决定阶段卖掉。"""
        b = eng.bazaar
        if not b:
            return None
        if b["phase"] == "select":
            return ("select", 0, 0)
        if b["phase"] == "bid":
            return ("pass",)
        if b["phase"] == "decide":
            return ("resolve", False)
        return None

    def choose_dragon_step(self, eng: CarcassonneEngine,
                           legal: List[Tuple[int, int]]) -> Tuple[int, int]:
        """龙移动决策：贪心走向最近非己方图元，远离己方密集区。"""
        my = eng.current_player().color
        best, best_s = None, None
        for pos in legal:
            # 评估：该格邻近 2 格内的敌我图元数
            enemy = ally = 0
            for root in eng.board.roots():
                meta = eng.board._meta[root]
                for node, color, _s in meta.meeple_nodes:
                    d = abs(node[0] - pos[0]) + abs(node[1] - pos[1])
                    if d <= 2:
                        if color == my:
                            ally += 1
                        else:
                            enemy += 1
                    elif d <= 3 and color != my:
                        enemy += 0.4
            s = enemy * 2 - ally * 3 + self.rng.random() * 0.5
            if best_s is None or s > best_s:
                best_s, best = s, pos
        return best or (legal[0] if legal else None)

    def choose_fairy_pos(self, eng: CarcassonneEngine,
                         options: List[Dict[str, object]]) -> Optional[Dict[str, object]]:
        """仙女移动：优先保护龙 2 步内可达的己方图元。"""
        dpos = eng.dragon.get("pos")
        best, best_s = None, -1.0
        for o in options:
            pos = o.get("pos")
            if not pos:
                continue
            s = 1.0
            if dpos:
                d = abs(pos[0] - dpos[0]) + abs(pos[1] - dpos[1])
                s += 3.0 if d <= 2 else 0.0
            if s > best_s:
                best_s, best = s, o
        return best

    def choose_princess_victim(self, eng: CarcassonneEngine,
                               options: List[Dict[str, object]]) -> Optional[Dict[str, object]]:
        """公主：移走对手骑士（优先大城），无对手骑士则不移。"""
        my = eng.current_player().color
        best, best_s = None, 0.0
        for o in options:
            if o.get("kind") != "princess":
                continue
            vc = o.get("victim_color")
            if vc == my:
                continue
            node = o.get("node")
            meta = eng.board.meta(node)
            s = float(len(meta.tiles))
            if s > best_s:
                best_s, best = s, o
        return best

    def choose_deploy(self, eng: CarcassonneEngine) -> Optional[Dict[str, object]]:
        """deploy 阶段决策（放置后调用）。返回选项 dict 或 None（跳过）。

        命运之轮：15% 概率上架空闲王冠位（防御性站坑）。
        """
        options = eng.deploy_options()
        if not options:
            return None
        if "wheel" in eng.expansions and self.rng.random() < 0.15:
            crowns = [o for o in options if o["kind"] == "crown"]
            if crowns:
                return self.rng.choice(crowns)
        if self.level == "easy":
            return self.rng.choice(options) if self.rng.random() < 0.3 else None
        return self._best_deploy(eng, options)

    # ------------------------------------------------------------ easy

    def _easy(self, eng: CarcassonneEngine, placements) -> Move:
        return self.rng.choice(placements), None

    # ------------------------------------------------------------ 静态分析

    def _prospects(self, eng: CarcassonneEngine, x: int, y: int, rot: int):
        """虚拟分析放置 (x,y,rot) 后各段的连接前景（不修改引擎）。

        返回 {kind: [ {node, merged_meta_view, completes, points_if_complete,
                       mine, theirs, new_seg_edges} ]}
        """
        tile = eng.current_tile
        board = eng.board
        my_color = eng.current_player().color
        opp_colors = [p.color for p in eng.players if p.color != my_color]
        out: Dict[str, List[dict]] = {KIND_CITY: [], KIND_ROAD: [], KIND_FARM: []}
        seg_finders = {KIND_CITY: board.city_seg_at_edge,
                       KIND_ROAD: board.road_seg_at_edge,
                       KIND_FARM: board.farm_seg_at_edge}

        for kind, segs in ((KIND_CITY, tile.rotated_cities(rot)),
                           (KIND_ROAD, tile.rotated_roads(rot)),
                           (KIND_FARM, tile.rotated_farms(rot))):
            for idx, seg in enumerate(segs):
                edges = seg[0] if kind != KIND_ROAD else seg[0]
                flag = None
                if kind == KIND_CITY:
                    flag = seg[2]          # cathedral
                elif kind == KIND_ROAD:
                    flag = seg[1]          # inn
                open_cnt = 0
                shared = 0
                merged = None
                for e in edges:
                    npos = board.neighbor(x, y, e)
                    if npos is None:
                        open_cnt += 1
                        continue
                    shared += 1
                    other = seg_finders[kind](npos, OPPOSITE[e])
                    if other is not None:
                        root_meta = board.meta((npos[0], npos[1], kind, other))
                        if merged is None:
                            merged = root_meta
                        else:
                            # 同放置连接多个特征：聚合（保守估计）
                            merged = _AggMeta(merged, root_meta)
                after_open = open_cnt + (merged.open_edges if merged else 0) - shared
                completes = kind != KIND_FARM and after_open <= 0
                n_tiles = (merged.tiles | {(x, y)}) if merged else {(x, y)}
                pennants = (merged.pennants if merged else 0) + \
                    (seg[1] if kind == KIND_CITY and seg[1] else 0)
                mine = (merged.meeples.get(my_color, 0) if merged else 0)
                theirs = sum(merged.meeples.get(c, 0) for c in opp_colors) if merged else 0
                pts = 0
                if completes and kind == KIND_CITY:
                    pts = (3 if flag else 2) * (len(n_tiles) + pennants)
                    if "traders" in eng.expansions:
                        pts += sum(len(cs.goods) for cs in tile.cities) * 3
                out[kind].append({
                    "idx": idx, "edges": edges, "open_after": after_open,
                    "completes": completes, "points": pts,
                    "n_tiles": len(n_tiles), "pennants": pennants,
                    "mine": mine, "theirs": theirs, "merged": merged,
                    "is_farm_adj": bool(seg[1]) if kind == KIND_FARM else False,
                    "inn": flag if kind == KIND_ROAD else False,
                    "cathedral": flag if kind == KIND_CITY else False,
                    # 在此段部署 1 个米宝后能否与对手形成平局或多数
                    # （接入争不赢的特征 = 白送米宝，hard 只在可争夺时介入）
                    "can_contest": theirs > 0 and mine + 1 >= theirs,
                })
        return out

    # ------------------------------------------------------------ 贪心

    def _greedy(self, eng: CarcassonneEngine, placements) -> Move:
        my_color = eng.current_player().color
        opp_colors = [p.color for p in eng.players if p.color != my_color]
        best_score = -1e9
        best: List[Move] = []
        scored: List[Tuple[float, Tuple[int, int, int], Optional[Tuple[str, int]]]] = []

        for (x, y, rot) in placements:
            info = self._prospects(eng, x, y, rot)
            s_place = 0.0
            # 1) 放置即完成 → 按完成后的多数归属估值：
            #    己方多数 = 得满额；平局 = 双方均得；对方多数 = 送分（强负）
            for kind in (KIND_CITY, KIND_ROAD):
                for seg in info[kind]:
                    if not seg["completes"]:
                        continue
                    if self.level == "hard":
                        m, t = seg["mine"], seg["theirs"]
                        if m > t and m > 0:
                            s_place += seg["points"] * 1.8
                        elif m > 0 and m == t:
                            s_place += seg["points"] * 1.1
                        elif t > m:
                            s_place -= seg["points"] * 0.9
                    elif seg["mine"] > 0:
                        s_place += seg["points"] * 1.5
            # 2) 延伸己方未完成特征（规模适中更易完成）
            for kind in (KIND_CITY, KIND_ROAD):
                for seg in info[kind]:
                    if not seg["completes"] and seg["mine"] > 0:
                        s_place += 1.2 + min(seg["n_tiles"], 6) * 0.3
            # 3) hard 的争夺/送分评估已并入上方多数感知完成评估
            # 4) 修道院牌：周围邻格越满越值得放
            tile = eng.current_tile
            if tile.center.value == 1:
                s_place += board_adjacent_count(eng, x, y) * 1.1

            # 5) hard：落牌完成邻格修道院（己方 +9 / 对方送分 -9）
            if self.level == "hard":
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        if not (dx or dy):
                            continue
                        pos = (x + dx, y + dy)
                        if pos not in eng.board.tiles:
                            continue
                        if not eng.board.monastery_pos(pos):
                            continue
                        if eng.board.occupied_around(*pos) != 7:
                            continue  # 本牌落下后恰好补齐第 8 格
                        meta = eng.board.meta((pos[0], pos[1], KIND_MON, 0))
                        if not meta.meeples or meta.scored:
                            continue
                        m = meta.meeples.get(my_color, 0)
                        t = sum(meta.meeples.get(c, 0) for c in opp_colors)
                        if m > t:
                            s_place += 9 * 1.8
                        elif t > m:
                            s_place -= 9 * 0.9

            # 部署评估
            player = eng.current_player()
            if player.meeples_left > 0:
                s_deploy, deploy = self._eval_deploy_static(info, my_color, opp_colors,
                                                            eng, x, y)
            else:
                s_deploy, deploy = 0.0, None
            total = s_place + s_deploy
            # 扰动避免机械：hard 更小（稳定选最优）
            total += self.rng.random() * (0.1 if self.level == "hard" else 0.3)
            scored.append((total, (x, y, rot), deploy))
            if total > best_score + 1e-9:
                best_score, best = total, [((x, y, rot), deploy)]
            elif abs(total - best_score) <= 1e-9:
                best.append(((x, y, rot), deploy))

        if self.level == "hard":
            scored.sort(key=lambda t: -t[0])
            picked = self._lookahead(eng, scored[:6])
            if picked is not None:
                return picked
        return self.rng.choice(best)

    def _lookahead(self, eng, candidates, k: int = 6):
        """1 步前瞻：对静态分 top-K 的候选做快照重建模拟，
        按（即时分差 + 特征潜力）选最优；模拟失败回退静态首选。"""
        from .engine import CarcassonneEngine
        try:
            snap = eng.snapshot_dict()
        except Exception:
            return None
        my_idx = eng.current_player().idx
        best_total = None
        best_move = None
        for _static, move, deploy in candidates[:k]:
            x, y, rot = move
            try:
                rep = CarcassonneEngine.from_dict(snap)
                rep.place(x, y, rot)
                if rep.phase == "deploy" and deploy:
                    rep.deploy(deploy[0], deploy[1])
                else:
                    rep.skip_deploy()
            except (AssertionError, KeyError):
                continue
            mine = rep.players[my_idx].score
            opp = max((p.score for i, p in enumerate(rep.players) if i != my_idx),
                      default=0)
            total = (mine - opp) + self._potential(rep, my_idx)
            if best_total is None or total > best_total:
                best_total, best_move = total, (move, deploy)
        return best_move

    def _potential(self, rep, my_idx: int) -> float:
        """未完成特征潜力：己方 ×0.25，最强对手 ×0.15。
        客栈路/大教堂城未完成终局 0 分 → 潜力减半（风险）。"""
        from .board import KIND_CITY, KIND_ROAD
        my_color = rep.players[my_idx].color
        opp_colors = [p.color for p in rep.players if p.idx != my_idx]
        val = 0.0
        for root in rep.board.roots():
            meta = rep.board._meta[root]
            if meta.kind not in (KIND_CITY, KIND_ROAD) or meta.complete:
                continue
            base = len(meta.tiles) * (2 if meta.kind == KIND_CITY else 1)
            base += meta.pennants * 2
            if meta.kind == KIND_CITY and meta.cathedrals:
                base *= 0.5
            if meta.kind == KIND_ROAD and meta.inns:
                base *= 0.5
            mine = meta.meeples.get(my_color, 0)
            theirs = max((meta.meeples.get(c, 0) for c in opp_colors), default=0)
            if mine > theirs and mine > 0:
                val += base * 0.25
            elif theirs > mine and theirs > 0:
                val -= base * 0.15
        return val

    def _eval_deploy_static(self, info, my_color, opp_colors, eng, x, y):
        """对每个可部署段估值（放置阶段预判，与 _best_deploy 口径一致）。"""
        best_s, best_d = 0.0, None
        for kind in (KIND_MON, KIND_CITY, KIND_ROAD, KIND_FARM):
            for seg in info.get(kind, []) or []:
                if kind == KIND_MON:
                    n_adj = board_adjacent_count(eng, x, y)
                    if n_adj >= 6:
                        s = 8.0
                    elif n_adj >= 5:
                        s = 6.0
                    elif n_adj >= 4:
                        s = 3.5
                    else:
                        s = 0.6
                    if s > best_s:
                        best_s, best_d = s, (KIND_MON, 0)
                    continue
                if seg["mine"] > 0:
                    continue  # 己方已占，无法部署
                completes, pts = seg["completes"], seg["points"]
                if kind == KIND_CITY:
                    s = pts * 1.8 if completes else 1.0 + min(seg["n_tiles"], 5) * 0.4
                    if self.level == "hard" and seg["can_contest"]:
                        s += 1.8  # 接入可赢的争夺（多数/平局）
                elif kind == KIND_ROAD:
                    s = pts * 1.6 if completes else 0.8 + min(seg["n_tiles"], 4) * 0.3
                    if self.level == "hard" and seg["can_contest"]:
                        s += 0.0
                else:  # farm：终局投资，米宝充裕且毗邻城市才值得
                    s = 0.25
                    if self.level == "hard" and seg["is_farm_adj"]                             and eng.current_player().meeples_left >= 5:
                        s += 0.0
                if s > best_s:
                    best_s, best_d = s, (kind, seg["idx"])
        return best_s, best_d

    def _best_deploy(self, eng: CarcassonneEngine, options) -> Optional[Dict[str, object]]:
        """deploy 阶段实际决策：从 options 中选最高估值。"""
        info = self._prospects(eng, eng.placed_pos[0], eng.placed_pos[1],
                               eng.board.tiles[eng.placed_pos].rot)
        my_color = eng.current_player().color
        opp_colors = [p.color for p in eng.players if p.color != my_color]
        best_s, best_opt = 0.0, None
        for opt in options:
            kind, seg_idx = opt["kind"], opt["seg"]
            if kind == "mayor":
                s = 1.2   # 市长：0 旗不得分但占位无消耗（旗城强）
                if best_s < s:
                    best_s, best_opt = s, opt
                continue
            if kind == "barn":
                s = 1.8   # 粮仓：立即结算
                if best_s < s:
                    best_s, best_opt = s, opt
                continue
            if kind == "wagon":
                s = 1.4   # 马车：滚动收益
                if best_s < s:
                    best_s, best_opt = s, opt
                continue
            if kind == "fairy":
                s = 2.0   # 保护的期望价值（龙伤害平均 ~3 分）
                if best_s < s:
                    best_s, best_opt = s, opt
                continue
            if kind == "builder":
                s = 2.5   # 双回合价值
                if best_s < s:
                    best_s, best_opt = s, opt
                continue
            if kind == "pig":
                s = 0.8
                if best_s < s:
                    best_s, best_opt = s, opt
                continue
            if kind == "princess":
                s = 3.0   # 移走对手骑士（削弱+节流）
                if best_s < s:
                    best_s, best_opt = s, opt
                continue
            if kind == KIND_MON:
                n_adj = board_adjacent_count(eng, eng.placed_pos[0], eng.placed_pos[1])
                s = 8.0 if n_adj >= 6 else (6.0 if n_adj >= 5 else
                                            (3.5 if n_adj >= 4 else 0.6))
            else:
                seg = info[kind][seg_idx]
                if kind == KIND_CITY:
                    s = seg["points"] * 1.8 if seg["completes"] else \
                        1.0 + min(seg["n_tiles"], 5) * 0.4
                    if seg["theirs"] > 0 and self.level == "hard":
                        s += 2.5
                elif kind == KIND_ROAD:
                    s = seg["points"] * 1.6 if seg["completes"] else \
                        0.8 + min(seg["n_tiles"], 4) * 0.3
                    if seg["theirs"] > 0 and self.level == "hard":
                        s += 1.2
                else:
                    s = 0.25
                    if self.level == "hard" and seg.get("is_farm_adj")                             and eng.current_player().meeples_left >= 5:
                        s += 0.0
            if s > best_s:
                best_s, best_opt = s, opt
        return best_opt


class _AggMeta:
    """一次放置连接多个特征时的聚合视图（只读）。"""

    def __init__(self, a, b):
        self.tiles = set(a.tiles) | set(b.tiles)
        self.pennants = a.pennants + b.pennants
        self.open_edges = a.open_edges + b.open_edges
        self.meeples = dict(a.meeples)
        for c, n in b.meeples.items():
            self.meeples[c] = self.meeples.get(c, 0) + n


def board_adjacent_count(eng: CarcassonneEngine, x: int, y: int) -> int:
    return eng.board.occupied_around(x, y)
