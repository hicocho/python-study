"""ブロック崩し

バーで玉を跳ね返してブロックを消す。文字で描いた 8 面、残機 3。連続で消すと倍率が上がる。
スマホでは画面のどこでも指を左右に動かすとバーが追いかける（傾きでも操作できる）。
今回覚えるところ：
  文字の地図        1 面を文字の並び 1 枚で描く。文字 → ブロックの種類は表（KINDS）
  軸ごとの当たり判定  玉を x だけ動かして調べ、次に y だけ動かして調べる。どちらの向きに跳ね返るかが自然に決まる
  細かい歩み        速い玉が薄いブロックをすり抜けないよう、1 コマを 1 ドットずつの歩みに分ける
  角度は当たった場所  バーのどこに当たったかで跳ね返る角度が決まる（真ん中は真上、端は浅く）

    python3 main.py            遊ぶ（スペースで始める・玉を放す。← → か a d でバー。q でやめる）
    python3 main.py --check    決まりを確かめる
    python3 main.py --sheet    遊んでいる場面を PNG に書き出す（見た目の確認用）
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

# ── 板とゲームの決まり ────────────────────────────────────────────────────

WIDTH = 120
HEIGHT = 84
STEP = 1 / 30
COLS = 12                                           # ブロックの列数
BRICK_W = WIDTH // COLS                             # ブロックの幅（10）
BRICK_H = 4                                         # ブロックの高さ
BRICK_TOP = 6                                       # 一番上のブロックの上端
PADDLE_Y = HEIGHT - 5                               # バーの上端
PADDLE_W = 18
PADDLE_H = 2
PADDLE_SPEED = 140.0                                # バーが 1 秒に動ける距離（指を追いかける速さ）
BALL_R = 1.3                                        # 玉の半径
LIVES = 3
SPEED_BASE = 42.0                                   # 玉の速さ（1 秒に進むドット）
SPEED_STAGE = 3.0                                   # 面が進むごとに足す
SPEED_HIT = 0.6                                     # バーで打ち返すごとに足す（1 つの玉の間）
SPEED_HIT_MAX = 14.0                                # その上限
MAX_ANGLE = math.radians(65)                        # バーの端で跳ね返る角度（真上から）
MIN_RISE = 0.25                                     # 玉の縦の速さの下限（横に走り続けないように）
STREAK_STEP = 3                                     # 連続 3 個ごとに倍率 +1（×4 まで）
SWAY = 8.0                                          # 動くブロックが左右にずれる幅
SWAY_PERIOD = 3.0                                   # その周期（秒）
STAGE_PAUSE = 1.5                                   # 面が変わるときの間
LAUNCH_ANGLE = math.radians(20)                     # 放したときの角度
TRAIL = 6                                           # 残像の数
DROP_RATE = 0.15                                    # ブロックを壊したときにカプセルが落ちる確率
CAPSULE_SPEED = 22.0                                # カプセルの落ちる速さ
CAPSULE_W = 7.0
CAPSULE_H = 3.6
WIDE_SCALE = 1.5                                    # 広いバー
SHRINK_SCALE = 0.6                                  # 縮んだバー
SLOW_SCALE = 0.65                                   # ゆっくり
SPLIT_ANGLE = math.radians(25)                      # 分裂した玉の開き
LASER_COOL = 0.35                                   # レーザーの連射間隔
LASER_SHOW = 0.12                                   # 光線が見えている時間
MAX_BALLS = 5                                       # 玉の数の上限
MAX_LIVES = 5                                       # 残機の上限
BARRIER_Y = HEIGHT - 1.5                            # バリアの線

# パワーアップ。効き目は「切れる時刻」で持つ（split は一度きり）。weight は落ちやすさ
POWERS = {
    "split": dict(word="玉が 3 つ！", seconds=0.0, weight=22, color=(120, 200, 255)),
    "wide": dict(word="バーが広い", seconds=12.0, weight=22, color=(110, 220, 120)),
    "pierce": dict(word="貫通！", seconds=8.0, weight=14, color=(255, 120, 60)),
    "slow": dict(word="ゆっくり", seconds=8.0, weight=16, color=(240, 220, 90)),
    "magnet": dict(word="磁石：拾って狙う", seconds=10.0, weight=14, color=(200, 130, 255)),
    "shrink": dict(word="バーが縮んだ…", seconds=8.0, weight=12, color=(160, 160, 170)),
    "laser": dict(word="レーザー：タップで撃つ", seconds=8.0, weight=14, color=(255, 80, 120)),
    "fire": dict(word="火の玉！", seconds=8.0, weight=12, color=(255, 150, 40)),
    "add": dict(word="玉が 1 つ増えた", seconds=0.0, weight=12, color=(200, 230, 255)),
    "life": dict(word="1UP！", seconds=0.0, weight=4, color=(255, 230, 80)),
    "barrier": dict(word="バリア（1 回だけ）", seconds=0.0, weight=12, color=(80, 220, 200)),
}

# 文字 → ブロックの種類。hits が 0 なら壊れない。points は壊したときの点
KINDS = {
    "r": dict(name="赤", hits=1, points=10, color=(226, 72, 66)),
    "o": dict(name="橙", hits=1, points=10, color=(240, 140, 50)),
    "y": dict(name="黄", hits=1, points=10, color=(240, 205, 60)),
    "g": dict(name="緑", hits=1, points=10, color=(90, 190, 90)),
    "b": dict(name="青", hits=1, points=10, color=(70, 140, 230)),
    "p": dict(name="紫", hits=1, points=10, color=(170, 100, 220)),
    "H": dict(name="硬い", hits=2, points=20, color=(190, 190, 200)),
    "S": dict(name="鉄", hits=0, points=0, color=(230, 190, 70)),
    "X": dict(name="爆発", hits=1, points=30, color=(255, 110, 40)),
    ">": dict(name="動く", hits=1, points=30, color=(100, 220, 220)),
    "<": dict(name="動く", hits=1, points=30, color=(100, 220, 220)),
}

# 面。1 行 12 文字、. は空き。上の行が上に置かれる
STAGES = [
    ("はじまり", """
rrrrrrrrrrrr
oooooooooooo
yyyyyyyyyyyy
gggggggggggg
"""),
    ("ピラミッド", """
.....bb.....
....bbbb....
...gggggg...
..yyyyyyyy..
.oooooooooo.
rrrrrrrrrrrr
"""),
    ("硬い壁", """
pppppppppppp
bbbbbbbbbbbb
HHHHHHHHHHHH
gggggggggggg
yyyyyyyyyyyy
"""),
    ("爆弾畑", """
rrrrXrrXrrrr
oooooooooooo
yXyyyyyyyXyy
gggggggggggg
bbbbXbbXbbbb
"""),
    ("鉄の柱", """
S..S..S..S..
S.rrS.rrS.rr
S.ooS.ooS.oo
S.yyS.yyS.yy
............
gggggggggggg
"""),
    ("動く列", """
>>>>>>>>>>>>
............
rrrrrrrrrrrr
HHHHHHHHHHHH
............
<<<<<<<<<<<<
"""),
    ("城", """
.rr.rr..rr..
.HHHHHHHHHH.
.H..X..X..H.
.H.pppppp.H.
.H.pppppp.H.
.HHHHHHHHHH.
"""),
    ("最後の砦", """
