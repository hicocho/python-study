"""物理の積み木（パチンコで崩す）ブラウザ版

CLI 版（g66-physics-slingshot/main.py）と中身はまったく同じ。物理（分離軸・撃力・
摩擦・眠り）も、面の表も、標的の割れ方も、得点の内訳も、キーの受け方（obey）も
1 文字も変えずに持ってきている。

持ってこなかったのは端末に描く Screen.render() と、それを使う play() /
read_keys() / check_terminal() と、自動プレイと検査、そして**記録の置き場所**だけ。
CLI 版は main.py の隣の records.json、こちらは localStorage（このブラウザの中だけ）。
"""

import asyncio
import json
import math
from bisect import insort
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, IntEnum
from itertools import combinations, groupby
from math import cos, inf, isclose, remainder, sin, tau
from typing import NamedTuple

from js import localStorage, window
from pyscript import document, when

WIDTH = 126                                         # 画面の横（ドット）。端末では 1 ドット = 1 桁


HEIGHT = 80                                         # 縦。端末では 2 ドット = 1 行 → 40 行


FLOOR_Y = 72.0                                      # 床の高さ


WALL_L = 2.0                                        # 左の壁


WALL_R = WIDTH - 2.0                                # 右の壁


FPS = 60


STEP = 1 / FPS                                      # 物理を進める刻み。時計の速さで変えない


SUBSTEPS = 4                                        # 1 コマを何回に割って解くか


ITERATIONS = 8                                      # 接触を何周なだめるか。積むにはこれが要る


BREAK = 90.0                                        # 標的が割れる衝撃。測って決めた


SLING = complex(12, 62)                             # パチンコの位置（左下）


POWERS = (140.0, 200.0, 260.0, 320.0)               # 強さは 4 段階


ANGLES = tuple(range(-70, -9, 5))                   # 上向きの角度（度）。−70 が高い山なり


SETTLE_WAIT = 2.5                                   # 撃ったあと、静かになるまで待つ上限（秒）


GRAVITY = complex(0, 260.0)                         # 下向き。複素数の虚部が下


BOUNCE = 0.05                                       # 反発係数。積み木なので低い（g64 は 0.28）


FRICTION = 0.55                                     # 接している面のすべりにくさ


CORRECTION = 0.35                                   # めり込みを 1 コマでどれだけ押し戻すか


SLOP = 0.05                                         # これくらいのめり込みは直さない（直しすぎると震える）


SLEEP_SPEED = 3.0                                   # これより遅ければ「止まった」とみなす


WAKE_SPEED = 20.0                                   # これより強くぶつかったときだけ目を覚ます


SLEEP_SPIN = 0.25


SLEEP_TIME = 0.4                                    # その状態がこれだけ続いたら眠らせる


PRIZE_COLORS = {100: (150, 110, 70), 250: (170, 175, 185), 500: (225, 190, 70)}


STONE = (200, 205, 215)                             # 撃つ石


AIM = (120, 130, 160)                               # ねらいの点線


SKY = (24, 26, 38)


GROUND = (86, 70, 52)


GROUND_LINE = (120, 100, 74)


BOX_COLORS = ((214, 118, 88), (196, 168, 92), (110, 170, 130), (120, 150, 210), (190, 130, 180))


DIM = 0.55                                          # 眠っている箱はこの明るさに落とす


EDGE = (250, 250, 240)


def dot(a: complex, b: complex) -> float:
    """内積。複素数なら conjugate をかけた実部がそれになる。"""
    return (a.conjugate() * b).real


def cross(a: complex, b: complex) -> float:
    """外積（2 次元なので大きさだけの数）。同じかけ算の虚部がそれになる。"""
    return (a.conjugate() * b).imag


