"""アイランド・ダイス（サイコロで進む 3D ボードゲーム）

島をうねうね進む一本道（分かれ道つき）。サイコロを振ってコマを進め、止まったマスでお金が増えたり減ったり、
カードを引いたり。自分 ＋ CPU 3 人。全員がゴールしたら所持金で順位。
今回の主題は「中身は Python、コマとサイコロの動きは Cannon-es（物理）、絵は Three.js」の 3 層。端末は上から見た島の地図。
今回覚えるところ：
  マスは表と道の網    SQUARES は 1 マス 1 行（名前・種類・額）。next で次のマスを指す。分かれ道は next が 2 つ
  手番の状態機械      ROLL → MOVING（1 マスずつ跳ぶ）→ FORK（選ぶ）→ EVENT（見せる）→ 次の人。CPU は待ち時間つき
  出目は外から渡す    world.roll(value)。端末と検査は乱数、ブラウザは物理で転がったサイコロの上の面を読んで渡す
  地形は式            height(x, z) で島の高さ。端末の地図もブラウザの地形も同じ式から
  性格つきの CPU      分かれ道とカードの判断を性格（堅実・賭け・いじわる）の表で変える

    python3 main.py            遊ぶ（スペースで振る。分かれ道は 1 か 2。q でやめる）
    python3 main.py --check    決まりを確かめる
    python3 main.py --sheet    遊んでいる場面を PNG に書き出す
"""

import io
import json
import math
import os
import random
import select
import sys
import time
import unicodedata
import wave
from array import array
from dataclasses import dataclass, field
from enum import Enum

# ── 島とマス ────────────────────────────────────────────────────────────

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


# 道の制御点（島の中をうねうね）。Catmull-Rom で滑らかにして、等間隔にマスを置く
MAIN_KNOTS = [(-9.5, 7.0), (-8.0, 3.0), (-4.5, 2.0), (-3.0, -2.0), (-6.0, -5.5), (-2.5, -8.5), (2.0, -8.0), (4.5, -5.0),
              (7.5, -3.0), (8.5, 1.0), (5.5, 4.0), (1.5, 5.5), (-1.5, 8.5), (3.0, 9.5), (7.5, 8.0), (10.0, 4.5)]
SIDE_KNOTS = [(-3.0, -2.0), (0.5, -3.0), (3.5, -1.0), (7.5, -3.0)]     # 分かれ道：山を越える近道（危険）
MAIN_COUNT = 38                                     # 本道のマスの数（スタートとゴールを含む）
SIDE_COUNT = 6                                      # 近道のマスの数（分岐と合流を除く）
FORK_AT = 4                                         # 本道の何番目で分かれるか
REJOIN_AT = 15                                      # 本道の何番目に戻るか

# マスの並び（文字 1 つ = 1 マス）。S スタート G ゴール + お金が増える - 減る ? カード ! 休み $ 宝（最初の 1 人だけ）. 何もない
MAIN_LAYOUT = "S+.?-+.?.+-!?+.-?+.$-.?+.-+?.-!+?.-+.G"
SIDE_LAYOUT = "-?-$-+"
assert len(MAIN_LAYOUT) == MAIN_COUNT and len(SIDE_LAYOUT) == SIDE_COUNT

KINDS = {
    "S": dict(name="スタート", color=(240, 240, 240)),
    "G": dict(name="ゴール", color=(255, 220, 90)),
    "+": dict(name="お金が増える", color=(90, 200, 120)),
    "-": dict(name="お金が減る", color=(230, 90, 90)),
    "?": dict(name="カード", color=(90, 150, 240)),
    "!": dict(name="1 回休み", color=(160, 160, 170)),
    "$": dict(name="宝", color=(255, 170, 60)),
    ".": dict(name="", color=(200, 190, 160)),
}
PLUS = (300, 400, 500, 600, 800)                    # + のマスの額（順に回す）
MINUS = (200, 300, 400, 500)
TREASURE = 1500
GOAL_BONUS = (3000, 2000, 1000, 500)                # ゴールした順
START_MONEY = 1000

# カード。effect は (world, player) → 出来事の文。self.luck を使うので順は種で決まる
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
)

