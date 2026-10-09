# -*- coding: utf-8 -*-
"""主机权威服务器：持有唯一规则引擎，校验客户端操作，广播快照。

- 房主即为 0 号位（通过名字匹配），其余人类按加入顺序入座，AI 补尾部座位
- AI 回合与断线玩家由服务器代打（BotAI normal），保证对局不阻塞
- 断线后同名 join 可重连，座位保留并补发快照
"""
from __future__ import annotations

import queue
import random
import socket
import threading
import traceback
from typing import Any, Dict, List, Optional

from .. import tile_data
from ..bot_ai import BotAI
from .. import ai_turn
from ..engine import CarcassonneEngine
from ..models import meeple_majority
from .protocol import recv_msg, send_msg

DEFAULT_PORT = 37241


class Seat:
    def __init__(self, idx: int, name: str, is_ai: bool, level: str):
        self.idx = idx
        self.name = name
        self.is_ai = is_ai
        self.level = level
        self.conn: Optional[socket.socket] = None
        self.addr: Optional[str] = None
        # 每座位发送队列 + 独立写线程：广播（lobby/snap/over）只入队，
        # 绝不在引擎主锁内做阻塞 sendall。此前一个僵死客户端会把
        # _broadcast 卡在锁内，冻结整台主机的所有玩家。
        self.outq: "queue.Queue" = queue.Queue(maxsize=8)

    @property
    def connected(self) -> bool:
        return self.is_ai or self.conn is not None

    def attach(self, conn: socket.socket) -> None:
        """绑定连接并启动写线程（重连时旧线程因 conn 换新自动退出）。

        每条连接换新队列：旧写线程持有旧队列的引用，物理上不可能
        消费发往新连接的消息（否则旧写线程会在出队后才发现归属已变，
        把新连接的应答发进废弃 socket，重连的 join 应答凭空丢失）。
        """
        self.outq = queue.Queue(maxsize=8)
        self.conn = conn
        threading.Thread(target=self._write_loop, args=(conn,),
                         daemon=True).start()

    def send_async(self, msg: Dict[str, Any]) -> None:
        """锁内安全发送：入队即返回；队列满视为客户端失能，弃连。"""
        if self.conn is None:
            return
        try:
            self.outq.put_nowait(msg)
        except queue.Full:
            self._drop_conn(self.conn, "发送队列溢出")

    @staticmethod
    def _drop_conn(conn: Optional[socket.socket], reason: str) -> None:
        """只关闭传入的那条连接（绝不误伤座位当前的新连接）。"""
        if conn is not None:
            try:
                conn.close()   # recv 线程随即报错，走统一清理路径
            except OSError:
                pass

    def _write_loop(self, conn: socket.socket) -> None:
        outq = self.outq   # 绑定本连接的队列（重连后旧线程留在旧队列上）
        while self.conn is conn:
            try:
                item = outq.get(timeout=5)
            except queue.Empty:
                continue
            if item is None:
                break
            try:
                send_msg(conn, item)
            except OSError:
                self._drop_conn(conn, "写线程发送失败")
                break


