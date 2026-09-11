"""小惑星をよける（3D）

宇宙船の後ろから見た視点で、迫ってくる小惑星をよける。3D は自分で書く。
  3D の点 (x, y, z) → 回転 → 透視投影（遠いものは小さく：x' = x / z）→ ドット画面

3D を感じさせる 4 つの手がかりを全部入れる。
  遠近   近づくと大きくなる（透視投影）
  視差   星は近いほど速く流れる
  隠面   奥の面から描く（画家のアルゴリズム）＋ こちらを向いていない面は描かない
  陰影   面の向きと光の向きの内積で明るさを決める

    python3 main.py            遊ぶ（← → ↑ ↓ で動く。Esc でやめる）
    python3 main.py --check    決まりを確かめる
    python3 main.py --shot     場面を PNG に書き出す（見た目の確認用）
"""

import io
import math
import os
import random
import select
import sys
import time
import wave
from array import array
from dataclasses import dataclass, field
from typing import NamedTuple

WIDTH = 128                                         # 画面の横（ドット）。端末では 1 ドット = 1 桁
HEIGHT = 80                                         # 縦。端末では 2 ドット = 1 行 → 40 行
CX = WIDTH // 2                                     # 画面の真ん中（＝視線の先）
CY = HEIGHT // 2
FOCUS = 62.0                                        # 焦点距離。大きいほど望遠
NEAR = 0.6                                          # これより手前は描かない
FAR = 48.0                                          # 小惑星と星が生まれる奥行き
EYE = 1.5                                           # 視点の高さ。自機を見下ろすので画面の下寄りに映る
SHIP_Z = 4.0                                        # 自機の奥行き
REACH_X = 4.2                                       # 自機が動ける範囲（カメラが追うので画面より広くてよい）
REACH_Y = (-0.4, 2.6)
FOLLOW = 0.55                                       # カメラが自機の横の動きを追う割合（1 なら真後ろに固定）
BANK = 0.32                                         # 曲がるときにカメラが傾く角度（ラジアン）
RING_GAP = 7.0                                      # トンネルの輪の間隔
RING_R = 6.5                                        # 輪の半径
RING_Y = 1.0                                        # 輪の中心の高さ
FOG_FROM = 8.0                                      # ここより奥は背景の色に溶けていく
STEP = 1 / 30                                       # 1 コマの時間（固定）

LIGHT_DIR = (-0.5, 0.8, -0.6)                       # 光の向き（左上・手前から）
SPACE = (6, 8, 14)                                  # 背景
ROCK = (150, 128, 108)                              # 小惑星の色（明るさは陰影で変わる）
SHIP = (120, 200, 235)                              # 自機
FLAME = (255, 160, 60)                              # 自機の噴射
STAR_NEAR = (240, 240, 250)
STAR_FAR = (90, 95, 120)
RING = (70, 120, 160)                               # トンネルの輪
RATE = 22050                                        # 音の標本の数（1 秒あたり）
VOLUME = 0.14


# ── 音（g73 と同じ作り方） ──────────────────────────────────────────────

def tone(hz: float, seconds: float, volume: float = VOLUME) -> array:
    count = int(RATE * seconds)
    edge = RATE / 200
    samples = array("h")
    for i in range(count):
        fade = min(1.0, i / edge, (count - i) / edge)
        samples.append(int(32767 * volume * fade * math.sin(math.tau * hz * i / RATE)))
    return samples


def sound_bytes(kind: str) -> bytes:
    """出来事の音。pass はよけた（小さく高く）、hit はぶつかった（低く長く）、over はおしまい。"""
    if kind == "pass":
        samples = tone(1320, 0.05)
    elif kind == "hit":
        samples = tone(110, 0.28, VOLUME * 1.8)
    else:
        samples = tone(440, 0.15) + tone(330, 0.15) + tone(220, 0.3)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(samples.tobytes())
    return buffer.getvalue()


SOUNDS = ("pass", "hit", "over")


# ── 3D の点 ─────────────────────────────────────────────────────────────

