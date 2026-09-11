"""3D レース ブラウザ版

CLI 版（g79-race-3d/main.py）と中身はまったく同じ。3D の点（V）も、回転（rotate）も、カメラ（view）も、
ニアクリッピング（clip_near）も、コース（Track）も、車（World.drive）も、CPU カーも 1 文字も変えていない。

違うのは入口と出口だけ。
  入口: 端末はキーの並び（押してから少しの間「押している」扱い）、ブラウザは keydown / keyup とボタン
  出口: 端末は ▀ の並び、ブラウザは canvas（2 倍の板）。音は端末が afplay、ブラウザは Audio
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
from bisect import bisect_right
from dataclasses import dataclass, field
from typing import NamedTuple

from pyscript import document, when, window


WIDTH = 128                                         # 画面の横（ドット）。端末では 1 ドット = 1 桁


HEIGHT = 80                                         # 縦。端末では 2 ドット = 1 行 → 40 行


CX = WIDTH // 2


CY = HEIGHT // 2


FOCUS = 62.0                                        # 焦点距離


NEAR = 0.5                                          # これより手前は切る（ニアクリッピング）


FAR = 95.0                                          # 道を描く奥行き


FOG_FROM = 30.0                                     # ここより奥は空の色に溶ける


CAM_BACK = 5.2                                      # カメラは車の後ろ何 m か


CAM_UP = 2.0                                        # カメラの高さ（車の位置から）


TILT = 0.14                                         # カメラの見下ろし（ラジアン）。地平線が真ん中より上に来る


STEP = 1 / 30


ROAD_HALF = 4.5                                     # 道の半分の幅


KERB = 0.55                                         # 縁石（赤白の縞）の幅


DIRT = 1.0                                          # 縁石の外の土の幅


LINE = 0.18                                         # 白線の幅


SHOULDER = KERB + DIRT                              # 道の外（ここまでは減速しない）


GRASS_W = 60.0                                      # 道の外の草を描く幅


SAMPLES = 20                                        # 制御点と制御点の間を何分割するか


DRAW_SEGS = 56                                      # 前方に描く断面の数


GRASS_SEGS = 30                                     # 草の縞を描く断面の数（遠くは平らな色）


DETAIL_SEGS = 34                                    # 土と白線を描く断面の数


TREE_EVERY = 7                                      # 何断面ごとに木を立てるか


TUNNEL = (118, 146)                                 # トンネルの断面（この範囲は暗い）


TUNNEL_H = 5.0                                      # トンネルの高さ


RAIL_TURN = 0.12                                    # これより曲がる断面には、外側にガードレール


SIGN_TURN = 0.3                                     # これより曲がるカーブの前には、矢印の看板


SUN_ANGLE = 0.9                                     # 太陽の向き（ラジアン）


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


GEARS = (0.0, 9.0, 18.0, 28.0, 44.5)                # ギアの切り替わる速さ（m/s）。4 速


ENGINE_HZ = 110.0                                   # エンジン音の輪（0.5 秒）の基本の高さ。速さで再生の速さを変える


COURSE = [(0, 0, 0), (0, 70, 0), (-12, 130, 4), (30, 170, 9), (85, 160, 7), (105, 110, 2),
          (80, 70, 0), (95, 20, -2), (70, -30, -4), (30, -55, -2), (0, -40, 0)]


SKY_TOP = (70, 125, 205)


SKY = (178, 205, 232)                               # 地平線の近く。霧もこの色へ溶ける


CLOUD = (240, 244, 250)


MOUNTAIN_FAR = (120, 150, 190)


MOUNTAIN_NEAR = (86, 118, 150)


GRASS_A = (74, 138, 62)


GRASS_B = (70, 131, 59)


DIRT_COLOR = (150, 128, 90)


ROAD_A = (84, 84, 90)


ROAD_B = (80, 80, 86)


LINE_COLOR = (225, 225, 220)


STRIPE_A = (205, 55, 45)


STRIPE_B = (232, 232, 226)


TRUNK = (92, 64, 38)


CROWN = (36, 100, 44)                               # 針葉樹


LEAF = (66, 132, 52)                                # 広葉樹


BUSH = (52, 112, 46)


SHADE = (46, 92, 40)                                # 木の影


RAIL = (205, 205, 200)


POST = (120, 120, 118)


TUNNEL_WALL = (70, 66, 62)


TUNNEL_MOUTH = (150, 146, 138)


HILL = (58, 118, 54)


TUNNEL_LAMP = (255, 240, 180)


SIGN_BOARD = (245, 200, 40)


SIGN_MARK = (20, 20, 20)


SUN = (255, 246, 210)


SUN_HALO = (232, 226, 205)


BANNER = (240, 240, 235)


BANNER_DARK = (25, 25, 25)


CAR = (230, 70, 60)                                 # 自分の車


CAR_GLASS = (150, 200, 235)


RIVAL_COLORS = ((60, 110, 220), (240, 200, 60), (180, 90, 200))


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


def engine_bytes() -> bytes:
    """エンジン音の輪。ノコギリ波に近い倍音の和（1/n、8 個）を 0.5 秒。ちょうど 55 周期なので、つないでも切れ目が無い。
    ブラウザはこれを loop で回し、playbackRate を速さで変えて音の高さにする。
    基本の高さは 110 Hz——60 Hz にしたら、スマホやノートのスピーカーでは低すぎて聞こえなかった。"""
    count = int(RATE * 0.5)
    samples = array("h")
    for i in range(count):
        t = i / RATE
        wave_ = sum(math.sin(math.tau * ENGINE_HZ * n * t) / n for n in range(1, 9))
        samples.append(int(32767 * 0.22 * wave_))
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(samples.tobytes())
    return buffer.getvalue()


def engine(speed: float) -> tuple[int, float]:
    """速さから (ギア, 再生の速さ) を決める。ギアの中では速いほど高く、ギアが変わると下がる。"""
    gear = max(1, min(len(GEARS) - 1, bisect_right(GEARS, speed)))
    lo, hi = GEARS[gear - 1], GEARS[gear]
    frac = max(0.0, min(1.0, (speed - lo) / (hi - lo)))
    return gear, 0.6 + 1.3 * frac


EVENTS = ("count", "go", "lap", "hit", "finish")    # update() が返す出来事


SOUNDS = EVENTS + ("best",)


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
        # 曲がり：少し前と少し後ろの向きの差。符号つき（右カーブが正）と、大きさ
        self.turn = [math.atan2(self.dirs[i - 3].cross(self.dirs[(i + 3) % m]).y,
                                self.dirs[(i + 3) % m].dot(self.dirs[i - 3])) for i in range(m)]
        self.bend = [abs(t) for t in self.turn]
        # ガードレールはカーブの外側（右カーブなら左）。少し手前から少し先まで
        self.rail = [0] * m
        for i in range(m):
            wide = max(range(i - 4, i + 5), key=lambda k: self.bend[k % m])
            if self.bend[wide % m] > RAIL_TURN:
                self.rail[i] = -1 if self.turn[wide % m] > 0 else 1
        # 暗さ：トンネルの中は暗い。出入り口は 4 断面で変わる
        self.dark = [1.0] * m
        for i in range(m):
            inside = min(i - TUNNEL[0], TUNNEL[1] - i)
            if inside >= 0:
                self.dark[i] = 0.42 + 0.58 * max(0.0, 1 - inside / 4)

    def in_tunnel(self, i: int) -> bool:
        return TUNNEL[0] <= i % len(self.centers) <= TUNNEL[1]

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


LIGHT_DIR = (-0.4, 0.9, -0.5)


PROFILE = [(-2.1, 0.32), (-2.1, 0.95), (-1.35, 1.02), (-0.85, 1.36), (0.25, 1.36), (0.85, 0.98), (2.05, 0.78), (2.1, 0.32)]


HALF_W = 0.92


GLASS_SPANS = ((2, 3), (4, 5))                      # PROFILE のどの区間がガラスか（リアウィンドウ、フロントガラス）


WHEEL_R = 0.33


WHEEL_AT = ((-0.86, 1.3), (0.86, 1.3), (-0.86, -1.3), (0.86, -1.3))   # (x, z)


def car_body() -> tuple[list[V], list[tuple[int, ...]], list[str]]:
    """車体。横顔を左右に押し出し、上面（区間ごと）・左右の面・前後の面を作る。面ごとに材質の名前を返す。"""
    n = len(PROFILE)
    points = [V(sx * HALF_W, y, z) for z, y in PROFILE for sx in (-1, 1)]   # 2k = 左、2k+1 = 右
    faces: list[tuple[int, ...]] = []
    kinds: list[str] = []
    for k in range(n - 1):                          # 上面（後ろから前へ。最初と最後は縦の面＝後ろ・前）
        faces.append((2 * k, 2 * k + 1, 2 * k + 3, 2 * k + 2))
        kinds.append("glass" if (k, k + 1) in GLASS_SPANS else "body")
    faces.append(tuple(range(0, 2 * n, 2)))         # 左の面（横顔そのもの）
    faces.append(tuple(range(1, 2 * n, 2)))         # 右の面
    kinds += ["side", "side"]
    faces.append((0, 2 * n - 2, 2 * n - 1, 1))      # 底
    kinds.append("under")
    return points, outward(points, faces), kinds


def wheel(x: float, z: float, sides: int = 8) -> tuple[list[V], list[tuple[int, ...]]]:
    """タイヤ。x 軸に沿った 8 角柱。"""
    points = []
    for sx in (-0.17, 0.17):
        for i in range(sides):
            a = i * math.tau / sides
            points.append(V(x + sx, WHEEL_R + WHEEL_R * math.cos(a), z + WHEEL_R * math.sin(a)))
    faces = [tuple(range(sides)), tuple(range(sides, 2 * sides))]
    for i in range(sides):
        j = (i + 1) % sides
        faces.append((i, j, sides + j, sides + i))
    return points, outward(points, faces)


CAR_BODY = car_body()


WHEELS = [wheel(x, z) for x, z in WHEEL_AT]


SIDE_WINDOW = [V(0, 1.02, -1.25), V(0, 1.30, -0.8), V(0, 1.30, 0.2), V(0, 1.02, 0.75)]   # 横の窓（x は左右で ±）


SHADOW = [V(math.cos(a) * 1.25, 0.02, math.sin(a) * 2.3) for a in (i * math.tau / 8 for i in range(8))]


TIRE = (28, 28, 32)


HUB = (150, 150, 150)


GLASS = (110, 150, 190)


SHADOW_COLOR = (36, 36, 40)


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


def fog(color: tuple[int, int, int], z: float) -> tuple[int, int, int]:
    amount = max(0.0, min(0.9, (z - FOG_FROM) / (FAR - FOG_FROM)))
    return tuple(int(c + (b - c) * amount) for c, b in zip(color, SKY))


def dim(color: tuple[int, int, int], k: float) -> tuple[int, int, int]:
    """暗くする（トンネルの中）。"""
    return color if k >= 1.0 else tuple(int(c * k) for c in color)


def shade(base: tuple[int, int, int], normal: V, z: float = 0.0) -> tuple[int, int, int]:
    light = V(*LIGHT_DIR).unit()
    bright = 0.35 + 0.65 * max(0.0, normal.dot(light))
    return fog(tuple(min(255, int(c * bright)) for c in base), z)


def draw_solid(screen: Screen, points: list[V], faces: list[tuple[int, ...]], color: tuple[int, int, int],
               colors: list[tuple[int, int, int]] | None = None) -> None:
    """立体をひとつ描く。こちらを向いた面だけを、奥から順に塗る。NEAR をまたぐ面は切る。
    colors を渡せば面ごとに色を変えられる（車の窓など）。"""
    if max(p.z for p in points) < NEAR:
        return
    scale = screen.width / WIDTH
    drawn = []
    for k, face in enumerate(faces):
        a, b, c = points[face[0]], points[face[1]], points[face[2]]
        normal = (b - a).cross(c - a).unit()
        if normal.dot(a) >= 0:
            continue
        poly = clip_near([points[i] for i in face])
        if len(poly) < 3:
            continue
        depth = sum(p.z for p in poly) / len(poly)
        drawn.append((depth, [project(p, scale) for p in poly], shade(colors[k] if colors else color, normal, depth)))
    for _, flat, painted in sorted(drawn, key=lambda item: -item[0]):
        screen.fill(flat, painted)


def draw_quad(screen: Screen, quad: list[V], color: tuple[int, int, int], scale: float) -> None:
    """地面の四角（道・路肩・草）。NEAR で切ってから塗る。全部手前なら描かない。"""
    if max(p.z for p in quad) < NEAR:
        return
    poly = clip_near(quad) if min(p.z for p in quad) < NEAR else quad
    if len(poly) >= 3:
        screen.fill([project(p, scale) for p in poly], color)


def draw_car(screen: Screen, car: Car, cam: Camera, roll: float = 0.0, dark: float = 1.0) -> None:
    """車。影 → 車体（面ごとに 車体色／ガラス／下回り）→ タイヤ → 横の窓 → ライト。dark はトンネルの暗さ。"""
    scale = screen.width / WIDTH
    place = lambda p: view(rotate(p, 0.0, car.yaw, roll) + car.pos, cam)   # noqa: E731
    draw_quad(screen, [place(p) for p in SHADOW], dim(SHADOW_COLOR, dark), scale)
    points, faces, kinds = CAR_BODY
    body = dim(car.color, dark)
    under = tuple(int(c * 0.55) for c in body)
    palette = {"body": body, "glass": dim(GLASS, dark), "side": body, "under": under}
    draw_solid(screen, [place(p) for p in points], faces, body, [palette[k] for k in kinds])
    hub = dim(HUB, dark)
    for w_points, w_faces in WHEELS:
        draw_solid(screen, [place(p) for p in w_points], w_faces, TIRE, [hub, hub] + [TIRE] * (len(w_faces) - 2))
    for sx in (-1, 1):                              # 横の窓は車体の面のすぐ外側に貼る
        quad = [place(V(sx * (HALF_W + 0.01), p.y, p.z)) for p in SIDE_WINDOW]
        if min(q.z for q in quad) > NEAR:
            a, b, c = quad[0], quad[1], quad[2]
            if (b - a).cross(c - a).dot(a) < 0:
                depth = sum(q.z for q in quad) / 4
                screen.fill([project(q, scale) for q in quad], dim(fog(GLASS, depth), dark))
    for z, y, color in ((2.11, 0.62, (255, 245, 200)), (-2.11, 0.62, (220, 40, 30))):   # ヘッドライトとテールランプ
        for sx in (-0.6, 0.6):
            quad = [place(V(sx + dx, y + dy, z)) for dx, dy in ((-0.2, -0.08), (0.2, -0.08), (0.2, 0.08), (-0.2, 0.08))]
            if min(q.z for q in quad) > NEAR:
                a, b, c = quad[0], quad[1], quad[2]
                if (b - a).cross(c - a).dot(a) < 0:
                    screen.fill([project(q, scale) for q in quad], fog(color, quad[0].z))


def draw_shadow(screen: Screen, base: V, scale: float, size: float) -> None:
    """木の影。地面に寝た楕円を、光と反対の側（右奥）へずらして置く。"""
    ring = [V(base.x + 1.3 * size + 1.6 * size * math.cos(a), base.y, base.z + 0.8 + 0.7 * size * math.sin(a))
            for a in (i * math.tau / 8 for i in range(8))]
    draw_quad(screen, ring, fog(SHADE, base.z), scale)


def draw_conifer(screen: Screen, base: V, scale: float, size: float = 1.0) -> None:
    """針葉樹。幹と、3 段の三角（下ほど広く暗い）。カメラに正対した板。"""
    z = base.z
    draw_shadow(screen, base, scale, 1.4 * size)
    trunk = [V(base.x - 0.22, base.y, z), V(base.x + 0.22, base.y, z), V(base.x + 0.22, base.y + 1.6, z), V(base.x - 0.22, base.y + 1.6, z)]
    screen.fill([project(p, scale) for p in trunk], fog(TRUNK, z))
    for k, (w, y0, y1, tone_) in enumerate(((2.2, 1.2, 3.4, 0.7), (1.7, 2.4, 4.6, 0.85), (1.2, 3.6, 6.0, 1.0))):
        w, y0, y1 = w * size, y0 * size, y1 * size
        tri = [V(base.x - w, base.y + y0, z), V(base.x + w, base.y + y0, z), V(base.x, base.y + y1, z)]
        color = tuple(int(c * tone_) for c in CROWN)
        screen.fill([project(p, scale) for p in tri], fog(color, z))


def draw_broadleaf(screen: Screen, base: V, scale: float, size: float = 1.0) -> None:
    """広葉樹。幹と、丸い葉（暗い丸の上に明るい丸を少しずらして重ね、立体感）。"""
    z = base.z
    draw_shadow(screen, base, scale, 1.6 * size)
    trunk = [V(base.x - 0.28, base.y, z), V(base.x + 0.28, base.y, z), V(base.x + 0.28, base.y + 2.4, z), V(base.x - 0.28, base.y + 2.4, z)]
    screen.fill([project(p, scale) for p in trunk], fog(TRUNK, z))
    for dx, dy, r, tone_ in ((0.0, 3.9, 2.4, 0.72), (-0.5, 4.3, 1.8, 1.0)):
        r *= size
        ring = [V(base.x + dx + r * math.cos(a), base.y + dy * size + r * 0.85 * math.sin(a), z)
                for a in (i * math.tau / 10 for i in range(10))]
        color = tuple(int(c * tone_) for c in LEAF)
        screen.fill([project(p, scale) for p in ring], fog(color, z))


def draw_bush(screen: Screen, base: V, scale: float) -> None:
    z = base.z
    ring = [V(base.x + 1.1 * math.cos(a), base.y + 0.9 + 0.75 * math.sin(a), z) for a in (i * math.tau / 8 for i in range(8))]
    screen.fill([project(p, scale) for p in ring], fog(BUSH, z))


def ridge(angle: float, layer: int) -> float:
    """地平線の山なみ。向き angle（ラジアン）での高さ。sin を何個か足しただけの決まった形（乱数なし）。"""
    if layer == 0:
        return 5.0 + 3.6 * math.sin(angle * 3 + 0.4) + 2.4 * math.sin(angle * 7 + 2.0) + 1.2 * math.sin(angle * 13)
    return 2.0 + 2.0 * math.sin(angle * 4 + 1.1) + 1.4 * math.sin(angle * 9 + 0.3) + 0.8 * math.sin(angle * 17 + 2.5)


def draw_backdrop(screen: Screen, cam: Camera, dark: float = 1.0) -> None:
    """空のグラデーション → 雲 → 太陽 → 遠い山 → 近い山。全部「向き」だけで決まる（車が曲がると横に流れる）。"""
    scale = screen.width / WIDTH
    horizon = int(HORIZON * scale)
    for y in range(horizon):                        # 空：上から地平線へ色を変える
        t = y / max(1, horizon)
        screen.band(y, y + 1, tuple(int(a + (b - a) * t) for a, b in zip(SKY_TOP, SKY)))
    screen.band(horizon, screen.height, dim(GRASS_A, dark))
    for k in range(9):                              # 雲：決まった向きに浮かぶ楕円
        angle = k * math.tau / 9 + 0.3
        dx = math.remainder(angle - cam.yaw, math.tau)
        if abs(dx) > 0.9:
            continue
        cx = (CX + FOCUS * math.tan(dx)) * scale
        cy = (HORIZON - 14 - 5 * math.sin(k * 2.1)) * scale
        rx, ry = (8 + 3 * math.sin(k * 1.7)) * scale, 2.6 * scale
        ring = [(cx + rx * math.cos(a), cy + ry * math.sin(a)) for a in (i * math.tau / 10 for i in range(10))]
        screen.fill(ring, CLOUD)
    dx = math.remainder(SUN_ANGLE - cam.yaw, math.tau)   # 太陽：決まった向きに 1 つ
    if abs(dx) < 0.9:
        cx, cy = (CX + FOCUS * math.tan(dx)) * scale, (HORIZON - 24) * scale
        for r, color in ((7.5 * scale, SUN_HALO), (5.0 * scale, SUN)):
            ring = [(cx + r * math.cos(a), cy + r * math.sin(a)) for a in (i * math.tau / 12 for i in range(12))]
            screen.fill(ring, color)
    step = int(6 * scale)                           # 山：列ごとの高さをつないだ台形の並び
    for layer, color in ((0, MOUNTAIN_FAR), (1, MOUNTAIN_NEAR)):
        xs = list(range(0, screen.width + step, step))
        heights = [ridge(cam.yaw + math.atan((x / scale - CX) / FOCUS), layer) * scale for x in xs]
        for x0, x1, h0, h1 in zip(xs, xs[1:], heights, heights[1:]):
            screen.fill([(x0, horizon - h0), (x1, horizon - h1), (x1, horizon + 1), (x0, horizon + 1)], color)


def draw_sign(screen: Screen, base: V, right_turn: bool, scale: float) -> None:
    """カーブの矢印看板。黄色い板に黒い三角（曲がる向き）。柱 2 本。カメラに正対した板。"""
    z = base.z
    for dx in (-0.9, 0.9):
        post = [V(base.x + dx - 0.07, base.y, z), V(base.x + dx + 0.07, base.y, z), V(base.x + dx + 0.07, base.y + 1.2, z), V(base.x + dx - 0.07, base.y + 1.2, z)]
        screen.fill([project(p, scale) for p in post], fog(POST, z))
    board = [V(base.x - 1.3, base.y + 1.0, z), V(base.x + 1.3, base.y + 1.0, z), V(base.x + 1.3, base.y + 2.3, z), V(base.x - 1.3, base.y + 2.3, z)]
    screen.fill([project(p, scale) for p in board], fog(SIGN_BOARD, z))
    tip = 0.8 if right_turn else -0.8
    mark = [V(base.x - tip, base.y + 1.2, z), V(base.x + tip, base.y + 1.65, z), V(base.x - tip, base.y + 2.1, z)]
    screen.fill([project(p, scale) for p in mark], fog(SIGN_MARK, z))


def draw_gantry(screen: Screen, a: list[V], up: V, scale: float, dark: float) -> None:
    """スタートラインの門。柱 2 本と、白黒の横断幕。"""
    lo, hi = up.scale(4.6), up.scale(6.0)
    left, right = a[1], a[10]
    for foot in (left, right):
        post = [foot, foot + V(0.18, 0, 0), foot + V(0.18, 0, 0) + hi, foot + hi]
        draw_quad(screen, post, dim(fog(POST, foot.z), dark), scale)
    span = right - left
    for i in range(8):                              # 8 マスの市松
        p0, p1 = left + span.scale(i / 8), left + span.scale((i + 1) / 8)
        quad = [p0 + lo, p1 + lo, p1 + hi, p0 + hi]
        draw_quad(screen, quad, dim(fog(BANNER if i % 2 else BANNER_DARK, quad[0].z), dark), scale)
        mid = up.scale(5.3)
        quad = [p0 + lo, p1 + lo, p1 + mid, p0 + mid]
        draw_quad(screen, quad, dim(fog(BANNER_DARK if i % 2 else BANNER, quad[0].z), dark), scale)


def draw_portal(screen: Screen, a: list[V], up: V, right: V, scale: float, dark: float) -> None:
    """トンネルの出入り口。道を通す丘（緑の山形）と、コンクリートの口（穴の左右と上の 3 枚）。"""
    z = a[3].z
    top = up.scale(TUNNEL_H)
    lid = up.scale(TUNNEL_H + 1.2)
    peak = up.scale(TUNNEL_H + 7.0)
    green = dim(fog(HILL, z), dark)                 # 丘は穴を避けて 3 枚（左・右・上）。穴の奥はそのまま見える
    draw_quad(screen, [a[1] + right.scale(-26.0), a[1] + right.scale(-10.0) + up.scale(TUNNEL_H + 3.0), a[1] + peak, a[1]], green, scale)
    draw_quad(screen, [a[10], a[10] + peak, a[10] + right.scale(10.0) + up.scale(TUNNEL_H + 3.0), a[10] + right.scale(26.0)], green, scale)
    draw_quad(screen, [a[1] + lid, a[10] + lid, a[10] + peak, a[1] + peak], green, scale)
    color = dim(fog(TUNNEL_MOUTH, z), dark)
    far_l, far_r = a[1] + right.scale(-2.5), a[10] + right.scale(2.5)
    draw_quad(screen, [far_l, a[1], a[1] + lid, far_l + lid], color, scale)
    draw_quad(screen, [a[10], far_r, far_r + lid, a[10] + lid], color, scale)
    draw_quad(screen, [a[1] + top, a[10] + top, a[10] + lid, a[1] + lid], color, scale)


def draw(screen: Screen, world: World) -> None:
    """背景（空・雲・山）→ 道（奥から）→ 木・茂み・CPU カー（奥から）→ 自分の車。"""
    scale = screen.width / WIDTH
    track, cam = world.track, world.cam
    draw_backdrop(screen, cam, track.dark[world.player.hint])
    start = world.player.hint - 3
    # 断面ごとの左右の点をカメラ座標に（隣の断面と共有するので 1 回ずつ）
    offsets = (-ROAD_HALF - KERB - DIRT - GRASS_W, -ROAD_HALF - KERB - DIRT, -ROAD_HALF - KERB, -ROAD_HALF, -ROAD_HALF + LINE,
               -LINE / 2, LINE / 2, ROAD_HALF - LINE, ROAD_HALF, ROAD_HALF + KERB, ROAD_HALF + KERB + DIRT, ROAD_HALF + KERB + DIRT + GRASS_W)
    edges = {}
    rights = {}
    up = rotate(V(0.0, 1.0, 0.0), -TILT, 0.0, 0.0)  # カメラから見た「上」（yaw で回しても y 軸は変わらない）
    for k in range(start, start + DRAW_SEGS + 1):    # view は回して足すだけなので、中心と右手を 1 回ずつ変換して足す
        center = view(track.centers[k % len(track)], cam)
        right = rotate(rotate(track.rights[k % len(track)], 0.0, -cam.yaw, 0.0), -TILT, 0.0, 0.0)
        edges[k] = [center + right.scale(o) for o in offsets]
        rights[k] = right
    things: dict[int, list] = {}                    # 断面 k → [(奥行き, 種類, 何を)] 木・茂み・看板・CPU カー。
    m = len(track)                                  # その断面の道を描いた直後に描く（奥の物が手前の壁に隠れる）
    for rival in world.rivals:
        k = start + (rival.car.hint - start) % m
        if k < start + DRAW_SEGS:
            z = view(rival.car.pos, cam).z
            if NEAR < z < FAR:
                things.setdefault(k, []).append((z, "car", rival.car))
    for k in range(start + DRAW_SEGS - 1, start - 1, -1):   # 奥から
        a, b = edges[k], edges[k + 1]
        depth = (a[3].z + a[8].z) / 2
        if depth > FAR:
            continue
        i = k % m
        dark = track.dark[i]
        stripe = (k // 3) % 2
        if k - start < GRASS_SEGS:
            grass = dim(fog(GRASS_A if (k // 5) % 2 else GRASS_B, depth), dark)
            draw_quad(screen, [a[0], a[1], b[1], b[0]], grass, scale)
            draw_quad(screen, [a[10], a[11], b[11], b[10]], grass, scale)
        near_by = k - start < DETAIL_SEGS               # 近くだけ土と白線を描く（遠くは 1 ドットにもならない）
        if near_by:
            dirt = dim(fog(DIRT_COLOR, depth), dark)
            draw_quad(screen, [a[1], a[2], b[2], b[1]], dirt, scale)
            draw_quad(screen, [a[9], a[10], b[10], b[9]], dirt, scale)
        kerb = dim(fog(STRIPE_A if stripe else STRIPE_B, depth), dark)
        draw_quad(screen, [a[2], a[3], b[3], b[2]], kerb, scale)
        draw_quad(screen, [a[8], a[9], b[9], b[8]], kerb, scale)
        draw_quad(screen, [a[3], a[8], b[8], b[3]], dim(fog(ROAD_A if stripe else ROAD_B, depth), dark), scale)
        if near_by:
            line = dim(fog(LINE_COLOR, depth), dark)
            draw_quad(screen, [a[3], a[4], b[4], b[3]], line, scale)   # 道の端の白線
            draw_quad(screen, [a[7], a[8], b[8], b[7]], line, scale)
            if (k // 2) % 2:                                            # 真ん中の破線
                draw_quad(screen, [a[5], a[6], b[6], b[5]], line, scale)
        if track.in_tunnel(i):                          # トンネル：左右の壁と天井、天井の灯り
            wall = dim(fog(TUNNEL_WALL, depth), dark)
            top_a, top_b = up.scale(TUNNEL_H), up.scale(TUNNEL_H)
            draw_quad(screen, [a[1], b[1], b[1] + top_b, a[1] + top_a], wall, scale)
            draw_quad(screen, [b[10], a[10], a[10] + top_a, b[10] + top_b], wall, scale)
            draw_quad(screen, [a[1] + top_a, a[10] + top_a, b[10] + top_b, b[1] + top_b], wall, scale)
            if i % 3 == 0:
                lamp = up.scale(TUNNEL_H - 0.05)
                draw_quad(screen, [a[5] + lamp, a[6] + lamp, b[6] + lamp, b[5] + lamp], fog(TUNNEL_LAMP, depth), scale)
            if i in TUNNEL:
                draw_portal(screen, a, up, rights[k], scale, dark)
        elif track.rail[i] and near_by:                 # ガードレール：カーブの外側
            side = track.rail[i]
            foot_a = a[10] if side > 0 else a[1]
            foot_b = b[10] if side > 0 else b[1]
            band = [foot_a + up.scale(0.5), foot_b + up.scale(0.5), foot_b + up.scale(0.72), foot_a + up.scale(0.72)]
            draw_quad(screen, band, fog(RAIL, depth), scale)
            if i % 2 == 0:
                post = [foot_a, foot_a + rights[k].scale(0.12), foot_a + rights[k].scale(0.12) + up.scale(0.78), foot_a + up.scale(0.78)]
                draw_quad(screen, post, fog(POST, depth), scale)
        if i == 0:
            draw_gantry(screen, a, up, scale, dark)
        here = things.get(k, [])
        if not (track.in_tunnel(i - 3) or track.in_tunnel(i + 3)):   # トンネルの近くに木は生えない
            if i % TREE_EVERY == 0:
                side = -1 if (i // TREE_EVERY) % 2 else 1
                kind = ("conifer", "broadleaf", "conifer", "bush")[(i // TREE_EVERY) % 4]
                base = view(track.edge(k, side * (ROAD_HALF + KERB + DIRT + 2.5 + (i % 5))), cam)
                here.append((base.z, kind, base))
            if i % TREE_EVERY == 3 and (i // TREE_EVERY) % 3 == 0:
                base = view(track.edge(k, (ROAD_HALF + KERB + DIRT + 1.2) * (1 if (i // 3) % 2 else -1)), cam)
                here.append((base.z, "bush", base))
            if track.bend[i] > SIGN_TURN and i % 6 == 0:    # きついカーブの外側に矢印の看板
                side = -1 if track.turn[i] > 0 else 1
                base = view(track.edge(k, side * (ROAD_HALF + KERB + DIRT + 1.6)), cam)
                here.append((base.z, "sign_r" if track.turn[i] > 0 else "sign_l", base))
        for z, kind, thing in sorted(here, key=lambda t: -t[0]):
            if kind == "car":
                draw_car(screen, thing, cam, dark=dark)
            elif z > NEAR + 0.5:
                if kind == "conifer":
                    draw_conifer(screen, thing, scale)
                elif kind == "broadleaf":
                    draw_broadleaf(screen, thing, scale)
                elif kind.startswith("sign"):
                    draw_sign(screen, thing, kind == "sign_r", scale)
                else:
                    draw_bush(screen, thing, scale)
    draw_car(screen, world.player, cam, roll=-world.steer * 0.06, dark=track.dark[world.player.hint])


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


# --- ここから下はブラウザ版だけ。CLI 版の run() / Screen.render() / Speaker / status() にあたる ---

SCALE = 3                                           # ブラウザは 3 倍の板（384 × 240）に描く
canvas = document.querySelector("#screen")
ctx = canvas.getContext("2d")
ctx.imageSmoothingEnabled = False
image = ctx.createImageData(WIDTH * SCALE, HEIGHT * SCALE)
lap_label = document.querySelector("#lap")
time_label = document.querySelector("#time")
last_label = document.querySelector("#last")
rank_label = document.querySelector("#rank")
speed_label = document.querySelector("#speed")
best_label = document.querySelector("#best")
fps_label = document.querySelector("#fps")
note_label = document.querySelector("#note")
message = document.querySelector("#message")
again_button = document.querySelector("#again")
go_button = document.querySelector("#go")
sound_on = document.querySelector("#engine")
gear_label = document.querySelector("#gear")
SAVED = "g79-best"                                  # localStorage の鍵。CLI 版の records.json にあたる


class CanvasScreen(Screen):
    """CLI 版の Screen をそのまま使い、描き終えた画素をまとめて canvas へ送る（g78 と同じ）。"""

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
    """ブラウザで音を出す係。出来事ごとの wav を data URI にして Audio に持たせておく。
    エンジン音は 0.5 秒の輪を loop で回し、playbackRate（再生の速さ＝音の高さ）を速さで変える。
    端末（afplay）は再生の速さを変えられないので、エンジン音はブラウザだけ。"""

    def __init__(self):
        self.made = {}
        for kind in SOUNDS:
            uri = "data:audio/wav;base64," + base64.b64encode(sound_bytes(kind)).decode()
            self.made[kind] = window.Audio.new(uri)
        self.engine = window.Audio.new("data:audio/wav;base64," + base64.b64encode(engine_bytes()).decode())
        self.engine.loop = True
        self.engine.preservesPitch = False          # 速く再生したら高く聞こえるように（既定は高さを保ってしまう）
        self.engine.webkitPreservesPitch = False    # Safari は別の名前
        self.engine.volume = 0.6
        self.running = False

    def say(self, kind: str | None) -> None:
        if kind is None:
            return
        sound = self.made[kind]
        sound.currentTime = 0
        sound.play()

    def start_engine(self) -> None:
        """エンジンを回し始める。**ボタンやキーの処理の中から呼ぶ**——Safari（iPhone）は、
        人が触った処理の中でしか音を出し始められない。loop() のような時計から呼んでも黙って失敗する。"""
        if not self.running:
            self.engine.currentTime = 0
            self.engine.play()
            self.running = True

    def rev(self, speed: float, on: bool) -> None:
        """エンジンの回転。on が False なら止める。"""
        if not on and self.running:
            self.engine.pause()
            self.running = False
        if self.running:
            _, rate = engine(speed)
            self.engine.playbackRate = rate


def clock_text(seconds: float) -> str:
    return f"{int(seconds // 60)}:{seconds % 60:05.2f}"


screen = CanvasScreen(WIDTH * SCALE, HEIGHT * SCALE)
speaker = Speaker()
world = World(seed=int(window.performance.now()))
best = Best.parse(window.localStorage.getItem(SAVED) or "")
improved = (False, False)
frames = []


def refresh() -> None:
    draw(screen, world)
    screen.flush()
    p = world.player
    lap_label.textContent = f"{min(p.lap + 1, LAPS)}/{LAPS}"
    time_label.textContent = clock_text(world.time)
    last_label.textContent = f"{p.lap_times[-1]:.2f}" if p.lap_times else "--.--"
    rank_label.textContent = f"{world.position()} 位"
    speed_label.textContent = f"{p.speed * 3.6:.0f}"
    gear_label.textContent = str(engine(p.speed)[0])
    best_label.textContent = clock_text(best.total) if best.total else "--:--.--"
    if not world.started:
        note = ""
    elif world.clock < 0:
        note = f"{int(-world.clock) + 1}"
    else:
        note = world.note if world.clock < world.note_until else ""
    note_label.textContent = note or " "
    if p.finished():
        message.textContent = (f"ゴール！ {world.rank} 位  {clock_text(p.finished_at)}"
                               + ("  ベスト更新！" if improved[0] else "") + ("  最速ラップ！" if improved[1] else ""))
    elif not world.started:
        message.textContent = "「スタート」で 3・2・1 のあと始まります。← → で曲がる、↑ アクセル、↓ ブレーキ"
    else:
        message.textContent = ""
    again_button.hidden = not p.finished()
    go_button.hidden = world.started


async def loop():
    """刻み幅は CLI 版と同じ STEP に固定する。"""
    global improved
    lag = 0.0
    last = window.performance.now() / 1000
    while True:
        now = window.performance.now() / 1000
        lag = min(lag + now - last, 0.25)
        last = now
        while lag >= STEP:
            event = world.update(STEP)
            if event == "finish":                   # ゴールした瞬間にベストへ取り込んで保存（CLI 版の run と同じ）
                improved = best.take(world.player.finished_at, world.player.lap_times)
                window.localStorage.setItem(SAVED, best.dump())
                event = "best" if any(improved) else event
            speaker.say(event)
            lag -= STEP
        speaker.rev(world.player.speed, world.started and sound_on.checked)
        refresh()
        frames.append(window.performance.now() / 1000)
        del frames[:-30]
        if len(frames) >= 2:
            fps_label.textContent = f"{(len(frames) - 1) / (frames[-1] - frames[0]):.0f}"
        await asyncio.sleep(STEP)


KEYS = {"ArrowLeft": "left", "ArrowRight": "right", "ArrowUp": "up", "ArrowDown": "down",
        "a": "left", "d": "right", "w": "up", "s": "down", " ": "go", "Enter": "go"}


def wake_sound() -> None:
    """人が触ったときに音を起こす（スタート後で、チェックが入っていれば）。"""
    if world.started and sound_on.checked and not world.player.finished():
        speaker.start_engine()


@when("keydown", "body")
def on_down(event):
    key = KEYS.get(event.key)
    if key is not None:
        event.preventDefault()
        obey(world, key, True)
        wake_sound()


@when("keyup", "body")
def on_up(event):
    key = KEYS.get(event.key)
    if key is not None:
        event.preventDefault()
        obey(world, key, False)


@when("click", "#go")
def go(event):
    obey(world, "go")
    go_button.blur()
    wake_sound()
    refresh()


@when("change", "#engine")
def toggle_engine(event):
    wake_sound()


@when("pointerdown", "#screen")
def tap_screen(event):
    wake_sound()


@when("pointerdown", ".pad button[data-key]")
def pad_down(event):
    event.preventDefault()
    obey(world, event.target.getAttribute("data-key"), True)
    wake_sound()


@when("pointerup", ".pad button[data-key]")
def pad_up(event):
    obey(world, event.target.getAttribute("data-key"), False)


@when("pointerleave", ".pad button[data-key]")
def pad_leave(event):
    obey(world, event.target.getAttribute("data-key"), False)


@when("click", "#again")
def again(event):
    global world, improved
    world = World(seed=int(window.performance.now()))
    world.started = True
    improved = (False, False)
    wake_sound()
    refresh()


document.querySelector("#loading").hidden = True
refresh()
asyncio.ensure_future(loop())
