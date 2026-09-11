"""3D レース

曲がって上下する周回コースを、CPU カー 3 台と 3 周で競う。3D は g78 と同じく自分で書く。
今回新しく覚えるところ：
  カメラを回す     車の向き（yaw）で世界を回してから投影する
  ニアクリッピング 道は視点の足元を通る。視点をまたぐ多角形は NEAR の面で切ってから投影する
  曲線からメッシュ 制御点を Catmull-Rom でつなぎ、断面（左端・右端）を並べて道の帯にする
  坂               道の高さを補間して車の y にする

    python3 main.py            遊ぶ（スペースで始める。← → で曲がる、↑ アクセル、↓ ブレーキ。q でやめる）
    python3 main.py --check    決まりを確かめる
    python3 main.py --shot     場面を PNG に書き出す（見た目の確認用）
    python3 main.py --map      コースを真上から PNG に書き出す
"""

import io
import json
import math
import os
import random
import select
import sys
import time
import wave
from array import array
from bisect import bisect_right
from dataclasses import dataclass, field
from typing import NamedTuple

WIDTH = 128                                         # 画面の横（ドット）。端末では 1 ドット = 1 桁
HEIGHT = 80                                         # 縦。端末では 2 ドット = 1 行 → 40 行
CX = WIDTH // 2
CY = HEIGHT // 2
FOCUS = 62.0                                        # 焦点距離
NEAR = 0.5                                          # これより手前は切る（ニアクリッピング）
FAR = 95.0                                          # 道を描く奥行き
FOG_FROM = 30.0                                     # ここより奥は空の色に溶ける
CAM_BACK = 6.5                                      # カメラは車の後ろ何 m か
CAM_UP = 2.4                                        # カメラの高さ（車の位置から）
TILT = 0.14                                         # カメラの見下ろし（ラジアン）。地平線が真ん中より上に来る
STEP = 1 / 30

ROAD_HALF = 4.5                                     # 道の半分の幅
SHOULDER = 0.9                                      # 路肩（赤白の縞）の幅
GRASS_W = 60.0                                      # 道の外の草を描く幅
SAMPLES = 20                                        # 制御点と制御点の間を何分割するか
DRAW_SEGS = 56                                      # 前方に描く断面の数
GRASS_SEGS = 30                                     # 草の縞を描く断面の数（遠くは平らな色）
TREE_EVERY = 7                                      # 何断面ごとに木を立てるか

ACCEL = 16.0                                        # アクセル（m/s²）
BRAKE = 26.0
DRAG = 0.36                                         # 空気抵抗。最高速は ACCEL / DRAG ≈ 44
OFF_DRAG = 1.4                                      # 草の上の抵抗（大きく減速）
TURN = 1.7                                          # 曲がる速さ（ラジアン/秒）の元
GRIP = 8.0                                          # 曲がりが効き始める速さ。速いほど曲がりにくい
LAPS = 3
COUNTDOWN = 3.0                                     # 3・2・1 の秒数
HIT_DIST = 2.6                                      # 車どうしがぶつかる距離
RIVAL_PACE = (33.0, 36.5, 39.5)                     # CPU カーの直線での速さ
RIVAL_LANES = (-2.2, 0.6, 2.4)                      # CPU カーの走る位置（中心からの横ずれ）

# 制御点 (x, z, y)。z が前、y が高さ。閉じたコースなので最後は最初につながる
COURSE = [(0, 0, 0), (0, 70, 0), (-12, 130, 4), (30, 170, 9), (85, 160, 7), (105, 110, 2),
          (80, 70, 0), (95, 20, -2), (70, -30, -4), (30, -55, -2), (0, -40, 0)]

SKY_TOP = (86, 140, 210)
SKY = (150, 190, 235)                               # 地平線の近く。霧もこの色へ溶ける
GRASS_A = (78, 150, 66)
GRASS_B = (68, 134, 58)
ROAD_A = (96, 96, 102)
ROAD_B = (90, 90, 96)
STRIPE_A = (215, 60, 50)
STRIPE_B = (235, 235, 230)
TRUNK = (96, 68, 40)
CROWN = (40, 110, 48)
CAR = (230, 70, 60)                                 # 自分の車
CAR_GLASS = (150, 200, 235)
RIVAL_COLORS = ((60, 110, 220), (240, 200, 60), (180, 90, 200))
RATE = 22050
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
    """出来事の音。count は 3・2・1、go はスタート、lap は周回、hit はぶつかった、
    finish はゴール、best はベスト更新。"""
    if kind == "count":
        samples = tone(880, 0.12)
    elif kind == "go":
        samples = tone(1320, 0.35)
    elif kind == "lap":
        samples = tone(1047, 0.08) + tone(1319, 0.14)
    elif kind == "hit":
        samples = tone(120, 0.2, VOLUME * 1.6)
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


EVENTS = ("count", "go", "lap", "hit", "finish")    # update() が返す出来事
SOUNDS = EVENTS + ("best",)


# ── 3D の点 ─────────────────────────────────────────────────────────────

class V(NamedTuple):
    """3D の点（ベクトル）。足す・引く・伸ばす・内積・外積。x 右、y 上、z 前。"""

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
        return self.x * other.x + self.y * other.y + self.z * other.z

    def cross(self, other: "V") -> "V":
        return V(self.y * other.z - self.z * other.y,
                 self.z * other.x - self.x * other.z,
                 self.x * other.y - self.y * other.x)

    def unit(self) -> "V":
        length = math.sqrt(self.dot(self)) or 1.0
        return self.scale(1 / length)

    def flat(self) -> "V":
        """高さを捨てて地面に寝かせる。向きの計算に使う。"""
        return V(self.x, 0.0, self.z)