class V(NamedTuple):
    """3D の点（ベクトル）。足す・引く・伸ばす・内積・外積。"""

    x: float
    y: float
    z: float

    def __add__(self, other: "V") -> "V":
        return V(self.x + other.x, self.y + other.y, self.z + other.z)

    def __sub__(self, other: "V") -> "V":
        return V(self.x - other.x, self.y - other.y, self.z - other.z)

    def scale(self, k: float) -> "V":
        return V(self.x * k, self.y * k, self.z * k)

    def dot(self, other: "V") -> float:
        """内積。同じ向きなら正、直角なら 0、逆なら負。陰影と隠面で使う。"""
        return self.x * other.x + self.y * other.y + self.z * other.z

    def cross(self, other: "V") -> "V":
        """外積。2 本の辺に直角な向き＝面の向き（法線）。"""
        return V(self.y * other.z - self.z * other.y,
                 self.z * other.x - self.x * other.z,
                 self.x * other.y - self.y * other.x)

    def unit(self) -> "V":
        length = math.sqrt(self.dot(self)) or 1.0
        return self.scale(1 / length)


def rotate(p: V, ax: float, ay: float, az: float) -> V:
    """x 軸・y 軸・z 軸のまわりに順に回す。回転は 2D の回転を 3 回やるだけ。"""
    cx, sx = math.cos(ax), math.sin(ax)
    cy, sy = math.cos(ay), math.sin(ay)
    cz, sz = math.cos(az), math.sin(az)
    y, z = p.y * cx - p.z * sx, p.y * sx + p.z * cx          # x 軸まわり
    x, z = p.x * cy + z * sy, -p.x * sy + z * cy             # y 軸まわり
    x, y = x * cz - y * sz, x * sz + y * cz                  # z 軸まわり
    return V(x, y, z)


class Camera(NamedTuple):
    """視点。横の位置と、傾き（ロール）。自機を追いかけ、曲がると傾く。"""

    x: float = 0.0
    roll: float = 0.0


def view(p: V, cam: Camera = Camera()) -> V:
    """世界の点を「カメラから見た点」にする。

    カメラの位置を引いてから、カメラの傾きのぶん逆に回す。カメラが右に傾けば
    世界は左に傾いて見える。視点は EYE の高さで、まっすぐ前を見ている。
    """
    q = V(p.x - cam.x, p.y - EYE, p.z)
    return rotate(q, 0, 0, -cam.roll)


def project(p: V, scale: float = 1.0) -> tuple[float, float]:
    """透視投影。遠い（z が大きい）ほど真ん中に寄って小さくなる。ここが 3D の心臓。

    受け取るのは「カメラから見た点」（view を通したもの）。
    scale は板の大きさ（ブラウザは 2 倍の板に描くので 2）。式は変わらず、全部が 2 倍になるだけ。
    """
    return (CX + FOCUS * p.x / p.z) * scale, (CY - FOCUS * p.y / p.z) * scale


# ── 画面 ────────────────────────────────────────────────────────────────

class Screen:
    """WIDTH × HEIGHT のドットの板。1 行を bytearray（RGB × WIDTH）で持つ。

    1 ドットずつ Python で置くと遅い。行ごとに「ここからここまで、この色」を
    **スライス代入でまとめて書く**と、中は C で走るので何倍も速い。
    ドットを 4 倍（256 × 160）にしても速さを保つための作り。
    """

    def __init__(self, width: int = WIDTH, height: int = HEIGHT):
        self.width, self.height = width, height
        self.rows = [bytearray(width * 3) for _ in range(height)]

    def clear(self, color: tuple[int, int, int]) -> None:
        line = bytes(color) * self.width
        for row in self.rows:
            row[:] = line

    def plot(self, x: int, y: int, color: tuple[int, int, int]) -> None:
        if 0 <= x < self.width and 0 <= y < self.height:
            self.rows[y][x * 3:x * 3 + 3] = bytes(color)

    def fill(self, points: list[tuple[float, float]], color: tuple[int, int, int]) -> None:
        """凸多角形を塗る。横 1 行ずつ、辺との交点の間をまとめて埋める（スキャンライン）。"""
        top = max(0, int(min(y for _, y in points)))
        bottom = min(self.height - 1, int(max(y for _, y in points)))
        count = len(points)
        paint = bytes(color)
        for y in range(top, bottom + 1):
            xs = []
            for i in range(count):
                (x1, y1), (x2, y2) = points[i], points[(i + 1) % count]
                if (y1 <= y < y2) or (y2 <= y < y1):          # この行をまたぐ辺だけ
                    xs.append(x1 + (y - y1) * (x2 - x1) / (y2 - y1))
            if len(xs) >= 2:
                left, right = max(0, int(min(xs))), min(self.width - 1, int(max(xs)))
                if left <= right:
                    self.rows[y][left * 3:(right + 1) * 3] = paint * (right - left + 1)

    def line(self, a: tuple[float, float], b: tuple[float, float], color: tuple[int, int, int]) -> None:
        """2 点を結ぶ線。長い方の軸に沿って 1 ドットずつ置く。"""
        (x1, y1), (x2, y2) = a, b
        steps = int(max(abs(x2 - x1), abs(y2 - y1))) + 1
        for i in range(steps + 1):
            t = i / steps
            self.plot(int(x1 + (x2 - x1) * t), int(y1 + (y2 - y1) * t), color)

    def pixel(self, x: int, y: int) -> tuple[int, int, int]:
        return tuple(self.rows[y][x * 3:x * 3 + 3])

    def render(self) -> str:
        """端末用の文字列。1 行に 2 ドット分の行を詰める（上が前景 ▀、下が背景）。"""
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