X>>>>>>>>>>X
SHHHHHHHHHHS
S.rroorryy.S
S.rXoorXyy.S
S.ggbbppgg.S
SHHHHHHHHHHS
<<<<<<<<<<<<
"""),
]

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
    """出来事の音。"""
    if kind == "wall":                              # 壁（コツ）
        samples = tone(700, 0.03, VOLUME * 0.6)
    elif kind == "paddle":                          # バー（ポン）
        samples = tone(440, 0.04) + tone(520, 0.04)
    elif kind == "brick":                           # ブロックが壊れる（パリン）
        samples = tone(1200, 0.03) + noise(0.06, VOLUME, 50.0, 3)
    elif kind == "clank":                           # 硬い・鉄（カン）
        samples = tone(1800, 0.025, VOLUME * 0.9) + noise(0.05, VOLUME * 0.7, 60.0, 5)
    elif kind == "boom":                            # 爆発
        samples = noise(0.35, VOLUME * 1.8, 9.0, 9) + tone(90, 0.2, VOLUME)
    elif kind == "power":                           # パワーアップを拾った（上がる 2 音）
        samples = tone(660, 0.06) + tone(990, 0.1)
    elif kind == "life":                            # 1UP（ファンファーレ）
        samples = tone(784, 0.08) + tone(988, 0.08) + tone(1175, 0.08) + tone(1568, 0.2)
    elif kind == "laser":                           # レーザー（ピュン）
        samples = array("h", (int(v) for v in tone(1400, 0.08, VOLUME * 0.8))) + tone(900, 0.04, VOLUME * 0.6)
    elif kind == "bad":                             # 悪いのを拾った（下がる 2 音）
        samples = tone(500, 0.06) + tone(330, 0.12)
    elif kind == "launch":                          # 放す（ピッ）
        samples = tone(880, 0.05)
    elif kind == "lose":                            # 玉を落とした
        samples = tone(300, 0.1, VOLUME * 0.8) + tone(220, 0.16, VOLUME * 0.8)
    elif kind == "clear":                           # 面クリア
        samples = tone(660, 0.1) + tone(880, 0.1) + tone(1100, 0.1) + tone(1320, 0.25)
    elif kind == "best":
        samples = tone(523, 0.1) + tone(659, 0.1) + tone(784, 0.1) + tone(1047, 0.3)
    else:                                           # end
        samples = tone(784, 0.12) + tone(659, 0.12) + tone(523, 0.12) + tone(392, 0.35)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(samples.tobytes())
    return buffer.getvalue()


EVENTS = ("end", "clear", "lose", "life", "boom", "power", "bad", "brick", "laser", "clank", "paddle", "wall", "launch")   # 目立つ順
SOUNDS = EVENTS + ("best",)

# ── 色 ────────────────────────────────────────────────────────────────

BACK_TOP = (22, 24, 48)
BACK_BOTTOM = (36, 40, 74)
WALL = (90, 96, 140)
PADDLE = (230, 232, 240)
PADDLE_EDGE = (150, 160, 200)
BALL = (255, 255, 240)
BALL_SHADE = (200, 200, 190)
LIFE = (255, 255, 240)
CRACK = (60, 60, 70)
SHINE = (255, 255, 255)
HOT = (255, 190, 60)                                # 連続 ×4 の玉
HOT_LIGHT = (255, 240, 170)
PIERCE = (255, 110, 50)
PIERCE_LIGHT = (255, 200, 150)
MAGNET = (200, 130, 255)
SHRUNK = (160, 160, 170)
FIRE = (255, 90, 30)
FIRE_LIGHT = (255, 220, 120)
LASER_BEAM = (255, 120, 160)
LASER_PAD = (255, 150, 180)
BARRIER = (80, 220, 200)


def shade(color: tuple[int, int, int], k: float) -> tuple[int, int, int]:
    return tuple(max(0, min(255, int(c * k))) for c in color)


# ── 板（g67 と同じ） ────────────────────────────────────────────────────

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


# ── ブロック・玉・面 ─────────────────────────────────────────────────────

@dataclass
class Brick:
    col: int
    row: int
    kind: str
    left: int = 0                                   # 残りの当たり回数（0 の鉄は壊れない）

    def __post_init__(self):
        self.left = KINDS[self.kind]["hits"]

    @property
    def breakable(self) -> bool:
        return KINDS[self.kind]["hits"] > 0

    def rect(self, now: float) -> tuple[float, float, float, float]:
        """いまの四角 (x, y, w, h)。動くブロックは左右に揺れる。"""
        x = self.col * BRICK_W
        if self.kind == ">":
            x += SWAY * math.sin(math.tau * now / SWAY_PERIOD)
        elif self.kind == "<":
            x -= SWAY * math.sin(math.tau * now / SWAY_PERIOD)
        return x, BRICK_TOP + self.row * BRICK_H, BRICK_W, BRICK_H


def parse_stage(text: str) -> list[Brick]:
    """文字の地図 → ブロックの列。"""
    bricks = []
    for row, line in enumerate(l for l in text.splitlines() if l.strip()):
        for col, ch in enumerate(line):
            if ch != ".":
                bricks.append(Brick(col, row, ch))
    return bricks


@dataclass
class Ball:
    x: float = WIDTH / 2
    y: float = PADDLE_Y - BALL_R
    vx: float = 0.0
    vy: float = 0.0
    stuck: bool = True                              # バーに乗っている（放す前）
    offset: float = 0.0                             # 乗っているときのバー中心からのずれ（磁石で拾った位置）
    trail: list[tuple[float, float]] = field(default_factory=list)   # 残像（少し前の位置）


@dataclass
class Spark:
    """壊れたときの粒。"""
    x: float
    y: float
    vx: float
    vy: float
    life: float
    color: tuple[int, int, int]


@dataclass
class Capsule:
    """落ちてくるパワーアップ。"""
    x: float
    y: float
    kind: str


@dataclass
class Best:
    score: int = 0
    stage: int = 0                                  # 到達した面（1 から）

    def dump(self) -> str:
        return json.dumps({"score": self.score, "stage": self.stage})

    @classmethod
    def parse(cls, text: str) -> "Best":
        try:
            data = json.loads(text)
            return cls(int(data.get("score", 0)), int(data.get("stage", 0)))
        except (ValueError, TypeError, AttributeError):
            return cls()

    def take(self, world: "World") -> bool:
        improved = world.score > self.score
        self.score = max(self.score, world.score)
        self.stage = max(self.stage, world.stage + 1)
        return improved


@dataclass
class World:
    seed: int = 0
    stage: int = 0                                  # いまの面（0 から）
    bricks: list[Brick] = field(default_factory=list)
    balls: list[Ball] = field(default_factory=list)
    capsules: list[Capsule] = field(default_factory=list)
    paddle_x: float = WIDTH / 2                     # バーの中心
    target_x: float = WIDTH / 2                     # 指（キー）が指している中心
    time: float = 0.0
    started: bool = False
    over: bool = False
    won: bool = False                               # 全部の面をクリアした
    lives: int = LIVES
    score: int = 0
    streak: int = 0                                 # バーに戻るまでに壊した数
    best_streak: int = 0
    paddle_hits: int = 0                            # この玉で打ち返した回数（速くなる）
    broken: int = 0
    caught: int = 0                                 # 拾ったパワーアップの数
    pause_until: float = 0.0                        # 面が変わるときの間
    note: str = ""
    note_until: float = 0.0
    sparks: list[Spark] = field(default_factory=list)
    flash_until: float = 0.0                        # バーが光る
    shake_until: float = 0.0                        # 画面が揺れる
    shake_size: float = 0.0
    powers: dict[str, float] = field(default_factory=dict)   # 効いているパワーアップ → 切れる時刻
    barrier: bool = False                           # 1 回だけ跳ね返す線
    laser_at: float = -9.0                          # 最後にレーザーを撃った時刻
    laser_x: float = 0.0                            # 光線の x（見せる用）
    laser_top: float = 0.0                          # 光線の上端

    def __post_init__(self):
        self.luck = random.Random(self.seed)
        self.load_stage(0)

    # ── 面 ──
    def load_stage(self, index: int) -> None:
        self.stage = index
        self.bricks = parse_stage(STAGES[index][1])
        self.capsules = []
        self.powers = {}
        self.barrier = False
        self.reset_ball()

    def reset_ball(self) -> None:
        self.balls = [Ball(x=self.paddle_x, y=PADDLE_Y - BALL_R, stuck=True)]
        self.paddle_hits = 0
        self.streak = 0

    @property
    def ball(self) -> Ball:
        """代表の玉（乗っている玉があればそれ、無ければ一番下の玉）。"""
        stuck = [b for b in self.balls if b.stuck]
        return stuck[0] if stuck else max(self.balls, key=lambda b: b.y)

    @ball.setter
    def ball(self, ball: Ball) -> None:
        self.balls = [ball]

    @property
    def stage_name(self) -> str:
        return STAGES[self.stage][0]

    @property
    def multiplier(self) -> int:
        return min(4, 1 + self.streak // STREAK_STEP)

    def has(self, power: str) -> bool:
        return self.time < self.powers.get(power, 0.0)

    @property
    def paddle_w(self) -> float:
        if self.has("wide"):
            return PADDLE_W * WIDE_SCALE
        if self.has("shrink"):
            return PADDLE_W * SHRINK_SCALE
        return PADDLE_W

    @property
    def speed(self) -> float:
        speed = SPEED_BASE + SPEED_STAGE * self.stage + min(SPEED_HIT_MAX, SPEED_HIT * self.paddle_hits)
        return speed * SLOW_SCALE if self.has("slow") else speed

    def remaining(self) -> int:
        return sum(1 for b in self.bricks if b.breakable)

    def tell(self, text: str, seconds: float = 1.5) -> None:
        self.note, self.note_until = text, self.time + seconds

    def shake(self, size: float, seconds: float = 0.2) -> None:
        self.shake_size = max(self.shake_size if self.time < self.shake_until else 0.0, size)
        self.shake_until = self.time + seconds

    # ── 入力 ──
    def launch(self) -> str | None:
        """乗っている玉を放す。乗っていなければ、レーザーが効いていれば撃つ。"""
        if self.time < self.pause_until:
            return None
        if not any(b.stuck for b in self.balls) and self.has("laser"):
            return self.fire_laser()
        launched = False
        for ball in self.balls:
            if not ball.stuck:
                continue
            ball.stuck = False
            if ball.offset:                         # 磁石で拾った玉は、その場所の角度で放す
                angle = max(-1.0, min(1.0, ball.offset / (self.paddle_w / 2))) * MAX_ANGLE
            else:
                angle = LAUNCH_ANGLE * (1 if self.luck.random() < 0.5 else -1)
            ball.vx, ball.vy = self.speed * math.sin(angle), -self.speed * math.cos(angle)
            ball.offset = 0.0
            launched = True
        return "launch" if launched else None

    def fire_laser(self) -> str | None:
        """バーの真上に光線。一番下の壊せるブロックを 1 つ削る。鉄で止まる。"""
        if self.time - self.laser_at < LASER_COOL - 1e-9:
            return None
        self.laser_at = self.time
        self.laser_x = self.paddle_x
        self.laser_top = 0.0
        below = [b for b in self.bricks if b.rect(self.time)[0] <= self.paddle_x < b.rect(self.time)[0] + BRICK_W]
        if below:
            target = max(below, key=lambda b: b.row)
            self.laser_top = target.rect(self.time)[1] + BRICK_H
            self.damage(target)
        return "laser"

    def aim(self, x: float) -> None:
        """バーの目標の中心を決める（指・傾き・自動）。"""
        half = self.paddle_w / 2
        self.target_x = max(half, min(WIDTH - half, x))

    def nudge(self, dx: float) -> None:
        """キーで少しずらす。"""
        self.aim(self.target_x + dx)

    # ── 進める ──
    def update(self, dt: float) -> str | None:
        if not self.started or self.over:
            return None
        self.time += dt
        half = self.paddle_w / 2
        step = max(-PADDLE_SPEED * dt, min(PADDLE_SPEED * dt, self.target_x - self.paddle_x))
        self.paddle_x = max(half, min(WIDTH - half, self.paddle_x + step))
        self.age_sparks(dt)
        if self.time < self.pause_until:
            if self.luck.random() < dt * 6:         # 面クリアの花火
                self.burst(self.luck.uniform(20, WIDTH - 20), self.luck.uniform(15, 50),
                           self.luck.choice([k["color"] for k in KINDS.values()]), 12)
            return None
        happened = set()
        happened |= self.fall_capsules(dt)
        hit_now: set[int] = set()
        for ball in list(self.balls):
            if ball.stuck:
                ball.x, ball.y = self.paddle_x + ball.offset, PADDLE_Y - BALL_R
                continue
            speed = self.speed                      # 向きはそのまま、速さだけそろえる
            length = math.hypot(ball.vx, ball.vy) or 1.0
            ball.vx, ball.vy = ball.vx / length * speed, ball.vy / length * speed
            ball.trail.append((ball.x, ball.y))
            del ball.trail[:-TRAIL]
            steps = max(1, math.ceil(speed * dt / 1.0))  # 1 ドットずつ歩む
            for _ in range(steps):
                happened |= self.walk(ball, dt / steps, hit_now)
                if ball.stuck or ball not in self.balls:
                    break
        if not self.balls:                          # 全部落とした
            happened.add(self.lose_life())
        if self.remaining() == 0 and not self.over:
            happened.add(self.next_stage())
        for name in EVENTS:
            if name in happened:
                return name
        return None

    def walk(self, ball: Ball, dt: float, hit_now: set[int]) -> set[str]:
        """玉を少し進める。x を動かして調べ、次に y を動かして調べる。"""
        happened = set()
        ball.x += ball.vx * dt
        if ball.x - BALL_R < 0:
            ball.x, ball.vx = BALL_R, abs(ball.vx)
            happened.add("wall")
        elif ball.x + BALL_R > WIDTH:
            ball.x, ball.vx = WIDTH - BALL_R, -abs(ball.vx)
            happened.add("wall")
        happened |= self.hit_bricks(ball, "x", hit_now)
        ball.y += ball.vy * dt
        if ball.y - BALL_R < 0:
            ball.y, ball.vy = BALL_R, abs(ball.vy)
            happened.add("wall")
        happened |= self.hit_bricks(ball, "y", hit_now)
        if ball.vy > 0 and ball.y + BALL_R >= PADDLE_Y and ball.y - BALL_R <= PADDLE_Y + PADDLE_H \
                and abs(ball.x - self.paddle_x) <= self.paddle_w / 2 + BALL_R:
            self.bounce_paddle(ball)
            happened.add("paddle")
        if self.barrier and ball.vy > 0 and ball.y + BALL_R >= BARRIER_Y:   # バリア：1 回だけ跳ね返す
            self.barrier = False
            ball.y, ball.vy = BARRIER_Y - BALL_R, -abs(ball.vy)
            self.burst(ball.x, BARRIER_Y, BARRIER, 8)
            self.tell("バリアで跳ね返した", 1.0)
            happened.add("paddle")
        if ball.y - BALL_R > HEIGHT:                # 落とした
            self.balls.remove(ball)
            if self.balls:
                self.tell(f"玉が落ちた（あと {len(self.balls)} 個）", 1.0)
        return happened

    def bounce_paddle(self, ball: Ball) -> None:
        """当たった場所で角度が決まる。真ん中は真上、端は MAX_ANGLE。磁石なら乗せる。"""
        offset = max(-1.0, min(1.0, (ball.x - self.paddle_x) / (self.paddle_w / 2)))
        self.paddle_hits += 1
        self.streak = 0
        self.flash_until = self.time + 0.12
        ball.y = PADDLE_Y - BALL_R
        if self.has("magnet"):
            ball.stuck, ball.offset = True, ball.x - self.paddle_x
            ball.vx = ball.vy = 0.0
            return
        angle = offset * MAX_ANGLE
        speed = self.speed
        ball.vx, ball.vy = speed * math.sin(angle), -speed * math.cos(angle)

    def hit_bricks(self, ball: Ball, axis: str, hit_now: set[int]) -> set[str]:
        happened = set()
        for brick in self.bricks:
            bx, by, bw, bh = brick.rect(self.time)
            if not (ball.x + BALL_R > bx and ball.x - BALL_R < bx + bw and ball.y + BALL_R > by and ball.y - BALL_R < by + bh):
                continue
            if self.has("pierce") and brick.breakable:      # 貫通：止まらずに壊す
                if id(brick) not in hit_now:
                    hit_now.add(id(brick))
                    brick.left = 1
                    happened.add(self.damage(brick))
                break
            if axis == "x":                         # 横から当たった → 左右に押し戻す
                if ball.vx > 0:
                    ball.x = bx - BALL_R
                else:
                    ball.x = bx + bw + BALL_R
                ball.vx = -ball.vx
            else:                                   # 縦から当たった
                if ball.vy > 0:
                    ball.y = by - BALL_R
                else:
                    ball.y = by + bh + BALL_R
                ball.vy = -ball.vy
            if id(brick) not in hit_now:
                hit_now.add(id(brick))
                happened.add(self.damage(brick))
                if self.has("fire") and brick.breakable:        # 火の玉：上下左右も壊す
                    for other in list(self.bricks):
                        if other.breakable and abs(other.col - brick.col) + abs(other.row - brick.row) == 1:
                            self.destroy(other)
            break                                   # 1 歩で当たるのは 1 つ
        if abs(ball.vy) < self.speed * MIN_RISE:    # 横に走りすぎない
            sign = 1 if ball.vy >= 0 else -1
            ball.vy = sign * self.speed * MIN_RISE
            ball.vx = math.copysign(math.sqrt(max(0.0, self.speed ** 2 - ball.vy ** 2)), ball.vx or 1.0)
        return happened

    def damage(self, brick: Brick) -> str:
        """ブロックに 1 発。壊れたら点と粒。爆発は周りも壊す。"""
        if not brick.breakable:
            self.shake(0.5, 0.1)
            return "clank"
        brick.left -= 1
        if brick.left > 0:
            return "clank"
        return self.destroy(brick)

    def destroy(self, brick: Brick) -> str:
        if brick not in self.bricks:
            return "brick"
        self.bricks.remove(brick)
        self.streak += 1
        self.best_streak = max(self.best_streak, self.streak)
        self.broken += 1
        gained = KINDS[brick.kind]["points"] * self.multiplier
        self.score += gained
        bx, by, bw, bh = brick.rect(self.time)
        self.burst(bx + bw / 2, by + bh / 2, KINDS[brick.kind]["color"], 6)
        self.shake(1.0, 0.12)
        if self.multiplier > 1:
            self.tell(f"{self.streak} 連続 ×{self.multiplier}", 1.0)
        if self.luck.random() < DROP_RATE:          # たまにパワーアップが落ちる
            names = list(POWERS)
            kind = self.luck.choices(names, weights=[POWERS[k]["weight"] for k in names])[0]
            self.capsules.append(Capsule(bx + bw / 2, by + bh / 2, kind))
        if brick.kind == "X":                       # 周り 8 つも壊す（鉄は残る。爆発は連鎖する）
            self.burst(bx + bw / 2, by + bh / 2, (255, 200, 80), 14)
            self.shake(2.5, 0.3)
            for other in list(self.bricks):
                if other.breakable and abs(other.col - brick.col) <= 1 and abs(other.row - brick.row) <= 1:
                    self.destroy(other)
            return "boom"
        return "brick"

    def fall_capsules(self, dt: float) -> set[str]:
        """カプセルが落ちる。バーで拾えば効く。"""
        happened = set()
        for cap in list(self.capsules):
            cap.y += CAPSULE_SPEED * dt
            if cap.y + CAPSULE_H / 2 >= PADDLE_Y and cap.y - CAPSULE_H / 2 <= PADDLE_Y + PADDLE_H \
                    and abs(cap.x - self.paddle_x) <= self.paddle_w / 2 + CAPSULE_W / 2:
                self.capsules.remove(cap)
                happened.add(self.apply_power(cap.kind))
            elif cap.y > HEIGHT + CAPSULE_H:
                self.capsules.remove(cap)
        return happened

    def apply_power(self, kind: str) -> str:
        spec = POWERS[kind]
        self.caught += 1
        self.tell(spec["word"], 1.5)
        self.burst(self.paddle_x, PADDLE_Y, spec["color"], 10)
        if kind == "split":                         # 玉を 3 つに（いま飛んでいる玉から分ける）
            flying = [b for b in self.balls if not b.stuck]
            source = flying[0] if flying else self.balls[0]
            for turn in (-SPLIT_ANGLE, SPLIT_ANGLE):
                if len(self.balls) >= MAX_BALLS:
                    break
                c, s = math.cos(turn), math.sin(turn)
                self.balls.append(Ball(source.x, source.y, source.vx * c - source.vy * s, source.vx * s + source.vy * c, stuck=False))
            if source.stuck:                        # 乗っている玉から分けたときは、分身だけ上へ放す
                for b in self.balls:
                    if b is not source and not b.stuck and b.vx == 0 and b.vy == 0:
                        b.vx, b.vy = self.speed * math.sin(LAUNCH_ANGLE), -self.speed * math.cos(LAUNCH_ANGLE)
            return "power"
        if kind == "add":                           # 乗った玉を 1 つ足す（上限あり）
            if len(self.balls) < MAX_BALLS:
                self.balls.append(Ball(self.paddle_x, PADDLE_Y - BALL_R, stuck=True))
            return "power"
        if kind == "life":
            self.lives = min(MAX_LIVES, self.lives + 1)
            return "life"
        if kind == "barrier":
            self.barrier = True
            return "power"
        if kind == "wide":
            self.powers.pop("shrink", None)
        elif kind == "shrink":
            self.powers.pop("wide", None)
        self.powers[kind] = self.time + spec["seconds"]
        return "power" if kind != "shrink" else "bad"

    def burst(self, x: float, y: float, color: tuple[int, int, int], count: int) -> None:
        for _ in range(count):
            angle = self.luck.uniform(0, math.tau)
            speed = self.luck.uniform(10, 40)
            self.sparks.append(Spark(x, y, math.cos(angle) * speed, math.sin(angle) * speed - 10, self.luck.uniform(0.3, 0.6), color))

    def age_sparks(self, dt: float) -> None:
        for s in self.sparks:
            s.x += s.vx * dt
            s.y += s.vy * dt
            s.vy += 60 * dt
            s.life -= dt
        self.sparks = [s for s in self.sparks if s.life > 0]

    def lose_life(self) -> str:
        self.lives -= 1
        self.powers = {}
        self.barrier = False
        self.shake(2.0, 0.3)
        if self.lives <= 0:
            self.over = True
            self.tell("ゲームオーバー", 99)
            return "end"
        self.reset_ball()
        self.tell(f"あと {self.lives} 個", 1.5)
        return "lose"

    def next_stage(self) -> str:
        if self.stage + 1 >= len(STAGES):
            self.over = True
            self.won = True
            self.tell("全部クリア！", 99)
            return "end"
        self.load_stage(self.stage + 1)
        self.pause_until = self.time + STAGE_PAUSE
        self.tell(f"面 {self.stage + 1}：{self.stage_name}", STAGE_PAUSE)
        return "clear"


# ── 描く ────────────────────────────────────────────────────────────────

def draw(screen: Screen, world: World) -> None:
    scale = screen.width // WIDTH
    ox = oy = 0.0                                                  # 揺れ
    if world.time < world.shake_until:
        k = world.shake_size * (world.shake_until - world.time) / 0.3
        ox = math.sin(world.time * 90) * k
        oy = math.cos(world.time * 70) * k * 0.6
    for y in range(screen.height):                  # 上から下へ少し明るく
        t = y / screen.height
        screen.band(y, y + 1, tuple(int(a + (b - a) * t) for a, b in zip(BACK_TOP, BACK_BOTTOM)))
    blink = world.remaining() <= 3 and int(world.time * 6) % 2 == 0
    for brick in world.bricks:
        bx, by, bw, bh = brick.rect(world.time)
        color = KINDS[brick.kind]["color"]
        if brick.kind == "H" and brick.left == 1:
            color = shade(color, 0.7)
        if blink and brick.breakable:
            color = shade(color, 1.4)
        x0, y0 = int((bx + ox) * scale), int((by + oy) * scale)
        w, h = bw * scale, bh * scale
        screen.box(x0, y0, w, h, shade(color, 0.55))              # 縁
        screen.box(x0 + scale, y0 + scale, w - 2 * scale, h - 2 * scale, color)
        screen.box(x0 + scale, y0 + scale, w - 2 * scale, max(1, scale // 2), shade(color, 1.35))   # 上の光
        if brick.kind == "S":                                     # 鉄：びょう
            for dx in (2, bw - 3):
                screen.box(x0 + dx * scale, y0 + scale, scale, scale, shade(color, 0.6))
        elif brick.kind == "X":                                   # 爆発：芯
            screen.box(x0 + (bw // 2 - 1) * scale, y0 + scale, 2 * scale, (bh - 2) * scale, (255, 230, 120))
        elif brick.kind == "H" and brick.left == 1:               # ひび
            for i in range(bh - 2):
                screen.box(x0 + (3 + i) * scale, y0 + (1 + i) * scale, scale, scale, CRACK)
        elif brick.kind in "<>":                                  # 動く：矢印の向き
            dx = bw - 3 if brick.kind == ">" else 2
            screen.box(x0 + dx * scale, y0 + scale, scale, (bh - 2) * scale, shade(color, 0.6))
    for cap in world.capsules:                                     # カプセル
        spec = POWERS[cap.kind]
        cx, cy = (cap.x + ox) * scale, (cap.y + oy) * scale
        screen.ellipse(cx, cy, CAPSULE_W / 2 * scale, CAPSULE_H / 2 * scale, shade(spec["color"], 0.6))
        screen.ellipse(cx, cy - 0.3 * scale, (CAPSULE_W / 2 - 0.8) * scale, (CAPSULE_H / 2 - 0.6) * scale, spec["color"])
        draw_icon(screen, cap.kind, cx, cy, scale)
    for s in world.sparks:
        screen.box(int((s.x + ox) * scale), int((s.y + oy) * scale), scale, scale, s.color)
    if world.time - world.laser_at < LASER_SHOW:                   # 光線
        top = int((world.laser_top + oy) * scale)
        screen.box(int((world.laser_x - 0.5 + ox) * scale), top, scale, int((PADDLE_Y + oy) * scale) - top, LASER_BEAM)
    if world.barrier:                                              # バリアの線
        screen.box(0, int((BARRIER_Y + oy) * scale), screen.width, max(1, scale // 2), BARRIER)
    half = world.paddle_w / 2
    px = int((world.paddle_x - half + ox) * scale)                  # バー
    py = int((PADDLE_Y + oy) * scale)
    paddle = SHINE if world.time < world.flash_until else PADDLE
    if world.has("magnet"):
        paddle = MAGNET
    elif world.has("laser"):
        paddle = LASER_PAD
    elif world.has("shrink"):
        paddle = SHRUNK
    screen.box(px, py, int(world.paddle_w * scale), PADDLE_H * scale, paddle)
    screen.box(px, py, scale, PADDLE_H * scale, PADDLE_EDGE)
    screen.box(px + int((world.paddle_w - 1) * scale), py, scale, PADDLE_H * scale, PADDLE_EDGE)
    hot = world.multiplier >= 4
    for ball in world.balls:                                       # 玉と残像
        for i, (tx, ty) in enumerate(ball.trail):
            k = (i + 1) / (len(ball.trail) + 1)
            screen.ellipse((tx + ox) * scale, (ty + oy) * scale, BALL_R * scale * k * 0.8, BALL_R * scale * k * 0.8,
                           shade(HOT if hot else BALL, 0.35 + 0.4 * k))
        color, light = (HOT, HOT_LIGHT) if hot else (BALL_SHADE, BALL)
        if world.has("pierce"):
            color, light = PIERCE, PIERCE_LIGHT
        if world.has("fire"):
            color, light = FIRE, FIRE_LIGHT
        bx, by = (ball.x + ox) * scale, (ball.y + oy) * scale
        screen.ellipse(bx, by, BALL_R * scale, BALL_R * scale, color)
        screen.ellipse(bx - scale * 0.3, by - scale * 0.3, BALL_R * scale * 0.7, BALL_R * scale * 0.7, light)
    for i in range(world.lives - 1):                               # 残りの玉（左上）
        screen.ellipse((3 + i * 4) * scale, 2.5 * scale, 1.2 * scale, 1.2 * scale, LIFE)
    x = WIDTH - 3                                                  # 効いているパワーアップ（右上、残り時間の棒）
    for kind, until in world.powers.items():
        if until <= world.time:
            continue
        left = (until - world.time) / POWERS[kind]["seconds"]
        screen.box(int((x - 8) * scale), int(1 * scale), int(8 * left * scale), int(2 * scale), POWERS[kind]["color"])
        x -= 10


def draw_icon(screen: Screen, kind: str, cx: float, cy: float, scale: int) -> None:
    """カプセルの中の印。"""
    ink = (30, 30, 40)
    if kind == "split":                                            # 点 3 つ
        for dx in (-1.8, 0, 1.8):
            screen.box(int(cx + dx * scale - scale * 0.5), int(cy - scale * 0.5), scale, scale, ink)
    elif kind == "wide":                                           # 横の棒
        screen.box(int(cx - 2.5 * scale), int(cy - scale * 0.5), 5 * scale, scale, ink)
    elif kind == "shrink":                                         # 短い棒
        screen.box(int(cx - 1 * scale), int(cy - scale * 0.5), 2 * scale, scale, ink)
    elif kind == "pierce":                                         # 上向きの矢
        screen.box(int(cx - scale * 0.5), int(cy - 1.5 * scale), scale, 3 * scale, ink)
        screen.box(int(cx - 1.5 * scale), int(cy - 1 * scale), 3 * scale, scale, ink)
    elif kind == "slow":                                           # 砂時計（上下の棒）
        screen.box(int(cx - 1.5 * scale), int(cy - 1.5 * scale), 3 * scale, scale, ink)
        screen.box(int(cx - 1.5 * scale), int(cy + 0.5 * scale), 3 * scale, scale, ink)
    elif kind == "magnet":                                         # U の字
        screen.box(int(cx - 1.5 * scale), int(cy - 1.5 * scale), scale, 3 * scale, ink)
        screen.box(int(cx + 0.5 * scale), int(cy - 1.5 * scale), scale, 3 * scale, ink)
        screen.box(int(cx - 1.5 * scale), int(cy + 0.5 * scale), 3 * scale, scale, ink)
    elif kind == "laser":                                          # 縦の光線 2 本
        for dx in (-1.2, 0.8):
            screen.box(int(cx + dx * scale - scale * 0.5), int(cy - 1.5 * scale), scale, 3 * scale, ink)
    elif kind == "fire":                                           # 炎（三角）
        screen.box(int(cx - scale * 0.5), int(cy - 1.5 * scale), scale, scale, ink)
        screen.box(int(cx - 1.5 * scale), int(cy - 0.5 * scale), 3 * scale, 2 * scale, ink)
    elif kind == "add":                                            # 玉 1 つ
        screen.ellipse(cx, cy, 1.3 * scale, 1.3 * scale, ink)
    elif kind == "life":                                           # ＋
        screen.box(int(cx - scale * 0.5), int(cy - 1.5 * scale), scale, 3 * scale, ink)
        screen.box(int(cx - 1.5 * scale), int(cy - scale * 0.5), 3 * scale, scale, ink)
    elif kind == "barrier":                                        # 下線
        screen.box(int(cx - 2.5 * scale), int(cy + 0.8 * scale), 5 * scale, scale, ink)


# ── 端末 ────────────────────────────────────────────────────────────────

def read_keys(fd: int) -> list[str]:
    keys = []
    while select.select([fd], [], [], 0)[0]:
        text = os.read(fd, 64).decode(errors="ignore")
        i = 0
        while i < len(text):
            ch = text[i]
            if ch == "\x1b" and text[i + 1:i + 2] == "[":      # 矢印キー
                arrow = text[i + 2:i + 3]
                if arrow == "C":
                    keys.append("right")
                elif arrow == "D":
                    keys.append("left")
                i += 3
                continue
            if ch in ("a", "j"):
                keys.append("left")
            elif ch in ("d", "l"):
                keys.append("right")
            elif ch in (" ", "\r", "\n"):
                keys.append("go")
            elif ch in ("q", "\x1b"):
                keys.append("quit")
            i += 1
    return keys


KEY_STEP = 12.0                                     # キー 1 回でバーが動く距離


def obey(world: World, key: str) -> str | None:
    """キーを 1 つ受ける。left/right でバー、go で始める・放す。出来事を返す。"""
    if key == "go":
        if not world.started:
            world.started = True
            return None
        return world.launch()
    if key == "left":
        world.nudge(-KEY_STEP)
    elif key == "right":
        world.nudge(KEY_STEP)
    return None


class Speaker:
    def __init__(self):
        import shutil
        import tempfile

        self.player = shutil.which("afplay") or shutil.which("aplay")
        self.folder = tempfile.mkdtemp(prefix="breakout-")
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
    """端末での表示幅（日本語は 2 桁）。"""
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def status(world: World, best: Best, improved: bool = False) -> str:
    """画面の下の 1 行。板と同じ 120 桁に収める。"""
    note = world.note if world.time < world.note_until else ""
    if not world.started:
        note, tail = "スペースで始める", "← → でバー、スペースで放す、q でやめる"
    elif world.over:
        note = ("全部クリア！" if world.won else "ゲームオーバー") + (" ベスト更新！" if improved else "")
        tail = "スペースでもう一度"
    else:
        if world.ball.stuck and not note:
            note = "スペースで放す"
        elif world.has("laser") and not note:
            note = "スペースでレーザー"
        tail = f"ベスト {best.score}（面 {best.stage}）q でやめる"
    head = (f" 面 {world.stage + 1}/{len(STAGES)} {world.stage_name} 残り {world.remaining():2d} 点 {world.score:5d} "
            f"×{world.multiplier} 玉 {world.lives} 速さ {world.speed:3.0f} ")
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

def autopilot(world: World) -> str | None:
    """自動で遊ぶ。玉の落ちてくる x を追い、残っているブロックの方へ角度を付けて返す。"""
    ball = world.ball
    if ball.stuck:
        world.aim(world.paddle_x)
        return world.launch()
    if world.has("laser") and world.time - world.laser_at >= LASER_COOL:
        return world.fire_laser()
    if ball.vy <= 0:
        good = [c for c in world.capsules if c.kind != "shrink"]
        if good:                                    # 玉が上にいる間はカプセルを拾いに行く
            cap = max(good, key=lambda c: c.y)
            world.aim(cap.x)
        else:
            world.aim(ball.x)
        return None
    seconds = (PADDLE_Y - BALL_R - ball.y) / ball.vy
    x = ball.x + ball.vx * seconds
    while x < BALL_R or x > WIDTH - BALL_R:         # 壁で折り返す
        x = -x + 2 * BALL_R if x < BALL_R else 2 * (WIDTH - BALL_R) - x
    targets = [b for b in world.bricks if b.breakable]
    if targets:
        goal = min(targets, key=lambda b: abs(b.rect(world.time)[0] + BRICK_W / 2 - x))
        gx = goal.rect(world.time)[0] + BRICK_W / 2
        want = max(-1.0, min(1.0, math.atan2(gx - x, PADDLE_Y - BRICK_TOP) / MAX_ANGLE))
        x -= want * (PADDLE_W / 2) * 0.8            # 目標の方へ返すには、その逆側で受ける
    world.aim(x)
    return None


def play_out(world: World, limit: float = 600.0) -> dict[str, int]:
    """自動で遊び切る（または limit 秒）。出来事の回数を返す。"""
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


def until(world: World, frames: int = 30) -> str | None:
    """出来事が起きるまで進める（最大 frames コマ）。"""
    for _ in range(frames):
        got = world.update(STEP)
        if got:
            return got
    return None


def check() -> None:
    print("● 面の地図")
    for name, text in STAGES:
        rows = [l for l in text.splitlines() if l.strip()]
        assert all(len(r) == COLS for r in rows), f"{name} の行の長さ"
        assert all(ch == "." or ch in KINDS for r in rows for ch in r), f"{name} に知らない文字"
        assert BRICK_TOP + len(rows) * BRICK_H < PADDLE_Y - 20, f"{name} が低すぎる"
        bricks = parse_stage(text)
        assert sum(1 for b in bricks if b.breakable) > 0, f"{name} に壊せるブロックが無い"
    kinds_used = {ch for _, t in STAGES for ch in t if ch in KINDS}
    assert kinds_used == set(KINDS), "使っていない種類がある"
    print(f"  {len(STAGES)} 面（" + "、".join(f"{n} {len(parse_stage(t))} 個" for n, t in STAGES) + f"）、種類は {len(KINDS)} 文字全部使う")

    print("● 跳ね返り")
    world = World(seed=1)
    world.started = True
    world.bricks = parse_stage("r...........")          # 面が終わらないように 1 つ残す
    world.ball = Ball(x=60, y=40, vx=0, vy=-50, stuck=False)
    world.update(STEP)
    assert world.ball.vy < 0 and world.ball.y < 40
    world.ball = Ball(x=60, y=2, vx=0, vy=-50, stuck=False)
    assert until(world) == "wall" and world.ball.vy > 0, "上の壁で下向きに"
    world.ball = Ball(x=116, y=40, vx=50, vy=-10, stuck=False)
    assert until(world) == "wall" and world.ball.vx < 0, "右の壁で左向きに"
    world.paddle_x = world.target_x = 60
    world.ball = Ball(x=60, y=PADDLE_Y - 3, vx=0, vy=50, stuck=False)
    assert until(world) == "paddle" and abs(world.ball.vx) < 1e-6 and world.ball.vy < 0, "真ん中は真上"
    world.ball = Ball(x=60 + PADDLE_W / 2, y=PADDLE_Y - 3, vx=0, vy=50, stuck=False)
    world.paddle_hits = 0
    assert until(world) == "paddle"
    angle = math.degrees(math.atan2(world.ball.vx, -world.ball.vy))
    assert abs(angle - math.degrees(MAX_ANGLE)) < 1, f"端は {angle:.0f}°"
    world.ball = Ball(x=60, y=HEIGHT + 3, vx=0, vy=50, stuck=False)
    lives = world.lives
    assert until(world) == "lose" and world.lives == lives - 1 and world.ball.stuck, "落とすと 1 つ減って乗り直す"
    print(f"  壁と天井で折り返す、バーの真ん中は真上・端は {math.degrees(MAX_ANGLE):.0f}°、落とすと玉が 1 つ減る")

    print("● ブロック")
    world = World(seed=1)
    world.started = True
    world.bricks = parse_stage("""
