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


TUNNEL_R = 28.0                                     # トンネルの筒の半径


TUNNEL_DARK = 0.45                                  # トンネルの中の暗さ


FLOOR_W = 45.0                                      # 谷底（平ら）の半分の幅


WALL_W = 110.0                                      # 谷底から丘の高さへ戻るまでの幅（壁の斜面）


GATE_R = 16.0                                       # 輪の半径


GATE_GAP = 130.0                                    # 輪の間隔（m）


GATE_FIRST = 200.0                                  # 最初の輪までの距離


MISS_PENALTY = 3.0                                  # 輪を外したときに足す秒数


BOOST_SPEED = 20.0                                  # 輪をくぐった直後の加速（m/s）


BOOST_TIME = 1.0                                    # ブーストの長さ（秒）。連続なら +0.3 秒ずつ、2.5 秒まで


LOW_ALT = 8.0                                       # これより低く飛ぶと「低空」


LOW_BONUS = 0.5                                     # 低空 1 秒ごとに引く秒数


SPEEDS = (55.0, 80.0, 110.0)                        # スロットル 3 段階の速さ（m/s）


TURN_MAX = 1.3                                      # ← → を押し切ったときの旋回（ラジアン/秒）


TURN_EASE = 0.15                                    # 押してから旋回が立ち上がる／離してから止まるまでの秒数


ROLL_RATE = 4.0                                     # 翼の傾きが「曲がっている量」に追いつく速さ（見た目）


BANK_SHOW = math.radians(60)                        # 押し切ったときの翼の傾き（見た目）


PITCH_LEVEL = 1.4                                   # 手を離したとき機首が水平に戻る速さ


PITCH_RATE = 0.7                                    # 機首の上げ下げの速さ（1.2 では 1 秒で 27 m 上下して敏感すぎた）


PITCH_LIMIT = math.radians(50)


BANK_LIMIT = math.radians(75)


MAGNET_RANGE = 120.0                                # 次の輪がこの距離より近いと、高さだけ少し吸い寄せる


MAGNET_PULL = 0.8                                   # 吸い寄せの強さ（高さの差 × これ ＝ 1 秒あたりの寄る量）


CAM_LEAD = 0.3                                      # カメラが曲がる先を見る量（0.9 では傾けると輪が画面の中で動いて狙えなかった）


CLIMB_DRAG = 0.35


BOUNCE_UP = 0.3                                     # ぶつかって跳ね返るときの機首の上げ（sin。約 17°）


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


TUNNEL_WALL = (74, 70, 66)


TUNNEL_FLOOR = (58, 56, 54)


TUNNEL_LAMP = (255, 236, 170)


TUNNEL_MOUTH = (40, 38, 36)


FOAM = (226, 236, 244)


BODY_COLOR = (230, 220, 80)


WING_COLOR = (215, 60, 50)


TAIL_COLOR = (215, 60, 50)


NOSE_COLOR = (70, 70, 76)


PROP_COLOR = (40, 40, 44)


SHADOW_COLOR = (40, 70, 40)


PLUMB = (255, 255, 200)                             # 自機から真下へ落ちる線


SPARK = (255, 220, 120)                             # くぐった輪が散る光


GAUGE = (120, 200, 140)


GAUGE_BG = (28, 30, 34)


BOOST_COLOR = (255, 170, 60)


LOW_COLOR = (255, 230, 90)


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
    """出来事の音。count は 3・2・1、go は出発、gate はくぐった、miss は外した、bump はぶつかった、finish はゴール、best はベスト更新。"""
    if kind == "count":
        samples = tone(880, 0.12)
    elif kind == "go":
        samples = tone(1320, 0.35)
    elif kind == "gate":                            # くぐった：風切り（雑音の山）＋上がる 3 音
        whoosh = noise(0.18, VOLUME * 0.9, 6.0, 8)
        rise = tone(1047, 0.07) + tone(1319, 0.07) + tone(1568, 0.14)
        samples = array("h", (max(-32767, min(32767, a + (rise[i] if i < len(rise) else 0))) for i, a in enumerate(whoosh)))
    elif kind == "miss":
        samples = tone(330, 0.12, VOLUME * 0.8) + tone(262, 0.16, VOLUME * 0.8)
    elif kind == "low":
        samples = tone(1760, 0.04, VOLUME * 0.6) + tone(2093, 0.05, VOLUME * 0.6)
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


EVENTS = ("count", "go", "low", "gate", "miss", "bump", "finish")


SOUNDS = EVENTS + ("best",)


ENGINE_HZ = 96.0                                    # エンジン音の輪（0.5 秒）の基本の高さ（g79 と同じ作り）


def engine_bytes() -> bytes:
    """エンジン音の輪。ノコギリ波に近い倍音の和を 0.5 秒＝ちょうど 48 周期。ブラウザが loop で回し、playbackRate を速さで変える。"""
    count = int(RATE * 0.5)
    samples = array("h")
    for i in range(count):
        t = i / RATE
        wave_ = sum(math.sin(math.tau * ENGINE_HZ * n * t) / n for n in range(1, 8))
        samples.append(int(32767 * 0.2 * wave_))
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(samples.tobytes())
    return buffer.getvalue()


def engine_rate(speed: float, throttle: int, boost: bool) -> float:
    """エンジン音の再生の速さ。スロットルで段が変わり、速さで少し上がり、ブースト中はさらに高く。"""
    return 0.7 + 0.25 * throttle + (speed - 55.0) / 200.0 + (0.25 if boost else 0.0)


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


def catmull(p0: V, p1: V, p2: V, p3: V, t: float) -> V:
    """Catmull-Rom 曲線（g79 と同じ）。"""
    a = p1.scale(2)
    b = (p2 - p0).scale(t)
    c = (p0.scale(2) - p1.scale(5) + p2.scale(4) - p3).scale(t * t)
    d = (p0.scale(-1) + p1.scale(3) - p2.scale(3) + p3).scale(t * t * t)
    return (a + b + c + d).scale(0.5)


