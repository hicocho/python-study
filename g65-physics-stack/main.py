"""物理の積み木 — 完成: 箱どうしがぶつかる。分離軸で重なりを見つけ、同じ撃力の式で押し返す。"""

import argparse
import math
import os
import random
import select
import shutil
import sys
import termios
import time
import tty
from dataclasses import dataclass, field
from itertools import combinations, starmap
from math import inf, isclose, remainder, tau
from typing import NamedTuple

WIDTH = 126                                         # 画面の横（ドット）。端末では 1 ドット = 1 桁
HEIGHT = 80                                         # 縦。端末では 2 ドット = 1 行 → 40 行
FLOOR_Y = 72.0                                      # 床の高さ
WALL_L = 2.0                                        # 左の壁
WALL_R = WIDTH - 2.0                                # 右の壁
FPS = 60
STEP = 1 / FPS                                      # 物理を進める刻み。時計の速さで変えない
SUBSTEPS = 4                                        # 1 コマを何回に割って解くか
ITERATIONS = 8                                      # 接触を何周なだめるか。積むにはこれが要る

GRAVITY = complex(0, 260.0)                         # 下向き。複素数の虚部が下
BOUNCE = 0.05                                       # 反発係数。積み木なので低い（g64 は 0.28）
FRICTION = 0.55                                     # 接している面のすべりにくさ
CORRECTION = 0.35                                   # めり込みを 1 コマでどれだけ押し戻すか
SLOP = 0.05                                         # これくらいのめり込みは直さない（直しすぎると震える）
SLEEP_SPEED = 3.0                                   # これより遅ければ「止まった」とみなす
WAKE_SPEED = 20.0                                   # これより強くぶつかったときだけ目を覚ます
SLEEP_SPIN = 0.25
SLEEP_TIME = 0.4                                    # その状態がこれだけ続いたら眠らせる

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


@dataclass(slots=True)                              # ←
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


# 積んである塔。(x, y, 幅, 高さ) を下から。柱・梁・柱・梁・かんむり。
TOWER = (
    (50, 68, 6, 8), (76, 68, 6, 8),                 # 1 段目の柱
    (63, 62, 34, 4),                                # 1 段目の梁
    (55, 56, 6, 8), (71, 56, 6, 8),                 # 2 段目の柱
    (63, 50, 26, 4),                                # 2 段目の梁
    (63, 45, 8, 6),                                 # かんむり
    (20, 68, 10, 8), (106, 68, 10, 8),              # 端に 1 つずつ
)

# 動かないもの。inf の質量を持つ、ただの大きな箱。
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


def nudge(hit: Contact) -> None:                    # ←
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
    """箱の入れ物。1 コマを SUBSTEPS 回に割り、接触を ITERATIONS 周なだめる。"""

    boxes: list[Body] = field(default_factory=list)
    walls: list[Body] = field(default_factory=list)
    time: float = 0.0

    def __post_init__(self) -> None:
        if not self.boxes:
            self.boxes = [make_box(*row) for row in TOWER]
        for i, box in enumerate(self.boxes):
            box.color = i % len(BOX_COLORS)
        self.walls = [make_box(*row, mass=inf) for row in WALLS]
        for wall in self.walls:
            wall.asleep = True                      # 動かない体は最初から眠っている扱い

    @property
    def bodies(self) -> list[Body]:
        return self.walls + self.boxes

    def drop(self, x: float, rng: random.Random) -> None:
        """上から箱を 1 つ落とす。"""
        w, h = rng.choice(((6, 8), (10, 4), (5, 5), (14, 3)))
        box = make_box(x, 6, w, h, angle=rng.uniform(-0.6, 0.6))
        box.color = len(self.boxes) % len(BOX_COLORS)
        box.vel = complex(rng.uniform(-15, 15), 40)
        self.boxes.append(box)

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

    def update(self, dt: float) -> None:
        """1 コマ。進める → 接触を探す → 何周かなだめる → めり込みを押し戻す。"""
        self.time += dt
        piece = dt / SUBSTEPS
        for _ in range(SUBSTEPS):
            for box in self.boxes:
                box.step(piece)
            found = self.find()
            for _ in range(ITERATIONS):             # 1 周では足りない。積むほど周が要る
                for hit in found:
                    resolve(hit)
            for hit in found:
                separate(hit)
            for hit in found:                       # ←
                nudge(hit)                          # ← 動いている物に触られたら、こちらも起きる
        for box in self.boxes:
            box.settle(dt)

    @property
    def awake(self) -> int:
        return sum(not b.asleep for b in self.boxes)

    def energy(self) -> float:
        """全部の箱の運動エネルギー。増え続けていたら、どこかが壊れている。"""
        return sum(0.5 * b.mass * abs(b.vel) ** 2 + 0.5 * b.inertia * b.spin ** 2
                   for b in self.boxes)

    def height(self) -> float:
        """いちばん高い箱の高さ（床から）。塔が崩れたかは、この数で分かる。"""
        return max((FLOOR_Y - min(c.imag for c in b.corners()) for b in self.boxes), default=0.0)


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

    def render(self) -> str:
        """端末用の文字列。1 行に 2 ドット分の行を詰める（上が前景 ▀、下が背景）。"""
        out = []
        last = None
        for top, bottom in zip(self.pixels[0::2], self.pixels[1::2]):
            for a, b in zip(top, bottom):
                if a is None and b is None:
                    code, ch = "\x1b[0m", " "
                elif b is None:
                    code, ch = f"\x1b[0m\x1b[38;2;{a[0]};{a[1]};{a[2]}m", "▀"
                elif a is None:
                    code, ch = f"\x1b[0m\x1b[38;2;{b[0]};{b[1]};{b[2]}m", "▄"
                else:
                    code, ch = f"\x1b[38;2;{a[0]};{a[1]};{a[2]}m\x1b[48;2;{b[0]};{b[1]};{b[2]}m", "▀"
                if code != last:
                    out.append(code)
                    last = code
                out.append(ch)
            out.append("\x1b[0m\n")
            last = None
        return "".join(out)


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