@dataclass(slots=True)
class Body:
    """剛体の箱 1 つ。位置と速度に加えて、向きと角速度を持つ。

    slots=True にすると __dict__ を持たなくなる。属性が固定されるかわりに
    読み書きが速くなる。今回は 1 コマで数千回 pos や vel を触るので効く。
    """

    pos: complex
    half: complex                                   # 箱の半分の大きさ（横, 縦）
    vel: complex = 0j
    angle: float = 0.0                              # 向き（ラジアン）
    spin: float = 0.0                               # 角速度（ラジアン/秒）
    mass: float = 1.0                               # inf なら「絶対に動かない」（床と壁）
    color: int = 0
    still: float = 0.0                              # 動かないまま経った秒数
    asleep: bool = False
    prize: "Prize | None" = None                    # 標的なら、その種類（＝点数）
    stone: bool = False                             # 撃った石か
    shock: float = 0.0                              # このコマに受けた衝撃の合計

    @property
    def inertia(self) -> float:
        """回りにくさ。長方形は m(w² + h²)/12。細長いほど、長い向きに回しにくい。"""
        w, h = 2 * self.half.real, 2 * self.half.imag
        return self.mass * (w * w + h * h) / 12

    @property
    def inv_mass(self) -> float:
        """質量の逆数。mass が inf なら ちょうど 0.0 になる ＝ どんな力でも動かない。"""
        return 1 / self.mass

    @property
    def inv_inertia(self) -> float:
        """回りにくさの逆数。こちらも inf の体では 0.0 になる。"""
        return 1 / self.inertia

    @property
    def fixed(self) -> bool:
        return self.mass == inf

    @property
    def rotation(self) -> complex:
        """向きを表す単位複素数。これをかけると回る（g16 と同じ手）。"""
        return complex(math.cos(self.angle), math.sin(self.angle))

    def corners(self) -> list[complex]:
        """4 すみの位置。箱の中心から、回した半径ぶん離れた所。"""
        rot = self.rotation
        return [self.pos + rot * complex(sx * self.half.real, sy * self.half.imag)
                for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]

    def local(self, point: complex) -> complex:
        """世界の点を、箱の向きに戻した座標へ。逆回転は conjugate をかけるだけ。"""
        return (point - self.pos) * self.rotation.conjugate()

    def contains(self, point: complex) -> bool:
        """その点が箱の中か。向きを戻してしまえば、比べるのは 2 つだけ。"""
        inside = self.local(point)
        return abs(inside.real) <= self.half.real and abs(inside.imag) <= self.half.imag

    def extent(self, axis: complex) -> float:
        """その向きに箱を影として落としたときの、中心から端までの長さ。

        箱の 2 辺のベクトルを軸に射影して、絶対値で足す。どちらへ回っていても、
        「いちばん飛び出しているすみ」までの長さになる。
        """
        rot = self.rotation
        return (abs(dot(rot * self.half.real, axis))
                + abs(dot(rot * 1j * self.half.imag, axis)))

    def velocity_at(self, point: complex) -> complex:
        """箱の上のある点が、今どちらへどれだけ動いているか。

        中心の速度に、回転ぶんを足す。2 次元では ω × r が「r を 90 度回して ω 倍」
        になるので、複素数なら spin * 1j * r で書ける。
        """
        return self.vel + self.spin * 1j * (point - self.pos)

    def push(self, point: complex, impulse: complex) -> None:
        """ある点を、ある向きに突く。中心の速度と回転の両方が変わる。

        割り算ではなく逆数のかけ算にしてある。動かない体は逆数が 0 なので、
        「動かない」を if で書かずに済む。
        """
        r = point - self.pos
        self.vel += impulse * self.inv_mass
        self.spin += cross(r, impulse) * self.inv_inertia
        self.shock += abs(impulse)                  # 割れるかの判定に使う

    def wake(self) -> None:
        if self.fixed:                              # 床と壁は起こさない（起きても意味がない）
            return
        self.asleep = False
        self.still = 0.0

    def step(self, dt: float) -> None:
        """dt 秒ぶん進める。眠っている箱は動かさない。"""
        if self.asleep:
            return
        self.vel += GRAVITY * dt
        self.pos += self.vel * dt
        self.angle = remainder(self.angle + self.spin * dt, tau)     # −π〜π に畳む

    def settle(self, dt: float) -> None:
        """ほとんど動かない状態が続いたら眠らせる。眠ると計算からも外れる。"""
        if abs(self.vel) < SLEEP_SPEED and abs(self.spin) < SLEEP_SPIN:
            self.still += dt
            if self.still > SLEEP_TIME:
                self.asleep = True
                self.vel, self.spin = 0j, 0.0
        else:
            self.still = 0.0


