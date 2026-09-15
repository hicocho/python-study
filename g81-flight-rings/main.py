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
FOCUS = 70.0                                        # 焦点距離（視野 85°。広く見えるように）
NEAR = 1.0
FAR = 1700.0                                        # 地形を描く距離
FOG_FROM = 600.0
STEP = 1 / 30

CELL = 80.0                                         # 地形のマスの一辺（m）
GRID = 32                                           # マスの数（32 × 32 = 2560 m 四方）
NEAR_CELLS = 6                                      # ここまでは 1 マスずつ描く
MID_CELLS = 12                                      # ここまでは 2 × 2 マスをまとめて描く
FAR_CELLS = 20                                      # ここまでは 4 × 4。それより遠くは描かない（霞に溶ける）
SEA = 0.0                                           # 水面の高さ
RING_R = 14.0                                       # 輪の半径（m）
RINGS = 12
SPEEDS = (40.0, 65.0, 90.0)                         # スロットル 3 段階の速さ（m/s）
ROLL_RATE = 1.7                                     # ロールの速さ（ラジアン/秒）
LEVEL_RATE = 1.1                                    # 手を離したとき水平に戻る速さ
PITCH_RATE = 0.75
PITCH_LIMIT = math.radians(55)
BANK_LIMIT = math.radians(70)                       # これ以上は傾かない（アーケード寄り）
TURN_PER_BANK = 0.9                                 # 傾き 1 ラジアンあたりの旋回（ラジアン/秒）。アーケード寄り
CLIMB_DRAG = 0.45                                   # 上昇で失う・降下で得る速さの割合（重力の効き）
BOUNCE_UP = 0.35                                    # ぶつかったとき機首を上げる量
COUNTDOWN = 3.0
LIGHT_DIR = (-0.45, 0.8, -0.4)

SKY_TOP = (78, 130, 210)
SKY = (176, 204, 232)
HAZE = (205, 218, 236)
SUN = (255, 246, 210)
CLOUD = (240, 244, 250)
WATER = (58, 110, 176)
SAND = (196, 184, 140)
GRASS = (78, 140, 66)
FOREST = (52, 108, 54)
ROCK = (128, 118, 108)
SNOW = (232, 236, 240)
RING_NEXT = (255, 150, 40)
RING_LATER = (120, 130, 150)
RING_DONE = (90, 200, 120)
PANEL = (42, 44, 50)
PANEL_EDGE = (70, 72, 80)
GAUGE = (120, 200, 140)
GAUGE_BG = (28, 30, 34)
NEEDLE = (255, 230, 120)
FRAME = (34, 36, 40)
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
    """出来事の音。count は 3・2・1、go は出発、ring はくぐった、bump はぶつかった、finish はゴール、best はベスト更新。"""
    if kind == "count":
        samples = tone(880, 0.12)
    elif kind == "go":
        samples = tone(1320, 0.35)
    elif kind == "ring":
        samples = tone(1047, 0.07) + tone(1319, 0.07) + tone(1568, 0.14)
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


EVENTS = ("count", "go", "ring", "bump", "finish")
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


# ── 地形（ハイトマップ） ────────────────────────────────────────────────

def relief(x: float, z: float) -> float:
    """地面の高さ（m）。sin をいくつか重ねた決まった形。真ん中を川（低い帯）が横切る。"""
    u, w = x / 700.0, z / 700.0
    h = (120 * math.sin(u * 1.3 + 0.4) * math.cos(w * 1.1 - 0.2)
         + 70 * math.sin(u * 2.9 + w * 1.7) + 40 * math.sin(u * 5.1 - w * 3.3 + 1.0)
         + 22 * math.sin(u * 9.7 + w * 8.1))
    river = 90 * math.exp(-((z - 1280 - 300 * math.sin(x / 600.0)) / 140.0) ** 2)   # 川の谷
    return max(-30.0, h + 60 - river)


HEIGHTS = [[relief(i * CELL, j * CELL) for i in range(GRID + 1)] for j in range(GRID + 1)]   # [z][x]


def ground_at(x: float, z: float) -> float:
    """任意の点の地面の高さ。マスの 4 隅から双一次補間（滑らかに）。外は海。"""
    fx, fz = x / CELL, z / CELL
    if fx < 0 or fz < 0 or fx >= GRID or fz >= GRID:
        return SEA
    i, j = int(fx), int(fz)
    tx, tz = fx - i, fz - j
    h00, h10 = HEIGHTS[j][i], HEIGHTS[j][i + 1]
    h01, h11 = HEIGHTS[j + 1][i], HEIGHTS[j + 1][i + 1]
    return (h00 * (1 - tx) + h10 * tx) * (1 - tz) + (h01 * (1 - tx) + h11 * tx) * tz