# ── 形 ──────────────────────────────────────────────────────────────────

def rock_shape(seed: int) -> tuple[list[V], list[tuple[int, ...]]]:
    """小惑星の形。正二十面体の頂点をでこぼこにずらす。面は三角形 20 枚。"""
    luck = random.Random(seed)
    g = (1 + math.sqrt(5)) / 2                        # 黄金比
    base = [V(-1, g, 0), V(1, g, 0), V(-1, -g, 0), V(1, -g, 0),
            V(0, -1, g), V(0, 1, g), V(0, -1, -g), V(0, 1, -g),
            V(g, 0, -1), V(g, 0, 1), V(-g, 0, -1), V(-g, 0, 1)]
    points = [p.unit().scale(luck.uniform(0.75, 1.15)) for p in base]   # でこぼこ
    faces = [(0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11),
             (1, 5, 9), (5, 11, 4), (11, 10, 2), (10, 7, 6), (7, 1, 8),
             (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8), (3, 8, 9),
             (4, 9, 5), (2, 4, 11), (6, 2, 10), (8, 6, 7), (9, 8, 1)]
    return points, outward(points, faces)


def outward(points: list[V], faces: list[tuple[int, ...]]) -> list[tuple[int, ...]]:
    """凸な立体の面を、法線が外を向く並びにそろえる。

    面の頂点を書く順で法線の向きが決まる（右ねじ）。手で書くと裏返しやすいので、
    重心から見て外を向いていなければ、並びを逆にする。
    """
    center = V(sum(p.x for p in points), sum(p.y for p in points), sum(p.z for p in points)).scale(1 / len(points))
    fixed = []
    for face in faces:
        a, b, c = points[face[0]], points[face[1]], points[face[2]]
        normal = (b - a).cross(c - a)
        fixed.append(face if normal.dot(a - center) >= 0 else tuple(reversed(face)))
    return fixed


SHIP_POINTS = [V(0, 0, 1.3), V(-1.0, -0.05, -0.6), V(1.0, -0.05, -0.6), V(0, 0.4, -0.5), V(0, -0.25, -0.6)]
SHIP_FACES = outward(SHIP_POINTS, [(0, 1, 3), (0, 3, 2), (0, 2, 4), (0, 4, 1), (1, 2, 3), (2, 1, 4)])


def fog(color: tuple[int, int, int], z: float) -> tuple[int, int, int]:
    """遠いほど背景の色に溶かす（空気遠近法）。奥に消えていく感じが出る。"""
    amount = max(0.0, min(0.85, (z - FOG_FROM) / (FAR - FOG_FROM)))
    return tuple(int(c + (b - c) * amount) for c, b in zip(color, SPACE))


def shade(base: tuple[int, int, int], normal: V, z: float = 0.0) -> tuple[int, int, int]:
    """面の向きと光の向きの内積で明るさを決める。光に向いた面ほど明るい。遠ければ霧。"""
    light = V(*LIGHT_DIR).unit()
    bright = 0.28 + 0.72 * max(0.0, normal.dot(light))
    return fog(tuple(min(255, int(c * bright)) for c in base), z)


