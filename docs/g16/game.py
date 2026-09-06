"""宇宙船（ブラウザ版）

CLI 版（g16-spaceship/main.py）と物理・ルールはまったく同じ。
定数 9 個と Planet、make_planets() / make_rings() / wrap() / gravity() / drag()、そして class Game を、
ステップの目印コメント（# ←）を外しただけで 1 文字も変えずに持ってきている。

持ってこなかったのは heading_char() / circle_cells() / field_text() と raw_mode() / read_key() / main()、
それに Game.render() だけ。違うのは入口と出口で、入口は select で待つ生キー入力ではなく
asyncio の時計とキーイベント、出口は 8 方向の記号ではなく SVG の三角形を rotate() で回す。
CLI 版が 22.5 度刻みに丸めていた向きが、ここではそのままの角度で見える。
"""

import asyncio
import cmath
import time
from dataclasses import dataclass

from pyscript import document, when

SVG = "http://www.w3.org/2000/svg"


# --- ここから class Game まで、CLI 版（g16-spaceship/main.py）からそのまま ---


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


# --- ここから下はブラウザ版だけ。CLI 版の read_key() / render() / main() にあたる ---

KEYMAP = {  # ブラウザが送ってくる名前 → CLI 版と同じ操作
    "ArrowUp": "thrust",
    "ArrowLeft": "left",
    "ArrowRight": "right",
}

planets_group = document.querySelector("#planets")
rings_group = document.querySelector("#ring-group")
trail_group = document.querySelector("#trail")
ship_el = document.querySelector("#ship")
rings_label = document.querySelector("#rings")
lives_label = document.querySelector("#lives")
time_label = document.querySelector("#time")
speed_label = document.querySelector("#speed")
message = document.querySelector("#message")
start_button = document.querySelector("#start-btn")

# 状態は Game が全部持っている。ブラウザ側が覚えるのは時計だけ
game = Game()
last = 0.0
ring_elements = []
trail_elements = []


def svg(tag: str, **attrs):
    """SVG の要素を作る。属性は辞書で渡す。"""
    element = document.createElementNS(SVG, tag)
    for name, value in attrs.items():
        element.setAttribute(name.replace("_", "-"), str(value))
    return element


def build():
    """星・リング・軌跡の入れ物を SVG に置く。新しいゲームのときだけ。"""
    global ring_elements, trail_elements

    planets_group.replaceChildren()
    for planet in game.planets:
        planets_group.appendChild(svg("circle", **{"class": "planet"},
                                      cx=f"{planet.center.real:.2f}", cy=f"{planet.center.imag:.2f}", r=planet.radius))

    rings_group.replaceChildren()
    ring_elements = []
    for ring in game.rings:
        circle = svg("circle", **{"class": "ring"}, cx=f"{ring.real:.2f}", cy=f"{ring.imag:.2f}", r=RING_RADIUS)
        rings_group.appendChild(circle)
        ring_elements.append(circle)

    trail_group.replaceChildren()
    trail_elements = []
    for _ in range(30):
        dot = svg("circle", **{"class": "trail"}, r=0.15, cx=-5, cy=-5)
        trail_group.appendChild(dot)
        trail_elements.append(dot)


def draw():
    """CLI 版の render() にあたる。船の位置と向きは transform で置く。"""
    degrees = game.heading * 180 / cmath.pi
    ship_el.setAttribute("transform", f"translate({game.pos.real:.2f} {game.pos.imag:.2f}) rotate({degrees:.1f})")

    for i, circle in enumerate(ring_elements):
        state = "done" if i < game.next_ring else "next" if i == game.next_ring else ""
        circle.setAttribute("class", f"ring {state}".strip())

    for dot, p in zip(trail_elements, reversed(game.trail)):
        dot.setAttribute("cx", f"{p.real:.2f}")
        dot.setAttribute("cy", f"{p.imag:.2f}")
    for dot in trail_elements[len(game.trail):]:
        dot.setAttribute("cx", "-5")

    rings_label.textContent = str(game.next_ring)
    lives_label.textContent = str(game.lives)
    time_label.textContent = f"{game.elapsed:.1f}"
    speed_label.textContent = f"{abs(game.vel):.0f}"


async def tick():
    """時間を進める係。CLI 版の read_key(FRAME_SECONDS) の待ち時間にあたる。"""
    global last

    while game.result is None:
        await asyncio.sleep(FRAME_SECONDS)
        now = time.monotonic()
        dt = min(now - last, MAX_DT)
        last = now
        game.update(dt)
        draw()

    message.textContent = f"{RESULT_TEXT[game.result]}  {game.elapsed:.1f} 秒"
    start_button.hidden = False


def start():
    global game, last

    game = Game()                                           # 作り直すだけで初期化になる
    last = time.monotonic()
    message.textContent = ""
    start_button.hidden = True
    build()
    draw()
    asyncio.ensure_future(tick())                           # 待ち続ける係を裏で走らせる


def act(action):
    """CLI 版の main の while ループの中身と同じ振り分け。"""
    if action == "thrust":
        game.thrust()
    elif action in ("left", "right"):
        game.turn(action)
    draw()


@when("keydown", "body")
def on_key(event):
    action = KEYMAP.get(event.key)
    if action is None:
        return
    event.preventDefault()
    act(action)


@when("click", "#left-btn")
def on_left(event):
    act("left")


@when("click", "#right-btn")
def on_right(event):
    act("right")


@when("click", "#thrust-btn")
def on_thrust(event):
    act("thrust")


@when("click", "#start-btn")
def on_start(event):
    start()


# Pyodide の読み込みが終わってから実行される＝ここが準備完了の合図
document.querySelector("#loading").hidden = True
start()
