"""物理の積み木（剛体の箱）ブラウザ版

CLI 版（g64-physics-boxes/main.py）と物理はまったく同じ。定数、dot() / cross()、
Body、床とのぶつかり方、World、描き方を 1 文字も変えずに持ってきている。

持ってこなかったのは端末に描く Screen.render() と、それを使う play() /
read_keys() / check_terminal() / main() だけ。出口は canvas、入口はボタン。
違いは時間の進め方が 1 か所だけ（loop() のコメントを参照）。
"""

import asyncio
import math
import random
from dataclasses import dataclass, field
from itertools import starmap
from math import isclose, remainder, tau

from js import window
from pyscript import document, when

WIDTH = 126                                         # 画面の横（ドット）。端末では 1 ドット = 1 桁
HEIGHT = 80                                         # 縦。端末では 2 ドット = 1 行 → 40 行
FLOOR_Y = 72.0                                      # 床の高さ
WALL_L = 2.0                                        # 左の壁
WALL_R = WIDTH - 2.0                                # 右の壁
FPS = 60
SUBSTEPS = 4                                        # 1 コマを何回に割って解くか


GRAVITY = complex(0, 260.0)                         # 下向き。複素数の虚部が下
BOUNCE = 0.28                                       # 反発係数。1 なら跳ね返り放題、0 ならぺたりと止まる
FRICTION = 0.45                                     # 接している面のすべりにくさ
CORRECTION = 0.6                                    # めり込みを 1 コマでどれだけ押し戻すか
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


@dataclass
class Body:
    """剛体の箱 1 つ。位置と速度に加えて、向きと角速度を持つ。

    位置も速度も複素数。g16 の宇宙船と同じだが、あちらは「向き」を持たなかった。
    回るものは、重さ（質量）のほかに「回りにくさ」（慣性モーメント）が要る。
    """

    pos: complex
    half: complex                                   # 箱の半分の大きさ（横, 縦）
    vel: complex = 0j
    angle: float = 0.0                              # 向き（ラジアン）
    spin: float = 0.0                               # 角速度（ラジアン/秒）
    mass: float = 1.0
    color: int = 0
    still: float = 0.0                              # 動かないまま経った秒数
    asleep: bool = False

    @property
    def inertia(self) -> float:
        """回りにくさ。長方形は m(w² + h²)/12。細長いほど、長い向きに回しにくい。"""
        w, h = 2 * self.half.real, 2 * self.half.imag
        return self.mass * (w * w + h * h) / 12

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

    def velocity_at(self, point: complex) -> complex:
        """箱の上のある点が、今どちらへどれだけ動いているか。

        中心の速度に、回転ぶんを足す。2 次元では ω × r が「r を 90 度回して ω 倍」
        になるので、複素数なら spin * 1j * r で書ける。
        """
        return self.vel + self.spin * 1j * (point - self.pos)

    def push(self, point: complex, impulse: complex) -> None:
        """ある点を、ある向きに突く。中心の速度と回転の両方が変わる。

        ここでは目を覚まさせない。触れているだけで起こしてしまうと、
        床に載っている箱が永遠に眠れなくなる（実際にそうなった）。
        """
        r = point - self.pos
        self.vel += impulse / self.mass
        self.spin += cross(r, impulse) / self.inertia

    def wake(self) -> None:
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


def make_box(x: float, y: float, w: float, h: float, angle: float = 0.0) -> Body:
    """置く場所と大きさから箱を 1 つ。重さは面積に比例させる。"""
    half = complex(w / 2, h / 2)
    return Body(pos=complex(x, y), half=half, angle=angle, mass=w * h / 40)


STACK = (
    (14, 10, 16, 6, 0.0),
    (34, 22, 6, 16, 0.5),
    (54, 6, 20, 5, -0.9),
    (74, 26, 12, 12, 0.3),
    (94, 14, 22, 4, 1.2),
    (114, 30, 8, 8, -0.4),
)


