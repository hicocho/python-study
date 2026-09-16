"""モグラ叩き

3 × 3 の穴から顔を出すモグラを叩く。60 秒 1 ラウンド。金のモグラ、ヘルメット（2 回叩く）、爆弾（叩いてはいけない）。
連続で当てるとコンボ、反応時間を測って表示する。
今回覚えるところ：
  絵と動きを分ける  絵は Sprite（文字で描いたドット絵。g32 と同じ）、動きは穴の状態機械（Hole）
  状態機械         穴は EMPTY → RISING → UP → SINKING（叩けば HIT）と時刻で進む
  重みつきの抽選    random.choices(weights=) でモグラの種類を選ぶ
  難しさの階段     時間が進むほど出る間隔と顔を出す時間が短くなる（式で決める）

    python3 main.py            遊ぶ（スペースで始める。テンキーの並び 7 8 9 / 4 5 6 / 1 2 3 で叩く。q でやめる）
    python3 main.py --check    決まりを確かめる
    python3 main.py --sheet    スプライトを PNG に書き出す（見た目の確認用）
"""

import io
import json
import math
import os
import random
import select
import statistics
import sys
import time
import wave
from array import array
from dataclasses import dataclass, field
from enum import Enum

WIDTH = 120                                         # 画面の横（ドット）。端末では 1 ドット = 1 桁
HEIGHT = 72                                         # 縦。端末では 2 ドット = 1 行 → 36 行
COLS = 3
ROWS = 3
CELL_W = WIDTH // COLS                              # 穴 1 つの幅（40）
CELL_H = 22                                         # 穴 1 つの高さ
TOP = 4                                             # 一番上の穴の上端
STEP = 1 / 30
ROUND = 60.0                                        # 1 ラウンドの秒数
RISE = 0.15                                         # 出るのにかかる秒数
SINK = 0.15                                         # 引っ込むのにかかる秒数
HIT_SHOW = 0.35                                     # 叩かれた顔を見せる秒数
MISS_PENALTY = 1                                    # 空の穴を叩いたときの減点
POINTS = {"normal": 1, "gold": 5, "helmet": 3, "bomb": -3}
WEIGHTS = {"normal": 70, "gold": 8, "helmet": 12, "bomb": 10}   # 出る割合（random.choices の重み）
COMBO_STEP = 3                                      # 3 連続ごとに倍率が 1 上がる（上限 ×4）


# ── 音（g73 と同じ作り方） ──────────────────────────────────────────────

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
    """出来事の音。pop は出た、hit は叩いた、gold は金、clank はヘルメット、bomb は爆弾、miss は空振り、end は終了、best はベスト。"""
    if kind == "pop":
        samples = tone(520, 0.04, VOLUME * 0.6) + tone(660, 0.05, VOLUME * 0.6)
    elif kind == "hit":
        samples = noise(0.08, VOLUME * 1.2, 40.0, 2) + tone(880, 0.06)
    elif kind == "gold":
        samples = tone(1319, 0.06) + tone(1760, 0.06) + tone(2637, 0.14)
    elif kind == "clank":
        samples = tone(1500, 0.03, VOLUME * 0.9) + noise(0.06, VOLUME * 0.8, 50.0, 5)
    elif kind == "bomb":
        samples = noise(0.4, VOLUME * 1.8, 8.0, 9) + tone(80, 0.25, VOLUME)
    elif kind == "miss":
        samples = tone(220, 0.1, VOLUME * 0.7)
    elif kind == "best":
        samples = tone(523, 0.1) + tone(659, 0.1) + tone(784, 0.1) + tone(1047, 0.3)
    else:
        samples = tone(784, 0.12) + tone(659, 0.12) + tone(784, 0.12) + tone(1047, 0.35)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(samples.tobytes())
    return buffer.getvalue()


EVENTS = ("pop", "miss", "clank", "hit", "gold", "bomb", "end")   # 目立つ順
SOUNDS = EVENTS + ("best",)


# ── 絵（スプライト。g32 と同じ作り） ──────────────────────────────────