SECTION_NAMES = {"canyon": "谷", "narrow": "狭い峡谷", "bridges": "三連橋", "snake": "S 字", "tunnel": "トンネル", "climb": "滝の上昇"}


COURSES = {
    "峡谷": dict(knots=[(200, 300), (500, 700), (400, 1200), (800, 1600), (1300, 1500), (1450, 1150), (1600, 1350), (1750, 1000),
                       (1950, 800), (2200, 1200), (2100, 1800), (1700, 2200), (1200, 2300)],
                plan=[("canyon", 900), ("narrow", 600), ("bridges", 600), ("snake", 800), ("canyon", 500), ("tunnel", 400),
                      ("canyon", 700), ("climb", 900)],
                floor=40.0, hill=(180.0, 1.0)),
    "海岸": dict(knots=[(300, 200), (700, 500), (1200, 450), (1600, 750), (1500, 1250), (1000, 1400), (600, 1750),
                       (900, 2150), (1500, 2250), (2000, 2000), (2300, 1500), (2250, 900)],
                plan=[("canyon", 700), ("bridges", 700), ("canyon", 600), ("snake", 700), ("bridges", 500), ("canyon", 700),
                      ("narrow", 600), ("canyon", 800)],
                floor=12.0, hill=(120.0, 0.7)),
    "高原": dict(knots=[(2300, 300), (1900, 600), (2100, 1000), (1700, 1350), (1300, 1150), (1000, 1500), (1250, 1900),
                       (800, 2200), (400, 1900), (350, 1400), (600, 1000), (300, 600)],
                plan=[("narrow", 700), ("tunnel", 400), ("canyon", 500), ("snake", 700), ("tunnel", 350), ("narrow", 600),
                      ("canyon", 500), ("climb", 1000)],
                floor=150.0, hill=(270.0, 1.1)),
}


COURSE_ORDER = ("峡谷", "海岸", "高原", "ランダム")


COURSE_NAME = "峡谷"


COURSE_SEED = 0


KNOTS = COURSES["峡谷"]["knots"]


SECTIONS: list[tuple[str, str, float, float]] = []  # (表示名, 種類, 道のりの始まり, 終わり)


FLOOR_BASE = 40.0


HILL_BASE = 180.0


HILL_AMP = 1.0


def random_course(seed: int) -> dict:
    """種から作るコース。道すじは向きを少しずつ変えながら 420 m ほどの歩幅で 12 歩、地図の中に収める。
    区間は 4 種を混ぜて並べ、最後は 2 回に 1 回「滝の上昇」。"""
    luck = random.Random(seed)
    x, z = luck.uniform(400, 2100), 280.0
    heading = luck.uniform(-0.4, 0.4)
    knots = [(x, z)]
    for _ in range(12):
        best = None                                  # 候補を何度か作り、地図の中で前の点から一番離れたものを採る
        for attempt in range(40):
            step = luck.uniform(340, 500)
            if attempt < 20:
                nh = heading + luck.uniform(0.3, 1.3) * luck.choice((-1, 1))   # 少し曲がる
            else:
                nh = math.atan2(1280 - x, 1280 - z) + luck.uniform(-1.2, 1.2)   # 真ん中のほうへ
            nx, nz = x + math.sin(nh) * step, z + math.cos(nh) * step
            if not (220 < nx < 2340 and 220 < nz < 2340):
                continue
            gap = min(math.hypot(nx - kx, nz - kz) for kx, kz in knots)
            if best is None or gap > best[0]:
                best = (gap, nh, nx, nz)
            if gap > 330:
                break
        _, heading, x, z = best
        knots.append((x, z))
    kinds = ["narrow", "bridges", "snake", "tunnel"]
    luck.shuffle(kinds)
    plan = [("canyon", 700)]
    for kind in kinds:
        plan.append((kind, luck.choice((500, 600, 700))))
        if luck.random() < 0.6:
            plan.append(("canyon", luck.choice((400, 500, 600))))
    if luck.random() < 0.5:
        plan.append(("climb", 900))
    else:
        plan.append(("canyon", 800))
    return dict(knots=knots, plan=plan, floor=luck.uniform(20, 120), hill=(luck.uniform(150, 260), luck.uniform(0.7, 1.2)))


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


PATH: list[V] = []


PATH_LEN = 0.0


def section_at(s: float) -> tuple[str, str]:
    """道のり s の区間（名前, 種類）。"""
    for name, kind, lo, hi in SECTIONS:
        if lo <= s < hi:
            return name, kind
    return SECTIONS[-1][0], SECTIONS[-1][1]


def section_span(kind: str) -> tuple[float, float] | None:
    """その種類の区間の (始まり, 終わり)。無ければ None。"""
    for _, k, lo, hi in SECTIONS:
        if k == kind:
            return lo, hi
    return None


def floor_width(k: int) -> float:
    """点 k の谷底の半分の幅。狭い峡谷は半分、トンネルの前後は少しずつ狭く。"""
    kind = section_at(k * PATH_STEP)[1]
    if kind == "narrow":
        return FLOOR_W * 0.5
    return FLOOR_W


def climb_lift(k: int) -> float:
    """滝の上昇の区間で足す高さ（900 m で 180 m）。谷底だけでなく、まわりの山も一緒に持ち上げる。"""
    span = section_span("climb")
    if span is None:
        return 0.0
    s = k * PATH_STEP
    lo, hi = span
    if s <= lo:
        return 0.0
    t = min(1.0, (s - lo) / (hi - lo))
    return 180 * t * t


