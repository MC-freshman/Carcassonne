"""真实 Tk 主循环验证：后台 AI、暂停丢弃过期结果、单步、异常恢复、全扩展终局。"""
import os
import threading
import time

os.environ["CARCASSONNE_HEADLESS"] = "1"

from game.ui import App
from game.ui_dialogs import EXPANSIONS
from game import ai_turn
from verify_ai import assert_final_supply


def wait(app, predicate, timeout=15):
    deadline = time.perf_counter() + timeout
    while not predicate():
        assert time.perf_counter() < deadline, "UI 等待超时，阶段=%s" % app.engine.phase
        app.update()
        time.sleep(0.002)


def run():
    exps = [key for key, _, _ in EXPANSIONS]
    app = App([{"name": "AI%d" % i, "is_ai": True} for i in range(3)],
              seed=0, expansions=exps)
    app.withdraw()
    app._cancel_ai()
    # 初始河流牌可能需弃牌，先推进到实际需要选步的阶段。
    for _ in range(32):
        if app.engine.phase in ("place", "river") and app.engine.legal_placements():
            break
        player = app.engine.decision_player()
        ai_turn.apply_action(app.engine, ai_turn.choose_action(app.engine, app.bots[player.idx]))
    baseline = len(app.engine.history)
    app.refresh()
    app._ai_delay.set(0)
    app._ai_follow.set(False)
    errors = []
    app._record_ai_error = lambda exc: errors.append(repr(exc))
    ticks = []
    def heartbeat():
        ticks.append(time.perf_counter())
        app.after(5, heartbeat)
    app.after(5, heartbeat)
    try:
        # 延迟计算时 UI 必须继续处理暂停事件，过期动作不能提交。
        player = app.engine.decision_player()
        bot = app.bots[player.idx]
        original = bot.choose_move
        started = threading.Event()
        release = threading.Event()
        def delayed(eng):
            started.set()
            assert release.wait(3)
            return original(eng)
        bot.choose_move = delayed
        before = app.engine.snapshot_dict()
        app._ai_step()
        wait(app, started.is_set)
        wait(app, lambda: len(ticks) >= 5)
        app._toggle_ai_pause()
        release.set()
        wait(app, lambda: app._ai_job is None)
        after = app.engine.snapshot_dict()
        assert after == before, "暂停后提交了过期动作：%s history=%s errors=%s" % (
            [key for key in before if before[key] != after[key]], app.engine.history, errors)
        assert len(ticks) >= 5, "AI 阻塞了 Tk 主循环"
        del bot.choose_move

        # 暂停状态单步只提交一个规则动作。
        app._single_ai_step()
        wait(app, lambda: app._ai_job is None and len(app.engine.history) == baseline + 1)
        assert app._ai_paused
        for _ in range(5):
            app.update()
        assert len(app.engine.history) == baseline + 1

        # 决策异常发生在提交前：记录错误，以合法的中性动作推进。
        player = app.engine.decision_player()
        bot = app.bots[player.idx]
        original_tower = bot.choose_tower_piece
        def fail(eng):
            raise RuntimeError("injected AI planning failure")
        bot.choose_tower_piece = fail
        app._single_ai_step()
        wait(app, lambda: app._ai_job is None and len(app.engine.history) == baseline + 2)
        assert errors and not app._ai_error
        del bot.choose_tower_piece

        app._toggle_ai_pause()
        wait(app, lambda: app.engine.game_over, timeout=150)
        app._cancel_ai()
        app.engine.final_scoring()
        assert_final_supply(app.engine)
        assert len(errors) == 1, "全扩展 UI 出现未预期的降级：%s" % errors
        print("AI UI OK: 主循环响应 / 暂停取消 / 单步 / 异常恢复 / 三人全20扩展终局；%d次动作" %
              len(app.engine.history), flush=True)
    finally:
        app.destroy()


if __name__ == "__main__":
    run()