....H.......
....r.......
""")
    world.ball = Ball(x=45, y=BRICK_TOP + 2 * BRICK_H + 3, vx=0, vy=-60, stuck=False)
    got = until(world)
    assert got == "brick" and len(world.bricks) == 1 and world.ball.vy > 0 and world.score == 10, (got, world.score)
    world.ball = Ball(x=45, y=BRICK_TOP + 1 * BRICK_H + 3, vx=0, vy=-60, stuck=False)
    assert until(world) == "clank" and world.bricks[0].left == 1, "硬いのは 1 回目はひび"
    world.ball = Ball(x=45, y=BRICK_TOP + 1 * BRICK_H + 3, vx=0, vy=-60, stuck=False)
    assert until(world) == "clear" and world.stage == 1 and world.score == 10 + 20 * 1, world.score
    world = World(seed=1)
    world.started = True
    world.bricks = parse_stage("""
S..........r
""")
    world.ball = Ball(x=5, y=BRICK_TOP + BRICK_H + 3, vx=0, vy=-60, stuck=False)
    assert until(world) == "clank" and len(world.bricks) == 2 and world.ball.vy > 0, "鉄は壊れないが跳ね返る"
    world = World(seed=1)
    world.started = True
    world.bricks = parse_stage("""
rrrSr.......
rXrrr.......
rrrrr.......
""")
    world.ball = Ball(x=15, y=BRICK_TOP + 3 * BRICK_H + 3, vx=0, vy=-60, stuck=False)
    assert until(world) == "brick" and len(world.bricks) == 14
    world.ball = Ball(x=15, y=BRICK_TOP + 2 * BRICK_H + 3, vx=0, vy=-60, stuck=False)
    assert until(world) == "boom", "爆発"
    left = {(b.col, b.row) for b in world.bricks}
    assert left == {(3, 0), (3, 1), (4, 0), (4, 1), (4, 2), (3, 2)}, left     # 周り 8 つが壊れ、鉄 (3,0) は残る
    world = World(seed=1)
    world.started = True
    world.bricks = parse_stage("""