def draw_solid(screen: Screen, points: list[V], faces: list[tuple[int, ...]],
               color: tuple[int, int, int]) -> None:
    """立体をひとつ描く。こちらを向いた面だけを、奥から順に塗る。"""
    if min(p.z for p in points) < NEAR:
        return
    scale = screen.width / WIDTH
    drawn = []
    for face in faces:
        a, b, c = points[face[0]], points[face[1]], points[face[2]]
        normal = (b - a).cross(c - a).unit()
        if normal.dot(a) >= 0:                      # 面の向きが視線と同じ＝裏側。描かない
            continue
        depth = sum(points[i].z for i in face) / len(face)
        drawn.append((depth, [project(points[i], scale) for i in face], shade(color, normal, depth)))
    for _, flat, painted in sorted(drawn, key=lambda item: -item[0]):   # 奥から
        screen.fill(flat, painted)


# ── 世界 ────────────────────────────────────────────────────────────────

@dataclass
class Rock:
    pos: V
    radius: float
    seed: int
    spin: V                                         # 回る速さ（軸ごと）
    angle: V = V(0, 0, 0)
    passed: bool = False


@dataclass
class World:
    seed: int = 0
    luck: random.Random = field(default_factory=random.Random)
    rocks: list[Rock] = field(default_factory=list)
    stars: list[V] = field(default_factory=list)
    ship: V = V(0.0, 0.6, SHIP_Z)                   # 自機は視点の少し先、少し下
    aim: V = V(0.0, 0.0, 0.0)                       # 動く向き（キー）
    cam: Camera = Camera()                          # 視点。自機を追いかけ、曲がると傾く
    rings: list[float] = field(default_factory=list)   # トンネルの輪の奥行き
    speed: float = 10.0                             # 前へ進む速さ
    time: float = 0.0
    spawn_at: float = 0.0
    score: int = 0
    lives: int = 3
    hurt: float = 0.0                               # ぶつかった直後（点滅）
    over: bool = False

    def __post_init__(self):
        self.luck = random.Random(self.seed)
        self.stars = [self.new_star(self.luck.uniform(NEAR + 1, FAR)) for _ in range(90)]
        self.rings = [float(z) for z in range(int(RING_GAP), int(FAR), int(RING_GAP))]

    def new_star(self, z: float) -> V:
        return V(self.luck.uniform(-24, 24), self.luck.uniform(-16, 16), z)

    def new_rock(self) -> Rock:
        return Rock(V(self.luck.uniform(-REACH_X, REACH_X), self.luck.uniform(*REACH_Y), FAR),
                    self.luck.uniform(0.7, 1.6), self.luck.randrange(1 << 30),
                    V(self.luck.uniform(-1.2, 1.2), self.luck.uniform(-1.2, 1.2), self.luck.uniform(-0.6, 0.6)))

    def update(self, dt: float) -> str | None:
        """1 コマ進める。起きたこと（"pass" / "hit"）を返す。"""
        if self.over:
            return None
        self.time += dt
        self.hurt = max(0.0, self.hurt - dt)
        # 自機
        x = max(-REACH_X, min(REACH_X, self.ship.x + self.aim.x * 7 * dt))
        y = max(REACH_Y[0], min(REACH_Y[1], self.ship.y + self.aim.y * 5 * dt))
        self.ship = V(x, y, self.ship.z)
        # カメラ：自機の横の動きを少し遅れて追う。曲がる向きに傾く（ゆっくり戻る）
        ease = min(1.0, 6 * dt)
        self.cam = Camera(self.cam.x + (self.ship.x * FOLLOW - self.cam.x) * ease,
                          self.cam.roll + (-self.aim.x * BANK - self.cam.roll) * ease)
        # トンネルの輪
        self.rings = [z - self.speed * dt for z in self.rings]
        self.rings = [z if z > NEAR else z + RING_GAP * len(self.rings) for z in self.rings]
        # 星（視差：近いほど速く流れて見える。動く速さは同じ）
        self.stars = [V(s.x, s.y, s.z - self.speed * dt) if s.z - self.speed * dt > NEAR
                      else self.new_star(FAR) for s in self.stars]
        # 小惑星
        happened = None
        if self.time >= self.spawn_at:
            self.rocks.append(self.new_rock())
            self.spawn_at = self.time + max(0.35, 1.1 - self.time * 0.01)
        kept = []
        for rock in self.rocks:
            rock.pos = V(rock.pos.x, rock.pos.y, rock.pos.z - self.speed * dt)
            rock.angle = rock.angle + rock.spin.scale(dt)
            if not rock.passed and rock.pos.z <= self.ship.z:
                rock.passed = True
                gap = math.dist((rock.pos.x, rock.pos.y), (self.ship.x, self.ship.y))
                if gap < rock.radius + 0.55 and self.hurt == 0:
                    self.lives -= 1
                    self.hurt = 1.0
                    happened = "hit"
                    if self.lives <= 0:
                        self.over = True
                        happened = "over"
                else:
                    self.score += 1
                    self.speed = min(34.0, self.speed + 0.35)
                    happened = happened or "pass"
            if rock.pos.z > NEAR:
                kept.append(rock)
        self.rocks = kept
        return happened