def land_color(height: float, steep: float) -> tuple[int, int, int]:
    """高さと傾きで地面の色。水 → 砂 → 草 → 森 → 岩 → 雪。急なところは岩。"""
    if height <= SEA + 1:
        return WATER
    if height < 8:
        return SAND
    if steep > 0.55 and height > 60:
        return ROCK
    if height > 210:
        return SNOW
    if height > 150:
        return ROCK
    if height > 60:
        return FOREST
    return GRASS


# ── 輪とコース ──────────────────────────────────────────────────────────

@dataclass
class Ring:
    pos: V
    dir: V                                          # くぐる向き（単位ベクトル。次の輪のほう）
    done: bool = False

    def basis(self) -> tuple[V, V]:
        """輪の面の中の 2 本（横と縦）。"""
        side = V(0, 1, 0).cross(self.dir).unit()
        up = self.dir.cross(side).unit()
        return side, up


START = V(GRID * CELL / 2, 0.0, GRID * CELL / 2 + 820 - 500)   # 最初の輪の 500 m 手前（南）


def make_course() -> list[Ring]:
    """輪 12 個。地図の真ん中を大きく回る。高さは地面 + 60〜130 m（谷は低く、山は越える）。"""
    points = []
    center = V(GRID * CELL / 2, 0, GRID * CELL / 2)
    for k in range(RINGS):
        a = k * math.tau / RINGS
        radius = 820 + 260 * math.sin(a * 2 + 0.7)
        x, z = center.x + math.sin(a) * radius, center.z + math.cos(a) * radius
        lift = 70 + 60 * (0.5 + 0.5 * math.sin(a * 3 + 1.3))
        points.append(V(x, max(ground_at(x, z), SEA) + lift, z))
    rings = []
    for k, p in enumerate(points):                  # 輪の向き＝「前の輪から来て、次の輪へ行く」向きの平均（最初の輪の前はスタート）
        prev = points[k - 1] if k else V(START.x, p.y, START.z)
        nxt = points[(k + 1) % RINGS]
        rings.append(Ring(p, ((p - prev).unit() + (nxt - p).unit()).unit()))
    return rings




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

