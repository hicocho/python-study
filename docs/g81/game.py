"""軽飛行機で輪をくぐる ブラウザ版

CLI 版（g81-flight-rings/main.py）と中身はまったく同じ。3 本のベクトルで持つ向き（Frame）も、
ロドリゲスの回転（spin）も、基底で見るカメラ（view）も、地形（HEIGHTS / ground_at）も、輪の判定（World.update）も 1 文字も変えていない。

違うのは入口と出口だけ。
  入口: 端末はキーの並び、ブラウザは keydown / keyup と十字ボタン・スロットルのボタン
  出口: 端末は ▀ の並び、ブラウザは canvas（4 倍の板）。音は端末が afplay、ブラウザは Audio
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
from typing import NamedTuple

from pyscript import document, when, window


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


# --- ここから下はブラウザ版だけ。CLI 版の run() / Screen.render() / Speaker / status() にあたる ---

SCALE = 4                                           # ブラウザは 4 倍の板（512 × 320）に描く
canvas = document.querySelector("#screen")
ctx = canvas.getContext("2d")
ctx.imageSmoothingEnabled = False
image = ctx.createImageData(WIDTH * SCALE, HEIGHT * SCALE)
time_label = document.querySelector("#time")
ring_label = document.querySelector("#ring")
speed_label = document.querySelector("#speed")
alt_label = document.querySelector("#alt")
heading_label = document.querySelector("#heading")
best_label = document.querySelector("#best")
fps_label = document.querySelector("#fps")
note_label = document.querySelector("#note")
message = document.querySelector("#message")
again_button = document.querySelector("#again")
go_button = document.querySelector("#go")
SAVED = "g81-best"                                  # localStorage の鍵。CLI 版の records.json にあたる


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


def refresh() -> None:
    draw(screen, world)
    screen.flush()
    time_label.textContent = clock_text(world.time)
    ring_label.textContent = f"{world.next}/{RINGS}"
    speed_label.textContent = f"{world.speed:.0f}"
    alt_label.textContent = f"{world.altitude():.0f}"
    heading_label.textContent = f"{int((math.degrees(world.frame.heading()) + 360) % 360):03d}"
    best_label.textContent = clock_text(best.total) if best.total else "--:--.--"
    if not world.started:
        note = ""
    elif world.clock < 0:
        note = f"{int(-world.clock) + 1}"
    else:
        note = world.note if world.clock < world.note_until else ""
    note_label.textContent = note or " "
    if world.finished_at is not None:
        message.textContent = (f"ゴール！ {clock_text(world.finished_at)}（ぶつかった {world.bumps} 回）"
                               + ("  ベスト更新！" if improved else ""))
    elif not world.started:
        message.textContent = "「スタート」で 3・2・1 のあと出発。← → で傾けて曲がる、↑ ↓ で機首、▲ ▼ でスロットル。橙の輪を順にくぐる"
    else:
        message.textContent = ""
    again_button.hidden = world.finished_at is None
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
            event = world.update(STEP)
            if event == "finish":
                improved = best.take(world.finished_at)
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


KEYS = {"ArrowLeft": "left", "ArrowRight": "right", "ArrowUp": "up", "ArrowDown": "down",
        "a": "left", "d": "right", "w": "faster", "s": "slower", " ": "go", "Enter": "go"}


@when("keydown", "body")
def on_down(event):
    key = KEYS.get(event.key)
    if key is not None:
        event.preventDefault()
        if event.repeat:
            return
        obey(world, key, True)


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
    refresh()


@when("pointerdown", ".pad button[data-key]")
def pad_down(event):
    event.preventDefault()
    obey(world, event.target.getAttribute("data-key"), True)


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
    improved = False
    refresh()


document.querySelector("#loading").hidden = True
refresh()
asyncio.ensure_future(loop())