def floor_at(k: int) -> float:
    """道すじの点 k の谷底の高さ。ゆっくり上下し、滝の上昇の区間では上る。水面（0）より下には行かない。"""
    s = k * PATH_STEP
    return max(6.0, FLOOR_BASE + 40 * math.sin(s / 600.0) + s * 0.012) + climb_lift(k)


def in_tunnel(s: float) -> bool:
    return section_at(s)[1] == "tunnel"


def hills(x: float, z: float) -> float:
    """峡谷を掘る前の丘。sin をいくつか重ねた決まった形。基準と倍率はコースで違う。"""
    u, w = x / 500.0 + COURSE_SEED * 0.37, z / 500.0 + COURSE_SEED * 0.61   # 種で模様をずらす
    return HILL_BASE + HILL_AMP * (40 * math.sin(u * 1.3 + 0.4) * math.cos(w * 1.1 - 0.2)
                                   + 30 * math.sin(u * 2.9 + w * 1.7) + 18 * math.sin(u * 5.1 - w * 3.3 + 1.0)
                                   + 8 * math.sin(u * 9.7 + w * 8.1))


def carve() -> list[list[float]]:
    """丘に峡谷を掘る。道すじに近いマスほど低く：谷底（幅 FLOOR_W）は平ら、そこから WALL_W かけて丘の高さへ戻る。
    谷底の高さは道すじに沿ってゆっくり上下する（進むほど少し上る）。"""
    heights = [[hills(i * CELL, j * CELL) for i in range(GRID + 1)] for j in range(GRID + 1)]
    near: dict[tuple[int, int], tuple[float, float, float, float]] = {}   # マス → (道すじまでの距離, 谷底の高さ, 谷底の幅, 持ち上げ)
    reach = int((FLOOR_W + WALL_W) / CELL) + 1
    for k, p in enumerate(PATH):
        if in_tunnel(k * PATH_STEP):                # トンネルの区間は掘らない（山がそのまま残り、筒で貫く）
            continue
        floor = floor_at(k)
        width = floor_width(k)
        ci, cj = int(p.x / CELL), int(p.z / CELL)
        for j in range(cj - reach, cj + reach + 1):
            for i in range(ci - reach, ci + reach + 1):
                if 0 <= i <= GRID and 0 <= j <= GRID:
                    d = math.hypot(i * CELL - p.x, j * CELL - p.z)
                    if (i, j) not in near or d < near[(i, j)][0]:
                        near[(i, j)] = (d, floor, width, climb_lift(k))
    for (i, j), (d, floor, width, lift) in near.items():
        t = max(0.0, min(1.0, (d - width) / WALL_W))
        t = t * t * (3 - 2 * t)                       # なめらかに（smoothstep）
        hill = heights[j][i] + lift                     # 上昇の区間では山も一緒に上げる
        heights[j][i] = max(floor, floor + (hill - floor) * t)
    return heights


HEIGHTS: list[list[float]] = []                     # [z][x]


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


def path_dir(k: int) -> V:
    a, b = PATH[max(0, k - 1)], PATH[min(len(PATH) - 1, k + 1)]
    return V(b.x - a.x, 0.0, b.z - a.z).unit()


def locate(pos: V, hint: int) -> tuple[int, float]:
    """道すじの上でどこか。hint の近くから一番近い点を探し、(点の番号, 道のり) を返す。"""
    lo, hi = max(0, hint - 8), min(len(PATH) - 1, hint + 16)
    k = min(range(lo, hi + 1), key=lambda i: (PATH[i].x - pos.x) ** 2 + (PATH[i].z - pos.z) ** 2)
    along = (pos - PATH[k]).dot(path_dir(k))
    return k, k * PATH_STEP + along


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
        kind = section_at(k * PATH_STEP)[1]
        lateral = 14.0 * math.sin(n * 1.9)
        lift = 28 + 12 * math.sin(n * 1.3 + 0.5)
        if kind == "narrow":                        # 狭い峡谷：真ん中を低く
            lateral, lift = 4.0 * math.sin(n * 1.9), 18 + 6 * math.sin(n * 1.3)
        elif kind == "bridges":                     # 三連橋：橋の下（低め）
            lateral, lift = 0.0, 22
        elif kind == "snake":                       # S 字：大きく左右に振る
            lateral, lift = 22.0 * (1 if n % 2 else -1), 26 + 8 * math.sin(n * 1.3)
        elif kind == "tunnel" or in_tunnel(k * PATH_STEP + 300):   # トンネルの中と、その手前 300 m：筒の真ん中の高さへ導く
            lateral, lift = 0.0, TUNNEL_R
        elif kind == "climb":                       # 上昇：谷底が上るので、少し高め
            lateral, lift = 10.0 * math.sin(n * 1.9), 34 + 8 * math.sin(n * 1.3)
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
        kind = section_at(k * PATH_STEP)[1]
        if kind == "bridges":                       # 三連橋：輪ごとに橋（輪はその下）
            props.append(Prop("bridge", V(p.x, floor_at(k) + 44, p.z), d, floor_width(k) * 2 + 30))
        elif kind == "tunnel":
            pass                                    # トンネルの中に障害物は置かない
        elif kind == "narrow":                      # 狭い峡谷：細い岩柱を真ん中寄りに
            off = 9.0 if n % 2 else -9.0
            props.append(Prop("pillar", V(p.x + side.x * off, floor_at(k), p.z + side.z * off), d, 40 + 10 * (n % 2)))
        elif n % 5 == 2 and kind == "canyon":
            props.append(Prop("bridge", V(p.x, floor_at(k) + 48, p.z), d, FLOOR_W * 2 + 30))
        else:
            off = (18.0 if n % 2 else -18.0) * (1 if n % 3 else -1)
            props.append(Prop("pillar", V(p.x + side.x * off, floor_at(k), p.z + side.z * off), d, 55 + 20 * (n % 3)))
        k += int(GATE_GAP / PATH_STEP)
        n += 1
    return props