@dataclass
class World:
    seed: int = 0
    luck: random.Random = field(default_factory=random.Random)
    pos: V = V(START.x, 0.0, START.z)
    frame: Frame = Frame()
    speed: float = SPEEDS[1]
    throttle: int = 1
    rings: list[Ring] = field(default_factory=make_course)
    next: int = 0                                   # 次にくぐる輪
    time: float = 0.0
    clock: float = -COUNTDOWN
    started: bool = False
    counted: int = 4
    roll_in: float = 0.0                            # -1 左、+1 右
    pitch_in: float = 0.0                           # +1 機首上げ
    hurt: float = 0.0                               # ぶつかった直後（赤く光る）
    bumps: int = 0
    finished_at: float | None = None
    note: str = ""
    note_until: float = -1.0
    side_before: float = 0.0                        # 次の輪の面に対して、前のコマにどちら側にいたか

    def __post_init__(self):
        self.luck = random.Random(self.seed)
        self.pos = V(START.x, max(ground_at(START.x, START.z), SEA) + 120.0, START.z)
        self.side_before = self.side(self.rings[0])

    def side(self, ring: Ring) -> float:
        """輪の面のどちら側にいるか（符号つき距離）。"""
        return (self.pos - ring.pos).dot(ring.dir)

    def tell(self, text: str, seconds: float = 1.5) -> None:
        self.note = text
        self.note_until = self.clock + seconds

    def fly(self, dt: float) -> None:
        """飛行機を 1 コマ進める。ロール → 傾きで旋回 → 機首 → 速さ → 位置 → 地面。"""
        bank = self.frame.bank()
        if self.roll_in:
            want = self.roll_in * ROLL_RATE * dt
            want = max(-BANK_LIMIT - bank, min(BANK_LIMIT - bank, want))   # 限界で止める
            self.frame = self.frame.roll(want)
        else:                                       # 手を離すと水平へ戻る（アーケード寄り）
            back = max(-LEVEL_RATE * dt, min(LEVEL_RATE * dt, -bank))
            self.frame = self.frame.roll(back)
        bank = self.frame.bank()
        turn = bank * TURN_PER_BANK * dt            # 右に傾けば右へ曲がる（世界の上の軸まわり。正で方位が増える）
        self.frame = Frame(spin(self.frame.forward, V(0, 1, 0), turn), spin(self.frame.up, V(0, 1, 0), turn),
                           spin(self.frame.right, V(0, 1, 0), turn))
        climb = self.frame.climb()
        want = self.pitch_in * PITCH_RATE * dt
        if climb + want > PITCH_LIMIT or climb + want < -PITCH_LIMIT:
            want = 0.0
        if want:
            self.frame = self.frame.pitch(want)
        self.frame = self.frame.tidy()
        target = SPEEDS[self.throttle]
        self.speed += (target - self.speed) * min(1.0, 0.6 * dt)
        self.speed -= 9.8 * self.frame.forward.y * CLIMB_DRAG * dt   # 上昇で遅く、降下で速く
        self.speed = max(25.0, min(120.0, self.speed))
        self.pos = self.pos + self.frame.forward.scale(self.speed * dt)

    def touch_ground(self) -> bool:
        """地面より下に来たら跳ね返す。ぶつかったら True。"""
        floor = max(ground_at(self.pos.x, self.pos.z), SEA) + 3.0
        if self.pos.y >= floor:
            return False
        self.pos = V(self.pos.x, floor, self.pos.z)
        if self.frame.forward.y < BOUNCE_UP:        # 機首を上へ
            self.frame = Frame(V(self.frame.forward.x, BOUNCE_UP, self.frame.forward.z).unit(), self.frame.up, self.frame.right).tidy()
            self.frame = Frame(self.frame.forward, self.frame.forward.cross(self.frame.right).unit(), self.frame.right).tidy()
        self.speed *= 0.6
        self.hurt = 0.8
        self.bumps += 1
        return True

    def update(self, dt: float) -> str | None:
        if not self.started:
            return None
        happened = None
        self.clock += dt
        if self.clock < 0:                          # カウントダウン
            due = int(-self.clock) + 1
            if due < self.counted:
                self.counted = due
                return "count"
            return None
        if self.time == 0.0:
            happened = "go"
            self.tell("GO!", 1.0)
        if self.finished_at is not None:
            self.fly(dt)                            # ゴール後も飛び続ける（操作は効く）
            self.touch_ground()
            return None
        self.time += dt
        self.hurt = max(0.0, self.hurt - dt)
        self.fly(dt)
        if self.touch_ground():
            self.tell("ぶつかった！", 1.0)
            happened = "bump"
        ring = self.rings[self.next]
        now = self.side(ring)
        if self.side_before < 0 <= now:              # 輪の面をまたいだ
            t = self.side_before / (self.side_before - now)   # またいだ瞬間の位置（前と今の間）
            at = self.pos_before + (self.pos - self.pos_before).scale(t)
            if (at - ring.pos).length() <= RING_R:
                ring.done = True
                self.next += 1
                if self.next >= RINGS:
                    self.finished_at = self.time
                    self.tell(f"ゴール！ {clock_text(self.time)}", 5.0)
                    happened = "finish"
                else:
                    self.tell(f"輪 {self.next}/{RINGS}")
                    happened = "ring"
                    self.side_before = self.side(self.rings[self.next])
                    self.pos_before = self.pos
                    return happened
            else:
                self.tell("外した… 戻ってくぐる", 1.5)
        self.side_before = now
        self.pos_before = self.pos
        return happened

    pos_before: V = V(0.0, 0.0, 0.0)

    def camera(self) -> Camera:
        """コックピット：機首の少し後ろ・上。向きは機体そのもの。"""
        eye = self.pos + self.frame.forward.scale(1.2) + self.frame.up.scale(0.9)
        return Camera(eye, self.frame)

    def altitude(self) -> float:
        return self.pos.y - max(ground_at(self.pos.x, self.pos.z), SEA)


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