def solve_floor(body: Body) -> None:
    """床と左右の壁にぶつかっているすみを探して、突き返す。

    速さの直し（撃力）はすみごとに入れるが、位置の押し戻しは
    **1 コマに 1 回だけ**、いちばん深いところぶんにする。
    すみごとに押すと、平らに載った箱が 2 回押されて跳ね続ける。
    """
    deepest, push_dir = 0.0, 0j
    for corner in body.corners():
        for depth, normal in edges(corner):
            if depth <= SLOP:
                continue
            bounce_off(body, corner, normal)
            if depth > deepest:
                deepest, push_dir = depth, normal
    if deepest > 0:
        body.pos += push_dir * (deepest - SLOP) * CORRECTION


def edges(corner: complex) -> list[tuple[float, complex]]:
    """そのすみが、床・左の壁・右の壁にどれだけ食い込んでいるか。"""
    return [(corner.imag - FLOOR_Y, complex(0, -1)),
            (WALL_L - corner.real, complex(1, 0)),
            (corner.real - WALL_R, complex(-1, 0))]


def bounce_off(body: Body, point: complex, normal: complex) -> None:
    """1 点を、面の法線の向きに突き返す。跳ね返りと摩擦の 2 回に分けて入れる。"""
    r = point - body.pos
    v = body.velocity_at(point)
    vn = dot(v, normal)
    if vn < 0:                                      # 面へ向かっているときだけ跳ね返す
        rn = cross(r, normal)
        j = -(1 + BOUNCE) * vn / (1 / body.mass + rn * rn / body.inertia)
        body.push(point, j * normal)
        # 摩擦は「面に沿った向き」に、跳ね返りの強さに比例した分だけ
        tangent = normal * 1j
        vt = dot(body.velocity_at(point), tangent)
        rt = cross(r, tangent)
        jt = -vt / (1 / body.mass + rt * rt / body.inertia)
        jt = max(-FRICTION * j, min(FRICTION * j, jt))              # クーロン摩擦の頭打ち
        body.push(point, jt * tangent)
        if vn < -WAKE_SPEED:                        # ← しっかりぶつかったときだけ目を覚ます
            body.wake()                             # ← 床に載っているだけの震えは −5 くらい。測って決めた


@dataclass
class World:
    """箱の入れ物。1 コマを SUBSTEPS 回に割って解く。"""

    boxes: list[Body] = field(default_factory=list)
    time: float = 0.0

    def __post_init__(self) -> None:
        if not self.boxes:
            self.boxes = list(starmap(make_box, STACK))              # 表を一気に箱へ
        for i, box in enumerate(self.boxes):
            box.color = i % len(BOX_COLORS)

    def drop(self, x: float, rng: random.Random) -> None:
        """上から箱を 1 つ落とす。"""
        w, h = rng.choice(((6, 8), (10, 4), (5, 5), (14, 3)))
        box = make_box(x, 6, w, h, angle=rng.uniform(-0.6, 0.6))
        box.color = len(self.boxes) % len(BOX_COLORS)
        box.vel = complex(rng.uniform(-15, 15), 40)
        self.boxes.append(box)

    def update(self, dt: float) -> None:
        """1 コマ。小さく刻んだ方が、めり込みが浅くて安定する。"""
        self.time += dt
        piece = dt / SUBSTEPS
        for _ in range(SUBSTEPS):
            for box in self.boxes:
                box.step(piece)
                if not box.asleep:
                    solve_floor(box)
        for box in self.boxes:
            box.settle(dt)

    @property
    def awake(self) -> int:
        return sum(not b.asleep for b in self.boxes)

    def energy(self) -> float:
        """全部の箱の運動エネルギー。増え続けていたら、どこかが壊れている。"""
        return sum(0.5 * b.mass * abs(b.vel) ** 2 + 0.5 * b.inertia * b.spin ** 2
                   for b in self.boxes)


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