def draw(screen: Screen, world: World) -> None:
    """場面を描く。星 → 小惑星（奥から）→ 自機。"""
    screen.clear(SPACE)
    cam = world.cam
    scale = screen.width / WIDTH
    for star in world.stars:
        sx, sy = project(view(star, cam), scale)
        near = 1 - star.z / FAR
        color = tuple(int(f + (n - f) * near) for f, n in zip(STAR_FAR, STAR_NEAR))
        screen.plot(int(sx), int(sy), color)
    for z in sorted(world.rings, reverse=True):     # 輪。奥から。16 角形の線
        color = fog(RING, z)
        corners = [project(view(V(RING_R * math.cos(a), RING_Y + RING_R * math.sin(a), z), cam), scale)
                   for a in (i * math.tau / 16 for i in range(16))]
        for i in range(16):
            screen.line(corners[i], corners[(i + 1) % 16], color)
    for rock in sorted(world.rocks, key=lambda r: -r.pos.z):
        points, faces = rock_shape(rock.seed)
        placed = [view(rotate(p, *rock.angle).scale(rock.radius) + rock.pos, cam) for p in points]
        draw_solid(screen, placed, faces, ROCK)
    if world.over or int(world.hurt * 12) % 2 == 0:  # ぶつかった直後は点滅
        tilt = -world.aim.x * 0.5                   # 曲がる向きに機体を傾ける
        placed = [view(rotate(p, 0.1, 0, tilt).scale(0.9) + world.ship, cam) for p in SHIP_POINTS]
        draw_solid(screen, placed, SHIP_FACES, SHIP)
        tail = view(rotate(V(0, 0, -0.8), 0.1, 0, tilt).scale(0.9) + world.ship, cam)
        fx, fy = project(tail, scale)
        screen.plot(int(fx), int(fy), FLAME)
        screen.plot(int(fx), int(fy) + 1, FLAME)


def obey(world: World, key: str, down: bool = True) -> None:
    """キーを 1 つ受ける。押した／離したで向きを変える。端末もブラウザもここを通る。"""
    v = 1.0 if down else 0.0
    if key == "left":
        world.aim = V(-v if down else 0.0, world.aim.y, 0)
    elif key == "right":
        world.aim = V(v, world.aim.y, 0)
    elif key == "up":
        world.aim = V(world.aim.x, v, 0)
    elif key == "down":
        world.aim = V(world.aim.x, -v, 0)
    elif key == "stop":
        world.aim = V(0.0, 0.0, 0)


# ── 端末 ────────────────────────────────────────────────────────────────

def read_keys(fd: int) -> list[str]:
    keys = []
    while select.select([fd], [], [], 0)[0]:
        text = os.read(fd, 64).decode(errors="ignore")
        for token, name in (("\x1b[D", "left"), ("\x1b[C", "right"), ("\x1b[A", "up"), ("\x1b[B", "down"),
                            ("a", "left"), ("d", "right"), ("w", "up"), ("s", "down"),
                            ("q", "quit"), ("\x1b", "quit"), ("r", "reset")):
            keys.extend([name] * text.count(token))
        if "\x1b[" in text:                         # 矢印の並びに含まれる \x1b を quit に数えない
            keys = [k for k in keys if k != "quit"] if text.count("\x1b") == text.count("\x1b[") else keys
    return keys


