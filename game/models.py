# -*- coding: utf-8 -*-
"""核心数据模型：地形、牌面定义、已放地块、玩家、计分事件。

坐标约定：格子坐标 (x, y)，x 向东、y 向南。
边序约定：0=北(N) 1=东(E) 2=南(S) 3=西(W)，顺时针。
旋转 rot ∈ {0,1,2,3}，表示顺时针旋转 rot×90°。
旋转后边 i 对应基础边 (i - rot) % 4。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, FrozenSet, List, Optional, Tuple


class Terrain(str, Enum):
    CITY = "c"
    ROAD = "r"
    FIELD = "f"
    WATER = "w"   # 河流（River II）：只与水边匹配，分隔农场


N, E, S, W = 0, 1, 2, 3
EDGE_DELTAS = {N: (0, -1), E: (1, 0), S: (0, 1), W: (-1, 0)}  # (dx, dy)
OPPOSITE = {N: S, E: W, S: N, W: E}


class Center(Enum):
    """牌中心特征。"""

    NONE = 0
    MONASTERY = 1   # 修道院
    JUNCTION = 2    # 道路交叉口/丁字路口：终止一切道路


@dataclass(frozen=True)
class CitySeg:
    """城市段：若干条边 + 旗帜/大教堂（I&C）/贸易商品（T&B，可多个）。"""

    edges: FrozenSet[int]
    pennant: bool = False
    cathedral: bool = False
    goods: Tuple[str, ...] = ()   # "wine" / "grain" / "cloth"（可重复）


@dataclass(frozen=True)
class RoadSeg:
    """道路段。

    edges 为该段连通的道路边集合（多为穿过牌面的直路/弯路，2 条边）；
    单条边表示道路在牌内终止（修道院/城门/交叉口支路/断头路）。
    inn：路旁客栈（I&C 扩展）——只影响本段：完成 2 分/牌，未完成终局 0 分。
    """

    edges: Tuple[int, ...]
    inn: bool = False


@dataclass(frozen=True)
class FarmSeg:
    """农场段：若干条边 + 与本牌哪些城市段相邻（用于终局农场计分）。"""

    edges: FrozenSet[int]
    adj_cities: FrozenSet[int] = frozenset()  # 城市段下标集合


@dataclass(frozen=True)
class TileDef:
    """一张牌面（基础朝向）的完整拓扑定义。"""

    tile_id: str
    edges: Tuple[Terrain, Terrain, Terrain, Terrain]
    cities: Tuple[CitySeg, ...] = ()
    roads: Tuple[RoadSeg, ...] = ()
    farms: Tuple[FarmSeg, ...] = ()
    center: Center = Center.NONE
    is_start: bool = False
    builder: bool = False   # 建造者图元（T&B，可部署到含己随从的城/路段）
    pig: bool = False       # 猪图元（T&B，可部署到含己农夫的农场段）
    volcano: bool = False   # 火山图元（P&D：放置后龙降临该牌，本回合不能部署）
    dragon_tile: bool = False  # 龙图元（P&D：放置后触发龙移动阶段）
    princess: bool = False  # 公主图元（P&D：可移走所延伸城的一个骑士）
    portal: bool = False    # 传送门图元（P&D：随从可部署到全场合法空段）
    mon_in_city: bool = False  # 城内修道院（P&D：可部署骑士或僧侣）
    abbey: bool = False     # 修道院牌（A&M：可放任意相邻空格，无需边匹配）
    mayor: bool = False     # 市长图元（A&M：城段，强度=城内旗帜数）
    barn: bool = False      # 粮仓图元（A&M：农场，放置即结算）
    wagon: bool = False     # 马车图元（A&M：城/路，完成后移动）
    spring: bool = False    # 泉源（River II：河流起始牌，单水边）
    pig_herd: bool = False  # 猪倌（River II：所在农场终局农夫 +1 分/城）
    shrine: bool = False    # 教堂（S&H：修道院型特征，可与修道院互相挑战）
    count_city: bool = False  # 伯爵城牌（Count：内边城+田双覆盖，合成大城）
    bazaar: bool = False    # 集市（BCB：放置并结算后触发拍卖）
    siege: bool = False     # 围攻（迷你：所在城被围，完成 1 分/牌，终局 0 分）
    festival: bool = False  # 节日（迷你：放置后可收回场上任一己方图元）
    gold: bool = False      # 金矿（迷你：放置时 2 块金子落牌上，完成时归属多数者）
    mage: bool = False      # 法师牌（迷你：放置后必须放置/移动法师或女巫）
    robber: bool = False    # 强盗牌（迷你：放置后各玩家可把强盗放上计分轨道）
    crop: str = ""          # 麦田怪圈（迷你："" 无；farm/road/city = 圈类型）
    tunnels: Tuple[int, ...] = ()  # 隧道口（迷你：路段下标 -> 该段终点是隧道口）
    tower: bool = False     # 塔基（Tower：可建塔，沿横竖射线抓随从）
    hill: bool = False      # 山丘（H&S：叠放垫牌；平局破缺）
    sheep: bool = False     # 羊圈（H&S：可部署牧羊人）
    vineyard: bool = False  # 葡萄园（H&S：修院完成 +3 分/座）
    fate: int = 0           # 命运之轮图腾数字（WoF：1-3，抽到即转轮盘）

    def edge(self, side: int, rot: int = 0) -> Terrain:
        """旋转 rot 后 side 边的地形。"""
        return self.edges[(side - rot) % 4]

    def rotated_cities(self, rot: int) -> List[Tuple[FrozenSet[int], bool, bool]]:
        """[(边集, 旗帜, 大教堂), ...]（下标即段号，供节点/部署引用）。"""
        return [
            (frozenset((e + rot) % 4 for e in seg.edges), seg.pennant,
             seg.cathedral)
            for seg in self.cities
        ]

    def rotated_roads(self, rot: int) -> List[Tuple[Tuple[int, ...], bool]]:
        """[((边..., ), 客栈), ...]（下标即段号）。"""
        return [(tuple(sorted((e + rot) % 4 for e in seg.edges)), seg.inn)
                for seg in self.roads]

    def rotated_farms(self, rot: int) -> List[Tuple[FrozenSet[int], FrozenSet[int]]]:
        return [
            (frozenset((e + rot) % 4 for e in seg.edges), seg.adj_cities)
            for seg in self.farms
        ]

    def topology(self, rot: int = 0) -> str:
        return "".join(self.edge(i, rot).value for i in (N, E, S, W))


@dataclass(frozen=True)
class PlacedTile:
    tile_id: str
    x: int
    y: int
    rot: int
    placed_by: int  # 玩家下标


@dataclass
class Player:
    idx: int
    name: str
    color: str          # 显示色名
    is_ai: bool = False
    ai_level: str = "normal"   # easy / normal / hard
    score: int = 0
    meeples_left: int = 7      # 8 个中 1 个作计分标记，7 个可用
    big_meeples_left: int = 0  # 大型米宝（I&C 扩展，每色 1 个，未启用为 0）
    builder_left: int = 0      # 建造者（T&B，每色 1 个）
    pig_left: int = 0          # 猪（T&B，每色 1 个）
    mayor_left: int = 0        # 市长（A&M，每色 1 个）
    barn_left: int = 0         # 粮仓（A&M，每色 1 个）
    wagon_left: int = 0        # 马车（A&M，每色 1 个）
    bridges_left: int = 0      # 木桥（BCB：2-4 人各 3，5-6 人各 2）
    castles_left: int = 0      # 城堡标记（BCB：同上）
    phantom_left: int = 0      # 幽灵（迷你：第二枚普通随从，每色 1）
    towers_left: int = 0       # 塔块（Tower：2 人各 10 / 3 人 9 / 4 人 7 / 5 人 6 / 6 人 5）
    shepherd_left: int = 0     # 牧羊人（H&S：每色 1，不是随从）
    crown_left: int = 0        # 王冠位部署额度（WoF：随从共用，无独立池——占位字段）
    tunnels_left: int = 0      # 隧道令牌对数（迷你：2 人 3 / 3 人 2 / 4-6 人 1）
    gold_pieces: int = 0       # 金块（迷你：终局按 1-3:1 / 4-6:2 / 7-9:3 / 10+:4 计分）
    goods: Dict[str, int] = field(default_factory=dict)  # wine/grain/cloth -> 数量


@dataclass(frozen=True)
class ScoreEvent:
    """一次计分记录（用于结算弹层与日志）。"""

    kind: str            # road / city / monastery / farm / final_road / final_city / final_monastery / final_farm
    reason: str          # 说明文本
    scores: Dict[str, int] = field(default_factory=dict)   # 玩家色名 -> 得分
    meeples: Dict[str, int] = field(default_factory=dict)  # 参与各色米宝数（多数判定展示）
    detail: str = ""     # 明细，如 "7 张牌 + 1 旗帜"
    pos: Optional[Tuple[int, int]] = None  # 特征位置（UI 飘字用）


def meeple_majority(meeples: Dict[str, int]) -> Tuple[List[str], int]:
    """多数判定：返回 (得分玩家色名列表, 最高米宝数)。

    规则（CAR）：数量最多者得分；平局全部均得全额；同色多米宝不翻倍。
    """
    if not meeples:
        return [], 0
    top = max(meeples.values())
    return [c for c, n in meeples.items() if n == top], top