class GameServer:
    """一台对局主机。start() 前为大厅，之后进入权威对局。"""

    def __init__(self, total_players: int, host_name: str,
                 ai_specs: Optional[List[dict]] = None,
                 port: int = 0, seed: Optional[int] = None,
                 expansions: Optional[List[str]] = None):
        assert 2 <= total_players <= 6
        self.expansions = list(expansions or [])
        ai_specs = ai_specs or []
        n_humans = total_players - len(ai_specs)
        assert 1 <= n_humans <= total_players, "至少留 1 个人类座位（房主）"

        self.seats: List[Seat] = [Seat(0, host_name, False, "normal")]
        for i in range(1, n_humans):
            self.seats.append(Seat(i, "（等待加入）", False, "normal"))
        for j, spec in enumerate(ai_specs):
            self.seats.append(Seat(n_humans + j, spec.get("name") or "AI-%d" % (n_humans + j),
                                   True, spec.get("ai_level", "normal")))

        self.engine: Optional[CarcassonneEngine] = None
        self.bots: Dict[int, BotAI] = {}
        self._seed = seed if seed is not None else random.randrange(1 << 30)
        self._lock = threading.Lock()
        self._sent_events = 0
        self._over_sent = False
        self._started = False

        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self._srv.bind(("", DEFAULT_PORT))   # 优先固定端口，便于口头告知
        except OSError:
            self._srv.bind(("", port))
        self._srv.listen(8)
        self.port = self._srv.getsockname()[1]
        self._stop = False
        self._acc = threading.Thread(target=self._accept_loop, daemon=True)
        self._acc.start()

    # ------------------------------------------------------------ 生命周期

    def close(self) -> None:
        self._stop = True
        try:
            self._srv.close()
        except OSError:
            pass
        for s in self.seats:
            s.outq.put(None)   # 唤醒写线程退出
            if s.conn:
                try:
                    s.conn.close()
                except OSError:
                    pass

    def _accept_loop(self) -> None:
        while not self._stop:
            try:
                conn, addr = self._srv.accept()
            except OSError:
                break
            threading.Thread(target=self._serve, args=(conn, addr),
                             daemon=True).start()

    def _serve(self, conn: socket.socket, addr) -> None:
        seat: Optional[Seat] = None
        try:
            while True:
                msg = recv_msg(conn)
                if msg is None:
                    break
                # 单条消息的引擎异常转成 error 回复，绝不因客户端操作杀死线程
                try:
                    with self._lock:
                        seat, reply = self._handle(conn, addr, seat, msg)
                except Exception:
                    traceback.print_exc()
                    reply = {"t": "error", "msg": "服务器处理该操作时出错"}
                if reply is not None:
                    send_msg(conn, reply)
        except (OSError, ValueError):
            pass
        finally:
            with self._lock:
                if seat is not None and seat.conn is conn:
                    seat.conn, seat.addr = None, None
                    seat.name = seat.name if not seat.name.startswith("（") else seat.name
                    self._broadcast_lobby()
                    # 若轮到断线者，代打推进
                    if self._started and self.engine and not self.engine.game_over:
                        try:
                            self._advance_and_broadcast([])
                        except Exception:
                            traceback.print_exc()
            try:
                conn.close()
            except OSError:
                pass

    # ------------------------------------------------------------ 消息处理

    def _handle(self, conn, addr, seat: Optional[Seat], msg: Dict[str, Any]):
        """返回 (绑定的座位, 立即回复消息或 None)。锁内调用。"""
        t = msg.get("t")

        if t == "join":
            name = str(msg.get("name") or "玩家")[:12]
            # 重连：对局中同名人类座位
            if self._started:
                for s in self.seats:
                    if not s.is_ai and s.name == name and s.conn is None:
                        s.addr = addr
                        s.attach(conn)
                        self._broadcast_lobby(exclude=conn)
                        if self.engine:
                            # 应答与补发快照都走该座位队列，保证客户端
                            # 先收到 lobby（知道 you）再收到 snap
                            s.send_async({"t": "lobby", "you": s.idx,
                                          "seats": self._lobby_seats()})
                            s.send_async(self._snap_msg([]))
                            return s, None
                        return s, {"t": "lobby", "you": s.idx,
                                   "seats": self._lobby_seats()}
                return None, {"t": "error", "msg": "对局已开始且无此玩家座位"}
            # 大厅：房主名匹配 0 号位，其余填第一个空位
            target = None
            if name == self.seats[0].name and self.seats[0].conn is None:
                target = self.seats[0]
            else:
                for s in self.seats[1:]:
                    if not s.is_ai and s.conn is None and \
                            s.name.startswith("（等待"):
                        target = s
                        break
            if target is None:
                return None, {"t": "error", "msg": "房间已满"}
            target.name = name
            target.addr = addr
            target.attach(conn)
            self._broadcast_lobby(exclude=conn)
            return target, {"t": "lobby", "you": target.idx,
                            "seats": self._lobby_seats()}

        if seat is None:
            return None, {"t": "error", "msg": "未加入"}

        if t == "ping":
            return seat, {"t": "pong", "ts": msg.get("ts")}

        if t == "kick":
            if seat.idx != 0:
                return seat, {"t": "error", "msg": "只有房主能移出玩家"}
            if self._started:
                return seat, {"t": "error", "msg": "对局中不能移出玩家"}
            target_idx = int(msg.get("seat", -1))
            target = self.seats[target_idx] if 0 <= target_idx < len(self.seats) else None
            if target is None or target.is_ai or target.conn is None:
                return seat, {"t": "error", "msg": "目标座位不可移出"}
            try:
                send_msg(target.conn, {"t": "kicked"})
            except OSError:
                pass
            target.conn = None
            target.name = "（等待加入）"
            self._broadcast_lobby()
            return seat, None

        if t == "start":
            if seat.idx != 0:
                return seat, {"t": "error", "msg": "只有房主能开始"}
            return seat, self._start_game()

        if t in ("place", "deploy", "skip", "discard", "drag", "bridge",
                 "redeploy", "countdep", "countskip", "castle", "bazaar",
                 "gold", "mw", "tunnel", "crop", "robber", "escape",
                 "tower", "shepherd", "plague"):
            if not self._started or self.engine is None:
                return seat, {"t": "error", "msg": "对局未开始"}
            ok, err = self._apply_action(seat, t, msg)
            if not ok:
                return seat, {"t": "error", "msg": err}
            new_events = [e for e in self.engine.events][self._sent_events:]
            self._sent_events = len(self.engine.events)
            self._advance_and_broadcast(new_events)
            return seat, None

        return seat, {"t": "error", "msg": "未知消息 %r" % t}

    # ------------------------------------------------------------ 对局驱动

    def _start_game(self) -> Dict[str, Any]:
        if any(not s.connected for s in self.seats):
            return {"t": "error", "msg": "还有座位未加入（可改为 AI 或等待）"}
        if self._started:
            return {"t": "error", "msg": "对局已开始"}
        specs = [{"name": s.name, "is_ai": s.is_ai, "ai_level": s.level}
                 for s in self.seats]
        self.engine = CarcassonneEngine(specs, seed=self._seed,
                                        expansions=self.expansions)
        self.bots = {s.idx: BotAI(s.level, seed=self._seed + s.idx)
                     for s in self.seats if s.is_ai}
        self._started = True
        self._sent_events = 0
        self._advance_and_broadcast([])
        return {"t": "started"}

    def _apply_action(self, seat: Seat, t: str, msg: Dict[str, Any]):
        eng = self.engine
        if eng.game_over:
            return False, "对局已结束"
        if t == "drag":
            # 龙移动：以龙轮值决定者为准（可能不是当前回合玩家）
            if eng.phase != "dragon":
                return False, "当前不是龙移动阶段"
            dec = eng.dragon_decider_player()
            if dec is None or dec.idx != seat.idx:
                return False, "还没轮到你移动龙"
            pos = (int(msg["x"]), int(msg["y"]))
            if pos not in eng.dragon_legal_steps():
                return False, "非法龙步"
            eng.dragon_move(pos)
            return True, None
        if t == "redeploy":
            # 伯爵城重部署回合：以当前决策者为准（非当前回合玩家）
            if eng.phase != "redeploy":
                return False, "当前不是重部署回合"
            st = eng.redeploy_state()
            if st is None or st["player"] != seat.idx:
                return False, "还没轮到你决定"
            eng.redeploy_move(bool(msg.get("move")))
            return True, None
        if t == "countdep":
            if eng.phase != "count_deploy":
                return False, "当前不是进城部署阶段"
            if seat.idx != eng._placer_idx:
                return False, "还没轮到你"
            q, fig = msg["quarter"], msg["fig"]
            mv = msg.get("count_move_to")
            if not any(o["quarter"] == q and o["fig"] == fig
                       for o in eng.count_deploy_options()):
                return False, "非法进城部署"
            if mv is not None and mv not in eng.count["quarters"]:
                return False, "非法伯爵移动"
            eng.deploy_count(q, fig, mv)
            return True, None
        if t == "countskip":
            if eng.phase != "count_deploy":
                return False, "当前不是进城部署阶段"
            if seat.idx != eng._placer_idx:
                return False, "还没轮到你"
            eng.skip_count_deploy()
            return True, None
        if t == "castle":
            if eng.phase != "castle":
                return False, "当前不是城堡改建阶段"
            winners = []
            if eng._castle_queue:
                meta = eng.board._meta[eng._castle_queue[0]]
                winners, _t = (eng._city_majority(meta) if meta.mayors
                               else meeple_majority(meta.meeples))
            occupier = winners[0] if winners else eng.current_player().color
            occ = eng._player_by_color(occupier)
            if occ.idx != seat.idx:
                return False, "只有小城占据者能改建城堡"
            eng.convert_castle(bool(msg.get("convert")))
            return True, None
        if t == "bridge":
            # M19：部署阶段的自愿建桥（CAR 脚注 292：部署之外的额外动作）
            if eng.phase != "deploy":
                return False, "当前不是部署阶段"
            if eng.players[eng.turn_idx].idx != seat.idx:
                return False, "还没轮到你"
            pos = (int(msg["x"]), int(msg["y"]))
            axis = int(msg["axis"])
            if (pos, axis) not in eng.bridge_options():
                return False, "非法建桥"
            eng.build_bridge(pos, axis)
            return True, None
        if t == "gold":
            # M20 金矿：第二块金子由放置者落位
            if eng.phase != "gold":
                return False, "当前不是金块落位阶段"
            if eng.players[eng.turn_idx].idx != seat.idx:
                return False, "还没轮到你"
            npos = (int(msg["x"]), int(msg["y"]))
            if npos not in eng.gold_options():
                return False, "非法金块落位"
            eng.place_gold(npos)
            return True, None
        if t == "mw":
            # M20 法师/女巫：放置或移动（node 为空=收回）
            if eng.phase != "magewitch":
                return False, "当前不是法师女巫阶段"
            if eng.players[eng.turn_idx].idx != seat.idx:
                return False, "还没轮到你"
            fig = msg.get("fig")
            if fig not in ("mage", "witch"):
                return False, "非法图元"
            node = msg.get("node")
            if node is None:
                if getattr(eng, fig) is None:
                    return False, "图元不在场上"
                eng.mw_remove(fig)
                return True, None
            node = tuple(node)
            if node not in eng.mw_options()[fig]:
                return False, "非法法师女巫目标"
            eng.mw_move(fig, node)
            return True, None
        if t == "tunnel":
            # M20 隧道令牌：占领或放弃
            if eng.phase != "tunnel":
                return False, "当前不是隧道阶段"
            if eng.players[eng.turn_idx].idx != seat.idx:
                return False, "还没轮到你"
            if msg.get("skip"):
                eng.tunnel_skip()
                return True, None
            kind = msg.get("kind", "road")
            node = (int(msg["x"]), int(msg["y"]), kind, int(msg["seg"]))
            if node not in eng.tunnel_options():
                return False, "非法隧道口"
            eng.tunnel_claim(node)
            return True, None
        if t == "crop":
            # M20 麦田怪圈：选效果 / 各玩家行动
            if eng.phase != "crop" or not eng.crop:
                return False, "当前不是麦田怪圈阶段"
            if eng.crop["mode"] is None:
                if seat.idx != eng._placer_idx:
                    return False, "还没轮到你选效果"
                eng.crop_choose("A" if msg.get("mode") == "A" else "B")
                return True, None
            idx = eng.crop["order"][eng.crop["pos"]]
            if seat.idx != idx:
                return False, "还没轮到你"
            node = msg.get("node")
            if node is not None:
                node = tuple(node)
                if not any(o["node"] == node for o in eng.crop_options()):
                    return False, "非法怪圈动作"
            eng.crop_act(node)
            return True, None
        if t == "robber":
            # M20 强盗：上轨 / 移动 / 放弃
            if eng.phase != "robber" or not eng.robber_phase:
                return False, "当前不是强盗阶段"
            idx = eng.robber_phase["order"][eng.robber_phase["pos"]]
            if seat.idx != idx:
                return False, "还没轮到你"
            space = msg.get("space")
            if space is not None:
                space = int(space)
                if space not in eng.robber_options():
                    return False, "非法强盗格"
            eng.robber_place(space)
            return True, None
        if t == "plague":
            # M21 命运之轮：瘟疫收回一名己方场上随从
            if eng.phase != "plague" or not eng.plague:
                return False, "当前不是瘟疫阶段"
            idx = eng.plague["order"][int(eng.plague["pos"])]
            if seat.idx != idx:
                return False, "还没轮到你"
            node = msg.get("node")
            if node is not None:
                node = tuple(node)
                if node not in eng.plague_options():
                    return False, "非法瘟疫收回"
            eng.plague_act(node)
            return True, None
        if t == "shepherd":
            # M21 山丘与羊：扩群 / 入圈
            if eng.phase != "shepherd":
                return False, "当前不是牧羊行动阶段"
            if eng.players[eng.turn_idx].idx != seat.idx:
                return False, "还没轮到你"
            eng.shepherd_act(bool(msg.get("expand")))
            return True, None
        if t == "tower":
            # M21 塔：建塔（可带抓捕）/ 驻塔 / 赎金（代替部署随从）
            if eng.phase != "deploy":
                return False, "当前不是部署阶段"
            if eng.players[eng.turn_idx].idx != seat.idx:
                return False, "还没轮到你"
            act = msg.get("action")
            if act == "piece":
                pos = (int(msg["x"]), int(msg["y"]))
                capture = msg.get("capture")
                if capture is not None:
                    capture = tuple(capture)
                if pos not in [p for p, _c in eng.tower_piece_options()]:
                    return False, "非法塔位"
                eng.tower_place(pos, capture)
                return True, None
            if act == "top":
                pos = (int(msg["x"]), int(msg["y"]))
                if pos not in eng.tower_top_options():
                    return False, "非法驻塔"
                eng.tower_deploy_top(pos, big=bool(msg.get("big")))
                return True, None
            if act == "ransom":
                idx = int(msg["idx"])
                if idx not in eng.ransom_options():
                    return False, "非法赎回"
                eng.ransom(idx)
                return True, None
            return False, "未知塔动作"
        if t == "escape":
            # M20 围攻脱困：回合末撤出一名骑士
            if eng.phase != "escape":
                return False, "当前不是脱困阶段"
            if eng.players[eng.turn_idx].idx != seat.idx:
                return False, "还没轮到你"
            node = msg.get("node")
            if node is not None:
                node = tuple(node)
                if node not in eng.escape_options():
                    return False, "非法脱困"
            eng.escape_move(node)
            return True, None
        if t == "bazaar":
            if eng.phase != "bazaar" or not eng.bazaar:
                return False, "当前不是集市阶段"
            b = eng.bazaar
            act = msg.get("action")
            if b["phase"] == "select" and seat.idx != b["selector"]:
                return False, "还没轮到你选牌"
            if b["phase"] == "bid" and seat.idx != b.get("bid_turn"):
                return False, "还没轮到你出价"
            if b["phase"] == "decide" and seat.idx != b["selector"]:
                return False, "还没轮到你决定"
            if act == "select":
                eng.bazaar_select(int(msg["idx"]), int(msg.get("bid", 0)))
            elif act == "bid":
                eng.bazaar_bid(int(msg["amount"]))
            elif act == "pass":
                eng.bazaar_pass()
            elif act == "resolve":
                eng.bazaar_resolve(bool(msg.get("keep")))
            else:
                return False, "未知集市动作"
            return True, None
        cur = eng.players[eng.turn_idx]
        if cur.idx != seat.idx:
            return False, "还没轮到你"
        if t == "place":
            if eng.phase not in ("place", "river"):
                return False, "当前不是放置阶段"
            x, y, rot = int(msg["x"]), int(msg["y"]), int(msg["rot"])
            if (x, y, rot) not in eng.legal_placements():
                return False, "非法放置"
            eng.place(x, y, rot)
            return True, None
        if t == "deploy":
            if eng.phase != "deploy":
                return False, "当前不是部署阶段"
            kind = msg["kind"]
            if kind == "festival_ret":
                # M20 节日牌：收回己方图元（代替部署）
                if eng.players[eng.turn_idx].idx != seat.idx:
                    return False, "还没轮到你"
                opt = {"fig": msg.get("fig"),
                       "node": tuple(msg.get("pos") or ())}
                if opt not in eng.festival_options():
                    return False, "非法节日收回"
                eng.festival_return(opt)
                return True, None
            seg, big = int(msg["seg"]), bool(msg.get("big"))
            pos = tuple(msg["pos"]) if msg.get("pos") else None
            phantom = bool(eng._phantom_step) and kind in (
                "city", "road", "farm", "mon")
            if not any(o["kind"] == kind and o["seg"] == seg
                       and bool(o.get("big")) == big
                       and (o.get("pos") or None) == (pos or None)
                       for o in eng.deploy_options()):
                return False, "非法部署"
            eng.deploy(kind, seg, big=big, pos=pos,
                       victim=msg.get("victim"),
                       victim_color=msg.get("victim_color"),
                       phantom=phantom)
            return True, None
        if t == "skip":
            if eng.phase != "deploy":
                return False, "当前不是部署阶段"
            eng.skip_deploy()
            return True, None
        if t == "discard":
            if eng.phase not in ("place", "river") or eng.can_place_anywhere():
                return False, "当前不可弃牌"
            eng.discard_and_redraw()
            return True, None
        return False, "未知操作"

    def _advance_and_broadcast(self, new_events: List) -> None:
        """AI 回合与断线者代打，直到轮到在线人类；随后广播。"""
        eng = self.engine
        guard = 0
        while not eng.game_over and guard < 5000:
            guard += 1
            player = eng.decision_player()
            if player is None:
                raise RuntimeError("AI 阶段缺少决策者：%s" % eng.phase)
            if self.seats[player.idx].connected and not player.is_ai:
                break
            bot = self.bots.get(player.idx) or BotAI("normal", seed=self._seed)
            try:
                chosen = ai_turn.choose_action(eng, bot)
            except Exception:
                traceback.print_exc()
                chosen = ai_turn.choose_action(eng, bot, neutral=True)
            ai_turn.apply_action(eng, chosen, atomic=True)
        if guard >= 5000 and not eng.game_over:
            raise RuntimeError("AI 连续行动超过上限：%s" % eng.phase)
        if eng.events and len(eng.events) > self._sent_events:
            new_events = eng.events[self._sent_events:] + list(new_events)
            self._sent_events = len(eng.events)
        if eng.game_over:
            fin = eng.final_scoring()
            msg = self._snap_msg(list(fin), over=True)
            if not self._over_sent:
                self._broadcast(msg)
                self._over_sent = True
            return
        self._broadcast(self._snap_msg(new_events))

    # ------------------------------------------------------------ 广播

    def _lobby_seats(self) -> List[Dict[str, Any]]:
        return [{"idx": s.idx, "name": s.name, "is_ai": s.is_ai,
                 "level": s.level, "connected": s.connected}
                for s in self.seats]

    def _broadcast_lobby(self, exclude: Optional[socket.socket] = None) -> None:
        for s in self.seats:
            if s.conn is not None and s.conn is not exclude:
                s.send_async({"t": "lobby", "seats": self._lobby_seats()})

    def _snap_msg(self, events: List, over: bool = False) -> Dict[str, Any]:
        ev = [{"kind": e.kind, "reason": e.reason,
               "scores": dict(e.scores), "meeples": dict(e.meeples),
               "detail": e.detail} for e in events]
        return {"t": "over" if over else "snap",
                "snap": self.engine.snapshot_dict(), "events": ev}

    def _broadcast(self, msg: Dict[str, Any]) -> None:
        """只入队不发送：写线程负责实际 sendall（见 Seat.send_async）。"""
        for s in self.seats:
            if s.conn is not None:
                s.send_async(msg)
