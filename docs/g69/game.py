"""深宇宙シューティング ブラウザ版

CLI 版（g69-deep-space/main.py）と中身はまったく同じ。世界（World）、小惑星の出方と割れ方、当たり判定、
点とコンボ、カメラの位置（camera_at）は 1 文字も変えていない。

違うのは出口だけ。端末は透視投影の丸と点を ▀ で描き、ここでは同じ世界を Three.js の物（Mesh）に写して
GPU に描かせる。星・霧・光・材質はすべて Three.js。入口は指のスライド（画面のどこでも）とタップ、傾き、キー。
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

from pyodide.ffi import create_proxy, to_js
from pyscript import document, when, window


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


ROCKS = {
    2: dict(name="大", r=6.0, points=10, weight=35),
    1: dict(name="中", r=3.5, points=20, weight=40),
    0: dict(name="小", r=2.0, points=40, weight=25),
}


AIMED = 0.55                                        # 機体を狙って飛んでくる小惑星の割合


STAGES = [
    dict(name="星雲の入口", seconds=60.0, interval=(1.1, 0.5), speed=(45.0, 70.0), sky=(7, 7, 20), nebula=(80, 60, 140)),
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


def stars_at(t: float, seed: int = 7) -> list[tuple[float, float, float]]:
    """星の位置。種から決まった星が、時間とともに手前へ流れて奥へ戻る（状態を持たない）。"""
    luck = random.Random(seed)
    stars = []
    for _ in range(STAR_COUNT):
        x, y, z0 = luck.uniform(-160, 160), luck.uniform(-90, 90), luck.uniform(0, STAR_DEPTH)
        z = (z0 - t * STAR_SPEED) % STAR_DEPTH - 20
        stars.append((x, y, z))
    return stars
# --- ここから下はブラウザ版だけ。CLI 版の draw() / run() / Speaker / status() にあたる ---
#   端末の draw() は「透視投影の式で丸を描く」。ここでは同じ世界の物を Three.js の Mesh に写し、
#   カメラは同じ camera_at() の位置に置く。描くのは GPU。

THREE = window.THREE
VIEW_W, VIEW_H = 640, 400


def js(**kw):
    """Python の dict → JS のオブジェクト（Three.js の引数はこれで渡す）。"""
    return to_js(kw, dict_converter=window.Object.fromEntries)


canvas = document.querySelector("#screen")
stage_label = document.querySelector("#stage")
time_label = document.querySelector("#time")
score_label = document.querySelector("#score")
streak_label = document.querySelector("#streak")
hp_label = document.querySelector("#hp")
lives_label = document.querySelector("#lives")
hits_label = document.querySelector("#hits")
best_label = document.querySelector("#best")
fps_label = document.querySelector("#fps")
note_label = document.querySelector("#note")
message = document.querySelector("#message")
again_button = document.querySelector("#again")
go_button = document.querySelector("#go")
SAVED = "g69-best"


# ── Three.js の舞台 ──────────────────────────────────────────────────────

renderer = THREE.WebGLRenderer.new(js(canvas=canvas, antialias=True))
renderer.setPixelRatio(min(2.0, window.devicePixelRatio))
renderer.setSize(VIEW_W, VIEW_H, False)
scene = THREE.Scene.new()
camera = THREE.PerspectiveCamera.new(2 * math.degrees(math.atan(CY / FOCUS)), VIEW_W / VIEW_H, 0.5, 900)   # 端末と同じ画角


def rgb(color: tuple[int, int, int]) -> int:
    r, g, b = color
    return (r << 16) | (g << 8) | b


def set_sky(spec: dict) -> None:
    scene.background = THREE.Color.new(rgb(spec["sky"]))
    scene.fog = THREE.FogExp2.new(rgb(spec["sky"]), 0.0045)


sun = THREE.DirectionalLight.new(0xfff4e0, 2.4)     # 遠くの太陽：右上手前から
sun.position.set(60, 80, -40)
scene.add(sun)
scene.add(THREE.AmbientLight.new(0x3a3f70, 1.2))
back = THREE.DirectionalLight.new(0x6080ff, 0.8)    # 星雲の照り返し：左奥から
back.position.set(-50, -20, 200)
scene.add(back)


def make_stars(count: int, spread: float, size: float, color: int) -> object:
    luck = random.Random(11)
    flat = []
    for _ in range(count):
        flat += [luck.uniform(-spread, spread), luck.uniform(-spread, spread), luck.uniform(-spread, spread)]
    geo = THREE.BufferGeometry.new()
    geo.setAttribute("position", THREE.Float32BufferAttribute.new(to_js(flat), 3))
    mat = THREE.PointsMaterial.new(js(color=color, size=size, sizeAttenuation=True, transparent=True, opacity=0.9, fog=False))
    return THREE.Points.new(geo, mat)


stars = make_stars(2500, 700, 1.6, 0xdde4ff)        # 遠くの星：カメラに付いて回る（動かない）
scene.add(stars)
DUST = 260                                          # 近くの塵：手前へ流れて速さを感じさせる
dust_geo = THREE.BufferGeometry.new()
dust_geo.setAttribute("position", THREE.Float32BufferAttribute.new(to_js([0.0] * (DUST * 3)), 3))
dust = THREE.Points.new(dust_geo, THREE.PointsMaterial.new(js(color=0x9fb0ff, size=0.7, sizeAttenuation=True)))
scene.add(dust)
dust_seed = random.Random(5)
DUST_BASE = [(dust_seed.uniform(-90, 90), dust_seed.uniform(-50, 50), dust_seed.uniform(0, STAR_DEPTH)) for _ in range(DUST)]


def rock_geometry(seed: int) -> object:
    """でこぼこの岩。正二十面体の頂点を、種で決めた量だけ外へ内へずらす（同じ場所の頂点は同じ量）。"""
    geo = THREE.IcosahedronGeometry.new(1.0, 1)
    attr = geo.attributes.position
    arr = attr.array
    flat = []
    for i in range(0, attr.count * 3, 3):
        x, y, z = arr[i], arr[i + 1], arr[i + 2]
        key = (round(x, 3), round(y, 3), round(z, 3))
        k = 0.72 + 0.56 * random.Random(hash(key) ^ seed).random()
        flat += [x * k, y * k, z * k]
    arr.set(to_js(flat))
    attr.needsUpdate = True
    geo.computeVertexNormals()
    return geo


ROCK_GEOS = [rock_geometry(n) for n in range(6)]
ROCK_MAT = THREE.MeshStandardMaterial.new(js(color=rgb(ROCK_COLOR), roughness=0.95, metalness=0.05, flatShading=True))
LASER_GEO = THREE.CylinderGeometry.new(0.28, 0.28, 7.0, 6)
LASER_MAT = THREE.MeshBasicMaterial.new(js(color=rgb(LASER)))


def make_ship() -> object:
    """機体：円錐の胴＋箱の翼＋尾翼＋噴射の玉。先が +z（奥）を向く。"""
    group = THREE.Group.new()
    body_mat = THREE.MeshStandardMaterial.new(js(color=rgb(SHIP), roughness=0.35, metalness=0.7))
    wing_mat = THREE.MeshStandardMaterial.new(js(color=rgb(SHIP_DARK), roughness=0.5, metalness=0.6))
    body = THREE.Mesh.new(THREE.ConeGeometry.new(1.1, 6.0, 10), body_mat)
    body.rotation.x = math.pi / 2
    group.add(body)
    wing = THREE.Mesh.new(THREE.BoxGeometry.new(7.0, 0.22, 2.4), wing_mat)
    wing.position.set(0, -0.2, -1.2)
    group.add(wing)
    fin = THREE.Mesh.new(THREE.BoxGeometry.new(0.2, 1.6, 1.6), wing_mat)
    fin.position.set(0, 0.9, -2.0)
    group.add(fin)
    flame = THREE.Mesh.new(THREE.SphereGeometry.new(0.55, 8, 8), THREE.MeshBasicMaterial.new(js(color=rgb(ENGINE))))
    flame.position.set(0, 0, -3.2)
    group.add(flame)
    return group


ship_mesh = make_ship()
scene.add(ship_mesh)
SPARKS = 400
spark_geo = THREE.BufferGeometry.new()
spark_geo.setAttribute("position", THREE.Float32BufferAttribute.new(to_js([0.0, -9999.0, 0.0] * SPARKS), 3))
sparks_points = THREE.Points.new(spark_geo, THREE.PointsMaterial.new(js(color=rgb(SPARK), size=1.1, sizeAttenuation=True)))
scene.add(sparks_points)
meshes: dict[int, object] = {}                      # uid → Mesh（小惑星と弾）


def sync(world: World) -> None:
    """世界の物を Three.js の物に写す。無い物は作り、消えた物は舞台から下ろす。"""
    alive = set()
    for rock in world.rocks:
        alive.add(rock.uid)
        mesh = meshes.get(rock.uid)
        if mesh is None:
            mesh = THREE.Mesh.new(ROCK_GEOS[rock.seed % len(ROCK_GEOS)], ROCK_MAT)
            mesh.scale.set(rock.r, rock.r, rock.r)
            mesh.rotation.set(rock.seed * 0.1, rock.seed * 0.07, 0)
            scene.add(mesh)
            meshes[rock.uid] = mesh
        mesh.position.set(rock.x, rock.y, rock.z)
        mesh.rotation.x += rock.spin * STEP
        mesh.rotation.y += rock.spin * 0.6 * STEP
    for laser in world.lasers:
        alive.add(laser.uid)
        mesh = meshes.get(laser.uid)
        if mesh is None:
            mesh = THREE.Mesh.new(LASER_GEO, LASER_MAT)
            mesh.rotation.x = math.pi / 2
            scene.add(mesh)
            meshes[laser.uid] = mesh
        mesh.position.set(laser.x, laser.y, laser.z)
    for uid in list(meshes):
        if uid not in alive:
            scene.remove(meshes.pop(uid))
    ship = world.ship
    ship_mesh.position.set(ship.x, ship.y, 0.0)
    ship_mesh.rotation.z = -max(-1.0, min(1.0, ship.vx / SHIP_SPEED)) * 0.6   # 横へ動くと翼を傾ける
    ship_mesh.rotation.x = max(-1.0, min(1.0, ship.vy / SHIP_SPEED)) * 0.25
    ship_mesh.visible = not (world.time < ship.safe_until and int(world.time * 10) % 2 == 0)
    flat = []
    for s in world.sparks[:SPARKS]:
        flat += [s.x, s.y, s.z]
    flat += [0.0, -9999.0, 0.0] * (SPARKS - len(world.sparks[:SPARKS]))
    spark_geo.attributes.position.array.set(to_js(flat))
    spark_geo.attributes.position.needsUpdate = True
    flat = []
    for x, y, z0 in DUST_BASE:
        flat += [x, y, (z0 - world.time * STAR_SPEED * 1.5) % STAR_DEPTH - 20]
    dust_geo.attributes.position.array.set(to_js(flat))
    dust_geo.attributes.position.needsUpdate = True
    cx, cy, cz = camera_at(ship)
    ox = oy = 0.0
    if world.time < world.shake_until:
        k = world.shake_size * (world.shake_until - world.time) / 0.3 * 0.3
        ox, oy = math.sin(world.time * 90) * k, math.cos(world.time * 70) * k
    camera.position.set(cx + ox, cy + oy, cz)
    camera.lookAt(cx + ox, cy + oy, cz + 100.0)
    stars.position.set(cx, cy, cz)
    stars.rotation.z = world.time * 0.004


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
held = {"left": False, "right": False, "up": False, "down": False}
set_sky(world.spec)


def refresh() -> None:
    sync(world)
    renderer.render(scene, camera)
    stage_label.textContent = f"{world.stage + 1}/{len(STAGES)} {world.stage_name}"
    time_label.textContent = f"{world.stage_left() if world.started else world.spec['seconds']:.1f}"
    score_label.textContent = str(world.score)
    streak_label.textContent = f"{world.streak}（×{world.multiplier}）"
    hp_label.textContent = "■" * world.ship.hp + "□" * (HP - world.ship.hp)
    lives_label.textContent = str(world.lives)
    hits_label.textContent = f"{world.hits}/{world.shots}"
    best_label.textContent = str(best.score)
    note_label.textContent = (world.note if world.time < world.note_until else "") or " "
    if world.over:
        message.textContent = (("全部クリア！ " if world.won else "ゲームオーバー。") +
                               f"点 {world.score}、命中 {world.hits}/{world.shots}、最長 {world.best_streak} 連続"
                               + ("  ベスト更新！" if improved else ""))
    elif not world.started:
        message.textContent = "「スタート」で始める。画面のどこでも指を動かすと機体が追いかける。押している間レーザー（パソコンは矢印とスペース）"
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
            if any(held.values()):
                world.nudge((held["right"] - held["left"]) * SHIP_SPEED * STEP, (held["up"] - held["down"]) * SHIP_SPEED * STEP)
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


KEYS = {"ArrowLeft": "left", "a": "left", "ArrowRight": "right", "d": "right", "ArrowUp": "up", "w": "up", "ArrowDown": "down", "s": "down"}


def wake_sound() -> None:
    if not wake_sound.done:
        wake_sound.done = True
        speaker.say("shoot")


wake_sound.done = False


def begin() -> None:
    if not world.started:
        world.started = True
        world.stage_start = world.time
        world.next_rock = world.time + 0.8


@when("keydown", "body")
def on_down(event):
    if event.key in KEYS:
        event.preventDefault()
        held[KEYS[event.key]] = True
        world.aim(world.ship.x, world.ship.y)
    elif event.key in (" ", "Enter"):
        event.preventDefault()
        if not event.repeat:
            wake_sound()
            begin()
            world.firing = True
            refresh()


@when("keyup", "body")
def on_up(event):
    if event.key in KEYS:
        held[KEYS[event.key]] = False
    elif event.key in (" ", "Enter"):
        world.firing = False


def finger(event) -> tuple[float, float]:
    """canvas の位置 → 世界の目標。左右 ±X_MAX、上下 ±Y_MAX（上が正）。"""
    rect = canvas.getBoundingClientRect()
    fx = (event.clientX - rect.left) / rect.width * 2 - 1
    fy = (event.clientY - rect.top) / rect.height * 2 - 1
    return fx * X_MAX, -fy * Y_MAX


@when("pointerdown", "#screen")
def press(event):
    event.preventDefault()
    wake_sound()
    begin()
    world.firing = True
    world.aim(*finger(event))
    refresh()


@when("pointermove", "#screen")
def slide(event):
    if tilt["on"]:
        return
    if event.pointerType == "mouse" and event.buttons == 0 and not world.started:
        return
    event.preventDefault()
    world.aim(*finger(event))


@when("pointerup", "#screen")
def release(event):
    world.firing = False


@when("pointercancel", "#screen")
def cancel(event):
    world.firing = False


@when("click", "#go")
def go(event):
    wake_sound()
    begin()
    go_button.blur()
    refresh()


@when("click", "#again")
def again(event):
    global world, improved
    world = World(seed=int(window.performance.now()))
    for uid in list(meshes):
        scene.remove(meshes.pop(uid))
    world.started = True
    set_sky(world.spec)
    improved = False
    refresh()


# --- スマホの傾き（g81・g68 と同じ）。gamma → 左右、beta → 上下
tilt = {"on": False, "beta0": 40.0}
tilt_button = document.querySelector("#tilt")
tilt_stop = document.querySelector("#tilt-stop")
tilt_note = document.querySelector("#tilt-note")


def on_orientation(event):
    if not tilt["on"]:
        return
    try:
        gamma, beta = float(event.gamma), float(event.beta)
    except (TypeError, ValueError):
        return
    world.aim(max(-1.0, min(1.0, gamma / 15.0)) * X_MAX, max(-1.0, min(1.0, (tilt["beta0"] - beta) / 15.0)) * Y_MAX)


def enable_tilt(granted: bool) -> None:
    if not granted:
        tilt_note.textContent = "傾きの利用が許可されませんでした。指で操作してください"
        return
    tilt["on"] = True
    window.addEventListener("deviceorientation", create_proxy(on_orientation))
    tilt_button.hidden = True
    tilt_stop.hidden = False
    tilt_note.textContent = "傾きで操作しています：左右に傾けて移動、手前に起こすと上、奥へ倒すと下。タップで撃つ"


@when("click", "#tilt")
def ask_tilt(event):
    tilt["beta0"] = 40.0
    request = getattr(window.DeviceOrientationEvent, "requestPermission", None)
    if request is None:
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