PALETTE = {
    "B": (110, 74, 44),     # モグラの茶
    "b": (82, 54, 30),      # 暗い茶
    "P": (240, 150, 160),   # 鼻
    "K": (24, 20, 20),      # 黒（目・爆弾）
    "W": (245, 245, 240),   # 白
    "Y": (250, 210, 60),    # 金
    "y": (200, 150, 30),    # 暗い金
    "G": (150, 150, 160),   # ヘルメット
    "g": (100, 100, 110),   # ヘルメットの影
    "R": (230, 70, 50),     # 赤（導火線の火・叩かれた星）
    "O": (255, 170, 60),    # 橙
}
GRASS = (92, 160, 70)
GRASS_DARK = (78, 140, 60)
HOLE = (46, 30, 18)
HOLE_RIM = (70, 48, 28)
SKY = (140, 200, 240)
GAUGE = (60, 60, 70)
GAUGE_ON = (255, 200, 80)


@dataclass(frozen=True)
class Sprite:
    """ドット絵 1 枚。rows は 1 行 1 文字列で、文字がパレットの色、. が透明。"""

    name: str
    rows: tuple[str, ...]

    @property
    def width(self) -> int:
        return len(self.rows[0])

    @property
    def height(self) -> int:
        return len(self.rows)

    def pixels(self) -> list[tuple[int, int, tuple[int, int, int]]]:
        return [(x, y, PALETTE[ch]) for y, row in enumerate(self.rows) for x, ch in enumerate(row) if ch != "."]

    def recolor(self, mapping: dict[str, str]) -> "Sprite":
        table = str.maketrans(mapping)
        return Sprite(self.name, tuple(row.translate(table) for row in self.rows))


def sprite(name: str, art: str) -> Sprite:
    rows = [line for line in art.splitlines() if line.strip()]
    width = max(len(r) for r in rows)
    return Sprite(name, tuple(r.ljust(width, ".") for r in rows))


MOLE = sprite("mole", """
.....BBBBBB.....
...BBBBBBBBBB...
..BBBBBBBBBBBB..
.BBBBBBBBBBBBBB.
.BBBKKBBBBKKBBB.
.BBBKWBBBBKWBBB.
BBBBBBBBBBBBBBBB
BBBBBBBPPBBBBBBB
BBBBBBPPPPBBBBBB
BBBBBBBbbBBBBBBB
BBBBBBbbbbBBBBBB
.BBBBBBBBBBBBBB.
.BBbBBBBBBBBbBB.
..bbbBBBBBBbbb..
""")
MOLE_HIT = sprite("mole-hit", """
.....BBBBBB.....
...BBBBBBBBBB...
..BBBBBBBBBBBB..
.BBBBBBBBBBBBBB.
.BBKBKBBBBKBKBB.
.BBBKBBBBBBKBBB.
BBBKBKBBBBKBKBBB
BBBBBBBPPBBBBBBB
BBBBBBPPPPBBBBBB
BBBBBBbbbbBBBBBB
BBBBBbBBBBbBBBBB
.BBBBBBBBBBBBBB.
.BBbBBBBBBBBbBB.
..bbbBBBBBBbbb..
""")
GOLD = MOLE.recolor({"B": "Y", "b": "y"})
GOLD_HIT = MOLE_HIT.recolor({"B": "Y", "b": "y"})
HELMET = sprite("helmet", """
.....GGGGGG.....
...GGGGGGGGGG...
..GGGGGGGGGGGG..
.GgggggggggggggG
.BBBKKBBBBKKBBB.
.BBBKWBBBBKWBBB.
BBBBBBBBBBBBBBBB
BBBBBBBPPBBBBBBB
BBBBBBPPPPBBBBBB
BBBBBBBbbBBBBBBB
BBBBBBbbbbBBBBBB
.BBBBBBBBBBBBBB.
.BBbBBBBBBBBbBB.
..bbbBBBBBBbbb..
""")
HELMET_CRACKED = sprite("helmet-cracked", """
.....GGGKGG.....
...GGGGKGGGGG...
..GGGGKGGGGGGG..
.GgggggKgggggggG
.BBBKKBBBBKKBBB.
.BBBKWBBBBKWBBB.
BBBBBBBBBBBBBBBB
BBBBBBBPPBBBBBBB
BBBBBBPPPPBBBBBB
BBBBBBBbbBBBBBBB
BBBBBBbbbbBBBBBB
.BBBBBBBBBBBBBB.
.BBbBBBBBBBBbBB.
..bbbBBBBBBbbb..
""")
BOMB = sprite("bomb", """
.........R......
........O.......
.......K........
......KK........
....KKKKKKK.....
...KKKKKKKKK....
..KKKWKKKKKKK...
..KKWKKKKKKKK...
..KKKKKKKKKKK...
..KKKKKKKKKKK...
...KKKKKKKKK....
....KKKKKKK.....
................
................
""")
BOOM = sprite("boom", """
....R......R....
.....R.O..R.....
..R...OOOO...R..
...O.OOWWOO.O...
....OOWWWWOO....
.RROOWWWWWWOORR.
....OOWWWWOO....
...O.OOWWOO.O...
..R...OOOO...R..
.....R.O..R.....
....R......R....
................
................
................
""")
HAMMER = sprite("hammer", """
..GGGGGG..
..GggggG..
..GGGGGG..
.....bb...
.....bb...
.....bb...
.....bb...
""")
SPRITES = {"normal": (MOLE, MOLE_HIT), "gold": (GOLD, GOLD_HIT), "helmet": (HELMET, HELMET_CRACKED), "bomb": (BOMB, BOOM)}


