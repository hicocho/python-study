"""宇宙船 — 完成: 重力のある宇宙でリングをくぐるタイムアタック。class Game にまとめる。"""

import cmath
import os
import select
import sys
import termios
import time
import tty
from contextlib import contextmanager
from dataclasses import dataclass

WIDTH = 50                                  # 画面の横のマス数
HEIGHT = 22                                 # 画面の縦のマス数
FRAME_SECONDS = 0.05                        # キーを待つ時間 ＝ 描き直す間隔
MAX_DT = 0.05
TURN_STEP = cmath.pi / 8                    # 矢印 1 回で回る角度（22.5 度）
THRUST = 4.0                                # ↑ 1 回で足される速さ（マス/秒）
MAX_SPEED = 30.0
HALF_LIFE = 3.0                             # 何もしなければ、速さがこの秒数で半分になる
G = 90.0                                    # 星の引力の強さ
LIVES = 3
RING_RADIUS = 1.5                           # ここまで近づけばくぐったことにする

# 向き（ラジアン）→ 船の見た目。0 が右、π/2 が下（画面の y は下向き）
HEADINGS = ">\\v/<\\^/"

ARROWS = {
    "\x1b[A": "thrust",
    "\x1b[C": "right",
    "\x1b[D": "left",
}

RESULT_TEXT = {
    "clear": "全部くぐった！",
    "over": "船を使い切った…",
    "quit": "やめました。",
}


@dataclass(frozen=True)
class Planet:
    """引力を持つ星。ぶつかると船が壊れる。"""

    center: complex
    radius: float
    mass: float


def make_planets() -> list[Planet]:
    return [Planet(complex(20, 8), 2.0, 1.0), Planet(complex(33, 15), 2.5, 1.6)]


def make_rings() -> list[complex]:
    """くぐる順に並んだリングの中心。"""
    return [complex(14, 4), complex(27, 12), complex(40, 5), complex(44, 17), complex(24, 19)]


def wrap(pos: complex) -> complex:
    """画面の端を越えたら反対側から出てくる。% は小数でも使える。"""
    return complex(pos.real % WIDTH, pos.imag % HEIGHT)


def heading_char(heading: float) -> str:
    """向きを 8 方向に丸めて 1 文字にする。"""
    index = round(heading / (cmath.pi / 4)) % 8
    return HEADINGS[index]


def gravity(pos: complex, planets: list[Planet]) -> complex:
    """すべての星から受ける加速度の合計。距離の 2 乗に反比例する。"""
    total = 0j
    for planet in planets:
        d = planet.center - pos                             # 船から星へ
        total += d * (G * planet.mass / abs(d) ** 3)        # 向き d/|d| × 強さ G m/|d|²
    return total


def drag(vel: complex, dt: float) -> complex:
    """何もしなくても少しずつ減速する。HALF_LIFE 秒で半分。"""
    return vel * 0.5 ** (dt / HALF_LIFE)


def circle_cells(center: complex, radius: float) -> set[tuple[int, int]]:
    """中心と半径から、その円に入るマスの集合。"""
    cx, cy = center.real, center.imag
    return {(x, y)
            for y in range(int(cy - radius) - 1, int(cy + radius) + 2)
            for x in range(int(cx - radius) - 1, int(cx + radius) + 2)
            if (x - cx) ** 2 + (y - cy) ** 2 <= radius * radius}


def field_text(pos: complex, heading: float, planets: list[Planet], rings: list[complex],
               next_ring: int, trail: list[complex]) -> str:
    """画面を文字列にして返す。船は向きの記号、次のリングは [ ]、残りは ( )。"""
    chars = {}
    for p in trail:
        chars[(round(p.real) % WIDTH, round(p.imag) % HEIGHT)] = "·"
    for planet in planets:
        for cell in circle_cells(planet.center, planet.radius):
            chars[cell] = "O"
    for i, ring in enumerate(rings[next_ring:], start=next_ring):
        x, y = round(ring.real), round(ring.imag)
        left, right = ("[", "]") if i == next_ring else ("(", ")")
        chars[(x - 1, y)] = left
        chars[(x + 1, y)] = right
    chars[(round(pos.real) % WIDTH, round(pos.imag) % HEIGHT)] = heading_char(heading)

    lines = ["+" + "-" * WIDTH + "+"]
    for y in range(HEIGHT):
        lines.append("|" + "".join(chars.get((x, y), " ") for x in range(WIDTH)) + "|")
    lines.append("+" + "-" * WIDTH + "+")
    return "\n".join(lines)


