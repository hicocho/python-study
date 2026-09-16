"""軽飛行機で輪をくぐる（3D フライト）

山と谷の上に浮かぶ 12 個の輪を、順にくぐってタイムを競う。コックピット視点。3D は g78〜g80 と同じく自分で書く。
今回新しく覚えるところ：
  3 軸の回転       向きを「前・上・右」の 3 本のベクトルで持ち、ロール・ピッチ・ヨーを機体の軸まわりで回す
  基底で見るカメラ  カメラの「右・上・前」との内積でカメラ座標にする（回転の式を書かない）
  ハイトマップ     マスごとの高さの表から地形の網（メッシュ）を作り、法線で陰影、高さで色
  輪をくぐる判定   輪の面をまたいだ瞬間に、中心からの距離が半径以内か

    python3 main.py            遊ぶ（スペースで始める。← → ロール、↑ ↓ 機首、w / s スロットル。q でやめる）
    python3 main.py --check    決まりを確かめる
    python3 main.py --shot     場面を PNG に書き出す（見た目の確認用）
    python3 main.py --map      地形と輪を真上から PNG に
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
from dataclasses import dataclass, field
from typing import NamedTuple

WIDTH = 128                                         # 画面の横（ドット）。端末では 1 ドット = 1 桁
HEIGHT = 80                                         # 縦。端末では 2 ドット = 1 行 → 40 行
CX = WIDTH // 2
CY = HEIGHT // 2
FOCUS = 74.0                                        # 焦点距離（視野 82°）
NEAR = 1.0
FAR = 1300.0                                        # 地形を描く距離
FOG_FROM = 450.0
STEP = 1 / 30

CELL = 40.0                                         # 地形のマスの一辺（m）。低く飛ぶので細かく
GRID = 64                                           # マスの数（64 × 64 = 2560 m 四方）
NEAR_CELLS = 6                                      # ここまでは 1 マスずつ描く（240 m）
MID_CELLS = 12                                      # ここまでは 2 × 2（480 m）
FAR_CELLS = 26                                      # ここまでは 4 × 4（1040 m）。それより遠くは霞
PATH_STEP = 5.0                                     # 道すじの点の間隔（m）
FLOOR_BASE = 40.0                                   # 谷底の高さの基準
FLOOR_W = 45.0                                      # 谷底（平ら）の半分の幅
WALL_W = 110.0                                      # 谷底から丘の高さへ戻るまでの幅（壁の斜面）
GATE_R = 16.0                                       # 輪の半径
GATE_GAP = 130.0                                    # 輪の間隔（m）
GATE_FIRST = 200.0                                  # 最初の輪までの距離
MISS_PENALTY = 3.0                                  # 輪を外したときに足す秒数
SPEEDS = (55.0, 80.0, 110.0)                        # スロットル 3 段階の速さ（m/s）
ROLL_RATE = 2.8                                     # ロールの速さ（ラジアン/秒）。きびきび
LEVEL_RATE = 1.6                                    # 手を離したとき水平に戻る速さ
PITCH_RATE = 1.2
PITCH_LIMIT = math.radians(50)
BANK_LIMIT = math.radians(75)
TURN_PER_BANK = 1.2                                 # 傾き 1 ラジアンあたりの旋回（ラジアン/秒）
CLIMB_DRAG = 0.35
CAM_BACK = 22.0                                     # カメラは自機の後ろ何 m か
CAM_UP = 7.0
COUNTDOWN = 3.0
LIGHT_DIR = (-0.45, 0.8, -0.4)

SKY_TOP = (78, 130, 210)
SKY = (176, 204, 232)
HAZE = (200, 214, 232)
SUN = (255, 246, 210)
CLOUD = (240, 244, 250)
WATER = (58, 110, 176)
SAND = (186, 176, 136)
GRASS = (84, 146, 70)
FOREST = (52, 108, 54)
ROCK = (138, 126, 112)
ROCK_DARK = (96, 88, 80)
SNOW = (232, 236, 240)
TRUNK = (92, 64, 38)
CROWN = (36, 100, 44)
RING_NEXT = (255, 150, 40)
RING_LATER = (150, 160, 180)
RING_DONE = (90, 200, 120)
RING_MISS = (220, 70, 60)
POLE = (120, 116, 110)
PILLAR = (128, 112, 96)
BRIDGE = (150, 60, 50)
BODY_COLOR = (230, 220, 80)
WING_COLOR = (215, 60, 50)
TAIL_COLOR = (215, 60, 50)
NOSE_COLOR = (70, 70, 76)
PROP_COLOR = (40, 40, 44)
SHADOW_COLOR = (40, 70, 40)
GAUGE = (120, 200, 140)
GAUGE_BG = (28, 30, 34)
MARK = (255, 240, 160)
BUMP_RED = (240, 70, 60)
RATE = 22050
VOLUME = 0.14


# ── 音 ──────────────────────────────────────────────────────────────────

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
    """出来事の音。count は 3・2・1、go は出発、gate はくぐった、miss は外した、bump はぶつかった、finish はゴール、best はベスト更新。"""
    if kind == "count":
        samples = tone(880, 0.12)
    elif kind == "go":
        samples = tone(1320, 0.35)
    elif kind == "gate":
        samples = tone(1047, 0.07) + tone(1319, 0.07) + tone(1568, 0.14)
    elif kind == "miss":
        samples = tone(330, 0.12, VOLUME * 0.8) + tone(262, 0.16, VOLUME * 0.8)
    elif kind == "bump":
        samples = noise(0.3, VOLUME * 1.6, 12.0, 4) + tone(110, 0.2, VOLUME)
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


EVENTS = ("count", "go", "gate", "miss", "bump", "finish")
SOUNDS = EVENTS + ("best",)


# ── 3D の点 ─────────────────────────────────────────────────────────────

class V(NamedTuple):
    """3D の点（ベクトル）。x 東、y 上、z 北。"""

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

    def length(self) -> float:
        return math.sqrt(self.dot(self))

    def unit(self) -> "V":
        return self.scale(1 / (self.length() or 1.0))


def spin(v: V, axis: V, angle: float) -> V:
    """v を axis（単位ベクトル）のまわりに angle だけ回す（ロドリゲスの回転公式）。

    g78 の rotate() は x・y・z 軸まわりだけだった。飛行機は「機体の軸」（前・上・右）まわりに回るので、
    どの向きの軸でも回せる式が要る。v を「軸に平行な成分」と「垂直な成分」に分けて、垂直な成分だけ回す。
    """
    c, s = math.cos(angle), math.sin(angle)
    return v.scale(c) + axis.cross(v).scale(s) + axis.scale(axis.dot(v) * (1 - c))


class Frame(NamedTuple):
    """向き。前・上・右の 3 本（互いに直角の単位ベクトル）。飛行機にもカメラにも使う。"""

    forward: V = V(0.0, 0.0, 1.0)
    up: V = V(0.0, 1.0, 0.0)
    right: V = V(1.0, 0.0, 0.0)

    def roll(self, angle: float) -> "Frame":            # 前の軸まわり：翼を傾ける（正なら右の翼が下がる）
        return Frame(self.forward, spin(self.up, self.forward, -angle), spin(self.right, self.forward, -angle))

    def pitch(self, angle: float) -> "Frame":           # 右の軸まわり：機首を上げ下げ（正なら上げる）
        return Frame(spin(self.forward, self.right, -angle), spin(self.up, self.right, -angle), self.right)

    def yaw(self, angle: float) -> "Frame":             # 上の軸まわり：向きを変える
        return Frame(spin(self.forward, self.up, angle), self.up, spin(self.right, self.up, angle))

    def bank(self) -> float:
        """傾き（ラジアン）。右の翼が下がっていれば正。"""
        return math.atan2(-self.right.y, math.hypot(self.right.x, self.right.z))

    def climb(self) -> float:
        """機首の上げ角（ラジアン）。"""
        return math.asin(max(-1.0, min(1.0, self.forward.y)))

    def heading(self) -> float:
        """方位（ラジアン。0 が北、右回り）。"""
        return math.atan2(self.forward.x, self.forward.z)

    def tidy(self) -> "Frame":
        """計算誤差で直角と長さがずれるのを直す（毎コマ少しずつ回すので）。"""
        f = self.forward.unit()
        r = self.right - f.scale(self.right.dot(f))
        r = r.unit()
        return Frame(f, f.cross(r).unit(), r)       # 上 = 前 × 右


class Camera(NamedTuple):
    pos: V = V(0.0, 100.0, 0.0)
    frame: Frame = Frame()


def view(p: V, cam: Camera) -> V:
    """世界の点を「カメラから見た点」に。カメラの右・上・前との内積を取るだけ。

    g79・g80 は yaw と pitch の角度で世界を逆に回した。向きを 3 本のベクトルで持てば、
    「その軸にどれだけ沿っているか」＝内積が、そのままカメラ座標になる。式は 3 行。
    """
    q = p - cam.pos
    return V(q.dot(cam.frame.right), q.dot(cam.frame.up), q.dot(cam.frame.forward))


def project(p: V, scale: float = 1.0) -> tuple[float, float]:
    return (CX + FOCUS * p.x / p.z) * scale, (CY - FOCUS * p.y / p.z) * scale


def clip_near(points: list[V]) -> list[V]:
    kept: list[V] = []
    count = len(points)
    for i in range(count):
        a, b = points[i], points[(i + 1) % count]
        a_in, b_in = a.z >= NEAR, b.z >= NEAR
        if a_in:
            kept.append(a)
        if a_in != b_in:
            t = (NEAR - a.z) / (b.z - a.z)
            kept.append(a + (b - a).scale(t))
    return kept


# ── 板（g78〜g80 と同じ） ──────────────────────────────────────────────

class Screen:
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
        """凸多角形を塗る（スキャンライン）。"""
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


# ── 地形（ハイトマップ）と峡谷 ─────────────────────────────────────────

def catmull(p0: V, p1: V, p2: V, p3: V, t: float) -> V:
    """Catmull-Rom 曲線（g79 と同じ）。"""
    a = p1.scale(2)
    b = (p2 - p0).scale(t)
    c = (p0.scale(2) - p1.scale(5) + p2.scale(4) - p3).scale(t * t)
    d = (p0.scale(-1) + p1.scale(3) - p2.scale(3) + p3).scale(t * t * t)
    return (a + b + c + d).scale(0.5)


# 峡谷の道すじの制御点 (x, z)。地図（2560 m 四方）を大きく S 字に横切る
KNOTS = [(200, 300), (500, 700), (400, 1200), (800, 1600), (1300, 1500), (1500, 1000),
         (1900, 800), (2200, 1200), (2100, 1800), (1700, 2200), (1200, 2300)]


def make_path(spacing: float = PATH_STEP) -> list[V]:
    """道すじを spacing m おきの点にする（y は 0。高さはあとで谷底に合わせる）。"""
    knots = [V(x, 0.0, z) for x, z in KNOTS]
    fine = []
    for k in range(len(knots) - 1):
        p0 = knots[max(0, k - 1)]
        p1, p2 = knots[k], knots[k + 1]
        p3 = knots[min(len(knots) - 1, k + 2)]
        for i in range(40):
            fine.append(catmull(p0, p1, p2, p3, i / 40))
    fine.append(knots[-1])
    points, walked = [fine[0]], 0.0                 # 等間隔に置き直す
    for a, b in zip(fine, fine[1:]):
        seg = (b - a).length()
        while walked + seg >= spacing:
            t = (spacing - walked) / seg
            a = a + (b - a).scale(t)
            points.append(a)
            seg -= spacing - walked
            walked = 0.0
        walked += seg
    return points


PATH = make_path()
PATH_LEN = (len(PATH) - 1) * PATH_STEP


def hills(x: float, z: float) -> float:
    """峡谷を掘る前の丘。sin をいくつか重ねた決まった形。100〜260 m。"""
    u, w = x / 500.0, z / 500.0
    return (180 + 40 * math.sin(u * 1.3 + 0.4) * math.cos(w * 1.1 - 0.2)
            + 30 * math.sin(u * 2.9 + w * 1.7) + 18 * math.sin(u * 5.1 - w * 3.3 + 1.0) + 8 * math.sin(u * 9.7 + w * 8.1))


def carve() -> list[list[float]]:
    """丘に峡谷を掘る。道すじに近いマスほど低く：谷底（幅 FLOOR_W）は平ら、そこから WALL_W かけて丘の高さへ戻る。
    谷底の高さは道すじに沿ってゆっくり上下する（進むほど少し上る）。"""
    heights = [[hills(i * CELL, j * CELL) for i in range(GRID + 1)] for j in range(GRID + 1)]
    near: dict[tuple[int, int], tuple[float, float]] = {}   # マス → (道すじまでの距離, 谷底の高さ)
    reach = int((FLOOR_W + WALL_W) / CELL) + 1
    for k, p in enumerate(PATH):
        floor = FLOOR_BASE + 40 * math.sin(k * PATH_STEP / 600.0) + k * PATH_STEP * 0.012
        ci, cj = int(p.x / CELL), int(p.z / CELL)
        for j in range(cj - reach, cj + reach + 1):
            for i in range(ci - reach, ci + reach + 1):
                if 0 <= i <= GRID and 0 <= j <= GRID:
                    d = math.hypot(i * CELL - p.x, j * CELL - p.z)
                    if (i, j) not in near or d < near[(i, j)][0]:
                        near[(i, j)] = (d, floor)
    for (i, j), (d, floor) in near.items():
        t = max(0.0, min(1.0, (d - FLOOR_W) / WALL_W))
        t = t * t * (3 - 2 * t)                       # なめらかに（smoothstep）
        heights[j][i] = floor + (heights[j][i] - floor) * t
    return heights


HEIGHTS = carve()                                   # [z][x]


def ground_at(x: float, z: float) -> float:
    """任意の点の地面の高さ。マスの 4 隅から双一次補間。外は丘のまま。"""
    fx, fz = x / CELL, z / CELL
    if fx < 0 or fz < 0 or fx >= GRID or fz >= GRID:
        return hills(x, z)
    i, j = int(fx), int(fz)
    tx, tz = fx - i, fz - j
    h00, h10 = HEIGHTS[j][i], HEIGHTS[j][i + 1]
    h01, h11 = HEIGHTS[j + 1][i], HEIGHTS[j + 1][i + 1]
    return (h00 * (1 - tx) + h10 * tx) * (1 - tz) + (h01 * (1 - tx) + h11 * tx) * tz


def ground_normal(x: float, z: float) -> V:
    """地面の法線（壁にぶつかったとき跳ね返る向き）。近くの高さの差から。"""
    gx = (ground_at(x + 2, z) - ground_at(x - 2, z)) / 4
    gz = (ground_at(x, z + 2) - ground_at(x, z - 2)) / 4
    return V(-gx, 1.0, -gz).unit()


def land_color(height: float, steep: float, floor: float) -> tuple[int, int, int]:
    """色。谷底は草と川、壁は岩（急なところは暗い岩）、上のほうは森、峰は雪。"""
    if height < floor + 3:
        return WATER if height < floor + 1.0 else SAND
    if steep > 0.6:
        return ROCK_DARK
    if steep > 0.35:
        return ROCK
    if height > 230:
        return SNOW
    if height > floor + 60:
        return FOREST
    return GRASS


def floor_at(k: int) -> float:
    """道すじの点 k の谷底の高さ（carve と同じ式）。"""
    return FLOOR_BASE + 40 * math.sin(k * PATH_STEP / 600.0) + k * PATH_STEP * 0.012


def path_dir(k: int) -> V:
    a, b = PATH[max(0, k - 1)], PATH[min(len(PATH) - 1, k + 1)]
    return V(b.x - a.x, 0.0, b.z - a.z).unit()


def locate(pos: V, hint: int) -> tuple[int, float]:
    """道すじの上でどこか。hint の近くから一番近い点を探し、(点の番号, 道のり) を返す。"""
    lo, hi = max(0, hint - 8), min(len(PATH) - 1, hint + 16)
    k = min(range(lo, hi + 1), key=lambda i: (PATH[i].x - pos.x) ** 2 + (PATH[i].z - pos.z) ** 2)
    along = (pos - PATH[k]).dot(path_dir(k))
    return k, k * PATH_STEP + along


# ── 輪・障害物・木 ─────────────────────────────────────────────────────

@dataclass
class Gate:
    pos: V
    dir: V
    s: float                                        # 道のり
    state: str = "next"                             # next / later / hit / miss

    def basis(self) -> tuple[V, V]:
        side = V(0, 1, 0).cross(self.dir).unit()
        return side, self.dir.cross(side).unit()


@dataclass
class Prop:
    """障害物。kind は pillar（岩柱）か bridge（橋）。"""

    kind: str
    pos: V
    dir: V
    size: float


def make_gates() -> list[Gate]:
    """輪。GATE_GAP おきに、谷底 + 20〜40 m、左右に ±14 m 蛇行。向きは道すじの向き。"""
    gates = []
    k = int(GATE_FIRST / PATH_STEP)
    n = 0
    while k < len(PATH) - 10:
        p = PATH[k]
        d = path_dir(k)
        side = V(d.z, 0.0, -d.x)
        lateral = 14.0 * math.sin(n * 1.9)
        lift = 28 + 12 * math.sin(n * 1.3 + 0.5)
        gates.append(Gate(V(p.x + side.x * lateral, floor_at(k) + lift, p.z + side.z * lateral), d, k * PATH_STEP))
        k += int(GATE_GAP / PATH_STEP)
        n += 1
    gates[0].state = "next"
    for g in gates[1:]:
        g.state = "later"
    return gates


def make_props() -> list[Prop]:
    """岩柱は輪と輪の間に左右どちらかへ、橋は 5 つに 1 つの輪の上に（輪はその下）。"""
    props = []
    n = 0
    k = int((GATE_FIRST + GATE_GAP / 2) / PATH_STEP)
    while k < len(PATH) - 10:
        p = PATH[k]
        d = path_dir(k)
        side = V(d.z, 0.0, -d.x)
        if n % 5 == 2:
            props.append(Prop("bridge", V(p.x, floor_at(k) + 48, p.z), d, FLOOR_W + 30))
        else:
            off = (18.0 if n % 2 else -18.0) * (1 if n % 3 else -1)
            props.append(Prop("pillar", V(p.x + side.x * off, floor_at(k), p.z + side.z * off), d, 55 + 20 * (n % 3)))
        k += int(GATE_GAP / PATH_STEP)
        n += 1
    return props


def make_trees() -> list[tuple[V, float]]:
    """谷の両岸に木。道すじに沿って 25 m おき、左右 40〜70 m。"""
    trees = []
    for k in range(0, len(PATH), int(25 / PATH_STEP)):
        p = PATH[k]
        d = path_dir(k)
        side = V(d.z, 0.0, -d.x)
        for sign in (-1, 1):
            off = sign * (40 + 30 * abs(math.sin(k * 0.7 + sign)))
            x, z = p.x + side.x * off, p.z + side.z * off
            trees.append((V(x, ground_at(x, z), z), 9 + 5 * abs(math.sin(k * 1.3))))
    return trees


GATES_ALL = make_gates()
PROPS = make_props()
TREES = make_trees()
GATES = len(GATES_ALL)


# ── 記録 ────────────────────────────────────────────────────────────────

@dataclass
class Best:
    total: float = 0.0                              # 0 は未記録

    def dump(self) -> str:
        return json.dumps({"total": self.total})

    @classmethod
    def parse(cls, text: str) -> "Best":
        try:
            return cls(float(json.loads(text)["total"]))
        except (ValueError, KeyError, TypeError):
            return cls()

    def take(self, total: float) -> bool:
        if self.total == 0.0 or total < self.total:
            self.total = round(total, 2)
            return True
        return False


# ── 世界 ────────────────────────────────────────────────────────────────

def fresh_gates() -> list[Gate]:
    return [Gate(g.pos, g.dir, g.s, "next" if k == 0 else "later") for k, g in enumerate(GATES_ALL)]


@dataclass
class World:
    seed: int = 0
    pos: V = V(0.0, 0.0, 0.0)
    frame: Frame = Frame()
    speed: float = SPEEDS[1]
    throttle: int = 1
    gates: list[Gate] = field(default_factory=fresh_gates)
    next: int = 0
    hint: int = 0                                   # 道すじの上の位置（探す起点）
    s: float = 0.0                                  # 道のり
    time: float = 0.0
    penalty: float = 0.0                            # 外した輪のぶん（秒）
    clock: float = -COUNTDOWN
    started: bool = False
    counted: int = 4
    roll_in: float = 0.0
    pitch_in: float = 0.0
    hurt: float = 0.0
    bumps: int = 0
    misses: int = 0
    combo: int = 0
    finished_at: float | None = None
    note: str = ""
    note_until: float = -1.0
    cam_pos: V = V(0.0, 0.0, 0.0)
    cam_frame: Frame = Frame()
    prop_spin: float = 0.0

    def __post_init__(self):
        k = 0
        d = path_dir(k)
        self.pos = V(PATH[k].x, floor_at(k) + 30.0, PATH[k].z)
        self.frame = Frame(d, V(0, 1, 0), V(0, 1, 0).cross(d).unit()).tidy()
        self.cam_pos = self.pos - d.scale(CAM_BACK) + V(0, CAM_UP, 0)
        self.cam_frame = self.frame

    def tell(self, text: str, seconds: float = 1.5) -> None:
        self.note = text
        self.note_until = self.clock + seconds

    def total(self) -> float:
        return self.time + self.penalty

    def fly(self, dt: float) -> None:
        """ロール → 傾きで旋回 → 機首 → 速さ → 位置。"""
        bank = self.frame.bank()
        if self.roll_in:
            want = self.roll_in * ROLL_RATE * dt
            want = max(-BANK_LIMIT - bank, min(BANK_LIMIT - bank, want))
            self.frame = self.frame.roll(want)
        else:
            back = max(-LEVEL_RATE * dt, min(LEVEL_RATE * dt, -bank))
            self.frame = self.frame.roll(back)
        bank = self.frame.bank()
        turn = bank * TURN_PER_BANK * dt
        self.frame = Frame(spin(self.frame.forward, V(0, 1, 0), turn), spin(self.frame.up, V(0, 1, 0), turn),
                           spin(self.frame.right, V(0, 1, 0), turn))
        climb = self.frame.climb()
        want = self.pitch_in * PITCH_RATE * dt
        if not self.pitch_in:                        # 手を離すと機首も水平へ
            want = max(-LEVEL_RATE * 0.5 * dt, min(LEVEL_RATE * 0.5 * dt, -climb))
        if climb + want > PITCH_LIMIT or climb + want < -PITCH_LIMIT:
            want = 0.0
        if want:
            self.frame = self.frame.pitch(want)
        self.frame = self.frame.tidy()
        target = SPEEDS[self.throttle]
        self.speed += (target - self.speed) * min(1.0, 0.8 * dt)
        self.speed -= 9.8 * self.frame.forward.y * CLIMB_DRAG * dt
        self.speed = max(30.0, min(130.0, self.speed))
        self.pos = self.pos + self.frame.forward.scale(self.speed * dt)
        self.prop_spin += self.speed * 0.4 * dt

    def collide(self) -> bool:
        """地面や壁にめり込んだら、法線の向きに押し出して、進む向きを跳ね返す。"""
        floor = ground_at(self.pos.x, self.pos.z) + 2.5
        if self.pos.y >= floor:
            return False
        n = ground_normal(self.pos.x, self.pos.z)
        f = self.frame.forward
        bounced = (f - n.scale(2 * f.dot(n))).scale(0.6) + n.scale(0.4)   # 反射して、少し法線の向きへ
        self.frame = Frame(bounced.unit(), V(0, 1, 0), V(0, 1, 0).cross(bounced).unit()).tidy()
        self.pos = V(self.pos.x, floor, self.pos.z) + n.scale(3.0)
        self.speed *= 0.5
        self.hurt = 0.8
        self.bumps += 1
        self.combo = 0
        return True

    def update(self, dt: float) -> str | None:
        if not self.started:
            self.follow(dt)
            return None
        happened = None
        self.clock += dt
        if self.clock < 0:
            self.follow(dt)
            due = int(-self.clock) + 1
            if due < self.counted:
                self.counted = due
                return "count"
            return None
        if self.time == 0.0:
            happened = "go"
            self.tell("GO!", 1.0)
        if self.finished_at is not None:
            self.fly(dt)
            self.collide()
            self.follow(dt)
            return None
        self.time += dt
        self.hurt = max(0.0, self.hurt - dt)
        before = self.pos
        self.fly(dt)
        if self.collide():
            self.tell("ぶつかった！", 1.0)
            happened = "bump"
        self.hint, self.s = locate(self.pos, self.hint)
        gate = self.gates[self.next]
        side_before = (before - gate.pos).dot(gate.dir)
        side_now = (self.pos - gate.pos).dot(gate.dir)
        if side_before < 0 <= side_now:              # 輪の面をまたいだ
            t = side_before / (side_before - side_now)
            at = before + (self.pos - before).scale(t)
            self.settle(gate, (at - gate.pos).length() <= GATE_R)
            happened = happened or ("gate" if gate.state == "hit" else "miss")
        elif self.s > gate.s + 60:                  # 面をまたがずに通り過ぎた（横や上を回った）
            self.settle(gate, False)
            happened = happened or "miss"
        if self.next >= GATES and self.finished_at is None:
            self.finished_at = self.total()
            self.tell(f"ゴール！ {clock_text(self.finished_at)}", 5.0)
            happened = "finish"
        self.follow(dt)
        return happened

    def settle(self, gate: Gate, hit: bool) -> None:
        """輪の結果。外したら罰の秒数を足して、戻らず次へ。"""
        if hit:
            gate.state = "hit"
            self.combo += 1
            self.tell(f"輪 {self.next + 1}/{GATES}" + (f"  {self.combo} 連続" if self.combo > 1 else ""))
        else:
            gate.state = "miss"
            self.misses += 1
            self.combo = 0
            self.penalty += MISS_PENALTY
            self.tell(f"外した… +{MISS_PENALTY:.0f} 秒", 1.5)
        self.next += 1
        if self.next < GATES:
            self.gates[self.next].state = "next"

    def follow(self, dt: float) -> None:
        """カメラは自機の後ろ・少し上。位置はなめらかに追い、向きは自機を見て、傾きは自機の半分だけ付き合う。"""
        want = self.pos - V(self.frame.forward.x, 0.0, self.frame.forward.z).unit().scale(CAM_BACK) + V(0, CAM_UP, 0)
        ease = min(1.0, 8 * dt)
        self.cam_pos = self.cam_pos + (want - self.cam_pos).scale(ease)
        look = (self.pos + self.frame.forward.scale(12.0) - self.cam_pos).unit()
        up_hint = spin(V(0, 1, 0), look, -self.frame.bank() * 0.25)
        right = up_hint.cross(look).unit()
        self.cam_frame = Frame(look, look.cross(right).unit(), right)

    def camera(self) -> Camera:
        return Camera(self.cam_pos, self.cam_frame)

    def altitude(self) -> float:
        return self.pos.y - ground_at(self.pos.x, self.pos.z)


def clock_text(seconds: float) -> str:
    return f"{int(seconds // 60)}:{seconds % 60:05.2f}"


# ── 描く ────────────────────────────────────────────────────────────────

def fog(color: tuple[int, int, int], z: float) -> tuple[int, int, int]:
    amount = max(0.0, min(0.92, (z - FOG_FROM) / (FAR - FOG_FROM)))
    return tuple(int(c + (b - c) * amount) for c, b in zip(color, HAZE))


def shade(base: tuple[int, int, int], normal: V, z: float) -> tuple[int, int, int]:
    light = V(*LIGHT_DIR).unit()
    bright = 0.45 + 0.55 * max(0.0, normal.dot(light))
    return fog(tuple(min(255, int(c * bright)) for c in base), z)


def draw_solid(screen: Screen, points: list[V], faces: list[tuple[int, ...]], color: tuple[int, int, int],
               colors: list[tuple[int, int, int]] | None = None) -> None:
    """立体をひとつ（g79 と同じ）。"""
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
    if max(p.z for p in quad) < NEAR:
        return
    poly = clip_near(quad) if min(p.z for p in quad) < NEAR else quad
    if len(poly) >= 3:
        screen.fill([project(p, scale) for p in poly], color)


def outward(points: list[V], faces: list[tuple[int, ...]]) -> list[tuple[int, ...]]:
    center = V(sum(p.x for p in points), sum(p.y for p in points), sum(p.z for p in points)).scale(1 / len(points))
    fixed = []
    for face in faces:
        a, b, c = points[face[0]], points[face[1]], points[face[2]]
        normal = (b - a).cross(c - a)
        fixed.append(face if normal.dot(a - center) >= 0 else tuple(reversed(face)))
    return fixed


def box(w: float, h: float, length: float, at: V = V(0, 0, 0)) -> tuple[list[V], list[tuple[int, ...]]]:
    points = [at + V(x * w / 2, y * h / 2, z * length / 2) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]
    faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    return points, outward(points, faces)


# 自機（機体座標：x 右、y 上、z 前）。胴・主翼・尾翼・垂直尾翼・エンジン
PLANE_PARTS = [
    (box(1.1, 1.0, 6.0, V(0, 0, 0)), BODY_COLOR),
    (box(9.0, 0.16, 1.5, V(0, 0.1, 0.4)), WING_COLOR),
    (box(3.2, 0.12, 0.9, V(0, 0.2, -2.7)), WING_COLOR),
    (box(0.12, 1.3, 1.1, V(0, 0.9, -2.6)), TAIL_COLOR),
    (box(0.9, 0.8, 1.0, V(0, 0.0, 3.2)), NOSE_COLOR),
]


def draw_plane(screen: Screen, world: World, cam: Camera) -> None:
    """自機。部品ごとに機体の向きへ回して置く（前・上・右の 3 本で座標を組み立てる）。プロペラは回る円盤。"""
    f, u, r = world.frame
    place = lambda p: view(world.pos + r.scale(p.x) + u.scale(p.y) + f.scale(p.z), cam)   # noqa: E731
    parts = sorted(PLANE_PARTS, key=lambda part: -view(world.pos + f.scale(part[0][0][0].z), cam).z)
    for (points, faces), color in parts:
        draw_solid(screen, [place(p) for p in points], faces, color)
    scale = screen.width / WIDTH
    blades = []
    for k in range(3):
        a = world.prop_spin + k * math.tau / 3
        blades.append([place(V(0, 0, 3.75)), place(V(math.cos(a) * 1.6, math.sin(a) * 1.6, 3.75)),
                       place(V(math.cos(a + 0.35) * 1.5, math.sin(a + 0.35) * 1.5, 3.75))])
    for tri in blades:
        if min(p.z for p in tri) > NEAR:
            screen.fill([project(p, scale) for p in tri], fog(PROP_COLOR, tri[0].z))
    shadow = [world.pos + r.scale(4.5 * math.cos(a)) + f.scale(3.0 * math.sin(a)) for a in (i * math.tau / 8 for i in range(8))]
    ground = [view(V(p.x, ground_at(p.x, p.z) + 0.3, p.z), cam) for p in shadow]
    if world.altitude() < 60 and max(p.z for p in ground) > NEAR:
        draw_quad(screen, ground, fog(SHADOW_COLOR, ground[0].z), scale)


def draw_sky(screen: Screen, cam: Camera) -> None:
    """空と地平線（傾く）。"""
    scale = screen.width / WIDTH
    f = cam.frame.forward
    flat = V(f.x, 0.0, f.z).unit() if math.hypot(f.x, f.z) > 1e-6 else V(cam.frame.up.x, 0.0, cam.frame.up.z).unit()
    side = V(flat.z, 0.0, -flat.x)
    ends = []
    for k in (-1, 1):
        d = (flat + side.scale(k * 0.9)).unit()
        q = V(d.dot(cam.frame.right), d.dot(cam.frame.up), d.dot(cam.frame.forward))
        if q.z < 0.05:
            screen.clear(SKY_TOP if f.y > 0 else FOREST)
            return
        ends.append(project(q, scale))
    (x1, y1), (x2, y2) = ends
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / length, dx / length
    u = cam.frame.up
    q = V(u.dot(cam.frame.right), u.dot(cam.frame.up), u.dot(cam.frame.forward))
    if nx * q.x - ny * q.y < 0:
        nx, ny = -nx, -ny
    big = 4000 * scale
    ax, ay = x1 - dx * 20, y1 - dy * 20
    bx, by = x2 + dx * 20, y2 + dy * 20
    screen.clear(HAZE)
    screen.fill([(ax, ay), (bx, by), (bx + nx * big, by + ny * big), (ax + nx * big, ay + ny * big)], SKY_TOP)
    for depth, color in ((14 * scale, SKY), (5 * scale, HAZE)):
        screen.fill([(ax, ay), (bx, by), (bx + nx * depth, by + ny * depth), (ax + nx * depth, ay + ny * depth)], color)
    sun = V(*LIGHT_DIR).unit()
    q = V(sun.dot(cam.frame.right), sun.dot(cam.frame.up), sun.dot(cam.frame.forward))
    if q.z > 0.2:
        sx, sy = project(q, scale)
        r = 5.0 * scale
        screen.fill([(sx + r * math.cos(a), sy + r * math.sin(a)) for a in (i * math.tau / 12 for i in range(12))], SUN)


CLOUDS = [(V(300 + 600 * i, 520 + 60 * math.sin(i * 2.3), 300 + 500 * ((i * 7) % 5)), 80 + 40 * math.sin(i * 1.7)) for i in range(9)]


def draw_clouds(screen: Screen, cam: Camera) -> None:
    scale = screen.width / WIDTH
    for pos, size in CLOUDS:
        q = view(pos, cam)
        if q.z < NEAR + 50:
            continue
        cx, cy = project(q, scale)
        rx, ry = FOCUS * size / q.z * scale, FOCUS * size * 0.28 / q.z * scale
        if rx < 1:
            continue
        screen.fill([(cx + rx * math.cos(a), cy + ry * math.sin(a)) for a in (i * math.tau / 12 for i in range(12))], fog(CLOUD, q.z))


def draw_terrain(screen: Screen, cam: Camera, floor: float) -> None:
    """地形。近くは 1 マス、中くらいは 2 × 2、遠くは 4 × 4 をまとめて、奥から。"""
    scale = screen.width / WIDTH
    ci, cj = int(cam.pos.x / CELL), int(cam.pos.z / CELL)
    quads = []

    def add(i: int, j: int, step: int) -> None:
        if i < 0 or j < 0 or i + step > GRID or j + step > GRID:
            return
        corners = [V(i * CELL, HEIGHTS[j][i], j * CELL), V((i + step) * CELL, HEIGHTS[j][i + step], j * CELL),
                   V((i + step) * CELL, HEIGHTS[j + step][i + step], (j + step) * CELL), V(i * CELL, HEIGHTS[j + step][i], (j + step) * CELL)]
        mid = V(sum(c.x for c in corners) / 4, sum(c.y for c in corners) / 4, sum(c.z for c in corners) / 4)
        q = view(mid, cam)
        reach = CELL * step * 1.2
        if q.z < -reach or q.z > FAR or abs(q.x) > q.z * 1.1 + reach or abs(q.y) > q.z * 0.8 + reach:
            return
        normal = (corners[2] - corners[0]).cross(corners[3] - corners[1]).unit()
        if normal.y < 0:
            normal = normal.scale(-1)
        quads.append((q.z, corners, shade(land_color(mid.y, 1 - normal.y, floor), normal, q.z)))

    for j in range(cj - FAR_CELLS, cj + FAR_CELLS + 1):
        for i in range(ci - FAR_CELLS, ci + FAR_CELLS + 1):
            di, dj = abs(i - ci), abs(j - cj)
            if di <= NEAR_CELLS and dj <= NEAR_CELLS:
                add(i, j, 1)
            elif di <= MID_CELLS and dj <= MID_CELLS:
                if i % 2 == 0 and j % 2 == 0:
                    add(i, j, 2)
            elif i % 4 == 0 and j % 4 == 0:
                add(i, j, 4)
    for _, corners, color in sorted(quads, key=lambda t: -t[0]):
        placed = [view(c, cam) for c in corners]
        if max(p.z for p in placed) < NEAR:
            continue
        poly = clip_near(placed) if min(p.z for p in placed) < NEAR else placed
        if len(poly) >= 3:
            screen.fill([project(p, scale) for p in poly], color)


def draw_gate(screen: Screen, gate: Gate, cam: Camera) -> None:
    """輪。16 角形の外と内の間を塗る。次は橙、あとは灰、くぐった輪は緑、外した輪は赤。"""
    scale = screen.width / WIDTH
    color = {"next": RING_NEXT, "later": RING_LATER, "hit": RING_DONE, "miss": RING_MISS}[gate.state]
    side, up = gate.basis()
    outer, inner = [], []
    for k in range(12):
        a = k * math.tau / 12
        outer.append(view(gate.pos + side.scale(GATE_R * math.cos(a)) + up.scale(GATE_R * math.sin(a)), cam))
        inner.append(view(gate.pos + side.scale(GATE_R * 0.82 * math.cos(a)) + up.scale(GATE_R * 0.82 * math.sin(a)), cam))
    paint = fog(color, view(gate.pos, cam).z)
    for k in range(12):
        draw_quad(screen, [outer[k], outer[(k + 1) % 12], inner[(k + 1) % 12], inner[k]], paint, scale)
    foot = view(V(gate.pos.x, ground_at(gate.pos.x, gate.pos.z), gate.pos.z), cam)   # 柱
    low = view(gate.pos - V(0, GATE_R, 0), cam)
    if foot.z > 25 and low.z > 25:                  # 近すぎる柱は描かない（画面いっぱいの線になる）
        w = 0.5
        draw_quad(screen, [V(foot.x - w, foot.y, foot.z), V(foot.x + w, foot.y, foot.z), V(low.x + w, low.y, low.z), V(low.x - w, low.y, low.z)], fog(POLE, foot.z), scale)


def draw_prop(screen: Screen, prop: Prop, cam: Camera) -> None:
    if prop.kind == "pillar":
        points, faces = box(9.0, prop.size, 9.0, prop.pos + V(0, prop.size / 2, 0))
        draw_solid(screen, [view(p, cam) for p in points], faces, PILLAR)
    else:                                            # 橋：谷を渡る梁と、両端の柱
        side = V(prop.dir.z, 0.0, -prop.dir.x)
        f, u, r = prop.dir, V(0, 1, 0), side
        half = prop.size / 2
        points = [prop.pos + r.scale(x * half) + u.scale(y * 2.0) + f.scale(z * 3.0) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]
        faces = outward(points, [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)])
        draw_solid(screen, [view(p, cam) for p in points], faces, BRIDGE)
        for sign in (-1, 1):
            foot = prop.pos + r.scale(sign * half)
            g = ground_at(foot.x, foot.z)
            column, cf = box(4.0, max(4.0, prop.pos.y - g), 4.0, V(foot.x, (prop.pos.y + g) / 2, foot.z))
            draw_solid(screen, [view(p, cam) for p in column], cf, PILLAR)


def draw_tree(screen: Screen, base: V, size: float, scale: float) -> None:
    z = base.z
    if z < NEAR + 2:
        return
    trunk = [V(base.x - 0.5, base.y, z), V(base.x + 0.5, base.y, z), V(base.x + 0.5, base.y + size * 0.3, z), V(base.x - 0.5, base.y + size * 0.3, z)]
    screen.fill([project(p, scale) for p in trunk], fog(TRUNK, z))
    for w, y0, y1, tone_ in ((0.42, 0.2, 0.6, 0.7), (0.32, 0.45, 0.85, 0.85), (0.2, 0.7, 1.05, 1.0)):
        tri = [V(base.x - w * size, base.y + y0 * size, z), V(base.x + w * size, base.y + y0 * size, z), V(base.x, base.y + y1 * size, z)]
        screen.fill([project(p, scale) for p in tri], fog(tuple(int(c * tone_) for c in CROWN), z))


def draw_marker(screen: Screen, world: World, cam: Camera) -> None:
    """次の輪の印。画面の中なら菱形、外なら縁に矢印。"""
    if world.next >= GATES:
        return
    scale = screen.width / WIDTH
    gate = world.gates[world.next]
    q = view(gate.pos, cam)
    w, h = screen.width, screen.height
    if q.z > NEAR:
        x, y = project(q, scale)
        if 0 <= x < w and 0 <= y < h:
            r = max(3.0, FOCUS * GATE_R * 1.4 / q.z * scale)
            for a, b in (((x - r, y), (x, y - r)), ((x, y - r), (x + r, y)), ((x + r, y), (x, y + r)), ((x, y + r), (x - r, y))):
                screen.line(a, b, MARK)
            return
    ax, ay = (q.x, q.y) if q.z > NEAR else (-q.x, -q.y)
    length = math.hypot(ax, ay) or 1.0
    ux, uy = ax / length, -ay / length
    cx, cy = w / 2, h / 2
    tip = (cx + ux * (w / 2 - 6 * scale), cy + uy * (h / 2 - 6 * scale))
    back = (tip[0] - ux * 7 * scale, tip[1] - uy * 7 * scale)
    px, py = -uy, ux
    screen.fill([tip, (back[0] + px * 4 * scale, back[1] + py * 4 * scale), (back[0] - px * 4 * scale, back[1] - py * 4 * scale)], MARK)


def draw_hud(screen: Screen, world: World) -> None:
    """板の中の表示：速さの棒（左下）、高度の棒（右下）、ぶつかった直後の赤い縁。文字は HTML と端末の行に任せる。"""
    scale = screen.width / WIDTH
    w, h = screen.width, screen.height
    for x0, value, top_value in ((4 * scale, world.speed, 130.0), (w - 7 * scale, world.altitude(), 150.0)):
        bar_h, y1 = 24 * scale, h - 4 * scale
        screen.fill([(x0, y1 - bar_h), (x0 + 3 * scale, y1 - bar_h), (x0 + 3 * scale, y1), (x0, y1)], GAUGE_BG)
        fill_h = bar_h * max(0.0, min(1.0, value / top_value))
        screen.fill([(x0, y1 - fill_h), (x0 + 3 * scale, y1 - fill_h), (x0 + 3 * scale, y1), (x0, y1)], GAUGE)
    if world.hurt > 0:
        thick = int(3 * scale)
        screen.fill([(0, 0), (w, 0), (w, thick), (0, thick)], BUMP_RED)
        screen.fill([(0, h - thick), (w, h - thick), (w, h), (0, h)], BUMP_RED)
        screen.fill([(0, 0), (thick, 0), (thick, h), (0, h)], BUMP_RED)
        screen.fill([(w - thick, 0), (w, 0), (w, h), (w - thick, h)], BUMP_RED)


def draw(screen: Screen, world: World) -> None:
    """空 → 雲 → 地形 → 木・輪・障害物（奥から）→ 自機 → 印と HUD。"""
    cam = world.camera()
    scale = screen.width / WIDTH
    draw_sky(screen, cam)
    draw_clouds(screen, cam)
    draw_terrain(screen, cam, floor_at(world.hint))
    things = []
    for base, size in TREES:
        q = view(base, cam)
        if NEAR < q.z < 450 and abs(q.x) < q.z * 1.3 + 30:
            things.append((q.z, "tree", (q, size)))
    for k, gate in enumerate(world.gates):
        q = view(gate.pos, cam)
        if -GATE_R < q.z < 750 and abs(q.x) < q.z * 1.3 + GATE_R * 2:
            things.append((q.z, "gate", gate))
    for prop in PROPS:
        q = view(prop.pos, cam)
        if -60 < q.z < 900 and abs(q.x) < q.z * 1.3 + 80:
            things.append((q.z, "prop", prop))
    for z, kind, thing in sorted(things, key=lambda t: -t[0]):
        if kind == "tree":
            draw_tree(screen, thing[0], thing[1], scale)
        elif kind == "gate":
            draw_gate(screen, thing, cam)
        else:
            draw_prop(screen, thing, cam)
    draw_plane(screen, world, cam)
    if world.finished_at is None:
        draw_marker(screen, world, cam)
    draw_hud(screen, world)


# ── 入力 ────────────────────────────────────────────────────────────────

def obey(world: World, key: str, down: bool = True) -> None:
    v = 1.0 if down else 0.0
    if key == "left":
        world.roll_in = -v if down else (0.0 if world.roll_in < 0 else world.roll_in)
    elif key == "right":
        world.roll_in = v if down else (0.0 if world.roll_in > 0 else world.roll_in)
    elif key == "up":
        world.pitch_in = v if down else (0.0 if world.pitch_in > 0 else world.pitch_in)
    elif key == "down":
        world.pitch_in = -v if down else (0.0 if world.pitch_in < 0 else world.pitch_in)
    elif key == "faster" and down:
        world.throttle = min(2, world.throttle + 1)
    elif key == "slower" and down:
        world.throttle = max(0, world.throttle - 1)
    elif key == "go" and down and not world.started:
        world.started = True


# ── 端末 ────────────────────────────────────────────────────────────────

def read_keys(fd: int) -> list[str]:
    keys = []
    while select.select([fd], [], [], 0)[0]:
        text = os.read(fd, 64).decode(errors="ignore")
        for token, name in (("\x1b[D", "left"), ("\x1b[C", "right"), ("\x1b[A", "up"), ("\x1b[B", "down"),
                            ("a", "left"), ("d", "right"), ("w", "faster"), ("s", "slower"),
                            ("q", "quit"), ("\x1b", "quit"), ("r", "reset"), (" ", "go"), ("\r", "go"), ("\n", "go")):
            keys.extend([name] * text.count(token))
        if "\x1b[" in text:
            keys = [k for k in keys if k != "quit"] if text.count("\x1b") == text.count("\x1b[") else keys
    return keys


class Speaker:
    def __init__(self):
        import shutil
        import tempfile

        self.player = shutil.which("afplay") or shutil.which("aplay")
        self.folder = tempfile.mkdtemp(prefix="flight-")
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


def status(world: World, best: Best, improved: bool = False) -> str:
    """画面の下の 1 行。128 桁に収める。"""
    note = world.note if world.clock < world.note_until else ""
    if not world.started:
        note, tail = "スペースで始める", "q でやめる"
    elif world.clock < 0:
        note, tail = f"{int(-world.clock) + 1}…", ""
    elif world.finished_at is not None:
        note = f"★ ゴール {clock_text(world.finished_at)}" + (" ベスト更新！" if improved else "") + " r でもう一度"
        tail = ""
    else:
        tail = f"ベスト {clock_text(best.total) if best.total else '--:--.--'}  q でやめる"
    return (f" {clock_text(world.total())}  輪 {world.next:2d}/{GATES}  外し {world.misses:2d}  連続 {world.combo:2d}  "
            f"速さ {world.speed:3.0f}  高度 {world.altitude():3.0f}  {note:<20} " + tail)


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
    held: dict[str, float] = {}
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
                if key == "reset" and world.finished_at is not None:
                    world = World(seed=int(time.time()))
                    world.started = True
                    improved = False
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
                    improved = best.take(world.finished_at)
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
    """自動操縦。次の輪の中心を、機体から見た「右・上」のずれで追う。右にずれていれば右へ傾け、上なら機首を上げる。"""
    if world.finished_at is not None:
        return
    ring = world.rings[world.next]
    d = ring.pos - world.pos
    flat = math.hypot(d.x, d.z) or 1.0
    turn = math.remainder(math.atan2(d.x, d.z) - world.frame.heading(), math.tau)   # 目標の方位との差（右が正）
    want_bank = max(-0.9, min(0.9, turn * 2.0))
    world.roll_in = 1.0 if want_bank > world.frame.bank() + 0.04 else (-1.0 if want_bank < world.frame.bank() - 0.04 else 0.0)
    want_climb = math.atan2(d.y, flat)                                          # 目標への上げ角
    err = want_climb - world.frame.climb()
    world.pitch_in = 1.0 if err > 0.02 else (-1.0 if err < -0.02 else 0.0)
    world.throttle = 1


def autopilot(world: World) -> None:
    """自動操縦。次の輪（近ければ）か、道すじの少し先を狙う。"""
    if world.finished_at is not None:
        return
    gate = world.gates[world.next] if world.next < GATES else None
    k = min(len(PATH) - 1, world.hint + int(90 / PATH_STEP))
    target = V(PATH[k].x, floor_at(k) + 30.0, PATH[k].z)
    if gate is not None and (gate.pos - world.pos).length() < 220:
        target = gate.pos
    d = target - world.pos
    flat = math.hypot(d.x, d.z) or 1.0
    turn = math.remainder(math.atan2(d.x, d.z) - world.frame.heading(), math.tau)
    want_bank = max(-1.0, min(1.0, turn * 2.5))
    world.roll_in = 1.0 if want_bank > world.frame.bank() + 0.04 else (-1.0 if want_bank < world.frame.bank() - 0.04 else 0.0)
    want_climb = math.atan2(d.y, flat)
    err = want_climb - world.frame.climb()
    world.pitch_in = 1.0 if err > 0.02 else (-1.0 if err < -0.02 else 0.0)
    world.throttle = 1


def check() -> None:
    print("● 3 軸の回転")
    f = Frame()
    r = f.roll(math.radians(30))
    assert abs(math.degrees(r.bank()) - 30) < 1e-6 and r.forward == f.forward, "ロールは前を変えず、傾きが 30° に"
    p = f.pitch(math.radians(20))
    assert abs(math.degrees(p.climb()) - 20) < 1e-6 and abs(p.right.dot(f.right) - 1) < 1e-9, "ピッチは右を変えず、機首が 20° 上"
    y = f.yaw(math.radians(90))
    assert abs(y.forward.x - 1) < 1e-9 and abs(y.forward.z) < 1e-9, "ヨー 90° で東を向く"
    mixed = f.roll(0.4).pitch(0.3).yaw(1.1).tidy()
    for a, b in ((mixed.forward, mixed.up), (mixed.up, mixed.right), (mixed.right, mixed.forward)):
        assert abs(a.dot(b)) < 1e-9 and abs(a.length() - 1) < 1e-9, "3 本は直角で長さ 1 のまま"
    assert abs(spin(V(1, 0, 0), V(0, 1, 0), math.pi / 2).z + 1) < 1e-9, "x 軸の点を y 軸まわりに 90° → −z（g78 の rotate と同じ）"
    print("  ロール・ピッチ・ヨーはそれぞれ 1 本を固定して 2 本を回す。混ぜても 3 本は直角で長さ 1")
    print("● 基底で見るカメラ")
    cam = Camera(V(0, 0, 0), Frame().yaw(math.pi / 2))
    q = view(V(10, 0, 0), cam)
    assert abs(q.z - 10) < 1e-9 and abs(q.x) < 1e-9, q
    q = view(V(0, 0, 10), cam)
    assert abs(q.x + 10) < 1e-9, q
    cam = Camera(V(0, 0, 0), Frame().roll(math.pi / 2))
    q = view(V(0, 10, 0), cam)
    assert abs(q.x + 10) < 1e-6 and abs(q.y) < 1e-6, q
    print("  東を向けば +x が正面で +z は左。右へ 90° 傾けば、世界の上が左に見える")
    print("● 峡谷")
    assert len(PATH) > 400 and abs(PATH_LEN - (len(PATH) - 1) * PATH_STEP) < 1e-9
    gaps = [(b - a).length() for a, b in zip(PATH, PATH[1:])]
    assert max(gaps) - min(gaps) < 0.5, "道すじの点は等間隔"
    deeper = 0
    for k in range(0, len(PATH), 20):
        p = PATH[k]
        d = path_dir(k)
        side = V(d.z, 0.0, -d.x)
        mid = ground_at(p.x, p.z)
        wall = max(ground_at(p.x + side.x * 150, p.z + side.z * 150), ground_at(p.x - side.x * 150, p.z - side.z * 150))
        if wall - mid > 40:
            deeper += 1
        assert abs(mid - floor_at(k)) < 8, (k, mid, floor_at(k))
    assert deeper > len(range(0, len(PATH), 20)) * 0.8, deeper
    n = ground_normal(PATH[0].x, PATH[0].z)
    assert n.y > 0.9, "谷底の法線はほぼ上向き"
    print(f"  道すじ {PATH_LEN:.0f} m（{len(PATH)} 点）。谷底は式どおりの高さで、両岸は 150 m 先で 40 m 以上高い（{deeper} / {len(range(0, len(PATH), 20))} 箇所）")
    print("● 輪と障害物")
    assert GATES >= 20
    for k, gate in enumerate(GATES_ALL):
        clearance = gate.pos.y - ground_at(gate.pos.x, gate.pos.z)
        assert 10 <= clearance <= 60, (k, clearance)
        assert abs(gate.dir.length() - 1) < 1e-9
    bridges = [p for p in PROPS if p.kind == "bridge"]
    pillars = [p for p in PROPS if p.kind == "pillar"]
    assert bridges and pillars
    for b in bridges:
        assert b.pos.y - ground_at(b.pos.x, b.pos.z) > 30
    print(f"  輪 {GATES} 個を {GATE_GAP:.0f} m おき、谷底から 10〜60 m。岩柱 {len(pillars)} 本、橋 {len(bridges)} 本、木 {len(TREES)} 本")
    print("● 飛行機の動き")
    world = World(seed=1)
    world.started = True
    world.clock = 0.0
    world.time = 0.001
    world.pos = V(1280.0, 600.0, 1280.0)             # 高いところで（壁に当たらないように）
    head0 = world.frame.heading()
    world.roll_in = 1.0
    for _ in range(30):
        world.update(STEP)
    bank = world.frame.bank()
    assert 0.3 < bank <= BANK_LIMIT + 1e-9, bank
    world.roll_in = 0.0
    for _ in range(30):
        world.update(STEP)
    turned = math.remainder(world.frame.heading() - head0, math.tau)
    assert turned > 0.3, "右へ傾けば右へ曲がる"
    for _ in range(60):
        world.update(STEP)
    assert abs(world.frame.bank()) < 0.05, "手を離せば 2 秒で水平"
    print(f"  右ロール 1 秒で傾き {math.degrees(bank):.0f}°、2 秒で方位 {math.degrees(turned):.0f}° 変わる。離すと水平に戻る")
    print("● 壁に跳ね返る")
    world = World(seed=1)
    world.started = True
    world.clock = 0.0
    world.time = 0.001
    world.frame = world.frame.yaw(math.pi / 2)      # 道すじの右の壁へ真横に
    for _ in range(30 * 20):
        got = world.update(STEP)
        if got == "bump":
            break
    assert world.bumps == 1 and world.altitude() >= 2.4, (world.bumps, world.altitude())
    away = world.frame.forward.dot(ground_normal(world.pos.x, world.pos.z))
    assert away > 0, "跳ね返ったあとは壁から離れる向き"
    print(f"  {world.time:.1f} 秒で壁。法線の向きに押し出され、進む向きが反射する。速さは半分")
    print("● 輪の判定")
    world = World(seed=1)
    world.started = True
    world.clock = 0.0
    world.time = 0.001
    gate = world.gates[0]
    world.pos = gate.pos - gate.dir.scale(5.0) + V(0, GATE_R * 0.5, 0)
    world.frame = Frame(gate.dir, V(0, 1, 0), V(0, 1, 0).cross(gate.dir).unit()).tidy()
    world.hint, world.s = locate(world.pos, 0)
    got = [world.update(STEP) for _ in range(8)]
    assert "gate" in got and world.next == 1 and gate.state == "hit" and world.combo == 1, got
    gate2 = world.gates[1]
    world.pos = gate2.pos - gate2.dir.scale(5.0) + V(0, GATE_R * 1.3, 0)
    world.frame = Frame(gate2.dir, V(0, 1, 0), V(0, 1, 0).cross(gate2.dir).unit()).tidy()
    world.hint, world.s = locate(world.pos, world.hint)
    got = [world.update(STEP) for _ in range(8)]
    assert "miss" in got and world.next == 2 and gate2.state == "miss" and world.penalty == MISS_PENALTY and world.combo == 0, got
    print(f"  中なら「くぐった」で連続が伸び、外したら +{MISS_PENALTY:.0f} 秒で次へ（戻らない）")
    print("● 自動操縦で 1 本")
    world = World(seed=2)
    world.started = True
    events = []
    for _ in range(30 * 600):
        autopilot(world)
        got = world.update(STEP)
        if got:
            events.append(got)
        if world.finished_at is not None:
            break
    assert world.finished_at is not None, (world.next, world.time)
    states = [g.state for g in world.gates]
    assert world.next == GATES and events.count("finish") == 1 and all(st in ("hit", "miss") for st in states)
    assert states.count("hit") >= GATES * 0.6 and states.count("miss") == world.misses, states
    print(f"  {clock_text(world.finished_at)}（走行 {clock_text(world.time)} + 罰 {world.penalty:.0f} 秒）。くぐった {GATES - world.misses}、外した {world.misses}、ぶつかった {world.bumps}")
    print("● 板の大きさ")
    world = World(seed=2)
    world.started = True
    for _ in range(30 * 15):
        autopilot(world)
        world.update(STEP)
    small, big = Screen(), Screen(WIDTH * 4, HEIGHT * 4)
    started = time.perf_counter()
    draw(small, world)
    took_small = time.perf_counter() - started
    started = time.perf_counter()
    draw(big, world)
    took_big = time.perf_counter() - started
    same = sum(1 for y in range(HEIGHT) for x in range(WIDTH) if small.pixel(x, y) == big.pixel(x * 4, y * 4))
    print(f"  128×80 を描くのに {took_small * 1000:.1f} ms、512×320 は {took_big * 1000:.1f} ms。一致 {same / (WIDTH * HEIGHT):.0%}")
    assert same / (WIDTH * HEIGHT) > 0.85
    print("● 記録と音")
    best = Best.parse("")
    assert best.take(100.0) and not best.take(120.0) and best.take(90.0) and best == Best(90.0)
    assert Best.parse(best.dump()) == best and Best.parse("{x") == Best()
    assert len({sound_bytes(k) for k in SOUNDS}) == len(SOUNDS) and all(k in SOUNDS for k in EVENTS)
    print(f"  短いタイムだけ更新。音は {len(SOUNDS)} つ全部別")
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


def shot(path: str, seconds: float = 8.0) -> None:
    world = World(seed=3)
    world.started = True
    world.clock = 0.0
    for _ in range(int(seconds / STEP)):
        autopilot(world)
        world.update(STEP)
    screen = Screen(WIDTH * 4, HEIGHT * 4)
    draw(screen, world)
    with open(path, "wb") as out:
        out.write(png_bytes(screen, 1))
    print(f"{path} に書き出した（{seconds} 秒後、輪 {world.next}、高度 {world.altitude():.0f} m）")


def terrain_map(path: str) -> None:
    """地形を真上から。高さの色と、道すじ、輪。"""
    size = 256
    screen = Screen(size, size)
    lo = min(min(row) for row in HEIGHTS)
    for y in range(size):
        for x in range(size):
            h = ground_at(x / size * GRID * CELL, (size - 1 - y) / size * GRID * CELL)
            t = (h - lo) / 260
            screen.plot(x, y, (int(40 + 180 * t), int(90 + 120 * t), int(40 + 60 * t)))
    for k, gate in enumerate(GATES_ALL):
        px, py = int(gate.pos.x / (GRID * CELL) * size), int(size - 1 - gate.pos.z / (GRID * CELL) * size)
        for dx in range(-1, 2):
            for dy in range(-1, 2):
                screen.plot(px + dx, py + dy, RING_NEXT if k == 0 else (255, 255, 255))
    with open(path, "wb") as out:
        out.write(png_bytes(screen, 2))
    print(f"{path} に書き出した（道すじ {PATH_LEN:.0f} m、輪 {GATES} 個）")


def main() -> None:
    if "--check" in sys.argv:
        check()
    elif "--shot" in sys.argv:
        shot(sys.argv[sys.argv.index("--shot") + 1] if len(sys.argv) > 2 else "shot.png")
    elif "--map" in sys.argv:
        terrain_map(sys.argv[sys.argv.index("--map") + 1] if len(sys.argv) > 2 else "map.png")
    else:
        run()


if __name__ == "__main__":
    main()
