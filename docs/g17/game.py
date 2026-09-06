"""小惑星（ブラウザ版）

CLI 版（g17-asteroids/main.py）と物理・当たり判定・ルールはまったく同じ。
定数 16 個と Entity / Ship / Bullet / Asteroid の 4 クラス、wrap() / heading_char() / drag() / spawn_asteroids()、
そして class Game を、ステップの目印コメント（# ←）を外しただけで 1 文字も変えずに持ってきている。

持ってこなかったのは circle_cells() / field_text() と raw_mode() / read_key() / main()、それに Game.render() だけ。
違うのは入口と出口で、入口は select で待つ生キー入力ではなく asyncio の時計とキーイベント、
出口は文字で埋めた円ではなく SVG の <circle>。小惑星は Entity の radius をそのまま r に入れる。
"""

import asyncio
import cmath
import random
import time
from abc import ABC, abstractmethod

from pyscript import document, when

SVG = "http://www.w3.org/2000/svg"


# --- ここから class Game まで、CLI 版（g17-asteroids/main.py）からそのまま ---


WIDTH = 50                                  # 画面の横のマス数
HEIGHT = 22                                 # 画面の縦のマス数
FRAME_SECONDS = 0.05                        # キーを待つ時間 ＝ 描き直す間隔
MAX_DT = 0.05
TURN_STEP = cmath.pi / 8                    # 矢印 1 回で回る角度（22.5 度）
THRUST = 4.0                                # ↑ 1 回で足される速さ（マス/秒）
MAX_SPEED = 30.0
HALF_LIFE = 3.0                             # 何もしなければ、速さがこの秒数で半分になる
LIVES = 3
BULLET_SPEED = 28.0
BULLET_LIFE = 1.2                           # 弾が消えるまでの秒数
MAX_BULLETS = 4
SAFE_SECONDS = 2.0                          # 復活したあと、当たらない時間
FIRST_WAVE = 3                              # 最初のウェーブの小惑星の数
SIZE_RADIUS = {3: 2.4, 2: 1.5, 1: 0.8}      # 大きさ → 半径
SIZE_POINTS = {3: 20, 2: 50, 1: 100}        # 大きさ → 点数（小さいほど当てにくい）
SIZE_CHAR = {3: "@", 2: "O", 1: "o"}


HEADINGS = ">\\v/<\\^/"


RESULT_TEXT = {
    "over": "船を使い切った…",
    "quit": "やめました。",
}


def wrap(pos: complex) -> complex:
    """画面の端を越えたら反対側から出てくる。"""
    return complex(pos.real % WIDTH, pos.imag % HEIGHT)


def heading_char(heading: float) -> str:
    """向きを 8 方向に丸めて 1 文字にする。"""
    return HEADINGS[round(heading / (cmath.pi / 4)) % 8]


def drag(vel: complex, dt: float) -> complex:
    """何もしなくても少しずつ減速する。HALF_LIFE 秒で半分。"""
    return vel * 0.5 ** (dt / HALF_LIFE)


class Entity(ABC):
    """画面を動くもの全部の親。位置・速度・半径を持ち、1 コマ進む。

    抽象クラスなので Entity そのものは作れない。子は char を必ず書く。
    """

    def __init__(self, pos: complex, vel: complex, radius: float):
        self.pos = pos
        self.vel = vel
        self.radius = radius
        self.alive = True

    def update(self, dt: float) -> None:
        """速度ぶん進んで、端をループする。子で足したければ super().update(dt) を呼ぶ。"""
        self.pos = wrap(self.pos + self.vel * dt)

    def hits(self, other: "Entity") -> bool:
        """2 つの円が重なっているか。"""
        return abs(self.pos - other.pos) < self.radius + other.radius

    @property
    @abstractmethod
    def char(self) -> str:
        """画面に出す 1 文字。子が決める。"""