# ── 板（g78 と同じ作り） ────────────────────────────────────────────────

class Screen:
    def __init__(self, width: int = WIDTH, height: int = HEIGHT):
        self.width, self.height = width, height
        self.rows = [bytearray(width * 3) for _ in range(height)]

    def band(self, top: int, bottom: int, color: tuple[int, int, int]) -> None:
        line = bytes(color) * self.width
        for y in range(max(0, top), min(self.height, bottom)):
            self.rows[y][:] = line

    def plot(self, x: int, y: int, color: tuple[int, int, int]) -> None:
        if 0 <= x < self.width and 0 <= y < self.height:
            self.rows[y][x * 3:x * 3 + 3] = bytes(color)

    def box(self, x0: int, y0: int, w: int, h: int, color: tuple[int, int, int]) -> None:
        paint = bytes(color)
        x0, x1 = max(0, x0), min(self.width, x0 + w)
        if x1 <= x0:
            return
        for y in range(max(0, y0), min(self.height, y0 + h)):
            self.rows[y][x0 * 3:x1 * 3] = paint * (x1 - x0)

    def ellipse(self, cx: float, cy: float, rx: float, ry: float, color: tuple[int, int, int]) -> None:
        """楕円。行ごとに横幅を求めて塗る。"""
        for y in range(int(cy - ry), int(cy + ry) + 1):
            t = (y - cy) / ry
            if abs(t) > 1:
                continue
            half = rx * math.sqrt(1 - t * t)
            self.box(int(cx - half), y, int(2 * half) + 1, 1, color)

    def blit(self, spr: Sprite, x0: int, y0: int, scale: int = 1, clip_bottom: int | None = None) -> None:
        """スプライトを置く。scale 倍に拡大。clip_bottom より下は描かない（穴の中に隠れる部分）。"""
        for x, y, color in spr.pixels():
            for dy in range(scale):
                yy = y0 + y * scale + dy
                if clip_bottom is not None and yy >= clip_bottom:
                    continue
                self.box(x0 + x * scale, yy, scale, 1, color)

    def pixel(self, x: int, y: int) -> tuple[int, int, int]:
        return tuple(self.rows[y][x * 3:x * 3 + 3])

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


# ── 穴の状態機械 ────────────────────────────────────────────────────────

class State(Enum):
    EMPTY = "empty"
    RISING = "rising"
    UP = "up"
    SINKING = "sinking"
    HIT = "hit"