class Game:
    """1 回ぶんの飛行。船・星・リング・残機・タイムを持つ。"""

    def __init__(self):
        self.planets = make_planets()
        self.rings = make_rings()
        self.next_ring = 0                                  # 次にくぐるリングの番号
        self.lives = LIVES
        self.elapsed = 0.0
        self.trail: list[complex] = []
        self.result: str | None = None
        self.reset_ship()

    def reset_ship(self) -> None:
        """スタート地点に置き直す。"""
        self.pos = complex(5, 11)
        self.vel = 0j
        self.heading = 0.0                                  # 右向き

    def turn(self, direction: str) -> None:
        if self.result is not None:
            return
        self.heading += TURN_STEP if direction == "right" else -TURN_STEP
        self.heading %= 2 * cmath.pi

    def thrust(self) -> None:
        """向いている方向へ加速する。"""
        if self.result is not None:
            return
        self.vel += cmath.rect(THRUST, self.heading)        # 長さ THRUST、向き heading のベクトルを足す

    def update(self, dt: float) -> None:
        if self.result is not None:
            return

        self.elapsed += dt
        self.vel += gravity(self.pos, self.planets) * dt
        self.vel = drag(self.vel, dt)
        if abs(self.vel) > MAX_SPEED:
            self.vel *= MAX_SPEED / abs(self.vel)

        self.trail.append(self.pos)
        self.trail = self.trail[-30:]
        self.pos = wrap(self.pos + self.vel * dt)

        for planet in self.planets:
            if abs(self.pos - planet.center) < planet.radius:   # 星にぶつかった
                self.lives -= 1
                self.trail = []
                if self.lives == 0:
                    self.result = "over"
                else:
                    self.reset_ship()
                return

        if abs(self.pos - self.rings[self.next_ring]) < RING_RADIUS:   # リングをくぐった
            self.next_ring += 1
            if self.next_ring == len(self.rings):
                self.result = "clear"

    def render(self) -> str:
        board = field_text(self.pos, self.heading, self.planets, self.rings, self.next_ring, self.trail)
        status = (f"リング {self.next_ring}/{len(self.rings)}   船 {self.lives}   "
                  f"{self.elapsed:6.1f} 秒   速さ {abs(self.vel):4.1f}   ← → 回転 / ↑ 加速 / q")
        return f"{board}\n{status}\n"


@contextmanager
def raw_mode():
    """このブロックの中だけ、キーを 1 文字ずつ読める端末にする。抜けたら必ず戻す。"""
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    tty.setcbreak(fd)
    try:
        yield
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def read_key(timeout: float) -> str | None:
    """timeout 秒まで待ってキーを 1 つ読む。来なければ None。"""
    if not select.select([sys.stdin], [], [], timeout)[0]:
        return None
    key = os.read(sys.stdin.fileno(), 8).decode()
    return ARROWS.get(key, key)


def main():
    game = Game()

    print("\x1b[2J", end="")
    last = time.monotonic()
    with raw_mode():
        while game.result is None:
            sys.stdout.write("\x1b[H" + game.render())
            sys.stdout.flush()

            key = read_key(FRAME_SECONDS)
            now = time.monotonic()
            dt = min(now - last, MAX_DT)
            last = now

            if key == "q":
                game.result = "quit"
            elif key == "thrust":
                game.thrust()
            elif key in ("left", "right"):
                game.turn(key)

            game.update(dt)

    sys.stdout.write("\x1b[H" + game.render())
    print(f"\n{RESULT_TEXT[game.result]}  {game.elapsed:.1f} 秒")


if __name__ == "__main__":
    main()
