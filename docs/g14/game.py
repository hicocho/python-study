"""ブロック崩し（ブラウザ版）

CLI 版（g14-breakout/main.py）とボールの物理・当たり判定・ルールはまったく同じ。
定数 13 個と class Vec、normalized() / serve() / bounce() / paddle_hit() / make_blocks() /
block_cell() / block_hit()、そして class Game を、ステップの目印コメント（# ←）を外しただけで
1 文字も変えずに持ってきている。

持ってこなかったのは field_text() と raw_mode() / read_key() / main()、それに Game.render() だけ。
違うのは入口と出口で、入口は select で待つ生キー入力ではなく asyncio の時計とキーイベント、
出口は 1 マス 1 文字の盤ではなく、マスの座標を % に直して置いた <div>。
だから CLI 版では round() で丸めていたボールの位置が、ここでは小数のまま滑らかに見える。
"""

import asyncio
import math
import random
import time
from dataclasses import dataclass

from pyscript import document, when


# --- ここから class Game まで、CLI 版（g14-breakout/main.py）からそのまま ---


WIDTH = 40                                  # 盤の横のマス数
HEIGHT = 20                                 # 盤の縦のマス数
FRAME_SECONDS = 0.05                        # キーを待つ時間 ＝ 描き直す間隔
MAX_DT = 0.05                               # 1 回に進める時間の上限（止まっていた後に飛ばないように）
PADDLE_WIDTH = 7
PADDLE_STEP = 2                             # 1 回のキーで動くマス
BALL_SPEED = 16.0                           # 1 秒に進むマス数
SPEED_UP_EVERY = 8                          # ブロックをこの数壊すごとに
SPEED_UP = 2.0                              # 速さがこれだけ増える
LIVES = 3
BLOCK_WIDTH = 4                             # ブロック 1 個の横幅（マス）
BLOCK_ROWS = range(2, 6)                    # ブロックがある行
SCORE_PER_BLOCK = 10


RESULT_TEXT = {
    "clear": "全部壊した！",
    "over": "ボールを落としきった…",
    "quit": "やめました。",
}


@dataclass(frozen=True)
class Vec:
    """2 次元のベクトル。位置にも速度にも使う。演算子で足し引きできる。"""

    x: float
    y: float

    def __add__(self, other: "Vec") -> "Vec":
        return Vec(self.x + other.x, self.y + other.y)

    def __sub__(self, other: "Vec") -> "Vec":
        return Vec(self.x - other.x, self.y - other.y)

    def __mul__(self, k: float) -> "Vec":
        return Vec(self.x * k, self.y * k)

    __rmul__ = __mul__                                      # 2 * v も v * 2 と同じ

    def __neg__(self) -> "Vec":
        return Vec(-self.x, -self.y)

    def __abs__(self) -> float:
        """abs(v) で長さ。"""
        return math.hypot(self.x, self.y)

    def __iter__(self):
        """x, y = v とほどけるように。"""
        yield self.x
        yield self.y


def normalized(v: Vec, speed: float) -> Vec:
    """向きはそのまま、長さを speed にしたベクトルを返す。"""
    return v * (speed / abs(v))


def serve(paddle_x: int, speed: float) -> tuple[Vec, Vec]:
    """パドルの上にボールを置き、左右どちらかへ打ち上げる。(位置, 速度) を返す。"""
    ball = Vec(paddle_x + (PADDLE_WIDTH - 1) / 2, HEIGHT - 3)
    vel = normalized(Vec(random.choice([-0.5, 0.5]), -1), speed)
    return ball, vel


def bounce(ball: Vec, vel: Vec, dt: float) -> Vec:
    """次の位置が左右の壁か天井を越えるなら、その向きの速度を反転した速度を返す。"""
    nxt = ball + vel * dt
    vx, vy = vel

    if not 0 <= nxt.x <= WIDTH - 1:
        vx = -vx
    if nxt.y < 0:                                           # 下は壁がない。落ちる
        vy = -vy

    return Vec(vx, vy)


