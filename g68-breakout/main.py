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


EVENTS = ("end", "clear", "lose", "boom", "brick", "clank", "paddle", "wall", "launch")   # 目立つ順
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
    ball: Ball = field(default_factory=Ball)
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
    pause_until: float = 0.0                        # 面が変わるときの間
    note: str = ""
    note_until: float = 0.0
    sparks: list[Spark] = field(default_factory=list)
    flash_until: float = 0.0                        # バーが光る

    def __post_init__(self):
        self.luck = random.Random(self.seed)
        self.load_stage(0)

    # ── 面 ──
    def load_stage(self, index: int) -> None:
        self.stage = index
        self.bricks = parse_stage(STAGES[index][1])
        self.reset_ball()

    def reset_ball(self) -> None:
        self.ball = Ball(x=self.paddle_x, y=PADDLE_Y - BALL_R, stuck=True)
        self.paddle_hits = 0
        self.streak = 0

    @property
    def stage_name(self) -> str:
        return STAGES[self.stage][0]

    @property
    def multiplier(self) -> int:
        return min(4, 1 + self.streak // STREAK_STEP)

    @property
    def speed(self) -> float:
        return SPEED_BASE + SPEED_STAGE * self.stage + min(SPEED_HIT_MAX, SPEED_HIT * self.paddle_hits)

    def remaining(self) -> int:
        return sum(1 for b in self.bricks if b.breakable)

    def tell(self, text: str, seconds: float = 1.5) -> None:
        self.note, self.note_until = text, self.time + seconds

    # ── 入力 ──
    def launch(self) -> str | None:
        """玉を放す。乗っていなければ何もしない。"""
        if not self.ball.stuck or self.time < self.pause_until:
            return None
        self.ball.stuck = False
        side = 1 if self.luck.random() < 0.5 else -1
        self.ball.vx = self.speed * math.sin(LAUNCH_ANGLE) * side
        self.ball.vy = -self.speed * math.cos(LAUNCH_ANGLE)
        return "launch"

    def aim(self, x: float) -> None:
        """バーの目標の中心を決める（指・傾き・自動）。"""
        self.target_x = max(PADDLE_W / 2, min(WIDTH - PADDLE_W / 2, x))

    def nudge(self, dx: float) -> None:
        """キーで少しずらす。"""
        self.aim(self.target_x + dx)

    # ── 進める ──
    def update(self, dt: float) -> str | None:
        if not self.started or self.over:
            return None
        self.time += dt
        step = max(-PADDLE_SPEED * dt, min(PADDLE_SPEED * dt, self.target_x - self.paddle_x))
        self.paddle_x = max(PADDLE_W / 2, min(WIDTH - PADDLE_W / 2, self.paddle_x + step))
        self.age_sparks(dt)
        if self.time < self.pause_until:
            return None
        ball = self.ball
        if ball.stuck:
            ball.x, ball.y = self.paddle_x, PADDLE_Y - BALL_R
            return None
        happened = set()
        speed = self.speed                          # 向きはそのまま、速さだけそろえる
        length = math.hypot(ball.vx, ball.vy) or 1.0
        ball.vx, ball.vy = ball.vx / length * speed, ball.vy / length * speed
        steps = max(1, math.ceil(speed * dt / 1.0))  # 1 ドットずつ歩む
        hit_now: set[int] = set()
        for _ in range(steps):
            happened |= self.walk(dt / steps, hit_now)
            if self.over or ball.stuck:
                break
        if self.remaining() == 0 and not self.over:
            happened.add(self.next_stage())
        for name in EVENTS:
            if name in happened:
                return name
        return None

    def walk(self, dt: float, hit_now: set[int]) -> set[str]:
        """玉を少し進める。x を動かして調べ、次に y を動かして調べる。"""
        ball, happened = self.ball, set()
        ball.x += ball.vx * dt
        if ball.x - BALL_R < 0:
            ball.x, ball.vx = BALL_R, abs(ball.vx)
            happened.add("wall")
        elif ball.x + BALL_R > WIDTH:
            ball.x, ball.vx = WIDTH - BALL_R, -abs(ball.vx)
            happened.add("wall")
        happened |= self.hit_bricks("x", hit_now)
        ball.y += ball.vy * dt
        if ball.y - BALL_R < 0:
            ball.y, ball.vy = BALL_R, abs(ball.vy)
            happened.add("wall")
        happened |= self.hit_bricks("y", hit_now)
        if ball.vy > 0 and ball.y + BALL_R >= PADDLE_Y and ball.y - BALL_R <= PADDLE_Y + PADDLE_H \
                and abs(ball.x - self.paddle_x) <= PADDLE_W / 2 + BALL_R:
            self.bounce_paddle()
            happened.add("paddle")
        if ball.y - BALL_R > HEIGHT:                # 落とした
            happened.add(self.lose_ball())
        return happened

    def bounce_paddle(self) -> None:
        """当たった場所で角度が決まる。真ん中は真上、端は MAX_ANGLE。"""
        ball = self.ball
        offset = max(-1.0, min(1.0, (ball.x - self.paddle_x) / (PADDLE_W / 2)))
        angle = offset * MAX_ANGLE
        self.paddle_hits += 1
        speed = self.speed
        ball.vx, ball.vy = speed * math.sin(angle), -speed * math.cos(angle)
        ball.y = PADDLE_Y - BALL_R
        self.streak = 0
        self.flash_until = self.time + 0.12

    def hit_bricks(self, axis: str, hit_now: set[int]) -> set[str]:
        ball, happened = self.ball, set()
        for index, brick in enumerate(self.bricks):
            bx, by, bw, bh = brick.rect(self.time)
            if not (ball.x + BALL_R > bx and ball.x - BALL_R < bx + bw and ball.y + BALL_R > by and ball.y - BALL_R < by + bh):
                continue
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
            if index not in hit_now:
                hit_now.add(index)
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
        if self.multiplier > 1:
            self.tell(f"{self.streak} 連続 ×{self.multiplier}", 1.0)
        if brick.kind == "X":                       # 周り 8 つも壊す（鉄は残る。爆発は連鎖する）
            self.burst(bx + bw / 2, by + bh / 2, (255, 200, 80), 14)
            for other in list(self.bricks):
                if other.breakable and abs(other.col - brick.col) <= 1 and abs(other.row - brick.row) <= 1:
                    self.destroy(other)
            return "boom"
        return "brick"

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

    def lose_ball(self) -> str:
        self.lives -= 1
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
    for y in range(screen.height):                  # 上から下へ少し明るく
        t = y / screen.height
        screen.band(y, y + 1, tuple(int(a + (b - a) * t) for a, b in zip(BACK_TOP, BACK_BOTTOM)))
    for brick in world.bricks:
        bx, by, bw, bh = brick.rect(world.time)
        color = KINDS[brick.kind]["color"]
        if brick.kind == "H" and brick.left == 1:
            color = shade(color, 0.7)
        x0, y0 = int(bx * scale), int(by * scale)
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
    for s in world.sparks:
        screen.box(int(s.x * scale), int(s.y * scale), scale, scale, s.color)
    px = int((world.paddle_x - PADDLE_W / 2) * scale)              # バー
    paddle = SHINE if world.time < world.flash_until else PADDLE
    screen.box(px, PADDLE_Y * scale, PADDLE_W * scale, PADDLE_H * scale, paddle)
    screen.box(px, PADDLE_Y * scale, scale, PADDLE_H * scale, PADDLE_EDGE)
    screen.box(px + (PADDLE_W - 1) * scale, PADDLE_Y * scale, scale, PADDLE_H * scale, PADDLE_EDGE)
    ball = world.ball                                              # 玉
    screen.ellipse(ball.x * scale, ball.y * scale, BALL_R * scale, BALL_R * scale, BALL_SHADE)
    screen.ellipse(ball.x * scale - scale * 0.3, ball.y * scale - scale * 0.3, BALL_R * scale * 0.7, BALL_R * scale * 0.7, BALL)
    for i in range(world.lives - 1):                               # 残りの玉（左上）
        screen.ellipse((3 + i * 4) * scale, 2.5 * scale, 1.2 * scale, 1.2 * scale, LIFE)


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
    if ball.vy <= 0:
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
    assert counts["boom"] >= 3, counts
    print(f"  {world.time:.0f} 秒で 8 面クリア、落とした {counts['lose']} 回、壊した {world.broken} 個、点 {world.score}、"
          f"最長 {world.best_streak} 連続、爆発 {counts['boom']} 回")
    world = World(seed=4)
    counts = play_out(world, limit=3000)
    assert world.over and (world.won or counts["lose"] == LIVES - 1 and counts["end"] == 1)
    print(f"  玉 3 つでは 面 {world.stage + 1} まで、点 {world.score}（{world.time:.0f} 秒）")

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
