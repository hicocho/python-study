"""ピンボール（ブラウザ版）

CLI 版（g15-pinball/main.py）と物理・当たり判定・ルールはまったく同じ。
定数 16 個と Vec / Segment / Bumper / Flipper の 4 クラス、reflect() / hit_segment() / hit_bumper() /
make_walls() / make_bumpers() / make_flippers()、そして class Game を、
ステップの目印コメント（# ←）を外しただけで 1 文字も変えずに持ってきている。

持ってこなかったのは raster() / field_text() と raw_mode() / read_key() / main()、それに Game.render() だけ。
違うのは入口と出口で、入口は select で待つ生キー入力ではなく asyncio の時計とキーイベント、
出口は文字の盤ではなく SVG。壁は <line>、バンパーは <circle>、フリッパーとボールは毎コマ座標を書き換える。
CLI 版が / \\ | - の 4 文字で近似していた斜めの壁が、ここでは本当の線になる。
"""

import asyncio
import math
import random
import time
from dataclasses import dataclass

from pyscript import document, when

SVG = "http://www.w3.org/2000/svg"


# --- ここから class Game まで、CLI 版（g15-pinball/main.py）からそのまま ---


WIDTH = 32                                  # 盤の横のマス数
HEIGHT = 26                                 # 盤の縦のマス数
FRAME_SECONDS = 0.04                        # キーを待つ時間 ＝ 描き直す間隔
MAX_DT = 0.04                               # 1 回に進める時間の上限
SUBSTEPS = 4                                # 1 コマの物理を何回に刻むか（速いボールが壁を抜けないように）
GRAVITY = 30.0                              # 1 秒に速度がこれだけ下向きに増える（マス/秒²）
BALL_RADIUS = 0.4
MAX_SPEED = 48.0                            # これ以上は速くならない
RESTITUTION = 0.9                           # 壁で跳ね返るたびに速さがこの割合になる（少しずつ勢いが落ちる）
BALLS = 3
LAUNCH_SPEED = (40.0, 46.0)                 # 打ち出す速さの範囲（マス/秒）。天井まで届く速さ
FLIP_TIME = 0.18                            # フリッパーが上がっている時間（秒）
FLIP_BOOST = 22.0                           # 上がっているフリッパーに当たると足される速さ
BUMPER_BOOST = 8.0                          # バンパーに当たると足される速さ
BUMPER_SCORE = 100
LIT_TIME = 0.25                             # バンパーが光っている時間（秒）


RESULT_TEXT = {
    "over": "ボールを使い切った。",
    "quit": "やめました。",
}


@dataclass(frozen=True)
class Vec:
    """2 次元のベクトル。g14 に、内積と回転を足したもの。"""

    x: float
    y: float

    def __add__(self, other: "Vec") -> "Vec":
        return Vec(self.x + other.x, self.y + other.y)

    def __sub__(self, other: "Vec") -> "Vec":
        return Vec(self.x - other.x, self.y - other.y)

    def __mul__(self, k: float) -> "Vec":
        return Vec(self.x * k, self.y * k)

    __rmul__ = __mul__

    def __truediv__(self, k: float) -> "Vec":
        return Vec(self.x / k, self.y / k)

    def __neg__(self) -> "Vec":
        return Vec(-self.x, -self.y)

    def __abs__(self) -> float:
        return math.hypot(self.x, self.y)

    def __iter__(self):
        yield self.x
        yield self.y

    def __matmul__(self, other: "Vec") -> float:
        """内積。同じ向きなら正、直角なら 0、逆向きなら負。"""
        return self.x * other.x + self.y * other.y

    def normalized(self) -> "Vec":
        """長さを 1 にしたベクトル。"""
        return self / abs(self)

    def perp(self) -> "Vec":
        """90 度回した（直角な）ベクトル。壁の法線に使う。"""
        return Vec(-self.y, self.x)

    def rotated(self, radians: float) -> "Vec":
        """角度ぶん回したベクトル。画面は y が下向きなので、正の角度で時計回り。"""
        c, s = math.cos(radians), math.sin(radians)
        return Vec(self.x * c - self.y * s, self.x * s + self.y * c)


