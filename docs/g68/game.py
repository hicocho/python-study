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
                               f"点 {world.score}、面 {world.stage + 1}、壊した {world.broken} 個、最長 {world.best_streak} 連続"
                               + ("  ベスト更新！" if improved else ""))
    elif not world.started:
        message.textContent = ("「スタート」で始める。画面のどこでも指を左右に動かすとバーが追いかける（← → キーでも）。"
                               "タップ（スペース）で玉を放す。玉は 3 つ、8 面")
    elif world.ball.stuck:
        message.textContent = "タップ（スペース）で玉を放す"
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