PLAYERS = (
    dict(name="あなた", cpu=None, color=(70, 140, 240)),
    dict(name="タケシ", cpu="steady", color=(90, 200, 110)),
    dict(name="ミカ", cpu="gambler", color=(240, 110, 160)),
    dict(name="ゴロウ", cpu="mean", color=(240, 170, 60)),
)
# 性格：分かれ道で近道を選ぶ確率（順位で変わる）
PERSONALITY = {
    "steady": dict(word="堅実", side=0.15, side_behind=0.35),
    "gambler": dict(word="賭け", side=0.8, side_behind=0.95),
    "mean": dict(word="いじわる", side=0.4, side_behind=0.7),
}
HOP_TIME = 0.28                                     # 1 マス跳ぶ時間
EVENT_TIME = 1.7                                    # 出来事を見せる時間
CPU_WAIT = 0.9                                      # CPU が振るまでの間
FORK_WAIT = 0.9                                     # CPU が道を選ぶまでの間
PIECE_R = 0.4

# 端末の板
WIDTH = 120
HEIGHT = 80
MAP_W = 84                                          # 左に地図、右に所持金の表
MAP_SCALE = MAP_W / (ISLAND_R * 2.2)                # 世界の単位 → ドット

# ── 音 ──────────────────────────────────────────────────────────────────

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


EVENTS = ("end", "goal", "treasure", "card", "plus", "minus", "rest", "dice", "hop")   # 目立つ順
SOUNDS = EVENTS + ("best",)

# ── 板 ──────────────────────────────────────────────────────────────────

GROUND_COLORS = {"sea": (40, 80, 150), "sand": (220, 200, 150), "grass": (90, 160, 80), "rock": (130, 120, 110), "snow": (240, 240, 245)}
PANEL = (24, 24, 40)
INK = (220, 220, 235)
DIM = (130, 130, 150)


def shade(color: tuple[int, int, int], k: float) -> tuple[int, int, int]:
    return tuple(max(0, min(255, int(c * k))) for c in color)


FONT = {
    "0": ("###", "#.#", "#.#", "#.#", "###"), "1": (".#.", "##.", ".#.", ".#.", "###"),
    "2": ("###", "..#", "###", "#..", "###"), "3": ("###", "..#", "###", "..#", "###"),
    "4": ("#.#", "#.#", "###", "..#", "..#"), "5": ("###", "#..", "###", "..#", "###"),
    "6": ("###", "#..", "###", "#.#", "###"), "7": ("###", "..#", "..#", "..#", "..#"),
    "8": ("###", "#.#", "###", "#.#", "###"), "9": ("###", "#.#", "###", "..#", "###"),
    "-": ("...", "...", "###", "...", "..."), "+": ("...", ".#.", "###", ".#.", "..."), " ": ("...", "...", "...", "...", "..."),
}


class Screen:
    def __init__(self, width: int = WIDTH, height: int = HEIGHT):
        self.width, self.height = width, height
        self.rows = [bytearray(width * 3) for _ in range(height)]

    def box(self, x0: int, y0: int, w: int, h: int, color: tuple[int, int, int]) -> None:
        paint = bytes(color)
        x0, x1 = max(0, x0), min(self.width, x0 + w)
        if x1 <= x0:
            return
        for y in range(max(0, y0), min(self.height, y0 + h)):
            self.rows[y][x0 * 3:x1 * 3] = paint * (x1 - x0)

    def ellipse(self, cx: float, cy: float, rx: float, ry: float, color: tuple[int, int, int]) -> None:
        for y in range(int(cy - ry), int(cy + ry) + 1):
            t = (y - cy) / ry
            if abs(t) > 1:
                continue
            half = rx * math.sqrt(1 - t * t)
            self.box(int(cx - half), y, int(2 * half) + 1, 1, color)

    def text(self, text: str, x: int, y: int, color: tuple[int, int, int], size: int = 1) -> None:
        for i, ch in enumerate(text):
            for row, line in enumerate(FONT.get(ch, FONT[" "])):
                for col, dot in enumerate(line):
                    if dot == "#":
                        self.box(x + i * 4 * size + col * size, y + row * size, size, size, color)

    def pixel(self, x: int, y: int) -> tuple[int, int, int]:
        return tuple(self.rows[y][x * 3:x * 3 + 3])

    def copy_from(self, other: "Screen") -> None:
        for y in range(self.height):
            self.rows[y][:] = other.rows[y]

    def render(self) -> str:
        out = []
        for top, bottom in zip(self.rows[0::2], self.rows[1::2]):
            last = None
            for x in range(self.width):
                a, b = top[x * 3:x * 3 + 3], bottom[x * 3:x * 3 + 3]
                code = f"\x1b[38;2;{a[0]};{a[1]};{a[2]}m\x1b[48;2;{b[0]};{b[1]};{b[2]}m"
                if code != last:
                    out.append(code)
                    last = code
                out.append("▀")
            out.append("\x1b[0m\n")
        return "".join(out)