def draw_sky(screen: Screen, cam: Camera) -> None:
    """空と地平線。地平線は「水平で無限に遠い方向」を 2 つ投影した直線——傾けば傾く。
    空はその線より上の半平面（大きな多角形で塗る）。地平線の近くは薄い帯。"""
    scale = screen.width / WIDTH
    f = cam.frame.forward
    flat = V(f.x, 0.0, f.z).unit() if math.hypot(f.x, f.z) > 1e-6 else V(cam.frame.up.x, 0.0, cam.frame.up.z).unit()
    side = V(flat.z, 0.0, -flat.x)
    ends = []
    for k in (-1, 1):
        d = (flat + side.scale(k * 0.9)).unit()     # 前方の左右 42° の水平な向き
        q = V(d.dot(cam.frame.right), d.dot(cam.frame.up), d.dot(cam.frame.forward))
        if q.z < 0.05:                              # 真上や真下を向いている：地平線が画面に無い
            up_on_screen = cam.frame.up.y > 0
            screen.clear(SKY_TOP if (f.y > 0) == up_on_screen or f.y > 0 else FOREST)
            return
        ends.append(project(q, scale))
    (x1, y1), (x2, y2) = ends
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / length, dx / length              # 線に直角な向き。空の側へ向ける
    u = cam.frame.up
    q = V(u.dot(cam.frame.right), u.dot(cam.frame.up), u.dot(cam.frame.forward))
    sky_side = nx * q.x - ny * q.y                  # 画面の「上」は y の負。カメラの上の向き (q.x, -q.y) と同じ側か
    if sky_side < 0:
        nx, ny = -nx, -ny
    big = 4000 * scale
    ax, ay = x1 - dx * 20, y1 - dy * 20
    bx, by = x2 + dx * 20, y2 + dy * 20
    screen.clear(FOREST)
    screen.fill([(ax, ay), (bx, by), (bx + nx * big, by + ny * big), (ax + nx * big, ay + ny * big)], SKY_TOP)
    for depth, color in ((14 * scale, SKY), (5 * scale, HAZE)):   # 地平線に近い帯ほど明るく
        screen.fill([(ax, ay), (bx, by), (bx + nx * depth, by + ny * depth), (ax + nx * depth, ay + ny * depth)], color)
    sun = V(*LIGHT_DIR).unit()
    q = V(sun.dot(cam.frame.right), sun.dot(cam.frame.up), sun.dot(cam.frame.forward))
    if q.z > 0.2:
        sx, sy = project(q, scale)
        r = 5.0 * scale
        screen.fill([(sx + r * math.cos(a), sy + r * math.sin(a)) for a in (i * math.tau / 12 for i in range(12))], SUN)


CLOUDS = [(V(400 + 700 * i, 620 + 80 * math.sin(i * 2.3), 300 + 640 * ((i * 7) % 5)), 90 + 40 * math.sin(i * 1.7)) for i in range(9)]


def draw_clouds(screen: Screen, cam: Camera) -> None:
    """雲。空の高いところに置いた平らな楕円（ビルボード）。"""
    scale = screen.width / WIDTH
    for pos, size in CLOUDS:
        q = view(pos, cam)
        if q.z < NEAR + 50:
            continue
        cx, cy = project(q, scale)
        rx, ry = FOCUS * size / q.z * scale, FOCUS * size * 0.28 / q.z * scale
        if rx < 1:
            continue
        ring = [(cx + rx * math.cos(a), cy + ry * math.sin(a)) for a in (i * math.tau / 12 for i in range(12))]
        screen.fill(ring, fog(CLOUD, q.z))


def draw_terrain(screen: Screen, cam: Camera) -> None:
    """地形。飛行機の近くのマスを 1 マスずつ、遠くは 2 × 2 をまとめて、奥から順に塗る。"""
    scale = screen.width / WIDTH
    ci, cj = int(cam.pos.x / CELL), int(cam.pos.z / CELL)
    quads = []                                      # (奥行き, 4 隅の世界座標, 色)
    light = V(*LIGHT_DIR).unit()

    def add(i: int, j: int, step: int) -> None:
        if i < 0 or j < 0 or i + step > GRID or j + step > GRID:
            return
        corners = [V(i * CELL, HEIGHTS[j][i], j * CELL), V((i + step) * CELL, HEIGHTS[j][i + step], j * CELL),
                   V((i + step) * CELL, HEIGHTS[j + step][i + step], (j + step) * CELL), V(i * CELL, HEIGHTS[j + step][i], (j + step) * CELL)]
        mid = V(sum(c.x for c in corners) / 4, sum(c.y for c in corners) / 4, sum(c.z for c in corners) / 4)
        q = view(mid, cam)
        if q.z < -CELL * step or q.z > FAR or abs(q.x) > q.z * 1.4 + CELL * step:   # 後ろ・遠すぎ・視野の外
            return
        normal = (corners[2] - corners[0]).cross(corners[3] - corners[1]).unit()
        if normal.y < 0:
            normal = normal.scale(-1)
        steep = 1 - normal.y
        height = max(c.y for c in corners)
        base = land_color(mid.y if height > SEA + 1 else SEA, steep)
        quads.append((q.z, corners, shade(base, normal, q.z)))

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
    for _, corners, color in sorted(quads, key=lambda t: -t[0]):   # 奥から
        placed = [view(c, cam) for c in corners]
        if max(p.z for p in placed) < NEAR:
            continue
        poly = clip_near(placed) if min(p.z for p in placed) < NEAR else placed
        if len(poly) >= 3:
            screen.fill([project(p, scale) for p in poly], color)