def make_box(x: float, y: float, w: float, h: float, angle: float = 0.0,
             mass: float | None = None) -> Body:
    """置く場所と大きさから箱を 1 つ。重さは面積に比例させる。"""
    half = complex(w / 2, h / 2)
    return Body(pos=complex(x, y), half=half, angle=angle,
                mass=w * h / 40 if mass is None else mass)


class Prize(IntEnum):
    """標的の種類。**値がそのまま点数**なので、取った標的を sum() すれば合計になる。

    ふつうの Enum と違って int そのものなので、足し算も比較もそのままできる。
    「種類」と「点数」を別々に持つと、必ずどちらかを直し忘れる。
    """

    WOOD = 100
    STONE = 250
    GOLD = 500


class Phase(Enum):
    """今どの場面か。ねらう → 飛んでいる → 片づけ → クリア / おしまい。"""

    AIM = "ねらう"
    FLY = "とんでいる"
    CLEAR = "クリア"
    OVER = "おしまい"


@dataclass(frozen=True)
class Stage:
    """1 面。積んである箱と、標的の置き場所と、撃てる回数。"""

    name: str
    blocks: tuple[tuple[float, float, float, float], ...]
    prizes: tuple[tuple[float, float, Prize], ...]
    shots: int


STAGES = (
    Stage("かべ",
          blocks=((66, 68, 4, 8), (66, 60, 4, 8), (66, 52, 4, 8),
                  (100, 68, 4, 8), (100, 60, 4, 8), (100, 52, 4, 8),
                  (83, 46, 40, 4)),
          prizes=((76, 69, Prize.STONE), (90, 69, Prize.STONE), (83, 41, Prize.GOLD)),
          shots=3),
    Stage("とう",
          blocks=((86, 70, 22, 4), (78, 64, 5, 8), (94, 64, 5, 8),
                  (86, 58, 18, 4), (80, 52, 5, 8), (92, 52, 5, 8),
                  (86, 46, 14, 4), (86, 40, 5, 8)),
          prizes=((86, 33, Prize.GOLD), (86, 65, Prize.WOOD), (86, 53, Prize.STONE)),
          shots=3),
    Stage("やぐら",
          blocks=((70, 68, 6, 8), (94, 68, 6, 8),
                  (82, 62, 32, 4),
                  (74, 56, 6, 8), (90, 56, 6, 8),
                  (82, 50, 24, 4)),
          prizes=((82, 45, Prize.WOOD), (78, 69, Prize.WOOD), (86, 69, Prize.STONE)),
          shots=4),
)


WALLS = (
    (WIDTH / 2, FLOOR_Y + 20, WIDTH + 40, 40),      # 床
    (WALL_L - 20, HEIGHT / 2, 40, HEIGHT * 3),      # 左の壁
    (WALL_R + 20, HEIGHT / 2, 40, HEIGHT * 3),      # 右の壁
)


class Contact(NamedTuple):
    """1 点の接触。どの 2 つが、どこで、どちら向きに、どれだけ重なっているか。

    NamedTuple なので tuple そのもの。作るのが速く、書き換えられない。
    1 コマに何百個も作っては捨てるものなので、軽さがそのまま速さになる。
    """

    a: Body
    b: Body
    point: complex
    normal: complex                                 # a から b へ押し出す向き（長さ 1）
    depth: float                                    # 重なっている深さ


def overlap(a: Body, b: Body) -> tuple[float, complex] | None:
    """分離軸法。2 つの箱の重なりを (深さ, 法線) で返す。離れていれば None。

    調べる軸は 4 本（両方の箱の、縦と横の向き）。**どれか 1 本でも隙間があれば、
    その 1 本が「離れている証拠」**になるので、そこで打ち切ってよい。
    全部が重なっていたときは、いちばん浅い軸が押し返す向きになる。
    """
    between = b.pos - a.pos
    found = []
    for body in (a, b):
        for axis in (body.rotation, body.rotation * 1j):
            gap = a.extent(axis) + b.extent(axis) - abs(dot(between, axis))
            if gap <= 0:
                return None                         # 隙間があった ＝ 当たっていない
            found.append((gap, axis if dot(between, axis) > 0 else -axis))
    return min(found, key=lambda pair: pair[0])     # いちばん浅い重なりが、押し返す向き