def paddle_hit(ball: Vec, vel: Vec, dt: float, paddle_x: int) -> Vec | None:
    """次の位置でパドルに当たるなら跳ね返した速度を、当たらなければ None を返す。"""
    nxt = ball + vel * dt
    if vel.y <= 0 or nxt.y < HEIGHT - 1:
        return None
    if not paddle_x - 0.5 <= nxt.x <= paddle_x + PADDLE_WIDTH - 0.5:
        return None

    center = paddle_x + (PADDLE_WIDTH - 1) / 2
    offset = (nxt.x - center) / (PADDLE_WIDTH / 2)          # -1（左端）〜 1（右端）
    return normalized(Vec(offset * 1.2, -1), abs(vel))      # 端に当たるほど横へ飛ぶ


def make_blocks() -> set[tuple[int, int]]:
    """ブロックの集まりを (行, 列) の集合で返す。"""
    return {(row, col) for row in BLOCK_ROWS for col in range(WIDTH // BLOCK_WIDTH)}


def block_cell(pos: Vec) -> tuple[int, int]:
    """位置が入っているブロックのマス (行, 列)。ブロックは横 BLOCK_WIDTH マスで 1 個。"""
    return math.floor(pos.y + 0.5), math.floor(pos.x + 0.5) // BLOCK_WIDTH


def block_hit(ball: Vec, vel: Vec, dt: float, blocks: set[tuple[int, int]]) -> tuple[Vec, tuple[int, int] | None]:
    """次の位置にブロックがあれば (跳ね返した速度, そのブロック) を、無ければ (そのままの速度, None) を返す。"""
    nxt = ball + vel * dt
    cell = block_cell(nxt)
    if cell not in blocks:
        return vel, None

    prev = block_cell(ball)                                 # 1 コマ前はどのマスにいたか
    vx, vy = vel
    if prev[0] != cell[0]:                                  # 行が変わった ＝ 上下から当たった
        vy = -vy
    if prev[1] != cell[1]:                                  # 列が変わった ＝ 横から当たった
        vx = -vx

    return Vec(vx, vy), cell


class Game:
    """1 回ぶんのブロック崩し。ボール・パドル・ブロック・残機・得点を持つ。"""

    def __init__(self, seed: int | None = None):
        if seed is not None:
            random.seed(seed)

        self.paddle_x = (WIDTH - PADDLE_WIDTH) // 2
        self.blocks = make_blocks()
        self.lives = LIVES
        self.score = 0
        self.cleared = 0
        self.ball, self.vel = serve(self.paddle_x, self.speed)
        self.result: str | None = None                      # "clear" / "over" / "quit"

    @property
    def speed(self) -> float:
        """壊した数に応じて速くなる。"""
        return BALL_SPEED + (self.cleared // SPEED_UP_EVERY) * SPEED_UP

    def move_paddle(self, direction: str) -> None:
        if self.result is not None:
            return
        if direction == "left":
            self.paddle_x = max(0, self.paddle_x - PADDLE_STEP)
        elif direction == "right":
            self.paddle_x = min(WIDTH - PADDLE_WIDTH, self.paddle_x + PADDLE_STEP)

    def update(self, dt: float) -> None:
        """dt 秒ぶん進める。当たり判定はパドル → ブロック、最後に必ず壁。"""
        if self.result is not None:
            return

        hit = paddle_hit(self.ball, self.vel, dt, self.paddle_x)
        if hit is not None:
            self.vel = hit
        else:
            self.vel, block = block_hit(self.ball, self.vel, dt, self.blocks)
            if block is not None:
                self.blocks.discard(block)
                self.score += SCORE_PER_BLOCK
                self.cleared += 1
                self.vel = normalized(self.vel, self.speed)  # 壊すたびに速さを合わせ直す

        self.vel = bounce(self.ball, self.vel, dt)          # 壁はいつでも最後に見る
        self.ball = self.ball + self.vel * dt

        if not self.blocks:
            self.result = "clear"
        elif self.ball.y > HEIGHT - 1:                      # パドルの下へ落ちた
            self.lives -= 1
            if self.lives == 0:
                self.result = "over"
            else:
                self.ball, self.vel = serve(self.paddle_x, self.speed)


# --- ここから下はブラウザ版だけ。CLI 版の read_key() / main() にあたる ---

KEYS = {  # ブラウザが送ってくる名前 → CLI 版と同じ呼び名
    "ArrowLeft": "left",
    "ArrowRight": "right",
}

field = document.querySelector("#field")
ball_el = document.querySelector("#ball")
paddle_el = document.querySelector("#paddle")
score_label = document.querySelector("#score")
lives_label = document.querySelector("#lives")
left_label = document.querySelector("#left")
speed_label = document.querySelector("#speed")
message = document.querySelector("#message")
start_button = document.querySelector("#start-btn")

# 状態は Game が全部持っている。ブラウザ側が覚えるのは「動いているか」と時計だけ
game = Game()
playing = False
last = 0.0
block_elements = {}                                         # (行, 列) → <div>


def percent(x: float, size: int) -> str:
    """マスの座標を盤の % に直す。マスの中央に置くので +0.5。"""
    return f"{(x + 0.5) / size * 100:.2f}%"


def build_blocks():
    """ブロックの <div> を作り直す。新しいゲームのときだけ。"""
    for element in block_elements.values():
        element.remove()
    block_elements.clear()

    for row, col in sorted(game.blocks):
        element = document.createElement("div")
        element.className = f"block r{row}"
        element.style.left = f"{col * BLOCK_WIDTH / WIDTH * 100:.2f}%"
        element.style.top = f"{row / HEIGHT * 100:.2f}%"
        field.appendChild(element)
        block_elements[(row, col)] = element


def draw():
    """CLI 版の render() にあたる。文字ではなく、位置を % で置く。"""
    ball_el.style.left = percent(game.ball.x, WIDTH)
    ball_el.style.top = percent(game.ball.y, HEIGHT)
    paddle_el.style.left = f"{game.paddle_x / WIDTH * 100:.2f}%"
    paddle_el.style.width = f"{PADDLE_WIDTH / WIDTH * 100:.2f}%"

    for key, element in block_elements.items():
        element.hidden = key not in game.blocks             # 壊れたブロックは隠すだけ

    score_label.textContent = str(game.score)
    lives_label.textContent = str(game.lives)
    left_label.textContent = str(len(game.blocks))
    speed_label.textContent = f"{game.speed:.0f}"


def finish():
    global playing

    playing = False
    message.textContent = f"{RESULT_TEXT[game.result]}  得点 {game.score}"
    start_button.textContent = "もう一度"
    start_button.disabled = False


async def tick():
    """時間を進める係。CLI 版の read_key(FRAME_SECONDS) の待ち時間にあたる。"""
    global last

    while playing:
        await asyncio.sleep(FRAME_SECONDS)
        if not playing:
            break
        now = time.monotonic()
        dt = min(now - last, MAX_DT)                        # 実際に経った時間ぶんだけ進める
        last = now
        game.update(dt)
        draw()
        if game.result is not None:
            finish()


def start():
    global game, playing, last

    game = Game()                                           # 作り直すだけで初期化になる
    playing = True
    last = time.monotonic()
    message.textContent = ""
    start_button.disabled = True
    build_blocks()
    draw()
    asyncio.ensure_future(tick())                           # 待ち続ける係を裏で走らせる


def act(direction):
    if playing:
        game.move_paddle(direction)
        draw()


@when("keydown", "body")
def on_key(event):
    if event.key == "Enter":
        if not playing:
            start()
        return

    direction = KEYS.get(event.key)
    if direction is None:
        return

    event.preventDefault()                                  # 矢印でページが動かないように
    act(direction)


@when("click", "#start-btn")
def on_start(event):
    start()


@when("click", "#left-btn")
def on_left(event):
    act("left")


@when("click", "#right-btn")
def on_right(event):
    act("right")


# Pyodide の読み込みが終わってから実行される＝ここが準備完了の合図
document.querySelector("#loading").hidden = True
start_button.disabled = False
build_blocks()
draw()
