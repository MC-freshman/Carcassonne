# -*- coding: utf-8 -*-
"""基础版 72 张地牌的完整拓扑数据。

数据来源与口径：
- 牌组分布按 CAR v7.4《Consolidated Tile Reference》各拓扑类 BASIC GAME 数量：
  cccc×1 cccf×4 cccr×3 ccff×7 ccrr×5 cfcf×6 cfff×5 cfrr×3 crfr×4 crrf×3 crrr×3
  ffff×4 fffr×2 ffrr×9 frfr×8 frrr×4 rrrr×1，合计 72（含 1 张深色背面起始牌）。
- 段结构（哪些边同属一个特征段）、道路端点（交叉口终止道路，CAR 脚注 15/358）、
  农场分段与"农场-城市相邻"关系按官方牌面图形建模；同拓扑类内旗帜的具体分布
  参照经典版牌面，若与实体牌有出入只需改本文件的 pennant 布尔值。
- 农场计分采用"第三版"口径（CAR 脚注 32）：每个毗邻/包含的完成城市 3 分。
"""
from __future__ import annotations

from typing import Dict, List, Tuple

from .models import Center, CitySeg, FarmSeg, RoadSeg, Terrain, TileDef, E, N, S, W

F, R, C = Terrain.FIELD, Terrain.ROAD, Terrain.CITY


def _t(s: str) -> Tuple[Terrain, Terrain, Terrain, Terrain]:
    """按 N,E,S,W 顺序的字母串转地形元组。"""
    return tuple(Terrain(ch) for ch in s)  # type: ignore[return-value]


# ---------------------------------------------------------------- 修道院

# 起始牌：修道院 + 南侧道路（深色背面）。田地绕修道院连为一段（CAR 脚注 13），
# 南边为道路边，农场仅覆盖北/东/西三边。
_M_START = TileDef(
    tile_id="MR-start",
    edges=_t("ffrf"),
    roads=(RoadSeg((S,)),),
    farms=(FarmSeg(frozenset({N, E, W})),),
    center=Center.MONASTERY,
    is_start=True,
)

# 修道院 + 道路（常规牌；与起始牌同构。CAR fffr 类 BASIC GAME ×2 = 起始牌 + 本张）
_MR_PLAIN = TileDef(
    tile_id="MR",
    edges=_t("ffrf"),
    roads=(RoadSeg((S,)),),
    farms=(FarmSeg(frozenset({N, E, W})),),
    center=Center.MONASTERY,
)

# 修道院（四面田野）
_M_PLAIN = TileDef(
    tile_id="M",
    edges=_t("ffff"),
    farms=(FarmSeg(frozenset({N, E, S, W})),),
    center=Center.MONASTERY,
)

# ---------------------------------------------------------------- 城市

# 全城 + 旗帜
_C_ALL = TileDef(
    tile_id="CAll",
    edges=_t("cccc"),
    cities=(CitySeg(frozenset({N, E, S, W}), pennant=True),),
)

# 三边城 + 一边田
_C_3S = TileDef(
    tile_id="C3s",
    edges=_t("cccf"),
    cities=(CitySeg(frozenset({N, E, S})),),
    farms=(FarmSeg(frozenset({W}), adj_cities=frozenset({0})),),
)
_C_3S_P = TileDef(
    tile_id="C3sP",
    edges=_t("cccf"),
    cities=(CitySeg(frozenset({N, E, S}), pennant=True),),
    farms=(FarmSeg(frozenset({W}), adj_cities=frozenset({0})),),
)

# 三边城 + 城门路（西侧道路在城门终止；无田）
_C_GATE = TileDef(
    tile_id="CGate",
    edges=_t("cccr"),
    cities=(CitySeg(frozenset({N, E, S})),),
    roads=(RoadSeg((W,)),),
)
_C_GATE_P = TileDef(
    tile_id="CGateP",
    edges=_t("cccr"),
    cities=(CitySeg(frozenset({N, E, S}), pennant=True),),
    roads=(RoadSeg((W,)),),
)

# 两邻边城（城墙拐角）；田在另两边，绕过城角连为一段
_C_CORNER = TileDef(
    tile_id="CCorner",
    edges=_t("ccff"),
    cities=(CitySeg(frozenset({N, E})),),
    farms=(FarmSeg(frozenset({S, W}), adj_cities=frozenset({0})),),
)
_C_CORNER_P = TileDef(
    tile_id="CCornerP",
    edges=_t("ccff"),
    cities=(CitySeg(frozenset({N, E}), pennant=True),),
    farms=(FarmSeg(frozenset({S, W}), adj_cities=frozenset({0})),),
)

# 对边城贯通（一座两段城）；左右田被城分隔
_C_THROUGH = TileDef(
    tile_id="CThrough",
    edges=_t("cfcf"),
    cities=(CitySeg(frozenset({N, S})),),
    farms=(
        FarmSeg(frozenset({E}), adj_cities=frozenset({0})),
        FarmSeg(frozenset({W}), adj_cities=frozenset({0})),
    ),
)
_C_THROUGH_P = TileDef(
    tile_id="CThroughP",
    edges=_t("cfcf"),
    cities=(CitySeg(frozenset({N, S}), pennant=True),),
    farms=(
        FarmSeg(frozenset({E}), adj_cities=frozenset({0})),
        FarmSeg(frozenset({W}), adj_cities=frozenset({0})),
    ),
)

# 对边两座独立小城；左右田在两城之间连通为一段，与两城均相邻
_C_SEP = TileDef(
    tile_id="CSep",
    edges=_t("cfcf"),
    cities=(CitySeg(frozenset({N})), CitySeg(frozenset({S}))),
    farms=(FarmSeg(frozenset({E, W}), adj_cities=frozenset({0, 1})),),
)
_C_SEP_P = TileDef(
    tile_id="CSepP",
    edges=_t("cfcf"),
    cities=(CitySeg(frozenset({N}), pennant=True), CitySeg(frozenset({S}))),
    farms=(FarmSeg(frozenset({E, W}), adj_cities=frozenset({0, 1})),),
)

# 单边小城 + 三边田
_C_1S = TileDef(
    tile_id="C1s",
    edges=_t("cfff"),
    cities=(CitySeg(frozenset({N})),),
    farms=(FarmSeg(frozenset({E, S, W}), adj_cities=frozenset({0})),),
)
_C_1S_P = TileDef(
    tile_id="C1sP",
    edges=_t("cfff"),
    cities=(CitySeg(frozenset({N}), pennant=True),),
    farms=(FarmSeg(frozenset({E, S, W}), adj_cities=frozenset({0})),),
)

# 单边城 + 直路（东西向，沿城墙脚下）；南侧田与城相邻
_C_STRAIGHT_ROAD = TileDef(
    tile_id="CStraightRoad",
    edges=_t("crfr"),
    cities=(CitySeg(frozenset({N})),),
    roads=(RoadSeg((E, W)),),
    farms=(FarmSeg(frozenset({S}), adj_cities=frozenset({0})),),
)
_C_STRAIGHT_ROAD_P = TileDef(
    tile_id="CStraightRoadP",
    edges=_t("crfr"),
    cities=(CitySeg(frozenset({N}), pennant=True),),
    roads=(RoadSeg((E, W)),),
    farms=(FarmSeg(frozenset({S}), adj_cities=frozenset({0})),),
)

# 单边城 + 弯路（西→南）；东侧田（镜像之一）
_CURVE_A = TileDef(
    tile_id="CCurveA",
    edges=_t("cfrr"),
    cities=(CitySeg(frozenset({N})),),
    roads=(RoadSeg((W, S)),),
    farms=(FarmSeg(frozenset({E}), adj_cities=frozenset({0})),),
)
_CURVE_A_P = TileDef(
    tile_id="CCurveAP",
    edges=_t("cfrr"),
    cities=(CitySeg(frozenset({N}), pennant=True),),
    roads=(RoadSeg((W, S)),),
    farms=(FarmSeg(frozenset({E}), adj_cities=frozenset({0})),),
)

# 单边城 + 弯路（东→南）；西侧田（镜像之二）
_CURVE_B = TileDef(
    tile_id="CCurveB",
    edges=_t("crrf"),
    cities=(CitySeg(frozenset({N})),),
    roads=(RoadSeg((E, S)),),
    farms=(FarmSeg(frozenset({W}), adj_cities=frozenset({0})),),
)
_CURVE_B_P = TileDef(
    tile_id="CCurveBP",
    edges=_t("crrf"),
    cities=(CitySeg(frozenset({N}), pennant=True),),
    roads=(RoadSeg((E, S)),),
    farms=(FarmSeg(frozenset({W}), adj_cities=frozenset({0})),),
)

# 两邻边城 + 弯路绕城（西→南）；无田
_C_CORNER_ROAD = TileDef(
    tile_id="CCornerRoad",
    edges=_t("ccrr"),
    cities=(CitySeg(frozenset({N, E})),),
    roads=(RoadSeg((W, S)),),
)
_C_CORNER_ROAD_P = TileDef(
    tile_id="CCornerRoadP",
    edges=_t("ccrr"),
    cities=(CitySeg(frozenset({N, E}), pennant=True),),
    roads=(RoadSeg((W, S)),),
)

# 单边城 + 三条路汇入交叉口；交叉口终止道路（CAR 脚注 15）；无田
_C_3ROADS = TileDef(
    tile_id="C3Roads",
    edges=_t("crrr"),
    cities=(CitySeg(frozenset({N})),),
    roads=(RoadSeg((E,)), RoadSeg((S,)), RoadSeg((W,))),
    center=Center.JUNCTION,
)
_C_3ROADS_P = TileDef(
    tile_id="C3RoadsP",
    edges=_t("crrr"),
    cities=(CitySeg(frozenset({N}), pennant=True),),
    roads=(RoadSeg((E,)), RoadSeg((S,)), RoadSeg((W,))),
    center=Center.JUNCTION,
)

# ---------------------------------------------------------------- 道路

# 十字交叉口：四条支路均为独立道路段；无田
_R_CROSS = TileDef(
    tile_id="RCross",
    edges=_t("rrrr"),
    roads=(RoadSeg((N,)), RoadSeg((E,)), RoadSeg((S,)), RoadSeg((W,))),
    center=Center.JUNCTION,
)

# 直路（东西向）；南北两块田被路分隔
_R_STRAIGHT = TileDef(
    tile_id="RStraight",
    edges=_t("frfr"),
    roads=(RoadSeg((E, W)),),
    farms=(FarmSeg(frozenset({N})), FarmSeg(frozenset({S}))),
)

# 弯路（西→南）；东北侧田连为一段
_R_CURVE = TileDef(
    tile_id="RCurve",
    edges=_t("ffrr"),
    roads=(RoadSeg((W, S)),),
    farms=(FarmSeg(frozenset({N, E})),),
)

# 丁字路口：三条支路独立、交叉口终止道路；北侧田
_R_T = TileDef(
    tile_id="RT",
    edges=_t("frrr"),
    roads=(RoadSeg((E,)), RoadSeg((S,)), RoadSeg((W,))),
    farms=(FarmSeg(frozenset({N})),),
    center=Center.JUNCTION,
)