class Speaker:
    """端末で音を出す係。3 つの wav を先に書いておき、出来事があったら afplay に渡す。"""

    def __init__(self):
        import shutil
        import tempfile

        self.player = shutil.which("afplay") or shutil.which("aplay")
        self.folder = tempfile.mkdtemp(prefix="space-3d-")
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
        subprocess.Popen([self.player, self.paths[kind]],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def close(self) -> None:
        import shutil

        shutil.rmtree(self.folder, ignore_errors=True)


def status(world: World) -> str:
    return (f" よけた {world.score:3d}  残り {'♥' * world.lives}{'♡' * (3 - world.lives)}  "
            f"速さ {world.speed:4.1f}   ← → ↑ ↓ で動く（w a s d でも）  q でやめる"
            + ("   ★ おしまい。r でもう一度" if world.over else ""))


def run() -> None:
    import termios
    import tty

    world = World(seed=int(time.time()))
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
            for key in read_keys(fd):
                if key == "quit":
                    return
                if key == "reset" and world.over:
                    world = World(seed=int(time.time()))
                obey(world, key)
            now = time.perf_counter()
            lag = min(lag + now - last, 0.25)
            last = now
            while lag >= STEP:                      # 固定の刻み幅（g64 で覚えた）
                speaker.say(world.update(STEP))
                lag -= STEP
            world.aim = V(world.aim.x * 0.85, world.aim.y * 0.85, 0)   # 端末はキーの離しが分からないので減らす
            draw(screen, world)
            sys.stdout.write("\x1b[H" + screen.render() + status(world) + "\x1b[K")
            sys.stdout.flush()
            time.sleep(max(0.0, STEP - (time.perf_counter() - now)))
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
        sys.stdout.write("\x1b[?25h\x1b[2J\x1b[H")
        speaker.close()


def check() -> None:
    print("● 透視投影")
    near, far = project(V(2, 1, 4)), project(V(2, 1, 40))
    assert abs(near[0] - CX) > abs(far[0] - CX), "遠い点の方が真ん中に寄るはず"
    assert project(view(V(0, EYE, 10))) == (CX, CY)
    print(f"  同じ (2, 1) でも z=4 なら中心から {near[0] - CX:.0f} ドット、z=40 なら {far[0] - CX:.1f} ドット")
    for x in (-REACH_X, REACH_X):
        for y in REACH_Y:
            cam = Camera(x * FOLLOW, 0.0)           # カメラが追いついた状態で
            sx, sy = project(view(V(x, y, SHIP_Z), cam))
            assert 8 <= sx <= WIDTH - 8 and 4 <= sy <= HEIGHT - 4, (x, y, sx, sy)
    print(f"  自機の動ける範囲（x ±{REACH_X}、y {REACH_Y}）は、カメラが追えば画面に収まる")
    print("● カメラ")
    assert project(view(V(2, EYE, 10), Camera(2.0, 0.0))) == (CX, CY), "カメラが自機の真上に来れば真ん中に映るはず"
    banked = project(view(V(0, EYE + 1, 10), Camera(0, -BANK)))   # 右へ曲がる＝右へ傾く
    assert banked[0] < CX, "右へ傾くと、上の点は左へずれて映るはず（世界が反対に傾く）"
    print("  自機を追うと真ん中に、右へ傾くと世界の上が左へ流れる")
    print("● 霧")
    assert fog(ROCK, 2.0) == ROCK and fog(ROCK, FAR) != ROCK
    assert sum(fog(ROCK, 20)) > sum(fog(ROCK, 40)) > sum(SPACE), "遠いほど背景に近づくはず"
    print(f"  {FOG_FROM} より手前は元の色、奥ほど背景（{SPACE}）へ溶ける")
    print("● 回転")
    p = rotate(V(1, 0, 0), 0, math.pi / 2, 0)
    assert abs(p.z + 1) < 1e-9 and abs(p.x) < 1e-9, p
    r = rotate(V(1, 2, 3), 0.3, 0.7, 1.1)
    assert abs(math.sqrt(r.dot(r)) - math.sqrt(14)) < 1e-9, "回しても長さは変わらないはず"
    print("  x 軸の点を y 軸まわりに 90° 回すと z 軸へ。回しても長さは変わらない")
    print("● 面の向きと陰影")
    n = (V(1, 0, 0) - V(0, 0, 0)).cross(V(0, 1, 0) - V(0, 0, 0)).unit()
    assert n == V(0, 0, 1)
    assert shade(ROCK, V(*LIGHT_DIR).unit()) > shade(ROCK, V(*LIGHT_DIR).unit().scale(-1))
    print("  x 軸と y 軸の面の法線は z 軸。光に向いた面の方が明るい")
    print("● 面の表裏")
    center = V(0, 0, 0)
    for face in SHIP_FACES + rock_shape(5)[1]:
        pts = SHIP_POINTS if face in SHIP_FACES else rock_shape(5)[0]
        a, b, c = pts[face[0]], pts[face[1]], pts[face[2]]
        mid = V(sum(p.x for p in pts), sum(p.y for p in pts), sum(p.z for p in pts)).scale(1 / len(pts))
        assert (b - a).cross(c - a).dot(a - mid) >= 0, face
    print("  自機と小惑星のすべての面が外を向いている（裏返しの面が無い）")
    print("● 小惑星の形")
    points, faces = rock_shape(1)
    assert len(points) == 12 and len(faces) == 20
    assert rock_shape(1) == rock_shape(1) and rock_shape(1) != rock_shape(2)
    print("  頂点 12・面 20。同じ種なら同じ形、違う種なら違う形")
    print("● トンネルの輪")
    world = World(seed=1)
    count = len(world.rings)
    assert count == (int(FAR) - 1) // int(RING_GAP) and all(NEAR < z < FAR for z in world.rings)
    for _ in range(60):
        world.update(STEP)
    assert all(z > NEAR for z in world.rings) and len(world.rings) == count
    print(f"  輪 {count} 本が {RING_GAP} おきに流れ、手前に来たら奥に戻る")
    print("● 世界")
    world = World(seed=1)
    events = []
    for _ in range(30 * 20):
        got = world.update(STEP)
        if got:
            events.append(got)
    assert world.score + (3 - world.lives) == events.count("pass") + events.count("hit") + events.count("over")
    print(f"  20 秒動かして、よけた {world.score}、ぶつかった {3 - world.lives}、速さ {world.speed:.1f}")
    print("● 自動でよけると")
    world = World(seed=1)
    for _ in range(30 * 40):
        near_rock = min((r for r in world.rocks if not r.passed), key=lambda r: r.pos.z, default=None)
        if near_rock is not None and near_rock.pos.z < 25:
            dx = world.ship.x - near_rock.pos.x
            world.aim = V(1.0 if dx >= 0 else -1.0, 0.0, 0)
        else:
            world.aim = V(-world.ship.x * 0.5, -world.ship.y * 0.5, 0)
        world.update(STEP)
    print(f"  40 秒: よけた {world.score}、残り {world.lives}、速さ {world.speed:.1f}")
    print("● 板の大きさ")
    world = World(seed=2)
    for _ in range(90):
        world.update(STEP)
    small, big = Screen(), Screen(WIDTH * 2, HEIGHT * 2)
    started = time.perf_counter()
    draw(small, world)
    took_small = time.perf_counter() - started
    started = time.perf_counter()
    draw(big, world)
    took_big = time.perf_counter() - started
    same = sum(1 for y in range(HEIGHT) for x in range(WIDTH) if small.pixel(x, y) == big.pixel(x * 2, y * 2))
    print(f"  128×80 を描くのに {took_small * 1000:.1f} ms、256×160 は {took_big * 1000:.1f} ms（{took_big / took_small:.1f} 倍）")
    print(f"  2 倍の板の偶数ドットは、小さい板と {same / (WIDTH * HEIGHT):.0%} 一致（線は細くなるので完全には一致しない）")
    assert same / (WIDTH * HEIGHT) > 0.9
    print("● 音")
    for kind in SOUNDS:
        data = sound_bytes(kind)
        assert data[:4] == b"RIFF"
    assert len({sound_bytes(k) for k in SOUNDS}) == 3
    print("  よけた・ぶつかった・おしまい の 3 つ。全部別の音")
    print("\nぜんぶ通った。")


def shot(path: str, seconds: float = 6.0) -> None:
    """場面を PNG に書き出す（見た目の確認用。標準ライブラリだけで PNG を組む）。"""
    import struct
    import zlib

    world = World(seed=3)
    for i in range(int(seconds / STEP)):
        world.aim = V(0.6 if i < 40 else -0.3, -0.2, 0)
        world.update(STEP)
    screen = Screen()
    draw(screen, world)
    scale = 5
    rows = b""
    for row in screen.rows:
        line = b"\x00" + b"".join(bytes(row[x * 3:x * 3 + 3]) * scale for x in range(screen.width))
        rows += line * scale

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", WIDTH * scale, HEIGHT * scale, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))
    with open(path, "wb") as out:
        out.write(png)
    print(f"{path} に書き出した（{len(world.rocks)} 個の小惑星、よけた {world.score}）")


def main() -> None:
    if "--check" in sys.argv:
        check()
    elif "--shot" in sys.argv:
        shot(sys.argv[sys.argv.index("--shot") + 1] if len(sys.argv) > 2 else "shot.png")
    else:
        run()


if __name__ == "__main__":
    main()