@dataclass(frozen=True)
class Segment:
    """壁 1 本。a から b への線分。"""

    a: Vec
    b: Vec

    def closest_point(self, p: Vec) -> Vec:
        """線分の上で p にいちばん近い点。"""
        ab = self.b - self.a
        t = ((p - self.a) @ ab) / (ab @ ab)                  # a からの割合。0 が a、1 が b
        t = max(0.0, min(1.0, t))                           # 線分の外にはみ出さない
        return self.a + ab * t

    @property
    def normal(self) -> Vec:
        """壁の法線（壁に直角な、長さ 1 のベクトル）。"""
        return (self.b - self.a).perp().normalized()

    def normal_toward(self, p: Vec) -> Vec:
        """p のある側を向いた法線。"""
        n = self.normal
        return n if (p - self.a) @ n >= 0 else -n


@dataclass
class Bumper:
    """丸いバンパー。当たると弾き返して得点。"""

    center: Vec
    radius: float = 1.5
    lit: float = 0.0                                        # 光っている残り時間


class Flipper:
    """フリッパー。軸を中心に、休んでいる角度と上げた角度の 2 つを行き来する。"""

    def __init__(self, pivot: Vec, rest_degrees: float, up_degrees: float, length: float = 4.0):
        self.pivot = pivot
        self.rest = math.radians(rest_degrees)
        self.up = math.radians(up_degrees)
        self.length = length
        self.timer = 0.0                                    # 上がっている残り時間

    @property
    def active(self) -> bool:
        return self.timer > 0

    @property
    def segment(self) -> Segment:
        """いまの角度での線分。"""
        angle = self.up if self.active else self.rest
        return Segment(self.pivot, self.pivot + Vec(self.length, 0).rotated(angle))

    def flip(self) -> None:
        self.timer = FLIP_TIME

    def update(self, dt: float) -> None:
        self.timer = max(0.0, self.timer - dt)


def reflect(vel: Vec, normal: Vec) -> Vec:
    """速度を法線で反射する。壁に沿う成分はそのまま、直角な成分だけ反転。"""
    return vel - normal * (2 * (vel @ normal))


def hit_segment(prev: Vec, pos: Vec, vel: Vec, seg: Segment) -> tuple[Vec, Vec] | None:
    """ボールが壁に触れた（またはこのコマで壁を飛び越えた）なら (押し戻した位置, 反射した速度)。

    速いボールは 1 コマで壁の向こうへ行ってしまうので、「触れているか」だけでなく
    「1 コマ前と今で壁のどちら側にいるか」も見る。
    """
    n = seg.normal
    ab = seg.b - seg.a
    side_prev = (prev - seg.a) @ n                          # 正か負かで、壁のどちら側か
    side_now = (pos - seg.a) @ n
    closest = seg.closest_point(pos)
    dist = abs(pos - closest)

    crossed = False
    if side_prev * side_now < 0:                            # 符号が変わった ＝ 線をまたいだ
        t = side_prev / (side_prev - side_now)              # prev から pos のどこで線を越えたか
        cross = prev + (pos - prev) * t
        u = ((cross - seg.a) @ ab) / (ab @ ab)              # 越えた点が線分のどのあたりか
        margin = BALL_RADIUS / abs(ab)
        crossed = -margin <= u <= 1 + margin                # 線分の範囲内（半径ぶんの余裕あり）

    if dist >= BALL_RADIUS and not crossed:
        return None

    normal = n if side_prev >= 0 else -n                    # ボールが来た側を向いた法線
    if vel @ normal >= 0 and not crossed:                   # もう離れていく向きなら何もしない
        return None

    base = cross if crossed else closest
    return base + normal * BALL_RADIUS, reflect(vel, normal) * RESTITUTION   # 壁の表面まで押し戻して反射


def hit_bumper(pos: Vec, vel: Vec, bumper: Bumper) -> tuple[Vec, Vec] | None:
    """バンパーに触れているなら (押し戻した位置, 弾かれた速度)。"""
    away = pos - bumper.center
    dist = abs(away)
    if dist >= bumper.radius + BALL_RADIUS or dist == 0:
        return None

    normal = away / dist                                    # 中心からボールへ
    pos = bumper.center + normal * (bumper.radius + BALL_RADIUS)
    vel = reflect(vel, normal) if vel @ normal < 0 else vel
    return pos, vel + normal * BUMPER_BOOST                 # 少し強く弾き返す


