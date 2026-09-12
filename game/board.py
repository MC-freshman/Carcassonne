# -*- coding: utf-8 -*-
"""棋盘：稀疏网格 + 特征并查集（城市/道路/农场/修道院各一套）。

特征节点键：(x, y, kind, seg_idx)。
- kind: "city" / "road" / "farm" / "mon"
- 城市与道路：open_edges==0 即完成（道路含闭环情形，CAR：所有边界被匹配）。
- 农场永不"完成"，只用于终局统计毗邻完成城市；节点另维护 farm-city 相邻对。
- 修道院：独立节点，完成条件为自身 + 周围 8 格全有地块。
"""
from __future__ import annotations

from typing import Dict, Iterator, List, Optional, Set, Tuple

from .models import (
    EDGE_DELTAS,
    OPPOSITE,
    PlacedTile,
    Terrain,
    TileDef,
    E,
    N,
    S,
    W,
)

Node = Tuple[int, int, str, int]
KIND_CITY, KIND_ROAD, KIND_FARM, KIND_MON = "city", "road", "farm", "mon"


class FeatureMeta:
    """并查集根节点上的特征元数据。

    meeples 为色名 -> 权重（普通米宝 1、大型米宝 2，直接用于多数判定）；
    meeple_nodes 记录 (节点, 色名, 大小) 用于归还。
    inns / cathedrals：客栈/大教堂计数（I&C 扩展，影响计分倍率与终局 0 分）。
    """

    __slots__ = ("kind", "tiles", "pennants", "open_edges", "meeples",
                 "meeple_nodes", "complete", "scored", "inns", "cathedrals",
                 "builders", "pigs", "goods", "figure_nodes",
                 "mayors", "wagons", "barns", "phantoms", "sieged")

    def __init__(self, kind: str):
        self.kind = kind
        self.tiles: Set[Tuple[int, int]] = set()
        self.pennants: int = 0
        self.open_edges: int = 0
        self.meeples: Dict[str, int] = {}          # 色名 -> 权重（多数判定）
        self.meeple_nodes: List[Tuple[Node, str, int]] = []  # (节点, 色, 大小)
        self.complete: bool = False
        self.scored: bool = False
        self.inns: int = 0
        self.cathedrals: int = 0
        self.builders: Dict[str, int] = {}   # 色名 -> 建造者数（不参与多数）
        self.pigs: Dict[str, int] = {}       # 色名 -> 猪数（不参与多数）
        self.goods: Dict[str, int] = {}      # wine/grain/cloth -> 符号数
        self.mayors: Dict[str, Node] = {}    # 色名 -> 市长节点（强度=段旗数）
        self.wagons: Dict[str, Node] = {}    # 色名 -> 马车节点（完成后移动）
        self.barns: Dict[str, Tuple[int, int]] = {}  # 色名 -> 农场段节点（代表）
        self.phantoms: List[Node] = []       # 幽灵节点（可重复：同节点叠放时按次消费）
        self.sieged: bool = False            # 被围攻城（M20：完成 1 分/牌）
        # 图元登记位置：(("builders"|"pigs", 色名)) -> [节点, ...]
        self.figure_nodes: Dict[Tuple[str, str], List[Node]] = {}

    def merge(self, other: "FeatureMeta") -> None:
        self.tiles |= other.tiles
        self.pennants += other.pennants
        self.open_edges += other.open_edges
        self.inns += other.inns
        self.cathedrals += other.cathedrals
        for d_from, d_to in ((other.builders, self.builders),
                             (other.pigs, self.pigs),
                             (other.goods, self.goods)):
            for k, n in d_from.items():
                d_to[k] = d_to.get(k, 0) + n
        # 市长/马车/粮仓：色名 -> 节点（数值合并不适用，覆盖即可——
        # 同色图元每色仅 1 个，合并时两特征各持一个同色图元不可能出现
        # （部署时要求特征无同色随从），直接 update）
        self.mayors.update(other.mayors)
        self.wagons.update(other.wagons)
        self.barns.update(other.barns)
        for key, nodes in other.figure_nodes.items():
            self.figure_nodes.setdefault(key, []).extend(nodes)
        for color, n in other.meeples.items():
            self.meeples[color] = self.meeples.get(color, 0) + n
        self.meeple_nodes.extend(other.meeple_nodes)
        self.phantoms.extend(other.phantoms)
        self.sieged = self.sieged or other.sieged