# ── 道を作る ────────────────────────────────────────────────────────────

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

# ── 遊ぶ人と世界 ───────────────────────────────────────────────────────

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


class Phase(Enum):
    ROLL = "roll"                                   # 振るのを待つ（人）／CPU の間
    MOVING = "moving"
    FORK = "fork"                                   # 道を選ぶ
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
            p.money += bonus
            self.tell(f"{p.name} がゴール！ {self.goals} 着 +{bonus}", 2.2)
            return "goal"
        if sq.kind == "+":
            p.money += sq.amount
            self.tell(f"{p.name}：{sq.name} +{sq.amount}")
            return "plus"
        if sq.kind == "-":
            p.money -= sq.amount
            self.tell(f"{p.name}：{sq.name} −{sq.amount}")
            return "minus"
        if sq.kind == "$":
            if sq.taken:
                self.tell(f"{p.name}：宝はもう無かった…")
                return None
            sq.taken = True
            p.money += sq.amount
            self.tell(f"{p.name}：宝を見つけた！ +{sq.amount}", 2.2)
            return "treasure"
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
        kind, amount = card["kind"], card["amount"]
        self.tell(f"{p.name}：カード「{card['name']}」 {card['text']}", 2.4)
        self.wait_left = 2.4
        if kind == "money":
            p.money += amount
        elif kind == "tax":
            for q in self.players:
                q.money -= amount
        elif kind == "steal":
            richest = max((q for q in self.players if q is not p), key=lambda q: q.money)
            richest.money -= amount
            p.money += amount
        elif kind == "give":
            for q in self.players:
                if q is not p:
                    q.money += amount
                    p.money -= amount
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


# ── 描く（端末：上から見た島） ──────────────────────────────────────────

def map_xy(x: float, z: float) -> tuple[float, float]:
    """世界の (x, z) → 地図のドット。"""
    return MAP_W / 2 + x * MAP_SCALE, HEIGHT / 2 + z * MAP_SCALE


_TERRAIN: dict[int, Screen] = {}


def terrain(scale: int) -> Screen:
    """島の地図（静止画）。描くのは最初の 1 回だけ。"""
    if scale not in _TERRAIN:
        base = Screen(WIDTH * scale, HEIGHT * scale)
        base.box(0, 0, base.width, base.height, PANEL)
        for py in range(HEIGHT * scale):
            for px in range(MAP_W * scale):
                x = (px / scale - MAP_W / 2) / MAP_SCALE
                z = (py / scale - HEIGHT / 2) / MAP_SCALE
                kind = ground(x, z)
                color = GROUND_COLORS[kind]
                if kind not in ("sea",):
                    color = shade(color, 0.85 + 0.15 * math.sin(height(x, z) * 3))
                base.rows[py][px * 3:px * 3 + 3] = bytes(color)
        for sq in SQUARES:                          # 道
            for n in sq.next:
                nx, ny = map_xy(SQUARES[n].x, SQUARES[n].z)
                mx, my = map_xy(sq.x, sq.z)
                for k in range(8):
                    t = k / 8
                    base.box(int((mx + (nx - mx) * t) * scale), int((my + (ny - my) * t) * scale), scale, scale, (120, 100, 70))
        _TERRAIN[scale] = base
    return _TERRAIN[scale]