# ================================================================ 扩展一：客栈与大教堂
# 18 张牌（CAR：Inns and Cathedrals）。客栈×6（完成路 2 分/牌、终局 0 分，
# 只影响紧邻路段，CAR 脚注 43）；大教堂×2（完成城 3 分/牌与旗帜、终局 0 分）；
# 另含四段独立城、修道院分隔道路、交叉口分隔道路等特殊牌。
_TILE_SHEET_IC: List[Tuple[TileDef, int]] = [
    # 全城 + 大教堂
    (TileDef(tile_id="IC-CathAll", edges=_t("cccc"),
             cities=(CitySeg(frozenset({N, E, S, W}), cathedral=True),)), 1),
    # 全城、四段互不相连（CAR："This tile has four unconnected city segments"）
    (TileDef(tile_id="IC-C4sep", edges=_t("cccc"),
             cities=(CitySeg(frozenset({N})), CitySeg(frozenset({E})),
                     CitySeg(frozenset({S})), CitySeg(frozenset({W})))), 1),
    # 全城（贯通单段）
    (TileDef(tile_id="IC-Cfull", edges=_t("cccc"),
             cities=(CitySeg(frozenset({N, E, S, W})),)), 1),
    # 三边城 + 大教堂
    (TileDef(tile_id="IC-Cath3s", edges=_t("cccf"),
             cities=(CitySeg(frozenset({N, E, S}), cathedral=True),),
             farms=(FarmSeg(frozenset({W}), adj_cities=frozenset({0})),)), 1),
    # 三边城（普通）
    (TileDef(tile_id="IC-C3s", edges=_t("cccf"),
             cities=(CitySeg(frozenset({N, E, S})),),
             farms=(FarmSeg(frozenset({W}), adj_cities=frozenset({0})),)), 1),
    # 两邻边城 + 客栈城门路（西）（第 6 张客栈牌）
    (TileDef(tile_id="IC-CCfR", edges=_t("ccfr"),
             cities=(CitySeg(frozenset({N, E})),),
             roads=(RoadSeg((W,), inn=True),),
             farms=(FarmSeg(frozenset({S}), adj_cities=frozenset({0})),)), 1),
    # 两邻边城 + 城门路（南）
    (TileDef(tile_id="IC-CCRf", edges=_t("ccrf"),
             cities=(CitySeg(frozenset({N, E})),),
             roads=(RoadSeg((S,)),),
             farms=(FarmSeg(frozenset({W}), adj_cities=frozenset({0})),)), 1),
    # 两邻边城 + 弯路绕城
    (TileDef(tile_id="IC-CCRr", edges=_t("ccrr"),
             cities=(CitySeg(frozenset({N, E})),),
             roads=(RoadSeg((W, S)),)), 1),
    # 单边小城
    (TileDef(tile_id="IC-C1s", edges=_t("cfff"),
             cities=(CitySeg(frozenset({N})),),
             farms=(FarmSeg(frozenset({E, S, W}), adj_cities=frozenset({0})),)), 1),
    # 城 + 修道院 + 南路（修道院分隔道路，CAR 提示牌）
    (TileDef(tile_id="IC-CMonR", edges=_t("cfrf"),
             cities=(CitySeg(frozenset({N})),),
             roads=(RoadSeg((S,)),),
             farms=(FarmSeg(frozenset({E, W}), adj_cities=frozenset({0})),),
             center=Center.MONASTERY), 1),
    # 城 + 客栈弯路（西→南）
    (TileDef(tile_id="IC-CurveInnA", edges=_t("cfrr"),
             cities=(CitySeg(frozenset({N})),),
             roads=(RoadSeg((W, S), inn=True),),
             farms=(FarmSeg(frozenset({E}), adj_cities=frozenset({0})),)), 1),
    # 客栈十字路口（客栈属于北支路，只影响该段）
    (TileDef(tile_id="IC-CrossInn", edges=_t("rrrr"),
             roads=(RoadSeg((N,), inn=True), RoadSeg((E,)),
                    RoadSeg((S,)), RoadSeg((W,))),
             center=Center.JUNCTION), 1),
    # 对边双独立城 + 交叉口分隔道路（CAR："The crossing divides the road"）
    (TileDef(tile_id="IC-C2Cross", edges=_t("crcr"),
             cities=(CitySeg(frozenset({N})), CitySeg(frozenset({S}))),
             roads=(RoadSeg((E,)), RoadSeg((W,))),
             center=Center.JUNCTION), 1),
    # 对边贯通城 + 直路
    (TileDef(tile_id="IC-CThroughR", edges=_t("crcr"),
             cities=(CitySeg(frozenset({N, S})),),
             roads=(RoadSeg((E, W)),)), 1),
    # 客栈直路
    (TileDef(tile_id="IC-StraightInn", edges=_t("frfr"),
             roads=(RoadSeg((E, W), inn=True),),
             farms=(FarmSeg(frozenset({N})), FarmSeg(frozenset({S})))), 1),
    # 修道院分隔道路（修道院在路中，东/西两段各自终止）
    (TileDef(tile_id="IC-MonSplit", edges=_t("frfr"),
             roads=(RoadSeg((E,)), RoadSeg((W,))),
             farms=(FarmSeg(frozenset({N})), FarmSeg(frozenset({S}))),
             center=Center.MONASTERY), 1),
    # 客栈弯路
    (TileDef(tile_id="IC-CurveInn", edges=_t("ffrr"),
             roads=(RoadSeg((W, S), inn=True),),
             farms=(FarmSeg(frozenset({N, E})),)), 1),
    # 客栈丁字路（客栈属于东支路，只影响该段）
    (TileDef(tile_id="IC-TInn", edges=_t("frrr"),
             roads=(RoadSeg((E,), inn=True), RoadSeg((S,)), RoadSeg((W,))),
             farms=(FarmSeg(frozenset({N})),),
             center=Center.JUNCTION), 1),
]

# CAR：I&C 18 张拓扑分布（旋转规范化后）
CAR_IC_CLASS_COUNTS: Dict[str, int] = {
    "cccc": 3, "cccf": 2, "ccfr": 1, "ccrf": 1, "ccrr": 1,
    "cfff": 1, "cfrf": 1, "cfrr": 1, "crcr": 2,
    "ffrr": 1, "frfr": 2, "frrr": 1, "rrrr": 1,
}


# ================================================================ 扩展二：商人与建造者
# 24 张牌（CAR：Traders and Builders）。每张都带图元：贸易商品（城）/建造者（城或路）/猪（农场）。
# 拓扑分布严格按 CAR Consolidated Reference（含基础版没有的 ccfr/cfcr/crff 类）。
# 商品分配凑整官方计数：酒 9 / 谷 6 / 布 5（共 20 个符号）。
def _g(*types):
    return tuple(types)


_TILE_SHEET_TB: List[Tuple[TileDef, int]] = [
    # ---- 贸易商品城（14 张，商品 酒9/谷6/布5）
    (TileDef(tile_id="TB-CCCGoods3", edges=_t("cccc"),
             cities=(CitySeg(frozenset({N, E, S, W}), goods=_g("wine", "wine", "grain")),)), 1),
    (TileDef(tile_id="TB-CCGoods2", edges=_t("cccc"),
             cities=(CitySeg(frozenset({N, E, S, W}), goods=_g("wine", "wine")),)), 1),
    (TileDef(tile_id="TB-C3Goods2", edges=_t("cccf"),
             cities=(CitySeg(frozenset({N, E, S}), goods=_g("wine", "wine")),),
             farms=(FarmSeg(frozenset({W}), adj_cities=frozenset({0})),)), 1),
    (TileDef(tile_id="TB-C3Plain", edges=_t("cccf"),
             cities=(CitySeg(frozenset({N, E, S})),),
             farms=(FarmSeg(frozenset({W}), adj_cities=frozenset({0})),)), 1),
    (TileDef(tile_id="TB-C3Builder", edges=_t("cccf"), builder=True,
             cities=(CitySeg(frozenset({N, E, S})),),
             farms=(FarmSeg(frozenset({W}), adj_cities=frozenset({0})),)), 1),
    (TileDef(tile_id="TB-GateCloth2", edges=_t("cccr"),
             cities=(CitySeg(frozenset({N, E, S}), goods=_g("cloth", "cloth")),),
             roads=(RoadSeg((W,)),)), 1),
    (TileDef(tile_id="TB-GateWine", edges=_t("cccr"),
             cities=(CitySeg(frozenset({N, E, S}), goods=_g("wine")),),
             roads=(RoadSeg((W,)),)), 1),
    (TileDef(tile_id="TB-GateGrain", edges=_t("cccr"),
             cities=(CitySeg(frozenset({N, E, S}), goods=_g("grain")),),
             roads=(RoadSeg((W,)),)), 1),
    (TileDef(tile_id="TB-CornerWine", edges=_t("ccff"),
             cities=(CitySeg(frozenset({N, E}), goods=_g("wine")),),
             farms=(FarmSeg(frozenset({S, W}), adj_cities=frozenset({0})),)), 1),
    (TileDef(tile_id="TB-CornerGrain", edges=_t("ccff"),
             cities=(CitySeg(frozenset({N, E}), goods=_g("grain")),),
             farms=(FarmSeg(frozenset({S, W}), adj_cities=frozenset({0})),)), 1),
    # ---- 城 + 猪（农场）/ 建造者（路）
    (TileDef(tile_id="TB-CCfRPig", edges=_t("ccfr"), pig=True,
             cities=(CitySeg(frozenset({N, E})),),
             roads=(RoadSeg((W,)),),
             farms=(FarmSeg(frozenset({S}), adj_cities=frozenset({0})),)), 1),
    (TileDef(tile_id="TB-CCfRCloth", edges=_t("ccfr"),
             cities=(CitySeg(frozenset({N, E}), goods=_g("cloth")),),
             roads=(RoadSeg((W,)),),
             farms=(FarmSeg(frozenset({S}), adj_cities=frozenset({0})),)), 1),
    (TileDef(tile_id="TB-CCRfPig", edges=_t("ccrf"), pig=True,
             cities=(CitySeg(frozenset({N, E})),),
             roads=(RoadSeg((S,)),),
             farms=(FarmSeg(frozenset({W}), adj_cities=frozenset({0})),)), 1),
    (TileDef(tile_id="TB-CCRfGrain", edges=_t("ccrf"),
             cities=(CitySeg(frozenset({N, E}), goods=_g("grain")),),
             roads=(RoadSeg((S,)),),
             farms=(FarmSeg(frozenset({W}), adj_cities=frozenset({0})),)), 1),
    (TileDef(tile_id="TB-CCWine", edges=_t("ccrr"),
             cities=(CitySeg(frozenset({N, E}), goods=_g("wine")),),
             roads=(RoadSeg((W, S)),)), 1),
    (TileDef(tile_id="TB-CCrrBuilder", edges=_t("ccrr"), builder=True,
             cities=(CitySeg(frozenset({N, E})),),
             roads=(RoadSeg((W, S)),)), 1),
    # ---- 对边城 + 布匹 / 建造者
    (TileDef(tile_id="TB-CfBuilder", edges=_t("cfcf"), builder=True,
             cities=(CitySeg(frozenset({N, S})),),
             farms=(FarmSeg(frozenset({E})), FarmSeg(frozenset({W})))), 1),
    # ---- 城田城路（cfcr：基础版没有的类）+ 商品/谷
    (TileDef(tile_id="TB-CfcCloth2", edges=_t("cfcr"),
             cities=(CitySeg(frozenset({N}), goods=_g("cloth")),
                     CitySeg(frozenset({S}), goods=_g("cloth"))),
             roads=(RoadSeg((W,)),),
             farms=(FarmSeg(frozenset({E}), adj_cities=frozenset({0, 1})),)), 1),
    (TileDef(tile_id="TB-CfcGrain", edges=_t("cfcr"),
             cities=(CitySeg(frozenset({N}), goods=_g("grain")),
                     CitySeg(frozenset({S}), goods=_g("grain"))),
             roads=(RoadSeg((W,)),),
             farms=(FarmSeg(frozenset({E}), adj_cities=frozenset({0, 1})),)), 1),
    # ---- 城 + 弯路布 / 弯路建造者
    (TileDef(tile_id="TB-CurveBuilder", edges=_t("cfrr"), builder=True,
             cities=(CitySeg(frozenset({N})),),
             roads=(RoadSeg((W, S)),),
             farms=(FarmSeg(frozenset({E}), adj_cities=frozenset({0})),)), 1),
    # ---- 城路城路 + 谷 / 建造者
    (TileDef(tile_id="TB-CrcBuilder", edges=_t("crcr"), builder=True,
             cities=(CitySeg(frozenset({N})), CitySeg(frozenset({S}))),
             roads=(RoadSeg((E, W)),)), 1),
    # ---- 城路田田 + 猪（农场 S/W）
    (TileDef(tile_id="TB-CrffPig", edges=_t("crff"), pig=True,
             cities=(CitySeg(frozenset({N})),),
             roads=(RoadSeg((E,)),),
             farms=(FarmSeg(frozenset({S, W}), adj_cities=frozenset({0})),)), 1),
    # ---- 修道院分隔三路 + 猪（CAR："cloister divides the road into three segments"）
    (TileDef(tile_id="TB-Mon3RdPig", edges=_t("frrr"), pig=True,
             roads=(RoadSeg((E,)), RoadSeg((S,)), RoadSeg((W,))),
             farms=(FarmSeg(frozenset({N})),),
             center=Center.MONASTERY), 1),
    # ---- 桥牌（CAR："The bridge is not a crossing"：两条贯通直路 + 四段独立田）
    (TileDef(tile_id="TB-Bridge", edges=_t("rrrr"), builder=True,
             roads=(RoadSeg((E, W)), RoadSeg((N, S))),
             farms=(FarmSeg(frozenset({N})), FarmSeg(frozenset({E})),
                    FarmSeg(frozenset({S})), FarmSeg(frozenset({W})))), 1),
]

CAR_TB_CLASS_COUNTS: Dict[str, int] = {
    "cccc": 2, "cccf": 3, "cccr": 3, "ccff": 2, "ccfr": 2, "ccrf": 2,
    "ccrr": 2, "cfcf": 1, "cfcr": 2, "cfrr": 1, "crcr": 1, "crff": 1,
    "frrr": 1, "rrrr": 1,
}


# ================================================================ 扩展三：公主与龙
# 30 张牌（CAR：The Princess & the Dragon）= 6 火山 + 12 龙牌 + 6 传送门 + 6 公主。
# 符号×拓扑分配按 CAR Consolidated Reference 线性规划凑定。
# 特殊牌：城内修道院（可部署骑士或僧侣）、全田火山+修道院。
def _PD(tile_id, edges, symbol, cities=(), roads=(), farms=(), center=Center.NONE,
        mon_in_city=False):
    kw = {}
    if symbol == "volcano":
        kw["volcano"] = True
    elif symbol == "dragon":
        kw["dragon_tile"] = True
    elif symbol == "princess":
        kw["princess"] = True
    elif symbol == "portal":
        kw["portal"] = True
    return TileDef(tile_id=tile_id, edges=edges, cities=cities, roads=roads,
                   farms=farms, center=center, mon_in_city=mon_in_city, **kw)


