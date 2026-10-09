# -*- coding: utf-8 -*-
"""存档/续局：重放日志往返一致性。

录制一局随机对局的全部操作 → build_save → 在新引擎上 apply_history →
权威状态（盘面/分数/米宝/阶段/RNG 状态）必须逐项一致。
RNG getstate 相等意味着抽牌序列完全复现，续局后的后续抽牌同样可信。
"""
import random

from game import recorder
from game.engine import CarcassonneEngine

MINI = ["goldmines", "tunnel", "magewitch", "robbers", "crop", "festival",
        "besiegers", "tower", "hillsheep", "wheel"]


def _random_deploy(eng, rng):
    """随机部署决策（含塔/节日/普通部署；幽灵步骤跳过）。"""
    if eng._phantom_step:
        eng.skip_deploy()
        return
    tower_opts = eng.tower_piece_options()
    if tower_opts and rng.random() < 0.3:
        pos, captures = rng.choice(tower_opts)
        eng.tower_place(pos, rng.choice(captures) if captures else None)
        return
    top_opts = eng.tower_top_options()
    if top_opts and rng.random() < 0.2:
        eng.tower_deploy_top(rng.choice(top_opts))
        return
    ransoms = eng.ransom_options()
    if ransoms and rng.random() < 0.2:
        eng.ransom(rng.choice(ransoms))
        return
    if eng.festival_options() and rng.random() < 0.2:
        eng.festival_return(rng.choice(eng.festival_options()))
        return
    options = eng.deploy_options()
    if options and rng.random() < 0.6:
        opt = rng.choice(options)
        k = opt["kind"]
        if k == "fairy":
            eng.deploy_fairy(tuple(opt["pos"]))
        elif k == "princess":
            eng.deploy_princess(tuple(opt["victim"]), opt["victim_color"])
        else:
            eng.deploy(k, opt["seg"], big=bool(opt.get("big")),
                       pos=opt.get("pos"))
    else:
        eng.skip_deploy()


def _play_random_game(specs, seed, expansions, turns_cap=600):
    rng = random.Random(seed ^ 0x5EED)
    proxy = recorder.RecordingProxy(
        CarcassonneEngine(specs, seed=seed, expansions=expansions))
    turns = 0
    while not proxy.game_over:
        recorder.drive_special_phases(proxy)
        if proxy.game_over:
            break
        if proxy.phase == "deploy":
            _random_deploy(proxy, rng)
            recorder.drive_special_phases(proxy)
            continue
        assert proxy.phase in ("place", "river"), proxy.phase
        turns += 1
        assert turns < turns_cap, "对局未收敛"
        tries = 0
        while not proxy.legal_placements() and not proxy.game_over:
            proxy.discard_and_redraw()
            recorder.drive_special_phases(proxy)
            tries += 1
            assert tries <= 30
        if proxy.game_over:
            break
        x, y, rot = rng.choice(proxy.legal_placements())
        proxy.place(x, y, rot)
        recorder.drive_special_phases(proxy)
    return proxy


def _state_fingerprint(engine):
    eng = (engine.raw_engine if isinstance(engine, recorder.RecordingProxy)
           else engine)
    return {
        "tiles": sorted((t.tile_id, t.x, t.y, t.rot, t.placed_by)
                        for t in eng.board.tiles.values()),
        "scores": [p.score for p in eng.players],
        "supply": [(p.meeples_left, p.big_meeples_left, p.phantom_left,
                    p.tunnels_left, p.gold_pieces)
                   for p in eng.players],
        "phase": eng.phase,
        "game_over": eng.game_over,
        "turn_idx": eng.turn_idx,
        "current_tile": eng.current_tile.tile_id if eng.current_tile else None,
        "rng_state": repr(eng.rng.getstate()),
    }


def _assert_roundtrip(specs, seed, expansions):
    proxy = _play_random_game(specs, seed, expansions)
    save = recorder.build_save(proxy, seed, proxy.history)
    assert save["schema"] == recorder.SAVE_SCHEMA
    eng2 = CarcassonneEngine(save["players"], seed=save["seed"],
                             expansions=save["expansions"])
    recorder.apply_history(eng2, save["ops"])
    a = _state_fingerprint(proxy)
    b = _state_fingerprint(eng2)
    assert a == b, "重放后权威状态不一致：%s vs %s" % (
        {k: (a[k], b[k]) for k in a if a[k] != b[k]},)


def test_replay_roundtrip_base():
    _assert_roundtrip(
        [{"name": "甲"}, {"name": "AI", "is_ai": True, "ai_level": "normal"}],
        123, [])


def test_replay_roundtrip_minis():
    _assert_roundtrip(
        [{"name": "甲"}, {"name": "乙"},
         {"name": "AI", "is_ai": True, "ai_level": "hard"}],
        456, MINI)


def test_save_file_roundtrip(tmp_path):
    specs = [{"name": "甲"}, {"name": "AI", "is_ai": True,
                              "ai_level": "normal"}]
    proxy = _play_random_game(specs, 789, [])
    save = recorder.build_save(proxy, 789, proxy.history)
    path = str(tmp_path / "case.cksave")
    recorder.save_to_file(path, save)
    data = recorder.load_save(path)
    assert data["seed"] == 789 and data["ops"]
    eng2 = CarcassonneEngine(data["players"], seed=data["seed"],
                             expansions=data["expansions"])
    recorder.apply_history(eng2, data["ops"])
    assert (_state_fingerprint(proxy) == _state_fingerprint(eng2))