def contacts(a: Body, b: Body):
    """接触点を 0〜2 個ずつ返す。当たっていなければ何も返さない。

    ジェネレータにしてあるので、呼ぶ側は「当たったかどうか」を気にせず for で回せる。
    点は「相手の中に入っているすみ」。箱が箱の上に載っているときは、
    上の箱の下 2 すみが下の箱に入るので、ちょうど 2 点になる。
    """
    hit = overlap(a, b)
    if hit is None:
        return
    depth, normal = hit
    points = [c for c in a.corners() if b.contains(c)]
    points += [c for c in b.corners() if a.contains(c)]
    for point in points[:2]:                        # 3 つ以上は角どうしの深い重なりだけ。2 点で足りる
        yield Contact(a, b, point, normal, depth)


def resolve(hit: Contact) -> None:
    """接触 1 点を、撃力で解く。g64 の bounce_off を 2 体ぶんに広げたもの。

    片方が動かない体（逆数が 0）なら、g64 とまったく同じ式に戻る。
    """
    a, b = hit.a, hit.b
    ra, rb = hit.point - a.pos, hit.point - b.pos
    relative = b.velocity_at(hit.point) - a.velocity_at(hit.point)
    vn = dot(relative, hit.normal)
    if vn > 0:                                      # 離れていく向きなら、もう触らない
        return
    j = -(1 + BOUNCE) * vn / share(a, b, ra, rb, hit.normal)
    a.push(hit.point, -j * hit.normal)
    b.push(hit.point, j * hit.normal)
    # 摩擦。面に沿った向きに、跳ね返りの強さに比例した分だけ
    tangent = hit.normal * 1j
    vt = dot(b.velocity_at(hit.point) - a.velocity_at(hit.point), tangent)
    jt = -vt / share(a, b, ra, rb, tangent)
    jt = max(-FRICTION * j, min(FRICTION * j, jt))  # クーロン摩擦の頭打ち
    a.push(hit.point, -jt * tangent)
    b.push(hit.point, jt * tangent)
    if vn < -WAKE_SPEED:                            # しっかりぶつかったときだけ目を覚ます
        a.wake()
        b.wake()


def share(a: Body, b: Body, ra: complex, rb: complex, axis: complex) -> float:
    """その向きに突いたとき、2 つの体がどれだけ動きやすいか（撃力の式の分母）。

    動かない体はここに 0 しか足さないので、相手だけが動く形になる。
    """
    return (a.inv_mass + b.inv_mass
            + cross(ra, axis) ** 2 * a.inv_inertia
            + cross(rb, axis) ** 2 * b.inv_inertia)


def nudge(hit: Contact) -> None:
    """動いている相手に触られた、眠っている箱を起こす。

    **「眠っているものだけ」を起こすのが肝。** 起きている箱に wake() を呼ぶと
    「動かないまま経った秒数」が毎コマ 0 に戻り、塔が永遠に眠れなくなる
    （g64 で「触れているだけで起こすと眠れない」を踏んだのと同じ形）。
    """
    for one, other in ((hit.a, hit.b), (hit.b, hit.a)):
        if one.asleep and not other.asleep and abs(other.vel) > SLEEP_SPEED:
            one.wake()


def separate(hit: Contact) -> None:
    """めり込みを、動きやすさに応じて分けて押し戻す。

    軽い箱の方が大きく動く。動かない体は逆数が 0 なので、まったく動かない。
    """
    total = hit.a.inv_mass + hit.b.inv_mass
    if total == 0:
        return
    push = hit.normal * max(hit.depth - SLOP, 0.0) * CORRECTION / total
    hit.a.pos -= push * hit.a.inv_mass
    hit.b.pos += push * hit.b.inv_mass