def draw_ring(screen: Screen, ring: Ring, cam: Camera, color: tuple[int, int, int]) -> None:
    """輪。面の中の 2 本の基底で 16 角形を 2 つ（外と内）作り、その間を 16 枚の四角で塗る。"""
    scale = screen.width / WIDTH
    side, up = ring.basis()
    outer, inner = [], []
    for k in range(16):
        a = k * math.tau / 16
        outer.append(view(ring.pos + side.scale(RING_R * math.cos(a)) + up.scale(RING_R * math.sin(a)), cam))
        inner.append(view(ring.pos + side.scale(RING_R * 0.82 * math.cos(a)) + up.scale(RING_R * 0.82 * math.sin(a)), cam))
    depth = view(ring.pos, cam).z
    paint = fog(color, depth)
    for k in range(16):
        quad = [outer[k], outer[(k + 1) % 16], inner[(k + 1) % 16], inner[k]]
        if max(p.z for p in quad) < NEAR:
            continue
        poly = clip_near(quad) if min(p.z for p in quad) < NEAR else quad
        if len(poly) >= 3:
            screen.fill([project(p, scale) for p in poly], paint)


def draw_marker(screen: Screen, world: World, cam: Camera) -> None:
    """次の輪の印。画面の中なら輪のまわりに菱形、外なら縁に矢印。"""
    scale = screen.width / WIDTH
    ring = world.rings[world.next]
    q = view(ring.pos, cam)
    w, h = screen.width, screen.height * 0.72        # 計器板の上まで
    if q.z > NEAR:
        x, y = project(q, scale)
        if 0 <= x < w and 0 <= y < h:
            r = max(3.0, FOCUS * RING_R * 1.5 / q.z * scale)
            for a, b in (((x - r, y), (x, y - r)), ((x, y - r), (x + r, y)), ((x + r, y), (x, y + r)), ((x, y + r), (x - r, y))):
                screen.line(a, b, MARK)
            return
    # 画面の外：向きを矢印で。前後どちらでも「右か左か・上か下か」で決める
    ax, ay = q.x, q.y
    if q.z <= NEAR:
        ax, ay = -ax, -ay                            # 後ろにあるなら反対側の縁へ
    length = math.hypot(ax, ay) or 1.0
    ux, uy = ax / length, -ay / length
    cx, cy = w / 2, h / 2
    tip = (cx + ux * (w / 2 - 6 * scale), cy + uy * (h / 2 - 6 * scale))
    back = (tip[0] - ux * 7 * scale, tip[1] - uy * 7 * scale)
    px, py = -uy, ux
    screen.fill([tip, (back[0] + px * 4 * scale, back[1] + py * 4 * scale), (back[0] - px * 4 * scale, back[1] - py * 4 * scale)], MARK)


