"""モグラ叩き ブラウザ版

CLI 版（g67-whack-a-mole/main.py）と中身はまったく同じ。ドット絵（Sprite）も、穴の状態機械（Hole）も、
点とコンボ（World.whack）も、絵を置く処理（draw）も 1 文字も変えていない。

違うのは入口と出口だけ。
  入口: 端末はテンキーの並びの数字、ブラウザは穴をタップ／クリック（と数字キー）
  出口: 端末は ▀ の並び、ブラウザは canvas（5 倍の板）。音は端末が afplay、ブラウザは Audio
  記録: 端末は records.json、ブラウザは localStorage。中身の形（Best.dump）は同じ
"""

import asyncio
import base64
import io
import json
import math
import random
import statistics
import wave
from array import array
from dataclasses import dataclass, field
from enum import Enum

from pyscript import document, when, window


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


# --- ここから下はブラウザ版だけ。CLI 版の run() / Screen.render() / Speaker / status() にあたる ---

SCALE = 5                                           # ブラウザは 5 倍の板（600 × 360）に描く
canvas = document.querySelector("#screen")
ctx = canvas.getContext("2d")
ctx.imageSmoothingEnabled = False
image = ctx.createImageData(WIDTH * SCALE, HEIGHT * SCALE)
time_label = document.querySelector("#time")
score_label = document.querySelector("#score")
combo_label = document.querySelector("#combo")
hits_label = document.querySelector("#hits")
escaped_label = document.querySelector("#escaped")
misses_label = document.querySelector("#misses")
react_label = document.querySelector("#react")
best_label = document.querySelector("#best")
fps_label = document.querySelector("#fps")
note_label = document.querySelector("#note")
message = document.querySelector("#message")
again_button = document.querySelector("#again")
go_button = document.querySelector("#go")
SAVED = "g67-best"


class CanvasScreen(Screen):
    def flush(self) -> None:
        rgb = b"".join(self.rows)
        count = len(rgb) // 3
        rgba = bytearray(count * 4)
        rgba[0::4] = rgb[0::3]
        rgba[1::4] = rgb[1::3]
        rgba[2::4] = rgb[2::3]
        rgba[3::4] = b"\xff" * count
        image.data.assign(bytes(rgba))
        ctx.putImageData(image, 0, 0)


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


screen = CanvasScreen(WIDTH * SCALE, HEIGHT * SCALE)
speaker = Speaker()
world = World(seed=int(window.performance.now()))
best = Best.parse(window.localStorage.getItem(SAVED) or "")
improved = False
frames = []


def refresh() -> None:
    draw(screen, world)
    screen.flush()
    time_label.textContent = f"{max(0.0, ROUND - world.time):.1f}"
    score_label.textContent = str(world.score)
    combo_label.textContent = f"{world.combo}（×{world.multiplier}）"
    hits_label.textContent = str(world.hits)
    escaped_label.textContent = str(world.escaped)
    misses_label.textContent = str(world.misses)
    react_label.textContent = f"{world.average_reaction():.2f}" if world.reactions else "--"
    best_label.textContent = str(best.score)
    note_label.textContent = (world.note if world.time < world.note_until else "") or " "
    if world.over:
        message.textContent = (f"おわり。点 {world.score}、命中 {world.hits}、最長 {world.best_combo} 連続、"
                               f"反応 平均 {world.average_reaction():.2f} 秒・最速 {world.fastest_reaction():.2f} 秒"
                               + ("  ベスト更新！" if improved else ""))
    elif not world.started:
        message.textContent = "「スタート」で 60 秒。穴をタップ（または 7 8 9 / 4 5 6 / 1 2 3 のキー）で叩く。爆弾は叩かない"
    else:
        message.textContent = ""
    again_button.hidden = not world.over
    go_button.hidden = world.started


async def loop():
    global improved
    lag = 0.0
    last = window.performance.now() / 1000
    while True:
        now = window.performance.now() / 1000
        lag = min(lag + now - last, 0.25)
        last = now
        while lag >= STEP:
            event = world.update(STEP)
            if event == "end":
                improved = best.take(world)
                window.localStorage.setItem(SAVED, best.dump())
                event = "best" if improved else event
            speaker.say(event)
            lag -= STEP
        refresh()
        frames.append(window.performance.now() / 1000)
        del frames[:-30]
        if len(frames) >= 2:
            fps_label.textContent = f"{(len(frames) - 1) / (frames[-1] - frames[0]):.0f}"
        spent = window.performance.now() / 1000 - now
        await asyncio.sleep(max(0.002, STEP - spent))


@when("keydown", "body")
def on_down(event):
    if event.repeat:
        return
    if event.key in KEYPAD:
        event.preventDefault()
        speaker.say(obey(world, event.key))
    elif event.key in (" ", "Enter"):
        event.preventDefault()
        obey(world, "go")
        refresh()


@when("pointerdown", "#screen")
def tap(event):
    """穴をタップ。canvas の座標 → 穴の番号（描く側の hole_rect と同じ割り付け）。"""
    event.preventDefault()
    rect = canvas.getBoundingClientRect()
    x = (event.clientX - rect.left) / rect.width * WIDTH
    y = (event.clientY - rect.top) / rect.height * HEIGHT
    col = min(COLS - 1, max(0, int(x // CELL_W)))
    row = min(ROWS - 1, max(0, int((y - TOP) // CELL_H)))
    if not world.started:
        obey(world, "go")
        refresh()
        return
    speaker.say(world.whack(row * COLS + col))


@when("click", "#go")
def go(event):
    obey(world, "go")
    go_button.blur()
    refresh()


@when("click", "#again")
def again(event):
    global world, improved
    world = World(seed=int(window.performance.now()))
    world.started = True
    improved = False
    refresh()


document.querySelector("#loading").hidden = True
refresh()
asyncio.ensure_future(loop())