_TILE_SHEET_PD: List[Tuple[TileDef, int]] = [
    # ---- cccf ×4（龙2 门1 公主1；含城内修道院）
    (_PD("PD-CCfMon", _t("cccf"), "dragon", mon_in_city=True,
         cities=(CitySeg(frozenset({N, E, S})),),
         farms=(FarmSeg(frozenset({W}), adj_cities=frozenset({0})),),
         center=Center.MONASTERY), 1),
    (_PD("PD-CCfDragon", _t("cccf"), "dragon",
         cities=(CitySeg(frozenset({N, E, S})),),
         farms=(FarmSeg(frozenset({W}), adj_cities=frozenset({0})),)), 1),
    (_PD("PD-CCfPortal", _t("cccf"), "portal",
         cities=(CitySeg(frozenset({N, E, S})),),
         farms=(FarmSeg(frozenset({W}), adj_cities=frozenset({0})),)), 1),
    (_PD("PD-CCfPrincess", _t("cccf"), "princess",
         cities=(CitySeg(frozenset({N, E, S})),),
         farms=(FarmSeg(frozenset({W}), adj_cities=frozenset({0})),)), 1),
    # ---- ccff ×4（龙2 门1 公主1 火山1）
    (_PD("PD-CCffDragon", _t("ccff"), "dragon",
         cities=(CitySeg(frozenset({N, E})),),
         farms=(FarmSeg(frozenset({S, W}), adj_cities=frozenset({0})),)), 1),
    (_PD("PD-CCffDragon2", _t("ccff"), "dragon",
         cities=(CitySeg(frozenset({N, E})),),
         farms=(FarmSeg(frozenset({S, W}), adj_cities=frozenset({0})),)), 1),
    (_PD("PD-CCffPrincess", _t("ccff"), "princess",
         cities=(CitySeg(frozenset({N, E})),),
         farms=(FarmSeg(frozenset({S, W}), adj_cities=frozenset({0})),)), 1),
    (_PD("PD-CCffVolcano", _t("ccff"), "volcano",
         cities=(CitySeg(frozenset({N, E})),),
         farms=(FarmSeg(frozenset({S, W}), adj_cities=frozenset({0})),)), 1),
    # ---- ccrr ×2（门1 公主1）
    (_PD("PD-CCrPortal", _t("ccrr"), "portal",
         cities=(CitySeg(frozenset({N, E})),),
         roads=(RoadSeg((W, S)),)), 1),
    (_PD("PD-CCrPrincess", _t("ccrr"), "princess",
         cities=(CitySeg(frozenset({N, E})),),
         roads=(RoadSeg((W, S)),)), 1),
    # ---- cfcf ×1（门1）
    (_PD("PD-CfPortal", _t("cfcf"), "portal",
         cities=(CitySeg(frozenset({N, S})),),
         farms=(FarmSeg(frozenset({E})), FarmSeg(frozenset({W})))), 1),
    # ---- cfff ×2（火山1 公主1）
    (_PD("PD-CfffVolcano", _t("cfff"), "volcano",
         cities=(CitySeg(frozenset({N})),),
         farms=(FarmSeg(frozenset({E, S, W}), adj_cities=frozenset({0})),)), 1),
    (_PD("PD-CfffPrincess", _t("cfff"), "princess",
         cities=(CitySeg(frozenset({N})),),
         farms=(FarmSeg(frozenset({E, S, W}), adj_cities=frozenset({0})),)), 1),
    # ---- cfrr ×2（龙1 火山1）
    (_PD("PD-CurveDragon", _t("cfrr"), "dragon",
         cities=(CitySeg(frozenset({N})),),
         roads=(RoadSeg((W, S)),),
         farms=(FarmSeg(frozenset({E}), adj_cities=frozenset({0})),)), 1),
    (_PD("PD-CurveVolcano", _t("cfrr"), "volcano",
         cities=(CitySeg(frozenset({N})),),
         roads=(RoadSeg((W, S)),),
         farms=(FarmSeg(frozenset({E}), adj_cities=frozenset({0})),)), 1),
    # ---- crcr ×1（龙1：双独立城 + 交叉口分离路）
    (_PD("PD-CrcDragon", _t("crcr"), "dragon",
         cities=(CitySeg(frozenset({N})), CitySeg(frozenset({S}))),
         roads=(RoadSeg((E,)), RoadSeg((W,))),
         center=Center.JUNCTION), 1),
    # ---- crrf ×2（公主1 龙1）
    (_PD("PD-CrrfPrincess", _t("crrf"), "princess",
         cities=(CitySeg(frozenset({N})),),
         roads=(RoadSeg((E, S)),),
         farms=(FarmSeg(frozenset({W}), adj_cities=frozenset({0})),)), 1),
    (_PD("PD-CrrfDragon", _t("crrf"), "dragon",
         cities=(CitySeg(frozenset({N})),),
         roads=(RoadSeg((E, S)),),
         farms=(FarmSeg(frozenset({W}), adj_cities=frozenset({0})),)), 1),
    # ---- crrr ×1（火山1：城 + 三臂交叉口）
    (_PD("PD-CrrrVolcano", _t("crrr"), "volcano",
         cities=(CitySeg(frozenset({N})),),
         roads=(RoadSeg((E,)), RoadSeg((S,)), RoadSeg((W,))),
         center=Center.JUNCTION), 1),
    # ---- ffff ×1（火山 + 修道院）
    (_PD("PD-FfffVolcano", _t("ffff"), "volcano",
         farms=(FarmSeg(frozenset({N, E, S, W})),),
         center=Center.MONASTERY), 1),
    # ---- fffr ×1（龙1：修道院 + 南路）
    (_PD("PD-FffrDragon", _t("fffr"), "dragon",
         roads=(RoadSeg((W,)),),
         farms=(FarmSeg(frozenset({N, E, S})),),
         center=Center.MONASTERY), 1),
    # ---- ffrr ×3（龙1 门1 公主1）
    (_PD("PD-CurveDragon2", _t("ffrr"), "dragon",
         roads=(RoadSeg((W, S)),),
         farms=(FarmSeg(frozenset({N, E})),)), 1),
    (_PD("PD-CurvePortal", _t("ffrr"), "portal",
         roads=(RoadSeg((W, S)),),
         farms=(FarmSeg(frozenset({N, E})),)), 1),
    (_PD("PD-CurvePrincess", _t("ffrr"), "princess",
         roads=(RoadSeg((W, S)),),
         farms=(FarmSeg(frozenset({N, E})),)), 1),
    # ---- frfr ×2（门1 龙1）
    (_PD("PD-StraightPortal", _t("frfr"), "portal",
         roads=(RoadSeg((E, W)),),
         farms=(FarmSeg(frozenset({N})), FarmSeg(frozenset({S})))), 1),
    (_PD("PD-StraightDragon", _t("frfr"), "dragon",
         roads=(RoadSeg((E, W)),),
         farms=(FarmSeg(frozenset({N})), FarmSeg(frozenset({S})))), 1),
    # ---- frrr ×3（火山1 龙1 门1）
    (_PD("PD-TVolcano", _t("frrr"), "volcano",
         roads=(RoadSeg((E,)), RoadSeg((S,)), RoadSeg((W,))),
         farms=(FarmSeg(frozenset({N})),),
         center=Center.JUNCTION), 1),
    (_PD("PD-TDragon", _t("frrr"), "dragon",
         roads=(RoadSeg((E,)), RoadSeg((S,)), RoadSeg((W,))),
         farms=(FarmSeg(frozenset({N})),),
         center=Center.JUNCTION), 1),
    (_PD("PD-TPortal", _t("frrr"), "portal",
         roads=(RoadSeg((E,)), RoadSeg((S,)), RoadSeg((W,))),
         farms=(FarmSeg(frozenset({N})),),
         center=Center.JUNCTION), 1),
    # ---- rrrr ×1（公主1：四臂交叉口）
    (_PD("PD-CrossDragon", _t("rrrr"), "dragon",
         roads=(RoadSeg((N,)), RoadSeg((E,)), RoadSeg((S,)), RoadSeg((W,))),
         center=Center.JUNCTION), 1),
]

CAR_PD_CLASS_COUNTS: Dict[str, int] = {
    "cccf": 4, "ccff": 4, "ccrr": 2, "cfcf": 1, "cfff": 2, "cfrr": 2,
    "crcr": 1, "crrf": 2, "crrr": 1, "ffff": 1, "fffr": 1, "ffrr": 3,
    "frfr": 2, "frrr": 3, "rrrr": 1,
}


# ================================================================ 扩展四：修道院与市长
# 12 张牌（CAR：Abbey & Mayor）。6 张修道院牌（全田+修道院，可放任意相邻空格、
# 无需边匹配）+ 6 张图元牌（市长/粮仓/马车各 2；拓扑无 CAR 文本数据，best-effort
# 组合，图元机制为核心）。
_TILE_SHEET_AM: List[Tuple[TileDef, int]] = [
    # ---- 修道院牌 ×6（全田 + 修道院 + abbey 放置特例）
    (TileDef(tile_id="AM-Abbey", edges=_t("ffff"), abbey=True,
             farms=(FarmSeg(frozenset({N, E, S, W})),),
             center=Center.MONASTERY), 6),
    # ---- 市长城牌 ×2
    (TileDef(tile_id="AM-CCfMayor", edges=_t("cccf"), builder=False, mayor=True,
             cities=(CitySeg(frozenset({N, E, S})),),
             farms=(FarmSeg(frozenset({W}), adj_cities=frozenset({0})),)), 1),
    (TileDef(tile_id="AM-CCornerMayor", edges=_t("ccff"), mayor=True,
             cities=(CitySeg(frozenset({N, E})),),
             farms=(FarmSeg(frozenset({S, W}), adj_cities=frozenset({0})),)), 1),
    # ---- 粮仓农场牌 ×2（barn 图元在农场角）
    (TileDef(tile_id="AM-CfffBarn", edges=_t("cfff"), barn=True,
             cities=(CitySeg(frozenset({N})),),
             farms=(FarmSeg(frozenset({E, S, W}), adj_cities=frozenset({0})),)), 1),
    (TileDef(tile_id="AM-ffrrBarn", edges=_t("ffrr"), barn=True,
             roads=(RoadSeg((W, S)),),
             farms=(FarmSeg(frozenset({N, E})),)), 1),
    # ---- 马车城/路牌 ×2
    (TileDef(tile_id="AM-CRCWagon", edges=_t("crfr"), wagon=True,
             cities=(CitySeg(frozenset({N})),),
             roads=(RoadSeg((E, W)),),
             farms=(FarmSeg(frozenset({S}), adj_cities=frozenset({0})),)), 1),
    (TileDef(tile_id="AM-CCRWagon", edges=_t("ccrr"), wagon=True,
             cities=(CitySeg(frozenset({N, E})),),
             roads=(RoadSeg((W, S)),)), 1),
]

# ---------------------------------------------------------------- 伯爵、国王与强盗
# （Count, King & Robber，CAR 页 69-87；牌面经 CAR 图版 / WikiCarpedia / 社区数据集三源核对）

# —— 国王与强盗男爵 5 张（CAR 页 71）——
_TILE_SHEET_KRB: List[Tuple[TileDef, int]] = [
    # 双城十字桥牌：两段城交叉（N-S 与 E-W 各一段；WikiCarpedia："one goes from the
    # top to the bottom ... the other goes from left to right, across the bridge"）
    # + 两段封闭内田（"2× Inner Farm"，永不连通、无处可依）
    (TileDef(tile_id="KR-CrossCity", edges=_t("cccc"),
             cities=(CitySeg(frozenset({N, S})), CitySeg(frozenset({E, W}))),
             farms=(FarmSeg(frozenset()), FarmSeg(frozenset()))), 1),
    # 大城（N+E，无旗帜）+ 城门弯路 W→S
    (TileDef(tile_id="KR-CityRoads", edges=_t("ccrr"),
             cities=(CitySeg(frozenset({N, E})),),
             roads=(RoadSeg((W, S)),)), 1),
    # 单边城 + 修道院（田野环绕）
    (TileDef(tile_id="KR-Cloister", edges=_t("cfff"),
             cities=(CitySeg(frozenset({N})),),
             farms=(FarmSeg(frozenset({E, S, W}), adj_cities=frozenset({0})),),
             center=Center.MONASTERY), 1),
    # 单边城 + 城门路 W（路止于城门）
    (TileDef(tile_id="KR-GateRoad", edges=_t("cffr"),
             cities=(CitySeg(frozenset({N})),),
             roads=(RoadSeg((W,)),),
             farms=(FarmSeg(frozenset({E, S}), adj_cities=frozenset({0})),)), 1),
    # 单边城 + 城门路 W + 弯路 E→S（田被三路围合，封闭）
    (TileDef(tile_id="KR-ThreeRoads", edges=_t("crrr"),
             cities=(CitySeg(frozenset({N})),),
             roads=(RoadSeg((W,)), RoadSeg((E, S))),
             farms=(FarmSeg(frozenset()),)), 1),
]

