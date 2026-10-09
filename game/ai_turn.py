"""AI 单步动作：单机、联机和完整对局验证共用；决策不提交权威状态。"""
from __future__ import annotations

from .recorder import OPS


def action(op, *args, **kwargs):
    return {"op": op, "args": args, "kwargs": kwargs}


def choose_action(eng, bot, neutral=False):
    ph = eng.phase
    if ph in ("place", "river"):
        legal = eng.legal_placements()
        if not legal:
            return action("discard_and_redraw")
        move = legal[0] if neutral else bot.choose_move(eng)[0]
        assert move in legal, "AI 非法放置"
        return action("place", *move)
    if ph == "deploy":
        # 幽灵步骤只允许第二枚随从，不再给塔/赎金/节日行动。
        if not eng._phantom_step and not neutral:
            tower = bot.choose_tower_piece(eng)
            if tower is not None:
                return action("tower_place", *tower)
            top = bot.choose_tower_top(eng)
            if top is not None:
                return action("tower_deploy_top", top)
            ransom = bot.choose_ransom(eng)
            if ransom is not None:
                return action("ransom", ransom)
            festival = eng.festival_options()
            if festival and eng.current_player().meeples_left <= 2:
                opts = [o for o in festival if o.get("fig") == "meeple"]
                if opts:
                    return action("festival_return", opts[0])
        opt = None if neutral else bot.choose_deploy(eng)
        return action("deploy_option", opt) if opt else action("skip_deploy")
    if ph == "dragon":
        legal = eng.dragon_legal_steps()
        assert legal, "龙阶段没有合法步"
        return action("dragon_move", legal[0] if neutral else bot.choose_dragon_step(eng, legal))
    if ph == "redeploy":
        return action("redeploy_move", False if neutral else bot.choose_redeploy(eng))
    if ph == "count_deploy":
        opt = None if neutral else bot.choose_count_deploy(eng)
        if opt is None:
            return action("skip_count_deploy")
        return action("deploy_count", opt["option"]["quarter"], opt["option"]["fig"],
                      opt.get("count_move_to"))
    if ph == "castle":
        return action("convert_castle", False if neutral else bot.choose_castle(eng))
    if ph == "bazaar" and eng.bazaar:
        phase = eng.bazaar["phase"]
        if phase == "select":
            return action("bazaar_select", 0, 0)
        if phase == "bid":
            return action("bazaar_pass")
        if phase == "decide":
            return action("bazaar_resolve", False)
    if ph == "gold":
        return action("place_gold", eng.gold_options()[0] if neutral else bot.choose_gold(eng))
    if ph == "magewitch":
        if neutral:
            opts = eng.mw_options()
            for fig in ("mage", "witch"):
                if opts[fig]:
                    return action("mw_move", fig, opts[fig][0])
            fig = "mage" if eng.mage is not None else "witch"
            return action("mw_remove", fig)
        fig, node = bot.choose_mw(eng)
        return action("mw_remove", fig) if node is None else action("mw_move", fig, node)
    if ph == "tunnel":
        node = None if neutral else bot.choose_tunnel(eng)
        return action("tunnel_skip") if node is None else action("tunnel_claim", node)
    if ph == "escape":
        return action("escape_move", None if neutral else bot.choose_escape(eng))
    if ph == "crop" and eng.crop:
        if eng.crop["mode"] is None:
            return action("crop_choose", "B" if neutral else bot.choose_crop(eng))
        opts = eng.crop_options()
        node = (opts[0]["node"] if opts else None) if neutral else bot.choose_crop(eng)
        return action("crop_act", node)
    if ph == "robber":
        return action("robber_place", None if neutral else bot.choose_robber(eng))
    if ph == "shepherd":
        return action("shepherd_act", False if neutral else bot.choose_shepherd(eng))
    if ph == "plague":
        opts = eng.plague_options()
        node = (opts[0] if opts else None) if neutral else bot.choose_plague(eng)
        return action("plague_act", node)
    raise ValueError("AI 未能推进阶段 %s" % ph)


def apply_action(eng, chosen, atomic=False):
    """提交单个动作；本地 UI 可回滚失败动作，不重试已提交的部分状态。"""
    assert chosen["op"] in OPS, "未知 AI 动作"
    raw = getattr(eng, "raw_engine", eng)
    before = raw.clone_for_simulation() if atomic else None
    try:
        return getattr(eng, chosen["op"])(*chosen["args"], **chosen["kwargs"])
    except Exception:
        if before is not None:
            raw.__dict__.clear()
            raw.__dict__.update(before.__dict__)
        raise