def rotate(p: V, ax: float, ay: float, az: float) -> V:
    """x 軸・y 軸・z 軸のまわりに順に回す（g78 と同じ）。"""
    cx, sx = math.cos(ax), math.sin(ax)
    cy, sy = math.cos(ay), math.sin(ay)
    cz, sz = math.cos(az), math.sin(az)
    y, z = p.y * cx - p.z * sx, p.y * sx + p.z * cx
    x, z = p.x * cy + z * sy, -p.x * sy + z * cy
    x, y = x * cz - y * sz, x * sz + y * cz
    return V(x, y, z)


def heading(yaw: float) -> V:
    """向き yaw（ラジアン。0 なら +z）の単位ベクトル。"""
    return V(math.sin(yaw), 0.0, math.cos(yaw))


class Camera(NamedTuple):
    """視点。位置と向き（yaw）。車の後ろ・少し上から、車の向きで世界を見る。"""

    pos: V = V(0.0, CAM_UP, -CAM_BACK)
    yaw: float = 0.0


def view(p: V, cam: Camera) -> V:
    """世界の点を「カメラから見た点」にする。位置を引き、向きのぶん逆に回し、少し見下ろす。

    g78 との違いは真ん中の 1 行：yaw で世界を回す。車が右を向けば世界は左へ回る。
    """
    q = p - cam.pos
    q = rotate(q, 0.0, -cam.yaw, 0.0)
    return rotate(q, -TILT, 0.0, 0.0)


def project(p: V, scale: float = 1.0) -> tuple[float, float]:
    """透視投影（g78 と同じ）。受け取るのは view() を通した点。z は NEAR 以上であること。"""
    return (CX + FOCUS * p.x / p.z) * scale, (CY - FOCUS * p.y / p.z) * scale


def clip_near(points: list[V]) -> list[V]:
    """多角形を z = NEAR の面で切る（Sutherland–Hodgman の 1 面ぶん）。

    道は視点の足元を通るので、断面の 1 つが視点の後ろ（z < NEAR）に来る。
    そのまま投影すると z で割った値が飛んで絵が破綻する。面をまたぐ辺は、
    面との交点で切って、手前側だけを残す。凸多角形は切っても凸のまま。
    """
    kept: list[V] = []
    count = len(points)
    for i in range(count):
        a, b = points[i], points[(i + 1) % count]
        a_in, b_in = a.z >= NEAR, b.z >= NEAR
        if a_in:
            kept.append(a)
        if a_in != b_in:                                # またぐ辺 → 交点を足す
            t = (NEAR - a.z) / (b.z - a.z)
            kept.append(a + (b - a).scale(t))
    return kept


HORIZON = CY - FOCUS * math.tan(TILT)               # 地平線の行（見下ろすぶん上がる）


# ── 板（g78 と同じ） ────────────────────────────────────────────────────

class Screen:
    """WIDTH × HEIGHT のドットの板。1 行を bytearray（RGB × WIDTH）で持ち、スライス代入で塗る。"""

    def __init__(self, width: int = WIDTH, height: int = HEIGHT):
        self.width, self.height = width, height
        self.rows = [bytearray(width * 3) for _ in range(height)]

    def band(self, top: int, bottom: int, color: tuple[int, int, int]) -> None:
        """top 行から bottom 行の手前までを 1 色で。"""
        line = bytes(color) * self.width
        for y in range(max(0, top), min(self.height, bottom)):
            self.rows[y][:] = line

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
                if (y1 <= y < y2) or (y2 <= y < y1):
                    xs.append(x1 + (y - y1) * (x2 - x1) / (y2 - y1))
            if len(xs) >= 2:
                left, right = max(0, int(min(xs))), min(self.width - 1, int(max(xs)))
                if left <= right:
                    self.rows[y][left * 3:(right + 1) * 3] = paint * (right - left + 1)

    def line(self, a: tuple[float, float], b: tuple[float, float], color: tuple[int, int, int]) -> None:
        (x1, y1), (x2, y2) = a, b
        steps = int(max(abs(x2 - x1), abs(y2 - y1))) + 1
        for i in range(steps + 1):
            t = i / steps
            self.plot(int(x1 + (x2 - x1) * t), int(y1 + (y2 - y1) * t), color)

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


# ── コース ──────────────────────────────────────────────────────────────

def catmull(p0: V, p1: V, p2: V, p3: V, t: float) -> V:
    """Catmull-Rom 曲線。p1 から p2 へ、p0 と p3 で向きを決める。t=0 で p1、t=1 で p2。"""
    a = p1.scale(2)
    b = (p2 - p0).scale(t)
    c = (p0.scale(2) - p1.scale(5) + p2.scale(4) - p3).scale(t * t)
    d = (p0.scale(-1) + p1.scale(3) - p2.scale(3) + p3).scale(t * t * t)
    return (a + b + c + d).scale(0.5)