class Ship(Entity):
    """自機。向きと進行方向が別。"""

    def __init__(self):
        super().__init__(complex(WIDTH / 2, HEIGHT / 2), 0j, 0.9)
        self.heading = -cmath.pi / 2                        # 上向き
        self.safe = SAFE_SECONDS                            # 残り無敵時間

    def turn(self, direction: str) -> None:
        self.heading += TURN_STEP if direction == "right" else -TURN_STEP
        self.heading %= 2 * cmath.pi

    def thrust(self) -> None:
        self.vel += cmath.rect(THRUST, self.heading)
        if abs(self.vel) > MAX_SPEED:
            self.vel *= MAX_SPEED / abs(self.vel)

    def update(self, dt: float) -> None:
        self.vel = drag(self.vel, dt)
        self.safe = max(0.0, self.safe - dt)
        super().update(dt)

    @property
    def char(self) -> str:
        return heading_char(self.heading)


class Bullet(Entity):
    """弾。まっすぐ飛んで、時間で消える。"""

    def __init__(self, pos: complex, heading: float):
        super().__init__(pos, cmath.rect(BULLET_SPEED, heading), 0.3)
        self.life = BULLET_LIFE

    def update(self, dt: float) -> None:
        self.life -= dt
        if self.life <= 0:
            self.alive = False
        super().update(dt)

    @property
    def char(self) -> str:
        return "·"


class Asteroid(Entity):
    """小惑星。大きさ 3・2・1。撃たれると 1 つ小さいのが 2 つに割れる。"""

    def __init__(self, pos: complex, size: int, vel: complex | None = None):
        if vel is None:
            speed = random.gauss(6.0, 2.0) + (3 - size) * 2  # 小さいほど速い
            vel = cmath.rect(max(2.0, speed), random.uniform(0, 2 * cmath.pi))
        super().__init__(pos, vel, SIZE_RADIUS[size])
        self.size = size

    def split(self) -> list["Asteroid"]:
        """砕けたあとの破片。いちばん小さいのは消えるだけ。"""
        if self.size == 1:
            return []
        return [Asteroid(self.pos, self.size - 1) for _ in range(2)]

    @property
    def char(self) -> str:
        return SIZE_CHAR[self.size]


def spawn_asteroids(count: int, avoid: complex) -> list[Asteroid]:
    """自機から離れた場所に、大きい小惑星を count 個置く。"""
    asteroids = []
    while len(asteroids) < count:
        pos = complex(random.uniform(0, WIDTH), random.uniform(0, HEIGHT))
        if abs(pos - avoid) > 10:
            asteroids.append(Asteroid(pos, 3))
    return asteroids


class Game:
    """1 回ぶんの小惑星。自機・小惑星・弾・残機・得点・ウェーブを持つ。"""

    def __init__(self, seed: int | None = None):
        if seed is not None:
            random.seed(seed)

        self.ship = Ship()
        self.asteroids: list[Asteroid] = []
        self.bullets: list[Bullet] = []
        self.lives = LIVES
        self.score = 0
        self.wave = 0
        self.result: str | None = None
        self.next_wave()

    def next_wave(self) -> None:
        """小惑星が無くなったら、1 つ多くして出し直す。"""
        self.wave += 1
        self.asteroids = spawn_asteroids(FIRST_WAVE + self.wave - 1, self.ship.pos)

    def fire(self) -> bool:
        """向いている方向へ弾を撃つ。画面に MAX_BULLETS 発まで。"""
        if self.result is not None or len(self.bullets) >= MAX_BULLETS:
            return False
        self.bullets.append(Bullet(self.ship.pos, self.ship.heading))
        return True

    def update(self, dt: float) -> None:
        if self.result is not None:
            return

        self.ship.update(dt)
        for entity in self.asteroids + self.bullets:        # 種類が違っても同じ update
            entity.update(dt)

        for bullet in self.bullets:                         # 弾 × 小惑星
            for asteroid in self.asteroids:
                if bullet.alive and asteroid.alive and bullet.hits(asteroid):
                    bullet.alive = False
                    asteroid.alive = False
                    self.score += SIZE_POINTS[asteroid.size]
                    self.asteroids.extend(asteroid.split())

        if self.ship.safe == 0:                             # 自機 × 小惑星
            for asteroid in self.asteroids:
                if asteroid.alive and asteroid.hits(self.ship):
                    self.lives -= 1
                    if self.lives == 0:
                        self.result = "over"
                        return
                    self.ship = Ship()                      # 真ん中で復活、しばらく無敵
                    break

        self.bullets = [b for b in self.bullets if b.alive]
        self.asteroids = [a for a in self.asteroids if a.alive]
        if not self.asteroids:
            self.next_wave()


