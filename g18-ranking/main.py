"""ランキング — 完成: 小惑星の得点を sqlite3 に残し、上位 10 件を出す。"""

import argparse
import cmath
import os
import random
import select
import sqlite3
import sys
import termios
import time
import tty
import unicodedata
from abc import ABC, abstractmethod
from contextlib import closing, contextmanager
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).with_name("ranking.db")    # main.py の隣。どこから起動しても同じ場所
TOP_N = 10

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


ARROWS = {
    "\x1b[A": "thrust",
    "\x1b[C": "right",
    "\x1b[D": "left",
    " ": "fire",
}


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


def circle_cells(center: complex, radius: float) -> set[tuple[int, int]]:
    """中心と半径から、その円に入るマスの集合（端はループ）。"""
    cx, cy = center.real, center.imag
    return {(x % WIDTH, y % HEIGHT)
            for y in range(int(cy - radius) - 1, int(cy + radius) + 2)
            for x in range(int(cx - radius) - 1, int(cx + radius) + 2)
            if (x - cx) ** 2 + (y - cy) ** 2 <= radius * radius}


def field_text(ship: Ship, asteroids: list[Asteroid], bullets: list[Bullet]) -> str:
    """画面を文字列にして返す。小惑星は大きさの文字で円を埋める。"""
    chars = {}
    for asteroid in asteroids:
        for cell in circle_cells(asteroid.pos, asteroid.radius):
            chars[cell] = asteroid.char
    for bullet in bullets:
        chars[(round(bullet.pos.real) % WIDTH, round(bullet.pos.imag) % HEIGHT)] = bullet.char
    if ship.alive and (ship.safe == 0 or int(ship.safe * 8) % 2 == 0):     # 無敵中は点滅
        chars[(round(ship.pos.real) % WIDTH, round(ship.pos.imag) % HEIGHT)] = ship.char

    lines = ["+" + "-" * WIDTH + "+"]
    for y in range(HEIGHT):
        lines.append("|" + "".join(chars.get((x, y), " ") for x in range(WIDTH)) + "|")
    lines.append("+" + "-" * WIDTH + "+")
    return "\n".join(lines)


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

    def render(self) -> str:
        board = field_text(self.ship, self.asteroids, self.bullets)
        status = (f"得点 {self.score:5d}   船 {self.lives}   ウェーブ {self.wave}   "
                  f"残り {len(self.asteroids):2d}   ← → 回転 / ↑ 加速 / スペース 発射 / q")
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


def display_width(text: str) -> int:
    """端末で何桁ぶんの幅になるか。全角は 2、半角は 1。"""
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def pad(text: str, width: int) -> str:
    """幅 width になるまで右に空白を足す。全角が混ざっても揃う。"""
    return text + " " * max(0, width - display_width(text))


class Ranking:
    """得点の記録。sqlite3 のファイル 1 つに残す。"""

    def __init__(self, path: Path | str = DB_PATH):
        self.path = str(path)
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS scores (
                    id        INTEGER PRIMARY KEY,
                    name      TEXT    NOT NULL,
                    score     INTEGER NOT NULL,
                    wave      INTEGER NOT NULL,
                    played_at TEXT    NOT NULL
                )
            """)
            conn.commit()

    def add(self, name: str, score: int, wave: int) -> int:
        """1 件足して、その得点が何位かを返す（同点は先に出した人が上）。"""
        with closing(sqlite3.connect(self.path)) as conn:
            cursor = conn.execute(
                "INSERT INTO scores (name, score, wave, played_at) VALUES (?, ?, ?, ?)",
                (name, score, wave, datetime.now().isoformat(timespec="seconds")),
            )
            conn.commit()
            (above,) = conn.execute(
                "SELECT COUNT(*) FROM scores WHERE score > ? OR (score = ? AND id < ?)",
                (score, score, cursor.lastrowid),
            ).fetchone()
            return above + 1

    def top(self, n: int = TOP_N) -> list[tuple[str, int, int, str]]:
        """上位 n 件を (名前, 得点, ウェーブ, 日時) で返す。"""
        with closing(sqlite3.connect(self.path)) as conn:
            return conn.execute(
                "SELECT name, score, wave, played_at FROM scores ORDER BY score DESC, id ASC LIMIT ?",
                (n,),
            ).fetchall()

    def count(self) -> int:
        with closing(sqlite3.connect(self.path)) as conn:
            (n,) = conn.execute("SELECT COUNT(*) FROM scores").fetchone()
            return n

    def reset(self) -> None:                # ←
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute("DELETE FROM scores")
            conn.commit()


def ranking_text(rows: list[tuple[str, int, int, str]], highlight: int | None = None) -> str:
    """順位表を文字列にして返す。highlight 位の行に ★ を付ける。"""
    if not rows:
        return "まだ記録がありません。"
    lines = ["   " + pad("名前", 12) + "  " + pad("得点", 6) + "  " + pad("ウェーブ", 8) + "  日時"]
    for i, (name, score, wave, played_at) in enumerate(rows, start=1):
        mark = "★" if i == highlight else " "
        lines.append(f"{mark}{i:2d} {pad(name, 12)}  {score:>6}  {wave:>8}  {played_at[:16].replace('T', ' ')}")
    return "\n".join(lines)


def ask_name() -> str:
    """名前を聞く。空なら「名無し」。"""
    name = input("名前を入れてください（Enter で 名無し）> ").strip()
    return name[:12] if name else "名無し"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="小惑星を遊んで、得点をランキングに残す。")
    parser.add_argument("--top", type=int, metavar="N", help="遊ばずに上位 N 件を表示する")
    parser.add_argument("--name", help="終わったあとの名前入力を省く") # ←
    parser.add_argument("--reset", action="store_true", help="記録を全部消す") # ←
    parser.add_argument("--db", default=DB_PATH, help="記録ファイルの場所（既定は main.py の隣）")
    return parser.parse_args()


def play() -> Game:
    """小惑星を 1 回遊んで、終わった Game を返す。"""
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
                game.ship.thrust()
            elif key in ("left", "right"):
                game.ship.turn(key)
            elif key == "fire":
                game.fire()

            game.update(dt)

    sys.stdout.write("\x1b[H" + game.render())
    print(f"\n{RESULT_TEXT[game.result]}  得点 {game.score}  ウェーブ {game.wave}")
    return game


def main():
    args = parse_args()
    ranking = Ranking(args.db)

    if args.reset:                          # ←
        if input(f"{ranking.count()} 件の記録を消します。よろしいですか？ (y/N) > ").strip().lower() == "y":
            ranking.reset()
            print("消しました。")
        return

    if args.top is not None:
        print(ranking_text(ranking.top(args.top)))
        return

    top3 = ranking.top(3)
    if top3:
        print("これまでの上位 3 件\n" + ranking_text(top3) + "\n")
    input("Enter でスタート > ")

    game = play()
    if game.score == 0:
        print("0 点は記録しません。")
        return

    name = args.name or ask_name()          # ←
    rank = ranking.add(name, game.score, game.wave)
    print(f"\n{name} さんは {rank} 位（{ranking.count()} 件中）\n")
    print(ranking_text(ranking.top(), highlight=rank if rank <= TOP_N else None))


if __name__ == "__main__":
    main()