class Track:
    """制御点を曲線でつなぎ、等間隔に近い断面を並べたコース。"""

    def __init__(self, course: list[tuple[float, float, float]] = COURSE, samples: int = SAMPLES):
        knots = [V(x, y, z) for x, z, y in course]
        n = len(knots)
        self.centers: list[V] = []
        for i in range(n):
            p0, p1, p2, p3 = knots[i - 1], knots[i], knots[(i + 1) % n], knots[(i + 2) % n]
            for k in range(samples):
                self.centers.append(catmull(p0, p1, p2, p3, k / samples))
        m = len(self.centers)
        self.dirs = [(self.centers[(i + 1) % m] - self.centers[i]).flat().unit() for i in range(m)]
        self.rights = [V(d.z, 0.0, -d.x) for d in self.dirs]          # 進む向きの右手
        self.dist = [0.0]                                              # 断面 i までの道のり
        for i in range(1, m):
            self.dist.append(self.dist[-1] + math.dist(self.centers[i - 1], self.centers[i]))
        self.length = self.dist[-1] + math.dist(self.centers[-1], self.centers[0])
        # 曲がりのきつさ：少し前と少し後ろの向きの差（CPU カーが減速する目安）
        self.bend = [abs(math.atan2(self.dirs[(i + 3) % m].cross(self.dirs[i - 3]).y,
                                    self.dirs[(i + 3) % m].dot(self.dirs[i - 3]))) for i in range(m)]

    def __len__(self) -> int:
        return len(self.centers)

    def edge(self, i: int, offset: float) -> V:
        """断面 i の、中心から右へ offset の点。左端は -ROAD_HALF、右端は +ROAD_HALF。"""
        i %= len(self.centers)
        return self.centers[i] + self.rights[i].scale(offset)

    def at(self, s: float, offset: float = 0.0) -> V:
        """道のり s（周回して戻る）の位置。断面の間は直線で補う。"""
        s %= self.length
        i = bisect_right(self.dist, s) - 1
        j = (i + 1) % len(self.centers)
        span = (self.dist[j] if j else self.length) - self.dist[i]
        t = (s - self.dist[i]) / span if span else 0.0
        c = self.centers[i] + (self.centers[j] - self.centers[i]).scale(t)
        return c + self.rights[i].scale(offset)

    def yaw_at(self, s: float) -> float:
        i = bisect_right(self.dist, s % self.length) - 1
        d = self.dirs[i]
        return math.atan2(d.x, d.z)

    def locate(self, pos: V, hint: int) -> tuple[int, float, float, float]:
        """pos に一番近い断面を hint の近くから探す。(断面, 道のり, 横ずれ, 道の高さ) を返す。"""
        m = len(self.centers)
        best = min(range(hint - 6, hint + 14), key=lambda k: math.dist(pos.flat(), self.centers[k % m].flat()))
        i = best % m
        j = (i + 1) % m
        rel = (pos - self.centers[i]).flat()
        along = rel.dot(self.dirs[i])
        span = math.dist(self.centers[i].flat(), self.centers[j].flat())
        t = max(0.0, min(1.0, along / span if span else 0.0))
        height = self.centers[i].y + (self.centers[j].y - self.centers[i].y) * t
        s = (self.dist[i] + along) % self.length
        return i, s, rel.dot(self.rights[i]), height


# ── 車 ──────────────────────────────────────────────────────────────────

def box(w: float, h: float, length: float, dy: float = 0.0, dz: float = 0.0) -> tuple[list[V], list[tuple[int, ...]]]:
    """直方体。幅 w・高さ h・長さ length を、y に dy・z に dz ずらして置く。面は外向きにそろえる。"""
    points = [V(x * w / 2, y * h / 2 + dy, z * length / 2 + dz)
              for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]
    faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    return points, outward(points, faces)


def outward(points: list[V], faces: list[tuple[int, ...]]) -> list[tuple[int, ...]]:
    """凸な立体の面を、法線が外を向く並びにそろえる（g78 と同じ）。"""
    center = V(sum(p.x for p in points), sum(p.y for p in points), sum(p.z for p in points)).scale(1 / len(points))
    fixed = []
    for face in faces:
        a, b, c = points[face[0]], points[face[1]], points[face[2]]
        normal = (b - a).cross(c - a)
        fixed.append(face if normal.dot(a - center) >= 0 else tuple(reversed(face)))
    return fixed


BODY = box(1.9, 0.7, 3.8, 0.35)
CABIN = box(1.4, 0.55, 1.7, 0.95, -0.3)
LIGHT_DIR = (-0.4, 0.9, -0.5)


@dataclass
class Car:
    """走る車。位置・向き・速さ。プレイヤーも CPU も同じ入れ物。"""

    pos: V
    yaw: float
    color: tuple[int, int, int]
    speed: float = 0.0
    lap: int = 0
    along: float = 0.0                              # コース上の道のり（0〜length）
    hint: int = 0                                   # 一番近い断面（探す起点）
    lateral: float = 0.0                            # 中心からの横ずれ
    on_road: bool = True
    lap_times: list[float] = field(default_factory=list)
    lap_start: float = 0.0
    finished_at: float | None = None
    stun: float = 0.0                               # ぶつかった直後

    @property
    def progress(self) -> float:
        return self.lap * 1e6 + self.along           # 周回が先、道のりが後（順位はこれで決まる）

    def finished(self) -> bool:
        return self.finished_at is not None


@dataclass
class Rival:
    """CPU カー。コースの曲線に沿って走る。速さは直線での pace、カーブで落とす。"""

    car: Car
    pace: float
    lane: float
    phase: float
    s: float = 0.0


# ── 記録 ────────────────────────────────────────────────────────────────

@dataclass
class Best:
    """ベスト（総合タイムとベストラップ）。端末は records.json、ブラウザは localStorage。形は同じ。"""

    total: float = 0.0                              # 0 は未記録
    lap: float = 0.0

    def dump(self) -> str:
        return json.dumps({"total": self.total, "lap": self.lap})

    @classmethod
    def parse(cls, text: str) -> "Best":
        try:
            data = json.loads(text)
            return cls(float(data["total"]), float(data["lap"]))
        except (ValueError, KeyError, TypeError):
            return cls()

    def take(self, total: float, laps: list[float]) -> tuple[bool, bool]:
        """走り終えた結果を取り込む。(総合を更新したか, ラップを更新したか)。"""
        better_total = self.total == 0.0 or total < self.total
        fastest = min(laps) if laps else 0.0
        better_lap = fastest > 0 and (self.lap == 0.0 or fastest < self.lap)
        if better_total:
            self.total = round(total, 2)
        if better_lap:
            self.lap = round(fastest, 2)
        return better_total, better_lap


# ── 世界 ────────────────────────────────────────────────────────────────