@dataclass
class Hole:
    """穴 1 つ。モグラの種類と状態と、その状態に入った時刻。"""

    state: State = State.EMPTY
    kind: str = "normal"
    since: float = 0.0                              # いまの状態に入った時刻
    stay: float = 1.2                               # 顔を出している秒数
    armor: int = 0                                  # ヘルメットの残り（2 回叩く）
    shown_at: float = 0.0                           # 顔を出し始めた時刻（反応時間の起点）

    def enter(self, state: State, now: float) -> None:
        self.state, self.since = state, now

    def lift(self, now: float) -> float:
        """0（穴の中）〜1（全部出ている）。出るとき・引っ込むときの途中の高さ。"""
        if self.state == State.RISING:
            return min(1.0, (now - self.since) / RISE)
        if self.state == State.SINKING:
            return max(0.0, 1 - (now - self.since) / SINK)
        if self.state in (State.UP, State.HIT):
            return 1.0
        return 0.0

    def whackable(self) -> bool:
        return self.state in (State.RISING, State.UP)


def interval_at(t: float) -> float:
    """次のモグラが出るまでの秒数。0 秒で 1.3、60 秒で 0.45（難しさの階段）。"""
    return 1.3 - 0.85 * min(1.0, t / ROUND)


def stay_at(t: float) -> float:
    """顔を出している秒数。0 秒で 1.5、60 秒で 0.7。"""
    return 1.5 - 0.8 * min(1.0, t / ROUND)


# ── 記録 ────────────────────────────────────────────────────────────────

@dataclass
class Best:
    score: int = 0
    combo: int = 0
    fastest: float = 0.0                            # 最速の反応（秒）。0 は未記録

    def dump(self) -> str:
        return json.dumps({"score": self.score, "combo": self.combo, "fastest": self.fastest})

    @classmethod
    def parse(cls, text: str) -> "Best":
        try:
            data = json.loads(text)
            return cls(int(data["score"]), int(data["combo"]), float(data["fastest"]))
        except (ValueError, KeyError, TypeError):
            return cls()

    def take(self, world: "World") -> bool:
        improved = world.score > self.score
        self.score = max(self.score, world.score)
        self.combo = max(self.combo, world.best_combo)
        if world.reactions:
            fastest = min(world.reactions)
            self.fastest = fastest if self.fastest == 0.0 or fastest < self.fastest else self.fastest
        return improved


# ── 世界 ────────────────────────────────────────────────────────────────

