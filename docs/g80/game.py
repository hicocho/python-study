"""クレー射撃 ブラウザ版

CLI 版（g80-clay-shooting/main.py）と中身はまったく同じ。3D の点（V）も、上下左右に回るカメラ（view）も、
皿の放物線（Clay.fly）も、円錐の当たり判定と先読み（judge / flight_time）も、ラウンドの進行（World）も 1 文字も変えていない。

違うのは入口と出口だけ。
  入口: 端末はキーの並び、ブラウザは keydown / keyup と十字ボタン。画面をなぞると照準が動き、タップで撃つ
  出口: 端末は ▀ の並び、ブラウザは canvas（3 倍の板）。音は端末が afplay、ブラウザは Audio
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


FOCUS = 110.0                                       # 焦点距離。少し望遠（視野 60°）。皿が小さいので


NEAR = 0.3


FAR = 140.0                                         # 木や山を置く遠さ


FOG_FROM = 40.0


EYE = 1.6                                           # 目の高さ


STEP = 1 / 30


G = 9.8                                             # 重力（破片用）


CLAY_G = 4.4                                        # 皿に効く重力。円盤は揚力で落ちにくい（本物も 3〜4 秒飛ぶ）


AIR = 0.22                                          # 皿の空気抵抗（1 秒に速さの 22% を失う）


CLAY_R = 0.5                                        # 皿の半径（本物は 0.055。見えるように大きく）


TRAP = (0.0, 0.6, 12.0)                             # 放出機の位置（正面 12 m）


SKEET_HIGH = (-18.0, 3.0, 6.0)                      # スキートの高い放出機（左）


SKEET_LOW = (18.0, 1.0, 6.0)                        # スキートの低い放出機（右）


LAUNCH_SPEED = (21.0, 26.0)                         # 放出の速さ（m/s）の範囲（慣れたころ）


LAUNCH_SLOW = (13.0, 16.0)                          # 最初の皿の速さ。EASE_IN 枚かけて LAUNCH_SPEED まで上げる


EASE_IN = 15


TRAP_YAW = 0.7                                      # トラップの左右のばらつき（±ラジアン）


TRAP_PITCH = (0.22, 0.42)                           # トラップの仰角の範囲


PELLET_SPEED = 400.0                                # 散弾の速さ


SPREAD = math.radians(3.2)                          # 散弾の広がり（円錐の半角）。30 m で半径 1.7 m。1.6° では全然当たらなかった


RANGE = 70.0                                        # これより遠くには届かない


SHOTS = 2                                           # 1 枚につき 2 発


ROUND = 25                                          # 1 ラウンドの枚数


TURN = 1.0                                          # 照準を回す速さ（ラジアン/秒）。押した直後はこの速さ（細かく合わせる）


TURN_FAST = 3.2                                     # 押し続けると TURN_RAMP 秒でここまで速くなる（大きく振る）


TURN_RAMP = 0.5


PITCH_GAIN = 0.5                                    # 上下は左右の半分の速さ（皿の上下の動きは小さいので）


NUDGE = 0.03                                        # 1 回押したときに動く角度（ラジアン。1.7°＝散弾の広がりの 1.1 倍。0.02 では遅かった）


HOLD = 0.18                                         # これより長く押し続けたら、連続して回り始める


PITCH_LIMIT = (-0.35, 0.9)                          # 見下ろし・見上げの限界


RECOIL = 0.05                                       # 撃ったときに跳ね上がる角度


POINTS = {"smash": 3, "break": 2, "chip": 1}        # 粉々・割れる・かする


SKY_TOP = (74, 128, 208)


SKY = (176, 204, 232)


CLOUD = (240, 244, 250)


MOUNTAIN_FAR = (122, 150, 188)


MOUNTAIN_NEAR = (90, 122, 152)


GRASS_A = (76, 140, 64)


GRASS_B = (70, 130, 60)


GRASS_FAR = (96, 150, 100)


TRUNK = (92, 64, 38)


CROWN = (36, 100, 44)


LEAF = (66, 132, 52)


HOUSE = (176, 166, 148)


HOUSE_ROOF = (120, 110, 96)


CLAY = (240, 120, 40)


CLAY_UNDER = (150, 70, 20)


BARREL = (48, 48, 54)


BARREL_LIGHT = (96, 96, 104)


STOCK = (120, 78, 42)


CROSS = (255, 255, 255)


FLASH = (255, 240, 170)


PIECE = (230, 110, 40)


LIGHT_DIR = (-0.4, 0.9, -0.5)


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
    """雑音が減衰していく音（発砲・割れる音）。乱数は種を固定するので毎回同じ波。"""
    luck = random.Random(seed)
    count = int(RATE * seconds)
    samples = array("h")
    for i in range(count):
        env = math.exp(-decay * i / RATE)
        samples.append(int(32767 * volume * env * luck.uniform(-1, 1)))
    return samples


def sound_bytes(kind: str) -> bytes:
    """出来事の音。pull は放出の合図、shot は発砲、smash / break / chip は当たり（粉々・割れる・かする）、
    miss は外れ（低く短く）、end はラウンド終了、best はベスト更新。"""
    if kind == "pull":
        samples = tone(990, 0.12)
    elif kind == "shot":
        samples = noise(0.35, VOLUME * 2.2, 9.0, 3)
    elif kind == "smash":
        samples = noise(0.22, VOLUME * 1.2, 14.0, 5) + tone(1760, 0.08)
    elif kind == "break":
        samples = noise(0.16, VOLUME, 18.0, 6)
    elif kind == "chip":
        samples = noise(0.08, VOLUME * 0.7, 30.0, 7)
    elif kind == "miss":
        samples = tone(220, 0.12, VOLUME * 0.6)
    elif kind == "click":
        samples = noise(0.03, VOLUME * 0.8, 60.0, 9)
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


EVENTS = ("pull", "shot", "miss", "chip", "break", "smash", "end")   # update() が返す出来事。目立つ順


SOUNDS = EVENTS + ("click", "best")                 # click は弾切れ（fire() が返す）


class V(NamedTuple):
    """3D の点（ベクトル）。x 右、y 上、z 前。"""

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


def rotate(p: V, ax: float, ay: float, az: float) -> V:
    """x 軸・y 軸・z 軸のまわりに順に回す（g78 と同じ）。"""
    cx, sx = math.cos(ax), math.sin(ax)
    cy, sy = math.cos(ay), math.sin(ay)
    cz, sz = math.cos(az), math.sin(az)
    y, z = p.y * cx - p.z * sx, p.y * sx + p.z * cx
    x, z = p.x * cy + z * sy, -p.x * sy + z * cy
    x, y = x * cz - y * sz, x * sz + y * cz
    return V(x, y, z)


def direction(yaw: float, pitch: float) -> V:
    """向き（yaw 左右、pitch 上下）の単位ベクトル。yaw 0・pitch 0 なら +z。"""
    return V(math.sin(yaw) * math.cos(pitch), math.sin(pitch), math.cos(yaw) * math.cos(pitch))


class Camera(NamedTuple):
    """視点。位置と、左右（yaw）・上下（pitch）の向き。"""

    pos: V = V(0.0, EYE, 0.0)
    yaw: float = 0.0
    pitch: float = 0.0


def view(p: V, cam: Camera) -> V:
    """世界の点を「カメラから見た点」にする。位置を引き、yaw のぶん、次に pitch のぶん逆に回す。

    g79 は yaw だけだった。上を向く（pitch > 0）と世界は下へ回る。順番が大事：先に yaw、あとで pitch。
    """
    q = p - cam.pos
    q = rotate(q, 0.0, -cam.yaw, 0.0)             # yaw は「逆に」回す
    return rotate(q, cam.pitch, 0.0, 0.0)          # pitch は rotate の x 回転の向きが逆なので、そのまま渡すと「逆に」回る


def project(p: V, scale: float = 1.0) -> tuple[float, float]:
    return (CX + FOCUS * p.x / p.z) * scale, (CY - FOCUS * p.y / p.z) * scale


def clip_near(points: list[V]) -> list[V]:
    """多角形を z = NEAR の面で切る（g79 と同じ）。"""
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


def angle_between(a: V, b: V) -> float:
    """2 つの向きの間の角度（ラジアン）。"""
    return math.acos(max(-1.0, min(1.0, a.unit().dot(b.unit()))))


class Screen:
    """WIDTH × HEIGHT のドットの板。1 行を bytearray（RGB × WIDTH）で持ち、スライス代入で塗る。"""

    def __init__(self, width: int = WIDTH, height: int = HEIGHT):
        self.width, self.height = width, height
        self.rows = [bytearray(width * 3) for _ in range(height)]

    def band(self, top: int, bottom: int, color: tuple[int, int, int]) -> None:
        line = bytes(color) * self.width
        for y in range(max(0, top), min(self.height, bottom)):
            self.rows[y][:] = line

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


@dataclass
class Clay:
    """飛んでいる皿。位置・速さ・回転。"""

    pos: V
    vel: V
    spin: float = 0.0
    shots: int = 0                                  # この皿に撃った数
    result: str | None = None                       # smash / break / chip / miss。None は飛行中
    pieces: list[tuple[V, V]] = field(default_factory=list)   # 割れた破片（位置, 速さ）
    done_at: float = 0.0                            # 決着した時刻

    def fly(self, dt: float) -> None:
        """放物線。重力で落ち、空気抵抗で減速する（g64 の物理を 3D に）。"""
        self.vel = V(self.vel.x, self.vel.y - CLAY_G * dt, self.vel.z).scale(1 - AIR * dt)
        self.pos = self.pos + self.vel.scale(dt)
        self.spin += 12 * dt
        for k, (p, v) in enumerate(self.pieces):
            v = V(v.x, v.y - G * dt, v.z).scale(1 - 0.6 * dt)
            self.pieces[k] = (p + v.scale(dt), v)

    def flying(self) -> bool:
        return self.result is None and self.pos.y > 0

    def ahead(self, seconds: float) -> V:
        """seconds 後の位置（同じ物理で写しを進める）。散弾が届く時刻の位置を知るのに使う。"""
        copy = Clay(self.pos, self.vel)
        left = seconds
        while left > 0:
            copy.fly(min(STEP, left))
            left -= STEP
        return copy.pos


def flight_time(shooter: V, clay: Clay) -> float:
    """散弾が皿に届くまでの時間。届く時刻の皿の位置は動くので、2 回まわして近づける。"""
    t = (clay.pos - shooter).length() / PELLET_SPEED
    for _ in range(2):
        t = (clay.ahead(t) - shooter).length() / PELLET_SPEED
    return t


def judge(shooter: V, aim: V, clay: Clay) -> tuple[str, float, float]:
    """撃った結果。(結果, 角度のずれ / 広がり, 届く時間)。
    散弾は円錐に広がる。届く時刻の皿の位置への向きと、狙った向き aim の角度が、
    広がり SPREAD の 0.45 倍以内なら粉々、0.8 倍以内なら割れる、1 倍以内ならかする。"""
    t = flight_time(shooter, clay)
    target = clay.ahead(t)
    if (target - shooter).length() > RANGE or target.y < 0:
        return "miss", 9.0, t
    ratio = angle_between(aim, target - shooter) / SPREAD
    if ratio < 0.45:
        return "smash", ratio, t
    if ratio < 0.8:
        return "break", ratio, t
    if ratio < 1.0:
        return "chip", ratio, t
    return "miss", ratio, t


@dataclass
class Best:
    """ベスト（1 ラウンドの命中数と点）。端末は records.json、ブラウザは localStorage。"""

    hits: int = 0
    score: int = 0

    def dump(self) -> str:
        return json.dumps({"hits": self.hits, "score": self.score})

    @classmethod
    def parse(cls, text: str) -> "Best":
        try:
            data = json.loads(text)
            return cls(int(data["hits"]), int(data["score"]))
        except (ValueError, KeyError, TypeError):
            return cls()

    def take(self, hits: int, score: int) -> bool:
        improved = score > self.score
        self.hits = max(self.hits, hits)
        self.score = max(self.score, score)
        return improved


@dataclass
class World:
    seed: int = 0
    mode: str = "trap"                              # trap / skeet
    luck: random.Random = field(default_factory=random.Random)
    cam: Camera = Camera()
    clay: Clay | None = None
    time: float = 0.0
    started: bool = False
    thrown: int = 0                                 # 放出した枚数
    hits: int = 0
    score: int = 0
    streak: int = 0
    best_streak: int = 0
    shots_left: int = SHOTS
    pull_at: float = 0.6                            # 次の放出の時刻
    over: bool = False
    turn: V = V(0.0, 0.0, 0.0)                      # 照準の動き（x 左右、y 上下）
    turning: float = 0.0                            # 照準を動かし続けている秒数（長いほど速く回る）
    recoil: float = 0.0                             # 反動の残り
    flash: float = 0.0                              # 発砲の光の残り
    note: str = ""
    note_until: float = 0.0
    log: list[str] = field(default_factory=list)   # 枚ごとの結果

    def __post_init__(self):
        self.luck = random.Random(self.seed)

    def launch_speed(self) -> float:
        """放出の速さ。最初はゆっくり、EASE_IN 枚かけて本来の速さへ（慣れてから速く）。"""
        ease = min(1.0, self.thrown / EASE_IN)
        lo = LAUNCH_SLOW[0] + (LAUNCH_SPEED[0] - LAUNCH_SLOW[0]) * ease
        hi = LAUNCH_SLOW[1] + (LAUNCH_SPEED[1] - LAUNCH_SLOW[1]) * ease
        return self.luck.uniform(lo, hi)

    def launch(self) -> Clay:
        """放出。トラップは正面の放出機から遠ざかる向きに、スキートは左右の放出機から交差して。"""
        speed = self.launch_speed()
        if self.mode == "trap":
            yaw = self.luck.uniform(-TRAP_YAW, TRAP_YAW)
            pitch = self.luck.uniform(*TRAP_PITCH)
            return Clay(V(*TRAP), direction(yaw, pitch).scale(speed))
        if self.thrown % 2 == 0:                    # 高い放出機（左）から右へ
            start, yaw = V(*SKEET_HIGH), math.pi / 2 - self.luck.uniform(0.25, 0.45)
        else:                                       # 低い放出機（右）から左へ
            start, yaw = V(*SKEET_LOW), -math.pi / 2 + self.luck.uniform(0.25, 0.45)
        pitch = self.luck.uniform(0.28, 0.4)
        return Clay(start, direction(yaw, pitch).scale(speed))

    def tell(self, text: str, seconds: float = 1.4) -> None:
        self.note = text
        self.note_until = self.time + seconds

    def fire(self) -> str | None:
        """撃つ。弾が残っていれば必ず発砲する（音と反動）。飛んでいる皿があれば判定。
        弾が無ければ「カチッ」。押したのに何も起きない、が無いように。"""
        if self.over:
            return None
        if self.shots_left <= 0:
            return "click"
        self.shots_left -= 1
        self.recoil = 1.0
        self.flash = 0.08
        if self.clay is None or not self.clay.flying():   # 皿が無い（まだ出ていない・割れた・落ちた）→ 空撃ち
            if self.clay is None:
                self.tell("皿はまだ…")
            elif self.clay.result in POINTS:
                self.tell("もう割れている")
            else:
                self.tell("次の皿を待つ")
            return "shot"
        self.clay.shots += 1
        aim = direction(self.cam.yaw, self.cam.pitch)
        result, ratio, t = judge(self.cam.pos, aim, self.clay)
        if result == "miss":
            if self.shots_left == 0:                # 2 発とも外れ
                self.settle("miss")
                return "miss"
            self.tell("外れ… もう 1 発")
            return "shot"
        self.settle(result, t)
        return result

    def settle(self, result: str, t: float = 0.0) -> None:
        """皿の決着。点と連続を更新し、割れたなら破片を飛ばす。"""
        clay = self.clay
        clay.result = result
        clay.done_at = self.time
        if result == "miss":
            self.streak = 0
            self.tell("外れ")
            self.log.append("×")
            return
        points = POINTS[result]
        second = " (2 発目)" if clay.shots == 2 else ""
        self.hits += 1
        self.streak += 1
        self.best_streak = max(self.best_streak, self.streak)
        self.score += points
        self.log.append({"smash": "◎", "break": "○", "chip": "△"}[result])
        word = {"smash": "粉々！", "break": "割れた！", "chip": "かすった"}[result]
        self.tell(f"{word} +{points}{second}" + (f"  {self.streak} 連続" if self.streak > 1 else ""))
        where = clay.ahead(t)                       # 弾が届いた場所で割れる
        clay.pos = where
        count = {"smash": 10, "break": 6, "chip": 3}[result]
        for k in range(count):
            a = k * math.tau / count
            v = V(math.cos(a) * 4, self.luck.uniform(1, 5), math.sin(a) * 4) + clay.vel.scale(0.5)
            clay.pieces.append((where, v))

    def update(self, dt: float) -> str | None:
        """1 コマ進める。起きたこと（EVENTS のどれか）を返す。"""
        if not self.started or self.over:
            return None
        self.time += dt
        # 照準。1 回押すと NUDGE だけ動く（obey）。HOLD 秒より長く押し続けると連続して回り、
        # 最初はゆっくり（細かく合わせる）、さらに押し続けると速く（大きく振る）
        if self.turn.x or self.turn.y:
            self.turning += dt
        else:
            self.turning = 0.0
        held = max(0.0, self.turning - HOLD)
        rate = (TURN + (TURN_FAST - TURN) * min(1.0, held / TURN_RAMP)) if self.turning > HOLD else 0.0
        yaw = self.cam.yaw + self.turn.x * rate * dt
        pitch = max(PITCH_LIMIT[0], min(PITCH_LIMIT[1], self.cam.pitch + self.turn.y * rate * PITCH_GAIN * dt))
        self.cam = Camera(self.cam.pos, yaw, pitch)
        self.recoil = max(0.0, self.recoil - 4 * dt)
        self.flash = max(0.0, self.flash - dt)
        happened = None
        # 皿
        if self.clay is not None:
            self.clay.fly(dt)
            if self.clay.flying() and self.clay.pos.y <= 0:
                pass
            if self.clay.result is None and self.clay.pos.y <= 0:   # 地面に落ちた
                self.settle("miss")
                happened = "miss"
            if self.clay.result is not None and self.time - self.clay.done_at > 1.2:
                self.clay = None
                if self.thrown >= ROUND:
                    self.over = True
                    return "end"
                self.pull_at = self.time + self.luck.uniform(0.4, 1.3)
        elif self.time >= self.pull_at:
            self.clay = self.launch()
            self.thrown += 1
            self.shots_left = SHOTS
            happened = "pull"
        return happened

    def status_text(self) -> str:
        return f"{self.thrown}/{ROUND} 枚  命中 {self.hits}  点 {self.score}"


def fog(color: tuple[int, int, int], z: float) -> tuple[int, int, int]:
    amount = max(0.0, min(0.85, (z - FOG_FROM) / (FAR - FOG_FROM)))
    return tuple(int(c + (b - c) * amount) for c, b in zip(color, SKY))


def shade(base: tuple[int, int, int], normal: V, z: float = 0.0) -> tuple[int, int, int]:
    light = V(*LIGHT_DIR).unit()
    bright = 0.4 + 0.6 * max(0.0, normal.dot(light))
    return fog(tuple(min(255, int(c * bright)) for c in base), z)


def draw_solid(screen: Screen, points: list[V], faces: list[tuple[int, ...]], color: tuple[int, int, int],
               colors: list[tuple[int, int, int]] | None = None, flat: bool = False) -> None:
    """立体をひとつ描く。こちらを向いた面だけを奥から。NEAR をまたぐ面は切る（g79 と同じ）。
    flat なら陰影を付けない（皿は小さいので、暗くなると見えなくなる）。"""
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
        paint = colors[k] if colors else color
        drawn.append((depth, [project(p, scale) for p in poly], fog(paint, depth) if flat else shade(paint, normal, depth)))
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


def box(w: float, h: float, length: float, at: V) -> tuple[list[V], list[tuple[int, ...]]]:
    points = [at + V(x * w / 2, y * h / 2 + h / 2, z * length / 2) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]
    faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    return points, outward(points, faces)


DISC = [V(math.cos(a) * CLAY_R, 0.0, math.sin(a) * CLAY_R) for a in (i * math.tau / 10 for i in range(10))]


DISC_FACES = [tuple(range(10)), tuple(reversed(range(10)))]   # 表と裏（どちらか一方だけこちらを向く）


TREES = [(a, 95 + 25 * math.sin(a * 5), "conifer" if k % 3 else "broadleaf", 0.8 + 0.5 * math.sin(a * 7))
         for k, a in enumerate(i * math.tau / 28 + 0.1 for i in range(28))]   # (向き, 距離, 種類, 大きさ)


def ridge(angle: float, layer: int) -> float:
    if layer == 0:
        return 5.0 + 3.6 * math.sin(angle * 3 + 0.4) + 2.4 * math.sin(angle * 7 + 2.0) + 1.2 * math.sin(angle * 13)
    return 2.0 + 2.0 * math.sin(angle * 4 + 1.1) + 1.4 * math.sin(angle * 9 + 0.3) + 0.8 * math.sin(angle * 17 + 2.5)


def draw_backdrop(screen: Screen, cam: Camera) -> None:
    """空 → 雲 → 山 → 地面。地平線は pitch で上下する。山と雲は yaw で横に流れる。"""
    scale = screen.width / WIDTH
    far = view(V(math.sin(cam.yaw) * 1e5, EYE, math.cos(cam.yaw) * 1e5), cam)   # 地平線の点
    horizon = int(project(far, scale)[1]) if far.z > 0 else screen.height
    horizon = max(0, min(screen.height, horizon))
    for y in range(horizon):
        t = y / max(1, horizon)
        screen.band(y, y + 1, tuple(int(a + (b - a) * t) for a, b in zip(SKY_TOP, SKY)))
    screen.band(horizon, screen.height, GRASS_FAR)
    for k in range(9):
        angle = k * math.tau / 9 + 0.3
        dx = math.remainder(angle - cam.yaw, math.tau)
        if abs(dx) > 0.7:
            continue
        cx = (CX + FOCUS * math.tan(dx)) * scale
        cy = horizon - (30 + 8 * math.sin(k * 2.1)) * scale
        rx, ry = (9 + 3 * math.sin(k * 1.7)) * scale, 2.8 * scale
        ring = [(cx + rx * math.cos(a), cy + ry * math.sin(a)) for a in (i * math.tau / 10 for i in range(10))]
        screen.fill(ring, CLOUD)
    step = int(6 * scale)
    for layer, color in ((0, MOUNTAIN_FAR), (1, MOUNTAIN_NEAR)):
        xs = list(range(0, screen.width + step, step))
        heights = [ridge(cam.yaw + math.atan((x / scale - CX) / FOCUS), layer) * scale for x in xs]
        for x0, x1, h0, h1 in zip(xs, xs[1:], heights, heights[1:]):
            screen.fill([(x0, horizon - h0), (x1, horizon - h1), (x1, horizon + 1), (x0, horizon + 1)], color)


def draw_ground(screen: Screen, cam: Camera) -> None:
    """地面。10 m ごとの帯（色を交互に）で距離が分かるように。手前 100 m まで。"""
    scale = screen.width / WIDTH
    for k in range(9, -1, -1):                      # 奥から
        z0, z1 = k * 10.0, k * 10.0 + 10.0
        quad = [view(V(-160, 0, z0), cam), view(V(160, 0, z0), cam), view(V(160, 0, z1), cam), view(V(-160, 0, z1), cam)]
        if max(p.z for p in quad) < NEAR:
            continue
        depth = max(NEAR, sum(p.z for p in quad) / 4)
        draw_quad(screen, quad, fog(GRASS_A if k % 2 else GRASS_B, depth), scale)
    back = [view(V(-160, 0, -40), cam), view(V(160, 0, -40), cam), view(V(160, 0, 0), cam), view(V(-160, 0, 0), cam)]
    draw_quad(screen, back, GRASS_B, scale)


def draw_tree(screen: Screen, base: V, kind: str, size: float, scale: float) -> None:
    if base.z < NEAR + 1:
        return
    z = base.z
    trunk = [V(base.x - 0.25, base.y, z), V(base.x + 0.25, base.y, z), V(base.x + 0.25, base.y + 2.0 * size, z), V(base.x - 0.25, base.y + 2.0 * size, z)]
    screen.fill([project(p, scale) for p in trunk], fog(TRUNK, z))
    if kind == "conifer":
        for w, y0, y1, tone_ in ((2.4, 1.2, 4.0, 0.7), (1.8, 2.6, 5.4, 0.85), (1.2, 4.0, 7.0, 1.0)):
            tri = [V(base.x - w * size, base.y + y0 * size, z), V(base.x + w * size, base.y + y0 * size, z), V(base.x, base.y + y1 * size, z)]
            screen.fill([project(p, scale) for p in tri], fog(tuple(int(c * tone_) for c in CROWN), z))
    else:
        for dx, dy, r, tone_ in ((0.0, 4.2, 2.8, 0.72), (-0.6, 4.7, 2.1, 1.0)):
            ring = [V(base.x + dx + r * size * math.cos(a), base.y + dy * size + r * size * 0.85 * math.sin(a), z)
                    for a in (i * math.tau / 10 for i in range(10))]
            screen.fill([project(p, scale) for p in ring], fog(tuple(int(c * tone_) for c in LEAF), z))


def draw_clay(screen: Screen, clay: Clay, cam: Camera) -> None:
    """皿。回りながら飛ぶ薄い円盤（表は明るく、裏は暗い）。割れたら破片。"""
    if clay.result is None or clay.result == "miss":
        tilt = 0.35 + 0.15 * math.sin(clay.spin * 0.7)
        placed = [view(rotate(rotate(p, 0.0, clay.spin, 0.0), tilt, 0.0, 0.0) + clay.pos, cam) for p in DISC]
        draw_solid(screen, placed, DISC_FACES, CLAY, [CLAY, CLAY_UNDER], flat=True)
    scale = screen.width / WIDTH
    for p, _ in clay.pieces:
        q = view(p, cam)
        if q.z > NEAR:
            x, y = project(q, scale)
            screen.plot(int(x), int(y), PIECE)
            screen.plot(int(x) + 1, int(y), PIECE)


def draw_gun(screen: Screen, world: World) -> None:
    """銃身。カメラに付いているので、カメラ座標に直接置く（回さない）。反動で下から跳ね上がる。"""
    scale = screen.width / WIDTH
    kick = world.recoil * 0.1
    root = V(0.34, -0.62 + kick, 1.0)               # 手元（右下）
    tip = V(0.03, -0.10 + kick * 0.4, 3.0)          # 銃口（照準の少し下）
    for dx, dy, color in ((0.0, 0.0, BARREL), (-0.02, 0.03, BARREL_LIGHT)):   # 上下 2 連。上の銃身は明るく
        quad = [root + V(dx - 0.075, dy, 0), root + V(dx + 0.075, dy, 0), tip + V(dx + 0.028, dy * 0.4, 0), tip + V(dx - 0.028, dy * 0.4, 0)]
        screen.fill([project(p, scale) for p in quad], color)
    stock = [root + V(-0.12, -0.12, -0.05), root + V(0.22, -0.12, -0.05), root + V(0.16, 0.06, 0), root + V(-0.06, 0.06, 0)]
    screen.fill([project(p, scale) for p in stock], STOCK)
    if world.flash > 0:                             # 発砲の光
        ring = [tip + V(0.07 * math.cos(a), 0.02 + 0.07 * math.sin(a), 0) for a in (i * math.tau / 8 for i in range(8))]
        screen.fill([project(p, scale) for p in ring], FLASH)
    cx, cy = CX * scale, CY * scale                 # 照準（十字。真ん中は空ける）
    gap, arm = int(2 * scale), int(6 * scale)
    screen.line((cx - gap - arm, cy), (cx - gap, cy), CROSS)
    screen.line((cx + gap, cy), (cx + gap + arm, cy), CROSS)
    screen.line((cx, cy - gap - arm), (cx, cy - gap), CROSS)
    screen.line((cx, cy + gap), (cx, cy + gap + arm), CROSS)


def draw(screen: Screen, world: World) -> None:
    """空・山 → 地面 → 木と放出機（奥から）→ 皿 → 銃と照準。"""
    scale = screen.width / WIDTH
    cam = world.cam
    draw_backdrop(screen, cam)
    draw_ground(screen, cam)
    things = []
    for angle, dist, kind, size in TREES:
        base = view(V(math.sin(angle) * dist, 0.0, math.cos(angle) * dist), cam)
        if NEAR < base.z < FAR + 30:
            things.append((base.z, "tree", (base, kind, size)))
    houses = [V(*TRAP)] + ([V(*SKEET_HIGH), V(*SKEET_LOW)] if world.mode == "skeet" else [])
    for at in houses:
        things.append((view(at, cam).z, "house", at))
    for z, kind, thing in sorted(things, key=lambda t: -t[0]):
        if kind == "tree":
            draw_tree(screen, *thing, scale)
        else:
            at = thing
            points, faces = box(2.4, 1.2 if at.z > 10 else 3.0, 2.0, V(at.x, 0.0, at.z))
            draw_solid(screen, [view(p, cam) for p in points], faces, HOUSE)
            roof, rf = box(2.7, 0.2, 2.3, V(at.x, 1.2 if at.z > 10 else 3.0, at.z))
            draw_solid(screen, [view(p, cam) for p in roof], rf, HOUSE_ROOF)
    if world.clay is not None:
        draw_clay(screen, world.clay, cam)
    draw_gun(screen, world)


def obey(world: World, key: str, down: bool = True) -> str | None:
    """キーを 1 つ受ける。矢印は照準、fire は撃つ、go は始める。撃った結果の出来事を返す。"""
    v = 1.0 if down else 0.0
    nudge = {"left": (-1, 0), "right": (1, 0), "up": (0, 1), "down": (0, -1)}.get(key)
    if nudge and down and world.started and not world.over:   # 押した瞬間に少しだけ動く（押し始めだけ）
        was = world.turn.x if nudge[0] else world.turn.y
        if was == 0.0:
            yaw = world.cam.yaw + nudge[0] * NUDGE
            pitch = max(PITCH_LIMIT[0], min(PITCH_LIMIT[1], world.cam.pitch + nudge[1] * NUDGE * PITCH_GAIN))
            world.cam = Camera(world.cam.pos, yaw, pitch)
    if key == "left":
        world.turn = V(-v if down else (0.0 if world.turn.x < 0 else world.turn.x), world.turn.y, 0)
    elif key == "right":
        world.turn = V(v if down else (0.0 if world.turn.x > 0 else world.turn.x), world.turn.y, 0)
    elif key == "up":
        world.turn = V(world.turn.x, v if down else (0.0 if world.turn.y > 0 else world.turn.y), 0)
    elif key == "down":
        world.turn = V(world.turn.x, -v if down else (0.0 if world.turn.y < 0 else world.turn.y), 0)
    elif key == "fire" and down:
        if not world.started:
            world.started = True
            return None
        return world.fire()
    return None


# --- ここから下はブラウザ版だけ。CLI 版の run() / Screen.render() / Speaker / status() にあたる ---

SCALE = 3                                           # ブラウザは 3 倍の板（384 × 240）に描く
canvas = document.querySelector("#screen")
ctx = canvas.getContext("2d")
ctx.imageSmoothingEnabled = False
image = ctx.createImageData(WIDTH * SCALE, HEIGHT * SCALE)
count_label = document.querySelector("#count")
hits_label = document.querySelector("#hits")
score_label = document.querySelector("#score")
streak_label = document.querySelector("#streak")
shots_label = document.querySelector("#shots")
best_label = document.querySelector("#best")
fps_label = document.querySelector("#fps")
note_label = document.querySelector("#note")
message = document.querySelector("#message")
log_label = document.querySelector("#log")
again_button = document.querySelector("#again")
go_button = document.querySelector("#go")
fire_button = document.querySelector("#fire")
mode_buttons = document.querySelectorAll(".modes button")
SAVED = "g80-best"                                  # localStorage の鍵。CLI 版の records.json にあたる


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
    """ブラウザで音を出す係。出来事ごとの wav を data URI にして Audio に持たせておく。"""

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
    count_label.textContent = f"{world.thrown}/{ROUND}"
    hits_label.textContent = str(world.hits)
    score_label.textContent = str(world.score)
    streak_label.textContent = str(world.streak)
    shots_label.textContent = "●" * world.shots_left + "○" * (SHOTS - world.shots_left)
    best_label.textContent = str(best.score)
    log_label.textContent = " ".join(world.log)
    note_label.textContent = (world.note if world.time < world.note_until else "") or " "
    if world.over:
        message.textContent = (f"おわり。命中 {world.hits}/{ROUND}、点 {world.score}、最高 {world.best_streak} 連続"
                               + ("  ベスト更新！" if improved else ""))
    elif not world.started:
        message.textContent = "種目を選んで「スタート」。← → ↑ ↓（または画面をなぞる）で照準、「撃つ」（画面タップ・スペース）で 1 発。1 枚に 2 発まで"
    else:
        message.textContent = ""
    again_button.hidden = not world.over
    go_button.hidden = world.started
    fire_button.hidden = not world.started or world.over
    for button in mode_buttons:
        button.classList.toggle("go", button.getAttribute("data-mode") == world.mode)
        button.disabled = world.started


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
            if event == "end":                      # ラウンドが終わった瞬間にベストへ取り込んで保存
                improved = best.take(world.hits, world.score)
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
        "a": "left", "d": "right", "w": "up", "s": "down", " ": "fire", "Enter": "fire"}


@when("keydown", "body")
def on_down(event):
    key = KEYS.get(event.key)
    if key is not None:
        event.preventDefault()
        if event.repeat:                            # 押しっぱなしの繰り返しは無視（押し始めだけ 1 回ぶん動く）
            return
        speaker.say(obey(world, key, True))


@when("keyup", "body")
def on_up(event):
    key = KEYS.get(event.key)
    if key is not None:
        event.preventDefault()
        obey(world, key, False)


@when("click", "#go")
def go(event):
    obey(world, "fire")                             # 最初の 1 回は「始める」
    go_button.blur()
    refresh()


@when("click", "#fire")
def fire(event):
    speaker.say(obey(world, "fire"))
    fire_button.blur()


@when("click", ".modes button")
def choose_mode(event):
    if not world.started:
        world.mode = event.target.getAttribute("data-mode")
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


drag = {"x": 0.0, "y": 0.0, "moved": 0.0, "on": False}
DRAG_GAIN = 0.0045                                  # 画面 1 ドット（CSS px）あたりの角度（ラジアン）


@when("pointerdown", "#screen")
def screen_down(event):
    """画面をなぞると照準が動く。動かさずに離せば撃つ。"""
    event.preventDefault()
    drag.update(x=event.clientX, y=event.clientY, moved=0.0, on=True)
    canvas.setPointerCapture(event.pointerId)


@when("pointermove", "#screen")
def screen_move(event):
    if not drag["on"] or not world.started:
        return
    dx, dy = event.clientX - drag["x"], event.clientY - drag["y"]
    drag.update(x=event.clientX, y=event.clientY, moved=drag["moved"] + abs(dx) + abs(dy))
    yaw = world.cam.yaw + dx * DRAG_GAIN
    pitch = max(PITCH_LIMIT[0], min(PITCH_LIMIT[1], world.cam.pitch - dy * DRAG_GAIN * PITCH_GAIN))
    world.cam = Camera(world.cam.pos, yaw, pitch)


@when("pointerup", "#screen")
def screen_up(event):
    if not drag["on"]:
        return
    drag["on"] = False
    if drag["moved"] < 6:
        speaker.say(obey(world, "fire"))


@when("click", "#again")
def again(event):
    global world, improved
    world = World(seed=int(window.performance.now()), mode=world.mode)
    world.started = True
    improved = False
    refresh()


document.querySelector("#loading").hidden = True
refresh()
asyncio.ensure_future(loop())
