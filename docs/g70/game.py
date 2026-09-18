"""アイランド・ダイス ブラウザ版

CLI 版（g70-island-dice/main.py）と中身はまったく同じ。島の高さ（height）、マスの表と道の網（SQUARES）、手番の状態機械
（World.update）、出来事（land・draw_card）、CPU の性格（cpu_choice）は 1 文字も変えていない。

違うのは 2 つ。
  絵: 端末は上から見た地図、ここでは同じ height() から島の地形を作り Three.js で描く（水・木・マス・コマ）
  サイコロ: 端末は乱数、ここでは Cannon-es（物理エンジン）で本当に転がし、止まったときに上を向いた面を読んで world.roll() に渡す
"""

import asyncio
import base64
import io
import json
import math
import random
import wave
from array import array
from dataclasses import dataclass, field
from enum import Enum

from pyodide.ffi import create_proxy, to_js
from pyscript import document, when, window


STEP = 1 / 30


ISLAND_R = 13.0                                     # 島の半径（世界の単位）


SEA = 0.35                                          # 海面の高さ


def height(x: float, z: float) -> float:
    """島の高さ。真ん中が高く、縁で海に沈む。山が 1 つ、うねりが少し。端末の地図もブラウザの地形もこの式。"""
    r = math.hypot(x, z) / ISLAND_R
    base = max(0.0, 2.4 * (1 - r * r))
    ripple = 0.5 * math.sin(x * 0.6 + 1.0) * math.cos(z * 0.5 - 0.5)
    peak = 3.6 * math.exp(-((x - 3.0) ** 2 + (z + 3.5) ** 2) / 10.0)
    return base + ripple * min(1.0, base) + peak * min(1.0, base)


def ground(x: float, z: float) -> str:
    """地面の種類（色に使う）。"""
    h = height(x, z)
    if h < SEA:
        return "sea"
    if h < SEA + 0.35:
        return "sand"
    if h < 2.6:
        return "grass"
    if h < 3.8:
        return "rock"
    return "snow"


MAIN_KNOTS = [(-9.5, 7.0), (-8.0, 3.0), (-4.5, 2.0), (-3.0, -2.0), (-6.0, -5.5), (-2.5, -8.5), (2.0, -8.0), (4.5, -5.0),
              (7.5, -3.0), (8.5, 1.0), (5.5, 4.0), (1.5, 5.5), (-1.5, 8.5), (3.0, 9.5), (7.5, 8.0), (10.0, 4.5)]


SIDE_KNOTS = [(-3.0, -2.0), (0.5, -3.0), (3.5, -1.0), (7.5, -3.0)]     # 分かれ道：山を越える近道（危険）


MAIN_COUNT = 38                                     # 本道のマスの数（スタートとゴールを含む）


SIDE_COUNT = 6                                      # 近道のマスの数（分岐と合流を除く）


FORK_AT = 4                                         # 本道の何番目で分かれるか


REJOIN_AT = 15                                      # 本道の何番目に戻るか


MAIN_LAYOUT = "S+.?-+.?B+-!?+.-?+.$-W?+H-+?J-!+?J-+.G"


SIDE_LAYOUT = "-?V$-+"


SHIP_TO = 18                                        # 船が着く先


WARP_RANGE = (3, 7)


SHOP_PRICE = 500


JANKEN_BET = 400


VOLCANO_RANGE = 4                                   # 火山のマスから道の番号でこの距離まで


VOLCANO_DAMAGE = 300


KINDS = {
    "S": dict(name="スタート", color=(240, 240, 240)),
    "G": dict(name="ゴール", color=(255, 220, 90)),
    "+": dict(name="お金が増える", color=(90, 200, 120)),
    "-": dict(name="お金が減る", color=(230, 90, 90)),
    "?": dict(name="カード", color=(90, 150, 240)),
    "!": dict(name="1 回休み", color=(160, 160, 170)),
    "$": dict(name="宝", color=(255, 170, 60)),
    "B": dict(name="船", color=(80, 200, 220)),
    "W": dict(name="ワープ", color=(170, 110, 240)),
    "H": dict(name="店", color=(230, 200, 100)),
    "J": dict(name="じゃんけん", color=(240, 120, 200)),
    "V": dict(name="火山", color=(150, 50, 40)),
    ".": dict(name="", color=(200, 190, 160)),
}


PLUS = (300, 400, 500, 600, 800)                    # + のマスの額（順に回す）


MINUS = (200, 300, 400, 500)


TREASURE = 1500


GOAL_BONUS = (3000, 2000, 1000, 500)                # ゴールした順


START_MONEY = 1000


CARDS = (
    dict(name="給料日", text="給料日！ +600", kind="money", amount=600),
    dict(name="宝くじ", text="宝くじが当たった！ +1200", kind="money", amount=1200),
    dict(name="財布を落とした", text="財布を落とした… −500", kind="money", amount=-500),
    dict(name="税金", text="税金の日。全員が 200 払う", kind="tax", amount=200),
    dict(name="おごり", text="1 位からおごってもらう +400", kind="steal", amount=400),
    dict(name="追い風", text="追い風！ 3 マス進む", kind="move", amount=3),
    dict(name="迷子", text="迷子… 2 マス戻る", kind="move", amount=-2),
    dict(name="昼寝", text="昼寝で 1 回休み", kind="rest", amount=0),
    dict(name="全員に配る", text="太っ腹！ 全員に 100 ずつ配る", kind="give", amount=100),
    dict(name="押し戻し", text="先頭の人を 3 マス戻す", kind="push", amount=3),
    dict(name="横取り", text="宝を持っている人から 500 もらう", kind="rob", amount=500),
)


PLAYERS = (
    dict(name="あなた", cpu=None, color=(70, 140, 240)),
    dict(name="タケシ", cpu="steady", color=(90, 200, 110)),
    dict(name="ミカ", cpu="gambler", color=(240, 110, 160)),
    dict(name="ゴロウ", cpu="mean", color=(240, 170, 60)),
)


PERSONALITY = {
    "steady": dict(word="堅実", side=0.15, side_behind=0.35, shop_if=1800),
    "gambler": dict(word="賭け", side=0.8, side_behind=0.95, shop_if=SHOP_PRICE),
    "mean": dict(word="いじわる", side=0.4, side_behind=0.7, shop_if=1000),
}


HOP_TIME = 0.28                                     # 1 マス跳ぶ時間


EVENT_TIME = 1.7                                    # 出来事を見せる時間


CPU_WAIT = 0.9                                      # CPU が振るまでの間


FORK_WAIT = 0.9                                     # CPU が道を選ぶまでの間


PIECE_R = 0.4


RATE = 22050


VOLUME = 0.14


def tone(hz: float, seconds: float, volume: float = VOLUME) -> array:
    count = int(RATE * seconds)
    edge = RATE / 200
    samples = array("h")
    for i in range(count):
        fade = min(1.0, i / edge, (count - i) / edge)
        samples.append(int(32767 * volume * fade * math.sin(math.tau * hz * i / RATE)))
    return samples


def noise(seconds: float, volume: float, decay: float, seed: int = 1) -> array:
    luck = random.Random(seed)
    count = int(RATE * seconds)
    samples = array("h")
    for i in range(count):
        env = math.exp(-decay * i / RATE)
        samples.append(int(32767 * volume * env * luck.uniform(-1, 1)))
    return samples


def sound_bytes(kind: str) -> bytes:
    if kind == "dice":                              # サイコロが転がる（コロコロ）
        samples = sum((noise(0.05, VOLUME * 0.7, 80.0, i) + tone(300 + 40 * i, 0.02, VOLUME * 0.3) for i in range(5)), array("h"))
    elif kind == "hop":                             # コマが跳ぶ
        samples = tone(500, 0.03, VOLUME * 0.5) + tone(700, 0.04, VOLUME * 0.5)
    elif kind == "plus":
        samples = tone(880, 0.06) + tone(1175, 0.06) + tone(1568, 0.14)
    elif kind == "minus":
        samples = tone(400, 0.08, VOLUME * 0.8) + tone(300, 0.14, VOLUME * 0.8)
    elif kind == "card":
        samples = tone(660, 0.05) + tone(990, 0.05) + tone(660, 0.05) + tone(990, 0.1)
    elif kind == "treasure":
        samples = tone(784, 0.08) + tone(988, 0.08) + tone(1175, 0.08) + tone(1568, 0.3)
    elif kind == "rest":
        samples = tone(330, 0.15, VOLUME * 0.6) + tone(262, 0.25, VOLUME * 0.6)
    elif kind == "warp":                            # ワープ（上がる）
        samples = sum((tone(400 * (1.15 ** i), 0.04, VOLUME * 0.7) for i in range(8)), array("h"))
    elif kind == "ship":                            # 船（汽笛）
        samples = tone(220, 0.25, VOLUME * 0.9) + tone(220, 0.15, VOLUME * 0.9)
    elif kind == "janken":                          # じゃんけん（ポン）
        samples = tone(880, 0.05) + noise(0.06, VOLUME, 50.0, 2)
    elif kind == "volcano":                         # 火山（ドーン）
        samples = noise(0.5, VOLUME * 1.8, 6.0, 7) + tone(70, 0.4, VOLUME)
    elif kind == "shop":                            # 店（チャリン）
        samples = tone(1568, 0.04) + tone(2093, 0.1)
    elif kind == "goal":
        samples = tone(523, 0.1) + tone(659, 0.1) + tone(784, 0.1) + tone(1047, 0.35)
    elif kind == "best":
        samples = tone(523, 0.1) + tone(659, 0.1) + tone(784, 0.1) + tone(1047, 0.3)
    else:                                           # end
        samples = tone(784, 0.12) + tone(659, 0.12) + tone(523, 0.12) + tone(392, 0.4)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(samples.tobytes())
    return buffer.getvalue()