@dataclass
class World:
    seed: int = 0
    luck: random.Random = field(default_factory=random.Random)
    holes: list[Hole] = field(default_factory=lambda: [Hole() for _ in range(COLS * ROWS)])
    time: float = 0.0
    started: bool = False
    over: bool = False
    next_pop: float = 0.8
    score: int = 0
    combo: int = 0
    best_combo: int = 0
    hits: int = 0
    escaped: int = 0                                # 叩けずに引っ込んだ数（爆弾は数えない）
    misses: int = 0
    reactions: list[float] = field(default_factory=list)
    hammer: tuple[int, float] | None = None         # 振り下ろしたハンマー（穴の番号, 時刻）
    note: str = ""
    note_until: float = 0.0

    def __post_init__(self):
        self.luck = random.Random(self.seed)

    @property
    def multiplier(self) -> int:
        return min(4, 1 + self.combo // COMBO_STEP)

    def tell(self, text: str, seconds: float = 1.0) -> None:
        self.note = text
        self.note_until = self.time + seconds

    def pop(self) -> Hole | None:
        """空いている穴を 1 つ選んでモグラを出す。種類は重みで抽選。"""
        empty = [h for h in self.holes if h.state == State.EMPTY]
        if not empty:
            return None
        hole = self.luck.choice(empty)
        hole.kind = self.luck.choices(list(WEIGHTS), weights=list(WEIGHTS.values()))[0]
        hole.stay = stay_at(self.time) * (0.6 if hole.kind == "gold" else 1.0)   # 金はすぐ引っ込む
        hole.armor = 2 if hole.kind == "helmet" else 1
        hole.shown_at = self.time
        hole.enter(State.RISING, self.time)
        return hole

    def update(self, dt: float) -> str | None:
        if not self.started or self.over:
            return None
        self.time += dt
        happened = None
        if self.time >= ROUND:
            self.over = True
            for hole in self.holes:
                hole.enter(State.EMPTY, self.time)
            return "end"
        for hole in self.holes:
            passed = self.time - hole.since
            if hole.state == State.RISING and passed >= RISE:
                hole.enter(State.UP, self.time)
            elif hole.state == State.UP and passed >= hole.stay:
                hole.enter(State.SINKING, self.time)
                if hole.kind != "bomb":
                    self.escaped += 1
            elif hole.state == State.SINKING and passed >= SINK:
                hole.enter(State.EMPTY, self.time)
            elif hole.state == State.HIT and passed >= HIT_SHOW:
                hole.enter(State.EMPTY, self.time)
        if self.time >= self.next_pop:
            if self.pop() is not None:
                happened = "pop"
            self.next_pop = self.time + interval_at(self.time) * self.luck.uniform(0.7, 1.3)
        return happened

    def whack(self, index: int) -> str | None:
        """穴 index を叩く。結果の出来事を返す。"""
        if not self.started or self.over or not 0 <= index < len(self.holes):
            return None
        hole = self.holes[index]
        self.hammer = (index, self.time)
        if not hole.whackable():
            self.score -= MISS_PENALTY
            self.misses += 1
            self.combo = 0
            self.tell("空振り −1")
            return "miss"
        if hole.kind == "bomb":
            self.score += POINTS["bomb"]
            self.combo = 0
            hole.enter(State.HIT, self.time)
            self.tell("爆弾！ −3", 1.2)
            return "bomb"
        hole.armor -= 1
        if hole.armor > 0:
            self.tell("ヘルメット！ もう 1 回")
            return "clank"
        self.combo += 1
        self.best_combo = max(self.best_combo, self.combo)
        points = POINTS[hole.kind] * self.multiplier
        self.score += points
        self.hits += 1
        self.reactions.append(self.time - hole.shown_at)
        hole.enter(State.HIT, self.time)
        word = {"normal": "命中", "gold": "金！", "helmet": "割れた！"}[hole.kind]
        self.tell(f"{word} +{points}" + (f"  ×{self.multiplier}" if self.multiplier > 1 else "") + (f"  {self.combo} 連続" if self.combo > 1 else ""))
        return "gold" if hole.kind == "gold" else "hit"

    def average_reaction(self) -> float:
        return statistics.mean(self.reactions) if self.reactions else 0.0

    def fastest_reaction(self) -> float:
        return min(self.reactions) if self.reactions else 0.0


# ── 描く ────────────────────────────────────────────────────────────────

def hole_rect(index: int) -> tuple[int, int, int, int]:
    """穴 index の四角 (x, y, w, h)。"""
    col, row = index % COLS, index // COLS
    return col * CELL_W, TOP + row * CELL_H, CELL_W, CELL_H


def draw(screen: Screen, world: World) -> None:
    """草の地面 → 穴（奥の行から）→ モグラ（穴の縁より下は隠す）→ ハンマー → 残り時間の棒。"""
    scale = screen.width // WIDTH
    screen.band(0, screen.height, GRASS)
    for row in range(ROWS):                         # 草の色を行ごとに少し変える（奥行き）
        y = (TOP + row * CELL_H) * scale
        screen.band(y, y + CELL_H * scale, GRASS if row % 2 else GRASS_DARK)
    for index, hole in enumerate(world.holes):
        x, y, w, h = hole_rect(index)
        cx, cy = (x + w / 2) * scale, (y + h - 4) * scale          # 穴は升の下のほう
        screen.ellipse(cx, cy, 15 * scale, 3.5 * scale, HOLE_RIM)
        screen.ellipse(cx, cy, 13 * scale, 2.5 * scale, HOLE)
        lift = hole.lift(world.time)
        if lift > 0:
            face, hit_face = SPRITES[hole.kind]
            spr = hit_face if hole.state == State.HIT else (HELMET_CRACKED if hole.kind == "helmet" and hole.armor == 1 else face)
            top_y = cy - spr.height * scale * lift                 # 出ているぶんだけ上に
            screen.blit(spr, int(cx - spr.width * scale / 2), int(top_y), scale, clip_bottom=int(cy))
        screen.ellipse(cx, cy, 15 * scale, 3.5 * scale, HOLE_RIM)   # 穴の手前の縁（モグラの下端を隠す）
        screen.ellipse(cx, cy + 1.2 * scale, 13 * scale, 2.0 * scale, HOLE)
    if world.hammer is not None and world.time - world.hammer[1] < 0.2:   # 振り下ろしたハンマー
        index, when = world.hammer
        x, y, w, h = hole_rect(index)
        swing = (world.time - when) / 0.2
        screen.blit(HAMMER, int((x + w / 2 - 5 + 6) * scale), int((y + 2 + 6 * swing) * scale), scale)
    bar_y = (TOP + ROWS * CELL_H + 1) * scale                       # 残り時間の棒
    screen.box(2 * scale, bar_y, (WIDTH - 4) * scale, 2 * scale, GAUGE)
    left = max(0.0, ROUND - world.time) / ROUND
    screen.box(2 * scale, bar_y, int((WIDTH - 4) * scale * left), 2 * scale, GAUGE_ON)


# ── 入力 ────────────────────────────────────────────────────────────────

KEYPAD = {"7": 0, "8": 1, "9": 2, "4": 3, "5": 4, "6": 5, "1": 6, "2": 7, "3": 8}   # テンキーの並び → 穴の番号


def obey(world: World, key: str) -> str | None:
    """キーを 1 つ受ける。数字は穴を叩く、go は始める。出来事を返す。"""
    if key == "go":
        if not world.started:
            world.started = True
        return None
    if key in KEYPAD:
        return world.whack(KEYPAD[key])
    return None


# ── 端末 ────────────────────────────────────────────────────────────────

def read_keys(fd: int) -> list[str]:
    keys = []
    while select.select([fd], [], [], 0)[0]:
        text = os.read(fd, 64).decode(errors="ignore")
        for ch in text:
            if ch in KEYPAD:
                keys.append(ch)
            elif ch in (" ", "\r", "\n"):
                keys.append("go")
            elif ch in ("q", "\x1b"):
                keys.append("quit")
            elif ch == "r":
                keys.append("reset")
    return keys


class Speaker:
    def __init__(self):
        import shutil
        import tempfile

        self.player = shutil.which("afplay") or shutil.which("aplay")
        self.folder = tempfile.mkdtemp(prefix="mole-")
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


def status(world: World, best: Best, improved: bool = False) -> str:
    """画面の下の 1 行。板と同じ 120 桁に収める（日本語は 2 桁）。"""
    note = world.note if world.time < world.note_until else ""
    if not world.started:
        note, tail = "スペースで始める", "789/456/123 で叩く q でやめる"
    elif world.over:
        note = (f"★ 点 {world.score} 反応 平均 {world.average_reaction():.2f} 最速 {world.fastest_reaction():.2f} 秒"
                + (" ベスト更新！" if improved else "") + " r でもう一度")
        tail = ""
    else:
        tail = f"ベスト {best.score} q でやめる"
    return (f" 残り {max(0.0, ROUND - world.time):4.1f} 点 {world.score:4d} 連続 {world.combo:2d} ×{world.multiplier} "
            f"命中 {world.hits:2d} 逃 {world.escaped:2d} 空振 {world.misses:2d} {note:<24} " + tail)


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
                if key == "reset" and world.over:
                    world = World(seed=int(time.time()))
                    world.started = True
                    improved = False
                else:
                    speaker.say(obey(world, key))
            lag = min(lag + now - last, 0.25)
            last = now
            while lag >= STEP:
                event = world.update(STEP)
                if event == "end":
                    improved = best.take(world)
                    save_best(best)
                    event = "best" if improved else event
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

def autopilot(world: World, delay: float = 0.25) -> str | None:
    """自動で叩く。顔を出して delay 秒たったモグラを叩く。爆弾は叩かない。"""
    for index, hole in enumerate(world.holes):
        if hole.whackable() and hole.kind != "bomb" and world.time - hole.shown_at >= delay:
            return world.whack(index)
    return None


def check() -> None:
    print("● 絵")
    for kind, (face, hit_face) in SPRITES.items():
        assert face.width == 16 and face.height == 14 and hit_face.width == 16, kind
        assert len(face.pixels()) > 60 and face.pixels() != hit_face.pixels(), kind
    assert GOLD.rows != MOLE.rows and all("B" not in row for row in GOLD.rows), "金は色を置き換えただけ（形は同じ）"
    assert HAMMER.height == 7
    print(f"  モグラ・金・ヘルメット・爆弾の 4 種 × 2 枚（ふつうと叩かれた顔）。金はふつうの色替え。ハンマー 1 枚")
    print("● 穴の状態機械")
    world = World(seed=1)
    world.started = True
    hole = world.pop()
    assert hole is not None and hole.state == State.RISING and hole.lift(0.0) == 0.0
    for _ in range(int(RISE / STEP) + 1):
        world.update(STEP)
    assert hole.state == State.UP and hole.lift(world.time) == 1.0
    for _ in range(int(hole.stay / STEP) + 1):
        world.update(STEP)
    assert hole.state == State.SINKING and world.escaped >= 1
    for _ in range(int(SINK / STEP) + 1):
        world.update(STEP)
    assert hole.state == State.EMPTY
    print(f"  EMPTY → RISING（{RISE} 秒）→ UP（顔を出す）→ SINKING（{SINK} 秒）→ EMPTY。叩けずに引っ込むと「逃した」")
    print("● 叩く")
    world = World(seed=1)
    world.started = True
    world.time = 1.0
    assert world.whack(4) == "miss" and world.score == -MISS_PENALTY and world.misses == 1, "空の穴は空振り"
    for kind, want_event, want_points in (("normal", "hit", 1), ("gold", "gold", 5), ("bomb", "bomb", -3)):
        world = World(seed=1)
        world.started = True
        world.time = 1.0
        hole = world.holes[0]
        hole.kind, hole.armor, hole.shown_at = kind, 1, 0.8
        hole.enter(State.UP, 1.0)
        assert world.whack(0) == want_event and world.score == want_points and hole.state == State.HIT, (kind, world.score)
    world = World(seed=1)
    world.started = True
    world.time = 1.0
    hole = world.holes[0]
    hole.kind, hole.armor, hole.shown_at = "helmet", 2, 0.5
    hole.enter(State.UP, 1.0)
    assert world.whack(0) == "clank" and hole.state == State.UP and world.score == 0, "ヘルメットは 1 回目は割れない"
    assert world.whack(0) == "hit" and world.score == POINTS["helmet"] and abs(world.reactions[0] - 0.5) < 1e-9
    print("  空振り −1、ふつう +1、金 +5、爆弾 −3、ヘルメットは 2 回で +3。反応時間は顔を出してから叩くまで")
    print("● コンボ")
    world = World(seed=1)
    world.started = True
    total = 0
    for k in range(7):
        hole = world.holes[k % 9]
        hole.kind, hole.armor, hole.shown_at = "normal", 1, world.time
        hole.enter(State.UP, world.time)
        world.whack(k % 9)
        total += 1 * min(4, 1 + (k + 1) // COMBO_STEP)   # 叩いた直後の連続数で倍率が決まる
    assert world.combo == 7 and world.multiplier == 3 and world.score == total, (world.combo, world.score, total)
    assert world.whack(8) == "miss" and world.combo == 0 and world.multiplier == 1
    print(f"  {COMBO_STEP} 連続ごとに倍率 +1（×4 まで）。7 連続で {total} 点。空振りで 0 に戻る")
    print("● 難しさの階段")
    assert interval_at(0) > interval_at(30) > interval_at(60) and stay_at(0) > stay_at(60)
    print(f"  出る間隔 {interval_at(0):.2f} → {interval_at(60):.2f} 秒、顔を出す時間 {stay_at(0):.1f} → {stay_at(60):.1f} 秒")
    print("● 1 ラウンド（自動で叩く）")
    world = World(seed=2)
    world.started = True
    events = []
    while not world.over:
        got = autopilot(world)
        if got:
            events.append(got)
        got = world.update(STEP)
        if got:
            events.append(got)
    kinds = {k: events.count(k) for k in EVENTS}
    assert kinds["end"] == 1 and kinds["pop"] > 50 and kinds["bomb"] == 0 and kinds["miss"] == 0
    assert world.hits > 40 and world.score > 40 and world.escaped == 0
    assert 0.2 < world.average_reaction() < 0.4
    print(f"  60 秒で {kinds['pop']} 匹出て、命中 {world.hits}（金 {kinds['gold']}、ヘルメット {kinds['clank']}）、点 {world.score}、"
          f"反応の平均 {world.average_reaction():.2f} 秒、最長 {world.best_combo} 連続")
    print("● 板の大きさ")
    world = World(seed=2)
    world.started = True
    for _ in range(90):
        world.update(STEP)
    small, big = Screen(), Screen(WIDTH * 4, HEIGHT * 4)
    started = time.perf_counter()
    draw(small, world)
    took_small = time.perf_counter() - started
    started = time.perf_counter()
    draw(big, world)
    took_big = time.perf_counter() - started
    same = sum(1 for y in range(HEIGHT) for x in range(WIDTH) if small.pixel(x, y) == big.pixel(x * 4, y * 4))
    print(f"  120×72 を描くのに {took_small * 1000:.1f} ms、480×288 は {took_big * 1000:.1f} ms。一致 {same / (WIDTH * HEIGHT):.0%}")
    assert same / (WIDTH * HEIGHT) > 0.95
    print("● 記録と音")
    best = Best.parse("")
    world = World(seed=3)
    world.score, world.best_combo, world.reactions = 30, 5, [0.4, 0.3]
    assert best.take(world) and best == Best(30, 5, 0.3)
    world.score, world.best_combo, world.reactions = 20, 8, [0.5]
    assert not best.take(world) and best == Best(30, 8, 0.3)
    assert Best.parse(best.dump()) == best and Best.parse("{x") == Best()
    assert len({sound_bytes(k) for k in SOUNDS}) == len(SOUNDS) and all(k in SOUNDS for k in EVENTS)
    print(f"  ベストは点で更新、連続と最速は別々に。音は {len(SOUNDS)} つ全部別")
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
    """スプライト一覧と、遊んでいる場面を PNG に。"""
    world = World(seed=5)
    world.started = True
    for _ in range(120):
        autopilot(world)
        world.update(STEP)
    for index, kind in ((0, "normal"), (1, "gold"), (2, "helmet"), (3, "bomb")):   # 4 種を並べて見せる
        hole = world.holes[index]
        hole.kind, hole.armor, hole.shown_at = kind, 2 if kind == "helmet" else 1, world.time
        hole.enter(State.UP, world.time)
    world.holes[4].kind, world.holes[4].armor = "helmet", 1
    world.holes[4].enter(State.UP, world.time)
    world.holes[5].kind = "normal"
    world.holes[5].enter(State.HIT, world.time)
    screen = Screen(WIDTH * 4, HEIGHT * 4)
    draw(screen, world)
    with open(path, "wb") as out:
        out.write(png_bytes(screen, 1))
    print(f"{path} に書き出した")


def main() -> None:
    if "--check" in sys.argv:
        check()
    elif "--sheet" in sys.argv:
        sheet(sys.argv[sys.argv.index("--sheet") + 1] if len(sys.argv) > 2 else "sheet.png")
    else:
        run()


if __name__ == "__main__":
    main()