# —— 河流 II 12 张（CAR 页 79-83）——
# 结构自洽性：泉源 1 水边起，岔流 +1 开口，9 张双水边 ±0，湖城/火山湖各 -1，
# 全链恰好闭合（1 +1 -1 -1 = 0）；火山湖最后放置（CAR 页 80）。
_TILE_SHEET_RII: List[Tuple[TileDef, int]] = [
    # 泉源（起始牌）：单水边 S；田地绕泉连为一段（CAR 脚注 234）
    (TileDef(tile_id="RI-Spring", edges=_t("ffwf"),
             farms=(FarmSeg(frozenset({N, E, W})),),
             spring=True, is_start=True), 1),
    # 岔流：三水边（一连二出； youngest 玩家第二张放置）
    (TileDef(tile_id="RI-Junction", edges=_t("wwfw"),
             farms=(FarmSeg(frozenset({S})),)), 1),
    # 弯河 E→S + 弯路 N→W（田封闭，略）
    (TileDef(tile_id="RI-RiverRoadA", edges=_t("rwwr"),
             roads=(RoadSeg((N, W)),)), 1),
    # 弯河 W→S + 弯路 N→E（与上张手性相反）
    (TileDef(tile_id="RI-RiverRoadB", edges=_t("rrww"),
             roads=(RoadSeg((N, E)),)), 1),
    # 猪倌牌：弯河 N→W + 农场（终局农夫 +1 分/城，脚注 247-251）
    (TileDef(tile_id="RI-PigHerd", edges=_t("wffw"), pig_herd=True,
             farms=(FarmSeg(frozenset({E, S})),)), 1),
    # 单边城（旗帜）+ 弯河 W→S；田与城相邻
    (TileDef(tile_id="RI-CityShield", edges=_t("cfww"),
             cities=(CitySeg(frozenset({N}), pennant=True),),
             farms=(FarmSeg(frozenset({E}), adj_cities=frozenset({0})),)), 1),
    # 横贯城 E-W + 直河 N→S（河上架城，田封闭）
    (TileDef(tile_id="RI-CitySpan", edges=_t("wcwc"),
             cities=(CitySeg(frozenset({E, W})),)), 1),
    # 单边城 W + 城门路 E（跨河桥）+ 直河 N→S
    (TileDef(tile_id="RI-CityGate", edges=_t("wrwc"),
             cities=(CitySeg(frozenset({W})),),
             roads=(RoadSeg((E,)),)), 1),
    # 修道院 + 直河 E→W（河分隔两侧田）
    (TileDef(tile_id="RI-Monastery", edges=_t("fwfw"),
             farms=(FarmSeg(frozenset({N})), FarmSeg(frozenset({S}))),
             center=Center.MONASTERY), 1),
    # 客栈桥：直路 E→W（跨河桥，带客栈）+ 直河 N→S；四象限独立田（WikiCarpedia：
    # "Fields do not go under small bridges - there are 4 separate fields"）
    (TileDef(tile_id="RI-InnBridge", edges=_t("wrwr"),
             roads=(RoadSeg((E, W), inn=True),)), 1),
    # 湖 + 单边城 S + 单水边 N
    (TileDef(tile_id="RI-LakeCity", edges=_t("wfcf"),
             cities=(CitySeg(frozenset({S})),),
             farms=(FarmSeg(frozenset({E, W}), adj_cities=frozenset({0})),)), 1),
    # 火山湖（末张）：单水边 N；田绕湖连为一段；龙降临湖面
    (TileDef(tile_id="RI-VolcanoLake", edges=_t("wfff"), volcano=True,
             farms=(FarmSeg(frozenset({E, S, W})),)), 1),
]

# —— 教堂与异端 5 张（CK&R 版；CAR 页 84-86；数据集 HES 的 #1/#2/#4/#5/#6）——
_TILE_SHEET_HES: List[Tuple[TileDef, int]] = [
    # 城边教堂：单边城 + 教堂（修道院型，可挑战）
    (TileDef(tile_id="HES-CityShrine", edges=_t("cfff"), shrine=True,
             cities=(CitySeg(frozenset({N})),),
             farms=(FarmSeg(frozenset({E, S, W}), adj_cities=frozenset({0})),),
             center=Center.MONASTERY), 1),
    # 城边教堂 + 南路
    (TileDef(tile_id="HES-CityRoadShrine", edges=_t("cfrf"), shrine=True,
             cities=(CitySeg(frozenset({N})),),
             roads=(RoadSeg((S,)),),
             farms=(FarmSeg(frozenset({E, W}), adj_cities=frozenset({0})),),
             center=Center.MONASTERY), 1),
    # 全田教堂（异端盘踞的野外教堂）
    (TileDef(tile_id="HES-FieldShrine", edges=_t("ffff"), shrine=True,
             farms=(FarmSeg(frozenset({N, E, S, W})),),
             center=Center.MONASTERY), 1),
    # 田野教堂 + 南路
    (TileDef(tile_id="HES-RoadShrine", edges=_t("ffrf"), shrine=True,
             roads=(RoadSeg((S,)),),
             farms=(FarmSeg(frozenset({N, E, W})),),
             center=Center.MONASTERY), 1),
    # 田野教堂 + 南北直路（路旁教堂）
    (TileDef(tile_id="HES-RoadsShrine", edges=_t("rfrf"), shrine=True,
             roads=(RoadSeg((N, S)),),
             farms=(FarmSeg(frozenset({E})), FarmSeg(frozenset({W}))),
             center=Center.MONASTERY), 1),
]

# —— 桥、城堡与集市 12 张（CAR 页 92-101；第一张 ×2）——
# 集市黄地终止道路（脚注 280：马车不可穿过集市）。
_TILE_SHEET_BCB: List[Tuple[TileDef, int]] = [
    # 全城 + 城内集市 ×2
    (TileDef(tile_id="BCB-CAllBazaar", edges=_t("cccc"),
             cities=(CitySeg(frozenset({N, E, S, W})),),
             bazaar=True), 2),
    # 三边独立城 + 西路（止于田）
    (TileDef(tile_id="BCB-C3sepR", edges=_t("cccr"),
             cities=(CitySeg(frozenset({N})), CitySeg(frozenset({E})),
                     CitySeg(frozenset({S}))),
             roads=(RoadSeg((W,)),),
             farms=(FarmSeg(frozenset(), adj_cities=frozenset({0, 1, 2})),)), 1),
    # 东西贯通城 + 南北田 + 城内集市
    (TileDef(tile_id="BCB-CEWBazaar", edges=_t("fcfc"),
             cities=(CitySeg(frozenset({E, W})),),
             farms=(FarmSeg(frozenset({N}), adj_cities=frozenset({0})),
                    FarmSeg(frozenset({S}), adj_cities=frozenset({0}))),
             bazaar=True), 1),
    # 东西贯通城（旗帜）+ 南北田
    (TileDef(tile_id="BCB-CEWPennant", edges=_t("fcfc"),
             cities=(CitySeg(frozenset({E, W}), pennant=True),),
             farms=(FarmSeg(frozenset({N}), adj_cities=frozenset({0})),
                    FarmSeg(frozenset({S}), adj_cities=frozenset({0})))), 1),
    # 北边城 + 南路止于集市
    (TileDef(tile_id="BCB-C1sBazaar", edges=_t("cfrf"),
             cities=(CitySeg(frozenset({N})),),
             roads=(RoadSeg((S,)),),
             farms=(FarmSeg(frozenset({E, W}), adj_cities=frozenset({0})),),
             bazaar=True), 1),
    # 东边三角城 + 南路（脚注 299：不可改建城堡）
    (TileDef(tile_id="BCB-TriCity", edges=_t("fcrf"),
             cities=(CitySeg(frozenset({E})),),
             roads=(RoadSeg((S,)),),
             farms=(FarmSeg(frozenset({N, W}), adj_cities=frozenset({0})),)), 1),
    # 全田集市
    (TileDef(tile_id="BCB-FieldBazaar", edges=_t("ffff"),
             farms=(FarmSeg(frozenset({N, E, S, W})),),
             bazaar=True), 1),
    # 南路止于集市 + 客栈
    (TileDef(tile_id="BCB-InnBazaar", edges=_t("ffrf"),
             roads=(RoadSeg((S,), inn=True),),
             farms=(FarmSeg(frozenset({N, E, W})),),
             bazaar=True), 1),
    # 南北两路均止于集市
    (TileDef(tile_id="BCB-NSBazaar", edges=_t("rfrf"),
             roads=(RoadSeg((N,)), RoadSeg((S,))),
             farms=(FarmSeg(frozenset({E})), FarmSeg(frozenset({W}))),
             bazaar=True), 1),
    # 南北两路止于集市 + 客栈（南段）
    (TileDef(tile_id="BCB-NSInnBazaar", edges=_t("rfrf"),
             roads=(RoadSeg((N,)), RoadSeg((S,), inn=True)),
             farms=(FarmSeg(frozenset({E})), FarmSeg(frozenset({W}))),
             bazaar=True), 1),
    # 修道院 + 东西贯通路
    (TileDef(tile_id="BCB-MonEW", edges=_t("frfr"),
             roads=(RoadSeg((E, W)),),
             farms=(FarmSeg(frozenset({N})), FarmSeg(frozenset({S}))),
             center=Center.MONASTERY), 1),
]

# —— 伯爵城起始版图 12 张（CAR 页 72-78；4×3 固定块，不入牌堆）——
# 内边 = 城墙（大城贯通各牌，开局即完整）；外圈 = 田（草地环带，跨牌边界连为
# 一圈：内边城+田双覆盖，合并逻辑按段覆盖查找，天然支持）。
# 外边特例：(0,0) 西边城门路；(3,0) 北边河道（CAR 脚注 206：河应"引离城去"）。
# 四区（城堡/市场/铁匠/大教堂）为抽象等候区，不落在牌面拓扑上。
def _cc(c: int, r: int) -> TileDef:
    """伯爵城块内 (col,row) 牌：内边城、外边田，(0,0)W 路、(3,0)N 水。"""
    edges = []
    for side in (N, E, S, W):
        if side == N:
            interior = r > 0
        elif side == S:
            interior = r < 2
        elif side == W:
            interior = c > 0
        else:
            interior = c < 3
        if interior:
            edges.append(Terrain.CITY)
        elif (c, r) == (0, 0) and side == W:
            edges.append(Terrain.ROAD)
        elif (c, r) == (3, 0) and side == N:
            edges.append(Terrain.WATER)
        else:
            edges.append(Terrain.FIELD)
    interior_set = frozenset(
        side for side in (N, E, S, W)
        if (edges[side] is Terrain.CITY))
    outer_set = frozenset(
        side for side in (N, E, S, W)
        if edges[side] is Terrain.FIELD)
    boundary = (c in (0, 3)) or (r in (0, 2))
    farms = ()
    if boundary and outer_set:
        # 草地环带：外圈田边 + 内边双覆盖（跨牌连成环）；相邻本牌大城
        farms = (FarmSeg(frozenset(set(outer_set) | set(interior_set)),
                         adj_cities=frozenset({0})),)
    roads = ()
    if (c, r) == (0, 0):
        roads = (RoadSeg((W,)),)   # 城门路：止于城门，向外接路
    return TileDef(tile_id="CC-%d%d" % (c, r), edges=tuple(edges),
                   cities=(CitySeg(interior_set),), roads=roads, farms=farms,
                   count_city=True)


CC_BLOCK: List[Tuple[int, int, TileDef]] = [
    (c, r, _cc(c, r)) for r in range(3) for c in range(4)
]

# 四区所属牌（仅用于界面展示等候区方位；规则上四区是抽象等候区）
CC_QUARTERS: Dict[str, List[Tuple[int, int]]] = {
    "castle": [(2, 0), (3, 0), (3, 1)],
    "market": [(2, 1), (3, 2), (2, 2)],
    "cathedral": [(0, 0), (0, 1), (1, 1)],
    "blacksmith": [(1, 0), (0, 2), (1, 2)],
}

# —— M20 迷你扩展（CAR 页 120-133/140-150/157-159/172-198）——
# 牌面辨讹来源：CAR 各牌面分布页内嵌图（98-130px）+ 边缘像素采样交叉核对。
# 脚注口径：358 麦田圈路口三路止于交叉口；359 CC-II 黄圈为独立特征（分隔路段）；
# 294（BCB）路可止于田（麦田圈/集市/隧道口同理，可被木桥跨接）。