def draw(screen: Screen, world: World) -> None:
    scale = screen.width // WIDTH
    screen.copy_from(terrain(scale))
    for sq in world.squares:                        # マス
        mx, my = map_xy(sq.x, sq.z)
        color = KINDS[sq.kind]["color"]
        if sq.kind == "$" and sq.taken:
            color = shade(color, 0.5)
        r = (2.2 if sq.kind in "SG$" else 1.6) * scale
        screen.ellipse(mx * scale, my * scale, r, r, shade(color, 0.6))
        screen.ellipse(mx * scale, my * scale, r * 0.7, r * 0.7, color)
    for i, p in enumerate(world.players):           # コマ（同じマスなら少しずらす）
        sq = world.squares[p.at]
        x, z = sq.x, sq.z
        if world.phase == Phase.MOVING and p is world.player and world.hop_left > 0:
            f = world.squares[p.hop_from]
            t = 1 - world.hop_left / HOP_TIME
            x, z = f.x + (sq.x - f.x) * t, f.z + (sq.z - f.z) * t
        mx, my = map_xy(x, z)
        ox, oy = ((-1, -1), (1, -1), (-1, 1), (1, 1))[i]
        cx, cy = (mx + ox * 1.2) * scale, (my + oy * 1.2) * scale
        r = 1.5 * scale
        if p is world.player and not world.over:
            screen.ellipse(cx, cy, r + scale, r + scale, (255, 255, 255))
        screen.ellipse(cx, cy, r, r, p.color)
    px = (MAP_W + 2) * scale                        # 右の表：所持金
    screen.box(px, 0, (WIDTH - MAP_W - 2) * scale, HEIGHT * scale, PANEL)
    for i, p in enumerate(world.ranking()):
        y = (3 + i * 12) * scale
        screen.ellipse(px + 3 * scale, y + 3 * scale, 2 * scale, 2 * scale, p.color)
        screen.text(f"{p.money}", px + 7 * scale, y, INK if not p.done else (255, 220, 90), scale)
        screen.text(f"{p.at if not p.done else 99}", px + 7 * scale, y + 6 * scale, DIM, scale)
    if world.dice:                                  # サイコロの目（右下）
        d = px + 4 * scale
        dy = (HEIGHT - 16) * scale
        screen.box(d, dy, 12 * scale, 12 * scale, (240, 240, 240))
        pips = {1: [(6, 6)], 2: [(3, 3), (9, 9)], 3: [(3, 3), (6, 6), (9, 9)], 4: [(3, 3), (9, 3), (3, 9), (9, 9)],
                5: [(3, 3), (9, 3), (6, 6), (3, 9), (9, 9)], 6: [(3, 3), (9, 3), (3, 6), (9, 6), (3, 9), (9, 9)]}[world.dice]
        for ox, oy in pips:
            screen.ellipse(d + ox * scale, dy + oy * scale, 1.2 * scale, 1.2 * scale, (30, 30, 40))


# ── 端末 ────────────────────────────────────────────────────────────────

def read_keys(fd: int) -> list[str]:
    keys = []
    while select.select([fd], [], [], 0)[0]:
        text = os.read(fd, 64).decode(errors="ignore")
        for ch in text:
            if ch in (" ", "\r", "\n"):
                keys.append("go")
            elif ch in ("1", "2"):
                keys.append("fork" + ch)
            elif ch in ("q", "\x1b"):
                keys.append("quit")
    return keys


def obey(world: World, key: str) -> str | None:
    if key == "go":
        if not world.started:
            world.started = True
            return None
        if world.phase == Phase.ROLL and world.player.cpu is None:
            return world.roll_random()
        return None
    if key.startswith("fork") and world.player.cpu is None:
        return world.choose(int(key[4]) - 1)
    return None


class Speaker:
    def __init__(self):
        import shutil
        import tempfile

        self.player = shutil.which("afplay") or shutil.which("aplay")
        self.folder = tempfile.mkdtemp(prefix="dice-")
        self.paths = {}
        for kind in SOUNDS:
            path = os.path.join(self.folder, f"{kind}.wav")
            with open(path, "wb") as out:
                out.write(sound_bytes(kind))
            self.paths[kind] = path

    def say(self, kind: str | None) -> None:
        import subprocess

        if kind is None or self.player is None:
            return
        subprocess.Popen([self.player, self.paths[kind]], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def close(self) -> None:
        import shutil

        shutil.rmtree(self.folder, ignore_errors=True)


RECORDS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "records.json")


def load_best() -> Best:
    try:
        with open(RECORDS, encoding="utf-8") as src:
            return Best.parse(src.read())
    except OSError:
        return Best()


def save_best(best: Best) -> None:
    with open(RECORDS, "w", encoding="utf-8") as out:
        out.write(best.dump())