EVENTS = ("end", "goal", "volcano", "treasure", "warp", "ship", "janken", "shop", "card", "plus", "minus", "rest", "dice", "hop")   # 目立つ順


SOUNDS = EVENTS + ("best",)


GROUND_COLORS = {"sea": (40, 80, 150), "sand": (220, 200, 150), "grass": (90, 160, 80), "rock": (130, 120, 110), "snow": (240, 240, 245)}


def shade(color: tuple[int, int, int], k: float) -> tuple[int, int, int]:
    return tuple(max(0, min(255, int(c * k))) for c in color)


def catmull(points: list[tuple[float, float]], per: int = 12) -> list[tuple[float, float]]:
    """制御点を必ず通る滑らかな線（Catmull-Rom。g79 と同じ）。"""
    out = []
    pts = [points[0]] + list(points) + [points[-1]]
    for i in range(1, len(pts) - 2):
        p0, p1, p2, p3 = pts[i - 1], pts[i], pts[i + 1], pts[i + 2]
        for k in range(per):
            t = k / per
            t2, t3 = t * t, t * t * t
            x = 0.5 * ((2 * p1[0]) + (-p0[0] + p2[0]) * t + (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2 + (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3)
            z = 0.5 * ((2 * p1[1]) + (-p0[1] + p2[1]) * t + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2 + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3)
            out.append((x, z))
    out.append(points[-1])
    return out


def spaced(line: list[tuple[float, float]], count: int) -> list[tuple[float, float]]:
    """線の上に count 個の点を等間隔に置く。"""
    lengths = [0.0]
    for a, b in zip(line, line[1:]):
        lengths.append(lengths[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
    total = lengths[-1]
    out = []
    for i in range(count):
        want = total * i / (count - 1)
        j = 0
        while j < len(lengths) - 2 and lengths[j + 1] < want:
            j += 1
        span = lengths[j + 1] - lengths[j]
        t = (want - lengths[j]) / span if span > 0 else 0.0
        a, b = line[j], line[j + 1]
        out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    return out


@dataclass
class Square:
    index: int
    kind: str
    x: float
    z: float
    y: float
    next: list[int] = field(default_factory=list)   # 次のマス（分かれ道は 2 つ。先が近道）
    amount: int = 0
    name: str = ""
    side: bool = False                              # 近道のマスか
    taken: bool = False                             # 宝を取られた


def build_squares() -> list[Square]:
    """本道と近道のマスを作る。本道 0〜MAIN_COUNT-1、近道はその後ろに続く。"""
    squares = []
    plus_i = minus_i = 0
    for i, (x, z) in enumerate(spaced(catmull(MAIN_KNOTS), MAIN_COUNT)):
        kind = MAIN_LAYOUT[i]
        sq = Square(i, kind, x, z, max(SEA + 0.1, height(x, z)))
        if kind == "+":
            sq.amount, plus_i = PLUS[plus_i % len(PLUS)], plus_i + 1
        elif kind == "-":
            sq.amount, minus_i = MINUS[minus_i % len(MINUS)], minus_i + 1
        elif kind == "$":
            sq.amount = TREASURE
        elif kind == "B":
            sq.amount = SHIP_TO
        sq.name = KINDS[kind]["name"]
        if i + 1 < MAIN_COUNT:
            sq.next = [i + 1]
        squares.append(sq)
    side_points = spaced(catmull(SIDE_KNOTS), SIDE_COUNT + 2)[1:-1]
    for k, (x, z) in enumerate(side_points):
        i = MAIN_COUNT + k
        kind = SIDE_LAYOUT[k]
        sq = Square(i, kind, x, z, max(SEA + 0.1, height(x, z)), side=True)
        if kind == "+":
            sq.amount = 600
        elif kind == "-":
            sq.amount = (300, 500, 400)[k % 3]
        elif kind == "$":
            sq.amount = TREASURE
        sq.name = KINDS[kind]["name"]
        sq.next = [i + 1 if k + 1 < SIDE_COUNT else REJOIN_AT]
        squares.append(sq)
    squares[FORK_AT].next.append(MAIN_COUNT)        # 分かれ道：2 つ目が近道
    return squares


SQUARES = build_squares()


GOAL = MAIN_COUNT - 1


@dataclass
class Player:
    index: int
    name: str
    cpu: str | None
    color: tuple[int, int, int]
    at: int = 0                                     # いるマス
    money: int = START_MONEY
    skip: bool = False                              # 次の手番を休む
    done: bool = False                              # ゴールした
    goal_order: int = -1
    hop_from: int = 0                               # 跳んでいる途中の前のマス（見た目）
    treasures: int = 0                              # 見つけた宝の数


class Phase(Enum):
    ROLL = "roll"                                   # 振るのを待つ（人）／CPU の間
    MOVING = "moving"
    FORK = "fork"                                   # 道を選ぶ
    SHOP = "shop"                                   # 店：もう 1 回振るを買うか
    EVENT = "event"                                 # 出来事を見せる
    OVER = "over"


@dataclass
class Best:
    wins: int = 0
    games: int = 0
    money: int = 0

    def dump(self) -> str:
        return json.dumps({"wins": self.wins, "games": self.games, "money": self.money})

    @classmethod
    def parse(cls, text: str) -> "Best":
        try:
            d = json.loads(text)
            return cls(int(d.get("wins", 0)), int(d.get("games", 0)), int(d.get("money", 0)))
        except (ValueError, TypeError, AttributeError):
            return cls()

    def take(self, world: "World") -> bool:
        self.games += 1
        me = world.players[0]
        won = world.ranking()[0] is me
        self.wins += 1 if won else 0
        improved = me.money > self.money
        self.money = max(self.money, me.money)
        return improved


@dataclass
class World:
    seed: int = 0
    players: list[Player] = field(default_factory=lambda: [Player(i, p["name"], p["cpu"], p["color"]) for i, p in enumerate(PLAYERS)])
    squares: list[Square] = field(default_factory=build_squares)
    turn: int = 0
    phase: Phase = Phase.ROLL
    time: float = 0.0
    started: bool = False
    over: bool = False
    steps_left: int = 0
    hop_left: float = 0.0
    wait_left: float = 0.0                          # CPU が振る／選ぶまで、出来事を見せる間
    dice: int = 0                                   # 最後の出目
    rolls: int = 0
    note: str = ""
    note_until: float = 0.0
    log: list[str] = field(default_factory=list)
    goals: int = 0
    last_card: dict | None = None
    throw_wanted: bool = False                      # 人の番で、振るのを待っている（ブラウザがサイコロを出す合図）
    janken: tuple[str, str, str] | None = None      # 最後のじゃんけん（自分の手, 相手の手, 結果）
    money_delta: list[tuple[int, int]] = field(default_factory=list)   # 直近の出来事でのお金の増減 (誰, いくら)。見せる用
    delta_count: int = 0
    cards_drawn: int = 0

    def __post_init__(self):
        self.luck = random.Random(self.seed)
        self.begin_turn()

    # ── 手番 ──
    @property
    def player(self) -> Player:
        return self.players[self.turn]

    def tell(self, text: str, seconds: float = EVENT_TIME) -> None:
        self.note, self.note_until = text, self.time + seconds
        self.log.append(text)
        del self.log[:-8]

    def pay(self, player: Player, amount: int) -> None:
        """お金の増減。見せる用に記録もする（delta_count は通し番号）。"""
        player.money += amount
        self.delta_count += 1
        self.money_delta.append((player.index, amount))
        del self.money_delta[:-8]

    def cpu_shop(self) -> bool:
        p = self.player
        return p.money >= SHOP_PRICE and p.money > PERSONALITY[p.cpu]["shop_if"]

    def shop(self, buy: bool) -> str | None:
        """店：500 でもう 1 回振る。"""
        if self.phase != Phase.SHOP:
            return None
        p = self.player
        if buy and p.money >= SHOP_PRICE:
            self.pay(p, -SHOP_PRICE)
            self.phase = Phase.ROLL
            self.throw_wanted = p.cpu is None
            self.wait_left = CPU_WAIT if p.cpu else 0.0
            self.tell(f"{p.name}：{SHOP_PRICE} 払ってもう 1 回！", 1.2)
            return "shop"
        self.phase = Phase.EVENT
        self.wait_left = 0.6
        self.tell(f"{p.name}：店を素通り", 0.8)
        return None

    def begin_turn(self) -> None:
        """次の人へ。ゴール済みは飛ばす。休みなら消費して次へ。"""
        for _ in range(len(self.players)):
            self.turn = (self.turn + 1) % len(self.players) if self.rolls or self.turn else self.turn
            p = self.player
            if p.done:
                self.turn = (self.turn + 1) % len(self.players)
                continue
            if p.skip:
                p.skip = False
                self.tell(f"{p.name} は 1 回休み")
                self.turn = (self.turn + 1) % len(self.players)
                continue
            break
        else:
            return
        p = self.player
        self.phase = Phase.ROLL
        self.throw_wanted = p.cpu is None
        self.wait_left = CPU_WAIT if p.cpu else 0.0

    def next_turn(self) -> None:
        """いまの手番を終えて次の人へ（ゴール済みや休みを飛ばす）。"""
        n = len(self.players)
        for k in range(1, n + 1):
            i = (self.turn + k) % n
            p = self.players[i]
            if p.done:
                continue
            if p.skip:
                p.skip = False
                self.tell(f"{p.name} は 1 回休み")
                continue
            self.turn = i
            self.phase = Phase.ROLL
            self.throw_wanted = p.cpu is None
            self.wait_left = CPU_WAIT if p.cpu else 0.0
            return
        self.finish()

    def roll(self, value: int) -> str | None:
        """出目を受けて進み始める。端末と検査は乱数、ブラウザは物理のサイコロから。"""
        if self.phase != Phase.ROLL or self.over or not 1 <= value <= 6:
            return None
        self.dice = value
        self.rolls += 1
        self.steps_left = value
        self.throw_wanted = False
        self.player.hop_from = self.player.at
        self.phase = Phase.MOVING
        self.hop_left = HOP_TIME
        self.tell(f"{self.player.name}：{value} が出た", 1.2)
        return "dice"

    def roll_random(self) -> str | None:
        return self.roll(self.luck.randint(1, 6))

    def choose(self, which: int) -> str | None:
        """分かれ道で選ぶ（0 本道、1 近道）。"""
        if self.phase != Phase.FORK:
            return None
        sq = self.squares[self.player.at]
        self.player.hop_from = self.player.at
        self.player.at = sq.next[min(which, len(sq.next) - 1)]
        self.steps_left -= 1
        self.phase = Phase.MOVING
        self.hop_left = HOP_TIME
        self.tell(f"{self.player.name}：{'近道' if which else '本道'}を選んだ", 1.0)
        return "hop"

    def cpu_choice(self) -> int:
        """性格と順位で近道を選ぶか決める。"""
        p = self.player
        spec = PERSONALITY[p.cpu]
        behind = self.ranking().index(p) >= 2
        return 1 if self.luck.random() < (spec["side_behind"] if behind else spec["side"]) else 0

    def ranking(self) -> list[Player]:
        return sorted(self.players, key=lambda p: (-p.money, p.goal_order if p.done else 99, p.index))

    # ── 進める ──
    def update(self, dt: float) -> str | None:
        if not self.started or self.over:
            return None
        self.time += dt
        p = self.player
        if self.phase == Phase.ROLL:
            if p.cpu and self.wait_left > 0:
                self.wait_left -= dt
                if self.wait_left <= 0:
                    return self.roll_random()
            return None
        if self.phase == Phase.MOVING:
            self.hop_left -= dt
            if self.hop_left > 0:
                return None
            return self.hop()
        if self.phase == Phase.FORK:
            if p.cpu:
                self.wait_left -= dt
                if self.wait_left <= 0:
                    return self.choose(self.cpu_choice())
            return None
        if self.phase == Phase.SHOP:
            if p.cpu:
                self.wait_left -= dt
                if self.wait_left <= 0:
                    return self.shop(self.cpu_shop())
            return None
        if self.phase == Phase.EVENT:
            self.wait_left -= dt
            if self.wait_left <= 0:
                self.next_turn()
            return None
        return None

    def hop(self) -> str | None:
        """1 マス進む。分かれ道なら止まって選ぶ。ゴールに着いたら止まる。歩き終えたら出来事。"""
        p = self.player
        sq = self.squares[p.at]
        if self.steps_left <= 0:
            return self.land()
        if len(sq.next) > 1:
            self.phase = Phase.FORK
            self.wait_left = FORK_WAIT
            return None
        if not sq.next:
            return self.land()
        p.hop_from = p.at
        p.at = sq.next[0]
        self.steps_left -= 1
        self.hop_left = HOP_TIME
        if p.at == GOAL:
            self.steps_left = 0
        return "hop"

    def land(self) -> str | None:
        """止まったマスの出来事。"""
        p = self.player
        sq = self.squares[p.at]
        self.phase = Phase.EVENT
        self.wait_left = EVENT_TIME
        self.last_card = None
        if sq.kind == "G":
            p.done = True
            p.goal_order = self.goals
            bonus = GOAL_BONUS[min(self.goals, len(GOAL_BONUS) - 1)]
            self.goals += 1
            self.pay(p, bonus)
            self.tell(f"{p.name} がゴール！ {self.goals} 着 +{bonus}", 2.2)
            return "goal"
        if sq.kind == "+":
            self.pay(p, sq.amount)
            self.tell(f"{p.name}：{sq.name} +{sq.amount}")
            return "plus"
        if sq.kind == "-":
            self.pay(p, -sq.amount)
            self.tell(f"{p.name}：{sq.name} −{sq.amount}")
            return "minus"
        if sq.kind == "$":
            if sq.taken:
                self.tell(f"{p.name}：宝はもう無かった…")
                return None
            sq.taken = True
            p.treasures += 1
            self.pay(p, sq.amount)
            self.tell(f"{p.name}：宝を見つけた！ +{sq.amount}", 2.2)
            return "treasure"
        if sq.kind == "B":                          # 船：対岸へ（着いた先の出来事は起きない）
            p.hop_from = p.at
            p.at = sq.amount
            self.tell(f"{p.name}：船に乗って対岸へ（{sq.amount} へ）", 2.0)
            self.wait_left = 2.0
            return "ship"
        if sq.kind == "W":                          # ワープ：3〜7 マス先へ跳ぶ（跳んだ先の出来事は起きる）
            self.steps_left = self.luck.randint(*WARP_RANGE)
            self.phase = Phase.MOVING
            self.hop_left = HOP_TIME * 0.6
            self.tell(f"{p.name}：ワープ！ {self.steps_left} マス先へ", 1.5)
            return "warp"
        if sq.kind == "H":                          # 店：もう 1 回振るを買うか
            if p.money < SHOP_PRICE:
                self.tell(f"{p.name}：店に来たがお金が足りない", 1.0)
                self.wait_left = 1.0
                return None
            self.phase = Phase.SHOP
            self.wait_left = FORK_WAIT
            self.tell(f"{p.name}：店。{SHOP_PRICE} でもう 1 回振れる", 9)
            return "shop"
        if sq.kind == "J":                          # じゃんけん：一番近い人と 400 を賭ける
            others = [q for q in self.players if q is not p and not q.done]
            if not others:
                self.tell(f"{p.name}：相手がいない", 1.0)
                return None
            other = min(others, key=lambda q: abs(q.at - p.at))
            hands = ("グー", "チョキ", "パー")
            mine, theirs = self.luck.randrange(3), self.luck.randrange(3)
            if mine == theirs:
                self.janken = (hands[mine], hands[theirs], "あいこ")
                self.tell(f"{p.name} vs {other.name}：{hands[mine]} と {hands[theirs]} であいこ", 2.0)
            elif (mine - theirs) % 3 == 2:          # グー→チョキ、チョキ→パー、パー→グー に勝つ
                self.janken = (hands[mine], hands[theirs], "勝ち")
                self.pay(p, JANKEN_BET)
                self.pay(other, -JANKEN_BET)
                self.tell(f"{p.name} vs {other.name}：{hands[mine]} で勝ち！ +{JANKEN_BET}", 2.2)
            else:
                self.janken = (hands[mine], hands[theirs], "負け")
                self.pay(p, -JANKEN_BET)
                self.pay(other, JANKEN_BET)
                self.tell(f"{p.name} vs {other.name}：{hands[mine]} で負け… −{JANKEN_BET}", 2.2)
            self.wait_left = 2.2
            return "janken"
        if sq.kind == "V":                          # 火山：道の番号で近い人みんなが −300
            hit = [q for q in self.players if not q.done and abs(q.at - p.at) <= VOLCANO_RANGE or q is p]
            for q in hit:
                self.pay(q, -VOLCANO_DAMAGE)
            self.tell(f"{p.name}：火山が噴火！ " + "・".join(q.name for q in hit) + f" が −{VOLCANO_DAMAGE}", 2.4)
            self.wait_left = 2.4
            return "volcano"
        if sq.kind == "!":
            p.skip = True
            self.tell(f"{p.name}：1 回休み")
            return "rest"
        if sq.kind == "?":
            return self.draw_card()
        self.tell(f"{p.name}：何もなし", 1.0)
        self.wait_left = 0.8
        return None

    def draw_card(self) -> str | None:
        p = self.player
        card = self.luck.choice(CARDS)
        self.last_card = card
        self.cards_drawn += 1
        kind, amount = card["kind"], card["amount"]
        self.tell(f"{p.name}：カード「{card['name']}」 {card['text']}", 2.4)
        self.wait_left = 2.4
        if kind == "money":
            self.pay(p, amount)
        elif kind == "tax":
            for q in self.players:
                self.pay(q, -amount)
        elif kind == "steal":
            richest = max((q for q in self.players if q is not p), key=lambda q: q.money)
            self.pay(richest, -amount)
            self.pay(p, amount)
        elif kind == "give":
            for q in self.players:
                if q is not p:
                    self.pay(q, amount)
                    self.pay(p, -amount)
        elif kind == "push":                        # 先頭の人（自分以外）を戻す
            ahead = [q for q in self.players if q is not p and not q.done]
            if ahead:
                lead = max(ahead, key=lambda q: q.at if q.at < MAIN_COUNT else REJOIN_AT)
                for _ in range(amount):
                    back = [sq.index for sq in self.squares if lead.at in sq.next]
                    if back:
                        lead.at = back[0]
                self.tell(f"{p.name}：カード「押し戻し」 {lead.name} を {amount} マス戻した", 2.4)
        elif kind == "rob":
            rich = [q for q in self.players if q is not p and q.treasures > 0]
            if rich:
                victim = max(rich, key=lambda q: q.treasures)
                self.pay(victim, -amount)
                self.pay(p, amount)
                self.tell(f"{p.name}：カード「横取り」 {victim.name} から {amount} もらった", 2.4)
            else:
                self.tell(f"{p.name}：カード「横取り」 宝を持っている人がいない…", 2.0)
        elif kind == "rest":
            p.skip = True
        elif kind == "move":
            if amount > 0:
                self.steps_left = amount
                self.phase = Phase.MOVING
                self.hop_left = HOP_TIME * 1.5
            else:
                for _ in range(-amount):
                    back = [s.index for s in self.squares if p.at in s.next]
                    if back:
                        p.at = back[0]
        return "card"

    def finish(self) -> None:
        self.over = True
        self.phase = Phase.OVER
        order = self.ranking()
        self.tell("おわり：" + " ＞ ".join(f"{p.name} {p.money}" for p in order), 99)
# --- ここから下はブラウザ版だけ。CLI 版の draw() / run() / Speaker / status() にあたる ---
#   絵は Three.js、サイコロの転がりは Cannon-es（物理エンジン）。どちらも index.html が CDN から読み込んで window に置く。
#   Python は「どこに何を置くか」「サイコロをどう投げるか」「止まったら上の面を読む」だけを書く。

THREE = window.THREE
CANNON = window.CANNON
ADDONS = window.ADDONS
GSAP = getattr(window, "gsap", None)                # 動きの補間（ばね・ぽん）。無ければ動きは省く
TONE = getattr(window, "Tone", None)                # 音（BGM・サイコロの衝突・ファンファーレ）。無ければ wav だけ
VIEW_W, VIEW_H = 640, 480


def js(**kw):
    return to_js(kw, dict_converter=window.Object.fromEntries)


def rgb(color: tuple[int, int, int]) -> int:
    r, g, b = color
    return (r << 16) | (g << 8) | b


def linear(c: int) -> float:
    return (c / 255) ** 2.2


canvas = document.querySelector("#screen")
note_label = document.querySelector("#note")
message = document.querySelector("#message")
board_label = document.querySelector("#board")
dice_label = document.querySelector("#dice")
fps_label = document.querySelector("#fps")
best_label = document.querySelector("#best")
log_label = document.querySelector("#log")
go_button = document.querySelector("#go")
again_button = document.querySelector("#again")
fork_a = document.querySelector("#fork-a")
fork_b = document.querySelector("#fork-b")
shop_yes = document.querySelector("#shop-yes")
shop_no = document.querySelector("#shop-no")
SAVED = "g70-best"

# ── Three.js の舞台 ──────────────────────────────────────────────────────

renderer = THREE.WebGLRenderer.new(js(canvas=canvas, antialias=True))
PIXEL_RATIO = min(2.0, window.devicePixelRatio)
renderer.setPixelRatio(PIXEL_RATIO)
renderer.setSize(VIEW_W, VIEW_H, False)
renderer.toneMapping = THREE.ACESFilmicToneMapping
renderer.shadowMap.enabled = True
renderer.shadowMap.type = THREE.PCFSoftShadowMap
scene = THREE.Scene.new()
SKY = (150, 200, 240)
scene.background = THREE.Color.new(rgb(SKY))
scene.fog = THREE.Fog.new(rgb(SKY), 40, 90)
pmrem = THREE.PMREMGenerator.new(renderer)
scene.environment = pmrem.fromScene(ADDONS.RoomEnvironment.new(), 0.04).texture
scene.environmentIntensity = 0.35                   # 映り込みは控えめ（1.0 だと色が白く飛ぶ。g69 の学び）
camera = THREE.PerspectiveCamera.new(45, VIEW_W / VIEW_H, 0.5, 200)

sun = THREE.DirectionalLight.new(0xfff2dc, 2.2)
sun.position.set(18, 30, 14)
sun.castShadow = True
sun.shadow.mapSize.set(2048, 2048)
for name, value in (("left", -20), ("right", 20), ("top", 20), ("bottom", -20), ("near", 1), ("far", 80)):
    setattr(sun.shadow.camera, name, value)
sun.shadow.bias = -0.0008
scene.add(sun)
scene.add(THREE.HemisphereLight.new(0xbfd8ff, 0x3a5a2a, 0.9))


def build_terrain(n: int = 72) -> object:
    """島の地形。height() を格子で読んで三角形の板にする。色は ground() から（頂点色は線形に直す）。"""
    size = ISLAND_R * 2.4
    positions, colors, indices = [], [], []
    for j in range(n + 1):
        for i in range(n + 1):
            x = -size / 2 + size * i / n
            z = -size / 2 + size * j / n
            y = height(x, z)
            positions += [x, y, z]
            kind = ground(x, z)
            color = GROUND_COLORS[kind]
            k = 0.85 + 0.15 * math.sin(y * 3) if kind != "sea" else 0.8
            colors += [linear(int(c * k)) for c in color]
    for j in range(n):
        for i in range(n):
            a = j * (n + 1) + i
            b = a + 1
            c = a + n + 1
            d = c + 1
            indices += [a, c, b, b, c, d]
    geo = THREE.BufferGeometry.new()
    geo.setAttribute("position", THREE.Float32BufferAttribute.new(to_js(positions), 3))
    geo.setAttribute("color", THREE.Float32BufferAttribute.new(to_js(colors), 3))
    geo.setIndex(to_js(indices))
    geo.computeVertexNormals()
    mesh = THREE.Mesh.new(geo, THREE.MeshStandardMaterial.new(js(vertexColors=True, roughness=0.95, metalness=0.0)))
    mesh.receiveShadow = True
    return mesh


scene.add(build_terrain())
WAVE_N = 26                                         # 海：頂点を毎コマ揺らす（近くは細かく、遠くは板のまま）
water = THREE.Mesh.new(THREE.PlaneGeometry.new(90, 90, WAVE_N, WAVE_N),
                       THREE.MeshPhysicalMaterial.new(js(color=0x2f6fc0, roughness=0.15, metalness=0.1, transparent=True, opacity=0.86)))
water.rotation.x = -math.pi / 2
water.position.y = SEA
scene.add(water)
far_water = THREE.Mesh.new(THREE.PlaneGeometry.new(400, 400), THREE.MeshStandardMaterial.new(js(color=0x2a62b0, roughness=0.3)))
far_water.rotation.x = -math.pi / 2
far_water.position.y = SEA - 0.05
scene.add(far_water)
WAVE_BASE = []
_arr = water.geometry.attributes.position.array
for i in range(0, water.geometry.attributes.position.count * 3, 3):
    WAVE_BASE.append((_arr[i], _arr[i + 1]))


def ripple_water(now: float) -> None:
    flat = []
    for x, y in WAVE_BASE:
        flat += [x, y, 0.12 * math.sin(x * 0.8 + now * 1.6) + 0.08 * math.cos(y * 1.1 - now * 1.3)]
    water.geometry.attributes.position.array.set(to_js(flat))
    water.geometry.attributes.position.needsUpdate = True
    water.geometry.computeVertexNormals()

SQUARE_GEO = THREE.CylinderGeometry.new(0.55, 0.6, 0.16, 24)
square_mats = {k: THREE.MeshStandardMaterial.new(js(color=rgb(v["color"]), roughness=0.6)) for k, v in KINDS.items()}
square_meshes: dict[int, object] = {}
for sq in SQUARES:
    m = THREE.Mesh.new(SQUARE_GEO, square_mats[sq.kind])
    m.position.set(sq.x, sq.y + 0.08, sq.z)
    m.castShadow = True
    m.receiveShadow = True
    scene.add(m)
    square_meshes[sq.index] = m
    if sq.kind in "SG$":
        ring = THREE.Mesh.new(THREE.TorusGeometry.new(0.75, 0.06, 8, 32), THREE.MeshStandardMaterial.new(js(color=0xfff0b0, emissive=0xffcc60, emissiveIntensity=0.6)))
        ring.rotation.x = math.pi / 2
        ring.position.set(sq.x, sq.y + 0.2, sq.z)
        scene.add(ring)
for sq in SQUARES:                                  # 道：マスとマスを結ぶ薄い帯
    for n in sq.next:
        t = SQUARES[n]
        dx, dz = t.x - sq.x, t.z - sq.z
        length = math.hypot(dx, dz)
        band = THREE.Mesh.new(THREE.BoxGeometry.new(length, 0.06, 0.35), THREE.MeshStandardMaterial.new(js(color=0xc9b48a, roughness=0.9)))
        band.position.set((sq.x + t.x) / 2, (sq.y + t.y) / 2 + 0.03, (sq.z + t.z) / 2)
        band.rotation.y = -math.atan2(dz, dx)
        band.rotation.z = math.atan2(t.y - sq.y, length)
        scene.add(band)

tree_luck = random.Random(21)                       # 木：草の上、道から離れた所に
TRUNK = THREE.MeshStandardMaterial.new(js(color=0x7a5030, roughness=0.9))
LEAF = THREE.MeshStandardMaterial.new(js(color=0x2f8a48, roughness=0.8))
placed = 0
while placed < 70:
    x, z = tree_luck.uniform(-ISLAND_R, ISLAND_R), tree_luck.uniform(-ISLAND_R, ISLAND_R)
    if ground(x, z) != "grass" or min(math.hypot(x - s.x, z - s.z) for s in SQUARES) < 1.3:
        continue
    y = height(x, z)
    scale = tree_luck.uniform(0.7, 1.3)
    trunk = THREE.Mesh.new(THREE.CylinderGeometry.new(0.08, 0.12, 0.5 * scale, 6), TRUNK)
    trunk.position.set(x, y + 0.25 * scale, z)
    leaf = THREE.Mesh.new(THREE.ConeGeometry.new(0.45 * scale, 1.1 * scale, 7), LEAF)
    leaf.position.set(x, y + 0.9 * scale, z)
    leaf.castShadow = True
    scene.add(trunk)
    scene.add(leaf)
    placed += 1

LAMP_MAT = THREE.MeshStandardMaterial.new(js(color=0xfff0c0, emissive=0xffc060, emissiveIntensity=0.0))
lamps = []                                          # 街灯：夕方から点く（emissive を上げる）
for sq in SQUARES[::3]:
    pole = THREE.Mesh.new(THREE.CylinderGeometry.new(0.04, 0.05, 1.1, 6), TRUNK)
    pole.position.set(sq.x + 0.7, sq.y + 0.55, sq.z + 0.4)
    scene.add(pole)
    bulb = THREE.Mesh.new(THREE.SphereGeometry.new(0.13, 10, 8), LAMP_MAT)
    bulb.position.set(sq.x + 0.7, sq.y + 1.15, sq.z + 0.4)
    scene.add(bulb)
    lamps.append(bulb)

SPARKS = 260                                        # 粒（宝のきらめき・ゴールの花火・お金）
spark_geo = THREE.BufferGeometry.new()
spark_geo.setAttribute("position", THREE.Float32BufferAttribute.new(to_js([0.0, -99.0, 0.0] * SPARKS), 3))
spark_geo.setAttribute("color", THREE.Float32BufferAttribute.new(to_js([1.0, 1.0, 1.0] * SPARKS), 3))
sparks_points = THREE.Points.new(spark_geo, THREE.PointsMaterial.new(js(size=0.28, vertexColors=True, transparent=True, opacity=0.95)))
scene.add(sparks_points)
sparks: list[list[float]] = []                      # [x, y, z, vx, vy, vz, life, r, g, b]
fx_luck = random.Random(9)


def burst(x: float, y: float, z: float, count: int, color: tuple[int, int, int], speed: float = 4.0, up: float = 5.0) -> None:
    r, g, b = [c / 255 for c in color]
    for _ in range(count):
        a = fx_luck.uniform(0, math.tau)
        s = fx_luck.uniform(0.3, 1.0) * speed
        sparks.append([x, y, z, math.cos(a) * s, fx_luck.uniform(0.5, 1.0) * up, math.sin(a) * s, fx_luck.uniform(0.6, 1.4), r, g, b])


def age_sparks(dt: float) -> None:
    flat, colors = [], []
    for s in sparks:
        s[0] += s[3] * dt
        s[1] += s[4] * dt
        s[2] += s[5] * dt
        s[4] -= 9.0 * dt
        s[6] -= dt
    sparks[:] = [s for s in sparks if s[6] > 0][-SPARKS:]
    for s in sparks:
        flat += [s[0], s[1], s[2]]
        colors += [s[7], s[8], s[9]]
    flat += [0.0, -99.0, 0.0] * (SPARKS - len(sparks))
    colors += [1.0, 1.0, 1.0] * (SPARKS - len(sparks))
    spark_geo.attributes.position.array.set(to_js(flat))
    spark_geo.attributes.position.needsUpdate = True
    spark_geo.attributes.color.array.set(to_js(colors))
    spark_geo.attributes.color.needsUpdate = True


CLOUD_MAT = THREE.MeshStandardMaterial.new(js(color=0xffffff, roughness=1.0, transparent=True, opacity=0.9))
clouds = []                                         # 雲：影を落としながら流れる
for i in range(6):
    group = THREE.Group.new()
    for k in range(4):
        puff = THREE.Mesh.new(THREE.SphereGeometry.new(fx_luck.uniform(0.9, 1.6), 10, 8), CLOUD_MAT)
        puff.position.set(k * 1.3 - 2.0, fx_luck.uniform(-0.2, 0.3), fx_luck.uniform(-0.6, 0.6))
        puff.castShadow = True
        group.add(puff)
    group.position.set(fx_luck.uniform(-20, 20), fx_luck.uniform(9.0, 11.5), fx_luck.uniform(-14, 14))
    scene.add(group)
    clouds.append(group)

BIRD_MAT = THREE.MeshStandardMaterial.new(js(color=0x333340))
birds = []                                          # 鳥：2 枚の羽をぱたぱた。山の周りを回る
for i in range(8):
    group = THREE.Group.new()
    for side in (-1, 1):
        wing = THREE.Mesh.new(THREE.BoxGeometry.new(0.5, 0.03, 0.14), BIRD_MAT)
        wing.position.x = side * 0.25
        group.add(wing)
    scene.add(group)
    birds.append(group)

PEAK = (3.0, height(3.0, -3.5), -3.5)
SMOKE = 90
smoke_geo = THREE.BufferGeometry.new()
smoke_geo.setAttribute("position", THREE.Float32BufferAttribute.new(to_js([0.0, -99.0, 0.0] * SMOKE), 3))
smoke_points = THREE.Points.new(smoke_geo, THREE.PointsMaterial.new(js(color=0x8a8a90, size=0.9, transparent=True, opacity=0.35, sizeAttenuation=True)))
scene.add(smoke_points)
SMOKE_SEED = [(fx_luck.uniform(0, 1), fx_luck.uniform(0, math.tau)) for _ in range(SMOKE)]
smoke_boost = {"until": -9.0}


def scenery(now: float, progress: float) -> None:
    """雲・鳥・噴煙・海・昼から夜へ。progress は先頭の進み具合 0〜1。"""
    for i, c in enumerate(clouds):
        c.position.x += (0.35 + 0.05 * i) * STEP
        if c.position.x > 24:
            c.position.x = -24
    for i, b in enumerate(birds):
        a = now * (0.25 + 0.03 * i) + i * 0.8
        r = 7.0 + i * 0.6
        b.position.set(PEAK[0] + math.cos(a) * r, PEAK[1] + 4.0 + math.sin(now * 0.7 + i), PEAK[2] + math.sin(a) * r)
        b.rotation.y = -a
        flap = math.sin(now * 9 + i) * 0.7
        b.children[0].rotation.z = flap
        b.children[1].rotation.z = -flap
    flat = []
    big = now < smoke_boost["until"]
    for t0, a in SMOKE_SEED:
        t = (t0 + now * 0.12) % 1.0
        spread = (0.3 + t * 1.6) * (2.0 if big else 1.0)
        flat += [PEAK[0] + math.cos(a + now * 0.3) * spread * t, PEAK[1] + 0.6 + t * (7.0 if big else 4.5), PEAK[2] + math.sin(a + now * 0.3) * spread * t]
    smoke_geo.attributes.position.array.set(to_js(flat))
    smoke_geo.attributes.position.needsUpdate = True
    smoke_points.material.opacity = 0.7 if big else 0.35
    if int(now * 30) % 3 == 0:                      # 海は 3 コマに 1 回（毎コマだと重い）
        ripple_water(now)
    # 昼 → 夕 → 夜。太陽は下がり、空は橙から紺へ、街灯が点く
    t = max(0.0, min(1.0, progress))
    angle = math.radians(65 - 70 * t)
    sun.position.set(18 * math.cos(angle) + 4, 30 * math.sin(angle) + 3, 14)
    sun.intensity = 2.2 * max(0.15, math.sin(angle) + 0.2)
    sun.color.setRGB(1.0, 0.95 - 0.35 * t, 0.86 - 0.6 * t)
    sky = [(150, 200, 240), (250, 170, 110), (28, 30, 70)]
    seg = min(1, int(t * 2))
    k = t * 2 - seg
    a_, b_ = sky[seg], sky[seg + 1]
    color = tuple(int(a_[i] + (b_[i] - a_[i]) * k) for i in range(3))
    scene.background.setHex(rgb(color))
    scene.fog.color.setHex(rgb(color))
    LAMP_MAT.emissiveIntensity = 0.0 if t < 0.55 else min(2.5, (t - 0.55) * 8)
    for sq in SQUARES:                              # 宝のきらめき
        if sq.kind == "$" and not sq.taken and fx_luck.random() < 0.12:
            burst(sq.x, sq.y + 0.5, sq.z, 1, (255, 230, 120), 0.6, 1.5)


piece_meshes: list[object] = []                     # コマ：円錐の体に球の頭
for p in PLAYERS:
    group = THREE.Group.new()
    mat = THREE.MeshStandardMaterial.new(js(color=rgb(p["color"]), roughness=0.4, metalness=0.1))
    body = THREE.Mesh.new(THREE.ConeGeometry.new(PIECE_R, 0.9, 16), mat)
    body.position.y = 0.45
    body.castShadow = True
    head = THREE.Mesh.new(THREE.SphereGeometry.new(0.28, 16, 12), mat)
    head.position.y = 1.05
    head.castShadow = True
    group.add(body)
    group.add(head)
    scene.add(group)
    piece_meshes.append(group)
halo = THREE.Mesh.new(THREE.TorusGeometry.new(0.6, 0.05, 8, 32), THREE.MeshBasicMaterial.new(js(color=0xffffff)))
halo.rotation.x = math.pi / 2
scene.add(halo)

# ── サイコロの台と物理（Cannon-es） ─────────────────────────────────────

TRAY = (0.0, 1.2, ISLAND_R + 5.5)                   # 海に浮かぶ石の台（島の手前）
TRAY_HALF = 3.6
tray = THREE.Mesh.new(THREE.CylinderGeometry.new(TRAY_HALF + 0.6, TRAY_HALF + 1.0, 1.2, 40),
                      THREE.MeshStandardMaterial.new(js(color=0x5c6068, roughness=0.85)))
tray.position.set(TRAY[0], TRAY[1] - 0.6, TRAY[2])
tray.receiveShadow = True
scene.add(tray)
rim_mat = THREE.MeshStandardMaterial.new(js(color=0x3e4148, roughness=0.8))
for rx, rz, w, d in ((0, -TRAY_HALF, TRAY_HALF * 2 + 0.6, 0.3), (0, TRAY_HALF, TRAY_HALF * 2 + 0.6, 0.3), (-TRAY_HALF, 0, 0.3, TRAY_HALF * 2), (TRAY_HALF, 0, 0.3, TRAY_HALF * 2)):
    rim = THREE.Mesh.new(THREE.BoxGeometry.new(w, 0.5, d), rim_mat)
    rim.position.set(TRAY[0] + rx, TRAY[1] + 0.25, TRAY[2] + rz)
    rim.castShadow = True
    scene.add(rim)

phys = CANNON.World.new()
phys.gravity.set(0, -28, 0)
phys.defaultContactMaterial.friction = 0.35
phys.defaultContactMaterial.restitution = 0.35
floor = CANNON.Body.new(js(mass=0, shape=CANNON.Plane.new()))
floor.quaternion.setFromEuler(-math.pi / 2, 0, 0)
floor.position.set(0, TRAY[1], 0)
phys.addBody(floor)
for rx, rz, w, d in ((0, -TRAY_HALF, TRAY_HALF + 0.3, 0.15), (0, TRAY_HALF, TRAY_HALF + 0.3, 0.15), (-TRAY_HALF, 0, 0.15, TRAY_HALF), (TRAY_HALF, 0, 0.15, TRAY_HALF)):
    wall = CANNON.Body.new(js(mass=0, shape=CANNON.Box.new(CANNON.Vec3.new(w, 6.0, d))))   # 見えない高い壁（飛び出さない）
    wall.position.set(TRAY[0] + rx, TRAY[1] + 6.0, TRAY[2] + rz)
    phys.addBody(wall)


def pip_texture(value: int) -> object:
    """サイコロの面（canvas に丸を描く）。"""
    cv = document.createElement("canvas")
    cv.width = cv.height = 128
    ctx = cv.getContext("2d")
    ctx.fillStyle = "#f4f2ea"
    ctx.fillRect(0, 0, 128, 128)
    ctx.fillStyle = "#c0392b" if value == 1 else "#202028"
    spots = {1: [(64, 64)], 2: [(36, 36), (92, 92)], 3: [(36, 36), (64, 64), (92, 92)], 4: [(36, 36), (92, 36), (36, 92), (92, 92)],
             5: [(36, 36), (92, 36), (64, 64), (36, 92), (92, 92)], 6: [(36, 32), (92, 32), (36, 64), (92, 64), (36, 96), (92, 96)]}[value]
    for x, y in spots:
        ctx.beginPath()
        ctx.arc(x, y, 13 if value != 1 else 20, 0, math.tau)
        ctx.fill()
    tex = THREE.CanvasTexture.new(cv)
    tex.colorSpace = THREE.SRGBColorSpace
    return tex


PIP_MATS = [THREE.MeshStandardMaterial.new(js(map=pip_texture(v), roughness=0.4)) for v in range(1, 7)]
FACE_VALUES = [1, 6, 2, 5, 3, 4]                    # BoxGeometry の面の順（+x −x +y −y +z −z）に貼る目。向かい合う面の和は 7
FACE_NORMALS = [(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)]
DICE_SIZE = 1.6                                     # 大きめ（0.9 では台の上で見えないほど小さかった）
dice_mesh = THREE.Mesh.new(THREE.BoxGeometry.new(DICE_SIZE, DICE_SIZE, DICE_SIZE), to_js([PIP_MATS[v - 1] for v in FACE_VALUES]))
dice_mesh.castShadow = True
scene.add(dice_mesh)
dice_body = CANNON.Body.new(js(mass=1.0, shape=CANNON.Box.new(CANNON.Vec3.new(DICE_SIZE / 2, DICE_SIZE / 2, DICE_SIZE / 2))))
dice_body.position.set(TRAY[0], TRAY[1] + DICE_SIZE / 2, TRAY[2])
dice_body.angularDamping = 0.15
dice_body.linearDamping = 0.05
phys.addBody(dice_body)
dice_body.addEventListener("collide", create_proxy(lambda event: on_collide(event)))
dice = {"flying": False, "since": 0.0, "still": 0.0, "value": 0, "pending_cpu": False, "cpu_at": 0.0}
DICE_TIMEOUT = 4.5
DICE_STILL = 0.35


def throw_dice(vx: float, vz: float, power: float) -> None:
    """サイコロを投げる。台の中の、投げる向きの手前から。回転はでたらめ。"""
    luck = random.Random(int(window.performance.now()))
    start_x = TRAY[0] + max(-TRAY_HALF + 1, min(TRAY_HALF - 1, -vx * 0.25))     # 台の中に収める（台の中心からのずれで）
    start_z = TRAY[2] + max(-TRAY_HALF + 1, min(TRAY_HALF - 1, -vz * 0.25))
    dice_body.position.set(start_x, TRAY[1] + 2.0, start_z)
    dice_body.velocity.set(vx, 2.5 + power * 1.5, vz)
    dice_body.angularVelocity.set(luck.uniform(-18, 18), luck.uniform(-18, 18), luck.uniform(-18, 18))
    dice_body.quaternion.setFromEuler(luck.uniform(0, math.tau), luck.uniform(0, math.tau), luck.uniform(0, math.tau))
    dice_body.wakeUp()
    dice.update(flying=True, since=window.performance.now() / 1000, still=0.0, value=0)
    speaker.say("dice")


def top_face() -> int:
    """いま上を向いている面の目。各面の法線を回して、y が一番大きい面。"""
    best_value, best_y = 1, -9.0
    out = CANNON.Vec3.new()
    for (nx, ny, nz), value in zip(FACE_NORMALS, FACE_VALUES):
        dice_body.quaternion.vmult(CANNON.Vec3.new(nx, ny, nz), out)
        if out.y > best_y:
            best_y, best_value = out.y, value
    return best_value


def dice_step(dt: float) -> int | None:
    """物理を進め、止まったら目を返す。落ちたり時間切れなら投げ直す。"""
    if not dice["flying"]:
        return None
    phys.step(1 / 60, dt, 4)
    v = dice_body.velocity
    w = dice_body.angularVelocity
    speed = math.sqrt(v.x * v.x + v.y * v.y + v.z * v.z) + math.sqrt(w.x * w.x + w.y * w.y + w.z * w.z) * 0.3
    now = window.performance.now() / 1000
    if dice_body.position.y < TRAY[1] - 3:          # 台から落ちた（普通は壁で止まる）
        throw_dice(random.uniform(-3, 3), random.uniform(-3, 3), 1.0)
        return None
    if speed < 0.08:
        dice["still"] += dt
    else:
        dice["still"] = 0.0
    if dice["still"] >= DICE_STILL or now - dice["since"] > DICE_TIMEOUT:
        dice["flying"] = False
        dice["value"] = top_face()
        return dice["value"]
    return None


# ── 浮かぶ文字・カード・吹き出し（GSAP で動かす） ────────────────────────

def text_sprite(text: str, color: str, size: int = 72, width: int = 512, stroke: str = "rgba(20,10,40,0.85)") -> object:
    cv = document.createElement("canvas")
    cv.width, cv.height = width, 160
    ctx = cv.getContext("2d")
    ctx.font = f"bold {size}px sans-serif"
    ctx.textAlign = "center"
    ctx.textBaseline = "middle"
    ctx.lineWidth = 12
    ctx.strokeStyle = stroke
    ctx.strokeText(text, width / 2, 80)
    ctx.fillStyle = color
    ctx.fillText(text, width / 2, 80)
    tex = THREE.CanvasTexture.new(cv)
    tex.colorSpace = THREE.SRGBColorSpace
    sprite = THREE.Sprite.new(THREE.SpriteMaterial.new(js(map=tex, transparent=True, depthTest=False)))
    sprite.scale.set(width / 160 * 1.6, 1.6, 1)
    return sprite


def float_text(text: str, color: str, x: float, y: float, z: float, size: int = 72, seconds: float = 1.4) -> None:
    """文字がぽんと出て、上がりながら消える。"""
    sprite = text_sprite(text, color, size)
    sprite.position.set(x, y, z)
    scene.add(sprite)
    if GSAP is None:
        return
    sprite.scale.multiplyScalar(0.2)
    GSAP.to(sprite.scale, js(x=sprite.scale.x * 5, y=sprite.scale.y * 5, duration=0.35, ease="back.out(2)"))
    GSAP.to(sprite.position, js(y=y + 2.2, duration=seconds, ease="power1.out"))
    GSAP.to(sprite.material, js(opacity=0.0, duration=0.5, delay=seconds - 0.5, onComplete=create_proxy(lambda: scene.remove(sprite))))


def card_show(card: dict, x: float, y: float, z: float) -> None:
    """カードの板が裏返って名前と説明を見せる。"""
    cv = document.createElement("canvas")
    cv.width, cv.height = 256, 352
    ctx = cv.getContext("2d")
    ctx.fillStyle = "#fff8e6"
    ctx.fillRect(0, 0, 256, 352)
    ctx.strokeStyle = "#3b6f9c"
    ctx.lineWidth = 12
    ctx.strokeRect(10, 10, 236, 332)
    ctx.fillStyle = "#1f2328"
    ctx.textAlign = "center"
    ctx.font = "bold 40px sans-serif"
    ctx.fillText(card["name"], 128, 120)
    ctx.font = "26px sans-serif"
    words = card["text"]
    for i in range(0, len(words), 9):
        ctx.fillText(words[i:i + 9], 128, 200 + (i // 9) * 34)
    tex = THREE.CanvasTexture.new(cv)
    tex.colorSpace = THREE.SRGBColorSpace
    back = THREE.MeshStandardMaterial.new(js(color=0x3b6f9c, roughness=0.5))
    front = THREE.MeshStandardMaterial.new(js(map=tex, roughness=0.5))
    plane = THREE.Mesh.new(THREE.BoxGeometry.new(1.8, 2.5, 0.05), to_js([back, back, back, back, front, back]))
    plane.position.set(x, y + 1.0, z + 0.5)
    plane.rotation.y = math.pi
    scene.add(plane)
    if GSAP is None:
        window.setTimeout(create_proxy(lambda: scene.remove(plane)), 2200)
        return
    GSAP.to(plane.rotation, js(y=0.0, duration=0.6, ease="back.out(1.4)"))
    GSAP.to(plane.position, js(y=y + 2.6, duration=0.6, ease="power2.out"))
    GSAP.to(plane.position, js(y=y + 4.5, duration=0.6, delay=1.7, ease="power2.in", onComplete=create_proxy(lambda: scene.remove(plane))))


bubble = text_sprite("うーん…", "#ffffff", 64, 320, "rgba(40,40,60,0.9)")
bubble.visible = False
scene.add(bubble)


# ── 音（Tone.js）：BGM・サイコロの衝突・ファンファーレ ─────────────────────

music = {"on": False, "synth": None, "drum": None, "loop": None, "last_hit": 0.0, "step": 0}
CHORDS = (("C4", "E4", "G4"), ("A3", "C4", "E4"), ("F3", "A3", "C4"), ("G3", "B3", "D4"))


def music_start() -> None:
    """人が触った処理の中で呼ぶ（Safari の決まり）。BGM は 8 分音符の輪。"""
    if TONE is None or music["on"]:
        return
    try:
        TONE.start()
        synth = TONE.PolySynth.new(TONE.Synth).toDestination()
        synth.volume.value = -16
        drum = TONE.MembraneSynth.new().toDestination()
        drum.volume.value = -8
        music.update(synth=synth, drum=drum, on=True)
        transport = TONE.getTransport()

        def tick(time):
            step = music["step"]
            chord = CHORDS[(step // 8) % len(CHORDS)]
            note = chord[step % 3] if step % 8 != 7 else chord[0].replace("3", "4").replace("4", "5")
            try:
                synth.triggerAttackRelease(note, "16n", time)
            except Exception:
                pass
            music["step"] = step + 1

        music["loop"] = TONE.Loop.new(create_proxy(tick), "8n").start(0)
        transport.bpm.value = 92
        transport.start()
    except Exception:
        music["on"] = False


def music_tempo(rolls: int) -> None:
    if TONE is None or not music["on"]:
        return
    try:
        TONE.getTransport().bpm.value = min(150, 92 + rolls * 1.5)
    except Exception:
        pass


def fanfare(notes: tuple[str, ...]) -> None:
    if not music["on"]:
        return
    try:
        now = TONE.now()
        for i, n in enumerate(notes):
            music["synth"].triggerAttackRelease(n, "8n", now + i * 0.12)
    except Exception:
        pass


def on_collide(event):
    """サイコロが台や壁に当たった強さで音を鳴らす（連続は 0.06 秒に 1 回）。"""
    if not music["on"]:
        return
    try:
        impact = abs(event.contact.getImpactVelocityAlongNormal())
        now = TONE.now()
        if impact < 1.2 or now - music["last_hit"] < 0.06:
            return
        music["last_hit"] = now
        music["drum"].triggerAttackRelease("C2" if impact > 5 else "E2", "32n", now, min(1.0, impact / 10))
    except Exception:
        pass


# ── 世界とカメラ ──────────────────────────────────────────────────────────

class Speaker:
    def __init__(self):
        self.made = {}
        for kind in SOUNDS:
            uri = "data:audio/wav;base64," + base64.b64encode(sound_bytes(kind)).decode()
            self.made[kind] = window.Audio.new(uri)

    def say(self, kind: str | None) -> None:
        if kind is None:
            return
        sound = self.made[kind]
        sound.currentTime = 0
        sound.play()


speaker = Speaker()
world = World(seed=int(window.performance.now()))
best = Best.parse(window.localStorage.getItem(SAVED) or "")
improved = False
frames = []
cam = {"x": 0.0, "y": 26.0, "z": 30.0, "lx": 0.0, "ly": 0.0, "lz": 0.0, "focus_until": -9.0}
CAM_EASE = 0.06
OVERVIEW = ((0.0, 26.0, 30.0), (0.0, 0.0, 1.0))
seen = {"delta": 0, "cards": 0, "at": [0] * len(PLAYERS), "dice": 0, "rolls": 0, "goals": 0}
shown_money = [float(START_MONEY)] * len(PLAYERS)


def piece_pos(p: Player) -> tuple[float, float, float]:
    """コマの位置。跳んでいる途中は放物線。"""
    sq = world.squares[p.at]
    x, y, z = sq.x, sq.y, sq.z
    if world.phase == Phase.MOVING and p is world.player and world.hop_left > 0 and p.hop_from != p.at:
        f = world.squares[p.hop_from]
        t = 1 - world.hop_left / HOP_TIME
        x, z = f.x + (sq.x - f.x) * t, f.z + (sq.z - f.z) * t
        y = f.y + (sq.y - f.y) * t + 1.2 * math.sin(math.pi * t)
    return x, y, z


def effects(now: float) -> None:
    """世界の変化を見つけて演出を出す：お金の増減の文字、カードの板、着地のぷるん、出目、ゴールの花火。"""
    if world.delta_count != seen["delta"]:
        fresh = world.money_delta[-(world.delta_count - seen["delta"]):]
        seen["delta"] = world.delta_count
        for who, amount in fresh:
            x, y, z = piece_pos(world.players[who])
            float_text(f"+{amount}" if amount > 0 else f"−{-amount}", "#7ee29a" if amount > 0 else "#ff7b7b", x, y + 1.8, z, 80, 1.5)
            burst(x, y + 1.0, z, 8, (120, 230, 150) if amount > 0 else (255, 120, 120), 1.5, 2.5)
    if world.cards_drawn != seen["cards"] and world.last_card is not None:
        seen["cards"] = world.cards_drawn
        x, y, z = piece_pos(world.player)
        card_show(world.last_card, x, y, z)
    for i, p in enumerate(world.players):           # 着地のぷるん（マスが変わった瞬間）
        if p.at != seen["at"][i]:
            seen["at"][i] = p.at
            mesh = piece_meshes[i]
            if GSAP is not None:
                GSAP.fromTo(mesh.scale, js(x=1.35, y=0.65, z=1.35), js(x=1.0, y=1.0, z=1.0, duration=0.45, ease="elastic.out(1, 0.4)"))
    if world.rolls != seen["rolls"]:                # 出目：サイコロに寄って数字を出す
        seen["rolls"] = world.rolls
        cam["focus_until"] = now + 0.9
        float_text(f"{world.dice}!", "#ffe27a", dice_body.position.x, dice_body.position.y + 1.6, dice_body.position.z, 110, 1.1)
        music_tempo(world.rolls)
    if world.goals != seen["goals"]:                # ゴール：花火とファンファーレ
        seen["goals"] = world.goals
        g = world.squares[GOAL]
        for _ in range(3):
            burst(g.x + fx_luck.uniform(-1, 1), g.y + 2.5, g.z + fx_luck.uniform(-1, 1), 40, (255, fx_luck.randrange(120, 255), fx_luck.randrange(80, 255)), 5.0, 7.0)
        fanfare(("C5", "E5", "G5", "C6"))


def sync(dt: float) -> None:
    now = world.time
    effects(now)
    stacked: dict[int, int] = {}
    for i, p in enumerate(world.players):
        x, y, z = piece_pos(p)
        k = stacked.get(p.at, 0)                    # 同じマスなら少しずらす
        stacked[p.at] = k + 1
        ox, oz = ((-0.3, -0.3), (0.3, -0.3), (-0.3, 0.3), (0.3, 0.3))[k % 4]
        mesh = piece_meshes[i]
        mesh.position.set(x + ox, y + 0.1, z + oz)
        mesh.rotation.y = now * 0.6 if p is world.player else 0.0
        if p is world.player and not world.over:
            halo.position.set(x + ox, y + 0.15, z + oz)
            halo.visible = True
    if world.over:
        halo.visible = False
    for sq in world.squares:
        if sq.kind == "$":
            square_meshes[sq.index].material = square_mats["."] if sq.taken else square_mats["$"]
    dice_mesh.position.copy(dice_body.position)
    dice_mesh.quaternion.copy(dice_body.quaternion)
    lead = max((p.at if p.at < MAIN_COUNT else REJOIN_AT) for p in world.players)
    scenery(now, lead / GOAL)
    age_sparks(dt)
    if world.phase == Phase.ROLL and world.player.cpu and dice["pending_cpu"] and not dice["flying"]:   # CPU が考えている
        x, y, z = piece_pos(world.player)
        bubble.position.set(x, y + 2.4, z)
        bubble.visible = True
    else:
        bubble.visible = False
    for i, p in enumerate(world.players):           # 所持金の表示は数えるように追いつく
        shown_money[i] += (p.money - shown_money[i]) * 0.12
        if abs(p.money - shown_money[i]) < 1:
            shown_money[i] = float(p.money)
    if not world.started or world.over:
        want, look = OVERVIEW
    elif now < cam["focus_until"]:                  # 止まったサイコロにぐっと寄る
        d = dice_body.position
        want, look = (d.x + 2.2, d.y + 3.2, d.z + 3.0), (d.x, d.y, d.z)
    elif world.phase == Phase.ROLL or dice["flying"]:
        want, look = (TRAY[0], TRAY[1] + 8.0, TRAY[2] + 8.5), (TRAY[0], TRAY[1] + 0.5, TRAY[2] - 0.5)
    else:
        x, y, z = piece_pos(world.player)
        want, look = (x + 6.0, y + 9.0, z + 9.0), (x, y, z)
    ease = CAM_EASE * (2.5 if now < cam["focus_until"] else 1.0)
    for key, value in (("x", want[0]), ("y", want[1]), ("z", want[2]), ("lx", look[0]), ("ly", look[1]), ("lz", look[2])):
        cam[key] += (value - cam[key]) * ease
    camera.position.set(cam["x"], cam["y"], cam["z"])
    camera.lookAt(cam["lx"], cam["ly"], cam["lz"])


def refresh(dt: float = STEP) -> None:
    sync(dt)
    renderer.render(scene, camera)
    rows = []
    for p in world.ranking():
        mark = "👑" if p.done else ""
        rows.append(f'<span class="who" style="--c:#{rgb(p.color):06x}"></span>{p.name} <b>{int(round(shown_money[p.index]))}</b>{mark}'
                    + (" ◀" if p is world.player and not world.over else ""))
    board_label.innerHTML = " ・ ".join(rows)
    dice_label.textContent = str(world.dice) if world.dice else "–"
    best_label.textContent = f"{best.wins} 勝 / {best.games} 回（最高 {best.money}）"
    note_label.textContent = (world.note if world.time < world.note_until or world.over else "") or " "
    log_label.textContent = "\n".join(world.log[-4:])
    human = world.player.cpu is None and not world.over
    if world.over:
        order = world.ranking()
        place = order.index(world.players[0]) + 1
        message.textContent = f"おわり。あなたは {place} 位（{world.players[0].money}）。1 位は {order[0].name}" + ("  最高記録！" if improved else "")
    elif not world.started:
        message.textContent = "「スタート」で始める。あなたの番になったら、サイコロの台の上で指をはらって投げる（強さと向きが反映）"
    elif world.phase == Phase.ROLL and human and not dice["flying"]:
        message.textContent = "あなたの番：画面の上で指をはらってサイコロを投げる"
    elif world.phase == Phase.FORK and human:
        message.textContent = "分かれ道：本道か、山を越える近道（危険だが宝あり）か"
    elif world.phase == Phase.SHOP and human:
        message.textContent = f"店：{SHOP_PRICE} 払ってもう 1 回振る？"
    else:
        message.textContent = f"{world.player.name}の番" if not dice["flying"] else "サイコロが転がっている…"
    fork_a.hidden = fork_b.hidden = not (world.phase == Phase.FORK and human)
    shop_yes.hidden = shop_no.hidden = not (world.phase == Phase.SHOP and human)
    again_button.hidden = not world.over
    go_button.hidden = world.started


async def loop():
    global improved
    lag = 0.0
    last = window.performance.now() / 1000
    while True:
        now = window.performance.now() / 1000
        frame_dt = min(0.1, now - last)
        lag = min(lag + now - last, 0.25)
        last = now
        got = dice_step(frame_dt)
        if got:
            speaker.say(world.roll(got))
        p = world.player
        if world.started and not world.over and world.phase == Phase.ROLL and p.cpu and not dice["flying"]:
            world.wait_left = 1e9                   # CPU の出目も物理で決める：Python の乱数を止めて、少し待って投げる
            if not dice["pending_cpu"]:
                dice["pending_cpu"] = True
                dice["cpu_at"] = now + CPU_WAIT
            elif now >= dice["cpu_at"]:
                dice["pending_cpu"] = False
                luck = random.Random(int(now * 1000))
                throw_dice(luck.uniform(-4, 4), luck.uniform(-5, -1), luck.uniform(0.5, 1.5))
        while lag >= STEP:
            was_over = world.over
            event = world.update(STEP)
            if world.over and not was_over:
                improved = best.take(world)
                window.localStorage.setItem(SAVED, best.dump())
                event = "best" if improved else "end"
            if event == "volcano":
                smoke_boost["until"] = world.time + 3.0
                burst(PEAK[0], PEAK[1] + 1.0, PEAK[2], 60, (255, 90, 40), 4.0, 8.0)
            speaker.say(event)
            lag -= STEP
        refresh(frame_dt)
        frames.append(window.performance.now() / 1000)
        del frames[:-30]
        if len(frames) >= 2:
            fps_label.textContent = f"{(len(frames) - 1) / (frames[-1] - frames[0]):.0f}"
        spent = window.performance.now() / 1000 - now
        await asyncio.sleep(max(0.002, STEP - spent))


def wake_sound() -> None:
    if not wake_sound.done:
        wake_sound.done = True
        speaker.say("hop")


wake_sound.done = False


def begin() -> None:
    if not world.started:
        world.started = True


touch = {"x": 0.0, "y": 0.0, "t": 0.0, "down": False}


@when("pointerdown", "#screen")
def press(event):
    event.preventDefault()
    wake_sound()
    music_start()
    if not world.started:
        begin()
        refresh()
        return
    touch.update(x=event.clientX, y=event.clientY, t=window.performance.now(), down=True)


@when("pointerup", "#screen")
def release(event):
    if not touch["down"]:
        return
    touch["down"] = False
    if not (world.phase == Phase.ROLL and world.player.cpu is None and world.throw_wanted and not dice["flying"]):
        return
    dx = event.clientX - touch["x"]
    dy = event.clientY - touch["y"]
    held = max(0.05, (window.performance.now() - touch["t"]) / 1000)
    rect = canvas.getBoundingClientRect()
    k = 12.0 / rect.width                           # 画面の幅いっぱいはらうと 12 の速さ
    vx, vz = dx * k, dy * k                         # 画面の上（dy < 0）が奥（−z）
    power = min(2.0, math.hypot(dx, dy) / rect.width / held * 0.5)
    if math.hypot(vx, vz) < 1.0:                    # ほとんど動かしていなければ軽く放る
        vx, vz = random.uniform(-1.5, 1.5), -2.0
    throw_dice(max(-8, min(8, vx)), max(-8, min(8, vz)), power)
    refresh()


@when("keydown", "body")
def on_down(event):
    if event.key in (" ", "Enter"):
        event.preventDefault()
        if event.repeat:
            return
        wake_sound()
        if not world.started:
            begin()
        elif world.phase == Phase.ROLL and world.player.cpu is None and not dice["flying"]:
            throw_dice(random.uniform(-4, 4), random.uniform(-6, -2), 1.0)
        refresh()
    elif event.key in ("1", "ArrowLeft"):
        speaker.say(world.choose(0))
    elif event.key in ("2", "ArrowRight"):
        speaker.say(world.choose(1))


@when("click", "#fork-a")
def pick_a(event):
    speaker.say(world.choose(0))
    refresh()


@when("click", "#fork-b")
def pick_b(event):
    speaker.say(world.choose(1))
    refresh()


@when("click", "#shop-yes")
def buy(event):
    speaker.say(world.shop(True))
    refresh()


@when("click", "#shop-no")
def skip(event):
    speaker.say(world.shop(False))
    refresh()


@when("click", "#go")
def go(event):
    wake_sound()
    music_start()
    begin()
    go_button.blur()
    refresh()


@when("click", "#again")
def again(event):
    global world, improved
    world = World(seed=int(window.performance.now()))
    world.started = True
    improved = False
    dice.update(flying=False, pending_cpu=False)
    seen.update(delta=0, cards=0, at=[0] * len(PLAYERS), rolls=0, goals=0)
    for i in range(len(PLAYERS)):
        shown_money[i] = float(START_MONEY)
    refresh()


refresh()
document.querySelector("#loading").hidden = True
asyncio.ensure_future(loop())
