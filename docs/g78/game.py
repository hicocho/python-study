"""小惑星をよける（3D）ブラウザ版

CLI 版（g78-space-3d/main.py）と中身はまったく同じ。3D の点（V）も、回転（rotate）も、
透視投影（project）も、面を塗る Screen.fill も、隠面消去と陰影（draw_solid）も、
世界（World）も、キーを受ける obey も 1 文字も変えていない。

違うのは入口と出口だけ。
  入口: 端末はキーの並び、ブラウザは keydown / keyup とボタン
  出口: 端末は ▀ の並び、ブラウザは canvas。音は端末が afplay、ブラウザは Audio
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

SCALE = 2                                           # ブラウザは 2 倍の板（256 × 160）に描く
canvas = document.querySelector("#screen")
ctx = canvas.getContext("2d")
ctx.imageSmoothingEnabled = False
image = ctx.createImageData(WIDTH * SCALE, HEIGHT * SCALE)
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


class CanvasScreen(Screen):
    """CLI 版の Screen をそのまま使い、描き終えた画素をまとめて canvas へ送る。

    行の RGB を RGBA に組み替えるのもスライス代入（3 つおき → 4 つおき）。1 ドットずつ触らない。
    """

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
    """ブラウザで音を出す係。3 つの wav を data URI にして Audio に持たせておく。"""

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
    score_label.textContent = str(world.score)
    passed_label.textContent = str(world.passed)
    combo_label.textContent = f"×{min(world.combo, COMBO_MAX)}" if world.combo > 1 else "―"
    note_label.textContent = world.note if world.time < world.note_until else " "
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
        message.textContent = "「スタート」で始まります（矢印で動けます）"
    elif world.paused:
        message.textContent = "一時停止中"
    else:
        message.textContent = ""
    again_button.hidden = not world.over
    go_button.hidden = world.over
    go_button.textContent = "▶ スタート" if not world.started else "▶ つづける" if world.paused else "❚❚ 一時停止"


async def loop():
    """刻み幅は CLI 版と同じ STEP に固定する（g64 で入れた）。"""
    global improved
    lag = 0.0
    last = window.performance.now() / 1000
    while True:
        now = window.performance.now() / 1000
        lag = min(lag + now - last, 0.25)           # ためすぎない（重い端末で追いつけなくなる）
        last = now
        while lag >= STEP:
            event = world.update(STEP)
            if event == "over":                     # 終わった瞬間にベストへ取り込んで保存（CLI 版の run と同じ）
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
        await asyncio.sleep(STEP)


KEYS = {"ArrowLeft": "left", "ArrowRight": "right", "ArrowUp": "up", "ArrowDown": "down",
        "a": "left", "d": "right", "w": "up", "s": "down", " ": "go", "p": "go", "Enter": "go"}


@when("keydown", "body")
def on_down(event):
    key = KEYS.get(event.key)
    if key is not None:
        event.preventDefault()
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
    go_button.blur()                                # ボタンに焦点が残ると、スペースが 2 回（ボタンとキー）効いてしまう
    refresh()


@when("click", "#screen")
def tap_screen(event):
    """画面をタップしても 始める／止める（スマホ用）。"""
    obey(world, "go")
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
    world = World(seed=int(window.performance.now()), started=True)
    improved = False
    refresh()


document.querySelector("#loading").hidden = True
refresh()
asyncio.ensure_future(loop())