....>......r
""")
    x0 = world.bricks[0].rect(0.0)[0]
    x1 = world.bricks[0].rect(SWAY_PERIOD / 4)[0]
    assert x0 == 40 and abs(x1 - (40 + SWAY)) < 1e-6, "動くブロックは 1/4 周期で右端"
    world = World(seed=1)
    world.started = True
    world.bricks = parse_stage("""
rrrrrrrrrrrr
""")
    world.ball = Ball(x=60, y=BRICK_TOP + BRICK_H + 3, vx=0, vy=-300, stuck=False)   # とても速い
    got = until(world)
    assert got == "brick" and world.ball.vy > 0 and world.ball.y > BRICK_TOP + BRICK_H and len(world.bricks) == 11, "速くてもすり抜けない"
    print("  ふつう 10 点、硬いは 2 回で 20 点、鉄は壊れない、爆発は周り 8 つ、動くのは揺れる、速い玉もすり抜けない")

    print("● 連続と倍率")
    world = World(seed=1)
    world.started = True
    world.bricks = parse_stage("""
rrrrrrr....r
""")
    for brick in list(world.bricks)[:7]:
        world.destroy(brick)
    assert world.streak == 7 and world.multiplier == 3 and world.score == 10 * (1 + 1 + 2 + 2 + 2 + 3 + 3), world.score
    world.paddle_x = world.target_x = 60
    world.ball = Ball(x=60, y=PADDLE_Y - 3, vx=0, vy=50, stuck=False)
    assert until(world) == "paddle" and world.streak == 0 and world.multiplier == 1, "バーに戻ると 0"
    print("  3 個ごとに倍率 +1（×4 まで。壊した直後の連続数で決まる）。7 個で 140 点。バーに戻ると 0")

    print("● 速さの階段")
    world = World(seed=1)
    s0 = world.speed
    world.paddle_hits = 10
    s1 = world.speed
    world.paddle_hits = 100
    s2 = world.speed
    world.stage = 7
    s3 = world.speed
    assert s0 < s1 < s2 < s3 and s2 - s0 == SPEED_HIT_MAX, (s0, s1, s2, s3)
    print(f"  {s0:.0f} → 打ち返し 10 回で {s1:.0f} → 上限 {s2:.0f}、8 面目は {s3:.0f}（1 秒に進むドット）")

    print("● 自動で遊ぶ（全部の面）")
    world = World(seed=3)
    world.lives = 99
    counts = play_out(world, limit=3000)
    assert world.won, f"面 {world.stage + 1} で止まった（{world.time:.0f} 秒）"
    assert counts["clear"] == len(STAGES) - 1 and counts["end"] == 1
    assert counts["boom"] >= 3 and world.caught >= 5, counts
    print(f"  {world.time:.0f} 秒で 8 面クリア、落とした {counts['lose']} 回、壊した {world.broken} 個、点 {world.score}、"
          f"最長 {world.best_streak} 連続、爆発 {counts['boom']} 回、拾った {world.caught} 個（悪いの {counts['bad']}）")
    world = World(seed=4)
    counts = play_out(world, limit=3000)
    assert world.over and (world.won or counts["lose"] == LIVES - 1 and counts["end"] == 1)
    print(f"  玉 3 つでは 面 {world.stage + 1} まで、点 {world.score}（{world.time:.0f} 秒）")

    print("● パワーアップ")
    world = World(seed=1)
    world.started = True
    world.bricks = parse_stage("...........r")
    world.paddle_x = world.target_x = 60

    def drop(kind: str) -> str | None:              # カプセルをバーの真上に落とす（玉は左端で上下するだけ）
        world.capsules = [Capsule(60, PADDLE_Y - 5, kind)]
        world.ball = Ball(x=10, y=30, vx=0, vy=-40, stuck=False)
        return until(world)

    assert drop("wide") == "power" and world.has("wide") and world.paddle_w == PADDLE_W * WIDE_SCALE and world.caught == 1
    assert drop("shrink") == "bad" and not world.has("wide") and world.paddle_w == PADDLE_W * SHRINK_SCALE, "縮むと広いは消える"
    drop("slow")
    slow = world.speed
    assert world.has("slow") and abs(slow / SLOW_SCALE - (SPEED_BASE + min(SPEED_HIT_MAX, SPEED_HIT * world.paddle_hits))) < 1e-9
    world.time = world.powers["slow"] + 0.01
    assert not world.has("slow") and abs(world.speed - slow / SLOW_SCALE) < 1e-9, "時間が来ると切れる"
    drop("split")
    assert len(world.balls) == 3 and all(not b.stuck for b in world.balls), "玉が 3 つ"
    world.balls[1].y = world.balls[2].y = HEIGHT + 5
    world.balls[1].vy = world.balls[2].vy = 50
    lives = world.lives
    until(world)
    assert len(world.balls) == 1 and world.lives == lives, "1 つ残っていれば落とさない"
    drop("magnet")
    world.paddle_x = world.target_x = 60
    world.ball = Ball(x=66, y=PADDLE_Y - 3, vx=0, vy=50, stuck=False)
    assert until(world) == "paddle" and world.ball.stuck and abs(world.ball.offset - 6) < 0.5, "磁石で拾う"
    for _ in range(10):
        world.update(STEP)
    assert world.ball.stuck and abs(world.ball.x - (world.paddle_x + 6)) < 0.5, "乗ったまま動く"
    assert world.launch() == "launch" and world.ball.vx > 0 and world.ball.vy < 0, "拾った位置の角度で放す"
    world = World(seed=1)
    world.started = True
    world.bricks = parse_stage("""