# 围攻 6 张（CAR 页 120-124；所有牌带围攻图腾，siege=True）
_TILE_SHEET_BES: List[Tuple[TileDef, int]] = [
    # 城{N,W} + 南路止于城门
    (TileDef(tile_id="BES-NWr", edges=_t("cfrc"),
             cities=(CitySeg(frozenset({N, W})),),
             roads=(RoadSeg((S,)),),
             farms=(FarmSeg(frozenset({E}), adj_cities=frozenset({0})),
                    FarmSeg(frozenset(), adj_cities=frozenset({0}))),
             siege=True), 1),
    # 城{N,W,E} + 南田
    (TileDef(tile_id="BES-NWE", edges=_t("ccfc"),
             cities=(CitySeg(frozenset({N, W, E})),),
             farms=(FarmSeg(frozenset({S}), adj_cities=frozenset({0})),),
             siege=True), 1),
    # 城{N,E} 对角 + 西南田
    (TileDef(tile_id="BES-NE", edges=_t("ccff"),
             cities=(CitySeg(frozenset({N, E})),),
             farms=(FarmSeg(frozenset({W, S}), adj_cities=frozenset({0})),),
             siege=True), 1),
    # 城{N,E} 对角 + 路{W,S} 折弯
    (TileDef(tile_id="BES-NErs", edges=_t("ccrr"),
             cities=(CitySeg(frozenset({N, E})),),
             roads=(RoadSeg((W, S)),),
             farms=(FarmSeg(frozenset()), FarmSeg(frozenset())),
             siege=True), 1),
    # 城{N}（V 形墙）+ 三边田
    (TileDef(tile_id="BES-N", edges=_t("cfff"),
             cities=(CitySeg(frozenset({N})),),
             farms=(FarmSeg(frozenset({W, E, S}), adj_cities=frozenset({0})),),
             siege=True), 1),
    # 城{N} + 东西贯通路 + 南北两田
    (TileDef(tile_id="BES-Nwe", edges=_t("crfr"),
             cities=(CitySeg(frozenset({N})),),
             roads=(RoadSeg((W, E)),),
             farms=(FarmSeg(frozenset(), adj_cities=frozenset({0})),
                    FarmSeg(frozenset({S}), adj_cities=frozenset({0}))),
             siege=True), 1),
]

# 节日 10 张（CAR 页 140-141；所有牌带 10 周年节庆图腾，festival=True）
_TILE_SHEET_FES: List[Tuple[TileDef, int]] = [
    # 双对角城带 {N,W} + {E,S}，中央内田
    (TileDef(tile_id="FES-X", edges=_t("cccc"),
             cities=(CitySeg(frozenset({N, W})), CitySeg(frozenset({E, S}))),
             farms=(FarmSeg(frozenset(), adj_cities=frozenset({0, 1})),),
             festival=True), 1),
    # 三面城{N,E,S} + 西田
    (TileDef(tile_id="FES-C3", edges=_t("cccf"),
             cities=(CitySeg(frozenset({N, E, S})),),
             farms=(FarmSeg(frozenset({W}), adj_cities=frozenset({0})),),
             festival=True), 1),
    # 城{N} + 路{W,S} 折弯
    (TileDef(tile_id="FES-Nws", edges=_t("cfrr"),
             cities=(CitySeg(frozenset({N})),),
             roads=(RoadSeg((W, S)),),
             farms=(FarmSeg(frozenset({E})),
                    FarmSeg(frozenset(), adj_cities=frozenset({0}))),
             festival=True), 1),
    # 城{N} + 南路止于城门
    (TileDef(tile_id="FES-Ns", edges=_t("cfrf"),
             cities=(CitySeg(frozenset({N})),),
             roads=(RoadSeg((S,)),),
             farms=(FarmSeg(frozenset({W}), adj_cities=frozenset({0})),
                    FarmSeg(frozenset({E}), adj_cities=frozenset({0}))),
             festival=True), 1),
    # 城{N} + 路{N门,S}——与 FES-Ns 同构异面（曲线差异）
    (TileDef(tile_id="FES-Ns2", edges=_t("cfrf"),
             cities=(CitySeg(frozenset({N})),),
             roads=(RoadSeg((S,)),),
             farms=(FarmSeg(frozenset({W}), adj_cities=frozenset({0})),
                    FarmSeg(frozenset({E}), adj_cities=frozenset({0}))),
             festival=True), 1),
    # 上下两城带 {N}+{S} + 东西路十字过城门间
    (TileDef(tile_id="FES-NSwe", edges=_t("crcr"),
             cities=(CitySeg(frozenset({N})), CitySeg(frozenset({S}))),
             roads=(RoadSeg((W, E)),),
             farms=(FarmSeg(frozenset()),), festival=True), 1),
    # 城{N} + 东路止于城门
    (TileDef(tile_id="FES-Ne", edges=_t("crff"),
             cities=(CitySeg(frozenset({N})),),
             roads=(RoadSeg((E,)),),
             farms=(FarmSeg(frozenset({W, S}), adj_cities=frozenset({0})),),
             festival=True), 1),
    # 城{N} + 南路出城门（右弯）
    (TileDef(tile_id="FES-Ns3", edges=_t("cfrf"),
             cities=(CitySeg(frozenset({N})),),
             roads=(RoadSeg((S,)),),
             farms=(FarmSeg(frozenset({W}), adj_cities=frozenset({0})),
                    FarmSeg(frozenset({E}), adj_cities=frozenset({0}))),
             festival=True), 1),
    # 大宅（非城段）+ 路{W,S} 折弯绕行
    (TileDef(tile_id="FES-manor", edges=_t("ffrr"),
             roads=(RoadSeg((W, S)),),
             farms=(FarmSeg(frozenset({N, E})),),
             festival=True), 1),
    # 路{N,W} 折弯
    (TileDef(tile_id="FES-nw", edges=_t("rffr"),
             roads=(RoadSeg((N, W)),),
             farms=(FarmSeg(frozenset({E, S})),),
             festival=True), 1),
]

# 金矿 8 张（CAR 页 148-150；带金块图腾，gold=True；第 9 张为随附麦田圈牌）
_TILE_SHEET_GLD: List[Tuple[TileDef, int]] = [
    # 城{N,E} 对角 + 西南田
    (TileDef(tile_id="GLD-NE", edges=_t("ccff"),
             cities=(CitySeg(frozenset({N, E})),),
             farms=(FarmSeg(frozenset({W, S}), adj_cities=frozenset({0})),),
             gold=True), 1),
    # 东西两城夹南北直路（穿双城门）
    (TileDef(tile_id="GLD-WEns", edges=_t("rcrc"),
             cities=(CitySeg(frozenset({W})), CitySeg(frozenset({E}))),
             roads=(RoadSeg((N, S)),), gold=True), 1),
    # 城{N,E} 对角 + 路{W,S} 折弯
    (TileDef(tile_id="GLD-NEws", edges=_t("ccrr"),
             cities=(CitySeg(frozenset({N, E})),),
             roads=(RoadSeg((W, S)),),
             farms=(FarmSeg(frozenset(), adj_cities=frozenset({0})),),
             gold=True), 1),
    # 城{N,W} 对角 + 路{E,S} 折弯
    (TileDef(tile_id="GLD-NWes", edges=_t("crrc"),
             cities=(CitySeg(frozenset({N, W})),),
             roads=(RoadSeg((E, S)),),
             farms=(FarmSeg(frozenset(), adj_cities=frozenset({0})),),
             gold=True), 1),
    # 修道院 + 路{W,S} 与 {N,E} 两段绕行
    (TileDef(tile_id="GLD-Mon", edges=_t("rrrr"),
             roads=(RoadSeg((W, S)), RoadSeg((N, E))),
             farms=(FarmSeg(frozenset()), FarmSeg(frozenset())),
             center=Center.MONASTERY, gold=True), 1),
    # 路{N,W} 与 {S,E} 两段折弯
    (TileDef(tile_id="GLD-nwse", edges=_t("rrrr"),
             roads=(RoadSeg((N, W)), RoadSeg((S, E))),
             farms=(FarmSeg(frozenset()), FarmSeg(frozenset())),
             gold=True), 1),
    # 高架桥：路{W,E}（桥面）与 {N,S}（桥下）不相接
    (TileDef(tile_id="GLD-bridge", edges=_t("rrrr"),
             roads=(RoadSeg((W, E)), RoadSeg((N, S))),
             farms=(FarmSeg(frozenset()), FarmSeg(frozenset())),
             gold=True), 1),
    # 修道院 + 路{S,E} 折弯
    (TileDef(tile_id="GLD-Mon2", edges=_t("frrf"),
             roads=(RoadSeg((S, E)),),
             farms=(FarmSeg(frozenset({N, W})),),
             center=Center.MONASTERY, gold=True), 1),
    # 随附麦田圈牌（CC-II）：城{N} + 东西两路止于黄圈 + 南田；草叉=农场圈
    (TileDef(tile_id="GLD-CC", edges=_t("crfr"),
             cities=(CitySeg(frozenset({N})),),
             roads=(RoadSeg((W,)), RoadSeg((E,))),
             farms=(FarmSeg(frozenset({S}), adj_cities=frozenset({0})),),
             crop="farm"), 1),
]

# 法师与女巫 8 张（CAR 页 157-159；带法师图腾，mage=True；第 9 张为随附麦田圈牌）
_TILE_SHEET_MGW: List[Tuple[TileDef, int]] = [
    # 城{N,W} + 路{S,E} 折弯
    (TileDef(tile_id="MGW-NWse", edges=_t("crrc"),
             cities=(CitySeg(frozenset({N, W})),),
             roads=(RoadSeg((S, E)),),
             farms=(FarmSeg(frozenset()),),
             mage=True), 1),
    # 城{N} + 东路出城门 + 路{W,S} 折弯
    (TileDef(tile_id="MGW-N", edges=_t("crrr"),
             cities=(CitySeg(frozenset({N})),),
             roads=(RoadSeg((E,)), RoadSeg((W, S))),
             farms=(FarmSeg(frozenset()), FarmSeg(frozenset())),
             mage=True), 1),
    # C 形城{N,S,W} + 东路穿缺口
    (TileDef(tile_id="MGW-C", edges=_t("crcc"),
             cities=(CitySeg(frozenset({N, S, W})),),
             roads=(RoadSeg((E,)),),
             farms=(FarmSeg(frozenset()),),
             mage=True), 1),
    # 双城对望{W}+{N,E} + 南路出右城门
    (TileDef(tile_id="MGW-tower", edges=_t("ccrc"),
             cities=(CitySeg(frozenset({W})), CitySeg(frozenset({N, E}))),
             roads=(RoadSeg((S,)),),
             farms=(FarmSeg(frozenset(), adj_cities=frozenset({0, 1})),),
             mage=True), 1),
    # 西城{W} + 三叉路{N,S,E}（交叉口终止道路）
    (TileDef(tile_id="MGW-W", edges=_t("rrrc"),
             cities=(CitySeg(frozenset({W})),),
             roads=(RoadSeg((N,)), RoadSeg((S,)), RoadSeg((E,))),
             farms=(FarmSeg(frozenset()),),
             center=Center.JUNCTION,
             mage=True), 1),
    # 城{N,W} + 路{S,E} 折弯（异面变体）
    (TileDef(tile_id="MGW-NWse2", edges=_t("crrc"),
             cities=(CitySeg(frozenset({N, W})),),
             roads=(RoadSeg((S, E)),),
             farms=(FarmSeg(frozenset()),),
             mage=True), 1),
    # 东城{E} + 三叉路{N,W,S}（交叉口终止道路）
    (TileDef(tile_id="MGW-E", edges=_t("rcrr"),
             cities=(CitySeg(frozenset({E})),),
             roads=(RoadSeg((N,)), RoadSeg((W,)), RoadSeg((S,))),
             farms=(FarmSeg(frozenset()),),
             center=Center.JUNCTION,
             mage=True), 1),
    # 双城隔谷对望 {W} + {N,E}，南田（无路）
    (TileDef(tile_id="MGW-valley", edges=_t("ccfc"),
             cities=(CitySeg(frozenset({W})), CitySeg(frozenset({N, E}))),
             farms=(FarmSeg(frozenset({S}), adj_cities=frozenset({0, 1})),),
             mage=True), 1),
    # 随附麦田圈牌（CC-II）：上下两城带 {N}+{S} 夹黄盾圈，东西田
    (TileDef(tile_id="MGW-CC", edges=_t("cfcf"),
             cities=(CitySeg(frozenset({N})), CitySeg(frozenset({S}))),
             farms=(FarmSeg(frozenset({W}), adj_cities=frozenset({0, 1})),
                    FarmSeg(frozenset({E}), adj_cities=frozenset({0, 1}))),
             crop="city"), 1),
]