def make_falls() -> list[Prop]:
    """滝。上昇の区間の入口の右の壁に 2 本（上昇の区間が無ければ無し）。"""
    falls = []
    span = section_span("climb")
    if span is None:
        return falls
    lo = span[0]
    for s_at in (lo + 150, lo + 520):
        k = int(s_at / PATH_STEP)
        p = PATH[k]
        d = path_dir(k)
        side = V(d.z, 0.0, -d.x)
        foot = V(p.x + side.x * (floor_width(k) + 30), 0.0, p.z + side.z * (floor_width(k) + 30))
        falls.append(Prop("falls", V(foot.x, ground_at(foot.x, foot.z), foot.z), side, 90.0))
    return falls


def tunnel_rings() -> list[list[tuple[V, V]]]:
    """トンネルごとの、筒の軸の点と向き。区間の少し外まで、20 m おき。"""
    tunnels = []
    for _, kind, lo, hi in SECTIONS:
        if kind != "tunnel":
            continue
        rings = []
        for s_at in range(int(lo) - 20, int(hi) + 21, 20):
            k = max(0, min(len(PATH) - 1, int(s_at / PATH_STEP)))
            rings.append((V(PATH[k].x, floor_at(k) + TUNNEL_R, PATH[k].z), path_dir(k)))
        tunnels.append(rings)
    return tunnels


TUNNELS: list[list[tuple[V, V]]] = []


def make_trees() -> list[tuple[V, float]]:
    """谷の両岸に木。道すじに沿って 25 m おき、左右 40〜70 m。"""
    trees = []
    for k in range(0, len(PATH), int(25 / PATH_STEP)):
        p = PATH[k]
        d = path_dir(k)
        side = V(d.z, 0.0, -d.x)
        if in_tunnel(k * PATH_STEP):
            continue
        for sign in (-1, 1):
            off = sign * (floor_width(k) + 10 + 25 * abs(math.sin(k * 0.7 + sign)))
            x, z = p.x + side.x * off, p.z + side.z * off
            trees.append((V(x, ground_at(x, z), z), 9 + 5 * abs(math.sin(k * 1.3))))
    return trees


GATES_ALL: list[Gate] = []


PROPS: list[Prop] = []


TREES: list[tuple[V, float]] = []


GATES = 0


def load_course(name: str, seed: int = 0) -> None:
    """コースを読み込む（地図の作り直し）。名前が「ランダム」なら種から作る。世界や描く側はこの結果を読む。"""
    global COURSE_NAME, COURSE_SEED, KNOTS, SECTIONS, FLOOR_BASE, HILL_BASE, HILL_AMP
    global PATH, PATH_LEN, HEIGHTS, TUNNELS, GATES_ALL, PROPS, TREES, GATES
    spec = random_course(seed) if name == "ランダム" else COURSES[name]
    COURSE_NAME, COURSE_SEED = name, (seed if name == "ランダム" else 0)
    KNOTS = spec["knots"]
    FLOOR_BASE, (HILL_BASE, HILL_AMP) = spec["floor"], spec["hill"]
    PATH = make_path()
    PATH_LEN = (len(PATH) - 1) * PATH_STEP
    SECTIONS, at = [], 0.0                          # 区間の並びを道のりに直す。最後の区間は道すじの終わりまで
    for k, (kind, length) in enumerate(spec["plan"]):
        end = PATH_LEN + 1 if k == len(spec["plan"]) - 1 else at + length
        SECTIONS.append((SECTION_NAMES[kind], kind, at, end))
        at = end
    HEIGHTS = carve()
    TUNNELS = tunnel_rings()
    GATES_ALL = make_gates()
    PROPS = make_props() + make_falls()
    TREES = make_trees()
    GATES = len(GATES_ALL)


LOADED = load_course("峡谷")                         # 最初のコースを読み込む（代入の形にしておくと、ブラウザ版の切り出しにも入る）


@dataclass
class Best:
    """コースごとのベストタイム。ランダムは種が違っても 1 つにまとめる。"""

    totals: dict[str, float] = field(default_factory=dict)

    def of(self, course: str) -> float:
        return self.totals.get(course, 0.0)          # 0 は未記録

    def dump(self) -> str:
        return json.dumps({"totals": self.totals})

    @classmethod
    def parse(cls, text: str) -> "Best":
        try:
            data = json.loads(text)
            totals = {str(k): float(v) for k, v in data["totals"].items()}
            return cls(totals)
        except (ValueError, KeyError, TypeError, AttributeError):
            return cls()

    def take(self, course: str, total: float) -> bool:
        if self.of(course) == 0.0 or total < self.of(course):
            self.totals[course] = round(total, 2)
            return True
        return False


def fresh_gates() -> list[Gate]:
    return [Gate(g.pos, g.dir, g.s, "next" if k == 0 else "later") for k, g in enumerate(GATES_ALL)]