@dataclass
class World:
    seed: int = 0
    luck: random.Random = field(default_factory=random.Random)
    track: Track = field(default_factory=Track)
    player: Car = field(default=None)               # __post_init__ で作る
    rivals: list[Rival] = field(default_factory=list)
    cam: Camera = Camera()
    time: float = 0.0                               # レースの時計（GO からの秒数）
    clock: float = -COUNTDOWN                       # スタート前は負
    started: bool = False
    counted: int = 4                                # 最後に鳴らしたカウント（4 = まだ）
    steer: float = 0.0                              # -1 左、+1 右
    throttle: bool = False
    brake: bool = False
    note: str = ""
    note_until: float = -1.0
    hit_cool: float = 0.0
    rank: int = 0                                   # ゴールした時点の順位（0 は未）

    def __post_init__(self):
        self.luck = random.Random(self.seed)
        start = self.track.at(0.0)
        self.player = Car(start + self.track.rights[0].scale(-1.0), self.track.yaw_at(0.0), CAR)
        self.rivals = []
        for k, (pace, lane) in enumerate(zip(RIVAL_PACE, RIVAL_LANES)):
            s = 7.0 * (k + 1)                       # プレイヤーの前に並ぶ（自分は最後尾からスタート）
            car = Car(self.track.at(s, lane), self.track.yaw_at(s), RIVAL_COLORS[k])
            car.along = s
            self.rivals.append(Rival(car, pace, lane, self.luck.uniform(0, math.tau), s))
        self.cam = self.follow(self.player, 1.0)

    # 車を動かす
    def drive(self, car: Car, dt: float) -> None:
        """プレイヤーの車。アクセル・ブレーキ・抵抗、曲がる、進む、道の高さに乗せる。"""
        if self.throttle:
            car.speed += ACCEL * dt
        if self.brake:
            car.speed -= BRAKE * dt
        drag = DRAG + (OFF_DRAG if not car.on_road else 0.0)
        car.speed -= car.speed * drag * dt
        car.speed = max(0.0, car.speed)
        # 曲がる速さ = TURN × (速さ / (速さ + GRIP)) × (1 − 速さ / (最高速 × 2))
        # 止まっていては曲がれず、速いほど曲がりにくい（曲がる半径 = 速さ ÷ 曲がる速さ が速さより速く増える）
        turn = TURN * (car.speed / (car.speed + GRIP)) * (1 - car.speed / (ACCEL / DRAG * 2))
        car.yaw += self.steer * turn * dt
        car.pos = car.pos + heading(car.yaw).scale(car.speed * dt)
        self.settle(car)

    def settle(self, car: Car) -> None:
        """コースの上のどこにいるかを調べ、道の高さに乗せ、周回を数える。"""
        i, s, lateral, height = self.track.locate(car.pos, car.hint)
        crossed = car.along > self.track.length * 0.8 and s < self.track.length * 0.2
        backed = car.along < self.track.length * 0.2 and s > self.track.length * 0.8
        car.hint, car.along, car.lateral = i, s, lateral
        car.on_road = abs(lateral) <= ROAD_HALF + SHOULDER
        car.pos = V(car.pos.x, height, car.pos.z)
        if crossed:
            car.lap += 1
        elif backed:
            car.lap -= 1

    def run_rival(self, rival: Rival, dt: float) -> None:
        """CPU カーはコースの道のり s で進む。曲がりのきついところは遅く。"""
        car = rival.car
        i = bisect_right(self.track.dist, rival.s % self.track.length) - 1
        want = rival.pace * max(0.65, 1 - self.track.bend[i] * 1.0)   # 測って決めた：自動操縦（19 秒/周）と競る速さ
        if car.stun > 0:
            want *= 0.5
        car.speed += (want - car.speed) * min(1.0, 1.5 * dt)
        rival.s += car.speed * dt
        lane = rival.lane + 0.8 * math.sin(self.time * 0.4 + rival.phase)
        car.pos = self.track.at(rival.s, lane)
        car.yaw = self.track.yaw_at(rival.s)
        car.lap = int(rival.s // self.track.length)
        car.along = rival.s % self.track.length
        car.stun = max(0.0, car.stun - dt)

    def follow(self, car: Car, ease: float) -> Camera:
        """車の後ろ・少し上。向きは車の向きへ少し遅れて寄る。"""
        back = heading(car.yaw).scale(-CAM_BACK)
        want = V(car.pos.x + back.x, car.pos.y + CAM_UP, car.pos.z + back.z)
        yaw = self.cam.yaw + math.remainder(car.yaw - self.cam.yaw, math.tau) * ease
        pos = self.cam.pos + (want - self.cam.pos).scale(ease)
        return Camera(pos, yaw)

    def tell(self, text: str, seconds: float = 1.5) -> None:
        self.note = text
        self.note_until = self.clock + seconds

    def update(self, dt: float) -> str | None:
        """1 コマ進める。起きたこと（EVENTS のどれか）を返す。"""
        if not self.started:
            return None
        happened = None
        self.clock += dt
        if self.clock < 0:                          # カウントダウン中は動かない
            due = int(-self.clock) + 1
            if due < self.counted:
                self.counted = due
                happened = "count"
            self.cam = self.follow(self.player, min(1.0, 4 * dt))
            return happened
        if self.time == 0.0 and self.clock >= 0:
            happened = "go"
            self.tell("GO!", 1.0)
        self.time += dt
        self.hit_cool = max(0.0, self.hit_cool - dt)
        player = self.player
        if not player.finished():
            before = player.lap
            self.drive(player, dt)
            if player.lap > before:
                lap_time = self.time - player.lap_start
                player.lap_times.append(lap_time)
                player.lap_start = self.time
                if player.lap >= LAPS:
                    player.finished_at = self.time
                    self.rank = 1 + sum(1 for r in self.rivals if r.car.progress > player.progress)
                    self.tell(f"ゴール！ {self.rank} 位", 5.0)
                    happened = "finish"
                else:
                    self.tell(f"LAP {lap_time:.2f}")
                    happened = "lap"
            elif player.lap < before:
                self.tell("逆走！", 1.0)
        else:
            self.throttle, self.brake = False, False
            self.drive(player, dt)
        for rival in self.rivals:
            self.run_rival(rival, dt)
            if rival.car.lap >= LAPS and not rival.car.finished():
                rival.car.finished_at = self.time
        # 接触：減速して押し出す
        for rival in self.rivals:
            gap = (rival.car.pos - player.pos).flat()
            if math.sqrt(gap.dot(gap)) < HIT_DIST and self.hit_cool == 0 and not player.finished():
                self.hit_cool = 0.8
                player.speed *= 0.55
                rival.car.stun = 0.8
                push = gap.unit().scale(-1.2) if gap.dot(gap) > 1e-6 else V(1.2, 0, 0)
                player.pos = player.pos + push
                self.settle(player)
                self.tell("接触！", 0.8)
                happened = happened or "hit"
        self.cam = self.follow(player, min(1.0, 6 * dt))
        return happened

    def standings(self) -> list[Car]:
        """順位。周回数と道のりで並べる。ゴール済みはゴールの順。"""
        cars = [self.player] + [r.car for r in self.rivals]
        return sorted(cars, key=lambda c: (c.finished_at if c.finished() else 9e9, -c.progress))

    def position(self) -> int:
        return self.standings().index(self.player) + 1


# ── 描く ────────────────────────────────────────────────────────────────

def fog(color: tuple[int, int, int], z: float) -> tuple[int, int, int]:
    amount = max(0.0, min(0.9, (z - FOG_FROM) / (FAR - FOG_FROM)))
    return tuple(int(c + (b - c) * amount) for c, b in zip(color, SKY))


def shade(base: tuple[int, int, int], normal: V, z: float = 0.0) -> tuple[int, int, int]:
    light = V(*LIGHT_DIR).unit()
    bright = 0.35 + 0.65 * max(0.0, normal.dot(light))
    return fog(tuple(min(255, int(c * bright)) for c in base), z)


def draw_solid(screen: Screen, points: list[V], faces: list[tuple[int, ...]], color: tuple[int, int, int]) -> None:
    """立体をひとつ描く。こちらを向いた面だけを、奥から順に塗る。NEAR をまたぐ面は切る。"""
    if max(p.z for p in points) < NEAR:
        return
    scale = screen.width / WIDTH
    drawn = []
    for face in faces:
        a, b, c = points[face[0]], points[face[1]], points[face[2]]
        normal = (b - a).cross(c - a).unit()
        if normal.dot(a) >= 0:
            continue
        poly = clip_near([points[i] for i in face])
        if len(poly) < 3:
            continue
        depth = sum(p.z for p in poly) / len(poly)
        drawn.append((depth, [project(p, scale) for p in poly], shade(color, normal, depth)))
    for _, flat, painted in sorted(drawn, key=lambda item: -item[0]):
        screen.fill(flat, painted)


def draw_quad(screen: Screen, quad: list[V], color: tuple[int, int, int], scale: float) -> None:
    """地面の四角（道・路肩・草）。NEAR で切ってから塗る。全部手前なら描かない。"""
    if max(p.z for p in quad) < NEAR:
        return
    poly = clip_near(quad) if min(p.z for p in quad) < NEAR else quad
    if len(poly) >= 3:
        screen.fill([project(p, scale) for p in poly], color)


def draw_car(screen: Screen, car: Car, cam: Camera, roll: float = 0.0) -> None:
    for (points, faces), color in ((BODY, car.color), (CABIN, CAR_GLASS)):
        placed = [view(rotate(p, 0.0, car.yaw, roll) + car.pos, cam) for p in points]
        draw_solid(screen, placed, faces, color)


def draw_tree(screen: Screen, base: V, scale: float) -> None:
    """木。幹は細い四角、葉は三角。どちらもカメラに正対した板（ビルボード）。"""
    if base.z < NEAR + 0.5:
        return
    trunk = [V(base.x - 0.25, base.y, base.z), V(base.x + 0.25, base.y, base.z),
             V(base.x + 0.25, base.y + 2.0, base.z), V(base.x - 0.25, base.y + 2.0, base.z)]
    crown = [V(base.x - 1.8, base.y + 1.6, base.z), V(base.x + 1.8, base.y + 1.6, base.z), V(base.x, base.y + 5.5, base.z)]
    screen.fill([project(p, scale) for p in trunk], fog(TRUNK, base.z))
    screen.fill([project(p, scale) for p in crown], fog(CROWN, base.z))


def draw(screen: Screen, world: World) -> None:
    """空と地面 → 道（奥から）→ 木と CPU カー（奥から）→ 自分の車。"""
    scale = screen.width / WIDTH
    horizon = int(HORIZON * scale)
    screen.band(0, horizon // 2, SKY_TOP)
    screen.band(horizon // 2, horizon, SKY)
    screen.band(horizon, screen.height, GRASS_A)
    track, cam = world.track, world.cam
    start = world.player.hint - 3
    # 断面ごとの左右の点をカメラ座標に（隣の断面と共有するので 1 回ずつ）
    edges = {}
    for k in range(start, start + DRAW_SEGS + 1):
        edges[k] = (view(track.edge(k, -ROAD_HALF - SHOULDER - GRASS_W), cam), view(track.edge(k, -ROAD_HALF - SHOULDER), cam),
                    view(track.edge(k, -ROAD_HALF), cam), view(track.edge(k, ROAD_HALF), cam),
                    view(track.edge(k, ROAD_HALF + SHOULDER), cam), view(track.edge(k, ROAD_HALF + SHOULDER + GRASS_W), cam))
    things = []                                     # (奥行き, 何を) 木と CPU カー
    for k in range(start + DRAW_SEGS - 1, start - 1, -1):   # 奥から
        a, b = edges[k], edges[k + 1]
        depth = (a[2].z + a[3].z) / 2
        if depth > FAR:
            continue
        stripe = (k // 3) % 2
        if k - start < GRASS_SEGS:
            grass = fog(GRASS_A if (k // 6) % 2 else GRASS_B, depth)
            draw_quad(screen, [a[0], a[1], b[1], b[0]], grass, scale)
            draw_quad(screen, [a[4], a[5], b[5], b[4]], grass, scale)
        edge_color = fog(STRIPE_A if stripe else STRIPE_B, depth)
        draw_quad(screen, [a[1], a[2], b[2], b[1]], edge_color, scale)
        draw_quad(screen, [a[3], a[4], b[4], b[3]], edge_color, scale)
        draw_quad(screen, [a[2], a[3], b[3], b[2]], fog(ROAD_A if stripe else ROAD_B, depth), scale)
        if k % TREE_EVERY == 0:
            side = -1 if (k // TREE_EVERY) % 2 else 1
            base = view(track.edge(k, side * (ROAD_HALF + SHOULDER + 3.0)), cam)
            things.append((base.z, "tree", base))
    for rival in world.rivals:
        z = view(rival.car.pos, cam).z
        if NEAR < z < FAR:
            things.append((z, "car", rival.car))
    for z, kind, thing in sorted(things, key=lambda t: -t[0]):
        if kind == "tree":
            draw_tree(screen, thing, scale)
        else:
            draw_car(screen, thing, cam)
    draw_car(screen, world.player, cam, roll=-world.steer * 0.08)


# ── 入力 ────────────────────────────────────────────────────────────────

def obey(world: World, key: str, down: bool = True) -> None:
    """キーを 1 つ受ける。端末もブラウザもここを通る。"""
    if key == "left":
        world.steer = -1.0 if down else (0.0 if world.steer < 0 else world.steer)
    elif key == "right":
        world.steer = 1.0 if down else (0.0 if world.steer > 0 else world.steer)
    elif key == "up":
        world.throttle = down
    elif key == "down":
        world.brake = down
    elif key == "go" and down and not world.started:
        world.started = True


# ── 端末 ────────────────────────────────────────────────────────────────

def read_keys(fd: int) -> list[str]:
    keys = []
    while select.select([fd], [], [], 0)[0]:
        text = os.read(fd, 64).decode(errors="ignore")
        for token, name in (("\x1b[D", "left"), ("\x1b[C", "right"), ("\x1b[A", "up"), ("\x1b[B", "down"),
                            ("a", "left"), ("d", "right"), ("w", "up"), ("s", "down"),
                            ("q", "quit"), ("\x1b", "quit"), ("r", "reset"),
                            (" ", "go"), ("\r", "go"), ("\n", "go")):
            keys.extend([name] * text.count(token))
        if "\x1b[" in text:
            keys = [k for k in keys if k != "quit"] if text.count("\x1b") == text.count("\x1b[") else keys
    return keys


class Speaker:
    def __init__(self):
        import shutil
        import tempfile

        self.player = shutil.which("afplay") or shutil.which("aplay")
        self.folder = tempfile.mkdtemp(prefix="race-3d-")
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


def clock_text(seconds: float) -> str:
    return f"{int(seconds // 60)}:{seconds % 60:05.2f}"


def status(world: World, best: Best, improved: tuple[bool, bool] = (False, False)) -> str:
    """画面の下の 1 行。128 桁に収める（日本語は 2 桁）。"""
    p = world.player
    lap = min(p.lap + 1, LAPS)
    last = p.lap_times[-1] if p.lap_times else 0.0
    note = world.note if world.clock < world.note_until else ""
    if not world.started:
        note = "スペースで始める"
    elif world.clock < 0:
        note = f"{int(-world.clock) + 1}…"
    if p.finished():
        tail = (f"★ {world.rank} 位 {clock_text(p.finished_at)}"
                + ("  ベスト更新！" if improved[0] else "") + ("  最速ラップ！" if improved[1] else "") + "  r でもう一度")
    else:
        tail = f"ベスト {clock_text(best.total) if best.total else '--:--.--'}  q でやめる"
    return (f" LAP {lap}/{LAPS}  {clock_text(world.time)}  前 {last:5.2f}  {world.position()}位  "
            f"速さ {p.speed * 3.6:4.0f}km/h  {note:<10} " + tail)


def run() -> None:
    import termios
    import tty

    world = World(seed=int(time.time()))
    best = load_best()
    improved = (False, False)
    screen = Screen()
    speaker = Speaker()
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    held: dict[str, float] = {}                     # 端末はキーの離しが分からないので、押してから少しの間「押している」
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
                if key == "reset" and world.player.finished():
                    world = World(seed=int(time.time()))
                    world.started = True
                    improved = (False, False)
                elif key in ("left", "right", "up", "down"):
                    held[key] = now + 0.45
                else:
                    obey(world, key)
            for key in ("left", "right", "up", "down"):
                obey(world, key, held.get(key, 0.0) > now)
            lag = min(lag + now - last, 0.25)
            last = now
            while lag >= STEP:
                event = world.update(STEP)
                if event == "finish":
                    improved = best.take(world.player.finished_at, world.player.lap_times)
                    save_best(best)
                    event = "best" if any(improved) else event
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

def autopilot(world: World, ahead: float = 14.0) -> None:
    """自動操縦。少し先の道の中心を狙って曲がり、曲がりがきつければブレーキ。検証と見た目の確認に使う。"""
    p = world.player
    target = world.track.at(p.along + ahead + p.speed * 0.25)
    want = math.atan2(target.x - p.pos.x, target.z - p.pos.z)
    diff = math.remainder(want - p.yaw, math.tau)
    world.steer = max(-1.0, min(1.0, diff * 4))
    i = bisect_right(world.track.dist, (p.along + 20) % world.track.length) - 1
    sharp = world.track.bend[i] > 0.35 and p.speed > 24
    world.throttle = not sharp
    world.brake = sharp and p.speed > 28


def check() -> None:
    track = Track()
    print("● コース")
    assert len(track) == len(COURSE) * SAMPLES
    gaps = [math.dist(track.centers[i], track.centers[(i + 1) % len(track)]) for i in range(len(track))]
    assert max(gaps) / min(gaps) < 3.5, (min(gaps), max(gaps))
    assert abs(track.at(0.0).x - COURSE[0][0]) < 1e-9 and abs(track.at(track.length).x - COURSE[0][0]) < 1e-9
    assert all(abs(r.y) < 1e-9 and abs(r.dot(d)) < 1e-9 for r, d in zip(track.rights, track.dirs)), "右手は地面に平行で進む向きに直角"
    print(f"  制御点 {len(COURSE)} → 断面 {len(track)}、1 周 {track.length:.0f} m、断面の間 {min(gaps):.1f}〜{max(gaps):.1f} m、"
          f"高低差 {max(c.y for c in track.centers) - min(c.y for c in track.centers):.0f} m")
    i, s, lateral, height = track.locate(track.at(120.0, 2.0), bisect_right(track.dist, 120.0) - 3)
    assert abs(s - 120.0) < 2.0 and abs(lateral - 2.0) < 0.2, (s, lateral)
    i, s, lateral, height = track.locate(track.at(track.length - 3.0), len(track) - 2)
    assert s > track.length - 5, s
    print("  道のり 120 m・右 2 m の点を locate すると、道のり 120・横 2 に戻る")
    print("● ニアクリッピング")
    quad = [V(-1, 0, -2), V(1, 0, -2), V(1, 0, 4), V(-1, 0, 4)]
    cut = clip_near(quad)
    assert len(cut) == 4 and min(p.z for p in cut) >= NEAR - 1e-9 and max(p.z for p in cut) == 4, cut
    assert all(abs(p.z - NEAR) < 1e-9 for p in cut if p.z < 1), "切り口は NEAR の面の上"
    assert clip_near([V(0, 0, -1), V(1, 0, -1), V(0, 0, -2)]) == []
    assert clip_near([V(0, 0, 1), V(1, 0, 1), V(0, 0, 2)]) == [V(0, 0, 1), V(1, 0, 1), V(0, 0, 2)]
    print(f"  視点をまたぐ四角は z = {NEAR} で切られて四角のまま。全部後ろなら空、全部前ならそのまま")
    print("● カメラ")
    cam = Camera(V(0, CAM_UP, 0), math.pi / 2)      # 右（+x）を向く
    ahead = view(V(10, CAM_UP, 0), cam)
    assert abs(ahead.x) < 1e-9 and ahead.z > 9, ahead
    left = view(V(0, CAM_UP, 10), cam)              # 世界の +z は、右を向いたカメラの左
    assert left.x < -9, left
    assert abs(project(view(V(0, CAM_UP, 1000), Camera(V(0, CAM_UP, 0), 0.0)))[1] - HORIZON) < 0.1
    print("  右を向けば +x が正面に、+z は左に見える。遠くの点は地平線の行に落ちる")
    print("● 車の動き")
    world = World(seed=1)
    world.started = True
    for _ in range(int((COUNTDOWN + 0.1) / STEP)):
        world.update(STEP)
    assert world.time > 0 and world.player.speed == 0
    for _ in range(30 * 5):                          # 最初の直線（150 m ほど）。向きだけ自動操縦に任せる
        autopilot(world)
        world.throttle, world.brake = True, False
        world.update(STEP)
    top = world.player.speed
    assert 30 < top < ACCEL / DRAG and world.player.on_road, (top, world.player.on_road)
    yaw0 = world.player.yaw
    world.steer = 1.0
    for _ in range(30):
        world.update(STEP)
    fast_turn = math.remainder(world.player.yaw - yaw0, math.tau)
    assert fast_turn > 0
    world.steer = 0.0
    world.throttle = False
    world.brake = True
    for _ in range(30 * 3):
        world.update(STEP)
    slow = world.player.speed
    assert slow < top * 0.3
    print(f"  アクセル 5 秒で {top * 3.6:.0f} km/h、右へ 1 秒で {math.degrees(fast_turn):.0f}°、ブレーキ 3 秒で {slow * 3.6:.0f} km/h")
    world = World(seed=1)
    world.started = True
    world.clock = 0.0
    world.player.speed = 10.0
    world.steer = 1.0
    world.update(STEP)
    slow_turn = world.player.yaw - world.track.yaw_at(0.0)
    world.player.speed = 40.0
    yaw1 = world.player.yaw
    world.update(STEP)
    assert (world.player.yaw - yaw1) < slow_turn, "速いほど曲がりにくい"
    print("  10 m/s と 40 m/s では、40 の方が 1 コマで曲がる角度が小さい")
    world = World(seed=1)
    world.started = True
    world.clock = 0.0
    world.rivals = []                                # ぶつからないように
    world.player.pos = world.player.pos + world.track.rights[0].scale(ROAD_HALF + SHOULDER + 3)   # 草の上
    world.player.speed = 30.0
    world.update(STEP)
    assert not world.player.on_road
    for _ in range(30):
        world.update(STEP)
    grass_speed = world.player.speed
    world = World(seed=1)
    world.started = True
    world.clock = 0.0
    world.rivals = []
    world.player.speed = 30.0
    for _ in range(31):
        world.update(STEP)
    assert grass_speed < world.player.speed * 0.5, (grass_speed, world.player.speed)
    print(f"  同じ 30 m/s から 1 秒惰性で、道の上 {world.player.speed:.1f}、草の上 {grass_speed:.1f}")
    print("● 自動操縦で 3 周")
    world = World(seed=2)
    world.started = True
    events = []
    for _ in range(30 * 150):
        autopilot(world)
        got = world.update(STEP)
        if got:
            events.append(got)
        if world.player.finished():
            break
    p = world.player
    assert p.finished() and len(p.lap_times) == LAPS, (p.lap, p.lap_times)
    assert events.count("count") == 3 and events.count("go") == 1 and events.count("lap") == LAPS - 1 and events.count("finish") == 1, events
    assert 1 <= world.rank <= 4
    assert all(r.car.lap >= 0 for r in world.rivals)
    print(f"  {clock_text(p.finished_at)} でゴール（ラップ {', '.join(f'{t:.1f}' for t in p.lap_times)}）、{world.rank} 位。"
          f"CPU は {[r.car.lap + 1 if not r.car.finished() else 'ゴール' for r in world.rivals]} 周目")
    print("● 順位")
    world = World(seed=3)
    world.started = True
    world.clock = 0.0
    assert world.position() == 4, "最後尾から始まる"
    for _ in range(30 * 10):
        world.update(STEP)
    assert world.position() == 4, "止まっていれば全員に抜かれて 4 位"
    order = world.standings()
    assert all(order[i].progress >= order[i + 1].progress for i in range(3))
    print("  止まっていれば 10 秒で 4 位。順位は周回 → 道のり の順")
    print("● 接触")
    world = World(seed=4)
    world.started = True
    world.clock = world.time = 0.5                   # GO のあと
    world.player.speed = 30.0
    rival = world.rivals[0]
    rival.s = world.player.along + 1.5
    rival.lane = world.player.lateral
    got = world.update(STEP)
    assert got == "hit" and world.player.speed < 20 and world.note == "接触！"
    print("  CPU カーに重なると「接触」、速さが半分ほどに落ちて押し出される")
    print("● 板の大きさ")
    world = World(seed=2)
    world.started = True
    for _ in range(30 * 12):
        autopilot(world)
        world.update(STEP)
    small, big = Screen(), Screen(WIDTH * 2, HEIGHT * 2)
    started = time.perf_counter()
    draw(small, world)
    took_small = time.perf_counter() - started
    started = time.perf_counter()
    draw(big, world)
    took_big = time.perf_counter() - started
    same = sum(1 for y in range(HEIGHT) for x in range(WIDTH) if small.pixel(x, y) == big.pixel(x * 2, y * 2))
    print(f"  128×80 を描くのに {took_small * 1000:.1f} ms、256×160 は {took_big * 1000:.1f} ms。偶数ドットの一致 {same / (WIDTH * HEIGHT):.0%}")
    assert same / (WIDTH * HEIGHT) > 0.9
    print("● 記録")
    best = Best.parse("")
    assert best == Best() and Best.parse("{x") == Best()
    assert best.take(70.0, [24.0, 23.0, 23.0]) == (True, True) and best == Best(70.0, 23.0)
    assert best.take(75.0, [22.5, 26.0, 26.5]) == (False, True) and best == Best(70.0, 22.5)
    assert best.take(69.0, [23.0, 23.0, 23.0]) == (True, False)
    assert Best.parse(best.dump()) == best
    print("  総合とラップは別々に更新。dump → parse で戻る")
    print("● 音")
    assert len({sound_bytes(k) for k in SOUNDS}) == len(SOUNDS) and all(k in SOUNDS for k in EVENTS)
    print(f"  {len(SOUNDS)} つ全部別の音。返す出来事には全部音がある")
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


def shot(path: str, seconds: float = 9.0) -> None:
    world = World(seed=3)
    world.started = True
    for _ in range(int(seconds / STEP)):
        autopilot(world)
        world.update(STEP)
    screen = Screen(WIDTH * 2, HEIGHT * 2)
    draw(screen, world)
    with open(path, "wb") as out:
        out.write(png_bytes(screen, 2))
    print(f"{path} に書き出した（{seconds} 秒後、{world.player.speed * 3.6:.0f} km/h）")


def track_map(path: str) -> None:
    """コースを真上から。道と断面、スタート、木。"""
    track = Track()
    xs = [c.x for c in track.centers]
    zs = [c.z for c in track.centers]
    size = 256
    lo_x, lo_z = min(xs) - 12, min(zs) - 12
    k = (size - 1) / max(max(xs) - lo_x + 12, max(zs) - lo_z + 12)
    screen = Screen(size, size)
    screen.band(0, size, GRASS_A)
    for i in range(len(track)):
        quad = [track.edge(i, -ROAD_HALF), track.edge(i, ROAD_HALF), track.edge(i + 1, ROAD_HALF), track.edge(i + 1, -ROAD_HALF)]
        flat = [((p.x - lo_x) * k, size - 1 - (p.z - lo_z) * k) for p in quad]
        screen.fill(flat, ROAD_A if (i // 3) % 2 else ROAD_B)
        if i % TREE_EVERY == 0:
            side = -1 if (i // TREE_EVERY) % 2 else 1
            t = track.edge(i, side * (ROAD_HALF + SHOULDER + 3.0))
            screen.plot(int((t.x - lo_x) * k), int(size - 1 - (t.z - lo_z) * k), CROWN)
    s = track.edge(0, -ROAD_HALF)
    e = track.edge(0, ROAD_HALF)
    screen.line(((s.x - lo_x) * k, size - 1 - (s.z - lo_z) * k), ((e.x - lo_x) * k, size - 1 - (e.z - lo_z) * k), STRIPE_B)
    with open(path, "wb") as out:
        out.write(png_bytes(screen, 2))
    print(f"{path} に書き出した（1 周 {track.length:.0f} m）")


def main() -> None:
    if "--check" in sys.argv:
        check()
    elif "--shot" in sys.argv:
        shot(sys.argv[sys.argv.index("--shot") + 1] if len(sys.argv) > 2 else "shot.png")
    elif "--map" in sys.argv:
        track_map(sys.argv[sys.argv.index("--map") + 1] if len(sys.argv) > 2 else "map.png")
    else:
        run()


if __name__ == "__main__":
    main()