class Board:
    """稀疏棋盘 + 特征并查集。"""

    def __init__(self) -> None:
        self.tiles: Dict[Tuple[int, int], PlacedTile] = {}
        self.defs: Dict[Tuple[int, int], TileDef] = {}
        self._parent: Dict[Node, Node] = {}
        self._meta: Dict[Node, FeatureMeta] = {}
        # 农场-城市相邻对（节点级别，查询时经 find 归一化）
        self.farm_city_pairs: Set[Tuple[Node, Node]] = set()
        # BCB 木桥：pos -> 0=南北 / 1=东西；路段下标固定 100（印刷路段远少于此）
        self.bridges: Dict[Tuple[int, int], int] = {}
        # M20 隧道：隧道口路段节点 -> 占领色名（同色第二枚令牌接通两条路）
        self.tunnel_tokens: Dict[Node, str] = {}

    # ------------------------------------------------------------ 基础查询

    def has(self, x: int, y: int) -> bool:
        return (x, y) in self.tiles

    def neighbor(self, x: int, y: int, side: int) -> Optional[Tuple[int, int]]:
        dx, dy = EDGE_DELTAS[side]
        pos = (x + dx, y + dy)
        return pos if pos in self.tiles else None

    def occupied_around(self, x: int, y: int) -> int:
        """周围 8 格已占数量（修道院用）。"""
        n = 0
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if (dx or dy) and (x + dx, y + dy) in self.tiles:
                    n += 1
        return n

    # ------------------------------------------------------------ 并查集

    def _add_node(self, node: Node, meta: FeatureMeta) -> Node:
        self._parent[node] = node
        self._meta[node] = meta
        return node

    def find(self, node: Node) -> Node:
        parent = self._parent.get(node)
        if parent is None:
            raise KeyError("特征节点不存在: %r" % (node,))
        root = node
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[node] != root:  # 路径压缩
            self._parent[node], node = root, self._parent[node]
        return root

    def meta(self, node: Node) -> FeatureMeta:
        return self._meta[self.find(node)]

    def _union(self, a: Node, b: Node) -> Node:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return ra
        ma, mb = self._meta[ra], self._meta[rb]
        # 元数据并入 ra，rb 重定向到 ra
        ma.merge(mb)
        self._meta[rb] = ma
        self._parent[rb] = ra
        return ra

    def roots(self) -> Iterator[Node]:
        for node in list(self._parent):
            if self._parent[node] == node:
                yield node

    # ------------------------------------------------------------ 段定位

    def _seg_root(self, pos: Tuple[int, int], kind: str, seg_idx: int) -> Node:
        return self.find((pos[0], pos[1], kind, seg_idx))

    def city_seg_at_edge(self, pos: Tuple[int, int], edge: int) -> Optional[int]:
        """pos 牌的 edge 边所在城市段下标（该边为城时）。"""
        segs = self.city_segs_at_edge(pos, edge)
        return segs[0] if segs else None

    def city_segs_at_edge(self, pos: Tuple[int, int], edge: int) -> List[int]:
        """edge 边覆盖的全部城市段（山丘与羊的半边双段特殊牌可有两个）。"""
        d = self.defs[pos]
        tile = self.tiles[pos]
        return [i for i, (edges, _p, _c) in enumerate(d.rotated_cities(tile.rot))
                if edge in edges]

    def farm_segs_at_edge(self, pos: Tuple[int, int], edge: int) -> List[int]:
        """edge 边覆盖的全部农场段（半边双段特殊牌可有两个）。"""
        d = self.defs[pos]
        tile = self.tiles[pos]
        return [i for i, (edges, _adj) in enumerate(d.rotated_farms(tile.rot))
                if edge in edges]

    def road_seg_at_edge(self, pos: Tuple[int, int], edge: int) -> Optional[int]:
        d = self.defs[pos]
        tile = self.tiles[pos]
        for i, (edges, _inn) in enumerate(d.rotated_roads(tile.rot)):
            if edge in edges:
                return i
        if self.has_bridge_on_edge(pos, edge):
            return 100
        return None

    def has_bridge_on_edge(self, pos: Tuple[int, int], edge: int) -> bool:
        axis = self.bridges.get(pos)
        if axis is None:
            return False
        return edge in ((N, S) if axis == 0 else (E, W))

    def printed_edge(self, pos: Tuple[int, int], edge: int) -> Terrain:
        """印刷边地形（不含木桥覆盖）。"""
        d = self.defs[pos]
        return d.edge(edge, self.tiles[pos].rot)

    def matching_edge(self, pos: Tuple[int, int], edge: int) -> Terrain:
        """邻接匹配用地形：木桥覆盖的田边视为道路。"""
        if self.has_bridge_on_edge(pos, edge):
            return Terrain.ROAD
        return self.printed_edge(pos, edge)

    def farm_seg_at_edge(self, pos: Tuple[int, int], edge: int) -> Optional[int]:
        d = self.defs[pos]
        tile = self.tiles[pos]
        for i, (edges, _adj) in enumerate(d.rotated_farms(tile.rot)):
            if edge in edges:
                return i
        return None

    def monastery_pos(self, pos: Tuple[int, int]) -> bool:
        return self.defs[pos].center.value == 1  # Center.MONASTERY

    # ------------------------------------------------------------ 放置

    def add_tile(self, tile: PlacedTile, defn: TileDef,
                 loose: bool = False) -> None:
        """放置地块并合并特征。调用前需确认合法（engine 负责）。

        loose=True：邻边不匹配时当作开放边（快照重建、木桥稍后补上）。
        """
        x, y = tile.x, tile.y
        self.tiles[(x, y)] = tile
        self.defs[(x, y)] = defn
        rot = tile.rot

        # 1) 建节点并处理边匹配
        # 注意：邻牌在其放置时把共享边计为开放边；连接时必须 -1 抵消，
        # 否则特征永远无法达到 open_edges==0（完成判定失效）。
        for i, (edges, pennant, cathedral) in enumerate(defn.rotated_cities(rot)):
            node = self._add_node((x, y, KIND_CITY, i), FeatureMeta(KIND_CITY))
            meta = self._meta[node]
            meta.tiles.add((x, y))
            if pennant:
                meta.pennants += 1
            if cathedral:
                meta.cathedrals += 1
            if defn.siege:
                meta.sieged = True   # M20 围攻牌：所在城被围
            for g in defn.cities[i].goods:
                meta.goods[g] = meta.goods.get(g, 0) + 1
            for e in edges:
                npos = self.neighbor(x, y, e)
                if npos is None:
                    meta.open_edges += 1
                else:
                    others = self.city_segs_at_edge(npos, OPPOSITE[e])
                    if not others:
                        if loose:
                            meta.open_edges += 1
                            continue
                        raise AssertionError("邻边地形不匹配（应被 engine 拦截）")
                    # 半边双段特殊牌：一条边可对两个城段，全部合并
                    for other in others:
                        root = self._union(node,
                                           (npos[0], npos[1], KIND_CITY, other))
                    self._meta[root].open_edges -= 1

        for i, (edges, inn) in enumerate(defn.rotated_roads(rot)):
            node = self._add_node((x, y, KIND_ROAD, i), FeatureMeta(KIND_ROAD))
            meta = self._meta[node]
            meta.tiles.add((x, y))
            if inn:
                meta.inns += 1
            if i in defn.tunnels:
                # M20 隧道口：该段路在此"断头"，须同色双令牌对接才算接通
                meta.open_edges += 1
            for e in edges:
                npos = self.neighbor(x, y, e)
                if npos is None:
                    meta.open_edges += 1
                else:
                    other = self.road_seg_at_edge(npos, OPPOSITE[e])
                    if other is None:
                        if loose:
                            meta.open_edges += 1
                            continue
                        raise AssertionError("邻边应为路")
                    root = self._union(node, (npos[0], npos[1], KIND_ROAD, other))
                    self._meta[root].open_edges -= 1

        for i, (edges, adj_cities) in enumerate(defn.rotated_farms(rot)):
            node = self._add_node((x, y, KIND_FARM, i), FeatureMeta(KIND_FARM))
            self._meta[node].tiles.add((x, y))
            for e in edges:
                npos = self.neighbor(x, y, e)
                if npos is not None:
                    for other in self.farm_segs_at_edge(npos, OPPOSITE[e]):
                        self._union(node, (npos[0], npos[1], KIND_FARM, other))
            # 注册本牌农场-城市相邻关系
            for ci in adj_cities:
                self.farm_city_pairs.add(((x, y, KIND_FARM, i), (x, y, KIND_CITY, ci)))

        if defn.center.value == 1:  # MONASTERY
            self._add_node((x, y, KIND_MON, 0), FeatureMeta(KIND_MON))
            self._meta[self.find((x, y, KIND_MON, 0))].tiles.add((x, y))

        # 2) 合并后城市/道路 open_edges 可能为 0 → 标记完成
        for node in [(x, y, KIND_CITY, i) for i in range(len(defn.cities))] + \
                    [(x, y, KIND_ROAD, i) for i in range(len(defn.roads))]:
            meta = self._meta[self.find(node)]
            if meta.open_edges == 0:
                meta.complete = True

    BRIDGE_SEG = 100  # 木桥路段下标（印刷路段远少于此）

    def can_build_bridge(self, pos: Tuple[int, int], axis: int) -> bool:
        """两端必须是印刷田（CAR 页 96）；邻格须为空或道路（脚注 294）。"""
        if pos not in self.tiles or pos in self.bridges:
            return False
        ends = (N, S) if axis == 0 else (E, W)
        if any(self.printed_edge(pos, e) is not Terrain.FIELD for e in ends):
            return False
        x, y = pos
        for e in ends:
            npos = self.neighbor(x, y, e)
            if npos is None:
                continue
            if self.road_seg_at_edge(npos, OPPOSITE[e]) is None:
                return False
        return True

    def add_bridge(self, pos: Tuple[int, int], axis: int,
                   force: bool = False) -> Node:
        """在已放牌上架木桥：田上架路，桥下农场/城不分隔。"""
        if not force:
            assert self.can_build_bridge(pos, axis), "非法木桥"
        else:
            assert pos in self.tiles and pos not in self.bridges
            ends = (N, S) if axis == 0 else (E, W)
            assert all(self.printed_edge(pos, e) is Terrain.FIELD for e in ends)
        x, y = pos
        self.bridges[pos] = axis
        ends = (N, S) if axis == 0 else (E, W)
        node = self._add_node((x, y, KIND_ROAD, self.BRIDGE_SEG),
                              FeatureMeta(KIND_ROAD))
        meta = self._meta[node]
        meta.tiles.add((x, y))
        for e in ends:
            npos = self.neighbor(x, y, e)
            if npos is None:
                meta.open_edges += 1
            else:
                other = self.road_seg_at_edge(npos, OPPOSITE[e])
                if other is None:
                    if force:
                        meta.open_edges += 1
                        continue
                    raise AssertionError("木桥邻边应为路")
                root = self._union(node, (npos[0], npos[1], KIND_ROAD, other))
                self._meta[root].open_edges -= 1
                node = root
                meta = self._meta[root]
        if meta.open_edges == 0:
            meta.complete = True
        return node

    # ------------------------------------------------------------ 完成

    def monastery_complete(self, pos: Tuple[int, int]) -> bool:
        return self.occupied_around(pos[0], pos[1]) == 8

    # ------------------------------------------------------------ 米宝

    def deploy_meeple(self, node: Node, color: str, size: int = 1,
                      force: bool = False, phantom: bool = False) -> None:
        """部署米宝（size=2 为大型米宝：占 1 个名额，多数判定按 2 计）。

        phantom：幽灵（M20，按普通随从判定，归还时回幽灵池）。
        """
        meta = self.meta(node)
        assert force or not meta.meeples, "该特征已有米宝"
        meta.meeples[color] = meta.meeples.get(color, 0) + size
        meta.meeple_nodes.append((node, color, size))
        if phantom:
            meta.phantoms.append(node)

    def deploy_mayor(self, node: Node, color: str) -> None:
        """部署市长到城段节点（不占骑士名额；强度=段旗数）。"""
        meta = self.meta(node)
        meta.mayors[color] = node

    def deploy_wagon(self, node: Node, color: str) -> None:
        """部署马车到城/路段节点（完成后移动）。"""
        meta = self.meta(node)
        meta.wagons[color] = node

    def deploy_barn(self, node: Node, color: str) -> None:
        """部署粮仓到农场段节点（代表该农场；放置即结算）。"""
        meta = self.meta(node)
        meta.barns[color] = (node[0], node[1])

    def return_mayors(self, root: Node, color: Optional[str] = None) -> int:
        meta = self._meta[self.find(root)]
        if color is None:
            n = len(meta.mayors)
            meta.mayors = {}
        else:
            n = 1 if meta.mayors.pop(color, None) is not None else 0
        return n

    def return_wagons(self, root: Node, color: Optional[str] = None) -> int:
        meta = self._meta[self.find(root)]
        if color is None:
            n = len(meta.wagons)
            meta.wagons = {}
        else:
            n = 1 if meta.wagons.pop(color, None) is not None else 0
        return n

    def deploy_builder(self, node: Node, color: str) -> None:
        """部署建造者到段节点（不参与多数判定；随特征结算归还）。"""
        meta = self.meta(node)
        meta.builders[color] = meta.builders.get(color, 0) + 1
        meta.figure_nodes.setdefault(("builders", color), []).append(node)

    def deploy_pig(self, node: Node, color: str) -> None:
        """部署猪到农场段节点（不参与多数判定；终局归还）。"""
        meta = self.meta(node)
        meta.pigs[color] = meta.pigs.get(color, 0) + 1
        meta.figure_nodes.setdefault(("pigs", color), []).append(node)

    def return_builders(self, node: Node, color: Optional[str] = None) -> int:
        """归还特征上（某色或全部）建造者，返回归还数量。"""
        meta = self._meta[self.find(node)]
        if color is None:
            n = sum(meta.builders.values())
            meta.builders = {}
            meta.figure_nodes = {k: v for k, v in meta.figure_nodes.items()
                                 if k[0] != "builders"}
        else:
            n = meta.builders.pop(color, 0)
            meta.figure_nodes.pop(("builders", color), None)
        return n

    def return_pigs(self, node: Node, color: Optional[str] = None) -> int:
        """归还特征上（某色或全部）猪，返回归还数量。"""
        meta = self._meta[self.find(node)]
        if color is None:
            n = sum(meta.pigs.values())
            meta.pigs = {}
            meta.figure_nodes = {k: v for k, v in meta.figure_nodes.items()
                                 if k[0] != "pigs"}
        else:
            n = meta.pigs.pop(color, 0)
            meta.figure_nodes.pop(("pigs", color), None)
        return n

    def return_meeples(self, node: Node) -> List[Tuple[str, int, Node]]:
        """归还特征上全部米宝。返回 [(色名, 大小, 节点), ...]。

        幽灵节点集由 pop_phantoms 单独取出（归还走 phantom_left 池）。
        """
        meta = self._meta[self.find(node)]
        taken = [(color, size, n) for n, color, size in meta.meeple_nodes]
        meta.meeples = {}
        meta.meeple_nodes = []
        return taken

    def pop_phantoms(self, node: Node) -> List[Node]:
        """取出特征上的幽灵节点列表并清空（结算归还时按次区分幽灵/普通池）。"""
        meta = self._meta[self.find(node)]
        out = list(meta.phantoms)
        meta.phantoms = []
        return out

    def remove_meeple(self, node: Node) -> Tuple[str, int, bool]:
        """按节点移除单个随从，返回 (色名, 大小, 是否幽灵)。"""
        meta = self._meta[self.find(node)]
        for i, (n, color, size) in enumerate(meta.meeple_nodes):
            if n == node:
                meta.meeple_nodes.pop(i)
                meta.meeples[color] -= size
                if meta.meeples[color] <= 0:
                    del meta.meeples[color]
                ph = node in meta.phantoms
                if ph:
                    meta.phantoms.remove(node)
                return color, size, ph
        raise AssertionError("节点无随从: %r" % (node,))

    # ------------------------------------------------------------ 快照

    def snapshot(self) -> Dict[str, object]:
        """联机/AI 用状态快照（M4 扩展用）。"""
        return {
            "tiles": {str(k): (v.tile_id, v.x, v.y, v.rot, v.placed_by)
                      for k, v in self.tiles.items()},
        }