def settle_report(world: World, seconds: float = 12.0, dt: float = 1 / FPS) -> list[str]:
    """静かになるまで回して、様子を書き出す。物理が壊れていないかの確認に使う。

    見るのは 3 つ。ぜんぶ眠るか（震え続けていないか）、めり込みが浅いままか、
    そして落ちきったあとに運動エネルギーが増えていないか（増えるなら、どこかで
    力を作り出してしまっている）。
    """
    out = []
    steps = int(seconds / dt)
    peak = after = 0.0
    for i in range(steps):
        world.update(dt)
        energy = world.energy()
        peak = max(peak, energy)
        if world.time > 3.0:                        # 落ちきったあとだけ見る
            after = max(after, energy)
        if i % (steps // 6) == 0:
            out.append(f"{world.time:5.1f} 秒  動いている {world.awake:2d} / {len(world.boxes)}  "
                       f"運動エネルギー {energy:8.2f}")
        if world.awake == 0:
            out.append(f"{world.time:5.1f} 秒  全部止まった")
            break
    deepest = max((max(c.imag for c in b.corners()) - FLOOR_Y for b in world.boxes), default=0.0)
    out.append(f"いちばん深いめり込み {deepest:.3f} ドット")
    out.append(f"ぶつかった瞬間の力 {peak:.0f} → 落ちきったあとの最大 {after:.2f}")
    # 浮動小数はぴったり 0 にはならない。isclose に「どこまでを 0 とみなすか」を渡して確かめる
    out.append("落ちきったあとに力が増えていない: "
               + ("はい" if isclose(after, 0.0, abs_tol=0.5) else "いいえ（どこかで力を作っている）"))
    return out
# --- ここから下はブラウザ版だけ。CLI 版の play() / Screen.render() にあたる ---

canvas = document.querySelector("#screen")
ctx = canvas.getContext("2d")
ctx.imageSmoothingEnabled = False
image = ctx.createImageData(WIDTH, HEIGHT)
count_label = document.querySelector("#count")
awake_label = document.querySelector("#awake")
energy_label = document.querySelector("#energy")
pad_buttons = document.querySelectorAll(".pad button")


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


screen = CanvasScreen()
rng = random.Random()
world = World()
aim = WIDTH / 2


def refresh():
    """CLI 版の play() の 1 周ぶん。共有部分に draw() があるので、この名前は使えない。"""
    draw(screen, world)
    for y in (2, 3):                                # 落とす位置の目印
        screen.plot(int(aim), y, EDGE)
    screen.flush()
    count_label.textContent = str(len(world.boxes))
    awake_label.textContent = str(world.awake)
    energy_label.textContent = f"{world.energy():.0f}"


STEP = 1 / FPS


async def loop():
    """進めて描く。刻み幅は CLI 版と同じ 1/FPS 秒に固定する。

    経った時間をそのまま world.update() に渡すと、ブラウザの都合でコマが飛んだとき
    刻みが大きくなり、1 回の刻みで進む距離が SLOP（見逃していい深さ）を超える。
    すると床とのぶつかりが見つからないまま落ち続け、深く入ってから跳ね返る——を
    繰り返して、いつまでも眠らない箱ができる。だから足りない時間は「ためて」おき、
    決まった幅で必要な回数だけ進める。
    """
    lag = 0.0
    last = window.performance.now() / 1000
    while True:
        now = window.performance.now() / 1000
        lag = min(lag + now - last, 0.25)           # ためすぎない（重い端末で追いつけなくなる）
        last = now
        while lag >= STEP:
            world.update(STEP)
            lag -= STEP
        refresh()
        await asyncio.sleep(STEP)


@when("click", ".pad")
def on_pad(event):
    """ボタンは入れ物の側で受ける（@when は登録時に在る要素にしか付かない）。"""
    global aim, world
    action = event.target.getAttribute("data-act")
    if action is None:
        return
    match action:
        case "left":
            aim = max(10, aim - 8)
        case "right":
            aim = min(WIDTH - 10, aim + 8)
        case "drop":
            world.drop(aim, rng)
        case "reset":
            world = World()
    refresh()


KEYS = {"ArrowLeft": "left", "a": "left", "ArrowRight": "right", "d": "right",
        " ": "drop", "ArrowDown": "drop", "s": "drop", "r": "reset"}


@when("keydown", "body")
def on_key(event):
    global aim, world
    action = KEYS.get(event.key)
    if action is None:
        return
    event.preventDefault()
    match action:
        case "left":
            aim = max(10, aim - 8)
        case "right":
            aim = min(WIDTH - 10, aim + 8)
        case "drop":
            world.drop(aim, rng)
        case "reset":
            world = World()


# Pyodide の読み込みが終わってから実行される＝ここが準備完了の合図
document.querySelector("#loading").hidden = True
refresh()
asyncio.ensure_future(loop())