def columns(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def status(world: World, best: Best, improved: bool = False) -> str:
    note = world.note if world.time < world.note_until or world.over else ""
    if not world.started:
        note, tail = "スペースで始める", "スペースで振る、分かれ道は 1（本道）2（近道）、q でやめる"
    elif world.over:
        tail = f"{best.wins}/{best.games} 勝 スペースでもう一度"
    elif world.phase == Phase.ROLL and world.player.cpu is None:
        note, tail = "あなたの番：スペースで振る", ""
    elif world.phase == Phase.FORK and world.player.cpu is None:
        note, tail = "分かれ道：1 本道 ／ 2 近道（山越え、危険だが宝あり）", ""
    else:
        tail = f"{world.player.name}の番"
    head = f" {world.rolls:3d} 手 "
    room = WIDTH - columns(head) - columns(tail) - 1
    while columns(note) > room:
        note = note[:-1]
    return head + note + " " * (room - columns(note) + 1) + tail


def run() -> None:
    import termios
    import tty

    world = World(seed=int(time.time()))
    best = load_best()
    improved = False
    screen = Screen()
    speaker = Speaker()
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        sys.stdout.write("\x1b[2J\x1b[?25l")
        last = time.perf_counter()
        lag = 0.0
        while True:
            now = time.perf_counter()
            for key in read_keys(fd):
                if key == "quit":
                    return
                if key == "go" and world.over:
                    world = World(seed=int(time.time()))
                    world.started = True
                    improved = False
                else:
                    speaker.say(obey(world, key))
            lag = min(lag + now - last, 0.25)
            last = now
            while lag >= STEP:
                was_over = world.over
                event = world.update(STEP)
                if world.over and not was_over:
                    improved = best.take(world)
                    save_best(best)
                    event = "best" if improved else "end"
                speaker.say(event)
                lag -= STEP
            draw(screen, world)
            sys.stdout.write("\x1b[H" + screen.render() + status(world, best, improved) + "\x1b[K")
            sys.stdout.flush()
            time.sleep(max(0.0, STEP - (time.perf_counter() - now)))
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
        sys.stdout.write("\x1b[?25h\x1b[2J\x1b[H")
        speaker.close()


# ── 確かめる ────────────────────────────────────────────────────────────

def autopilot(world: World) -> str | None:
    """人の番を自動で：振る、分かれ道は 2 位以下なら近道。"""
    if world.player.cpu is not None:
        return None
    if world.phase == Phase.ROLL:
        return world.roll_random()
    if world.phase == Phase.FORK:
        return world.choose(1 if world.ranking().index(world.player) >= 2 else 0)
    return None


def play_out(world: World, limit: float = 600.0) -> dict[str, int]:
    counts = {k: 0 for k in EVENTS}
    world.started = True
    while not world.over and world.time < limit:
        got = autopilot(world)
        if got:
            counts[got] += 1
        got = world.update(STEP)
        if got:
            counts[got] += 1
    return counts


def until(world: World, frames: int = 120) -> str | None:
    for _ in range(frames):
        got = world.update(STEP)
        if got:
            return got
    return None


def check() -> None:
    print("● 島とマス")
    assert height(0, 0) > 2 and height(ISLAND_R + 1, 0) <= 0 and ground(0, 0) in ("grass", "rock", "snow") and ground(ISLAND_R, 0) == "sea"
    assert height(3, -3.5) > height(-3, 3.5) + 2, "山は右下"
    sq = SQUARES
    assert len(sq) == MAIN_COUNT + SIDE_COUNT and sq[0].kind == "S" and sq[GOAL].kind == "G"
    assert sq[FORK_AT].next == [FORK_AT + 1, MAIN_COUNT] and sq[MAIN_COUNT + SIDE_COUNT - 1].next == [REJOIN_AT]
    assert all(s.y >= SEA + 0.1 for s in sq), "マスは海の上に出ている"
    gaps = [math.hypot(a.x - b.x, a.z - b.z) for a, b in zip(sq[:GOAL], sq[1:GOAL + 1])]
    assert max(gaps) / min(gaps) < 1.5, "本道のマスはだいたい等間隔"
    assert sum(1 for s in sq if s.kind == "$") == 2 and sum(1 for s in sq if s.kind == "?") >= 8
    print(f"  本道 {MAIN_COUNT} マス（分岐 {FORK_AT} → 合流 {REJOIN_AT}）、近道 {SIDE_COUNT} マス。間隔 {min(gaps):.2f}〜{max(gaps):.2f}。"
          f"＋{sum(1 for s in sq if s.kind == '+')} −{sum(1 for s in sq if s.kind == '-')} ？{sum(1 for s in sq if s.kind == '?')} 宝 2 休み {sum(1 for s in sq if s.kind == '!')}")

    print("● 手番の状態機械")
    world = World(seed=1)
    world.started = True
    assert world.turn == 0 and world.phase == Phase.ROLL and world.throw_wanted, "最初はあなたの番"
    assert world.roll(7) is None and world.roll(0) is None
    assert world.roll(3) == "dice" and world.phase == Phase.MOVING and world.steps_left == 3
    hops = 0
    while world.phase == Phase.MOVING:
        if until(world, 20) == "hop":
            hops += 1
    assert hops == 3 and world.players[0].at == 3 and world.phase == Phase.EVENT, (hops, world.players[0].at, world.phase)
    kind = world.squares[3].kind
    assert kind == "?" and world.last_card is not None
    got = until(world, 200)                         # 出来事を見せる 2.4 秒 → タケシの番 → 0.9 秒後に振る
    assert world.turn == 1 and world.player.cpu == "steady" and not world.throw_wanted, "次はタケシ"
    assert got == "dice" and world.dice in range(1, 7) and world.time > 2.4 + 0.9, "CPU は待ってから振る"
    print("  ROLL → MOVING（1 マス 0.28 秒）→ EVENT（カード）→ 次は CPU が 0.9 秒後に振る")

    print("● 分かれ道")
    world = World(seed=2)
    world.started = True
    world.roll(FORK_AT + 2)
    while world.phase == Phase.MOVING:
        world.update(STEP)
    assert world.phase == Phase.FORK and world.players[0].at == FORK_AT and world.steps_left == 2
    assert world.choose(1) == "hop" and world.players[0].at == MAIN_COUNT and world.steps_left == 1 and world.squares[MAIN_COUNT].side
    while world.phase == Phase.MOVING:
        world.update(STEP)
    assert world.players[0].at == MAIN_COUNT + 1
    world = World(seed=2)
    world.started = True
    world.roll(FORK_AT)
    while world.phase == Phase.MOVING:
        world.update(STEP)
    assert world.phase == Phase.EVENT and world.players[0].at == FORK_AT, "ちょうど分岐に止まれば選ばない"
    counts = {}
    for cpu in PERSONALITY:
        w = World(seed=5)
        w.turn = [p.cpu for p in w.players].index(cpu)
        counts[cpu] = sum(w.cpu_choice() for _ in range(200))
    assert counts["gambler"] > counts["mean"] > counts["steady"], counts
    print(f"  分岐で止まると選ぶ。近道は合流 {REJOIN_AT} へ。200 回のうち近道：堅実 {counts['steady']}、いじわる {counts['mean']}、賭け {counts['gambler']}")

    print("● マスの出来事")
    world = World(seed=1)
    world.started = True
    p = world.players[0]

    def land_on(index: int) -> str | None:
        p.at = index
        world.phase = Phase.MOVING
        world.steps_left = 0
        world.turn = 0
        return world.hop()

    money = p.money
    plus = next(s for s in world.squares if s.kind == "+")
    assert land_on(plus.index) == "plus" and p.money == money + plus.amount
    minus = next(s for s in world.squares if s.kind == "-")
    assert land_on(minus.index) == "minus" and p.money == money + plus.amount - minus.amount
    money = p.money
    treasure = next(s for s in world.squares if s.kind == "$")
    assert land_on(treasure.index) == "treasure" and p.money == money + TREASURE and treasure.taken
    assert land_on(treasure.index) is None and p.money == money + TREASURE, "宝は最初の 1 人だけ"
    rest = next(s for s in world.squares if s.kind == "!")
    assert land_on(rest.index) == "rest" and p.skip
    p.skip = False
    seen = set()
    for _ in range(60):
        q = next(s for s in world.squares if s.kind == "?")
        world.players[1].money = 5000
        land_on(q.index)
        seen.add(world.last_card["name"])
        if world.phase == Phase.MOVING:
            while world.phase == Phase.MOVING:
                world.update(STEP)
    assert seen == {c["name"] for c in CARDS}, seen - {c["name"] for c in CARDS}
    world = World(seed=1)
    world.started = True
    p = world.players[0]
    p.at = GOAL - 2
    world.phase = Phase.ROLL
    world.roll(6)
    while world.phase == Phase.MOVING:
        world.update(STEP)
    assert p.done and p.at == GOAL and p.goal_order == 0 and p.money == START_MONEY + GOAL_BONUS[0], "ゴールを超えてもゴールで止まる"
    print(f"  ＋／−／宝（1 人だけ）／休み／カード {len(CARDS)} 種全部／ゴールは超えても止まり 1 着 +{GOAL_BONUS[0]}")

    print("● 1 ゲーム（自動）")
    results = []
    for seed in (11, 12, 13):
        world = World(seed=seed)
        counts = play_out(world, limit=900)
        assert world.over and all(p.done for p in world.players), (seed, world.time, [p.at for p in world.players])
        results.append((world.rolls, round(world.time), world.ranking()[0].name, [p.money for p in world.players]))
    print("  " + " ／ ".join(f"種 {s}: {r} 手 {t} 秒 1 位 {w} {m}" for s, (r, t, w, m) in zip((11, 12, 13), results)))
    a, b = World(seed=7), World(seed=7)
    play_out(a, 900)
    play_out(b, 900)
    assert [p.money for p in a.players] == [p.money for p in b.players], "同じ種は同じ結果"

    print("● 板の大きさ")
    world = World(seed=2)
    play_out(world, limit=30)
    started = time.perf_counter()
    small = Screen()
    draw(small, world)
    first = time.perf_counter() - started
    started = time.perf_counter()
    draw(small, world)
    took_small = time.perf_counter() - started
    big = Screen(WIDTH * 4, HEIGHT * 4)
    started = time.perf_counter()
    draw(big, world)
    took_big_first = time.perf_counter() - started
    started = time.perf_counter()
    draw(big, world)
    took_big = time.perf_counter() - started
    print(f"  地図は最初の 1 回 {first * 1000:.0f} ms（4 倍は {took_big_first * 1000:.0f} ms）、2 回目から {took_small * 1000:.1f} ms（4 倍 {took_big * 1000:.1f} ms）")
    assert took_small < 0.02

    print("● 記録と音と状態行")
    best = Best.parse(Best(2, 5, 3000).dump())
    assert (best.wins, best.games, best.money) == (2, 5, 3000) and Best.parse("x").games == 0
    assert len({sound_bytes(k) for k in SOUNDS}) == len(SOUNDS)
    world = World(seed=1)
    for started, over, phase in ((False, False, Phase.ROLL), (True, False, Phase.ROLL), (True, False, Phase.FORK), (True, True, Phase.OVER)):
        world.started, world.over, world.phase = started, over, phase
        world.tell("あなた：カード「宝くじ」 宝くじが当たった！ +1200", 9)
        assert columns(status(world, best, True)) == WIDTH, columns(status(world, best, True))
    print(f"  記録は勝ち数・回数・最高所持金。音は {len(SOUNDS)} つ全部別。状態行は {WIDTH} 桁ちょうど")
    print("\nぜんぶ通った。")


def png_bytes(screen: Screen, scale: int = 1) -> bytes:
    import struct
    import zlib

    rows = b""
    for row in screen.rows:
        line = b"\x00" + b"".join(bytes(row[x * 3:x * 3 + 3]) * scale for x in range(screen.width))
        rows += line * scale

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", screen.width * scale, screen.height * scale, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def sheet(path: str) -> None:
    world = World(seed=5)
    play_out(world, limit=60.0)
    screen = Screen(WIDTH * 5, HEIGHT * 5)
    draw(screen, world)
    with open(path, "wb") as out:
        out.write(png_bytes(screen, 1))
    print(f"{path} に書き出した")


def main() -> None:
    if "--check" in sys.argv:
        check()
    elif "--sheet" in sys.argv:
        sheet(sys.argv[sys.argv.index("--sheet") + 1] if len(sys.argv) > 2 else "scene.png")
    else:
        run()


if __name__ == "__main__":
    main()