def draw(screen: Screen, world: World) -> None:
    """1 コマぶん。空 → 地面 → 箱。眠っている箱は灰色にする。"""
    screen.clear()
    for y in range(HEIGHT):
        for x in range(WIDTH):
            screen.plot(x, y, GROUND if y > FLOOR_Y else SKY)
    for x in range(WIDTH):
        screen.plot(x, int(FLOOR_Y), GROUND_LINE)
    for box in world.boxes:
        color = BOX_COLORS[box.color]
        if box.asleep:                              # 眠っている箱は暗く。色は変えないので、どれがどれか分かる
            color = tuple(int(v * DIM) for v in color)
        fill_box(screen, box, color)
        outline(screen, box)


def read_keys(fd: int) -> list[str]:
    """押されたキーを名前で。空白か下で箱を落とす、r でやり直し、q でやめる。"""
    keys = []
    while select.select([fd], [], [], 0)[0]:
        text = os.read(fd, 64).decode(errors="ignore")
        for token, name in ((" ", "drop"), ("\x1b[B", "drop"), ("r", "reset"), ("q", "quit"),
                            ("\x1b[D", "left"), ("\x1b[C", "right")):
            keys.extend([name] * text.count(token))
    return keys


def check_terminal() -> str | None:
    columns, lines = shutil.get_terminal_size()
    need = HEIGHT // 2 + 3
    if columns < WIDTH or lines < need:
        return f"端末を {WIDTH} 桁 × {need} 行以上にしてください（今は {columns} × {lines}）。"
    return None


def play(world: World, seed: int | None = None, auto: bool = False) -> None:
    """端末で遊ぶ。物理は STEP 秒ずつ、決まった幅で進める。

    経った時間をそのまま update() に渡すと、画面が重いときだけ物理が変わる。
    足りない時間はためておき、決まった幅で必要な回数だけ進める（g64 で入れた）。
    """
    rng = random.Random(seed)
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    tty.setcbreak(fd)
    screen = Screen()
    aim = WIDTH / 2
    lag = 0.0
    try:
        sys.stdout.write("\x1b[2J\x1b[?25l")
        last = time.monotonic()
        while True:
            now = time.monotonic()
            lag = min(lag + now - last, 0.25)       # ためすぎない（追いつけなくなる）
            last = now
            for key in read_keys(fd):
                match key:
                    case "quit":
                        return
                    case "reset":
                        world.__init__()
                    case "drop":
                        world.drop(aim, rng)
                    case "left":
                        aim = max(10, aim - 6)
                    case "right":
                        aim = min(WIDTH - 10, aim + 6)
            while lag >= STEP:                      # たまったぶんだけ、決まった幅で進める
                if auto and int(world.time * 2) != int((world.time + STEP) * 2):
                    world.drop(rng.uniform(20, WIDTH - 20), rng)
                world.update(STEP)
                lag -= STEP
            draw(screen, world)
            for y in (2, 3):                        # 落とす位置の目印
                screen.plot(int(aim), y, EDGE)
            sys.stdout.write("\x1b[H" + screen.render()
                             + f"\x1b[0m箱 {len(world.boxes):2d}   動いている {world.awake:2d}   "
                               f"塔の高さ {world.height():4.1f}   "
                               f"← → 位置  空白 落とす  r やり直し  q やめる\x1b[K\n")
            sys.stdout.flush()
            time.sleep(max(0.0, STEP - (time.monotonic() - now)))
    finally:
        sys.stdout.write("\x1b[0m\x1b[?25h")
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    print()


