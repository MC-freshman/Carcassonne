# -*- coding: utf-8 -*-
"""本地对局录制与存档：录制代理 + 重放 + 特殊阶段驱动。

存档采用"输入重放日志"式：记录种子、扩展、玩家与每一步已生效的引擎
公开变更调用（人类与 AI 的动作都记为 op），重放时不依赖 AI 决策的
可复现性，只依赖引擎在同一随机种子下抽牌序列的确定性——引擎对 RNG
的消费路径本来就是动作的纯函数（sheep_bag 洗牌等已在 __init__ 处理）。

这比全量序列化更不易漏字段：engine 有 30+ 个阶段状态字段
（engine.py CarcassonneEngine.__init__），逐字段序列化一旦新增扩展漏掉
一个就会产出损坏存档；重放日志天然覆盖未来扩展。
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional

SAVE_SCHEMA = "carcassonne-save/v1"
SAVE_SUFFIX = ".cksave"


def saves_dir() -> str:
    """存档目录：~/.carcassonne/saves（跨安装目录 portable）。"""
    path = os.path.join(os.path.expanduser("~"), ".carcassonne", "saves")
    os.makedirs(path, exist_ok=True)
    return path


# 会改变权威状态的公开入口（UI/AI 驱动的全部变更路径）。
# 引擎内部的私有调用（如 deploy() 路由到 deploy_fairy）发生在裸引擎上，
# 不会经代理，因此不会重复记录。
OPS = frozenset({
    "place", "deploy", "deploy_option", "skip_deploy", "discard_and_redraw",
    "dragon_move", "redeploy_move", "deploy_count", "skip_count_deploy",
    "convert_castle", "bazaar_select", "bazaar_bid", "bazaar_pass",
    "bazaar_resolve", "build_bridge", "place_gold",
    "mw_move", "mw_remove", "tunnel_claim", "tunnel_skip",
    "crop_choose", "crop_act", "robber_place", "escape_move",
    "shepherd_act", "plague_act", "ransom",
    "tower_place", "tower_deploy_top", "festival_return",
    "deploy_fairy", "deploy_princess",
})


def _to_jsonable(v: Any) -> Any:
    if isinstance(v, tuple):
        return [_to_jsonable(x) for x in v]
    if isinstance(v, list):
        return [_to_jsonable(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _to_jsonable(x) for k, x in v.items()}
    return v


def _to_tuples(v: Any) -> Any:
    """重放时把 JSON 的 list 还原为 tuple（引擎节点/坐标均为 tuple）。"""
    if isinstance(v, list):
        return tuple(_to_tuples(x) for x in v)
    if isinstance(v, dict):
        return {k: _to_tuples(x) for k, x in v.items()}
    return v


class RecordingProxy:
    """引擎录制代理：透明转发全部访问，OPS 调用成功后追加进 history。

    用法：engine = RecordingProxy(CarcassonneEngine(...))；UI/AI 照常使用。
    续局：apply_history(裸引擎, 存档.ops) 后再包一层代理继续记录。
    """

    def __init__(self, engine, history: Optional[List[dict]] = None):
        object.__setattr__(self, "_engine", engine)
        object.__setattr__(self, "history", list(history or []))

    def __getattr__(self, name: str):
        attr = getattr(self._engine, name)
        if name in OPS and callable(attr):
            def _recorded(*args, **kwargs):
                result = attr(*args, **kwargs)
                self.history.append({"op": name,
                                     "a": _to_jsonable(args),
                                     "k": _to_jsonable(kwargs)})
                return result
            return _recorded
        return attr

    @property
    def raw_engine(self):
        return self._engine


def apply_history(engine, ops: List[dict]) -> None:
    """在裸引擎上按序重放已录制的操作（用于续局与存档校验）。"""
    for entry in ops:
        args = tuple(_to_tuples(a) for a in entry.get("a") or [])
        kwargs = {k: _to_tuples(v) for k, v in (entry.get("k") or {}).items()}
        getattr(engine, entry["op"])(*args, **kwargs)


def build_save(engine, seed: int, ops: List[dict]) -> Dict[str, Any]:
    """把一局可续的对局打包成 JSON 可序列化的存档 dict。"""
    eng = engine.raw_engine if isinstance(engine, RecordingProxy) else engine
    return {
        "schema": SAVE_SCHEMA,
        "app_version": _app_version(),
        "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "seed": int(seed),
        "expansions": list(eng.expansions),
        "players": [{"name": p.name, "is_ai": p.is_ai,
                     "ai_level": p.ai_level} for p in eng.players],
        "turn_index": eng.turn_idx,
        "round_count": eng.round_count,
        "ops": list(ops),
    }


def load_save(path: str) -> Dict[str, Any]:
    """读取并做结构校验（不重放；重放由调用方执行）。"""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or data.get("schema") != SAVE_SCHEMA:
        raise ValueError("不是有效的卡卡颂存档（schema 不符）")
    for key in ("seed", "expansions", "players", "ops"):
        if key not in data:
            raise ValueError("存档缺少字段：%s" % key)
    return data


def save_to_file(path: str, save: Dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(save, f, ensure_ascii=False, indent=1)


def _app_version() -> str:
    from . import __version__
    return __version__


def drive_special_phases(eng) -> None:
    """把特殊阶段推进到 place/river/deploy/over（中性选择）。

    供验证脚本与测试驱动完整对局使用；各阶段取首个合法目标或跳过。
    与 UI 的代打路径同构：金矿落位/法师女巫/隧道/脱困/怪圈/强盗/牧羊/
    瘟疫/重部署/进城部署/城堡改建/龙步。
    """
    guard = 0
    while not eng.game_over and guard < 64:
        guard += 1
        ph = eng.phase
        if ph in ("place", "river", "over", "deploy"):
            return
        if ph == "gold":
            eng.place_gold(eng.gold_options()[0])
        elif ph == "magewitch":
            fig = "mage" if eng.mage is not None else "witch"
            nodes = eng.mw_options().get(fig) or []
            if nodes:
                eng.mw_move(fig, nodes[0])
            else:
                eng.mw_remove(fig)
        elif ph == "tunnel":
            eng.tunnel_skip()
        elif ph == "escape":
            eng.escape_move(None)
        elif ph == "crop" and eng.crop:
            if eng.crop["mode"] is None:
                eng.crop_choose("B")
            else:
                copts = eng.crop_options()
                eng.crop_act(copts[0]["node"] if copts else None)
        elif ph == "robber" and eng.robber_phase:
            eng.robber_place(None)
        elif ph == "shepherd":
            eng.shepherd_act(True)
        elif ph == "plague" and eng.plague:
            popts = eng.plague_options()
            eng.plague_act(popts[0] if popts else None)
        elif ph == "redeploy":
            eng.redeploy_move(False)
        elif ph == "count_deploy":
            eng.skip_count_deploy()
        elif ph == "castle":
            eng.convert_castle(False)
        elif ph == "dragon":
            legal = eng.dragon_legal_steps()
            if legal:
                eng.dragon_move(legal[0])
            else:
                return
        else:
            return
