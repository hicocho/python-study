"""ブロック崩し ブラウザ版

CLI 版（g68-breakout/main.py）と中身はまったく同じ。面の地図（STAGES）も、玉の歩みと当たり判定（World.walk）も、
点と連続（World.destroy）も、絵を置く処理（draw）も 1 文字も変えていない。

違うのは入口と出口だけ。
  入口: 端末は ← → キー、ブラウザは指のスライド（画面のどこでも）・傾き・← → キー
  出口: 端末は ▀ の並び、ブラウザは canvas（5 倍の板）。音は端末が afplay、ブラウザは Audio
  記録: 端末は records.json、ブラウザは localStorage。中身の形（Best.dump）は同じ
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

from pyodide.ffi import create_proxy
from pyscript import document, when, window


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


DROP_RATE = 0.12                                    # ブロックを壊したときにカプセルが落ちる確率


CAPSULE_SPEED = 22.0                                # カプセルの落ちる速さ


CAPSULE_W = 7.0


CAPSULE_H = 3.6


WIDE_SCALE = 1.5                                    # 広いバー


SHRINK_SCALE = 0.6                                  # 縮んだバー


SLOW_SCALE = 0.65                                   # ゆっくり


SPLIT_ANGLE = math.radians(25)                      # 分裂した玉の開き


POWERS = {
    "split": dict(word="玉が 3 つ！", seconds=0.0, weight=22, color=(120, 200, 255)),
    "wide": dict(word="バーが広い", seconds=12.0, weight=22, color=(110, 220, 120)),
    "pierce": dict(word="貫通！", seconds=8.0, weight=14, color=(255, 120, 60)),
    "slow": dict(word="ゆっくり", seconds=8.0, weight=16, color=(240, 220, 90)),
    "magnet": dict(word="磁石：拾って狙う", seconds=10.0, weight=14, color=(200, 130, 255)),
    "shrink": dict(word="バーが縮んだ…", seconds=8.0, weight=12, color=(160, 160, 170)),
}


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


EVENTS = ("end", "clear", "lose", "boom", "power", "bad", "brick", "clank", "paddle", "wall", "launch")   # 目立つ順


SOUNDS = EVENTS + ("best",)


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


def shade(color: tuple[int, int, int], k: float) -> tuple[int, int, int]:
    return tuple(max(0, min(255, int(c * k))) for c in color)


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

    def __post_init__(self):
        self.luck = random.Random(self.seed)
        self.load_stage(0)

    # ── 面 ──
    def load_stage(self, index: int) -> None:
        self.stage = index
        self.bricks = parse_stage(STAGES[index][1])
        self.capsules = []
        self.powers = {}
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
        """乗っている玉を放す。乗っていなければ何もしない。"""
        if self.time < self.pause_until:
            return None
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
                c, s = math.cos(turn), math.sin(turn)
                self.balls.append(Ball(source.x, source.y, source.vx * c - source.vy * s, source.vx * s + source.vy * c, stuck=False))
            if source.stuck:                        # 乗っている玉から分けたときは、分身だけ上へ放す
                for b in self.balls[-2:]:
                    b.vx, b.vy = self.speed * math.sin(LAUNCH_ANGLE) * (1 if b is self.balls[-1] else -1), -self.speed * math.cos(LAUNCH_ANGLE)
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
    half = world.paddle_w / 2
    px = int((world.paddle_x - half + ox) * scale)                  # バー
    py = int((PADDLE_Y + oy) * scale)
    paddle = SHINE if world.time < world.flash_until else PADDLE
    if world.has("magnet"):
        paddle = MAGNET
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
# --- ここから下はブラウザ版だけ。CLI 版の run() / Screen.render() / Speaker / status() にあたる ---

SCALE = 5                                           # ブラウザは 5 倍の板（600 × 420）に描く
canvas = document.querySelector("#screen")
ctx = canvas.getContext("2d")
ctx.imageSmoothingEnabled = False
image = ctx.createImageData(WIDTH * SCALE, HEIGHT * SCALE)
stage_label = document.querySelector("#stage")
left_label = document.querySelector("#left")
score_label = document.querySelector("#score")
streak_label = document.querySelector("#streak")
lives_label = document.querySelector("#lives")
speed_label = document.querySelector("#speed")
best_label = document.querySelector("#best")
fps_label = document.querySelector("#fps")
note_label = document.querySelector("#note")
message = document.querySelector("#message")
again_button = document.querySelector("#again")
go_button = document.querySelector("#go")
SAVED = "g68-best"


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
held = {"left": False, "right": False}              # 押しっぱなしのキー


def refresh() -> None:
    draw(screen, world)
    screen.flush()
    stage_label.textContent = f"{world.stage + 1}/{len(STAGES)} {world.stage_name}"
    left_label.textContent = str(world.remaining())
    score_label.textContent = str(world.score)
    streak_label.textContent = f"{world.streak}（×{world.multiplier}）"
    lives_label.textContent = str(world.lives)
    speed_label.textContent = f"{world.speed:.0f}"
    best_label.textContent = f"{best.score}（面 {best.stage}）"
    note_label.textContent = (world.note if world.time < world.note_until else "") or " "
    if world.over:
        message.textContent = (("全部クリア！ " if world.won else "ゲームオーバー。") +
                               f"点 {world.score}、面 {world.stage + 1}、壊した {world.broken} 個、最長 {world.best_streak} 連続、拾った {world.caught} 個"
                               + ("  ベスト更新！" if improved else ""))
    elif not world.started:
        message.textContent = ("「スタート」で始める。画面のどこでも指を左右に動かすとバーが追いかける（← → キーでも）。"
                               "タップ（スペース）で玉を放す。玉は 3 つ、8 面")
    elif world.ball.stuck:
        message.textContent = "タップ（スペース）で玉を放す" + ("（磁石：拾った場所の角度で飛ぶ）" if world.has("magnet") else "")
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
            if held["left"] != held["right"]:       # キーは押している間ずっと動く
                world.nudge(-PADDLE_SPEED * STEP if held["left"] else PADDLE_SPEED * STEP)
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


KEYS = {"ArrowLeft": "left", "a": "left", "ArrowRight": "right", "d": "right"}


def wake_sound() -> None:
    """Safari は人が触った処理の中でしか音を始められない。最初の操作で一度だけ鳴らして起こす。"""
    if not wake_sound.done:
        wake_sound.done = True
        speaker.say("launch")


wake_sound.done = False


@when("keydown", "body")
def on_down(event):
    if event.key in KEYS:
        event.preventDefault()
        if not event.repeat:
            held[KEYS[event.key]] = True
            world.aim(world.paddle_x)               # 指の目標を捨ててキーに従う
    elif event.key in (" ", "Enter"):
        event.preventDefault()
        if not event.repeat:
            speaker.say(obey(world, "go"))
            refresh()


@when("keyup", "body")
def on_up(event):
    if event.key in KEYS:
        held[KEYS[event.key]] = False


def finger_x(event) -> float:
    rect = canvas.getBoundingClientRect()
    return (event.clientX - rect.left) / rect.width * WIDTH


@when("pointerdown", "#screen")
def press(event):
    """タップ：始める・玉を放す。指の x をバーの目標に。"""
    event.preventDefault()
    wake_sound()
    if not world.started:
        obey(world, "go")
    elif world.ball.stuck:
        speaker.say(world.launch())
    world.aim(finger_x(event))
    refresh()


@when("pointermove", "#screen")
def slide(event):
    """画面のどこでも、指（マウス）の x をバーが追いかける。"""
    if tilt["on"]:
        return
    if event.pointerType == "mouse" and event.buttons == 0 and not world.started:
        return
    event.preventDefault()
    world.aim(finger_x(event))


@when("click", "#go")
def go(event):
    wake_sound()
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


# --- スマホの傾きで操作（DeviceOrientation）。gamma（左右の傾き）→ バーの位置。
#   iPhone は「傾きで操作」を押した処理の中で許可を求める必要がある（requestPermission）。
tilt = {"on": False}
tilt_button = document.querySelector("#tilt")
tilt_stop = document.querySelector("#tilt-stop")
tilt_note = document.querySelector("#tilt-note")
TILT_FULL = 15.0                                    # 15° 傾けると端まで


def on_orientation(event):
    if not tilt["on"]:
        return
    try:
        gamma = float(event.gamma)
    except (TypeError, ValueError):                 # 値が無いイベント（JS の null）は無視
        return
    lean = max(-1.0, min(1.0, gamma / TILT_FULL))
    world.aim(WIDTH / 2 + lean * (WIDTH / 2 - PADDLE_W / 2))


def enable_tilt(granted: bool) -> None:
    if not granted:
        tilt_note.textContent = "傾きの利用が許可されませんでした。指のスライドで操作してください"
        return
    tilt["on"] = True
    window.addEventListener("deviceorientation", create_proxy(on_orientation))
    tilt_button.hidden = True
    tilt_stop.hidden = False
    tilt_note.textContent = "傾きで操作しています：左右に 15° 傾けると端まで動きます。「傾きをやめる」で指に戻ります"


@when("click", "#tilt")
def ask_tilt(event):
    request = getattr(window.DeviceOrientationEvent, "requestPermission", None)
    if request is None:                             # Android など：許可なしで使える
        enable_tilt(True)
        return
    def done(state):
        enable_tilt(str(state) == "granted")
    def failed(error):
        enable_tilt(False)
    request().then(create_proxy(done)).catch(create_proxy(failed))


@when("click", "#tilt-stop")
def stop_tilt(event):
    tilt["on"] = False
    tilt_button.hidden = False
    tilt_stop.hidden = True
    tilt_note.textContent = "傾きで操作するには、上のボタンを押して許可してください（スマホ・タブレット）"


refresh()
document.querySelector("#loading").hidden = True
asyncio.ensure_future(loop())
