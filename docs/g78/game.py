"""ワープ・トンネルブラウザ版

CLI 版（g78-space-3d/main.py）と中身はまったく同じ。3D の点（V）も、回転（rotate）も、
透視投影（project）も、面を塗る Screen.fill も、隠面消去と陰影（draw_solid）も、
世界（World）も、キーを受ける obey も 1 文字も変えていない。

違うのは入口と出口だけ。
  入口: 端末はキーの並び、ブラウザは keydown / keyup とボタン、画面をなぞる
  出口: 端末は ▀ の並び（自分で書いた 3D）、ブラウザは同じ世界を Three.js の Mesh に写して GPU に描かせる（2026-09-18 に Three.js 化）
        カメラの位置・傾き・揺れ・画角は CLI 版の cam_now / focus をそのまま使う。星雲・ブルーム・粒は Three.js
  時計: 端末は time.perf_counter()、ブラウザは performance.now()。刻み幅は同じ STEP
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

from pyodide.ffi import create_proxy, to_js
from pyscript import document, when, window
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


HIT_GAP = 0.55                                      # 小惑星の縁からこれより近いとぶつかる


GRAZE_GAP = 0.5                                     # ぶつかる境目からこれ以内なら「スレスレ」（+3、コンボが伸びる）


NEAR_GAP = 1.2                                      # これ以内なら「近い」（+2、コンボが伸びる）。それより遠くは +1


COMBO_MAX = 5                                       # コンボの倍率の上限


SHAKE_HIT = 0.45                                    # ぶつかったときに揺れる秒数


SHAKE_GRAZE = 0.12                                  # スレスレのときに軽く揺れる秒数


SHAKE_AMP = 0.35                                    # 揺れの大きさ（世界の単位）


SPEED0 = 10.0                                       # 始めの速さ


SPEED_MAX = 34.0                                    # 速さの上限


WIDE = 0.3                                          # 速さが上限のとき、焦点距離をこの割合だけ縮める（広角になる）


STREAK = 3.0                                        # 星の流線の長さ（何コマぶんの動きを線にするか）


GATE_EVERY = 10                                     # よけた数がこれに達するたびにゲートが来る


GATE_R = 2.0                                        # ゲートの半径。中心からこれ以内を通れば通過


GATE_SPEED = 1.5                                    # ゲートを通ると速さがこれだけ上がる（ステージが 1 つ進む）


LIGHT_DIR = (-0.5, 0.8, -0.6)                       # 光の向き（左上・手前から）


SPACE = (6, 8, 14)                                  # 背景


ROCK = (150, 128, 108)                              # 小惑星の色（明るさは陰影で変わる）


SHIP = (120, 200, 235)                              # 自機


FLAME = (255, 160, 60)                              # 自機の噴射


STAR_NEAR = (240, 240, 250)


STAR_FAR = (90, 95, 120)


RING = (70, 120, 160)                               # トンネルの輪


GLOW = (255, 228, 96)                               # スレスレのとき画面の縁が光る色


BLOOD = (235, 70, 60)                               # ぶつかったときの縁の色


GATE = (110, 230, 150)                              # ゲートの色


ROCK_DANGER = (215, 95, 75)                         # いまの位置のままだとぶつかる小惑星の色


RATE = 22050                                        # 音の標本の数（1 秒あたり）


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
    """出来事の音。pass はよけた（小さく高く）、graze はスレスレ（キラッと 2 音）、
    gate はゲート通過（上がる 3 音）、hit はぶつかった（低く長く）、over はおしまい、
    best はベスト更新（上がっていく 4 音）。"near" は pass と同じ音。"""
    if kind in ("pass", "near"):
        samples = tone(1320, 0.05)
    elif kind == "graze":
        samples = tone(1760, 0.04) + tone(2640, 0.08)
    elif kind == "best":
        samples = tone(523, 0.1) + tone(659, 0.1) + tone(784, 0.1) + tone(1047, 0.3)
    elif kind == "gate":
        samples = tone(660, 0.07) + tone(880, 0.07) + tone(1320, 0.18)
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


EVENTS = ("pass", "near", "graze", "gate", "hit", "over")   # update() が返す出来事。目立つ順


SOUNDS = EVENTS + ("best",)                         # 出来事ごとに音を 1 つ（near は pass と同じ音）＋ ベスト更新


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
    """視点。横の位置と、傾き（ロール）、揺れ。自機を追いかけ、曲がると傾き、ぶつかると揺れる。"""

    x: float = 0.0
    roll: float = 0.0
    jolt_x: float = 0.0                             # 揺れ（カメラそのものがずれる。近いものほど大きく揺れて見える）
    jolt_y: float = 0.0


def view(p: V, cam: Camera = Camera()) -> V:
    """世界の点を「カメラから見た点」にする。

    カメラの位置を引いてから、カメラの傾きのぶん逆に回す。カメラが右に傾けば
    世界は左に傾いて見える。視点は EYE の高さで、まっすぐ前を見ている。
    """
    q = V(p.x - cam.x - cam.jolt_x, p.y - EYE - cam.jolt_y, p.z)
    return rotate(q, 0, 0, -cam.roll)


def project(p: V, scale: float = 1.0, focus: float = FOCUS) -> tuple[float, float]:
    """透視投影。遠い（z が大きい）ほど真ん中に寄って小さくなる。ここが 3D の心臓。

    受け取るのは「カメラから見た点」（view を通したもの）。
    scale は板の大きさ（ブラウザは 2 倍の板に描くので 2）。式は変わらず、全部が 2 倍になるだけ。
    focus は焦点距離。小さいほど広角（同じ点が真ん中寄りに映り、手前のものが流れて見える）。
    """
    return (CX + focus * p.x / p.z) * scale, (CY - focus * p.y / p.z) * scale


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

    def frame(self, thick: int, color: tuple[int, int, int]) -> None:
        """画面の縁を太さ thick で塗る（光る演出）。"""
        paint = bytes(color)
        for y in range(self.height):
            if y < thick or y >= self.height - thick:
                self.rows[y][:] = paint * self.width
            else:
                self.rows[y][:thick * 3] = paint * thick
                self.rows[y][-thick * 3:] = paint * thick

    def line(self, a: tuple[float, float], b: tuple[float, float], color: tuple[int, int, int]) -> None:
        """2 点を結ぶ線。長い方の軸に沿って 1 ドットずつ置く。"""
        (x1, y1), (x2, y2) = a, b
        steps = int(max(abs(x2 - x1), abs(y2 - y1))) + 1
        for i in range(steps + 1):
            t = i / steps
            self.plot(int(x1 + (x2 - x1) * t), int(y1 + (y2 - y1) * t), color)

    def pixel(self, x: int, y: int) -> tuple[int, int, int]:
        return tuple(self.rows[y][x * 3:x * 3 + 3])


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
               color: tuple[int, int, int], focus: float = FOCUS) -> None:
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
        drawn.append((depth, [project(points[i], scale, focus) for i in face], shade(color, normal, depth)))
    for _, flat, painted in sorted(drawn, key=lambda item: -item[0]):   # 奥から
        screen.fill(flat, painted)


@dataclass
class Rock:
    pos: V
    radius: float
    seed: int
    spin: V                                         # 回る速さ（軸ごと）
    angle: V = V(0, 0, 0)
    passed: bool = False


@dataclass
class Gate:
    """ゲート。中を通れば ♥ が 1 つ戻り、ステージが 1 つ進む。"""

    pos: V
    passed: bool = False


@dataclass
class Best:
    """これまでのベスト。端末は records.json、ブラウザは localStorage に置くが、中身の形（dump）は同じ。"""

    score: int = 0
    combo: int = 0                                  # 最高コンボ
    passed: int = 0                                 # 最多よけた数

    def dump(self) -> str:
        return json.dumps({"score": self.score, "combo": self.combo, "passed": self.passed})

    @classmethod
    def parse(cls, text: str) -> "Best":
        """壊れていたり空だったりしたら 0 から。"""
        try:
            data = json.loads(text)
            return cls(int(data["score"]), int(data["combo"]), int(data["passed"]))
        except (ValueError, KeyError, TypeError):
            return cls()

    def take(self, world: "World") -> bool:
        """終わった世界の成績を取り込む。点のベストを更新したら True。"""
        improved = world.score > self.score
        self.score = max(self.score, world.score)
        self.combo = max(self.combo, world.combo_max)
        self.passed = max(self.passed, world.passed)
        return improved


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
    speed: float = SPEED0                           # 前へ進む速さ
    started: bool = False                           # スタート前は宇宙が流れているだけ
    paused: bool = False
    time: float = 0.0
    spawn_at: float = 0.0
    score: int = 0                                  # 点。スレスレ +3、近い +2、それ以外 +1 に、コンボの倍率をかける
    passed: int = 0                                 # よけた数（速さはこれで決まる）
    combo: int = 0                                  # スレスレ・近いが続いた数。ぶつかるか、遠くをよけると 0 に戻る
    combo_max: int = 0
    lives: int = 3
    hurt: float = 0.0                               # ぶつかった直後（点滅）
    stage: int = 1                                  # ゲートを通るたびに 1 つ進む。小惑星の出方が増える
    gate: Gate | None = None                        # いま来ているゲート
    since_gate: int = 0                             # 前のゲートからよけた数。GATE_EVERY で次のゲート
    shake: float = 0.0                              # 揺れの残り秒数
    flash: float = 0.0                              # 画面の縁が光る残り秒数
    flash_color: tuple[int, int, int] = GLOW
    note: str = ""                                  # 直近の出来事の言葉（「スレスレ！ +6」など）
    note_until: float = 0.0
    over: bool = False

    def __post_init__(self):
        self.luck = random.Random(self.seed)
        self.stars = [self.new_star(self.luck.uniform(NEAR + 1, FAR)) for _ in range(90)]
        self.rings = [float(z) for z in range(int(RING_GAP), int(FAR), int(RING_GAP))]

    def new_star(self, z: float) -> V:
        return V(self.luck.uniform(-24, 24), self.luck.uniform(-16, 16), z)

    def new_rock(self, pos: V | None = None, radius: float | None = None) -> Rock:
        """小惑星を 1 つ。場所と大きさは指定がなければ、動ける範囲の中でランダム。"""
        if pos is None:
            pos = V(self.luck.uniform(-REACH_X, REACH_X), self.luck.uniform(*REACH_Y), FAR)
        if radius is None:
            radius = self.luck.uniform(0.7, 1.6)
        return Rock(pos, radius, self.luck.randrange(1 << 30),
                    V(self.luck.uniform(-1.2, 1.2), self.luck.uniform(-1.2, 1.2), self.luck.uniform(-0.6, 0.6)))

    def gap(self, rock: Rock) -> float:
        """小惑星の「ぶつかる境目（縁 + HIT_GAP）」から自機までの余り。負ならぶつかっている。"""
        return math.dist((rock.pos.x, rock.pos.y), (self.ship.x, self.ship.y)) - rock.radius - HIT_GAP

    def judge(self, rock: Rock) -> str:
        """自機の横を通り過ぎた小惑星との近さで、出来事を決める。
        余りが GRAZE_GAP 以内なら graze、NEAR_GAP 以内なら near。"""
        gap = self.gap(rock)
        if gap < 0:
            return "hit"
        if gap < GRAZE_GAP:
            return "graze"
        if gap < NEAR_GAP:
            return "near"
        return "pass"

    def reward(self, event: str) -> int:
        """よけた点。スレスレ・近いはコンボを伸ばし、点にコンボの倍率がかかる。遠くをよけると +1 でコンボは途切れる。"""
        if event in ("graze", "near"):
            self.combo += 1
            self.combo_max = max(self.combo_max, self.combo)
            points = {"graze": 3, "near": 2}[event] * min(self.combo, COMBO_MAX)
        else:
            self.combo = 0
            points = 1
        self.score += points
        self.passed += 1
        self.since_gate += 1
        self.speed = min(SPEED_MAX, self.speed + 0.35)
        return points

    def tell(self, text: str) -> None:
        self.note = text
        self.note_until = self.time + 1.2

    @property
    def focus(self) -> float:
        """速いほど広角に（焦点距離を縮める）。速さの実感はここから来る。"""
        return FOCUS * (1 - WIDE * (self.speed - SPEED0) / (SPEED_MAX - SPEED0))

    def dangerous(self, rock: Rock) -> bool:
        """自機がいまの位置のままだと、この小惑星にぶつかるか。"""
        return not rock.passed and rock.pos.z > self.ship.z and self.gap(rock) < 0

    @property
    def cam_now(self) -> Camera:
        """揺れを足したカメラ。揺れは時間から決まる（乱数を使わないので端末とブラウザで同じ）。"""
        if self.shake <= 0:
            return self.cam
        amp = SHAKE_AMP * min(1.0, self.shake / 0.3)   # 終わりに向けて小さく
        return self.cam._replace(jolt_x=amp * math.sin(self.time * 71),
                                 jolt_y=amp * 0.7 * math.cos(self.time * 53))

    def update(self, dt: float) -> str | None:
        """1 コマ進める。起きたこと（EVENTS のどれか）を返す。
        スタート前は宇宙（星・輪）だけが流れ、自機は動かせるが小惑星は出ない。一時停止中は何も動かない。"""
        if self.over or self.paused:
            return None
        if self.started:                            # 時計はスタートしてから進む（出す間隔が時間で決まるので）
            self.time += dt
        self.hurt = max(0.0, self.hurt - dt)
        self.shake = max(0.0, self.shake - dt)
        self.flash = max(0.0, self.flash - dt)
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
        if not self.started:
            return None
        # 出す：ゲートの番なら ゲート、そうでなければ ステージに応じた並びの小惑星
        happened = None
        if self.time >= self.spawn_at:
            if self.gate is None and self.since_gate >= GATE_EVERY:
                self.gate = Gate(V(self.luck.uniform(-REACH_X + GATE_R * 0.6, REACH_X - GATE_R * 0.6),
                                   self.luck.uniform(0.2, 2.0), FAR))
                self.spawn_at = self.time + 0.8     # 通ったあとも少し休み
            elif self.gate is not None and not self.gate.passed:
                pass                                # ゲートが来る間は小惑星を出さない（ひと息つく）
            else:
                pattern = self.luck.choice(stage_patterns(self.stage))
                self.rocks.extend(PATTERNS[pattern](self))
                self.spawn_at = self.time + max(0.35, 1.1 - self.time * 0.01)
        # ゲート
        if self.gate is not None:
            self.gate.pos = V(self.gate.pos.x, self.gate.pos.y, self.gate.pos.z - self.speed * dt)
            if not self.gate.passed and self.gate.pos.z <= self.ship.z:
                self.gate.passed = True
                self.since_gate = 0
                if math.dist((self.gate.pos.x, self.gate.pos.y), (self.ship.x, self.ship.y)) <= GATE_R:
                    self.stage += 1
                    self.lives = min(3, self.lives + 1)
                    self.speed = min(SPEED_MAX, self.speed + GATE_SPEED)
                    self.flash, self.flash_color = 0.4, GATE
                    self.tell(f"ゲート通過！ ステージ {self.stage}")
                    happened = "gate"
                else:
                    self.tell("ゲートを外した…")
            if self.gate.pos.z <= NEAR:
                self.gate = None
        # 小惑星。同じコマに何個も通り過ぎたら（帯など）、いちばん近い 1 個で決める
        for rock in self.rocks:
            rock.pos = V(rock.pos.x, rock.pos.y, rock.pos.z - self.speed * dt)
            rock.angle = rock.angle + rock.spin.scale(dt)
        passing = [r for r in self.rocks if not r.passed and r.pos.z <= self.ship.z]
        if passing:
            for rock in passing:
                rock.passed = True
            rock = min(passing, key=self.gap)
            event = self.judge(rock)
            if event == "hit" and self.hurt > 0:   # 点滅中（無敵）はぶつからないが、点にもならない
                pass
            elif event == "hit":
                self.lives -= 1
                self.hurt = 1.0
                self.combo = 0
                self.shake = SHAKE_HIT
                self.flash, self.flash_color = SHAKE_HIT, BLOOD
                self.tell("ぶつかった！ コンボ 0")
                happened = "hit"
                if self.lives <= 0:
                    self.over = True
                    happened = "over"
            else:
                points = self.reward(event)
                if event == "graze":
                    self.shake = max(self.shake, SHAKE_GRAZE)
                    self.flash, self.flash_color = 0.25, GLOW
                    self.tell(f"スレスレ！ +{points}" + (f"  ×{min(self.combo, COMBO_MAX)}" if self.combo > 1 else ""))
                elif event == "near":
                    self.tell(f"近い +{points}" + (f"  ×{min(self.combo, COMBO_MAX)}" if self.combo > 1 else ""))
                if happened is None or EVENTS.index(event) > EVENTS.index(happened):
                    happened = event            # 同じコマに 2 つ起きたら、目立つ方（EVENTS の後ろ）を返す
        self.rocks = [r for r in self.rocks if r.pos.z > NEAR]
        return happened


def spawn_one(world: World) -> list[Rock]:
    """1 個。場所も大きさもランダム。"""
    return [world.new_rock()]


def spawn_pair(world: World) -> list[Rock]:
    """左右に 2 個。間を抜けると両方スレスレ。"""
    center = world.luck.uniform(-REACH_X + 1.9, REACH_X - 1.9)
    y = world.luck.uniform(*REACH_Y)
    return [world.new_rock(V(center - 1.9, y, FAR), 0.9), world.new_rock(V(center + 1.9, y, FAR), 0.9)]


def spawn_band(world: World) -> list[Rock]:
    """横一列の帯。1 か所だけ穴が空いている（上下によけてもよい）。"""
    y = world.luck.uniform(*REACH_Y)
    hole = world.luck.randrange(5)
    return [world.new_rock(V(-REACH_X + 2.1 * i, y, FAR), 0.8) for i in range(5) if i != hole]


def spawn_big(world: World) -> list[Rock]:
    """大きいのが 1 個。動ける範囲の半分をふさぐ。"""
    return [world.new_rock(radius=world.luck.uniform(2.0, 2.6))]


PATTERNS = {"one": spawn_one, "pair": spawn_pair, "band": spawn_band, "big": spawn_big}   # 名前 → 出し方


STAGE_ORDER = ("one", "pair", "band", "big")        # ステージが進むと、この順に出方が増える


def stage_patterns(stage: int) -> tuple[str, ...]:
    """そのステージで出る出方。ステージ 1 は 1 個だけ、2 で左右、3 で帯、4 で大きいの。"""
    return STAGE_ORDER[:max(1, min(stage, len(STAGE_ORDER)))]


def draw_gate(screen: Screen, gate: Gate, cam: Camera, scale: float, focus: float = FOCUS) -> None:
    """ゲート。二重の 24 角形の輪。奥にあるほど霧で薄い。"""
    color = fog(GATE, gate.pos.z * 0.5)             # 目標なので、小惑星より霧に溶けにくくする
    for r in (GATE_R, GATE_R + 0.18):
        corners = [project(view(V(gate.pos.x + r * math.cos(a), gate.pos.y + r * math.sin(a), gate.pos.z), cam), scale, focus)
                   for a in (i * math.tau / 24 for i in range(24))]
        for i in range(24):
            screen.line(corners[i], corners[(i + 1) % 24], color)


def draw(screen: Screen, world: World) -> None:
    """場面を描く。星 → 小惑星（奥から）→ 自機。"""
    screen.clear(SPACE)
    cam = world.cam_now                             # 揺れ込み
    scale = screen.width / WIDTH
    focus = world.focus                             # 速いほど広角
    for star in world.stars:                        # 星。前のコマの位置から線を引く（流線）。近く・速いほど長い
        sx, sy = project(view(star, cam), scale, focus)
        back = star.z + world.speed * STEP * STREAK
        bx, by = project(view(V(star.x, star.y, back), cam), scale, focus)
        near = 1 - star.z / FAR
        color = tuple(int(f + (n - f) * near) for f, n in zip(STAR_FAR, STAR_NEAR))
        screen.line((bx, by), (sx, sy), tuple(c // 2 for c in color))
        screen.plot(int(sx), int(sy), color)
    for z in sorted(world.rings, reverse=True):     # 輪。奥から。16 角形の線
        color = fog(RING, z)
        corners = [project(view(V(RING_R * math.cos(a), RING_Y + RING_R * math.sin(a), z), cam), scale, focus)
                   for a in (i * math.tau / 16 for i in range(16))]
        for i in range(16):
            screen.line(corners[i], corners[(i + 1) % 16], color)
    gate_z = world.gate.pos.z if world.gate is not None else -1.0
    for rock in sorted(world.rocks, key=lambda r: -r.pos.z):
        if world.gate is not None and rock.pos.z < gate_z < FAR:   # ゲートより手前の小惑星の前に、ゲートを描く
            draw_gate(screen, world.gate, cam, scale, focus)
            gate_z = FAR
        points, faces = rock_shape(rock.seed)
        placed = [view(rotate(p, *rock.angle).scale(rock.radius) + rock.pos, cam) for p in points]
        draw_solid(screen, placed, faces, ROCK_DANGER if world.dangerous(rock) else ROCK, focus)   # 危ないのは赤み
    if world.gate is not None and gate_z < FAR:
        draw_gate(screen, world.gate, cam, scale, focus)
    if world.over or int(world.hurt * 12) % 2 == 0:  # ぶつかった直後は点滅
        tilt = -world.aim.x * 0.5                   # 曲がる向きに機体を傾ける
        placed = [view(rotate(p, 0.1, 0, tilt).scale(0.9) + world.ship, cam) for p in SHIP_POINTS]
        draw_solid(screen, placed, SHIP_FACES, SHIP, focus)
        tail = view(rotate(V(0, 0, -0.8), 0.1, 0, tilt).scale(0.9) + world.ship, cam)
        fx, fy = project(tail, scale, focus)
        screen.plot(int(fx), int(fy), FLAME)
        screen.plot(int(fx), int(fy) + 1, FLAME)
    if world.flash > 0:                             # 画面の縁が光る（スレスレは黄、ぶつかったら赤）
        screen.frame(int(scale), world.flash_color)


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
    elif key == "go" and down:                      # 1 つのキーで「始める」と「止める／つづける」
        if not world.started:
            world.started = True
        elif not world.over:
            world.paused = not world.paused
# --- ここから下はブラウザ版だけ。CLI 版の run() / Screen.render() / Speaker にあたる ---
#   2026-09-18 に Three.js 化。世界（World）・回転・透視投影・当たり判定は 1 文字も変えず、
#   端末が ▀ に描くところを、ここでは同じ世界の物を Three.js の Mesh に写して GPU に描かせる。
#   カメラの位置・傾き・揺れ・画角（speed で広角になる）も CLI 版の cam_now / focus から。
#   同日の 3 回目：宇宙のキューブマップ（環境と背景）、岩と自機のテクスチャと法線マップ、ステージで変わる光、
#   ワープのトンネル（自分で書いたシェーダ）、GPU で動く粒（頂点シェーダが位置を計算）、被写界深度・残像・フィルムの粒子

THREE = window.THREE
ADDONS = window.ADDONS
TONE = getattr(window, "Tone", None)                # 音（エンジンの持続音・スレスレ・ゲート・衝突）。無ければ wav だけ
VIEW_W, VIEW_H = 640, 400


def js(**kw):
    return to_js(kw, dict_converter=window.Object.fromEntries)


def rgb(color: tuple[int, int, int]) -> int:
    r, g, b = color
    return (r << 16) | (g << 8) | b


def linear(c: int) -> float:
    return (c / 255) ** 2.2


canvas = document.querySelector("#screen")
score_label = document.querySelector("#score")
passed_label = document.querySelector("#passed")
combo_label = document.querySelector("#combo")
note_label = document.querySelector("#note")
best_label = document.querySelector("#best")
stage_label = document.querySelector("#stage")
gate_label = document.querySelector("#gate")
SAVED = "g78-best"                                  # localStorage の鍵。CLI 版の records.json にあたる
lives_label = document.querySelector("#lives")
speed_label = document.querySelector("#speed")
fps_label = document.querySelector("#fps")
message = document.querySelector("#message")
again_button = document.querySelector("#again")
go_button = document.querySelector("#go")

# ── Three.js の舞台 ──────────────────────────────────────────────────────

renderer = THREE.WebGLRenderer.new(js(canvas=canvas, antialias=True))
PIXEL_RATIO = min(2.0, window.devicePixelRatio)
renderer.setPixelRatio(PIXEL_RATIO)
renderer.setSize(VIEW_W, VIEW_H, False)
renderer.toneMapping = THREE.ACESFilmicToneMapping
renderer.shadowMap.enabled = True                   # 岩どうし・自機の影
renderer.shadowMap.type = THREE.PCFSoftShadowMap
scene = THREE.Scene.new()
scene.background = THREE.Color.new(rgb(SPACE))
scene.fog = THREE.FogExp2.new(rgb(SPACE), 0.028)   # CLI 版の fog（FOG_FROM より奥は背景に溶ける）にあたる
camera = THREE.PerspectiveCamera.new(2 * math.degrees(math.atan(CY / FOCUS)), VIEW_W / VIEW_H, 0.3, 300)
pmrem = THREE.PMREMGenerator.new(renderer)

# 後処理の並び：描く → 被写界深度（遠くがぼける）→ 残像（速さの尾）→ ブルーム → 色収差 → 周辺減光 → フィルムの粒子 → 出力
composer = ADDONS.EffectComposer.new(renderer)
composer.setPixelRatio(PIXEL_RATIO)
composer.setSize(VIEW_W, VIEW_H)
composer.addPass(ADDONS.RenderPass.new(scene, camera))
bokeh = ADDONS.BokehPass.new(scene, camera, js(focus=SHIP_Z + 1.0, aperture=0.00012, maxblur=0.006))
composer.addPass(bokeh)
afterimage = ADDONS.AfterimagePass.new(0.55)        # 残像：速いほど強く（モーションブラー風）
composer.addPass(afterimage)
bloom = ADDONS.UnrealBloomPass.new(THREE.Vector2.new(VIEW_W, VIEW_H), 0.45, 0.6, 0.85)   # 光る物（輪・ゲート・噴射）がにじむ
composer.addPass(bloom)
shift = ADDONS.ShaderPass.new(ADDONS.RGBShiftShader)   # 色収差：速いほど画面の端で色がずれる（レンズの歪みの感じ）
shift.uniforms.amount.value = 0.0
composer.addPass(shift)
vignette_pass = ADDONS.ShaderPass.new(ADDONS.VignetteShader)   # 周辺減光：速いほど端が暗く、視野が狭まる
vignette_pass.uniforms.offset.value = 1.1
vignette_pass.uniforms.darkness.value = 1.0      # darkness は 1 以上（1 未満だと端が「灰色」に向かって画面全体が白く濁る）
composer.addPass(vignette_pass)
film = ADDONS.FilmPass.new(0.12, False)             # フィルムの粒子（映画っぽさ）
composer.addPass(film)
composer.addPass(ADDONS.OutputPass.new())

sun = THREE.DirectionalLight.new(0xfff4e6, 2.4)     # 主光：ステージで向きが変わる（惑星の側から）
sun.position.set(LIGHT_DIR[0] * 30, LIGHT_DIR[1] * 30, LIGHT_DIR[2] * 30)
sun.castShadow = True
sun.shadow.mapSize.set(1024, 1024)
for name, value in (("left", -14), ("right", 14), ("top", 10), ("bottom", -8), ("near", 1), ("far", 120)):
    setattr(sun.shadow.camera, name, value)
sun.shadow.bias = -0.0006
scene.add(sun)
scene.add(sun.target)
ambient = THREE.AmbientLight.new(0x30365a, 0.6)
scene.add(ambient)
rim = THREE.DirectionalLight.new(0x5a78ff, 0.9)     # 星雲の照り返し（奥から）。逆光でシルエットが出る
rim.position.set(10, -5, 80)
scene.add(rim)
gate_light = THREE.PointLight.new(rgb(GATE), 0.0, 18.0, 1.5)   # ゲートが周りの岩を緑に照らす
scene.add(gate_light)


# ── 絵を canvas で作る（テクスチャ・法線マップ・キューブマップ） ─────────────────

def noise_canvas(size: int, seed: int, base: int = 128, spread: int = 60, blobs: int = 260) -> object:
    """ざらざらの絵：大小の丸をたくさん重ねた明るさのむら。岩の色と凹凸に使う。"""
    luck = random.Random(seed)
    cv = document.createElement("canvas")
    cv.width = cv.height = size
    ctx = cv.getContext("2d")
    ctx.fillStyle = f"rgb({base},{base},{base})"
    ctx.fillRect(0, 0, size, size)
    for _ in range(blobs):
        v = base + int(luck.uniform(-spread, spread))
        r = luck.uniform(2, size / 6)
        ctx.fillStyle = f"rgba({v},{v},{v},{luck.uniform(0.25, 0.6):.2f})"
        ctx.beginPath()
        ctx.arc(luck.uniform(0, size), luck.uniform(0, size), r, 0, math.tau)
        ctx.fill()
    return cv


def normal_from(cv: object, strength: float = 2.5) -> object:
    """明るさの絵 → 法線マップ。隣との明るさの差（傾き）を色に（x → 赤、y → 緑、青は上向き）。"""
    size = cv.width
    src = cv.getContext("2d").getImageData(0, 0, size, size).data
    out = document.createElement("canvas")
    out.width = out.height = size
    ctx = out.getContext("2d")
    img = ctx.createImageData(size, size)
    data = img.data
    h = [src[i * 4] / 255 for i in range(size * size)]
    pixels = []
    for y in range(size):
        for x in range(size):
            l = h[y * size + (x - 1) % size]
            r = h[y * size + (x + 1) % size]
            u = h[((y - 1) % size) * size + x]
            d = h[((y + 1) % size) * size + x]
            nx, ny, nz = (l - r) * strength, (u - d) * strength, 1.0
            k = 1 / math.sqrt(nx * nx + ny * ny + nz * nz)
            pixels += [int((nx * k * 0.5 + 0.5) * 255), int((ny * k * 0.5 + 0.5) * 255), int((nz * k * 0.5 + 0.5) * 255), 255]
    data.set(to_js(pixels))
    ctx.putImageData(img, 0, 0)
    return out


def texture_of(cv: object, srgb: bool = True, repeat: float = 1.0) -> object:
    tex = THREE.CanvasTexture.new(cv)
    if srgb:
        tex.colorSpace = THREE.SRGBColorSpace
    tex.wrapS = tex.wrapT = THREE.RepeatWrapping
    tex.repeat.set(repeat, repeat)
    return tex


ROCK_NOISE = noise_canvas(128, 3, 118, 70)
ROCK_MAP = texture_of(ROCK_NOISE, True, 2.0)
ROCK_NORMAL = texture_of(normal_from(ROCK_NOISE, 3.0), False, 2.0)


def ship_canvas() -> object:
    """自機の外板：パネルの線と擦り傷。"""
    cv = document.createElement("canvas")
    cv.width = cv.height = 128
    ctx = cv.getContext("2d")
    ctx.fillStyle = "#8fbfe0"
    ctx.fillRect(0, 0, 128, 128)
    luck = random.Random(8)
    ctx.strokeStyle = "rgba(40,60,90,0.6)"
    ctx.lineWidth = 2
    for i in range(6):
        y = 10 + i * 20
        ctx.beginPath()
        ctx.moveTo(0, y)
        ctx.lineTo(128, y)
        ctx.stroke()
    for _ in range(40):
        ctx.strokeStyle = f"rgba(255,255,255,{luck.uniform(0.1, 0.4):.2f})"
        ctx.lineWidth = 1
        x, y = luck.uniform(0, 128), luck.uniform(0, 128)
        ctx.beginPath()
        ctx.moveTo(x, y)
        ctx.lineTo(x + luck.uniform(-14, 14), y + luck.uniform(-3, 3))
        ctx.stroke()
    return cv


SHIP_MAP = texture_of(ship_canvas(), True, 1.0)


def sky_face(seed: int, colors: tuple[int, ...], space: tuple[int, int, int], size: int = 256) -> object:
    """キューブマップの 1 面：暗い宇宙に星雲の光と星。"""
    luck = random.Random(seed)
    cv = document.createElement("canvas")
    cv.width = cv.height = size
    ctx = cv.getContext("2d")
    ctx.fillStyle = f"rgb({space[0]},{space[1]},{space[2]})"
    ctx.fillRect(0, 0, size, size)
    for color in colors:
        for _ in range(3):
            x, y, r = luck.uniform(0, size), luck.uniform(0, size), luck.uniform(size * 0.25, size * 0.7)
            grad = ctx.createRadialGradient(x, y, 0, x, y, r)
            grad.addColorStop(0, f"rgba({(color >> 16) & 255},{(color >> 8) & 255},{color & 255},0.22)")
            grad.addColorStop(1, "rgba(0,0,0,0)")
            ctx.fillStyle = grad
            ctx.fillRect(0, 0, size, size)
    for _ in range(260):
        b = luck.randrange(120, 255)
        ctx.fillStyle = f"rgba({b},{b},{min(255, b + 30)},{luck.uniform(0.5, 1.0):.2f})"
        s = luck.uniform(0.6, 1.8)
        ctx.fillRect(luck.uniform(0, size), luck.uniform(0, size), s, s)
    return cv


# 空間の色はステージで変わる（表 1 行）。星雲の色・背景と霧・惑星・光の向き
THEMES = (
    dict(name="青い星雲", nebula=(0x5a2a9a, 0x1e3c8a, 0x8a2a5a, 0x1a6a7a), space=(6, 8, 14), planet=(0x3a6fc0, 0x8fc0ff, -38, 14), sun=(-0.5, 0.8, -0.6), sun_color=0xfff4e6),
    dict(name="赤い星雲", nebula=(0x9a2a2a, 0x8a3c1e, 0x5a1a4a, 0x7a3a1a), space=(14, 6, 8), planet=(0xc05a3a, 0xffb080, 40, 10), sun=(0.7, 0.4, 0.5), sun_color=0xffc090),
    dict(name="緑のガス", nebula=(0x1a7a3a, 0x2a6a5a, 0x4a7a1a, 0x1a5a4a), space=(5, 12, 9), planet=(0x4aa070, 0xa0ffc0, -30, -8), sun=(-0.6, -0.2, 0.7), sun_color=0xc0ffd0),
    dict(name="暗黒帯", nebula=(0x2a2a3a, 0x1a1a2a, 0x3a2a3a, 0x202030), space=(3, 3, 6), planet=(0x303040, 0x5060a0, 34, -12), sun=(0.6, -0.5, 0.6), sun_color=0x8090ff),
    dict(name="金の星雲", nebula=(0x9a7a1a, 0x8a5a1e, 0x7a4a2a, 0x6a6a1a), space=(12, 10, 4), planet=(0xd0a040, 0xfff0b0, -42, 6), sun=(-0.7, 0.6, 0.3), sun_color=0xffe8b0),
)
SKIES: dict[int, object] = {}                       # ステージの番号 → キューブマップ（作るのは最初の 1 回）
ENVS: dict[int, object] = {}


def sky_for(index: int) -> tuple[object, object]:
    if index not in SKIES:
        theme = THEMES[index]
        faces = [sky_face(index * 10 + k, theme["nebula"], theme["space"]) for k in range(6)]
        cube = THREE.CubeTexture.new(to_js(faces))
        cube.colorSpace = THREE.SRGBColorSpace
        cube.needsUpdate = True
        SKIES[index] = cube
        ENVS[index] = pmrem.fromCubemap(cube).texture
    return SKIES[index], ENVS[index]


planet = THREE.Mesh.new(THREE.SphereGeometry.new(9.8, 32, 24),   # 大きさは 70%（14 → 9.8）
                        THREE.MeshStandardMaterial.new(js(color=0x3a6fc0, roughness=0.8, fog=False, emissive=0x3a6fc0, emissiveIntensity=0.8)))   # 影の側も見えるよう自分で光る
planet.position.set(-38, 14, 110)
scene.add(planet)
GLOW_TEX = None


def glow_texture(inner: str, outer: str = "rgba(0,0,0,0)") -> object:
    """真ん中が明るく縁が透ける丸（canvas）。噴射・粒に使う。"""
    cv = document.createElement("canvas")
    cv.width = cv.height = 128
    ctx = cv.getContext("2d")
    grad = ctx.createRadialGradient(64, 64, 0, 64, 64, 64)
    grad.addColorStop(0.0, inner)
    grad.addColorStop(1.0, outer)
    ctx.fillStyle = grad
    ctx.fillRect(0, 0, 128, 128)
    tex = THREE.CanvasTexture.new(cv)
    tex.colorSpace = THREE.SRGBColorSpace
    return tex


planet_glow = THREE.Sprite.new(THREE.SpriteMaterial.new(js(map=glow_texture("rgba(255,255,255,0.9)"), color=0x8fc0ff, transparent=True, opacity=0.7, blending=THREE.AdditiveBlending, depthWrite=False, fog=False)))
planet_glow.scale.set(28, 28, 1)
planet_glow.position.copy(planet.position)
scene.add(planet_glow)


def apply_theme(stage: int) -> None:
    index = (stage - 1) % len(THEMES)
    theme = THEMES[index]
    sky, env = sky_for(index)
    scene.background = sky                          # 宇宙そのものが背景に
    scene.environment = env                         # 自機の金属や輪に宇宙が映る
    scene.environmentIntensity = 0.3
    scene.fog.color.setHex(rgb(theme["space"]))
    body, glow, px, py = theme["planet"]
    planet.material.color.setHex(body)
    planet.material.emissive.setHex(body)
    planet_glow.material.color.setHex(glow)
    planet.position.set(px, py, 110)
    planet_glow.position.set(px, py, 108)
    sx, sy, sz = theme["sun"]
    sun.position.set(sx * 30, sy * 30, sz * 30)
    sun.color.setHex(theme["sun_color"])
    rim.position.set(px * 0.3, py * 0.3, 80)         # 惑星の側からの逆光


STREAKS = len(World().stars)                        # 近くの星：CLI 版と同じ 90 個を、流線として線で描く
streak_geo = THREE.BufferGeometry.new()
streak_geo.setAttribute("position", THREE.Float32BufferAttribute.new(to_js([0.0] * (STREAKS * 6)), 3))
streak_geo.setAttribute("color", THREE.Float32BufferAttribute.new(to_js([1.0] * (STREAKS * 6)), 3))
streaks = THREE.LineSegments.new(streak_geo, THREE.LineBasicMaterial.new(js(vertexColors=True, transparent=True, opacity=0.9)))
scene.add(streaks)

RING_GEO = THREE.TorusGeometry.new(RING_R, 0.09, 8, 48)
RING_MAT = THREE.MeshStandardMaterial.new(js(color=rgb(RING), emissive=rgb(RING), emissiveIntensity=1.6, roughness=0.25, metalness=0.6))
rings = []                                          # トンネルの輪（使い回し 10 本）
for _ in range(10):
    m = THREE.Mesh.new(RING_GEO, RING_MAT)
    m.visible = False
    scene.add(m)
    rings.append(m)

# ワープのトンネル：自分で書いたシェーダ。光の帯が時間に沿って奥から手前へ流れ、ゲートを通ると（uWarp）伸びて強く光る
TUNNEL_VERT = """
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
"""
TUNNEL_FRAG = """
uniform float uTime;
uniform float uSpeed;
uniform float uWarp;
uniform vec3 uColorA;
uniform vec3 uColorB;
varying vec2 vUv;
void main() {
  float flow = vUv.y * (18.0 - 10.0 * uWarp) - uTime * (1.5 + 4.0 * uSpeed + 6.0 * uWarp);   // 帯の位相：速いほど速く流れる
  float band = smoothstep(0.82 - 0.4 * uWarp, 1.0, fract(flow));                             // 細い帯（ワープ中は太く）
  float lane = 0.5 + 0.5 * sin(vUv.x * 6.2831 * 6.0 + uTime * 0.7);                           // 周りで 6 本の筋
  float fade = smoothstep(0.0, 0.25, vUv.y) * (1.0 - smoothstep(0.7, 1.0, vUv.y));         // 手前と奥は薄く
  float a = band * (0.35 + 0.65 * lane) * fade * (0.08 + 0.16 * uSpeed + 0.45 * uWarp);
  vec3 color = mix(uColorA, uColorB, vUv.x);
  gl_FragColor = vec4(color * (1.0 + 2.0 * uWarp), a);
}
"""
tunnel_mat = THREE.ShaderMaterial.new(js(
    vertexShader=TUNNEL_VERT, fragmentShader=TUNNEL_FRAG, transparent=True, depthWrite=False, side=THREE.BackSide, blending=THREE.AdditiveBlending,
    uniforms=js(uTime=js(value=0.0), uSpeed=js(value=0.0), uWarp=js(value=0.0), uColorA=js(value=THREE.Color.new(0x40a0ff)), uColorB=js(value=THREE.Color.new(0xb060ff)))))
tunnel = THREE.Mesh.new(THREE.CylinderGeometry.new(RING_R + 0.4, RING_R + 0.4, FAR, 48, 1, True), tunnel_mat)
tunnel.rotation.x = math.pi / 2
tunnel.position.set(0, RING_Y, FAR / 2)
scene.add(tunnel)

gate_mesh = THREE.Mesh.new(THREE.TorusGeometry.new(GATE_R, 0.14, 10, 48),
                           THREE.MeshStandardMaterial.new(js(color=rgb(GATE), emissive=rgb(GATE), emissiveIntensity=2.2, roughness=0.3)))
gate_mesh.visible = False
scene.add(gate_mesh)
gate_core = THREE.Mesh.new(THREE.CircleGeometry.new(GATE_R - 0.15, 32),
                           THREE.MeshBasicMaterial.new(js(color=rgb(GATE), transparent=True, opacity=0.18, side=THREE.DoubleSide, depthWrite=False)))
gate_core.visible = False
scene.add(gate_core)


def rock_geometry(seed: int, detail: int = 2) -> object:
    """でこぼこの岩。正二十面体の頂点を種で決めた量だけずらし（CLI 版の rock_shape と同じ考え）、
    クレーターは 3 か所を内側へ凹ませる。色は頂点ごとにまだら（暗い斑）。"""
    geo = THREE.IcosahedronGeometry.new(1.0, detail)
    attr = geo.attributes.position
    arr = attr.array
    luck = random.Random(seed)
    craters = [(luck.uniform(-1, 1), luck.uniform(-1, 1), luck.uniform(-1, 1)) for _ in range(3)]
    flat, colors = [], []
    for i in range(0, attr.count * 3, 3):
        x, y, z = arr[i], arr[i + 1], arr[i + 2]
        key = (round(x, 3), round(y, 3), round(z, 3))
        k = 0.78 + 0.4 * random.Random(hash(key) ^ seed).random()
        for cx, cy, cz in craters:                  # クレーターの近くは凹む
            d = math.sqrt((x - cx) ** 2 + (y - cy) ** 2 + (z - cz) ** 2)
            if d < 0.9:
                k -= 0.18 * (1 - d / 0.9)
        flat += [x * k, y * k, z * k]
        tone_ = 0.75 + 0.25 * random.Random(hash(key) ^ (seed * 7 + 3)).random()
        colors += [tone_, tone_ * (0.96 if k < 0.85 else 1.0), tone_ * 0.92]
    arr.set(to_js(flat))
    attr.needsUpdate = True
    geo.setAttribute("color", THREE.Float32BufferAttribute.new(to_js(colors), 3))
    geo.computeVertexNormals()
    return geo


ROCK_GEOS = [rock_geometry(n) for n in range(6)]
ROCK_MAT = THREE.MeshStandardMaterial.new(js(color=rgb(ROCK), roughness=0.95, metalness=0.05, vertexColors=True, emissive=0x000000,
                                            map=ROCK_MAP, normalMap=ROCK_NORMAL, normalScale=THREE.Vector2.new(1.2, 1.2)))
DANGER_MAT = THREE.MeshStandardMaterial.new(js(color=rgb(ROCK_DANGER), roughness=0.9, metalness=0.05, vertexColors=True,
                                              map=ROCK_MAP, normalMap=ROCK_NORMAL, normalScale=THREE.Vector2.new(1.2, 1.2),
                                              emissive=rgb(ROCK_DANGER), emissiveIntensity=0.5))
GLINT_MAT = THREE.MeshStandardMaterial.new(js(color=rgb(ROCK), roughness=0.5, metalness=0.2, vertexColors=True,
                                             map=ROCK_MAP, normalMap=ROCK_NORMAL, emissive=rgb(GLOW), emissiveIntensity=1.2))
rock_meshes: dict[int, object] = {}                 # id(rock) → Mesh
glint_until: dict[int, float] = {}                  # スレスレで表面が光る岩 → 消える時刻
back_rocks = []                                     # 奥の層：大きな岩がゆっくり流れる
back_luck = random.Random(31)
for i in range(12):
    m = THREE.Mesh.new(ROCK_GEOS[i % 6], ROCK_MAT)
    r = back_luck.uniform(3, 7)
    m.scale.set(r, r, r)
    m.position.set(back_luck.uniform(-45, 45), back_luck.uniform(-20, 25), back_luck.uniform(40, 95))
    scene.add(m)
    back_rocks.append(m)
DEBRIS_GEO = THREE.IcosahedronGeometry.new(0.18, 0)
debris = []                                         # ぶつかって砕けた破片 [mesh, vx, vy, vz, life, spin]
debris_pool = []
for _ in range(16):
    m = THREE.Mesh.new(DEBRIS_GEO, ROCK_MAT)
    m.visible = False
    m.castShadow = True
    scene.add(m)
    debris_pool.append(m)


def shatter(x: float, y: float, z: float, radius: float) -> None:
    """岩が砕ける：破片 8 個が回転しながら散る。"""
    for m in debris_pool:
        if m.visible:
            continue
        if len([d for d in debris]) >= 8:
            break
        a = fx_luck.uniform(0, math.tau)
        s = fx_luck.uniform(2, 6)
        m.visible = True
        k = radius * fx_luck.uniform(0.5, 1.2)
        m.scale.set(k, k, k)
        m.position.set(x + fx_luck.uniform(-0.3, 0.3), y + fx_luck.uniform(-0.3, 0.3), z)
        debris.append([m, math.cos(a) * s, math.sin(a) * s, fx_luck.uniform(2, 5), 1.3, fx_luck.uniform(4, 12)])


def make_ship() -> object:
    """自機：CLI 版の SHIP_POINTS と同じ「先のとがった機体」。円錐の胴＋薄い翼＋噴射の玉。外板はテクスチャ。"""
    group = THREE.Group.new()
    body_mat = THREE.MeshStandardMaterial.new(js(color=0xffffff, map=SHIP_MAP, roughness=0.35, metalness=0.75))
    body = THREE.Mesh.new(THREE.ConeGeometry.new(0.28, 1.7, 12), body_mat)
    body.rotation.x = math.pi / 2
    body.castShadow = True
    group.add(body)
    wing = THREE.Mesh.new(THREE.BoxGeometry.new(1.9, 0.06, 0.7), THREE.MeshStandardMaterial.new(js(color=0xaacce0, map=SHIP_MAP, roughness=0.4, metalness=0.7)))
    wing.position.set(0, -0.05, -0.45)
    wing.castShadow = True
    group.add(wing)
    fin = THREE.Mesh.new(THREE.BoxGeometry.new(0.06, 0.45, 0.5), body_mat)
    fin.position.set(0, 0.25, -0.6)
    group.add(fin)
    flame = THREE.Sprite.new(THREE.SpriteMaterial.new(js(map=glow_texture("rgba(255,200,90,1)"), color=rgb(FLAME), transparent=True, blending=THREE.AdditiveBlending, depthWrite=False)))
    flame.position.set(0, 0, -1.0)
    flame.scale.set(0.7, 0.7, 1)
    group.add(flame)
    return group


ship_mesh = make_ship()
scene.add(ship_mesh)

# ── GPU で動く粒：位置は頂点シェーダが「生まれた時刻・速さ・いまの時刻」から計算する。Python は生まれるときだけ書く ──
PARTICLES = 4000
PART_VERT = """
attribute vec3 aVel;
attribute float aBirth;
attribute float aLife;
attribute vec3 aColor;
attribute float aSize;
uniform float uTime;
uniform float uDrift;
varying vec3 vColor;
varying float vFade;
void main() {
  float age = uTime - aBirth;
  float t = age / aLife;
  vColor = aColor;
  vFade = (age < 0.0 || t > 1.0) ? 0.0 : (1.0 - t) * (1.0 - t);
  vec3 p = position + aVel * age + vec3(0.0, -0.4 * age * age, -uDrift * age);   // 少し落ちながら、世界と一緒に手前へ
  vec4 mv = modelViewMatrix * vec4(p, 1.0);
  gl_PointSize = (vFade > 0.0) ? aSize * (1.0 - 0.5 * t) * 180.0 / max(1.0, -mv.z) : 0.0;
  gl_Position = projectionMatrix * mv;
}
"""
PART_FRAG = """
varying vec3 vColor;
varying float vFade;
void main() {
  vec2 d = gl_PointCoord - vec2(0.5);
  float r = length(d) * 2.0;
  float a = smoothstep(1.0, 0.2, r) * vFade;
  gl_FragColor = vec4(vColor * (1.0 + 0.6 * (1.0 - r)), a);
}
"""
part_geo = THREE.BufferGeometry.new()
part_geo.setAttribute("position", THREE.Float32BufferAttribute.new(to_js([0.0, -99.0, 0.0] * PARTICLES), 3))
part_geo.setAttribute("aVel", THREE.Float32BufferAttribute.new(to_js([0.0] * (PARTICLES * 3)), 3))
part_geo.setAttribute("aBirth", THREE.Float32BufferAttribute.new(to_js([-99.0] * PARTICLES), 1))
part_geo.setAttribute("aLife", THREE.Float32BufferAttribute.new(to_js([1.0] * PARTICLES), 1))
part_geo.setAttribute("aColor", THREE.Float32BufferAttribute.new(to_js([1.0] * (PARTICLES * 3)), 3))
part_geo.setAttribute("aSize", THREE.Float32BufferAttribute.new(to_js([1.0] * PARTICLES), 1))
part_mat = THREE.ShaderMaterial.new(js(vertexShader=PART_VERT, fragmentShader=PART_FRAG, transparent=True, depthWrite=False, blending=THREE.AdditiveBlending,
                                       uniforms=js(uTime=js(value=0.0), uDrift=js(value=0.0))))
particles = THREE.Points.new(part_geo, part_mat)
particles.frustumCulled = False
scene.add(particles)
part_next = {"i": 0}
fx_luck = random.Random(4)


def emit(x: float, y: float, z: float, count: int, color: tuple[int, int, int], speed: float = 3.0, life: float = 0.7, size: float = 1.0, now: float = 0.0, up: float = 0.0) -> None:
    """粒を count 個生む。属性の列に書くだけで、あとは GPU が動かす。"""
    r, g, b = [c / 255 for c in color]
    pos, vel, birth, lives, cols, sizes = [], [], [], [], [], []
    for _ in range(count):
        a = fx_luck.uniform(0, math.tau)
        u = fx_luck.uniform(-1, 1)
        s = fx_luck.uniform(0.3, 1.0) * speed
        pos += [x, y, z]
        vel += [math.cos(a) * s, u * s + up, fx_luck.uniform(-0.3, 0.3) * s]
        birth.append(now + fx_luck.uniform(0.0, 0.05))
        lives.append(life * fx_luck.uniform(0.6, 1.3))
        cols += [r, g, b]
        sizes.append(size * fx_luck.uniform(0.6, 1.4))
    i = part_next["i"]
    end = i + count
    if end > PARTICLES:                              # 輪の終わりに来たら先頭へ
        i, end = 0, count
    part_geo.attributes.position.array.set(to_js(pos), i * 3)
    part_geo.attributes.aVel.array.set(to_js(vel), i * 3)
    part_geo.attributes.aBirth.array.set(to_js(birth), i)
    part_geo.attributes.aLife.array.set(to_js(lives), i)
    part_geo.attributes.aColor.array.set(to_js(cols), i * 3)
    part_geo.attributes.aSize.array.set(to_js(sizes), i)
    for name in ("position", "aVel", "aBirth", "aLife", "aColor", "aSize"):
        getattr(part_geo.attributes, name).needsUpdate = True
    part_next["i"] = end


vignette = THREE.Sprite.new(THREE.SpriteMaterial.new(js(map=glow_texture("rgba(0,0,0,0)", "rgba(255,255,255,1)"), color=rgb(GLOW), transparent=True, opacity=0.0, depthTest=False)))
vignette.scale.set(6.4, 4.0, 1)
vignette.position.set(0, 0, -2.4)                   # カメラの子：画面の縁が光る（スレスレは黄、ぶつかったら赤）
camera.add(vignette)
scene.add(camera)
cam_fx = {"x": 0.0, "pull": 0.0, "ring": 0.0, "min_ring": 99.0, "orbit": 0.0, "stage": 1, "warp": 0.0}

# CLI 版の透視投影は「x が大きいほど画面の右」。Three.js のカメラは +z を向くと +x が左に映るので、
# 写すときに x の符号を反転する（M）。回転の y・z 軸と傾きも一緒に反転する
M = -1.0


def burst(x: float, y: float, z: float, count: int, color: tuple[int, int, int], speed: float = 3.0) -> None:
    emit(x, y, z, count, color, speed, 0.7, 1.0, world.time)


def sync(world: World, dt: float) -> None:
    """世界を Three.js の物に写す。カメラは cam_now（揺れ込み）と focus（速いほど広角）から。"""
    cam = world.cam_now
    focus = world.focus
    frac = (world.speed - SPEED0) / (SPEED_MAX - SPEED0)
    slow = world.started and not world.paused and world.hurt > 0.75   # ぶつかった直後のスロー
    if world.stage != cam_fx["stage"]:              # ステージが変わると空間の色が変わる
        cam_fx["stage"] = world.stage
        apply_theme(world.stage)
    cam_fx["x"] += (cam.x - cam_fx["x"]) * 0.22    # カメラは少し遅れて追う（曲がりに演技が付く）
    cam_fx["pull"] = max(0.0, cam_fx["pull"] - dt * 1.6)
    cam_fx["ring"] = max(0.0, cam_fx["ring"] - dt * 7.0)
    cam_fx["warp"] = max(0.0, cam_fx["warp"] - dt * 0.9)
    ring_now = min(world.rings) if world.rings else 99.0
    if ring_now < SHIP_Z <= cam_fx["min_ring"] or (cam_fx["min_ring"] < SHIP_Z and ring_now > cam_fx["min_ring"] + 3):
        if world.started and not world.paused and cam_fx["min_ring"] < 99:
            cam_fx["ring"] = 1.0                    # 輪を抜けた：一瞬白く光る
    cam_fx["min_ring"] = ring_now
    warp = cam_fx["warp"]
    fov = 2 * math.degrees(math.atan(CY / focus)) * (1 + 0.25 * warp)   # ワープ中は画角がぐっと広がる
    if slow:
        fov *= 0.82                                 # スロー中は自機に寄る
    camera.fov = fov
    camera.updateProjectionMatrix()
    cx = M * (cam_fx["x"] + cam.jolt_x)
    cy = EYE + cam.jolt_y
    cz = -2.5 * cam_fx["pull"]                      # ゲート通過：一瞬後ろへ引かれて戻る
    gate = world.gate
    if gate is not None and not gate.passed and SHIP_Z < gate.pos.z < SHIP_Z + 12:   # ゲートの手前は少し下から見上げる
        cy -= 0.6 * (1 - (gate.pos.z - SHIP_Z) / 12)
    if world.over:                                  # 終わり：自機の周りを回る
        cam_fx["orbit"] += dt * 0.8
        a = cam_fx["orbit"]
        s = world.ship
        camera.up.set(0, 1, 0)
        camera.position.set(M * s.x + 3.2 * math.sin(a), s.y + 1.4, s.z - 3.2 * math.cos(a))
        camera.lookAt(M * s.x, s.y, s.z)
    else:
        camera.up.set(M * -math.sin(cam.roll), math.cos(cam.roll), 0)   # 曲がると傾く（view() の -roll と同じ向き）
        camera.position.set(cx, cy, cz)
        camera.lookAt(cx, EYE + cam.jolt_y, 100.0)
    sun.target.position.set(cx, cy, 20)
    shift.uniforms.amount.value = 0.0004 + 0.0028 * frac + (0.004 if slow else 0.0) + 0.006 * warp
    vignette_pass.uniforms.darkness.value = 1.0 + 0.5 * frac
    vignette_pass.uniforms.offset.value = 1.15 - 0.35 * frac
    afterimage.uniforms.damp.value = 0.3 + 0.35 * frac + 0.2 * warp   # 残像：速いほど尾が長い
    bokeh.uniforms.focus.value = SHIP_Z + 1.0
    bokeh.uniforms.aperture.value = 0.00008 + 0.0002 * (1 if slow else 0)   # スロー中はピントが浅くなる
    tunnel_mat.uniforms.uTime.value = world.time
    tunnel_mat.uniforms.uSpeed.value = frac if world.started and not world.paused else 0.0
    tunnel_mat.uniforms.uWarp.value = warp
    tunnel.position.z = FAR / 2 + (world.rings[0] % RING_GAP if world.rings else 0) * 0.0
    for m in back_rocks:                            # 奥の層はごくゆっくり流れ（速さの 3%）、近づく前に奥へ戻す
        m.position.z -= world.speed * 0.03 * dt if world.started and not world.paused else 0.0
        m.rotation.y += 0.03 * dt
        if m.position.z < 50:
            m.position.z = 110
            m.position.x = back_luck.uniform(-50, 50)
    flat, colors = [], []
    stretch = 1.0 + 4.0 * warp                      # ワープ中は星が長い線になる
    for star in world.stars:                        # 流線：CLI 版と同じ「前のコマの位置から線」
        back = star.z + world.speed * STEP * STREAK * stretch
        near = 1 - star.z / FAR
        flat += [M * star.x, star.y, star.z, M * star.x, star.y, back]
        c = [linear(int(f + (n - f) * near)) for f, n in zip(STAR_FAR, STAR_NEAR)]
        colors += c + [v * 0.25 for v in c]
    streak_geo.attributes.position.array.set(to_js(flat))
    streak_geo.attributes.position.needsUpdate = True
    streak_geo.attributes.color.array.set(to_js(colors))
    streak_geo.attributes.color.needsUpdate = True
    for i, m in enumerate(rings):
        if i < len(world.rings):
            m.visible = True
            m.position.set(0, RING_Y, world.rings[i])
            m.rotation.z = world.time * 0.15 + i
        else:
            m.visible = False
    alive = set()
    for rock in world.rocks:
        key = id(rock)
        alive.add(key)
        mesh = rock_meshes.get(key)
        if mesh is None:
            mesh = THREE.Mesh.new(ROCK_GEOS[rock.seed % len(ROCK_GEOS)], ROCK_MAT)
            mesh.scale.set(rock.radius, rock.radius, rock.radius)
            mesh.castShadow = True
            mesh.receiveShadow = True
            scene.add(mesh)
            rock_meshes[key] = mesh
        mesh.position.set(M * rock.pos.x, rock.pos.y, rock.pos.z)
        near = max(0.0, 1 - rock.pos.z / FAR)
        spin = 1.0 + 1.2 * near * near              # 近いほど速く回って見える
        mesh.rotation.set(rock.angle.x * spin, M * rock.angle.y * spin, M * rock.angle.z * spin)
        if glint_until.get(key, -1.0) > world.time:
            mesh.material = GLINT_MAT
        else:
            mesh.material = DANGER_MAT if world.dangerous(rock) else ROCK_MAT
    for key in list(rock_meshes):
        if key not in alive:
            scene.remove(rock_meshes.pop(key))
            glint_until.pop(key, None)
    for d in debris:                                # 破片：飛んで回って、世界と一緒に流れ、消える
        m = d[0]
        m.position.x += d[1] * dt
        m.position.y += d[2] * dt
        m.position.z += (d[3] - world.speed) * dt
        m.rotation.x += d[5] * dt
        m.rotation.y += d[5] * 0.7 * dt
        d[4] -= dt
        if d[4] <= 0:
            m.visible = False
    debris[:] = [d for d in debris if d[4] > 0]
    DANGER_MAT.emissiveIntensity = 0.5 + 0.4 * math.sin(world.time * 9)
    if gate is not None and not gate.passed:
        gate_mesh.visible = gate_core.visible = True
        gate_mesh.position.set(M * gate.pos.x, gate.pos.y, gate.pos.z)
        gate_core.position.set(M * gate.pos.x, gate.pos.y, gate.pos.z)
        gate_light.position.set(M * gate.pos.x, gate.pos.y, gate.pos.z)
        gate_light.intensity = 40.0
        gate_mesh.rotation.z = world.time * 0.8
        if fx_luck.random() < 0.5:                  # ゲートの縁からきらめき
            a = fx_luck.uniform(0, math.tau)
            emit(M * gate.pos.x + GATE_R * math.cos(a), gate.pos.y + GATE_R * math.sin(a), gate.pos.z, 2, GATE, 0.4, 0.6, 0.8, world.time)
    else:
        gate_mesh.visible = gate_core.visible = False
        gate_light.intensity = 0.0
    ship = world.ship
    tilt = -world.aim.x * 0.5
    ship_mesh.position.set(M * ship.x, ship.y, ship.z)
    ship_mesh.rotation.set(0.1 - world.aim.y * 0.25, 0, M * tilt)
    ship_mesh.visible = world.over or int(world.hurt * 12) % 2 == 0
    flame = ship_mesh.children[3]
    k = 0.35 + 0.15 * frac + 0.06 * math.sin(world.time * 40)
    flame.scale.set(k, k * (1.3 + 1.2 * frac), 1)   # 速いほど噴射が少し長く、青白くなる（大きいと画面が見えない）
    flame.material.color.setRGB(1.0, 0.63 + 0.3 * frac, 0.24 + 0.7 * frac)
    if world.started and not world.paused and not world.over:   # 噴射：炎と火花と煙（GPU の粒）
        emit(M * ship.x - 0.15 * math.sin(M * tilt), ship.y - 0.05, ship.z - 1.0, 2, (255, 170 + int(60 * frac), 60 + int(150 * frac)), 0.3, 0.25, 0.4, world.time)
        if fx_luck.random() < 0.3:
            emit(M * ship.x, ship.y - 0.1, ship.z - 1.2, 1, (255, 240, 200), 1.2, 0.4, 0.25, world.time)
        if fx_luck.random() < 0.25:                 # 煙は少なく・小さく・短く（多いと画面が見えない）
            emit(M * ship.x, ship.y, ship.z - 1.3, 1, (90, 90, 110), 0.2, 0.7, 0.6, world.time)
    part_mat.uniforms.uTime.value = world.time
    part_mat.uniforms.uDrift.value = world.speed if world.started and not world.paused and not world.over else 0.0
    if world.flash > 0:
        vignette.material.color.setHex(rgb(world.flash_color))
        vignette.material.opacity = min(0.85, world.flash * 3.0)
    elif cam_fx["ring"] > 0:
        vignette.material.color.setHex(0xbfd8ff)
        vignette.material.opacity = 0.12 * cam_fx["ring"]      # 輪を抜けた瞬間だけ薄く（0.35 では速いとき画面が白く濁った）
    else:
        vignette.material.opacity = 0.0
    bloom.strength = 0.45 + 0.25 * frac + (0.3 if world.flash > 0 else 0.0) + 0.2 * cam_fx["ring"] + 0.4 * warp
    engine_tone(frac if world.started and not world.paused and not world.over else -1.0)


# ── 音（Tone.js）：エンジンの持続音・スレスレの風切り（左右）・ゲートの和音・衝突 ─────────────
music = {"on": False, "engine": None, "filter": None, "synth": None, "drum": None, "whoosh": None, "pan": None}


def music_start() -> None:
    """人が触った処理の中で呼ぶ（Safari の決まり）。"""
    if TONE is None or music["on"]:
        return
    try:
        TONE.start()
        filt = TONE.Filter.new(400, "lowpass").toDestination()
        engine = TONE.Oscillator.new(55, "sawtooth").connect(filt)
        engine.volume.value = -26
        engine.start()
        synth = TONE.PolySynth.new(TONE.Synth).toDestination()
        synth.volume.value = -12
        drum = TONE.MembraneSynth.new().toDestination()
        drum.volume.value = -6
        pan = TONE.Panner.new(0).toDestination()
        whoosh = TONE.NoiseSynth.new(js(noise=js(type="pink"), envelope=js(attack=0.02, decay=0.18, sustain=0.0, release=0.1))).connect(pan)
        whoosh.volume.value = -10
        music.update(on=True, engine=engine, filter=filt, synth=synth, drum=drum, whoosh=whoosh, pan=pan)
    except Exception:
        music["on"] = False


def engine_tone(frac: float) -> None:
    """エンジンの持続音：速いほど高く、大きく。frac < 0 なら止まっている（小さく）。"""
    if not music["on"]:
        return
    try:
        if frac < 0:
            music["engine"].volume.rampTo(-40, 0.3)
            return
        music["engine"].frequency.rampTo(55 + 90 * frac, 0.15)
        music["filter"].frequency.rampTo(300 + 1400 * frac, 0.15)
        music["engine"].volume.rampTo(-26 + 8 * frac, 0.2)
    except Exception:
        pass


def sound_event(event: str, side: float = 0.0) -> bool:
    """出来事の音（Tone.js）。鳴らせたら True（wav は鳴らさない）。"""
    if not music["on"]:
        return False
    try:
        now = TONE.now()
        if event == "graze":
            music["pan"].pan.value = max(-1.0, min(1.0, side))
            music["whoosh"].triggerAttackRelease("16n", now)
            return True
        if event == "gate":
            music["synth"].triggerAttackRelease(to_js(["C4", "E4", "G4", "C5"]), "4n", now)
            return True
        if event == "hit":
            music["drum"].triggerAttackRelease("C1", "8n", now)
            return True
        if event in ("over", "best"):
            music["drum"].triggerAttackRelease("A0", "2n", now)
            for i, n in enumerate(("E4", "C4", "A3", "F3")):
                music["synth"].triggerAttackRelease(n, "8n", now + 0.18 * i)
            return True
    except Exception:
        pass
    return False


class Speaker:
    """ブラウザで音を出す係。wav を data URI にして Audio に持たせておく。"""

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


def refresh(dt: float = STEP) -> None:
    sync(world, dt)
    composer.render()
    score_label.textContent = str(world.score)
    passed_label.textContent = str(world.passed)
    combo_label.textContent = f"×{min(world.combo, COMBO_MAX)}" if world.combo > 1 else "―"
    note_label.textContent = world.note if world.time < world.note_until else " "
    note_label.style.color = ("#c0392b" if world.note.startswith("ぶつかった")
                              else "#2e8b57" if world.note.startswith("ゲート") else "#b8860b")
    lives_label.textContent = "♥" * world.lives + "♡" * (3 - world.lives)
    speed_label.textContent = f"{world.speed:.1f}"
    best_label.textContent = str(best.score)
    stage_label.textContent = str(world.stage)
    gate_label.textContent = "来た！" if world.gate is not None and not world.gate.passed else f"あと {GATE_EVERY - world.since_gate}"
    if world.over:
        message.textContent = (f"おしまい。点 {world.score}" + ("  ベスト更新！" if improved else f"（ベスト {best.score}）")
                               + "  「もう一度」で最初から")
    elif not world.started:
        message.textContent = "「スタート」で始まります（矢印・w a s d・画面のボタン。画面を左右になぞっても動けます）"
    elif world.paused:
        message.textContent = "一時停止中"
    else:
        message.textContent = ""
    again_button.hidden = not world.over
    go_button.hidden = world.over
    go_button.textContent = "▶ スタート" if not world.started else "▶ つづける" if world.paused else "❚❚ 一時停止"


def effect(event: str | None) -> None:
    """出来事の演出：スレスレは黄の粒、ぶつかると赤い破片、ゲートは緑の輪、終わりは爆発。"""
    if event is None:
        return
    s = world.ship
    sx = M * s.x
    nearest = min(world.rocks, key=lambda r: abs(r.pos.z - s.z) + 0.3 * abs(r.pos.x - s.x), default=None)
    side = M * (nearest.pos.x - s.x) if nearest is not None else 0.0
    if event in ("graze", "near"):
        burst(sx, s.y, s.z + 0.5, 14 if event == "graze" else 6, GLOW, 2.5)
        if event == "graze" and nearest is not None:
            glint_until[id(nearest)] = world.time + 0.3   # すれた岩の表面が一瞬光る
    elif event == "hit":
        burst(sx, s.y, s.z + 0.3, 40, BLOOD, 4.0)
        burst(sx, s.y, s.z + 0.3, 20, ROCK, 3.0)
        if nearest is not None:
            shatter(M * nearest.pos.x, nearest.pos.y, nearest.pos.z, nearest.radius)   # 岩が砕けて破片が散る
    elif event == "gate":
        cam_fx["pull"] = 1.0
        cam_fx["warp"] = 1.0                        # ワープ：トンネルの帯が伸び、星が線になり、画角が広がる
        g = world.gate
        if g is not None:
            for _ in range(48):
                a = fx_luck.uniform(0, math.tau)
                burst(M * g.pos.x + GATE_R * math.cos(a), g.pos.y + GATE_R * math.sin(a), g.pos.z, 1, GATE, 1.5)
    elif event in ("over", "best"):
        burst(sx, s.y, s.z, 120, FLAME, 6.0)
        burst(sx, s.y, s.z, 60, SHIP, 5.0)


async def loop():
    """刻み幅は CLI 版と同じ STEP に固定する（g64 で入れた）。"""
    global improved
    lag = 0.0
    last = window.performance.now() / 1000
    while True:
        now = window.performance.now() / 1000
        frame_dt = min(0.1, now - last)
        lag = min(lag + now - last, 0.25)           # ためすぎない（重い端末で追いつけなくなる）
        last = now
        while lag >= STEP:
            event = world.update(STEP * (0.25 if world.hurt > 0.75 else 1.0))   # ぶつかった直後はスロー
            if event == "over":                     # 終わった瞬間にベストへ取り込んで保存（CLI 版の run と同じ）
                improved = best.take(world)
                window.localStorage.setItem(SAVED, best.dump())
                event = "best" if improved else event
            effect(event)
            if not sound_event(event, side=(M * (min(world.rocks, key=lambda r: abs(r.pos.z - world.ship.z), default=world.ship).pos.x - world.ship.x)) if event == "graze" else 0.0):
                speaker.say(event)
            lag -= STEP
        refresh(frame_dt)
        frames.append(window.performance.now() / 1000)
        del frames[:-30]
        if len(frames) >= 2:
            fps_label.textContent = f"{(len(frames) - 1) / (frames[-1] - frames[0]):.0f}"
        spent = window.performance.now() / 1000 - now   # 描くのにかかった時間を引いて眠る（STEP ぶん眠ると 20 コマ/秒止まり）
        await asyncio.sleep(max(0.002, STEP - spent))


KEYS = {"ArrowLeft": "left", "ArrowRight": "right", "ArrowUp": "up", "ArrowDown": "down",
        "a": "left", "d": "right", "w": "up", "s": "down", " ": "go", "p": "go", "Enter": "go"}


@when("keydown", "body")
def on_down(event):
    key = KEYS.get(event.key)
    if key is not None:
        event.preventDefault()
        if key == "go":
            music_start()
        obey(world, key, True)


@when("keyup", "body")
def on_up(event):
    key = KEYS.get(event.key)
    if key is not None:
        event.preventDefault()
        obey(world, key, False)


@when("click", "#go")
def go(event):
    music_start()
    obey(world, "go")
    go_button.blur()                                # ボタンに焦点が残ると、スペースが 2 回（ボタンとキー）効いてしまう
    refresh()


# 画面をなぞって動く（スマホ）。指の位置と自機の位置の差で向きを決める。タップだけなら 始める／止める
touch = {"down": False, "x": 0.0, "y": 0.0, "moved": False, "t": 0.0}


def steer(event) -> None:
    rect = canvas.getBoundingClientRect()
    fx = (event.clientX - rect.left) / rect.width * 2 - 1
    fy = -((event.clientY - rect.top) / rect.height * 2 - 1)
    want_x = fx * REACH_X
    want_y = REACH_Y[0] + (fy + 1) / 2 * (REACH_Y[1] - REACH_Y[0])
    dx, dy = want_x - world.ship.x, want_y - world.ship.y
    world.aim = V(0.0 if abs(dx) < 0.25 else (1.0 if dx > 0 else -1.0), 0.0 if abs(dy) < 0.25 else (1.0 if dy > 0 else -1.0), 0)


@when("pointerdown", "#screen")
def press(event):
    event.preventDefault()
    music_start()
    touch.update(down=True, x=event.clientX, y=event.clientY, moved=False, t=window.performance.now())


@when("pointermove", "#screen")
def slide(event):
    if not touch["down"]:
        return
    if abs(event.clientX - touch["x"]) > 8 or abs(event.clientY - touch["y"]) > 8:
        touch["moved"] = True
    if touch["moved"] and world.started and not world.paused:
        steer(event)


@when("pointerup", "#screen")
def release(event):
    if not touch["down"]:
        return
    touch["down"] = False
    if touch["moved"]:
        obey(world, "stop")
    else:
        obey(world, "go")
    refresh()


@when("pointercancel", "#screen")
def cancel(event):
    touch["down"] = False
    obey(world, "stop")


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
    world = World(seed=int(window.performance.now()), started=True)
    for key in list(rock_meshes):
        scene.remove(rock_meshes.pop(key))
    cam_fx["warp"] = 0.0
    for d in debris:
        d[0].visible = False
    debris.clear()
    cam_fx.update(pull=0.0, ring=0.0, orbit=0.0, stage=1)
    apply_theme(1)
    improved = False
    refresh()


apply_theme(1)
document.querySelector("#loading").hidden = True
refresh()
asyncio.ensure_future(loop())