@dataclass
class World:
    seed: int = 0
    course: str = "峡谷"                             # 読み込んだコースの名前（記録の鍵）
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
    turning: float = 0.0                            # いま曲がっている量（-1〜+1）。roll_in に 0.15 秒で追いつく
    sparks: list[list] = field(default_factory=list)   # くぐった輪の光の粒 [位置, 速さ, 残り秒]
    spray: list[list] = field(default_factory=list)    # 低空の水しぶき [位置, 速さ, 残り秒]
    hurt: float = 0.0
    bumps: int = 0
    misses: int = 0
    combo: int = 0
    finished_at: float | None = None
    boost: float = 0.0                              # ブーストの残り秒数
    low_time: float = 0.0                           # 低空を続けている秒数（1 秒ごとにボーナス）
    low_total: float = 0.0                          # 低空で稼いだ秒数
    note: str = ""
    note_until: float = -1.0
    cam_pos: V = V(0.0, 0.0, 0.0)
    cam_frame: Frame = Frame()
    prop_spin: float = 0.0

    def __post_init__(self):
        self.course = COURSE_NAME
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
        """旋回（押した量に直結）→ 翼の傾き（見た目）→ 機首 → 速さ → 位置。

        前は「翼を傾ける → 傾きに比例して曲がる」の 2 段階で、押してから 0.3 秒遅れて曲がり始め、
        離しても 0.5〜1 秒曲がり続けた。今は押した量 roll_in に turning が 0.15 秒で追いつき、その量で曲がる。
        翼の傾きは turning に合わせて見せるだけ（曲がりの原因ではない）。
        """
        ease = min(1.0, dt / TURN_EASE)
        self.turning += (self.roll_in - self.turning) * ease
        if abs(self.turning) < 0.01 and not self.roll_in:
            self.turning = 0.0
        turn = self.turning * TURN_MAX * dt
        self.frame = Frame(spin(self.frame.forward, V(0, 1, 0), turn), spin(self.frame.up, V(0, 1, 0), turn),
                           spin(self.frame.right, V(0, 1, 0), turn))
        bank = self.frame.bank()
        want_bank = self.turning * BANK_SHOW
        self.frame = self.frame.roll(max(-ROLL_RATE * dt, min(ROLL_RATE * dt, want_bank - bank)))
        climb = self.frame.climb()
        want = self.pitch_in * PITCH_RATE * dt
        if not self.pitch_in:                        # 手を離すと機首も水平へ
            want = max(-PITCH_LEVEL * dt, min(PITCH_LEVEL * dt, -climb))
        want = max(-PITCH_LIMIT - climb, min(PITCH_LIMIT - climb, want)) if abs(climb) < PITCH_LIMIT else (
            want if want * climb < 0 else 0.0)      # 限界の中では限界で止め、外にいる（ぶつかって上を向いた）ときは戻る向きだけ許す
        if want:
            self.frame = self.frame.pitch(want)
        self.frame = self.frame.tidy()
        target = SPEEDS[self.throttle] + (BOOST_SPEED if self.boost > 0 else 0.0)
        self.speed += (target - self.speed) * min(1.0, (2.5 if self.boost > 0 else 0.8) * dt)
        self.speed -= 9.8 * self.frame.forward.y * CLIMB_DRAG * dt
        self.speed = max(30.0, min(140.0, self.speed))
        self.pos = self.pos + self.frame.forward.scale(self.speed * dt)
        self.prop_spin += self.speed * 0.4 * dt

    def hit_prop(self) -> V | None:
        """岩柱や橋にめり込んでいれば、押し出す向き（法線）を返す。"""
        for prop in PROPS:
            d = self.pos - prop.pos
            if abs(d.x) > 80 or abs(d.z) > 80:
                continue
            if prop.kind == "falls":
                continue
            if prop.kind == "pillar":
                if abs(d.x) < 5.5 and abs(d.z) < 5.5 and d.y < prop.size + 2:
                    n = V(d.x, 0.0, d.z).unit() if math.hypot(d.x, d.z) > 0.1 else V(1.0, 0.0, 0.0)
                    return n if d.y < prop.size - 2 else V(0, 1, 0)   # 上面ならはね上げる
                continue
            side = V(prop.dir.z, 0.0, -prop.dir.x)
            along, across = d.dot(prop.dir), d.dot(side)
            if abs(along) < 4.5 and abs(across) < prop.size / 2 + 2 and abs(d.y) < 3.5:   # 梁
                return V(0, -1.0, 0) if d.y < 0 else V(0, 1.0, 0)
            for sign in (-1, 1):                                                    # 両端の柱
                if abs(along) < 3.5 and abs(across - sign * prop.size / 2) < 3.5 and d.y < 2:
                    return prop.dir.scale(1 if along > 0 else -1)
        return None

    def collide(self) -> bool:
        """地面や壁、岩柱や橋、トンネルの筒にめり込んだら、法線の向きに押し出して、進む向きを跳ね返す。"""
        floor = ground_at(self.pos.x, self.pos.z) + 2.5
        axis = self.tunnel_axis()
        n = self.hit_prop()
        if axis is not None:                            # トンネルの中：筒の壁が「地面」
            center, d = axis
            off = self.pos - center
            off = off - d.scale(off.dot(d))             # 軸に直角な成分
            if off.length() <= TUNNEL_R - 2.5:
                return False
            n = off.unit().scale(-1)                    # 軸へ向かう向き
            self.pos = center + off.unit().scale(TUNNEL_R - 3.0) + d.scale(off.dot(d) * 0)
            floor = self.pos.y
        elif n is None and self.pos.y >= floor:
            return False
        elif n is None:
            n = ground_normal(self.pos.x, self.pos.z)
        else:
            floor = self.pos.y                          # 障害物：地面には触っていない
            self.pos = self.pos + n.scale(6.0)          # めり込みから出す
        f = self.frame.forward
        bounced = (f - n.scale(2 * f.dot(n))).scale(0.6) + n.scale(0.4)   # 反射して、少し法線の向きへ
        level = V(bounced.x, 0.0, bounced.z)        # 横向きの成分。真上に跳ねそうなら、もとの向きの横成分を使う
        if level.length() < 0.2:
            level = V(f.x, 0.0, f.z)
        lift = max(0.05, min(BOUNCE_UP, bounced.y))  # ただし機首は少ししか上げない（谷から飛び出さない）
        bounced = level.unit().scale(math.sqrt(1 - lift * lift)) + V(0, lift, 0)
        self.frame = Frame(bounced, V(0, 1, 0), V(0, 1, 0).cross(bounced).unit()).tidy()
        self.pos = V(self.pos.x, max(self.pos.y, floor), self.pos.z) + n.scale(3.0)
        self.speed *= 0.5
        self.hurt = 0.8
        self.bumps += 1
        self.combo = 0
        self.boost = 0.0
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
        self.boost = max(0.0, self.boost - dt)
        before = self.pos
        self.fly(dt)
        if self.next < GATES:                        # 次の輪が近ければ、高さだけ少し吸い寄せる（上下の狙いを助ける）
            gate = self.gates[self.next]
            ahead = (gate.pos - self.pos).dot(gate.dir)
            if 0 < ahead < MAGNET_RANGE and abs(gate.pos.y - self.pos.y) < 30:
                self.pos = V(self.pos.x, self.pos.y + (gate.pos.y - self.pos.y) * MAGNET_PULL * dt, self.pos.z)
        if self.collide():
            self.tell("ぶつかった！", 1.0)
            happened = "bump"
        for bits in (self.sparks, self.spray):      # 粒を飛ばす
            for bit in bits:
                bit[0] = bit[0] + bit[1].scale(dt)
                bit[1] = V(bit[1].x, bit[1].y - 9.8 * dt, bit[1].z)
                bit[2] -= dt
            bits[:] = [bit for bit in bits if bit[2] > 0]
        if self.altitude() < LOW_ALT and self.speed > 50:   # 低空：1 秒続けるごとにタイムを引く
            if ground_at(self.pos.x, self.pos.z) < floor_at(self.hint) + 1.0 and len(self.spray) < 40:   # 川の上なら水しぶき
                for _ in range(2):
                    aside = self.frame.right.scale(random.Random(int(self.time * 1000) % 977).uniform(-3, 3))
                    self.spray.append([self.pos - self.frame.forward.scale(3.0) + aside, V(0, 6.0, 0) - self.frame.forward.scale(8.0), 0.5])
            self.low_time += dt
            if self.low_time >= 1.0:
                self.low_time -= 1.0
                self.low_total += LOW_BONUS
                self.penalty -= LOW_BONUS
                self.tell(f"低空！ −{LOW_BONUS} 秒", 1.0)
                happened = happened or "low"
        else:
            self.low_time = 0.0
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
            self.boost = min(2.5, BOOST_TIME + 0.3 * (self.combo - 1))   # くぐるとブースト。連続なら長く
            side, up = gate.basis()
            for k in range(14):                     # 輪が光の粒になって散る
                a = k * math.tau / 14
                out = side.scale(math.cos(a)) + up.scale(math.sin(a))
                self.sparks.append([gate.pos + out.scale(GATE_R), out.scale(18.0) + gate.dir.scale(self.speed * 0.3), 0.7])
            self.tell(f"輪 {self.next + 1}/{GATES}  ブースト" + (f"  {self.combo} 連続" if self.combo > 1 else ""))
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
        ahead = self.frame.forward.scale(12.0)
        lead = spin(self.frame.forward, V(0, 1, 0), self.turning * TURN_MAX * CAM_LEAD)   # 曲がる先の向き
        look = (self.pos + ahead + lead.scale(self.speed * 0.35 * abs(self.turning)) - self.cam_pos).unit()
        up_hint = spin(V(0, 1, 0), look, -self.frame.bank() * 0.25)
        right = up_hint.cross(look).unit()
        self.cam_frame = Frame(look, look.cross(right).unit(), right)

    def camera(self) -> Camera:
        return Camera(self.cam_pos, self.cam_frame)

    def altitude(self) -> float:
        return self.pos.y - ground_at(self.pos.x, self.pos.z)

    def section(self) -> str:
        return section_at(self.s)[0]

    def tunnel_axis(self) -> tuple[V, V] | None:
        """トンネルの中なら (軸の点, 向き)。"""
        if not in_tunnel(self.s):
            return None
        k = self.hint
        return V(PATH[k].x, floor_at(k) + TUNNEL_R, PATH[k].z), path_dir(k)

    def darkness(self) -> float:
        """いまの暗さ（1 = 明るい）。どのトンネルでも、口の前後 40 m で変わる。"""
        inside = 0.0
        for _, kind, lo, hi in SECTIONS:
            if kind == "tunnel":
                inside = max(inside, max(0.0, min(self.s - lo + 40, hi - self.s + 40, 60)) / 60)
        return 1.0 - (1.0 - TUNNEL_DARK) * inside