def draw_cockpit(screen: Screen, world: World) -> None:
    """計器板。姿勢指示器（人工水平儀）・速度計・高度計・輪の数・窓の柱。"""
    scale = screen.width / WIDTH
    w, h = screen.width, screen.height
    top = int(h * 0.74)
    screen.fill([(0, top), (w, top), (w, h), (0, h)], PANEL)
    screen.fill([(0, top), (w, top), (w, top + 2 * scale), (0, top + 2 * scale)], PANEL_EDGE)
    for x0 in (0, w - 5 * scale):                   # 窓の柱
        screen.fill([(x0, 0), (x0 + 5 * scale, 0), (x0 + 5 * scale, top), (x0, top)], FRAME)
    # 姿勢指示器：丸の中に地平線。傾き＝ロール、上下＝機首
    cx, cy, r = w / 2, top + (h - top) / 2, (h - top) * 0.42
    bank, climb = world.frame.bank(), world.frame.climb()
    screen.fill([(cx + r * math.cos(a), cy + r * math.sin(a)) for a in (i * math.tau / 16 for i in range(16))], GAUGE_BG)
    shift = climb / PITCH_LIMIT * r * 0.8
    hx, hy = math.cos(bank), math.sin(bank)         # 地平線の向き（画面。ロールで回る）
    ox, oy = -hy * shift, hx * shift                # 機首を上げると地平線は下がる
    ground = [(cx + ox - hx * r * 1.5, cy + oy - hy * r * 1.5), (cx + ox + hx * r * 1.5, cy + oy + hy * r * 1.5),
              (cx + ox + hx * r * 1.5 - hy * r * 2, cy + oy + hy * r * 1.5 + hx * r * 2), (cx + ox - hx * r * 1.5 - hy * r * 2, cy + oy - hy * r * 1.5 + hx * r * 2)]
    sky = [(cx + ox - hx * r * 1.5, cy + oy - hy * r * 1.5), (cx + ox + hx * r * 1.5, cy + oy + hy * r * 1.5),
           (cx + ox + hx * r * 1.5 + hy * r * 2, cy + oy + hy * r * 1.5 - hx * r * 2), (cx + ox - hx * r * 1.5 + hy * r * 2, cy + oy - hy * r * 1.5 - hx * r * 2)]
    clipped_sky = clip_circle(sky, cx, cy, r)
    clipped_ground = clip_circle(ground, cx, cy, r)
    if len(clipped_sky) >= 3:
        screen.fill(clipped_sky, (90, 150, 220))
    if len(clipped_ground) >= 3:
        screen.fill(clipped_ground, (150, 100, 60))
    screen.line((cx - r * 0.6, cy), (cx - r * 0.2, cy), NEEDLE)   # 機体の印（固定）
    screen.line((cx + r * 0.2, cy), (cx + r * 0.6, cy), NEEDLE)
    screen.plot(int(cx), int(cy), NEEDLE)
    # 速度計（左）と高度計（右）：縦の棒
    for x0, value, top_value, label_color in ((w * 0.16, world.speed, 120.0, GAUGE), (w * 0.84, world.altitude(), 400.0, GAUGE)):
        bar_h = (h - top) * 0.8
        y0 = top + (h - top) * 0.1
        screen.fill([(x0 - 4 * scale, y0), (x0 + 4 * scale, y0), (x0 + 4 * scale, y0 + bar_h), (x0 - 4 * scale, y0 + bar_h)], GAUGE_BG)
        fill_h = bar_h * max(0.0, min(1.0, value / top_value))
        screen.fill([(x0 - 3 * scale, y0 + bar_h - fill_h), (x0 + 3 * scale, y0 + bar_h - fill_h), (x0 + 3 * scale, y0 + bar_h), (x0 - 3 * scale, y0 + bar_h)], label_color)
    # スロットル（速度計の横）と、くぐった輪の数（高度計の横）
    for k in range(3):
        color = NEEDLE if k <= world.throttle else GAUGE_BG
        x0, y0 = w * 0.16 + (8 + k * 4) * scale, top + (h - top) * 0.5
        screen.fill([(x0, y0 - 3 * scale), (x0 + 3 * scale, y0 - 3 * scale), (x0 + 3 * scale, y0 + 3 * scale), (x0, y0 + 3 * scale)], color)
    for k in range(RINGS):
        color = RING_DONE if k < world.next else (RING_NEXT if k == world.next else GAUGE_BG)
        x0, y0 = w * 0.84 - (8 + (k % 6) * 4) * scale, top + (h - top) * (0.35 if k < 6 else 0.6)
        screen.fill([(x0, y0 - 1.5 * scale), (x0 + 3 * scale, y0 - 1.5 * scale), (x0 + 3 * scale, y0 + 1.5 * scale), (x0, y0 + 1.5 * scale)], color)
    if world.hurt > 0:                              # ぶつかった直後：窓の縁が赤く
        thick = int(3 * scale)
        screen.fill([(0, 0), (w, 0), (w, thick), (0, thick)], BUMP_RED)
        screen.fill([(0, 0), (thick, 0), (thick, top), (0, top)], BUMP_RED)
        screen.fill([(w - thick, 0), (w, 0), (w, top), (w - thick, top)], BUMP_RED)


def clip_circle(points: list[tuple[float, float]], cx: float, cy: float, r: float) -> list[tuple[float, float]]:
    """多角形を円で切る（近似：円を 16 角形とみなし、各辺で Sutherland–Hodgman）。計器の丸の中だけ塗るため。"""
    poly = points
    for k in range(16):
        a = k * math.tau / 16
        nx, ny = math.cos(a), math.sin(a)          # 辺の外向きの法線
        d = r * math.cos(math.pi / 16)
        kept = []
        for i in range(len(poly)):
            p, q = poly[i], poly[(i + 1) % len(poly)]
            sp = (p[0] - cx) * nx + (p[1] - cy) * ny - d
            sq = (q[0] - cx) * nx + (q[1] - cy) * ny - d
            if sp <= 0:
                kept.append(p)
            if (sp <= 0) != (sq <= 0):
                t = sp / (sp - sq)
                kept.append((p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t))
        poly = kept
        if not poly:
            return []
    return poly