@dataclass
class World:
    """1 面ぶんの世界。箱の物理は g65 のまま、上に「撃つ・割る・数える」を載せる。"""

    level: int = 0
    boxes: list[Body] = field(default_factory=list)
    walls: list[Body] = field(default_factory=list)
    taken: list[Prize] = field(default_factory=list)
    time: float = 0.0
    shots: int = 0
    phase: Phase = Phase.AIM
    angle: int = 6                                  # ANGLES の何番目か
    power: int = 2                                  # POWERS の何番目か
    quiet: float = 0.0                              # 静かになってから経った秒数
    score: int = 0

    def __post_init__(self) -> None:
        self.build()

    @property
    def stage(self) -> Stage:
        return STAGES[min(self.level, len(STAGES) - 1)]

    def build(self) -> None:
        """今の面を組み立て直す。撃った石も標的も、ここで作り直される。"""
        stage = self.stage
        self.boxes = [make_box(*row) for row in stage.blocks]
        for i, box in enumerate(self.boxes):
            box.color = i % len(BOX_COLORS)
        for x, y, kind in stage.prizes:
            box = make_box(x, y, 6, 6)
            box.prize = kind
            self.boxes.append(box)
        self.walls = [make_box(*row, mass=inf) for row in WALLS]
        for wall in self.walls:
            wall.asleep = True                      # 動かない体は最初から眠っている扱い
        self.taken = []
        self.shots = stage.shots
        self.phase = Phase.AIM
        self.time = self.quiet = 0.0

    @property
    def bodies(self) -> list[Body]:
        return self.walls + self.boxes

    @property
    def left(self) -> int:
        """まだ残っている標的の数。"""
        return sum(b.prize is not None for b in self.boxes)

    def launch(self) -> None:
        """パチンコを離す。角度と強さから、石の速度を作る。"""
        if self.phase is not Phase.AIM or self.shots <= 0:
            return
        radians = math.radians(ANGLES[self.angle])
        speed = POWERS[self.power]
        stone = make_box(SLING.real, SLING.imag, 5, 5, mass=3.0)
        stone.vel = complex(cos(radians), sin(radians)) * speed
        stone.stone = True
        stone.color = 3
        self.boxes.append(stone)
        self.shots -= 1
        self.phase = Phase.FLY
        self.quiet = 0.0

    def flight(self, steps: int = 26, every: int = 3) -> list[complex]:
        """ねらいの見当。ぶつかりを無視して、重力だけで飛ばした点を並べる。

        当たり判定を通さないので本番とは少しずれるが、「どのあたりへ飛ぶか」は
        これで十分わかる。物理そのものを使わずに、同じ式だけを使うのが要点。
        """
        radians = math.radians(ANGLES[self.angle])
        vel = complex(cos(radians), sin(radians)) * POWERS[self.power]
        pos = SLING
        points = []
        for i in range(steps * every):
            vel += GRAVITY * STEP
            pos += vel * STEP
            if pos.imag > FLOOR_Y or not 0 < pos.real < WIDTH:
                break
            if i % every == 0:
                points.append(pos)
        return points

    def update(self, dt: float) -> None:
        """1 コマ。物理を進め、割れた標的を数え、場面を進める。"""
        self.time += dt
        piece = dt / SUBSTEPS
        for box in self.boxes:
            box.shock = 0.0                         # 衝撃はこのコマぶんだけ数える
        for _ in range(SUBSTEPS):
            for box in self.boxes:
                box.step(piece)
            found = self.find()
            for _ in range(ITERATIONS):             # 1 周では足りない。積むほど周が要る
                for hit in found:
                    resolve(hit)
            for hit in found:
                separate(hit)
            for hit in found:
                nudge(hit)                          # 動いている物に触られたら、こちらも起きる
        for box in self.boxes:
            box.settle(dt)
        self.crack()
        self.advance(dt)

    def crack(self) -> None:
        """強くぶつかった標的を割る。落ちてきた箱でも割れるので、連鎖が起きる。"""
        alive = []
        for box in self.boxes:
            if box.prize is not None and box.shock > BREAK:
                self.taken.append(box.prize)
                self.score += int(box.prize)        # IntEnum なので、そのまま足せる
            else:
                alive.append(box)
        self.boxes = alive

    def advance(self, dt: float) -> None:
        """場面を進める。静かになったら次の 1 発、標的が尽きたらクリア。"""
        if self.phase is not Phase.FLY:
            return
        self.quiet = self.quiet + dt if self.awake == 0 else 0.0
        if self.left == 0:
            self.score += self.shots * 100          # 残した弾はおまけ
            self.phase = Phase.CLEAR
        elif self.quiet > 0.5 or self.time > SETTLE_WAIT + 12:
            self.phase = Phase.AIM if self.shots > 0 else Phase.OVER

    def next_stage(self) -> None:
        """次の面へ。最後の面をクリアしたら、そこで打ち止め。"""
        if self.level + 1 < len(STAGES):
            self.level += 1
            self.build()

    def find(self) -> list[Contact]:
        """今ぶつかっている所を全部。combinations で「同じ組を 2 度見ない」。

        両方とも眠っているか、両方とも動かない体なら、見るだけ無駄なので飛ばす。
        """
        found = []
        for a, b in combinations(self.bodies, 2):
            if a.asleep and b.asleep:
                continue
            found.extend(contacts(a, b))
        return found

    @property
    def awake(self) -> int:
        return sum(not b.asleep for b in self.boxes)

    def energy(self) -> float:
        """全部の箱の運動エネルギー。増え続けていたら、どこかが壊れている。"""
        return sum(0.5 * b.mass * abs(b.vel) ** 2 + 0.5 * b.inertia * b.spin ** 2
                   for b in self.boxes)