# 强盗 8 张（CAR 页 186-192；带钱袋图腾，robber=True；第 9 张为随附麦田圈牌）
_TILE_SHEET_RBR: List[Tuple[TileDef, int]] = [
    # 路{W,S} 折弯 + 田舍
    (TileDef(tile_id="RBR-ws", edges=_t("ffrr"),
             roads=(RoadSeg((W, S)),),
             farms=(FarmSeg(frozenset({N, E})),),
             robber=True), 1),
    # 丁字路 {W,E,S}（路心宅；交叉口终止道路，三分支独立）
    (TileDef(tile_id="RBR-T", edges=_t("frrr"),
             roads=(RoadSeg((W,)), RoadSeg((E,)), RoadSeg((S,))),
             farms=(FarmSeg(frozenset({N})),),
             center=Center.JUNCTION,
             robber=True), 1),
    # 双对角城带 {N,E} + {W,S}
    (TileDef(tile_id="RBR-X", edges=_t("cccc"),
             cities=(CitySeg(frozenset({N, E})), CitySeg(frozenset({W, S}))),
             farms=(FarmSeg(frozenset(), adj_cities=frozenset({0, 1})),),
             robber=True), 1),
    # 南北直路（弯）
    (TileDef(tile_id="RBR-ns", edges=_t("rfrf"),
             roads=(RoadSeg((N, S)),),
             farms=(FarmSeg(frozenset({W})), FarmSeg(frozenset({E}))),
             robber=True), 1),
    # 南北直路（弯，变体；田舍为图饰）
    (TileDef(tile_id="RBR-ns2", edges=_t("rfrf"),
             roads=(RoadSeg((N, S)),),
             farms=(FarmSeg(frozenset({W})), FarmSeg(frozenset({E}))),
             robber=True), 1),
    # 路{W,S} 折弯（变体）
    (TileDef(tile_id="RBR-ws2", edges=_t("ffrr"),
             roads=(RoadSeg((W, S)),),
             farms=(FarmSeg(frozenset({N, E})),),
             robber=True), 1),
    # 城{N} + 南路出城门
    (TileDef(tile_id="RBR-Ns", edges=_t("cfrf"),
             cities=(CitySeg(frozenset({N})),),
             roads=(RoadSeg((S,)),),
             farms=(FarmSeg(frozenset({W}), adj_cities=frozenset({0})),
                    FarmSeg(frozenset({E}), adj_cities=frozenset({0}))),
             robber=True), 1),
    # 城{N} + 三边田
    (TileDef(tile_id="RBR-N", edges=_t("cfff"),
             cities=(CitySeg(frozenset({N})),),
             farms=(FarmSeg(frozenset({W, E, S}), adj_cities=frozenset({0})),),
             robber=True), 1),
    # 随附麦田圈牌（CC-II）：城{N,W} 对角 + 大黄盾圈 + 东南田
    (TileDef(tile_id="RBR-CC", edges=_t("cffc"),
             cities=(CitySeg(frozenset({N, W})),),
             farms=(FarmSeg(frozenset({E, S}), adj_cities=frozenset({0})),
                    FarmSeg(frozenset(), adj_cities=frozenset({0}))),
             crop="city"), 1),
]

# 隧道 4 张（CAR 页 198-200；tunnels = 终点是隧道口的路段下标）
_TILE_SHEET_TUN: List[Tuple[TileDef, int]] = [
    # 城{N} + 东西两路各止于一个隧道口（同牌双口）
    (TileDef(tile_id="TUN-Nwe", edges=_t("crfr"),
             cities=(CitySeg(frozenset({N})),),
             roads=(RoadSeg((W,)), RoadSeg((E,))),
             farms=(FarmSeg(frozenset({S}), adj_cities=frozenset({0})),
                    FarmSeg(frozenset(), adj_cities=frozenset({0}))),
             tunnels=(0, 1)), 1),
    # 城{N} + 三路各止于隧道口
    (TileDef(tile_id="TUN-N3", edges=_t("crrr"),
             cities=(CitySeg(frozenset({N})),),
             roads=(RoadSeg((W,)), RoadSeg((E,)), RoadSeg((S,))),
             farms=(FarmSeg(frozenset()),),
             tunnels=(0, 1, 2)), 1),
    # 三路各止于隧道口 + 北田
    (TileDef(tile_id="TUN-3", edges=_t("frrr"),
             roads=(RoadSeg((W,)), RoadSeg((E,)), RoadSeg((S,))),
             farms=(FarmSeg(frozenset({N})),),
             tunnels=(0, 1, 2)), 1),
    # 四路：北段止于路宅（无口），西/东/南止于隧道口
    (TileDef(tile_id="TUN-4", edges=_t("rrrr"),
             roads=(RoadSeg((N,)), RoadSeg((W,)), RoadSeg((E,)),
                    RoadSeg((S,))),
             farms=(FarmSeg(frozenset()), FarmSeg(frozenset())),
             tunnels=(1, 2, 3)), 1),
]

# 麦田怪圈 I 6 张（CAR 页 130-133；crop = 圈影响类型 farm/road/city）
_TILE_SHEET_CRP: List[Tuple[TileDef, int]] = [
    # 城{N,E} 对角 + 西南田；盾圈=城
    (TileDef(tile_id="CRP-NE", edges=_t("ccff"),
             cities=(CitySeg(frozenset({N, E})),),
             farms=(FarmSeg(frozenset({W, S}), adj_cities=frozenset({0})),),
             crop="city"), 1),
    # 城{N,W} + 东南田；盾圈=城
    (TileDef(tile_id="CRP-NW", edges=_t("cffc"),
             cities=(CitySeg(frozenset({N, W})),),
             farms=(FarmSeg(frozenset({E, S}), adj_cities=frozenset({0})),),
             crop="city"), 1),
    # 城{N} + 路{W,S} 折弯；草叉圈=农场
    (TileDef(tile_id="CRP-Nws", edges=_t("cfrr"),
             cities=(CitySeg(frozenset({N})),),
             roads=(RoadSeg((W, S)),),
             farms=(FarmSeg(frozenset({E})),
                    FarmSeg(frozenset(), adj_cities=frozenset({0}))),
             crop="farm"), 1),
    # 城{N} + 东西直路；草叉圈=农场
    (TileDef(tile_id="CRP-Nwe", edges=_t("crfr"),
             cities=(CitySeg(frozenset({N})),),
             roads=(RoadSeg((W, E)),),
             farms=(FarmSeg(frozenset(), adj_cities=frozenset({0})),
                    FarmSeg(frozenset({S}))),
             crop="farm"), 1),
    # 东西两路各止于黄圈；棍圈=路
    (TileDef(tile_id="CRP-we", edges=_t("frfr"),
             roads=(RoadSeg((W,)), RoadSeg((E,))),
             farms=(FarmSeg(frozenset({N})), FarmSeg(frozenset({S}))),
             crop="road"), 1),
    # 三叉路口 {W,S,E}；棍圈=路（脚注 358：三分支独立，交叉口终止道路）
    (TileDef(tile_id="CRP-T", edges=_t("frrr"),
             roads=(RoadSeg((W,)), RoadSeg((S,)), RoadSeg((E,))),
             farms=(FarmSeg(frozenset({N})),),
             center=Center.JUNCTION,
             crop="road"), 1),
]

# —— 塔 18 张（CAR 页 51-57；带塔基石 square，tower=True）——
# CAR v7.4 明确：塔基石牌按常规方式放置，无额外邻接限制；横竖射线只用于
# 塔块抓人（射程=塔块数）。塔门/塔基可作道路终点（同城门口径）。
_TILE_SHEET_TOW: List[Tuple[TileDef, int]] = [
    # 环城 + 旗帜（塔基在城内；开局即完整）
    (TileDef(tile_id="TOW-ring", edges=_t("cccc"),
             cities=(CitySeg(frozenset({N, E, S, W}), pennant=True),),
             tower=True), 1),
    # 城{N,E} + 西路止于塔门
    (TileDef(tile_id="TOW-NEw", edges=_t("ccfr"),
             cities=(CitySeg(frozenset({N, E})),),
             roads=(RoadSeg((W,)),),
             farms=(FarmSeg(frozenset({S}), adj_cities=frozenset({0})),
                    FarmSeg(frozenset(), adj_cities=frozenset({0}))),
             tower=True), 1),
    # 城{N} + 西路止于塔门
    (TileDef(tile_id="TOW-Nw", edges=_t("cffr"),
             cities=(CitySeg(frozenset({N})),),
             roads=(RoadSeg((W,)),),
             farms=(FarmSeg(frozenset({E, S}), adj_cities=frozenset({0})),
                    FarmSeg(frozenset(), adj_cities=frozenset({0}))),
             tower=True), 1),
    # 全田 + 塔基
    (TileDef(tile_id="TOW-field", edges=_t("ffff"),
             farms=(FarmSeg(frozenset({N, E, S, W})),),
             tower=True), 1),
    # 修道院 + 塔基
    (TileDef(tile_id="TOW-mon", edges=_t("ffff"),
             farms=(FarmSeg(frozenset({N, E, S, W})),),
             center=Center.MONASTERY, tower=True), 1),
    # 路{W,S} 折弯 + 塔基
    (TileDef(tile_id="TOW-ws", edges=_t("ffrr"),
             roads=(RoadSeg((W, S)),),
             farms=(FarmSeg(frozenset({N, E})),),
             tower=True), 1),
    # 丁字路 {N,W,E} + 塔基（交叉口终止道路）
    (TileDef(tile_id="TOW-T1", edges=_t("rrfr"),
             roads=(RoadSeg((N,)), RoadSeg((W,)), RoadSeg((E,))),
             farms=(FarmSeg(frozenset({S})),),
             center=Center.JUNCTION, tower=True), 1),
    # 双弧路 {N,W} 与 {S,E} + 塔基
    (TileDef(tile_id="TOW-arcs", edges=_t("rrrr"),
             roads=(RoadSeg((N, W)), RoadSeg((S, E))),
             farms=(FarmSeg(frozenset()), FarmSeg(frozenset())),
             tower=True), 1),
    # 丁字路 {N,W,E} + 塔基（变体）
    (TileDef(tile_id="TOW-T2", edges=_t("rrfr"),
             roads=(RoadSeg((N,)), RoadSeg((W,)), RoadSeg((E,))),
             farms=(FarmSeg(frozenset({S})),),
             center=Center.JUNCTION, tower=True), 1),
    # 城{N,E} 对角 + 塔基
    (TileDef(tile_id="TOW-NE1", edges=_t("ccff"),
             cities=(CitySeg(frozenset({N, E})),),
             farms=(FarmSeg(frozenset({W, S}), adj_cities=frozenset({0})),),
             tower=True), 1),
    # 城{N,E} + 南路止于塔门
    (TileDef(tile_id="TOW-NEs", edges=_t("ccrf"),
             cities=(CitySeg(frozenset({N, E})),),
             roads=(RoadSeg((S,)),),
             farms=(FarmSeg(frozenset({W}), adj_cities=frozenset({0})),
                    FarmSeg(frozenset(), adj_cities=frozenset({0}))),
             tower=True), 1),
    # 城{N} + 南路出城门（塔基）
    (TileDef(tile_id="TOW-Ns1", edges=_t("cfff"),
             cities=(CitySeg(frozenset({N})),),
             farms=(FarmSeg(frozenset({W, E, S}), adj_cities=frozenset({0})),),
             tower=True), 2),
    # 城{N} + 南路出城门
    (TileDef(tile_id="TOW-Ns2", edges=_t("cfrf"),
             cities=(CitySeg(frozenset({N})),),
             roads=(RoadSeg((S,)),),
             farms=(FarmSeg(frozenset({W}), adj_cities=frozenset({0})),
                    FarmSeg(frozenset({E}), adj_cities=frozenset({0}))),
             tower=True), 1),
    # 城{N} + 路{W,S} 折弯
    (TileDef(tile_id="TOW-Nws", edges=_t("cfrr"),
             cities=(CitySeg(frozenset({N})),),
             roads=(RoadSeg((W, S)),),
             farms=(FarmSeg(frozenset({E}), adj_cities=frozenset({0})),
                    FarmSeg(frozenset(), adj_cities=frozenset({0}))),
             tower=True), 1),
    # 城{N} + 东西高架桥路（桥面贯通）
    (TileDef(tile_id="TOW-bridge", edges=_t("crfr"),
             cities=(CitySeg(frozenset({N})),),
             roads=(RoadSeg((W, E)),),
             farms=(FarmSeg(frozenset()), FarmSeg(frozenset({S}))),
             tower=True), 1),
    # 城{N,E} + 路{W,S} 折弯
    (TileDef(tile_id="TOW-NEws", edges=_t("ccrr"),
             cities=(CitySeg(frozenset({N, E})),),
             roads=(RoadSeg((W, S)),),
             farms=(FarmSeg(frozenset(), adj_cities=frozenset({0})),),
             tower=True), 1),
    # 十字路 {N,E,S,W} + 塔基居中（交叉口终止道路）
    (TileDef(tile_id="TOW-cross", edges=_t("rrrr"),
             roads=(RoadSeg((N,)), RoadSeg((E,)), RoadSeg((S,)),
                    RoadSeg((W,))),
             farms=(FarmSeg(frozenset()),),
             center=Center.JUNCTION, tower=True), 1),
]