def clock_text(seconds: float) -> str:
    return f"{int(seconds // 60)}:{seconds % 60:05.2f}"


DIM = [1.0]                                         # いまの明るさ（トンネルの中で暗く）。draw() が決める


def fog(color: tuple[int, int, int], z: float) -> tuple[int, int, int]:
    amount = max(0.0, min(0.92, (z - FOG_FROM) / (FAR - FOG_FROM)))
    k = DIM[0]
    return tuple(int((c + (b - c) * amount) * k) for c, b in zip(color, HAZE))


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
    if max(p.z for p in ground) > NEAR:              # 真下の影（高さの当たりをつける）と、そこへ落ちる細い線
        draw_quad(screen, ground, fog(SHADOW_COLOR, ground[0].z), scale)
        foot = view(V(world.pos.x, ground_at(world.pos.x, world.pos.z) + 0.3, world.pos.z), cam)
        top = view(world.pos - u.scale(0.6), cam)
        if foot.z > NEAR and top.z > NEAR:
            screen.line(project(top, scale), project(foot, scale), fog(PLUMB, foot.z))


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
    if in_tunnel(gate.s):                           # トンネルの中の輪に柱は無い
        return
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


def draw_tunnel(screen: Screen, rings: list[tuple[V, V]], k: int, cam: Camera) -> None:
    """トンネルの筒の 1 区切り（20 m）。12 角形の輪と輪の間を塗る。天井に灯り。入口と出口は暗い口。"""
    scale = screen.width / WIDTH
    (c0, d0), (c1, d1) = rings[k], rings[k + 1]
    side0, side1 = V(0, 1, 0).cross(d0).unit(), V(0, 1, 0).cross(d1).unit()
    up0, up1 = d0.cross(side0).unit(), d1.cross(side1).unit()
    ring0 = [view(c0 + side0.scale(TUNNEL_R * math.cos(a)) + up0.scale(TUNNEL_R * math.sin(a)), cam) for a in (i * math.tau / 12 for i in range(12))]
    ring1 = [view(c1 + side1.scale(TUNNEL_R * math.cos(a)) + up1.scale(TUNNEL_R * math.sin(a)), cam) for a in (i * math.tau / 12 for i in range(12))]
    depth = view(c0, cam).z
    for i in range(12):
        quad = [ring0[i], ring0[(i + 1) % 12], ring1[(i + 1) % 12], ring1[i]]
        lamp = k % 2 == 0 and i in (2, 3)             # 上のほう、1 つおきの区切りに灯り
        color = TUNNEL_LAMP if lamp else (TUNNEL_WALL if i in (0, 1, 2, 3, 4, 5, 6) else TUNNEL_FLOOR)
        draw_quad(screen, quad, fog(color, max(NEAR, depth)), scale)
    if k == 0 or k == len(rings) - 2:                  # 口：筒のまわりの暗い環（山の面との継ぎ目を隠す）
        c, sd, up = (c0, side0, up0) if k == 0 else (c1, side1, up1)
        outer = [view(c + sd.scale(TUNNEL_R * 1.7 * math.cos(a)) + up.scale(TUNNEL_R * 1.7 * math.sin(a)), cam) for a in (i * math.tau / 12 for i in range(12))]
        inner = ring0 if k == 0 else ring1
        for i in range(12):
            draw_quad(screen, [outer[i], outer[(i + 1) % 12], inner[(i + 1) % 12], inner[i]], fog(TUNNEL_MOUTH, max(NEAR, depth)), scale)