def make_walls() -> list[Segment]:
    """動かない壁。外周・右のレーン・下の斜めガイド。"""
    return [
        Segment(Vec(0, 0), Vec(0, HEIGHT - 1)),             # 左
        Segment(Vec(WIDTH - 1, 0), Vec(WIDTH - 1, HEIGHT - 1)),   # 右
        Segment(Vec(0, 0), Vec(25, 0)),                     # 天井
        Segment(Vec(25, 0), Vec(WIDTH - 1, 6)),             # 右上の斜め。レーンから上がった球を左へ流す
        Segment(Vec(28, 8), Vec(28, HEIGHT - 1)),           # レーンの壁
        Segment(Vec(28, HEIGHT - 1), Vec(WIDTH - 1, HEIGHT - 1)),   # レーンの底
        Segment(Vec(0, 16), Vec(11, 23)),                   # 左のガイド
        Segment(Vec(28, 16), Vec(20, 23)),                  # 右のガイド
    ]


def make_bumpers() -> list[Bumper]:
    return [Bumper(Vec(8, 7)), Bumper(Vec(16, 5)), Bumper(Vec(24, 9)), Bumper(Vec(13, 13)), Bumper(Vec(20, 13))]


def make_flippers() -> dict[str, Flipper]:
    """左右のフリッパー。休んでいるときは下向き、上げると水平より少し上。"""
    return {
        "left": Flipper(Vec(11, 23), rest_degrees=30, up_degrees=-25),
        "right": Flipper(Vec(20, 23), rest_degrees=150, up_degrees=205),
    }


class Game:
    """1 回ぶんのピンボール。壁・フリッパー・バンパー・ボール・得点を持つ。"""

    def __init__(self, seed: int | None = None):
        if seed is not None:
            random.seed(seed)

        self.walls = make_walls()
        self.bumpers = make_bumpers()
        self.flippers = make_flippers()
        self.balls = BALLS
        self.score = 0
        self.ball = self.lane_start()
        self.vel = Vec(0, 0)
        self.phase = "ready"                                # "ready"（打ち出し待ち）→ "play" → "over"
        self.result: str | None = None

    def lane_start(self) -> Vec:
        return Vec(30, HEIGHT - 2)

    def launch(self) -> bool:
        """レーンから打ち出す。打ち出し待ちのときだけ。"""
        if self.phase != "ready":
            return False
        self.vel = Vec(0, -random.uniform(*LAUNCH_SPEED))
        self.phase = "play"
        return True

    def flip(self, side: str) -> None:
        if self.phase == "over":
            return
        self.flippers[side].flip()

    def update(self, dt: float) -> None:
        """dt 秒ぶん進める。物理は SUBSTEPS 回に刻む。"""
        if self.phase == "over":
            return

        for flipper in self.flippers.values():
            flipper.update(dt)
        for bumper in self.bumpers:
            bumper.lit = max(0.0, bumper.lit - dt)

        if self.phase != "play":
            return

        h = dt / SUBSTEPS
        for _ in range(SUBSTEPS):
            self.step(h)
            if self.phase != "play":
                break

    def step(self, h: float) -> None:
        """物理を h 秒ぶん 1 回進める。"""
        self.vel = self.vel + Vec(0, GRAVITY) * h           # 重力
        prev = self.ball
        self.ball = self.ball + self.vel * h

        for bumper in self.bumpers:
            hit = hit_bumper(self.ball, self.vel, bumper)
            if hit is not None:
                self.ball, self.vel = hit
                self.score += BUMPER_SCORE
                bumper.lit = LIT_TIME

        for seg in self.walls:
            hit = hit_segment(prev, self.ball, self.vel, seg)
            if hit is not None:
                self.ball, self.vel = hit

        for flipper in self.flippers.values():
            hit = hit_segment(prev, self.ball, self.vel, flipper.segment)
            if hit is not None:
                self.ball, self.vel = hit
                if flipper.active:                          # 上がっている最中なら強く打ち出す
                    self.vel = self.vel + flipper.segment.normal_toward(self.ball) * FLIP_BOOST

        if abs(self.vel) > MAX_SPEED:                       # 速すぎるボールは抑える
            self.vel = self.vel.normalized() * MAX_SPEED

        if self.ball.y > HEIGHT:                            # フリッパーの間から落ちた
            self.balls -= 1
            self.ball = self.lane_start()
            self.vel = Vec(0, 0)
            if self.balls == 0:
                self.phase = "over"
                self.result = "over"
            else:
                self.phase = "ready"
        elif self.ball.x > 28.5 and self.ball.y > HEIGHT - 3 and abs(self.vel) < 4:
            self.phase = "ready"                            # レーンに戻ってきて止まった。もう一度打てる
            self.ball = self.lane_start()
            self.vel = Vec(0, 0)