# —— 山丘与羊 18 张（CAR 页 102-109）——
# hill=山丘（叠放垫牌+平局破缺）；sheep=羊圈（可部署牧羊人）；
# vineyard=葡萄园（修院完成 +3/座）。
# 特殊牌：HS-citysplit 东边为"城侧"（两个独立城段）；HS-fieldsplit 东边为
# "田侧"（两个独立田段）——一条边被两段覆盖，add_tile 按全部覆盖段合并；
# CAR 页 107 两牌相邻"不相连"特例依赖半边方位，整边模型近似为相连（已注记）。
_TILE_SHEET_HS: List[Tuple[TileDef, int]] = [
    # 羊圈 + 双城（两城间草场不相连）
    (TileDef(tile_id="HS-twoCity", edges=_t("ccfc"),
             cities=(CitySeg(frozenset({N, W})), CitySeg(frozenset({E}))),
             farms=(FarmSeg(frozenset({S}), adj_cities=frozenset({0, 1})),
                    FarmSeg(frozenset(), adj_cities=frozenset({0, 1}))),
             sheep=True), 2),
    # 山丘：上北下南两城带
    (TileDef(tile_id="HS-hillNS", edges=_t("cfcf"),
             cities=(CitySeg(frozenset({N})), CitySeg(frozenset({S}))),
             farms=(FarmSeg(frozenset({W}), adj_cities=frozenset({0, 1})),
                    FarmSeg(frozenset({E}), adj_cities=frozenset({0, 1}))),
             hill=True), 1),
    # 山丘：城{N,E} 对角
    (TileDef(tile_id="HS-hillNE", edges=_t("ccff"),
             cities=(CitySeg(frozenset({N, E})),),
             farms=(FarmSeg(frozenset({W, S}), adj_cities=frozenset({0})),),
             hill=True), 1),
    # 山丘：路{W,S} 折弯
    (TileDef(tile_id="HS-hillws", edges=_t("ffrr"),
             roads=(RoadSeg((W, S)),),
             farms=(FarmSeg(frozenset({N, E})),),
             hill=True), 1),
    # 山丘：城{N} + 南路出城门
    (TileDef(tile_id="HS-hillNs", edges=_t("cfrf"),
             cities=(CitySeg(frozenset({N})),),
             roads=(RoadSeg((S,)),),
             farms=(FarmSeg(frozenset({W}), adj_cities=frozenset({0})),
                    FarmSeg(frozenset({E}), adj_cities=frozenset({0}))),
             hill=True), 1),
    # 山丘：城{N} + 路{W,S} 折弯
    (TileDef(tile_id="HS-hillNws", edges=_t("cfrr"),
             cities=(CitySeg(frozenset({N})),),
             roads=(RoadSeg((W, S)),),
             farms=(FarmSeg(frozenset({E}), adj_cities=frozenset({0})),
                    FarmSeg(frozenset(), adj_cities=frozenset({0}))),
             hill=True), 1),
    # 山丘：路{N,W} 折弯 + 南路短段（止于山丘）
    (TileDef(tile_id="HS-hillnw", edges=_t("rfrr"),
             roads=(RoadSeg((N, W)), RoadSeg((S,))),
             farms=(FarmSeg(frozenset({E})), FarmSeg(frozenset())),
             hill=True), 1),
    # 山丘：城{N} + 路{E,S} 折弯
    (TileDef(tile_id="HS-hillNes", edges=_t("crrf"),
             cities=(CitySeg(frozenset({N})),),
             roads=(RoadSeg((E, S)),),
             farms=(FarmSeg(frozenset({W}), adj_cities=frozenset({0})),),
             hill=True), 1),

    # 山丘：城{W} + 三边田
    (TileDef(tile_id="HS-hillW", edges=_t("fffc"),
             cities=(CitySeg(frozenset({W})),),
             farms=(FarmSeg(frozenset({N, E, S}), adj_cities=frozenset({0})),),
             hill=True), 2),
    # 葡萄园：南北贯通路
    (TileDef(tile_id="HS-vydNS", edges=_t("rfrf"),
             roads=(RoadSeg((N, S)),),
             farms=(FarmSeg(frozenset({W})), FarmSeg(frozenset({E}))),
             vineyard=True), 1),
    # 葡萄园：路{E,S} 折弯
    (TileDef(tile_id="HS-vydES", edges=_t("frrf"),
             roads=(RoadSeg((E, S)),),
             farms=(FarmSeg(frozenset({N, W})),),
             vineyard=True), 1),
    # 羊圈：城{N,W} + 南路（小屋截断为独立短段）
    (TileDef(tile_id="HS-cottage", edges=_t("cfrc"),
             cities=(CitySeg(frozenset({N, W})),),
             roads=(RoadSeg((S,)),),
             farms=(FarmSeg(frozenset({E}), adj_cities=frozenset({0})),
                    FarmSeg(frozenset(), adj_cities=frozenset({0}))),
             sheep=True), 1),
    # 羊圈：城{N} + 南路出城门
    (TileDef(tile_id="HS-sheepNs", edges=_t("cfrf"),
             cities=(CitySeg(frozenset({N})),),
             roads=(RoadSeg((S,)),),
             farms=(FarmSeg(frozenset({W}), adj_cities=frozenset({0})),
                    FarmSeg(frozenset({E}), adj_cities=frozenset({0}))),
             sheep=True), 1),
    # 羊圈：城{N,W} 对角
    (TileDef(tile_id="HS-sheepNW", edges=_t("cffc"),
             cities=(CitySeg(frozenset({N, W})),),
             farms=(FarmSeg(frozenset({E, S}), adj_cities=frozenset({0})),),
             sheep=True), 1),
    # 特殊：东边"城侧"两个独立城段（邻牌城段与两段同时合并）
    (TileDef(tile_id="HS-citysplit", edges=_t("ccfc"),
             cities=(CitySeg(frozenset({N, W})), CitySeg(frozenset({E})),
                     CitySeg(frozenset({E}))),
             farms=(FarmSeg(frozenset({S}), adj_cities=frozenset({0, 1, 2})),
                    FarmSeg(frozenset(), adj_cities=frozenset({0, 1, 2}))),
             sheep=True), 1),
    # 特殊：东边"田侧"两个独立田段（邻牌田段与两段同时合并）
    (TileDef(tile_id="HS-fieldsplit", edges=_t("cffc"),
             cities=(CitySeg(frozenset({N, W})),),
             farms=(FarmSeg(frozenset({S}), adj_cities=frozenset({0})),
                    FarmSeg(frozenset({E}), adj_cities=frozenset({0})),
                    FarmSeg(frozenset({E}), adj_cities=frozenset({0}))),
             sheep=True), 1),
]

# —— 命运之轮（WoF，CAR 页 109-116）——
# 起始轮盘牌替代修道院起始牌（边界近似：北/东城段 + 南/西路，城门连通；
# 轮盘王冠位为抽象等候区，不计入棋盘特征）。
# 命运牌采用官方"仅混入 19 张图腾牌"变体：基础拓扑 + 图腾数字 1-3
# （数字分布为近似重建，CAR 页 114 下划线分布不可完全复原）。
_WOF_START = TileDef(
    tile_id="WOF-start",
    edges=_t("ccrr"),
    cities=(CitySeg(frozenset({N})), CitySeg(frozenset({E}))),
    roads=(RoadSeg((S,)), RoadSeg((W,))),
    farms=(FarmSeg(frozenset()), FarmSeg(frozenset()),
           FarmSeg(frozenset()), FarmSeg(frozenset())),
    is_start=True,
)

_TILE_SHEET_WOF: List[Tuple[TileDef, int]] = [
    (TileDef(tile_id="WOF-rs1", edges=_t("frfr"),
             roads=(RoadSeg((W, E)),),
             farms=(FarmSeg(frozenset({N})), FarmSeg(frozenset({S}))),
             fate=1), 1),
    (TileDef(tile_id="WOF-rc1", edges=_t("ffrr"),
             roads=(RoadSeg((W, S)),),
             farms=(FarmSeg(frozenset({N, E})),),
             fate=1), 1),
    (TileDef(tile_id="WOF-c1a", edges=_t("cfff"),
             cities=(CitySeg(frozenset({N})),),
             farms=(FarmSeg(frozenset({W, E, S}), adj_cities=frozenset({0})),),
             fate=1), 1),
    (TileDef(tile_id="WOF-mon", edges=_t("ffff"),
             farms=(FarmSeg(frozenset({N, E, S, W})),),
             center=Center.MONASTERY, fate=1), 1),
    (TileDef(tile_id="WOF-rc2", edges=_t("ffrr"),
             roads=(RoadSeg((W, S)),),
             farms=(FarmSeg(frozenset({N, E})),),
             fate=1), 1),
    (TileDef(tile_id="WOF-rs2", edges=_t("frfr"),
             roads=(RoadSeg((W, E)),),
             farms=(FarmSeg(frozenset({N})), FarmSeg(frozenset({S}))),
             fate=1), 1),
    (TileDef(tile_id="WOF-cc", edges=_t("ccff"),
             cities=(CitySeg(frozenset({N, E})),),
             farms=(FarmSeg(frozenset({W, S}), adj_cities=frozenset({0})),),
             fate=1), 1),
    (TileDef(tile_id="WOF-rt1", edges=_t("frrr"),
             roads=(RoadSeg((E,)), RoadSeg((S,)), RoadSeg((W,))),
             farms=(FarmSeg(frozenset({N})),),
             center=Center.JUNCTION, fate=2), 1),
    (TileDef(tile_id="WOF-mon2", edges=_t("ffff"),
             farms=(FarmSeg(frozenset({N, E, S, W})),),
             center=Center.MONASTERY, fate=2), 1),
    (TileDef(tile_id="WOF-cc2", edges=_t("ccff"),
             cities=(CitySeg(frozenset({N, E})),),
             farms=(FarmSeg(frozenset({W, S}), adj_cities=frozenset({0})),),
             fate=2), 1),
    (TileDef(tile_id="WOF-c3", edges=_t("cccf"),
             cities=(CitySeg(frozenset({N, E, S})),),
             farms=(FarmSeg(frozenset({W}), adj_cities=frozenset({0})),),
             fate=2), 1),
    (TileDef(tile_id="WOF-rc3", edges=_t("ffrr"),
             roads=(RoadSeg((W, S)),),
             farms=(FarmSeg(frozenset({N, E})),),
             fate=2), 1),
    (TileDef(tile_id="WOF-rs3", edges=_t("frfr"),
             roads=(RoadSeg((W, E)),),
             farms=(FarmSeg(frozenset({N})), FarmSeg(frozenset({S}))),
             fate=2), 1),
    (TileDef(tile_id="WOF-cthru", edges=_t("cfcf"),
             cities=(CitySeg(frozenset({N, S})),),
             farms=(FarmSeg(frozenset({W})), FarmSeg(frozenset({E}))),
             fate=3), 1),
    (TileDef(tile_id="WOF-c1b", edges=_t("cfff"),
             cities=(CitySeg(frozenset({N})),),
             farms=(FarmSeg(frozenset({W, E, S}), adj_cities=frozenset({0})),),
             fate=3), 1),
    (TileDef(tile_id="WOF-rt2", edges=_t("frrr"),
             roads=(RoadSeg((E,)), RoadSeg((S,)), RoadSeg((W,))),
             farms=(FarmSeg(frozenset({N})),),
             center=Center.JUNCTION, fate=3), 1),
    (TileDef(tile_id="WOF-rc4", edges=_t("ffrr"),
             roads=(RoadSeg((W, S)),),
             farms=(FarmSeg(frozenset({N, E})),),
             fate=3), 1),
    (TileDef(tile_id="WOF-rs4", edges=_t("frfr"),
             roads=(RoadSeg((W, E)),),
             farms=(FarmSeg(frozenset({N})), FarmSeg(frozenset({S}))),
             fate=3), 1),
    (TileDef(tile_id="WOF-cc3", edges=_t("ccff"),
             cities=(CitySeg(frozenset({N, E})),),
             farms=(FarmSeg(frozenset({W, S}), adj_cities=frozenset({0})),),
             fate=3), 1),
]
for _w in _TILE_SHEET_WOF:
    pass

# 牌组构建
# (牌面定义, 数量)。数量严格按 CAR v7.4 Consolidated Tile Reference。
_TILE_SHEET: List[Tuple[TileDef, int]] = [
    (_M_START, 1),
    (_MR_PLAIN, 1),
    (_M_PLAIN, 4),
    (_C_ALL, 1),
    (_C_3S, 3),
    (_C_3S_P, 1),
    (_C_GATE, 2),
    (_C_GATE_P, 1),
    (_C_CORNER, 5),
    (_C_CORNER_P, 2),
    (_C_THROUGH, 2),
    (_C_THROUGH_P, 1),
    (_C_SEP, 1),
    (_C_SEP_P, 2),
    (_C_1S, 4),
    (_C_1S_P, 1),
    (_C_STRAIGHT_ROAD, 3),
    (_C_STRAIGHT_ROAD_P, 1),
    (_CURVE_A, 2),
    (_CURVE_A_P, 1),
    (_CURVE_B, 2),
    (_CURVE_B_P, 1),
    (_C_CORNER_ROAD, 3),
    (_C_CORNER_ROAD_P, 2),
    (_C_3ROADS, 2),
    (_C_3ROADS_P, 1),
    (_R_CROSS, 1),
    (_R_STRAIGHT, 8),
    (_R_CURVE, 9),
    (_R_T, 4),
]

# CAR v7.4 基础版拓扑类分布（上右下左）
CAR_CLASS_COUNTS: Dict[str, int] = {
    "cccc": 1, "cccf": 4, "cccr": 3, "ccff": 7, "ccrr": 5,
    "cfcf": 6, "cfff": 5, "cfrr": 3, "crfr": 4, "crrf": 3, "crrr": 3,
    "ffff": 4, "fffr": 2, "ffrr": 9, "frfr": 8, "frrr": 4, "rrrr": 1,
}