def draw_falls(screen: Screen, prop: Prop, cam: Camera) -> None:
    """滝。壁に貼った縦長の板（水色）に白い筋。足元に水しぶきの円。"""
    scale = screen.width / WIDTH
    side = V(prop.dir.z, 0.0, -prop.dir.x)
    top = prop.pos + V(0, prop.size, 0)
    for w, color, dy in ((7.0, WATER, 0.0), (2.2, FOAM, 0.0), (2.2, FOAM, prop.size * 0.4)):
        x0 = side.scale(w) if dy == 0 else side.scale(w + 3.0)
        quad = [view(prop.pos - x0, cam), view(prop.pos + x0, cam), view(top + x0, cam), view(top - x0, cam)]
        draw_quad(screen, quad, fog(color, max(NEAR, view(prop.pos, cam).z)), scale)
    ring = [view(prop.pos + side.scale(14 * math.cos(a)) + prop.dir.scale(-9 * math.sin(a) - 6) + V(0, 0.5, 0), cam) for a in (i * math.tau / 10 for i in range(10))]
    draw_quad(screen, ring, fog(FOAM, max(NEAR, view(prop.pos, cam).z)), scale)


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
    for x0, value, top_value, color in ((4 * scale, world.speed, 140.0, BOOST_COLOR if world.boost > 0 else GAUGE),
                                        (w - 7 * scale, world.altitude(), 150.0, LOW_COLOR if world.altitude() < LOW_ALT else GAUGE)):
        bar_h, y1 = 24 * scale, h - 4 * scale
        screen.fill([(x0, y1 - bar_h), (x0 + 3 * scale, y1 - bar_h), (x0 + 3 * scale, y1), (x0, y1)], GAUGE_BG)
        fill_h = bar_h * max(0.0, min(1.0, value / top_value))
        screen.fill([(x0, y1 - fill_h), (x0 + 3 * scale, y1 - fill_h), (x0 + 3 * scale, y1), (x0, y1)], color)
    if world.boost > 0 and world.hurt == 0:         # ブースト中：縁がうっすら橙に
        thick = int(2 * scale)
        for quad in (((0, 0), (w, 0), (w, thick), (0, thick)), ((0, h - thick), (w, h - thick), (w, h), (0, h)),
                     ((0, 0), (thick, 0), (thick, h), (0, h)), ((w - thick, 0), (w, 0), (w, h), (w - thick, h))):
            screen.fill(list(quad), BOOST_COLOR)
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
    DIM[0] = world.darkness()
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
    for rings in TUNNELS:
        for k in range(len(rings) - 1):
            q = view(rings[k][0], cam)
            if -30 < q.z < 900:
                things.append((q.z + 10, "tunnel", (rings, k)))   # 少し奥扱い（同じ場所の輪より先に描く）
    for z, kind, thing in sorted(things, key=lambda t: -t[0]):
        if kind == "tree":
            draw_tree(screen, thing[0], thing[1], scale)
        elif kind == "gate":
            draw_gate(screen, thing, cam)
        elif kind == "tunnel":
            draw_tunnel(screen, thing[0], thing[1], cam)
        elif thing.kind == "falls":
            draw_falls(screen, thing, cam)
        else:
            draw_prop(screen, thing, cam)
    for bits, color, size in ((world.sparks, SPARK, 0.8), (world.spray, FOAM, 0.6)):
        for pos, _, left in bits:
            q = view(pos, cam)
            if q.z > NEAR:
                x, y = project(q, scale)
                r = max(1.0, size * scale * (0.5 + left))
                screen.fill([(x - r, y), (x, y - r), (x + r, y), (x, y + r)], fog(color, q.z))
    draw_plane(screen, world, cam)
    if world.finished_at is None:
        draw_marker(screen, world, cam)
    draw_hud(screen, world)


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
miss_label = document.querySelector("#miss")
combo_label = document.querySelector("#combo")
low_label = document.querySelector("#low")
section_label = document.querySelector("#section")
speed_label = document.querySelector("#speed")
alt_label = document.querySelector("#alt")
heading_label = document.querySelector("#heading")
best_label = document.querySelector("#best")
fps_label = document.querySelector("#fps")
note_label = document.querySelector("#note")
message = document.querySelector("#message")
again_button = document.querySelector("#again")
go_button = document.querySelector("#go")
course_buttons = document.querySelectorAll(".courses button")
course_label = document.querySelector("#course")
SAVED = "g81-best"                                  # localStorage の鍵。CLI 版の records.json にあたる
sound_on = document.querySelector("#engine")


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
    """出来事の音は Audio に持たせておく。エンジン音は 0.5 秒の輪を loop で回し、playbackRate を変える（g79 と同じ。ブラウザだけ）。"""

    def __init__(self):
        self.made = {}
        for kind in SOUNDS:
            uri = "data:audio/wav;base64," + base64.b64encode(sound_bytes(kind)).decode()
            self.made[kind] = window.Audio.new(uri)
        self.engine = window.Audio.new("data:audio/wav;base64," + base64.b64encode(engine_bytes()).decode())
        self.engine.loop = True
        self.engine.preservesPitch = False
        self.engine.webkitPreservesPitch = False
        self.engine.volume = 0.45
        self.running = False

    def say(self, kind: str | None) -> None:
        if kind is None:
            return
        sound = self.made[kind]
        sound.currentTime = 0
        sound.play()

    def start_engine(self) -> None:
        """人が触った処理の中から呼ぶ（Safari は時計からでは音を始められない。g79 で覚えた）。"""
        if not self.running:
            self.engine.currentTime = 0
            self.engine.play()
            self.running = True

    def rev(self, world_: World, on: bool) -> None:
        if not on and self.running:
            self.engine.pause()
            self.running = False
        if self.running:
            self.engine.playbackRate = engine_rate(world_.speed, world_.throttle, world_.boost > 0)
            self.engine.volume = 0.6 if in_tunnel(world_.s) else 0.45   # トンネルの中は反響で大きく