# --- ここから下はブラウザ版だけ。CLI 版の read_key() / render() / main() にあたる ---

KEYMAP = {  # ブラウザが送ってくる名前 → CLI 版と同じ操作
    "ArrowUp": "thrust",
    "ArrowLeft": "left",
    "ArrowRight": "right",
    " ": "fire",
}

rocks_group = document.querySelector("#rocks")
bullets_group = document.querySelector("#bullets")
ship_el = document.querySelector("#ship")
score_label = document.querySelector("#score")
lives_label = document.querySelector("#lives")
wave_label = document.querySelector("#wave")
left_label = document.querySelector("#left")
message = document.querySelector("#message")
start_button = document.querySelector("#start-btn")

# 状態は Game が全部持っている。ブラウザ側が覚えるのは時計だけ
game = Game()
last = 0.0


def svg(tag: str, **attrs):
    """SVG の要素を作る。属性は辞書で渡す。"""
    element = document.createElementNS(SVG, tag)
    for name, value in attrs.items():
        element.setAttribute(name.replace("_", "-"), str(value))
    return element


def sync_circles(group, entities, class_name):
    """<circle> の数を entities に合わせて、位置と半径を書き込む。"""
    while group.childElementCount < len(entities):
        group.appendChild(svg("circle", **{"class": class_name}))
    while group.childElementCount > len(entities):
        group.lastElementChild.remove()
    for circle, entity in zip(group.children, entities):
        circle.setAttribute("cx", f"{entity.pos.real:.2f}")
        circle.setAttribute("cy", f"{entity.pos.imag:.2f}")
        circle.setAttribute("r", f"{entity.radius:.2f}")


def draw():
    """CLI 版の render() にあたる。"""
    ship = game.ship
    degrees = ship.heading * 180 / cmath.pi
    ship_el.setAttribute("transform", f"translate({ship.pos.real:.2f} {ship.pos.imag:.2f}) rotate({degrees:.1f})")
    ship_el.setAttribute("class", "safe" if ship.safe > 0 else "")

    sync_circles(rocks_group, game.asteroids, "rock")
    sync_circles(bullets_group, game.bullets, "bullet")

    score_label.textContent = str(game.score)
    lives_label.textContent = str(game.lives)
    wave_label.textContent = str(game.wave)
    left_label.textContent = str(len(game.asteroids))


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

    message.textContent = f"{RESULT_TEXT[game.result]}  得点 {game.score}  ウェーブ {game.wave}"
    start_button.hidden = False


def start():
    global game, last

    game = Game()                                           # 作り直すだけで初期化になる
    last = time.monotonic()
    message.textContent = ""
    start_button.hidden = True
    draw()
    asyncio.ensure_future(tick())                           # 待ち続ける係を裏で走らせる


def act(action):
    """CLI 版の main の while ループの中身と同じ振り分け。"""
    if game.result is not None:
        return
    if action == "thrust":
        game.ship.thrust()
    elif action in ("left", "right"):
        game.ship.turn(action)
    elif action == "fire":
        game.fire()
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


@when("click", "#fire-btn")
def on_fire(event):
    act("fire")


@when("click", "#start-btn")
def on_start(event):
    start()


# Pyodide の読み込みが終わってから実行される＝ここが準備完了の合図
document.querySelector("#loading").hidden = True
start()