def breakdown(taken: list[Prize]) -> list[tuple[str, int, int]]:
    """取った標的を種類ごとにまとめる。(名前, 個数, 小計) の一覧。

    **groupby は「並んでいるもの」しかまとめられない。** 撃った順のまま渡すと、
    金・木・金 が 3 組になってしまう。だから先に並べ替える。
    """
    rows = []
    for kind, group in groupby(sorted(taken, reverse=True)):
        got = list(group)
        rows.append((kind.name, len(got), sum(got)))
    return rows


@dataclass(frozen=True, order=True)
class Record:
    """1 回ぶんの記録。得点・面の名前・残した弾・いつ。"""

    score: int
    stage: str
    left: int
    when: str


def remember(rows: list[Record], record: Record, keep: int = 5) -> list[Record]:
    """記録を差し込む。**並べ直さず、並んだままの所へ挿す**（bisect.insort）。

    key に -score を渡すと、得点の高い順に並んだ列を保てる。
    毎回 sort し直しても結果は同じだが、insort は「どこへ入るか」を二分探索で
    見つけて挿すだけなので、列が長くなっても速い。
    """
    insort(rows, record, key=lambda r: -r.score)
    return rows[:keep]


class Screen:
    """WIDTH × HEIGHT のドットの板。1 ドットは RGB か None（黒）。"""

    def __init__(self):
        self.pixels: list[list[tuple[int, int, int] | None]] = [[None] * WIDTH for _ in range(HEIGHT)]

    def clear(self) -> None:
        for row in self.pixels:
            row[:] = [None] * WIDTH

    def plot(self, x: int, y: int, color: tuple[int, int, int]) -> None:
        if 0 <= x < WIDTH and 0 <= y < HEIGHT:
            self.pixels[y][x] = color


def fill_box(screen: Screen, body: Body, color: tuple[int, int, int]) -> None:
    """回った箱を塗る。

    回った四角形を「線で囲んで中を塗る」のは面倒だが、点の側を逆回転させれば
    軸に揃った四角形との比較で済む（Body.contains）。見る範囲は、すみの外接する枠だけ。
    """
    cs = body.corners()
    x0, x1 = int(min(c.real for c in cs)) - 1, int(max(c.real for c in cs)) + 2
    y0, y1 = int(min(c.imag for c in cs)) - 1, int(max(c.imag for c in cs)) + 2
    for y in range(y0, y1):
        for x in range(x0, x1):
            if body.contains(complex(x, y)):
                screen.plot(x, y, color)