rrrrrrrrrrrr
rrrrrrrrrrrr
""")
    world.powers["pierce"] = 99.0
    world.ball = Ball(x=65, y=BRICK_TOP + 2 * BRICK_H + 3, vx=0, vy=-50, stuck=False)
    for _ in range(10):
        world.update(STEP)
    assert world.ball.vy < 0 and world.ball.y < BRICK_TOP and len(world.bricks) == 22, "貫通は止まらず 2 つ壊す"
    world = World(seed=1)
    world.started = True
    world.bricks = parse_stage("""
....S......r
....H.......
....r.......
""")
    world.paddle_x = world.target_x = 45
    world.powers["laser"] = 99.0
    world.ball = Ball(x=100, y=40, vx=0, vy=-40, stuck=False)
    assert world.launch() == "laser" and len(world.bricks) == 3 and world.laser_top == BRICK_TOP + 3 * BRICK_H, "一番下を撃つ"
    assert world.launch() is None, "連射は間を置く"
    world.time += LASER_COOL + 0.01
    assert world.launch() == "laser" and world.bricks[1].left == 1, "硬いのは 1 回で削れる"
    world.time += LASER_COOL + 0.01
    world.launch()
    world.time += LASER_COOL + 0.01
    assert world.launch() == "laser" and len(world.bricks) == 2 and world.laser_top == BRICK_TOP + BRICK_H, "鉄で止まる"
    world.balls = [Ball(stuck=True)]
    world.time += LASER_COOL + 0.01
    assert world.launch() == "launch", "乗っている玉があれば放すのが先"
    world = World(seed=1)
    world.started = True
    world.bricks = parse_stage("""
