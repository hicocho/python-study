"""物理の積み木 — 完成: 剛体の箱。重力で落ち、床にぶつかって回る。撃力で跳ね返し、摩擦で止める。"""

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
from itertools import starmap
from math import isclose, remainder, tau

WIDTH = 126                                         # 画面の横（ドット）。端末では 1 ドット = 1 桁
HEIGHT = 80                                         # 縦。端末では 2 ドット = 1 行 → 40 行
FLOOR_Y = 72.0                                      # 床の高さ
WALL_L = 2.0                                        # 左の壁
WALL_R = WIDTH - 2.0                                # 右の壁
FPS = 60
STEP = 1 / FPS                                      # 物理を進める刻み。時計の速さで変えない
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
        """ほとんど動かない状態が続いたら眠らせる。眠ると計算からも外れる。"""      # ←
        if abs(self.vel) < SLEEP_SPEED and abs(self.spin) < SLEEP_SPIN:
            self.still += dt
            if self.still > SLEEP_TIME:             # ←
                self.asleep = True
                self.vel, self.spin = 0j, 0.0
        else:
            self.still = 0.0


def make_box(x: float, y: float, w: float, h: float, angle: float = 0.0) -> Body:
    """置く場所と大きさから箱を 1 つ。重さは面積に比例させる。"""
    half = complex(w / 2, h / 2)
    return Body(pos=complex(x, y), half=half, angle=angle, mass=w * h / 40)


# 最初に落ちてくる箱。(x, y, 幅, 高さ, 傾き) の表を starmap で一気に箱にする。
# g64 では箱どうしがまだすり抜けるので、重ならないよう横に並べてある（積むのは g65）。
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
    1 回の刻みで進む距離が SLOP（見逃していい深さ）を超えると床とのぶつかりを
    見落とし、深く入ってから跳ね返る——を繰り返して、いつまでも眠らない箱ができる。
    足りない時間はためておき、決まった幅で必要な回数だけ進める。
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
            while lag >= STEP:                  # たまったぶんだけ、決まった幅で進める
                if auto and int(world.time * 2) != int((world.time + STEP) * 2):
                    world.drop(rng.uniform(20, WIDTH - 20), rng)
                world.update(STEP)
                lag -= STEP
            draw(screen, world)
            for y in (2, 3):                        # 落とす位置の目印
                screen.plot(int(aim), y, EDGE)
            sys.stdout.write("\x1b[H" + screen.render()
                             + f"\x1b[0m箱 {len(world.boxes):2d}   動いている {world.awake:2d}   "
                               f"力 {world.energy():7.1f}   ← → 位置  空白 落とす  r やり直し  q やめる\x1b[K\n")
            sys.stdout.flush()
            time.sleep(max(0.0, STEP - (time.monotonic() - now)))
    finally:
        sys.stdout.write("\x1b[0m\x1b[?25h")
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    print()


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


def main():
    parser = argparse.ArgumentParser(description="物理の積み木 — 剛体の箱")
    parser.add_argument("--auto", action="store_true", help="勝手に箱を落とし続けるデモ")
    parser.add_argument("--check", action="store_true", help="静かになるまで回して、物理が壊れていないか見る")
    parser.add_argument("--seed", type=int, help="落とす箱の乱数の種")
    args = parser.parse_args()
    world = World()
    if args.check:
        rng = random.Random(args.seed if args.seed is not None else 0)
        for _ in range(6):
            world.drop(rng.uniform(20, WIDTH - 20), rng)
        for line_ in settle_report(world):
            print(line_)
        return
    if problem := check_terminal():
        print(problem)
        return
    play(world, seed=args.seed, auto=args.auto)


if __name__ == "__main__":
    main()
