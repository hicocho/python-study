"""ブロック崩し — 完成: class Game にまとめ、ブロックが減るほど速くなる。"""

import math
import os
import random
import select
import sys
import termios
import time
import tty
from contextlib import contextmanager
from dataclasses import dataclass

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

ARROWS = {
    "\x1b[C": "right",
    "\x1b[D": "left",
}

RESULT_TEXT = {                             # ←
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


def field_text(ball: Vec, paddle_x: int, blocks: set[tuple[int, int]]) -> str:
    """盤を表示用の文字列にして返す。o ボール / = パドル / # ブロック。"""
    bx, by = round(ball.x), round(ball.y)                   # マスに丸める
    lines = ["+" + "-" * WIDTH + "+"]
    for y in range(HEIGHT):
        chars = []
        for x in range(WIDTH):
            if (x, y) == (bx, by):
                chars.append("o")
            elif y == HEIGHT - 1 and paddle_x <= x < paddle_x + PADDLE_WIDTH:
                chars.append("=")
            elif (y, x // BLOCK_WIDTH) in blocks:
                chars.append("#")
            else:
                chars.append(" ")
        lines.append("|" + "".join(chars) + "|")
    lines.append("+" + "-" * WIDTH + "+")
    return "\n".join(lines)


class Game:                                 # ←
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

    def render(self) -> str:
        """端末に出す文字列。上書きで描くので桁は固定。"""
        status = (f"得点 {self.score:4d}   残機 {self.lives}   残り {len(self.blocks):2d} 個   "
                  f"速さ {self.speed:4.1f}   ← → / q でやめる")
        return f"{field_text(self.ball, self.paddle_x, self.blocks)}\n{status}\n"


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
    data = os.read(sys.stdin.fileno(), 8)
    key = data.decode()
    return ARROWS.get(key, key)


def main():                                 # ←
    game = Game()

    print("\x1b[2J", end="")
    last = time.monotonic()
    with raw_mode():
        while game.result is None:
            sys.stdout.write("\x1b[H" + game.render())
            sys.stdout.flush()

            key = read_key(FRAME_SECONDS)
            now = time.monotonic()
            dt = min(now - last, MAX_DT)                    # 実際に経った時間ぶんだけ進める
            last = now

            if key == "q":
                game.result = "quit"
            elif key is not None:
                game.move_paddle(key)

            game.update(dt)

    sys.stdout.write("\x1b[H" + game.render())
    print(f"\n{RESULT_TEXT[game.result]}  得点 {game.score}")


if __name__ == "__main__":
    main()