def outline(screen: Screen, body: Body) -> None:
    """すみを結ぶ線。向きが分かるように、1 本だけ明るくする。"""
    cs = body.corners()
    for i, a in enumerate(cs):
        b = cs[(i + 1) % 4]
        line(screen, a, b, EDGE if i == 0 else tuple(v // 2 for v in EDGE))


def line(screen: Screen, a: complex, b: complex, color: tuple[int, int, int]) -> None:
    """2 点を結ぶ線。ブレゼンハム（g20 の視線と同じ）。"""
    x0, y0, x1, y1 = round(a.real), round(a.imag), round(b.real), round(b.imag)
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
    err = dx + dy
    while True:
        screen.plot(x0, y0, color)
        if (x0, y0) == (x1, y1):
            return
        step = 2 * err
        if step >= dy:
            err += dy
            x0 += sx
        if step <= dx:
            err += dx
            y0 += sy


def tint(box: Body) -> tuple[int, int, int]:
    """その箱を何色で塗るか。標的と石は特別、あとは番号どおり。"""
    if box.prize is not None:
        return PRIZE_COLORS[int(box.prize)]         # IntEnum なので、そのまま鍵に使える
    if box.stone:
        return STONE
    return BOX_COLORS[box.color]


def draw(screen: Screen, world: World) -> None:
    """1 コマぶん。空 → 地面 → パチンコ → ねらいの点線 → 箱。"""
    screen.clear()
    for y in range(HEIGHT):
        for x in range(WIDTH):
            screen.plot(x, y, GROUND if y > FLOOR_Y else SKY)
    for x in range(WIDTH):
        screen.plot(x, int(FLOOR_Y), GROUND_LINE)
    sling(screen, world)
    for box in world.boxes:
        color = tint(box)
        if box.asleep and box.prize is None:        # 眠っている箱は暗く。標的は目立たせたままにする
            color = tuple(int(v * DIM) for v in color)
        fill_box(screen, box, color)
        outline(screen, box)


def sling(screen: Screen, world: World) -> None:
    """パチンコの台と、ねらう向きの点線。ねらっているときだけ点線を出す。"""
    x, y = int(SLING.real), int(SLING.imag)
    for row in range(y, int(FLOOR_Y)):              # 台の柱
        screen.plot(x, row, GROUND_LINE)
        screen.plot(x + 1, row, GROUND_LINE)
    for dx, dy in ((-2, -2), (-2, -1), (3, -2), (3, -1)):   # 二股の腕
        screen.plot(x + dx, y + dy, GROUND_LINE)
    if world.phase is Phase.AIM:
        for point in world.flight():
            screen.plot(round(point.real), round(point.imag), AIM)
        for dx in (0, 1):                           # かけてある石
            for dy in (0, 1):
                screen.plot(x + dx, y + dy, STONE)


def obey(world: World, key: str) -> bool:
    """キー 1 つ。やめるなら False。端末でもブラウザでも同じ物を使う。"""
    match key:
        case "quit":
            return False
        case "reset":
            world.build()
        case "next":
            world.next_stage()
        case "shoot":
            if world.phase is Phase.CLEAR:
                world.next_stage()
            else:
                world.launch()
        case "up":
            world.angle = max(0, world.angle - 1)
        case "down":
            world.angle = min(len(ANGLES) - 1, world.angle + 1)
        case "stronger":
            world.power = min(len(POWERS) - 1, world.power + 1)
        case "weaker":
            world.power = max(0, world.power - 1)
    return True


# --- ここから下はブラウザ版だけ。CLI 版の play() / Screen.render() / 記録の読み書き ---

canvas = document.querySelector("#screen")
ctx = canvas.getContext("2d")
ctx.imageSmoothingEnabled = False
image = ctx.createImageData(WIDTH, HEIGHT)
stage_label = document.querySelector("#stage")
score_label = document.querySelector("#score")
shots_label = document.querySelector("#shots")
prizes_label = document.querySelector("#prizes")
aim_label = document.querySelector("#aim")
phase_label = document.querySelector("#phase")
board = document.querySelector("#board")
KEEP = "g66-records"


class CanvasScreen(Screen):
    """CLI 版の Screen をそのまま使い、描き終えた画素をまとめて canvas へ送る。"""

    def flush(self) -> None:
        buf = bytearray(WIDTH * HEIGHT * 4)
        i = 0
        for row in self.pixels:
            for color in row:
                if color is not None:
                    buf[i], buf[i + 1], buf[i + 2] = color
                buf[i + 3] = 255
                i += 4
        image.data.assign(bytes(buf))
        ctx.putImageData(image, 0, 0)


def load_records() -> list[Record]:
    """CLI 版は records.json、こちらは localStorage。読み方は同じ形にそろえてある。"""
    rows: list[Record] = []
    with suppress(Exception):
        saved = localStorage.getItem(KEEP)
        if saved:
            rows = [Record(**row) for row in json.loads(saved)]
    return rows


def save_records(rows: list[Record]) -> None:
    localStorage.setItem(KEEP, json.dumps([r.__dict__ for r in rows]))


screen = CanvasScreen()
world = World()
records = load_records()
kept = False                                        # この面の記録をもう残したか


def show_board() -> None:
    """得点の内訳と、上位 5 件の記録。CLI 版の --auto / --records にあたる。"""
    rows = [f"{name:6} × {count}  {total:5d} 点" for name, count, total in breakdown(world.taken)]
    if world.phase is Phase.CLEAR:
        rows.append(f"残した弾 {world.shots} × 100 点")
    best = [f"{i}. {r.score:5d} 点  {r.stage} まで  {r.when}" for i, r in enumerate(records, 1)]
    board.textContent = "\n".join(rows + ([""] if rows and best else []) + best)


def refresh() -> None:
    """CLI 版の play() の 1 周ぶん。共有部分に draw() があるので、この名前は使えない。"""
    draw(screen, world)
    screen.flush()
    stage_label.textContent = world.stage.name
    score_label.textContent = str(world.score)
    shots_label.textContent = str(world.shots)
    prizes_label.textContent = str(world.left)
    aim_label.textContent = f"{ANGLES[world.angle]:+d}° / 強 {world.power + 1}"
    phase_label.textContent = world.phase.value
    show_board()


def keep_record() -> None:
    """決着したら 1 回だけ記録する。"""
    global records, kept
    if kept or world.phase not in (Phase.CLEAR, Phase.OVER) or not world.score:
        return
    records = remember(records, Record(world.score, world.stage.name, world.shots,
                                       datetime.now().strftime("%Y-%m-%d %H:%M")))
    save_records(records)
    kept = True


async def loop():
    """刻み幅は CLI 版と同じ 1/FPS 秒に固定する（g64 で入れた）。"""
    lag = 0.0
    last = window.performance.now() / 1000
    while True:
        now = window.performance.now() / 1000
        lag = min(lag + now - last, 0.25)           # ためすぎない（重い端末で追いつけなくなる）
        last = now
        while lag >= STEP:
            world.update(STEP)
            lag -= STEP
        keep_record()
        refresh()
        await asyncio.sleep(STEP)


@when("click", ".pad")
def on_pad(event):
    """ボタンは入れ物の側で受ける（@when は登録時に在る要素にしか付かない）。"""
    global kept
    key = event.target.getAttribute("data-key")
    if key is None:
        return
    if key in ("reset", "next"):
        kept = False
    obey(world, key)                                # 判断は CLI 版と同じ関数
    refresh()


KEYS = {"ArrowLeft": "up", "ArrowRight": "down", "ArrowUp": "stronger",
        "ArrowDown": "weaker", " ": "shoot", "n": "next", "r": "reset"}


@when("keydown", "body")
def on_key(event):
    global kept
    key = KEYS.get(event.key)
    if key is None:
        return
    event.preventDefault()
    if key in ("reset", "next"):
        kept = False
    obey(world, key)


# Pyodide の読み込みが終わってから実行される＝ここが準備完了の合図
document.querySelector("#loading").hidden = True
refresh()
asyncio.ensure_future(loop())