def draw(screen: Screen, world: World) -> None:
    """空 → 雲 → 地形（奥から）→ 輪（奥から）→ 次の輪の印 → 計器板。"""
    cam = world.camera()
    draw_sky(screen, cam)
    draw_clouds(screen, cam)
    draw_terrain(screen, cam)
    order = sorted(range(RINGS), key=lambda k: -view(world.rings[k].pos, cam).z)
    for k in order:
        ring = world.rings[k]
        if view(ring.pos, cam).z < NEAR - RING_R:
            continue
        color = RING_DONE if ring.done else (RING_NEXT if k == world.next else RING_LATER)
        if world.finished_at is None or not ring.done:
            draw_ring(screen, ring, cam, color)
    if world.finished_at is None:
        draw_marker(screen, world, cam)
    draw_cockpit(screen, world)


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
    heading = int((math.degrees(world.frame.heading()) + 360) % 360)
    return (f" {clock_text(world.time)}  輪 {world.next:2d}/{RINGS}  速さ {world.speed:3.0f}  高度 {world.altitude():4.0f}  "
            f"方位 {heading:3d}°  傾き {int(round(math.degrees(world.frame.bank()))):4d}°  {note:<18} " + tail)


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
    cam = Camera(V(0, 0, 0), Frame().yaw(math.pi / 2))          # 東を向く
    q = view(V(10, 0, 0), cam)
    assert abs(q.z - 10) < 1e-9 and abs(q.x) < 1e-9, q
    q = view(V(0, 0, 10), cam)                                   # 北は、東を向いたカメラの左
    assert abs(q.x + 10) < 1e-9, q
    cam = Camera(V(0, 0, 0), Frame().roll(math.pi / 2))          # 右へ 90° 傾く
    q = view(V(0, 10, 0), cam)                                   # 世界の上は、下がった右の翼と反対＝左に
    assert abs(q.x + 10) < 1e-6 and abs(q.y) < 1e-6, q
    print("  東を向けば +x が正面で +z は左。右へ 90° 傾けば、世界の上が左に見える")
    print("● 地形")
    assert len(HEIGHTS) == GRID + 1 and all(len(row) == GRID + 1 for row in HEIGHTS)
    lo, hi = min(min(row) for row in HEIGHTS), max(max(row) for row in HEIGHTS)
    assert lo < SEA + 5 and hi > 150, (lo, hi)
    assert abs(ground_at(3 * CELL, 5 * CELL) - HEIGHTS[5][3]) < 1e-9, "マスの角ではその高さ"
    mid = ground_at(3.5 * CELL, 5 * CELL)
    assert abs(mid - (HEIGHTS[5][3] + HEIGHTS[5][4]) / 2) < 1e-9, "辺の真ん中は両端の平均（双一次補間）"
    assert ground_at(-10, 0) == SEA and ground_at(GRID * CELL + 10, 0) == SEA
    water = sum(1 for row in HEIGHTS for h in row if h <= SEA)
    print(f"  {GRID}×{GRID} マス（{GRID * CELL:.0f} m 四方）、高さ {lo:.0f}〜{hi:.0f} m、水面の角 {water} 個。外は海")
    print("● コース")
    rings = make_course()
    assert len(rings) == RINGS
    for k, ring in enumerate(rings):
        clearance = ring.pos.y - max(ground_at(ring.pos.x, ring.pos.z), SEA)
        assert 60 <= clearance <= 140, (k, clearance)
        assert abs(ring.dir.length() - 1) < 1e-9
        gap = (rings[(k + 1) % RINGS].pos - ring.pos).length()
        assert 250 < gap < 900, (k, gap)
    print(f"  輪 {RINGS} 個。地面から 60〜140 m、間隔 {min((rings[(k + 1) % RINGS].pos - r.pos).length() for k, r in enumerate(rings)):.0f}〜"
          f"{max((rings[(k + 1) % RINGS].pos - r.pos).length() for k, r in enumerate(rings)):.0f} m")
    print("● 飛行機の動き")
    world = World(seed=1)
    world.started = True
    world.clock = 0.0
    world.time = 0.001
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
    assert turned > 0.2, "右へ傾けば右へ曲がる"
    assert abs(world.frame.bank()) < bank, "手を離すと水平へ戻る"
    for _ in range(60):
        world.update(STEP)
    assert abs(world.frame.bank()) < 0.05, "2 秒で水平"
    alt0 = world.pos.y
    speed0 = world.speed
    world.pitch_in = 1.0
    for _ in range(45):
        world.update(STEP)
    assert world.pos.y > alt0 + 20 and world.speed < speed0, "機首を上げれば上昇し、速さは落ちる"
    world.pitch_in = 0.0
    world.throttle = 2
    for _ in range(90):
        world.update(STEP)
    assert world.speed > 75, world.speed
    print(f"  右ロール 1 秒で傾き {math.degrees(bank):.0f}°、離すと 2 秒で水平。機首上げで上昇、スロットル最大で {world.speed:.0f} m/s")
    print("● 地面との当たり")
    world = World(seed=1)
    world.started = True
    world.clock = 0.0
    world.time = 0.001
    world.pitch_in = -1.0
    events = []
    for _ in range(30 * 40):
        got = world.update(STEP)
        if got:
            events.append(got)
        if world.bumps:
            break
    assert "bump" in events and world.altitude() >= 2.9 and world.frame.forward.y > 0, (events, world.altitude())
    print(f"  機首を下げ続けると {world.time:.1f} 秒で地面。跳ね返って機首が上を向き、速さが落ちる")
    print("● 輪をくぐる判定")
    world = World(seed=1)
    world.started = True
    world.clock = 0.0
    world.time = 0.001
    ring = world.rings[0]
    world.pos = ring.pos - ring.dir.scale(5.0) + V(0, RING_R * 0.5, 0)   # 中心から 7 m 上、5 m 手前
    world.frame = Frame(ring.dir, V(0, 1, 0), V(0, 1, 0).cross(ring.dir).unit()).tidy()
    world.pos_before = world.pos
    world.side_before = world.side(ring)
    got = [world.update(STEP) for _ in range(8)]                 # 5 m 手前から 2 m/コマで進む
    assert "ring" in got and world.next == 1 and ring.done, got
    ring2 = world.rings[1]
    world.pos = ring2.pos - ring2.dir.scale(5.0) + V(0, RING_R * 1.3, 0)  # 中心から 18 m 上 → 外れ
    world.frame = Frame(ring2.dir, V(0, 1, 0), V(0, 1, 0).cross(ring2.dir).unit()).tidy()
    world.pos_before = world.pos
    world.side_before = world.side(ring2)
    got = [world.update(STEP) for _ in range(8)]
    assert "ring" not in got and world.next == 1 and world.note.startswith("外した"), got
    print("  面をまたいだ瞬間の位置が中心から半径以内なら「くぐった」。外れたら戻る")
    print("● 自動操縦で 1 周")
    world = World(seed=2)
    world.started = True
    events = []
    for _ in range(30 * 400):
        autopilot(world)
        got = world.update(STEP)
        if got:
            events.append(got)
        if world.finished_at is not None:
            break
    assert world.finished_at is not None, (world.next, world.time)
    assert events.count("ring") == RINGS - 1 and events.count("finish") == 1 and events.count("count") == 3
    print(f"  {clock_text(world.finished_at)} で {RINGS} 個全部（ぶつかった {world.bumps} 回）")
    print("● 板の大きさ")
    world = World(seed=2)
    world.started = True
    for _ in range(30 * 20):
        autopilot(world)
        world.update(STEP)
    small, big = Screen(), Screen(WIDTH * 3, HEIGHT * 3)
    started = time.perf_counter()
    draw(small, world)
    took_small = time.perf_counter() - started
    started = time.perf_counter()
    draw(big, world)
    took_big = time.perf_counter() - started
    same = sum(1 for y in range(HEIGHT) for x in range(WIDTH) if small.pixel(x, y) == big.pixel(x * 3, y * 3))
    print(f"  128×80 を描くのに {took_small * 1000:.1f} ms、384×240 は {took_big * 1000:.1f} ms。一致 {same / (WIDTH * HEIGHT):.0%}")
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


def shot(path: str, seconds: float = 12.0) -> None:
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
    """地形を真上から。高さの色と、輪と、スタート。"""
    size = 256
    screen = Screen(size, size)
    for y in range(size):
        for x in range(size):
            h = ground_at(x / size * GRID * CELL, (size - 1 - y) / size * GRID * CELL)
            screen.plot(x, y, land_color(h, 0.0))
    for k, ring in enumerate(make_course()):
        px, py = int(ring.pos.x / (GRID * CELL) * size), int(size - 1 - ring.pos.z / (GRID * CELL) * size)
        for dx in range(-2, 3):
            for dy in range(-2, 3):
                screen.plot(px + dx, py + dy, RING_NEXT if k == 0 else RING_LATER)
    px, py = int(START.x / (GRID * CELL) * size), int(size - 1 - START.z / (GRID * CELL) * size)
    for dx in range(-2, 3):
        screen.plot(px + dx, py, MARK)
        screen.plot(px, py + dx, MARK)
    with open(path, "wb") as out:
        out.write(png_bytes(screen, 2))
    print(f"{path} に書き出した")


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