# 扩展牌张数（CAR v7.4：页 30/34/40/57/70-71/79-83/84-86/92-101/120-200）
EXP_TILE_COUNTS: Dict[str, int] = {
    "inns": 18, "traders": 24, "pd": 30, "abbey": 12,
    "king": 5, "river": 12, "shrine": 5, "bcb": 12,
    "besiegers": 6, "festival": 10, "goldmines": 9, "magewitch": 9,
    "robbers": 9, "tunnel": 4, "crop": 6, "tower": 18, "hillsheep": 18,
    "wheel": 19,
}

_EXP_SHEETS: Dict[str, List[Tuple[TileDef, int]]] = {
    "inns": _TILE_SHEET_IC, "traders": _TILE_SHEET_TB,
    "pd": _TILE_SHEET_PD, "abbey": _TILE_SHEET_AM,
    "king": _TILE_SHEET_KRB, "river": _TILE_SHEET_RII,
    "shrine": _TILE_SHEET_HES, "bcb": _TILE_SHEET_BCB,
    "besiegers": _TILE_SHEET_BES, "festival": _TILE_SHEET_FES,
    "goldmines": _TILE_SHEET_GLD, "magewitch": _TILE_SHEET_MGW,
    "robbers": _TILE_SHEET_RBR, "tunnel": _TILE_SHEET_TUN,
    "crop": _TILE_SHEET_CRP, "tower": _TILE_SHEET_TOW,
    "hillsheep": _TILE_SHEET_HS, "wheel": _TILE_SHEET_WOF,
}


def build_deck(expansions=None) -> List[TileDef]:
    """构建洗牌前的摸牌堆（不含起始牌/泉源）。河流牌由引擎按固定次序组织。"""
    deck: List[TileDef] = []
    for tile, count in _TILE_SHEET:
        if tile.is_start:
            continue
        deck.extend([tile] * count)
    if expansions and "inns" in expansions:
        for tile, count in _TILE_SHEET_IC:
            deck.extend([tile] * count)
    if expansions and "traders" in expansions:
        for tile, count in _TILE_SHEET_TB:
            deck.extend([tile] * count)
    if expansions and "pd" in expansions:
        for tile, count in _TILE_SHEET_PD:
            deck.extend([tile] * count)
    if expansions and "abbey" in expansions:
        for tile, count in _TILE_SHEET_AM:
            deck.extend([tile] * count)
    if expansions and "king" in expansions:
        for tile, count in _TILE_SHEET_KRB:
            deck.extend([tile] * count)
    if expansions and "river" in expansions:
        for tile, count in _TILE_SHEET_RII:
            if tile.is_start:
                continue
            deck.extend([tile] * count)
    if expansions and "shrine" in expansions:
        for tile, count in _TILE_SHEET_HES:
            deck.extend([tile] * count)
    if expansions and "bcb" in expansions:
        for tile, count in _TILE_SHEET_BCB:
            deck.extend([tile] * count)
    for key in ("besiegers", "festival", "goldmines", "magewitch",
                "robbers", "tunnel", "crop", "tower", "hillsheep", "wheel"):
        if expansions and key in expansions:
            for tile, count in _EXP_SHEETS[key]:
                deck.extend([tile] * count)
    return deck


def start_tile(expansions=None) -> TileDef:
    """起始牌：命运之轮 > 河流 II > 修道院起始牌。"""
    if expansions and "wheel" in expansions:
        return _WOF_START
    if expansions and "river" in expansions:
        return by_id("RI-Spring")
    return _M_START


def river_deck(expansions=None, rng=None) -> List[TileDef]:
    """河流摸牌序列：岔流固定第二张，其余洗匀，火山湖固定最后（CAR 页 79）。

    泉源作为起始牌已放置，不在序列内。
    """
    import random
    others = [t for t, _c in _TILE_SHEET_RII
              if not t.is_start and not t.volcano and t.tile_id != "RI-Junction"]
    if rng is not None:
        rng.shuffle(others)
    else:
        random.shuffle(others)
    junction = by_id("RI-Junction")
    volcano = by_id("RI-VolcanoLake")
    return [junction] + others + [volcano]


def _canon_topo(topo: str) -> str:
    """旋转规范化（取 4 个旋转中最小字典序），与 CAR 规范写法对齐。"""
    return min(topo[i:] + topo[:i] for i in range(4))


def all_definitions(expansions=None) -> List[TileDef]:
    """全部牌面定义（含起始牌；expansions 含对应扩展时含扩展牌）。"""
    defs = [t for t, _ in _TILE_SHEET]
    if expansions and "inns" in expansions:
        defs += [t for t, _ in _TILE_SHEET_IC]
    if expansions and "traders" in expansions:
        defs += [t for t, _ in _TILE_SHEET_TB]
    if expansions and "pd" in expansions:
        defs += [t for t, _ in _TILE_SHEET_PD]
    if expansions and "abbey" in expansions:
        defs += [t for t, _ in _TILE_SHEET_AM]
    if expansions and "king" in expansions:
        defs += [t for t, _ in _TILE_SHEET_KRB]
    if expansions and "river" in expansions:
        defs += [t for t, _ in _TILE_SHEET_RII]
    if expansions and "shrine" in expansions:
        defs += [t for t, _ in _TILE_SHEET_HES]
    if expansions and "bcb" in expansions:
        defs += [t for t, _ in _TILE_SHEET_BCB]
    for key in ("besiegers", "festival", "goldmines", "magewitch",
                "robbers", "tunnel", "crop", "tower", "hillsheep", "wheel"):
        if expansions and key in expansions:
            defs += [t for t, _ in _EXP_SHEETS[key]]
    return defs


_DEFS_BY_ID: Dict[str, TileDef] = {
    t.tile_id: t for sheet in (_TILE_SHEET, _TILE_SHEET_IC, _TILE_SHEET_TB,
                               _TILE_SHEET_PD, _TILE_SHEET_AM,
                               _TILE_SHEET_KRB, _TILE_SHEET_RII,
                               _TILE_SHEET_HES, _TILE_SHEET_BCB)
    for t, _n in sheet}
for _key in ("besiegers", "festival", "goldmines", "magewitch",
             "robbers", "tunnel", "crop", "tower", "hillsheep", "wheel"):
    _DEFS_BY_ID.update(
        {t.tile_id: t for t, _n in _EXP_SHEETS[_key]})
_DEFS_BY_ID.update({t.tile_id: t for _c, _r, t in CC_BLOCK})
_DEFS_BY_ID[_WOF_START.tile_id] = _WOF_START


def by_id(tile_id: str) -> TileDef:
    """按唯一牌面 ID 取定义（联机快照反序列化用）。"""
    return _DEFS_BY_ID[tile_id]


def validate() -> Dict[str, object]:
    """数据自检：基础版与四个扩展的总量、拓扑分布、段-边一致性、旗帜合法性。

    返回统计字典；任何不一致直接抛 AssertionError。
    """
    sheet = all_definitions()
    total = sum(count for _, count in _TILE_SHEET)
    assert total == 72, "牌组（含起始牌）应为 72 张，实际 %d" % total

    deck = build_deck()
    assert len(deck) == 71, "摸牌堆应为 71 张，实际 %d" % len(deck)

    class_counts: Dict[str, int] = {}
    for tile in [_M_START] + deck:
        topo = _canon_topo(tile.topology())
        class_counts[topo] = class_counts.get(topo, 0) + 1
    assert class_counts == CAR_CLASS_COUNTS, "拓扑分布与 CAR 不符: %s" % class_counts

    assert sum(1 for t in deck if t.is_start) == 0, "摸牌堆不应含起始牌"

    for tile in sheet:
        _check_segments(tile)

    # 扩展牌：张数对齐 CAR v7.4 + 段-边一致性全检
    # （河流 II 的泉源为起始牌：牌堆 11 张，含泉源共 12 张）
    exp_counts: Dict[str, int] = {}
    for key, exp_sheet in _EXP_SHEETS.items():
        n = sum(count for _, count in exp_sheet)
        assert n == EXP_TILE_COUNTS[key], \
            "扩展 %s 应为 %d 张，实际 %d" % (key, EXP_TILE_COUNTS[key], n)
        for tile, _count in exp_sheet:
            _check_segments(tile)
        exp_counts[key] = n

    deck_sizes = {k: len(build_deck([k])) for k in _EXP_SHEETS}
    for k, n in deck_sizes.items():
        expect = 71 + EXP_TILE_COUNTS[k] - (1 if k == "river" else 0)
        assert n == expect, "扩展 %s 牌堆应为 %d 张，实际 %d" % (k, expect, n)

    full_deck = build_deck(list(_EXP_SHEETS))
    assert len(full_deck) == 71 + sum(EXP_TILE_COUNTS.values()) - 1, \
        "全扩展牌堆应为 %d 张，实际 %d" % (
            71 + sum(EXP_TILE_COUNTS.values()) - 1, len(full_deck))

    # 伯爵城起始块：12 张、四角/边/中的内边城互连、外圈草地成环
    assert len(CC_BLOCK) == 12, "伯爵城应为 12 张"
    for _c, _r, cc in CC_BLOCK:
        _check_segments(cc)

    stats = {
        "total": total,
        "classes": class_counts,
        "exp_counts": exp_counts,
        "pennant_tiles": sum(
            count * sum(1 for cs in tile.cities if cs.pennant)
            for tile, count in _TILE_SHEET
        ),
        "variants": len(_TILE_SHEET),
    }
    return stats


def _check_segments(tile: TileDef) -> None:
    """校验单张牌：每条边恰好被一个段覆盖且地形匹配（桥牌/伯爵城牌除外）。"""
    if tile.tile_id == "TB-Bridge":
        # 桥牌：两条贯通直路（E-W / N-S）+ 四段独立象限田。
        # 每条边同时是路和田（路侧田被桥分隔），通用单覆盖检查不适用。
        assert len(tile.roads) == 2
        road_edge_sets = {frozenset(r.edges) for r in tile.roads}
        assert road_edge_sets == {frozenset({E, W}), frozenset({N, S})}
        assert len(tile.farms) == 4
        assert all(len(fs.edges) == 1 for fs in tile.farms)
        assert set.union(*[set(fs.edges) for fs in tile.farms]) == {N, E, S, W}
        for ci, cs in enumerate(tile.cities):
            for e in cs.edges:
                assert tile.edges[e] is Terrain.CITY
        return
    if tile.count_city:
        # 伯爵城牌：内边为城（各牌大城贯通），内边允许城+田双覆盖
        # （外圈草地环带跨牌连成一片）；外边为田/路/水。
        for i, terr in enumerate(tile.edges):
            in_city = any(i in cs.edges for cs in tile.cities)
            in_farm = any(i in fs.edges for fs in tile.farms)
            in_road = any(i in rs.edges for rs in tile.roads)
            if terr is Terrain.CITY:
                assert in_city and not in_road, \
                    "%s 内边 %d 应为城（可含田双覆盖）" % (tile.tile_id, i)
            elif terr is Terrain.WATER:
                assert not (in_city or in_farm or in_road), \
                    "%s 水边 %d 不应被覆盖" % (tile.tile_id, i)
            else:
                assert (in_farm or in_road) and not in_city, \
                    "%s 外边 %d 应为田/路" % (tile.tile_id, i)
        assert len(tile.cities) == 1
        return
    split_ok = tile.tile_id in ("HS-citysplit", "HS-fieldsplit")
    for i, terr in enumerate(tile.edges):
        covered = sum(1 for cs in tile.cities if i in cs.edges)
        covered += sum(1 for rs in tile.roads if i in rs.edges)
        covered += sum(1 for fs in tile.farms if i in fs.edges)
        if terr is Terrain.WATER:
            assert covered == 0, "%s 水边 %d 不应被段覆盖" % (tile.tile_id, i)
            continue
        assert covered in ((1, 2) if split_ok else (1,)),             "%s 边 %d 被 %d 个段覆盖" % (tile.tile_id, i, covered)

        if terr is Terrain.CITY:
            assert any(i in cs.edges for cs in tile.cities), "%s 边 %d 应为城" % (tile.tile_id, i)
        elif terr is Terrain.ROAD:
            assert any(i in rs.edges for rs in tile.roads), "%s 边 %d 应为路" % (tile.tile_id, i)
        else:
            assert any(i in fs.edges for fs in tile.farms), "%s 边 %d 应为田" % (tile.tile_id, i)

    for ci, cs in enumerate(tile.cities):
        for e in cs.edges:
            assert tile.edges[e] is Terrain.CITY
    for rs in tile.roads:
        for e in rs.edges:
            assert tile.edges[e] is Terrain.ROAD
        assert len(rs.edges) in (1, 2)
    for fs in tile.farms:
        for e in fs.edges:
            assert tile.edges[e] is Terrain.FIELD
        for ci in fs.adj_cities:
            assert 0 <= ci < len(tile.cities)
    if tile.center is Center.JUNCTION:
        # 交叉口牌的每条道路必须是单边支路（被交叉口终止）
        assert all(len(rs.edges) == 1 for rs in tile.roads)
