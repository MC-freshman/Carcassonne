"""全扩展 AI 的故障回归与模拟隔离；完整对局矩阵见 verify_ai --all。"""
import threading

import pytest

from game import ai_turn, recorder, tile_data as td
from game.board import KIND_CITY, KIND_MON, KIND_ROAD
from game.bot_ai import BotAI
from game.engine import CarcassonneEngine
from game.models import PlacedTile


def engine(players=2, expansions=()):
    return CarcassonneEngine([{"name": str(i), "is_ai": True} for i in range(players)],
                             seed=5, expansions=list(expansions))


def add(eng, tile_id, pos, rot=0):
    tile = td.by_id(tile_id)
    eng.board.add_tile(PlacedTile(tile_id, *pos, rot, 0), tile, loose=True)
    return tile


def deploy_state(eng, tile_id="PD-CfPortal"):
    eng.current_tile = add(eng, tile_id, (1, 0))
    eng.placed_pos = (1, 0)
    eng.phase = "deploy"


@pytest.mark.parametrize("players,victim_idx", [(n, i) for n in range(2, 7) for i in range(1, n)])
def test_tower_targets_each_opponent(players, victim_idx):
    eng = engine(players, ("tower",))
    deploy_state(eng, "TOW-field")
    add(eng, "CSep", (2, 0))
    victim = (2, 0, KIND_CITY, 0)
    eng.board.deploy_meeple(victim, eng.players[victim_idx].color)
    eng.players[victim_idx].meeples_left -= 1
    chosen = BotAI("easy").choose_tower_piece(eng)
    assert chosen == ((1, 0), victim)


@pytest.mark.parametrize("level", ("normal", "hard"))
def test_portal_evaluates_and_deploys_remote_segment(level):
    eng = engine(expansions=("pd", "inns"))
    deploy_state(eng)
    add(eng, "CSep", (3, 0))
    opt = next(o for o in eng.deploy_options() if o.get("pos") == (3, 0)
               and o["kind"] == KIND_CITY and o["seg"] == 1 and not o["big"])
    chosen = BotAI(level)._best_deploy(eng, [opt])
    assert chosen == opt
    proxy = recorder.RecordingProxy(eng)
    ai_turn.apply_action(proxy, ai_turn.action("deploy_option", chosen))
    assert eng.board.meta(opt["node"]).meeples[eng.players[0].color] == 1
    assert proxy.history[-1]["a"][0]["pos"] == [3, 0]


def test_portal_does_not_offer_occupied_monastery():
    eng = engine(expansions=("pd",))
    deploy_state(eng)
    add(eng, "M", (3, 0))
    eng.board.deploy_meeple((3, 0, KIND_MON, 0), eng.players[1].color)
    assert not any(o["kind"] == KIND_MON and o.get("pos") == (3, 0)
                   for o in eng.deploy_options())


def test_only_large_supply_is_available():
    eng = engine(expansions=("inns",))
    deploy_state(eng, "CSep")
    eng.players[0].meeples_left = 0
    ordinary = [o for o in eng.deploy_options() if o["kind"] in ("city", "road", "farm", "mon")]
    assert ordinary and all(o["big"] for o in ordinary)


def test_phantom_deployment_uses_phantom_supply_even_without_ordinary_supply():
    eng = engine(expansions=("phantom", "inns", "wheel", "hillsheep"))
    deploy_state(eng, "CSep")
    first = next(o for o in eng.deploy_options() if o["kind"] == KIND_CITY and not o["big"])
    eng.deploy_option(first)
    assert eng._phantom_step
    ordinary_before = eng.players[0].meeples_left
    eng.players[0].meeples_left = 0
    opts = eng.deploy_options()
    assert opts and all(o.get("phantom") and not o["big"] for o in opts)
    chosen = BotAI("normal").choose_deploy(eng)
    eng.deploy_option(chosen)
    assert eng.players[0].meeples_left == 0
    assert eng.players[0].phantom_left == 0
    assert ordinary_before == 6


def test_dragon_returns_phantom_to_correct_pool():
    eng = engine(expansions=("pd", "phantom"))
    add(eng, "CSep", (2, 0))
    node = (2, 0, KIND_CITY, 0)
    eng.board.deploy_meeple(node, eng.players[0].color, phantom=True)
    eng.players[0].phantom_left = 0
    eng._dragon_devour((2, 0))
    assert eng.players[0].phantom_left == 1
    assert eng.players[0].meeples_left == 7


