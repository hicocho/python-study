"""深宇宙シューティング

宇宙船で星雲の中を奥へ進みながら、迫ってくる小惑星を撃つ。60 秒のステージ、体力 3・残機 3。
今回の主題は「中身は Python、絵はブラウザで Three.js」。端末は同じ中身を透視投影の丸と点で描く。
今回覚えるところ：
  奥行きのある世界     x（左右）y（上下）z（奥行き）で物を持ち、カメラは機体の少し後ろ上を追う
  透視投影 1 行        画面の位置 = 中心 + FOCUS × (物 − カメラ) / 奥行き。端末はこの式だけで描く
  球の当たり判定       弾と小惑星、機体と小惑星は「距離 < 半径の和」
  割れる小惑星         大 → 中 2 つ → 小 2 つ（g78）。点は小さいほど高い
  ブラウザは Three.js  同じ世界を PyScript から Three.js の物に写す（docs/g69/game.py の尻尾）

    python3 main.py            遊ぶ（スペースで始める・撃つ。矢印か w a s d で機体。q でやめる）
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

# ── 板と世界の決まり ─────────────────────────────────────────────────────

WIDTH = 120                                         # 端末の板（ドット）
HEIGHT = 80
STEP = 1 / 30
FOCUS = 70.0                                        # 透視投影の焦点距離（板のドット）
CX = WIDTH / 2
CY = HEIGHT / 2
NEAR = 1.0                                          # カメラよりこれ以上手前は描かない
X_MAX = 36.0                                        # 機体が動ける範囲（世界の単位）
Y_MAX = 16.0
FAR = 240.0                                         # 小惑星が現れる奥行き
BEHIND = -14.0                                      # ここより手前に来た物は消す
CAM_FOLLOW = 0.7                                    # カメラは機体の位置にこの割合で付いていく
CAM_UP = 5.0                                        # カメラは機体より上に
CAM_BACK = 22.0                                     # カメラは機体より後ろに
SHIP_R = 2.4                                        # 機体の当たりの半径
SHIP_SPEED = 70.0                                   # 機体が目標へ動く速さ（1 秒あたり）
LASER_SPEED = 220.0
LASER_R = 0.8
SHOT_GAP = 0.16                                     # 連射の間隔
HP = 3                                              # 体力（体当たり 3 回で 1 機失う）
LIVES = 3
SAFE_TIME = 1.6                                     # 当たった直後の無敵
STREAK_STEP = 5                                     # 連続 5 発ごとに倍率 +1（×4 まで）
STAGE_PAUSE = 2.5
STAR_COUNT = 140                                    # 端末の星の数
STAR_SPEED = 30.0                                   # 星が流れる速さ（奥行きの感じ）
STAR_DEPTH = 320.0

# 小惑星の大きさ。size 2 が大、1 が中、0 が小。割れると 1 つ下の大きさ 2 つに
ROCKS = {
    2: dict(name="大", r=6.0, points=10, weight=35),
    1: dict(name="中", r=3.5, points=20, weight=40),
    0: dict(name="小", r=2.0, points=40, weight=25),
}
AIMED = 0.55                                        # 機体を狙って飛んでくる小惑星の割合

# ステージ。interval は出る間隔（始め → 終わり）、speed は小惑星の速さ（始め → 終わり）、sky は空の色（ブラウザの霧と背景）
STAGES = [
    dict(name="星雲の入口", seconds=60.0, interval=(1.1, 0.5), speed=(45.0, 70.0), sky=(7, 7, 20), nebula=(80, 60, 140)),
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


def sweep(start: float, end: float, seconds: float, volume: float = VOLUME) -> array:
    """音の高さが start から end へ滑る（レーザー）。"""
    count = int(RATE * seconds)
    samples = array("h")
    phase = 0.0
    for i in range(count):
        hz = start + (end - start) * i / count
        phase += math.tau * hz / RATE
        fade = min(1.0, (count - i) / (RATE / 100))
        samples.append(int(32767 * volume * fade * math.sin(phase)))
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
    if kind == "shoot":                             # レーザー（ピュゥ）
        samples = sweep(1600, 700, 0.07, VOLUME * 0.7)
    elif kind == "hit":                             # 小惑星が割れる（パリッ）
        samples = noise(0.08, VOLUME * 1.1, 45.0, 3) + tone(900, 0.04, VOLUME * 0.6)
    elif kind == "boom":                            # 大きいのが砕ける
        samples = noise(0.3, VOLUME * 1.7, 12.0, 9) + tone(110, 0.15, VOLUME * 0.8)
    elif kind == "ouch":                            # 体当たり
        samples = noise(0.2, VOLUME * 1.4, 20.0, 5) + sweep(400, 150, 0.2, VOLUME * 0.8)
    elif kind == "lose":                            # 1 機失う
        samples = sweep(600, 120, 0.5, VOLUME * 0.9)
    elif kind == "clear":                           # ステージクリア
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


EVENTS = ("end", "clear", "lose", "ouch", "boom", "hit", "shoot")   # 目立つ順
SOUNDS = EVENTS + ("best",)

# ── 色（端末） ──────────────────────────────────────────────────────────

ROCK_COLOR = (150, 140, 125)
ROCK_DARK = (90, 84, 76)
LASER = (120, 250, 255)
SHIP = (220, 225, 240)
SHIP_DARK = (140, 150, 190)
ENGINE = (255, 170, 60)
STAR = (200, 205, 230)
SPARK = (255, 200, 90)
GAUGE = (60, 60, 80)
GAUGE_ON = (120, 220, 255)
HP_ON = (110, 230, 130)
HP_OFF = (60, 70, 70)


def shade(color: tuple[int, int, int], k: float) -> tuple[int, int, int]:
    return tuple(max(0, min(255, int(c * k))) for c in color)


# ── 板（g67・g68 と同じ） ───────────────────────────────────────────────

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


# ── 世界の物 ────────────────────────────────────────────────────────────

@dataclass
class Ship:
    x: float = 0.0
    y: float = 0.0
    vx: float = 0.0                                 # 見た目の傾きに使う
    vy: float = 0.0
    hp: int = HP
    safe_until: float = 0.0                         # 無敵の終わり


@dataclass
class Rock:
    x: float
    y: float
    z: float
    vx: float
    vy: float
    vz: float
    size: int
    uid: int = 0
    spin: float = 0.0                               # 回る速さ（見た目）
    seed: int = 0                                   # 形の種

    @property
    def r(self) -> float:
        return ROCKS[self.size]["r"]


@dataclass
class Laser:
    x: float
    y: float
    z: float
    uid: int = 0


@dataclass
class Spark:
    x: float
    y: float
    z: float
    vx: float
    vy: float
    vz: float
    life: float
    color: tuple[int, int, int] = SPARK


@dataclass
class Best:
    score: int = 0
    stage: int = 0

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


def camera_at(ship: Ship) -> tuple[float, float, float]:
    """カメラの位置。機体の少し後ろ上を、機体の動きに 7 割だけ付いていく。"""
    return ship.x * CAM_FOLLOW, ship.y * CAM_FOLLOW + CAM_UP, -CAM_BACK


def project(x: float, y: float, z: float, cam: tuple[float, float, float]) -> tuple[float, float, float] | None:
    """世界の点 → 板の (sx, sy, k)。k は 1 世界単位が何ドットか。カメラより手前なら None。"""
    depth = z - cam[2]
    if depth < NEAR:
        return None
    k = FOCUS / depth
    return CX + (x - cam[0]) * k, CY - (y - cam[1]) * k, k


@dataclass
class World:
    seed: int = 0
    start: int = 0
    stage: int = 0
    ship: Ship = field(default_factory=Ship)
    target_x: float = 0.0                           # 指（キー）が指している位置
    target_y: float = 0.0
    firing: bool = False                            # 押している間ずっと撃つ
    rocks: list[Rock] = field(default_factory=list)
    lasers: list[Laser] = field(default_factory=list)
    sparks: list[Spark] = field(default_factory=list)
    time: float = 0.0
    stage_start: float = 0.0
    started: bool = False
    over: bool = False
    won: bool = False
    lives: int = LIVES
    score: int = 0
    streak: int = 0
    best_streak: int = 0
    hits: int = 0
    shots: int = 0
    escaped: int = 0                                # 撃たずに後ろへ流れた小惑星
    next_rock: float = 0.8
    next_shot: float = 0.0
    pause_until: float = 0.0
    note: str = ""
    note_until: float = 0.0
    shake_until: float = 0.0
    shake_size: float = 0.0
    counter: int = 0                                # uid の元

    def __post_init__(self):
        self.luck = random.Random(self.seed)
        self.stage = self.start

    # ── 面 ──
    @property
    def spec(self) -> dict:
        return STAGES[self.stage]

    @property
    def stage_name(self) -> str:
        return self.spec["name"]

    def stage_left(self) -> float:
        return max(0.0, self.stage_start + self.spec["seconds"] - self.time)

    def progress(self) -> float:
        """ステージの進み具合 0〜1（難しさの階段の目盛り）。"""
        return max(0.0, min(1.0, (self.time - self.stage_start) / self.spec["seconds"]))

    def interval(self) -> float:
        a, b = self.spec["interval"]
        return a + (b - a) * self.progress()

    def rock_speed(self) -> float:
        a, b = self.spec["speed"]
        return a + (b - a) * self.progress()

    @property
    def multiplier(self) -> int:
        return min(4, 1 + self.streak // STREAK_STEP)

    def tell(self, text: str, seconds: float = 1.5) -> None:
        self.note, self.note_until = text, self.time + seconds

    def shake(self, size: float, seconds: float = 0.25) -> None:
        self.shake_size = max(self.shake_size if self.time < self.shake_until else 0.0, size)
        self.shake_until = self.time + seconds

    def next_uid(self) -> int:
        self.counter += 1
        return self.counter

    # ── 入力 ──
    def aim(self, x: float, y: float) -> None:
        """機体の目標（指・傾き・自動）。枠の中に収める。"""
        self.target_x = max(-X_MAX, min(X_MAX, x))
        self.target_y = max(-Y_MAX, min(Y_MAX, y))

    def nudge(self, dx: float, dy: float) -> None:
        self.aim(self.target_x + dx, self.target_y + dy)

    def shoot(self) -> str | None:
        """レーザーを 1 発。間隔が空いていなければ撃てない。"""
        if not self.started or self.over or self.time < self.pause_until or self.time < self.next_shot:
            return None
        self.next_shot = self.time + SHOT_GAP
        self.lasers.append(Laser(self.ship.x, self.ship.y, 2.0, self.next_uid()))
        self.shots += 1
        return "shoot"

    # ── 出す ──
    def spawn_rock(self) -> Rock:
        """奥から小惑星を 1 つ。半分は機体の今いる場所を狙って飛んでくる。"""
        sizes = list(ROCKS)
        size = self.luck.choices(sizes, weights=[ROCKS[s]["weight"] for s in sizes])[0]
        x = self.luck.uniform(-X_MAX - 10, X_MAX + 10)
        y = self.luck.uniform(-Y_MAX - 8, Y_MAX + 8)
        speed = self.rock_speed() * self.luck.uniform(0.85, 1.15)
        seconds = FAR / speed                       # 機体の奥行きに着くまでの秒数
        if self.luck.random() < AIMED:
            vx, vy = (self.ship.x - x) / seconds, (self.ship.y - y) / seconds
        else:
            vx, vy = self.luck.uniform(-4, 4), self.luck.uniform(-3, 3)
        rock = Rock(x, y, FAR, vx, vy, -speed, size, self.next_uid(), self.luck.uniform(-1.5, 1.5), self.luck.randrange(1000))
        self.rocks.append(rock)
        return rock

    def split(self, rock: Rock) -> None:
        """割れる：1 つ下の大きさ 2 つに。小は消えるだけ。"""
        if rock.size == 0:
            return
        for side in (-1, 1):
            child = Rock(rock.x, rock.y, rock.z, rock.vx + side * 9.0, rock.vy + self.luck.uniform(-4, 4), rock.vz,
                         rock.size - 1, self.next_uid(), self.luck.uniform(-3, 3), self.luck.randrange(1000))
            self.rocks.append(child)

    def burst(self, x: float, y: float, z: float, count: int, color: tuple[int, int, int] = SPARK, speed: float = 25.0) -> None:
        for _ in range(count):
            a = self.luck.uniform(0, math.tau)
            b = self.luck.uniform(-1, 1)
            s = self.luck.uniform(0.3, 1.0) * speed
            self.sparks.append(Spark(x, y, z, math.cos(a) * s, b * s, math.sin(a) * s * 0.5 - 10, self.luck.uniform(0.3, 0.7), color))

    # ── 進める ──
    def update(self, dt: float) -> str | None:
        if not self.started or self.over:
            return None
        self.time += dt
        happened = set()
        ship = self.ship
        step = SHIP_SPEED * dt                     # 機体は目標へ一定の速さで
        dx, dy = self.target_x - ship.x, self.target_y - ship.y
        dist = math.hypot(dx, dy)
        if dist > step:
            dx, dy = dx / dist * step, dy / dist * step
        ship.vx, ship.vy = dx / dt, dy / dt
        ship.x, ship.y = ship.x + dx, ship.y + dy
        for s in self.sparks:
            s.x += s.vx * dt
            s.y += s.vy * dt
            s.z += s.vz * dt
            s.life -= dt
        self.sparks = [s for s in self.sparks if s.life > 0]
        if self.time < self.pause_until:
            return None
        if self.stage_left() <= 0:
            happened.add(self.next_stage())
        if self.firing:
            got = self.shoot()
            if got:
                happened.add(got)
        if self.time >= self.next_rock:
            self.spawn_rock()
            self.next_rock = self.time + self.interval() * self.luck.uniform(0.7, 1.3)
        for laser in self.lasers:
            laser.z += LASER_SPEED * dt
        self.lasers = [l for l in self.lasers if l.z < FAR + 20]
        for rock in self.rocks:
            rock.x += rock.vx * dt
            rock.y += rock.vy * dt
            rock.z += rock.vz * dt
        happened |= self.collide()
        stayed = []
        for rock in self.rocks:
            if rock.z < BEHIND:
                self.escaped += 1
            else:
                stayed.append(rock)
        self.rocks = stayed
        for name in EVENTS:
            if name in happened:
                return name
        return None

    def collide(self) -> set[str]:
        """弾と小惑星、機体と小惑星。どちらも「距離 < 半径の和」。"""
        happened = set()
        ship = self.ship
        for laser in list(self.lasers):
            for rock in list(self.rocks):
                if rock not in self.rocks or laser not in self.lasers:
                    continue
                if abs(rock.z - laser.z) > rock.r + LASER_SPEED * STEP:   # 1 コマで進むぶんも見る（すり抜け防止）
                    continue
                if math.hypot(rock.x - laser.x, rock.y - laser.y) < rock.r + LASER_R:
                    self.lasers.remove(laser)
                    self.rocks.remove(rock)
                    self.hits += 1
                    self.streak += 1
                    self.best_streak = max(self.best_streak, self.streak)
                    gained = ROCKS[rock.size]["points"] * self.multiplier
                    self.score += gained
                    self.burst(rock.x, rock.y, rock.z, 6 + rock.size * 4, ROCK_COLOR if rock.size else SPARK)
                    self.split(rock)
                    if self.multiplier > 1:
                        self.tell(f"{self.streak} 連続 ×{self.multiplier}", 1.0)
                    happened.add("boom" if rock.size == 2 else "hit")
                    break
        if self.time >= ship.safe_until:
            for rock in list(self.rocks):
                if abs(rock.z) < rock.r + SHIP_R and math.hypot(rock.x - ship.x, rock.y - ship.y) < rock.r + SHIP_R:
                    self.rocks.remove(rock)
                    self.burst(rock.x, rock.y, rock.z, 12, ROCK_COLOR)
                    happened.add(self.damage())
                    break
        return happened

    def damage(self) -> str:
        """体当たり：体力が減る。0 なら 1 機失う。"""
        ship = self.ship
        ship.hp -= 1
        ship.safe_until = self.time + SAFE_TIME
        self.streak = 0
        self.shake(2.0, 0.3)
        self.burst(ship.x, ship.y, 0.0, 10, (255, 120, 80))
        if ship.hp > 0:
            self.tell(f"体当たり！ 体力 {ship.hp}", 1.2)
            return "ouch"
        self.lives -= 1
        if self.lives <= 0:
            self.over = True
            self.tell("ゲームオーバー", 99)
            return "end"
        ship.hp = HP
        self.tell(f"1 機失った（あと {self.lives} 機）", 1.5)
        return "lose"

    def next_stage(self) -> str:
        if self.stage + 1 >= len(STAGES):
            self.over = True
            self.won = True
            self.tell("全部クリア！", 99)
            return "end"
        self.stage += 1
        self.rocks = []
        self.lasers = []
        self.stage_start = self.time + STAGE_PAUSE
        self.pause_until = self.time + STAGE_PAUSE
        self.next_rock = self.stage_start + 0.8
        self.tell(f"ステージ {self.stage + 1}：{self.stage_name}", STAGE_PAUSE)
        return "clear"


# ── 描く（端末：透視投影の丸と点） ──────────────────────────────────────

def stars_at(t: float, seed: int = 7) -> list[tuple[float, float, float]]:
    """星の位置。種から決まった星が、時間とともに手前へ流れて奥へ戻る（状態を持たない）。"""
    luck = random.Random(seed)
    stars = []
    for _ in range(STAR_COUNT):
        x, y, z0 = luck.uniform(-160, 160), luck.uniform(-90, 90), luck.uniform(0, STAR_DEPTH)
        z = (z0 - t * STAR_SPEED) % STAR_DEPTH - 20
        stars.append((x, y, z))
    return stars


def draw(screen: Screen, world: World) -> None:
    scale = screen.width // WIDTH
    sky = world.spec["sky"]
    for y in range(screen.height):                  # 上は星雲の色を少し混ぜる
        t = y / screen.height
        neb = world.spec["nebula"]
        screen.band(y, y + 1, tuple(int(a + (b - a) * (0.35 * (1 - t))) for a, b in zip(sky, neb)))
    ox = oy = 0.0
    if world.time < world.shake_until:
        k = world.shake_size * (world.shake_until - world.time) / 0.3
        ox, oy = math.sin(world.time * 90) * k, math.cos(world.time * 70) * k * 0.6
    cam = camera_at(world.ship)
    for x, y, z in stars_at(world.time):
        p = project(x, y, z, cam)
        if p:
            k = min(1.0, p[2] * 2.5)
            screen.box(int((p[0] + ox) * scale), int((p[1] + oy) * scale), scale, scale, shade(STAR, 0.3 + 0.7 * k))
    things: list[tuple[float, str, object]] = [(r.z, "rock", r) for r in world.rocks]
    things += [(l.z, "laser", l) for l in world.lasers]
    things += [(s.z, "spark", s) for s in world.sparks]
    things.sort(key=lambda t: -t[0])                # 奥から手前へ
    for z, kind, thing in things:
        p = project(thing.x, thing.y, thing.z, cam)
        if not p:
            continue
        sx, sy, k = (p[0] + ox) * scale, (p[1] + oy) * scale, p[2] * scale
        if kind == "rock":
            r = thing.r * k
            depth = max(0.0, min(1.0, 1 - thing.z / FAR))
            screen.ellipse(sx, sy, r, r, shade(ROCK_DARK, 0.5 + 0.5 * depth))
            screen.ellipse(sx - r * 0.25, sy - r * 0.25, r * 0.65, r * 0.6, shade(ROCK_COLOR, 0.5 + 0.5 * depth))
        elif kind == "laser":
            screen.box(int(sx - max(1, k * 0.4)), int(sy - k * 3), max(1, int(k * 0.8)), max(2, int(k * 6)), LASER)
        else:
            screen.box(int(sx), int(sy), max(1, scale), max(1, scale), thing.color)
    ship = world.ship                                              # 機体（手前に描く）
    p = project(ship.x, ship.y, 0.0, cam)
    if p and not (world.time < ship.safe_until and int(world.time * 10) % 2 == 0):
        sx, sy, k = (p[0] + ox) * scale, (p[1] + oy) * scale, p[2] * scale
        tilt = max(-1.0, min(1.0, ship.vx / SHIP_SPEED))
        w = k * 2.6
        screen.box(int(sx - w * (1 - 0.3 * tilt)), int(sy + k * 0.2), int(w * 2), max(1, int(k * 0.5)), SHIP_DARK)      # 翼
        screen.ellipse(sx, sy - k * 0.2, max(1.0, k * 0.6), max(1.0, k * 1.6), SHIP)                                   # 胴
        screen.box(int(sx - k * 0.35), int(sy + k * 1.2), max(1, int(k * 0.7)), max(1, int(k * 0.6)), ENGINE)         # 噴射
    for i in range(world.lives):                                   # 残機（左上）
        screen.box((2 + i * 4) * scale, 2 * scale, 2 * scale, 2 * scale, SHIP)
    for i in range(HP):                                            # 体力（左下）
        screen.box((2 + i * 5) * scale, (HEIGHT - 4) * scale, 4 * scale, 2 * scale, HP_ON if i < ship.hp else HP_OFF)
    bar = int((WIDTH - 4) * scale * (1 - world.progress())) if world.started else (WIDTH - 4) * scale   # 残り時間（上）
    screen.box(2 * scale, 0, (WIDTH - 4) * scale, scale, GAUGE)
    screen.box(2 * scale, 0, bar, scale, GAUGE_ON)


# ── 端末 ────────────────────────────────────────────────────────────────

def read_keys(fd: int) -> list[str]:
    keys = []
    while select.select([fd], [], [], 0)[0]:
        text = os.read(fd, 64).decode(errors="ignore")
        i = 0
        while i < len(text):
            ch = text[i]
            if ch == "\x1b" and text[i + 1:i + 2] == "[":
                keys.append({"A": "up", "B": "down", "C": "right", "D": "left"}.get(text[i + 2:i + 3], ""))
                i += 3
                continue
            if ch in ("a", "j"):
                keys.append("left")
            elif ch in ("d", "l"):
                keys.append("right")
            elif ch in ("w", "i"):
                keys.append("up")
            elif ch in ("s", "k"):
                keys.append("down")
            elif ch in (" ", "\r", "\n"):
                keys.append("go")
            elif ch in ("q", "\x1b"):
                keys.append("quit")
            i += 1
    return [k for k in keys if k]


KEY_STEP = 6.0                                      # キー 1 回で目標が動く距離


def obey(world: World, key: str) -> str | None:
    """キーを 1 つ受ける。矢印で目標、go で始める・撃つ。出来事を返す。"""
    if key == "go":
        if not world.started:
            world.started = True
            world.stage_start = world.time
            return None
        return world.shoot()
    moves = {"left": (-KEY_STEP, 0), "right": (KEY_STEP, 0), "up": (0, KEY_STEP), "down": (0, -KEY_STEP)}
    if key in moves:
        world.nudge(*moves[key])
    return None


class Speaker:
    def __init__(self):
        import shutil
        import tempfile

        self.player = shutil.which("afplay") or shutil.which("aplay")
        self.folder = tempfile.mkdtemp(prefix="space-")
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
    """画面の下の 1 行。板と同じ 120 桁に収める。"""
    note = world.note if world.time < world.note_until else ""
    if not world.started:
        note, tail = "スペースで始める", "矢印か wasd で機体、スペースで撃つ、q でやめる"
    elif world.over:
        note = ("全部クリア！" if world.won else "ゲームオーバー") + (" ベスト更新！" if improved else "")
        tail = "スペースでもう一度"
    else:
        tail = f"ベスト {best.score} q でやめる"
    head = (f" {world.stage + 1}/{len(STAGES)} {world.stage_name} {world.stage_left():4.1f}秒 点 {world.score:5d} ×{world.multiplier} "
            f"体力 {world.ship.hp} 機 {world.lives} 命中 {world.hits:3d} ")
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

def autopilot(world: World) -> None:
    """自動で遊ぶ。近づいた小惑星はよけ、それ以外は一番手前の小惑星の未来の位置を狙って撃ち続ける。"""
    ship = world.ship
    for rock in world.rocks:
        if -5 < rock.z < 50:
            dx, dy = rock.x - ship.x, rock.y - ship.y
            if math.hypot(dx, dy) < rock.r + SHIP_R + 5:
                world.aim(ship.x - math.copysign(rock.r + 9, dx or 1.0), ship.y - math.copysign(4, dy or 1.0))
                world.firing = True
                return
    ahead = [r for r in world.rocks if r.z > 8]
    if ahead:
        rock = min(ahead, key=lambda r: r.z)
        seconds = rock.z / (LASER_SPEED - rock.vz)
        world.aim(rock.x + rock.vx * seconds, rock.y + rock.vy * seconds)
        world.firing = True
    else:
        world.aim(0.0, 0.0)
        world.firing = False


def play_out(world: World, limit: float = 600.0) -> dict[str, int]:
    counts = {k: 0 for k in EVENTS}
    world.started = True
    world.stage_start = world.time
    while not world.over and world.time < limit:
        autopilot(world)
        got = world.update(STEP)
        if got:
            counts[got] += 1
    return counts


def until(world: World, frames: int = 30) -> str | None:
    for _ in range(frames):
        got = world.update(STEP)
        if got:
            return got
    return None


def check() -> None:
    print("● 透視投影")
    cam = camera_at(Ship())
    assert cam == (0.0, CAM_UP, -CAM_BACK)
    p = project(0.0, CAM_UP, 100.0, cam)
    assert p and abs(p[0] - CX) < 1e-9 and abs(p[1] - CY) < 1e-9, "カメラの正面の点は板の中央"
    near, far = project(10.0, CAM_UP, 20.0, cam), project(10.0, CAM_UP, 200.0, cam)
    assert near[0] - CX > far[0] - CX > 0, "同じ x でも遠いほど中央に寄る"
    assert project(0.0, 0.0, -CAM_BACK - 1, cam) is None, "カメラの後ろは描かない"
    p = project(0.0, 0.0, 0.0, cam)
    assert 0 < p[0] < WIDTH and CY < p[1] < HEIGHT, "機体は板の下寄りに映る"
    cam2 = camera_at(Ship(x=X_MAX, y=-Y_MAX))
    p2 = project(X_MAX, -Y_MAX, 0.0, cam2)
    assert 0 < p2[0] < WIDTH and 0 < p2[1] < HEIGHT, "端にいても機体は板の中"
    print(f"  正面は中央、遠いほど小さく、カメラの後ろは描かない。機体は ({p[0]:.0f}, {p[1]:.0f})、端でも板の中")

    print("● 機体")
    world = World(seed=1)
    world.started = True
    world.aim(100.0, -100.0)
    assert (world.target_x, world.target_y) == (X_MAX, -Y_MAX), "目標は枠の中"
    for _ in range(30):
        world.update(STEP)
    assert abs(world.ship.x - X_MAX) < 1e-6 and abs(world.ship.y + Y_MAX) < 1e-6, "1 秒で端まで"
    world.aim(0.0, 0.0)
    world.update(STEP)
    assert world.ship.x < X_MAX and world.ship.vx < 0, "目標へ向かう。vx は傾きに"
    print(f"  目標へ 1 秒に {SHIP_SPEED:.0f}、枠は ±{X_MAX:.0f} × ±{Y_MAX:.0f}")

    print("● 弾")
    world = World(seed=1)
    world.started = True
    world.next_rock = 999
    assert world.shoot() == "shoot" and world.shoot() is None, "連射は間を置く"
    world.time += SHOT_GAP
    assert world.shoot() == "shoot" and len(world.lasers) == 2
    z0 = world.lasers[0].z
    world.update(STEP)
    assert world.lasers[0].z - z0 > LASER_SPEED * STEP * 0.99
    for _ in range(60):
        world.update(STEP)
    assert not world.lasers, "奥へ抜けた弾は消える"
    world.firing = True
    for _ in range(30):
        world.update(STEP)
    assert world.shots == 2 + round(1.0 / SHOT_GAP) or world.shots == 2 + round(1.0 / SHOT_GAP) + 1, world.shots
    print(f"  間隔 {SHOT_GAP} 秒、速さ {LASER_SPEED:.0f}、押している間は連射")

    print("● 小惑星")
    world = World(seed=2)
    world.started = True
    world.next_rock = 999                           # 勝手に湧かないように
    rock = world.spawn_rock()
    assert rock.z == FAR and rock.vz < 0 and rock.size in ROCKS
    world.rocks = [Rock(0.0, 0.0, 30.0, 0.0, 0.0, -50.0, 2, 1)]
    world.lasers = [Laser(0.0, 0.0, 26.0, 2)]
    got = until(world, 3)
    assert got == "boom" and len(world.rocks) == 2 and all(r.size == 1 for r in world.rocks) and world.score == 10, (got, world.score)
    assert world.rocks[0].vx < 0 < world.rocks[1].vx, "左右に割れる"
    world.lasers = [Laser(world.rocks[0].x, world.rocks[0].y, world.rocks[0].z - 2, 3)]
    assert until(world, 3) == "hit" and len(world.rocks) == 3 and sum(1 for r in world.rocks if r.size == 0) == 2 and world.score == 30
    for r in world.rocks:                           # 重なっている中を横へどけて、小だけを撃つ
        if r.size == 1:
            r.x = 30.0
    small = [r for r in world.rocks if r.size == 0][0]
    world.lasers = [Laser(small.x, small.y, small.z - 2, 4)]
    assert until(world, 3) == "hit" and len(world.rocks) == 2 and world.score == 70, "小は消えて 40 点"
    world.rocks = [Rock(60.0, 0.0, 10.0, 0.0, 0.0, -60.0, 0, 5)]
    world.lasers = []
    for _ in range(30):
        world.update(STEP)
    assert world.escaped == 1 and not world.rocks, "後ろへ流れたら消える"
    world.rocks = [Rock(0.0, 0.0, 30.0, 0.0, 0.0, -50.0, 0, 6)]
    world.lasers = [Laser(0.0, 0.0, 0.0, 7)]
    assert until(world, 3) == "hit", "速い弾も小さい石をすり抜けない"
    a, b = World(seed=3), World(seed=3)
    for w in (a, b):
        w.started = True
    assert [(r.x, r.size) for r in [a.spawn_rock(), a.spawn_rock()]] == [(r.x, r.size) for r in [b.spawn_rock(), b.spawn_rock()]], "同じ種は同じ"
    print("  大 → 中 2 つ（10 点）→ 小 2 つ（20 点）→ 消える（40 点）。後ろへ流れたら消える")

    print("● 体当たり")
    world = World(seed=1)
    world.started = True
    world.next_rock = 999
    world.rocks = [Rock(0.0, 0.0, 3.0, 0.0, 0.0, -50.0, 1, 1)]
    assert until(world, 3) == "ouch" and world.ship.hp == HP - 1 and not world.rocks and world.time < world.ship.safe_until
    world.rocks = [Rock(0.0, 0.0, 2.0, 0.0, 0.0, -50.0, 1, 2)]
    assert until(world, 3) is None and world.ship.hp == HP - 1, "無敵の間は当たらない"
    world.time = world.ship.safe_until + 0.01
    world.rocks = [Rock(0.0, 0.0, 2.0, 0.0, 0.0, -50.0, 1, 3)]
    assert until(world, 3) == "ouch" and world.ship.hp == HP - 2
    world.time = world.ship.safe_until + 0.01
    world.rocks = [Rock(0.0, 0.0, 2.0, 0.0, 0.0, -50.0, 1, 4)]
    assert until(world, 3) == "lose" and world.ship.hp == HP and world.lives == LIVES - 1, "体力 0 で 1 機失い、体力は戻る"
    world.lives = 1
    world.time = world.ship.safe_until + 0.01
    world.ship.hp = 1
    world.rocks = [Rock(0.0, 0.0, 2.0, 0.0, 0.0, -50.0, 1, 5)]
    assert until(world, 3) == "end" and world.over and not world.won
    print(f"  体力 {HP}、当たると {SAFE_TIME} 秒無敵、0 で 1 機失う、{LIVES} 機で終わり")

    print("● 連続と倍率")
    world = World(seed=1)
    world.started = True
    world.next_rock = 999
    for i in range(7):
        world.rocks = [Rock(0.0, 0.0, 30.0, 0.0, 0.0, -50.0, 0, 10 + i)]
        world.lasers = [Laser(0.0, 0.0, 27.0, 20 + i)]
        world.update(STEP)
    assert world.streak == 7 and world.multiplier == 2 and world.score == 40 * (4 + 2 * 3), world.score
    world.rocks = [Rock(0.0, 0.0, 2.0, 0.0, 0.0, -50.0, 1, 30)]
    world.time = world.ship.safe_until + 0.01
    until(world, 3)
    assert world.streak == 0, "当たると 0"
    print("  5 発ごとに倍率 +1（×4 まで。5 発目から ×2）。7 発で 400 点。体当たりで 0")

    print("● ステージ")
    world = World(seed=1)
    world.started = True
    assert abs(world.interval() - STAGES[0]["interval"][0]) < 1e-9 and abs(world.rock_speed() - STAGES[0]["speed"][0]) < 1e-9
    world.time = world.stage_start + STAGES[0]["seconds"] * 0.5
    assert abs(world.interval() - sum(STAGES[0]["interval"]) / 2) < 1e-9, "間隔は面の途中で真ん中"
    world.time = world.stage_start + STAGES[0]["seconds"] + 0.01
    got = world.update(STEP)
    assert got == "end" and world.won, "最後の面が終わると全部クリア"
    for spec in STAGES:
        assert spec["interval"][0] > spec["interval"][1] and spec["speed"][0] < spec["speed"][1]
    print(f"  {len(STAGES)} 面（" + "、".join(f"{s['name']} {s['seconds']:.0f} 秒" for s in STAGES) + "）。出る間隔は縮み、速さは上がる")

    print("● 自動で遊ぶ")
    world = World(seed=4)
    counts = play_out(world)
    assert world.over and world.won, f"{world.time:.0f} 秒で止まった（機 {world.lives}）"
    assert world.hits > 40 and counts["ouch"] + counts["lose"] * HP < 9, (world.hits, counts)
    accuracy = world.hits / max(1, world.shots)
    print(f"  {world.time:.0f} 秒で 1 面クリア。{world.shots} 発撃って命中 {world.hits}（{accuracy:.0%}）、点 {world.score}、"
          f"最長 {world.best_streak} 連続、体当たり {counts['ouch'] + counts['lose']} 回、流した {world.escaped} 個、残り {world.lives} 機")

    print("● 板の大きさ")
    world = World(seed=2)
    play_out(world, limit=20)
    small, big = Screen(), Screen(WIDTH * 4, HEIGHT * 4)
    started = time.perf_counter()
    draw(small, world)
    took_small = time.perf_counter() - started
    started = time.perf_counter()
    draw(big, world)
    took_big = time.perf_counter() - started
    print(f"  {WIDTH}×{HEIGHT} を描くのに {took_small * 1000:.1f} ms、{WIDTH * 4}×{HEIGHT * 4} は {took_big * 1000:.1f} ms（小惑星 {len(world.rocks)}、粒 {len(world.sparks)}）")
    assert took_small < 0.02

    print("● 記録と音と状態行")
    best = Best.parse(Best(120, 1).dump())
    assert (best.score, best.stage) == (120, 1) and Best.parse("xx").score == 0
    assert len({sound_bytes(k) for k in SOUNDS}) == len(SOUNDS)
    world = World(seed=1)
    for started, over in ((False, False), (True, False), (True, True)):
        world.started, world.over = started, over
        world.tell("体当たり！ 体力 2", 9)
        assert columns(status(world, best, True)) == WIDTH, columns(status(world, best, True))
    print(f"  ベストは点で更新。音は {len(SOUNDS)} つ全部別。状態行は {WIDTH} 桁ちょうど")
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
    play_out(world, limit=14.0)
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