# --- ここから下はブラウザ版だけ。CLI 版の read_key() / render() / main() にあたる ---

KEYMAP = {  # ブラウザが送ってくる名前 → CLI 版と同じ操作
    "z": "left",
    "x": "right",
    "m": "right",
    " ": "launch",
    "ArrowLeft": "left",
    "ArrowRight": "right",
}

walls_group = document.querySelector("#walls")
bumpers_group = document.querySelector("#bumpers")
flip_left = document.querySelector("#flip-left")
flip_right = document.querySelector("#flip-right")
ball_el = document.querySelector("#ball")
score_label = document.querySelector("#score")
balls_label = document.querySelector("#balls")
message = document.querySelector("#message")
launch_button = document.querySelector("#launch-btn")
start_button = document.querySelector("#start-btn")

# 状態は Game が全部持っている。ブラウザ側が覚えるのは時計だけ
game = Game()
last = 0.0
bumper_elements = []


def svg(tag: str, **attrs):
    """SVG の要素を作る。<line x1=... /> のような属性を辞書で渡す。"""
    element = document.createElementNS(SVG, tag)
    for name, value in attrs.items():
        element.setAttribute(name.replace("_", "-"), str(value))
    return element


def set_line(element, seg: Segment) -> None:
    """<line> の両端を線分に合わせる。CLI 版の raster() にあたる。"""
    element.setAttribute("x1", f"{seg.a.x:.2f}")
    element.setAttribute("y1", f"{seg.a.y:.2f}")
    element.setAttribute("x2", f"{seg.b.x:.2f}")
    element.setAttribute("y2", f"{seg.b.y:.2f}")


def build():
    """動かない壁とバンパーを SVG に置く。新しいゲームのときだけ。"""
    global bumper_elements

    walls_group.replaceChildren()
    for seg in game.walls:
        line = svg("line", **{"class": "wall"})
        set_line(line, seg)
        walls_group.appendChild(line)

    bumpers_group.replaceChildren()
    bumper_elements = []
    for bumper in game.bumpers:
        circle = svg("circle", **{"class": "bumper"}, cx=f"{bumper.center.x:.2f}", cy=f"{bumper.center.y:.2f}", r=bumper.radius)
        bumpers_group.appendChild(circle)
        bumper_elements.append(circle)


def draw():
    """CLI 版の render() にあたる。動くものの座標だけ書き換える。"""
    ball_el.setAttribute("cx", f"{game.ball.x:.2f}")
    ball_el.setAttribute("cy", f"{game.ball.y:.2f}")
    set_line(flip_left, game.flippers["left"].segment)
    set_line(flip_right, game.flippers["right"].segment)

    for bumper, circle in zip(game.bumpers, bumper_elements):
        circle.setAttribute("class", "bumper lit" if bumper.lit > 0 else "bumper")

    score_label.textContent = str(game.score)
    balls_label.textContent = str(game.balls)
    launch_button.disabled = game.phase != "ready"


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

    message.textContent = f"{RESULT_TEXT[game.result]}  得点 {game.score}"
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
    if action == "launch":
        game.launch()
    elif action in ("left", "right"):
        game.flip(action)
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


@when("click", "#launch-btn")
def on_launch(event):
    act("launch")


@when("click", "#start-btn")
def on_start(event):
    start()


# Pyodide の読み込みが終わってから実行される＝ここが準備完了の合図
document.querySelector("#loading").hidden = True
start()