def tower_report(world: World, seconds: float = 8.0, dt: float = STEP) -> list[str]:
    """塔を建てて回し、上から 1 つ載せて、様子を書き出す。

    見るのは 5 つ。塔が自分から崩れないか、ぜんぶ眠るか、載せたら下の箱も起きるか、
    めり込みが浅いままか、落ち着いたあとに運動エネルギーが増えていないか。
    """
    out = []
    start = world.height()
    out.append(f"建てた直後    高さ {start:5.2f}  箱 {len(world.boxes)}")
    quiet, _ = run_until_quiet(world, seconds, dt)
    out.append(f"{quiet:5.2f} 秒で全部止まった" if quiet else "眠らなかった（震え続けている）")
    out.append(f"  高さ {world.height():5.2f}  いちばん深いめり込み "
               f"{max(deepest_overlap(world), default=0.0):.3f} ドット")
    world.drop(63.0, random.Random(0))              # 上から 1 つ載せてみる
    quiet, busiest = run_until_quiet(world, seconds, dt)
    out.append(f"1 つ落とすと  いちばん多いときで 動いている {busiest} / {len(world.boxes)}"
               f"（下の箱も目を覚ます）")
    out.append(f"{quiet:5.2f} 秒でまた全部止まった" if quiet else "落としたあと眠らなかった")
    out.append(f"  高さ {world.height():5.2f}  いちばん深いめり込み "
               f"{max(deepest_overlap(world), default=0.0):.3f} ドット")
    out.append(f"落ち着いたあとの運動エネルギー {world.energy():.2f}"
               + ("（力を作り出していない）" if isclose(world.energy(), 0.0, abs_tol=0.5)
                  else "（どこかで力を作っている）"))
    out.append(f"塔は自分から崩れていない: {'はい' if world.height() > start - 2.0 else 'いいえ'}")
    return out


def run_until_quiet(world: World, seconds: float, dt: float = STEP) -> tuple[float | None, int]:
    """全部眠るまで回す。返すのは (眠った時刻 か None, その間いちばん多かった起きている数)。"""
    busiest = 0
    for _ in range(int(seconds / dt)):
        world.update(dt)
        busiest = max(busiest, world.awake)
        if world.awake == 0:
            return world.time, busiest
    return None, busiest


def deepest_overlap(world: World):
    """今どれだけ食い込んでいるか。箱どうしの組だけを見る。"""
    for a, b in combinations(world.boxes, 2):
        hit = overlap(a, b)
        if hit is not None:
            yield hit[0]


def smash_report(world: World, seed: int | None = None) -> list[str]:
    """塔の上に重い塊を落として、崩れるかを見る。崩れなければ物理が固すぎる。

    「崩れた」は高さではなく、**元の場所から動いた箱の数**で見る。
    梁が斜めに立てかかると高さは残るので、高さだけでは崩れたか分からない。
    """
    out = []
    run_until_quiet(world, 4.0)
    before = [b.pos for b in world.boxes]
    out.append(f"建った        高さ {world.height():5.2f}  動いている {world.awake}")
    ball = make_box(63, 4, 12, 12, mass=40.0)       # 重い塊。同じ大きさの箱の 11 倍
    ball.vel = complex(0, 160)
    ball.color = 0
    world.boxes.append(ball)
    run_until_quiet(world, 10.0)
    moved = sum(abs(box.pos - was) > 3.0 for box, was in zip(world.boxes, before))
    out.append(f"ぶつけたあと  高さ {world.height():5.2f}  動いている {world.awake}")
    out.append(f"元の場所から動いた箱 {moved} / {len(before)}")
    out.append(f"崩れた: {'はい' if moved >= len(before) // 2 else 'いいえ'}")
    return out


def main():
    parser = argparse.ArgumentParser(description="物理の積み木 — 箱どうしの衝突")
    parser.add_argument("--auto", action="store_true", help="勝手に箱を落とし続けるデモ")
    parser.add_argument("--check", action="store_true", help="塔を建てたまま回して、物理が壊れていないか見る")
    parser.add_argument("--smash", action="store_true", help="重い箱を落として、塔が崩れるか見る")
    parser.add_argument("--seed", type=int, help="落とす箱の乱数の種")
    args = parser.parse_args()
    world = World()
    if args.check:
        for line_ in tower_report(world):
            print(line_)
        return
    if args.smash:
        for line_ in smash_report(world, seed=args.seed):
            print(line_)
        return
    if problem := check_terminal():
        print(problem)
        return
    play(world, seed=args.seed, auto=args.auto)


if __name__ == "__main__":
    main()