def test_escape_returns_large_knight_to_large_pool():
    eng = engine(expansions=("inns", "besiegers"))
    add(eng, "CSep", (2, 0))
    node = (2, 0, KIND_CITY, 0)
    eng.board.meta(node).sieged = True
    add(eng, "M", (3, 0))
    eng.board.deploy_meeple(node, eng.players[0].color, size=2)
    eng.players[0].big_meeples_left = 0
    eng.phase = "escape"
    eng.escape_move(node)
    assert eng.players[0].big_meeples_left == 1
    assert eng.players[0].meeples_left == 7


def test_clone_preserves_state_rng_and_feature_aliases():
    eng = engine(expansions=("inns", "traders", "pd", "phantom", "tower"))
    for _ in range(25):
        bot = BotAI("easy", seed=5)
        ai_turn.apply_action(eng, ai_turn.choose_action(eng, bot))
    eng.legal_placements()
    rep = eng.clone_for_simulation()
    assert rep.snapshot_dict() == eng.snapshot_dict()
    assert rep.rng.getstate() == eng.rng.getstate()
    aliases = {}
    for node, meta in eng.board._meta.items():
        assert rep.board.meta(node) is not meta
        if id(meta) in aliases:
            assert rep.board._meta[node] is aliases[id(meta)]
        aliases[id(meta)] = rep.board._meta[node]
    rep.players[0].score += 100
    assert rep.players[0].score != eng.players[0].score
    rep.board.frontier.clear()
    assert eng.board.frontier


def test_atomic_action_rolls_back_partial_failure_and_keeps_history():
    eng = engine()
    proxy = recorder.RecordingProxy(eng)
    before = eng.snapshot_dict()
    def bad_place(*args):
        eng.players[0].score += 100
        eng.log_lines.append("partial")
        raise RuntimeError("fault injection")
    eng.place = bad_place
    with pytest.raises(RuntimeError):
        ai_turn.apply_action(proxy, ai_turn.action("place", 0, 1, 0), atomic=True)
    assert eng.snapshot_dict() == before
    assert not proxy.history


def test_decision_player_rotates_during_dragon():
    eng = engine(3, ("pd",))
    eng.phase = "dragon"
    eng.turn_idx = 0
    eng.dragon["decider"] = 2
    assert eng.decision_player() is eng.players[2]


def test_budget_and_cancellation_keep_a_legal_fallback():
    eng = engine()
    bot = BotAI("hard", seed=5, time_budget_ms=0)
    assert bot.choose_move(eng)[0] in eng.legal_placements()
    assert bot.last_stats["simulated"] == 0
    bot.cancel_event = threading.Event()
    bot.cancel_event.set()
    assert bot.choose_move(eng)[0] in eng.legal_placements()


def test_legal_cache_returns_independent_list_and_invalidates_on_placement():
    eng = engine()
    opts = eng.legal_placements()
    original = list(opts)
    opts.clear()
    assert eng.legal_placements() == original
    eng.place(*original[0])
    assert not eng.legal_placements()
    expected = {(x+dx, y+dy) for x, y in eng.board.tiles
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))} - set(eng.board.tiles)
    assert eng.board.frontier == expected


def test_simulation_stops_before_hidden_fate_tile():
    eng = engine(expansions=("wheel",))
    eng.current_tile = td.by_id("RStraight")
    fate = next(t for t in td.registered_definitions() if t.fate)
    eng.deck = [fate]
    rep = eng.clone_for_simulation()
    rep._simulation_stop_before_draw = True
    rep.place(*rep.legal_placements()[0])
    wheel_before = rep.wheel_pig
    assert BotAI("hard")._drive_sim(rep, None)
    assert rep.current_tile is None
    assert rep.deck == [fate]
    assert rep.wheel_pig == wheel_before


def test_asset_registry_covers_every_expansion():
    from game.ui_dialogs import EXPANSIONS
    registered = {tile.tile_id for tile in td.registered_definitions()}
    for key, _, _ in EXPANSIONS:
        assert {t.tile_id for t in td.all_definitions([key])} <= registered
    assert td.start_tile(["wheel"]).tile_id in registered


def test_missing_sprite_falls_back_to_drawing(monkeypatch):
    from types import SimpleNamespace
    import tkinter as tk
    from game import ui
    drawn = []
    def missing(*args):
        raise tk.TclError("missing PNG")
    app = SimpleNamespace(sprites=SimpleNamespace(ok=True), _tile_img=missing)
    monkeypatch.setattr(ui, "draw_tile", lambda *args: drawn.append(args))
    ui.App._draw_tile_sprite(app, None, td.by_id("M"), 0, 0, 0, 100, "static")
    assert len(drawn) == 1