....S.......
...rrr......
....r.......
""")
    world.powers["fire"] = 99.0
    world.ball = Ball(x=45, y=BRICK_TOP + 3 * BRICK_H + 3, vx=0, vy=-50, stuck=False)
    assert until(world) == "brick" and {(b.col, b.row) for b in world.bricks} == {(4, 0), (3, 1), (5, 1)}, "火の玉は上（4,1）も壊す。斜めは残る"
    world = World(seed=1)
    world.started = True
    world.bricks = parse_stage("...........r")
    world.paddle_x = world.target_x = 60
    world.ball = Ball(x=10, y=30, vx=0, vy=-40, stuck=False)
    world.capsules = [Capsule(60, PADDLE_Y - 5, "add")]
    assert until(world) == "power" and len(world.balls) == 2 and world.balls[1].stuck, "玉が 1 つ足される"
    world.balls = [Ball(stuck=False, x=10, y=30, vy=-40)] * 1 + [Ball(stuck=True) for _ in range(MAX_BALLS - 1)]
    world.capsules = [Capsule(60, PADDLE_Y - 5, "add")]
    until(world)
    assert len(world.balls) == MAX_BALLS, "上限 5"
    world.lives = 3
    world.ball = Ball(x=10, y=30, vx=0, vy=-40, stuck=False)
    world.capsules = [Capsule(60, PADDLE_Y - 5, "life")]
    assert until(world) == "life" and world.lives == 4
    world.lives = MAX_LIVES
    world.ball = Ball(x=10, y=30, vx=0, vy=-40, stuck=False)
    world.capsules = [Capsule(60, PADDLE_Y - 5, "life")]
    until(world)
    assert world.lives == MAX_LIVES, "残機の上限 5"
    world.ball = Ball(x=10, y=30, vx=0, vy=-40, stuck=False)
    world.capsules = [Capsule(60, PADDLE_Y - 5, "barrier")]
    assert until(world) == "power" and world.barrier
    world.ball = Ball(x=10, y=HEIGHT - 6, vx=0, vy=50, stuck=False)
    lives = world.lives
    assert until(world) == "paddle" and world.ball.vy < 0 and not world.barrier and world.lives == lives, "バリアは 1 回だけ跳ね返す"
    world.ball = Ball(x=10, y=HEIGHT - 6, vx=0, vy=50, stuck=False)
    assert until(world, 60) == "lose", "2 回目は落ちる"
    weights = sum(p["weight"] for p in POWERS.values())
    print(f"  {len(POWERS)} 種（" + "、".join(f"{p['word']} {p['weight'] * 100 // weights}%" for p in POWERS.values()) + f"）、落ちる確率 {DROP_RATE:.0%}。"
          "広い/縮むは入れ替わり、時間で切れる、分裂は 3 つ、1 つ残れば落とさない、磁石は拾った角度で放す、貫通は止まらない、\n"
          "  レーザーは真上の一番下を撃ち鉄で止まる、火の玉は上下左右も、玉を足す（5 つまで）、1UP（5 つまで）、バリアは 1 回だけ")

    print("● 演出")
    world = World(seed=1)
    world.started = True
    world.bricks = parse_stage("rrrrrrrrrrrr")
    world.ball = Ball(x=60, y=BRICK_TOP + BRICK_H + 3, vx=0, vy=-50, stuck=False)
    until(world)
    assert world.time < world.shake_until and world.shake_size >= 1.0 and world.sparks, "壊すと揺れて粒が出る"
    assert 1 <= len(world.ball.trail) <= TRAIL, "残像"
    small = Screen()
    draw(small, world)
    world.streak = 12
    assert world.multiplier == 4
    draw(small, world)
    print("  壊すと揺れ（爆発は大きく）、残像、×4 で玉が金色、残り 3 個で点滅、面クリアで花火")

    print("● 板の大きさ")
    world = World(seed=2)
    world.lives = 99
    play_out(world, limit=20)
    small, big = Screen(), Screen(WIDTH * 4, HEIGHT * 4)
    started = time.perf_counter()
    draw(small, world)
    took_small = time.perf_counter() - started
    started = time.perf_counter()
    draw(big, world)
    took_big = time.perf_counter() - started
    same = sum(1 for y in range(HEIGHT) for x in range(WIDTH)
               if all(abs(a - b) <= 6 for a, b in zip(small.pixel(x, y), big.pixel(x * 4 + 2, y * 4 + 2))))   # 背景の階調は少しずれる
    print(f"  {WIDTH}×{HEIGHT} を描くのに {took_small * 1000:.1f} ms、{WIDTH * 4}×{HEIGHT * 4} は {took_big * 1000:.1f} ms。一致 {same * 100 // (WIDTH * HEIGHT)}%")
    assert same > WIDTH * HEIGHT * 0.9

    print("● 記録と音と状態行")
    best = Best.parse(Best(120, 3).dump())
    assert (best.score, best.stage) == (120, 3) and Best.parse("xx").score == 0
    world = World(seed=1)
    world.score, world.stage = 200, 4
    assert best.take(world) and best.stage == 5
    world.score = 50
    assert not best.take(world) and best.score == 200
    assert len({sound_bytes(k) for k in SOUNDS}) == len(SOUNDS)
    world = World(seed=1)
    for started, over in ((False, False), (True, False), (True, True)):
        world.started, world.over = started, over
        world.tell("面 8：最後の砦", 9)
        assert columns(status(world, best, True)) == WIDTH, columns(status(world, best, True))
    print(f"  ベストは点で更新、面は到達した最大。音は {len(SOUNDS)} つ全部別。状態行は {WIDTH} 桁ちょうど")
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
    """遊んでいる場面（面ごと）を PNG に。path が stage.png なら stage1.png … と書き出す。"""
    base, ext = os.path.splitext(path)
    for index in range(len(STAGES)):
        world = World(seed=5)
        world.lives = 99
        world.load_stage(index)
        play_out(world, limit=6.0)
        screen = Screen(WIDTH * 5, HEIGHT * 5)
        draw(screen, world)
        with open(f"{base}{index + 1}{ext}", "wb") as out:
            out.write(png_bytes(screen, 1))
    print(f"{base}1{ext} 〜 {base}{len(STAGES)}{ext} に書き出した")


def main() -> None:
    if "--check" in sys.argv:
        check()
    elif "--sheet" in sys.argv:
        sheet(sys.argv[sys.argv.index("--sheet") + 1] if len(sys.argv) > 2 else "stage.png")
    else:
        run()


if __name__ == "__main__":
    main()