screen = CanvasScreen(WIDTH * SCALE, HEIGHT * SCALE)
speaker = Speaker()
world = World(seed=int(window.performance.now()))
best = Best.parse(window.localStorage.getItem(SAVED) or "")
improved = False
frames = []


def refresh() -> None:
    draw(screen, world)
    screen.flush()
    time_label.textContent = clock_text(world.total())
    ring_label.textContent = f"{world.next}/{GATES}"
    miss_label.textContent = str(world.misses)
    low_label.textContent = f"{world.low_total:.1f}"
    section_label.textContent = world.section()
    combo_label.textContent = str(world.combo)
    speed_label.textContent = f"{world.speed:.0f}"
    alt_label.textContent = f"{world.altitude():.0f}"
    heading_label.textContent = f"{int((math.degrees(world.frame.heading()) + 360) % 360):03d}"
    best_label.textContent = clock_text(best.of(world.course)) if best.of(world.course) else "--:--.--"
    course_label.textContent = world.course + (f"（種 {COURSE_SEED}）" if world.course == "ランダム" else "")
    for button in course_buttons:
        button.classList.toggle("go", button.getAttribute("data-course") == world.course)
        button.disabled = world.started
    if not world.started:
        note = ""
    elif world.clock < 0:
        note = f"{int(-world.clock) + 1}"
    else:
        note = world.note if world.clock < world.note_until else ""
    note_label.textContent = note or " "
    if world.finished_at is not None:
        message.textContent = (f"ゴール！ {clock_text(world.finished_at)}（外した {world.misses}、ぶつかった {world.bumps}）"
                               + ("  ベスト更新！" if improved else ""))
    elif not world.started:
        message.textContent = "コースを選んで「スタート」。← → で傾けて曲がる、↑ ↓ で機首、▲ ▼ でスロットル。峡谷を縫って橙の輪をくぐる。外しても +3 秒で続行"
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
                improved = best.take(world.course, world.finished_at)
                window.localStorage.setItem(SAVED, best.dump())
                event = "best" if improved else event
            speaker.say(event)
            lag -= STEP
        speaker.rev(world, world.started and sound_on.checked)
        refresh()
        frames.append(window.performance.now() / 1000)
        del frames[:-30]
        if len(frames) >= 2:
            fps_label.textContent = f"{(len(frames) - 1) / (frames[-1] - frames[0]):.0f}"
        spent = window.performance.now() / 1000 - now
        await asyncio.sleep(max(0.002, STEP - spent))


KEYS = {"ArrowLeft": "left", "ArrowRight": "right", "ArrowUp": "up", "ArrowDown": "down",
        "a": "left", "d": "right", "w": "faster", "s": "slower", " ": "go", "Enter": "go"}


def wake_sound() -> None:
    if world.started and sound_on.checked:
        speaker.start_engine()


@when("keydown", "body")
def on_down(event):
    key = KEYS.get(event.key)
    if key is not None:
        event.preventDefault()
        if event.repeat:
            return
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
    if world.course == "ランダム":                     # ランダムは毎回違う地形
        load_course("ランダム", int(window.performance.now()) % 10000)
    world = World(seed=int(window.performance.now()))
    world.started = True
    improved = False
    wake_sound()
    refresh()


@when("click", ".courses button")
def choose_course(event):
    global world
    if world.started:
        return
    name = event.target.getAttribute("data-course")
    message.textContent = f"{name} を作っています…"
    load_course(name, int(window.performance.now()) % 10000)   # 地図の作り直し（1〜2 秒）
    world = World(seed=int(window.performance.now()))
    refresh()


document.querySelector("#loading").hidden = True
refresh()
asyncio.ensure_future(loop())
