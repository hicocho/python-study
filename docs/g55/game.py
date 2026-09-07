"""パックマン風（迷路とパックマン）ブラウザ版

CLI 版（g55-pacman-maze/main.py）と迷路・動き・エサの判定はまったく同じ。
定数と MAZE_TEXT、Maze / Direction、ドット絵と Sprite / Screen / png_bytes()、Pacman、
draw 一式、eat() / sight()、そして class Game を、ステップの目印コメント（# ←）を外しただけで
1 文字も変えずに持ってきている。

持ってこなかったのは端末に描く Screen.render() と、それを使う play() / read_keys() /
check_terminal() / main() だけ。出口は canvas。Screen をそのまま使って画素の板を作り、
最後に ImageData へ 1 回で流し込む（塗る点が 2000 を超えるので、1 点ずつ fillRect すると間に合わない）。
"""

import asyncio
import base64
import random
import struct
import zlib
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import InitVar, dataclass, field
from enum import Enum
from functools import cache
from itertools import batched, count, takewhile
from types import MappingProxyType
from typing import Self

from js import window
from pyscript import document, when

WALL = "#"
DOOR = "-"                                          # 巣の扉。パックマンは通れない
PELLET = "."
POWER = "o"
EMPTY = " "
START = "P"                                         # パックマンの出発点（エサは無い）
FPS = 30
SPEED = 6.0                                         # 1 秒に進むマス数
PELLET_SCORE = 10
POWER_SCORE = 50


RESULT_TEXT = {
    "clear": "クリア！ {game.score} 点、{game.elapsed:.1f} 秒。",
    "quit": "やめました。{game.score} 点、残り {game.remaining} 個。",
}


MAZE_TEXT = """
#####################
#.........#.........#
#o###.###.#.###.###o#
#...................#
#.#####.#####.#####.#
#....##.##-##.##....#
####.##.#   #.##.####
.....##.#####.##.....
####.##...P...##.####
#.........#.........#
#o##.####.#.####.##o#
#...................#
#####################
"""


class Maze(Mapping):                                # Mapping を継承すると get・items・in がついてくる
    """迷路 1 枚。(x, y) から文字を引ける読み取り専用の入れ物。"""

    def __init__(self, rows: tuple[str, ...]):
        self.rows = rows

    @classmethod
    def from_text(cls, text: str) -> Self:          # 戻り値が「このクラス」だと書ける
        """三重引用符の迷路から作る。行の幅がそろっていなければここで気づく。"""
        rows = tuple(line for line in text.splitlines() if line.strip())
        list(zip(*rows, strict=True))               # 幅が違う行があると ValueError。zip は遅延なので list で使い切る
        return cls(rows)

    # --- Mapping が求める 3 つ。これだけ書けば残りは Mapping が用意する ---
    def __getitem__(self, pos: tuple[int, int]) -> str:
        x, y = pos
        if not (0 <= x < self.width and 0 <= y < self.height):
            raise KeyError(pos)                     # IndexError ではなく KeyError。get の既定値が効くようになる
        return self.rows[y][x]

    def __iter__(self):
        return ((x, y) for y in range(self.height) for x in range(self.width))

    def __len__(self) -> int:
        return self.width * self.height

    @property
    def width(self) -> int:
        return len(self.rows[0])

    @property
    def height(self) -> int:
        return len(self.rows)

    def wall(self, pos: tuple[int, int]) -> bool:
        """パックマンが通れないマスか。迷路の外も壁とみなす。"""
        return self.get(pos, WALL) in (WALL, DOOR)  # 外は KeyError → get の既定値 WALL

    def ahead(self, pos: tuple[int, int], d: "Direction") -> tuple[int, int]:
        """pos の d 方向の隣。左右は端で反対側につながる（トンネル）。"""
        x, y = pos
        return (x + d.dx) % self.width, y + d.dy                                # 横だけ剰余で回す

    def corridor(self, pos: tuple[int, int], d: "Direction") -> list[tuple[int, int]]:
        """pos から d の向きに、壁にぶつかるまでのマスを順に。トンネルも通る。"""
        ahead = (self.reach(pos, d, n) for n in count(1))                                # 1 マス先、2 マス先…と無限に作り
        return list(takewhile(lambda p: not self.wall(p), ahead))                        # 壁が出るまでで打ち切る

    def reach(self, pos: tuple[int, int], d: "Direction", n: int) -> tuple[int, int]:
        """pos から d の向きに n マス先。"""
        x, y = pos
        return (x + d.dx * n) % self.width, y + d.dy * n

    def start(self) -> tuple[int, int]:
        """P の位置。"""
        for pos, ch in self.items():                # items も Mapping が用意したもの
            if ch == START:
                return pos
        raise ValueError("出発点 P がありません")

    def pellets(self) -> dict[tuple[int, int], str]:
        """エサの一覧。{(x, y): "." または "o"}"""
        return {pos: ch for pos, ch in self.items() if ch in (PELLET, POWER)}


class Direction(Enum):
    """4 方向。値がそのまま (dx, dy) のベクトル。"""

    UP = (0, -1)
    DOWN = (0, 1)
    LEFT = (-1, 0)
    RIGHT = (1, 0)

    @property
    def dx(self) -> int:
        return self.value[0]

    @property
    def dy(self) -> int:
        return self.value[1]

    @property
    def opposite(self) -> Self:                     # 戻り値も Direction。Self と書けば名前を繰り返さずに済む
        return Direction((-self.dx, -self.dy))      # 値から逆引きできるのが Enum の便利なところ


KEY_TO_DIR = MappingProxyType({                     # 定数の辞書。うっかり書き換えると TypeError になる
    "up": Direction.UP, "down": Direction.DOWN, "left": Direction.LEFT, "right": Direction.RIGHT,
})


CELL = 6                                            # 1 マス = 6 ドット
HUD_H = 8                                           # 上の得点欄の高さ
WIDTH = 21 * CELL                                   # 126 ドット
HEIGHT = HUD_H + 13 * CELL                          # 86 ドット → 端末では 43 行
WALL_COLOR = (33, 33, 222)                          # 本家の青い壁
DOOR_COLOR = (255, 184, 255)
PELLET_COLOR = (255, 184, 151)
PAC_COLOR = (255, 255, 0)
TEXT_COLOR = (222, 222, 255)
PALETTE = {"Y": PAC_COLOR, "W": (255, 255, 255), "K": (0, 0, 0)}


@dataclass(frozen=True)
class Sprite:
    """ドット絵 1 枚。rows は 1 行 1 文字列で、文字がパレットの色、. が透明。"""

    name: str
    rows: tuple[str, ...]
    palette: dict[str, tuple[int, int, int]] = field(default_factory=lambda: PALETTE, hash=False, compare=False)

    @property
    def width(self) -> int:
        return len(self.rows[0])

    @property
    def height(self) -> int:
        return len(self.rows)

    @property
    def pixels(self) -> list[tuple[int, int, tuple[int, int, int]]]:
        """(x, y, 色) の一覧。透明は含まない。"""
        return [(x, y, self.palette[ch]) for y, row in enumerate(self.rows) for x, ch in enumerate(row) if ch != "."]

    def __str__(self) -> str:
        return "\n".join(self.rows)


def sprite(name: str, art: str) -> Sprite:
    """三重引用符のドット絵から Sprite を作る。空行は無視、幅は最長の行にそろえる。"""
    rows = [line for line in art.splitlines() if line.strip()]
    width = max(len(r) for r in rows)
    return Sprite(name, tuple(r.ljust(width, ".") for r in rows))


def turned(spr: Sprite, name: str, quarter: int) -> Sprite:
    """右向きの絵を 90° ずつ回して、上・左・下向きを作る。"""
    rows = spr.rows
    for _ in range(quarter % 4):
        rows = tuple("".join(col) for col in zip(*rows[::-1]))   # 時計回りに 90°
    return Sprite(name, rows)


PAC_RIGHT = [
    sprite("pac-0", """
..YYY..
.YYYYY.
YYYYYYY
YYYYYYY
YYYYYYY
.YYYYY.
..YYY..
"""),
    sprite("pac-1", """
..YYY..
.YYYYY.
YYYYY..
YYYY...
YYYYY..
.YYYYY.
..YYY..
"""),
    sprite("pac-2", """
..YYY..
.YYYY..
YYYY...
YYY....
YYYY...
.YYYY..
..YYY..
"""),
]


PAC_SPRITES = {
    d: [turned(s, f"pac-{d.name.lower()}-{i}", q) for i, s in enumerate(PAC_RIGHT)]
    for d, q in ((Direction.RIGHT, 0), (Direction.DOWN, 1), (Direction.LEFT, 2), (Direction.UP, 3))
}


DIGIT_FLAT = {
    "0": "WWWW.WW.WW.WWWW", "1": ".W.WW..W..W.WWW", "2": "WWW..WWWWW..WWW", "3": "WWW..WWWW..WWWW",
    "4": "W.WW.WWWW..W..W", "5": "WWWW..WWW..WWWW", "6": "WWWW..WWWW.WWWW", "7": "WWW..W..W..W..W",
    "8": "WWWW.WWWWW.WWWW", "9": "WWWW.WWWW..WWWW",
}


DIGITS = {ch: Sprite(f"digit-{ch}", tuple("".join(row) for row in batched(flat, 3)))   # 15 文字を 3 文字ずつ 5 行に
          for ch, flat in DIGIT_FLAT.items()}


class Screen:
    """WIDTH × HEIGHT のドットのキャンバス。1 ドットは RGB か None（黒）。"""

    def __init__(self):
        self.pixels: list[list[tuple[int, int, int] | None]] = [[None] * WIDTH for _ in range(HEIGHT)]

    def clear(self) -> None:
        for row in self.pixels:
            row[:] = [None] * WIDTH

    def plot(self, x: int, y: int, color: tuple[int, int, int]) -> None:
        if 0 <= x < WIDTH and 0 <= y < HEIGHT:
            self.pixels[y][x] = color

    def blit(self, spr: Sprite, x: float, y: float) -> None:
        """スプライトを (x, y) を左上にして置く。透明は上書きしない。"""
        ox, oy = round(x), round(y)
        for px, py, color in spr.pixels:
            self.plot(ox + px, oy + py, color)

    def text(self, s: str, x: int, y: int) -> None:
        """3×5 の数字で文字列を描く。数字以外は空ける。"""
        for i, ch in enumerate(s):
            if ch in DIGITS:
                self.blit(DIGITS[ch], x + i * 4, y)


def png_bytes(spr: Sprite, scale: int = 1, background: tuple[int, int, int] | None = None) -> bytes:
    """スプライトを PNG に。ライブラリなしで、チャンクを struct と zlib で組み立てる。background が無ければ透明。"""
    w, h = spr.width * scale, spr.height * scale
    colors = {(x, y): c for x, y, c in spr.pixels}
    blank = bytes(background) + b"\xff" if background else b"\x00\x00\x00\x00"
    raw = bytearray()
    for y in range(h):
        raw.append(0)                                       # フィルタ 0（そのまま）
        for x in range(w):
            c = colors.get((x // scale, y // scale))
            raw += bytes(c) + b"\xff" if c else blank

    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

    header = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)   # 8 ビット、RGBA
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b"")


@cache
def data_uri(spr: Sprite, scale: int = 1) -> str:
    """ブラウザで <img src=...> に入れる文字列。同じスプライトは一度だけ作る。"""
    return "data:image/png;base64," + base64.b64encode(png_bytes(spr, scale)).decode()


@dataclass
class Pacman:
    """今いるマスと、次のマスへどれだけ進んだか（0.0〜1.0）で位置を持つ。"""

    cell: tuple[int, int]
    facing: Direction = Direction.LEFT
    offset: float = 0.0
    wish: Direction | None = None                   # 押されたキー。次にマスの中心へ着いたときに 1 回だけ試す

    @property
    def at_center(self) -> bool:
        """マスの中心にぴたりといるか。曲がれるのはこのときだけ。"""
        return self.offset == 0.0

    @property
    def pos(self) -> tuple[float, float]:
        """描画用の連続した座標。マス単位。"""
        x, y = self.cell
        return x + self.facing.dx * self.offset, y + self.facing.dy * self.offset

    def press(self, maze: Maze, d: Direction) -> None:
        """キーを受け取る。逆向きだけはその場で振り向ける（本家と同じ）。"""
        self.wish = d                                                           # 曲がれるまで覚えておく
        if d is self.facing.opposite and self.offset > 0.0:
            self.cell = maze.ahead(self.cell, self.facing)                      # 進みかけの「次のマス」から
            self.offset = 1.0 - self.offset                                     # 逆向きに測り直す
            self.facing = d
            self.wish = None

    def step(self, maze: Maze, dt: float, decide: Callable[[], Direction] | None = None) -> None:
        """dt 秒ぶん進む。マスの中心に着くたびに、曲がるか・その先へ入れるかを決める。

        decide があれば中心に着くたびに呼んで向きを決めてもらう（自動プレイ）。1 コマの間に
        いくつも中心を通ることがあるので、外側の輪ではなくここで呼ぶ。
        """
        remaining = SPEED * dt
        while remaining > 1e-9:                                         # 小数の足し算で出る端数は無視する
            if self.at_center:                                          # マスの中心にいる
                if decide:
                    self.wish = decide()
                if self.wish and not maze.wall(maze.ahead(self.cell, self.wish)):
                    self.facing = self.wish
                    self.wish = None                                    # 曲がれたときだけ忘れる。だめなら覚えておく
                if maze.wall(maze.ahead(self.cell, self.facing)):
                    break                                               # 壁を向いている。止まったまま
            move = min(remaining, 1.0 - self.offset)
            self.offset += move
            remaining -= move
            if self.offset > 1.0 - 1e-9:                                # 次のマスに着いた（小数の誤差ぶん余裕を見る）
                self.cell = maze.ahead(self.cell, self.facing)
                self.offset = 0.0


MOUTH = (0, 1, 2, 1)                                # 口の開き方の順番（閉じ → 半開き → 開き → 半開き）


def draw_maze(screen: Screen, maze: Maze, eaten: set[tuple[int, int]], blink: bool) -> None:
    """迷路とエサを描く。壁は「通路に面した辺だけ線を引く」ので、輪郭だけの本家らしい形になる。"""
    for pos in maze:
        x0, y0 = pos[0] * CELL, HUD_H + pos[1] * CELL
        match maze[pos]:
            case "#":
                draw_wall(screen, maze, pos, x0, y0)
            case "-":
                for x in range(CELL):
                    screen.plot(x0 + x, y0 + CELL // 2, DOOR_COLOR)
            case "." if pos not in eaten:
                for dx, dy in ((2, 2), (3, 2), (2, 3), (3, 3)):
                    screen.plot(x0 + dx, y0 + dy, PELLET_COLOR)
            case "o" if pos not in eaten and blink:
                for dx in range(1, 5):
                    for dy in range(1, 5):
                        if (dx, dy) not in ((1, 1), (4, 1), (1, 4), (4, 4)):
                            screen.plot(x0 + dx, y0 + dy, PELLET_COLOR)


def draw_wall(screen: Screen, maze: Maze, pos: tuple[int, int], x0: int, y0: int) -> None:
    """壁 1 マス。通路に面した辺に線を引き、内側の角には点を打って線をつなぐ。"""
    cx, cy = pos
    end = CELL - 1

    def solid(x: int, y: int) -> bool:
        return maze.get((x % maze.width, y), WALL) in (WALL, DOOR)      # 迷路の外も壁とみなす

    if not solid(cx, cy - 1):
        for x in range(CELL):
            screen.plot(x0 + x, y0, WALL_COLOR)
    if not solid(cx, cy + 1):
        for x in range(CELL):
            screen.plot(x0 + x, y0 + end, WALL_COLOR)
    if not solid(cx - 1, cy):
        for y in range(CELL):
            screen.plot(x0, y0 + y, WALL_COLOR)
    if not solid(cx + 1, cy):
        for y in range(CELL):
            screen.plot(x0 + end, y0 + y, WALL_COLOR)
    for sx, sy, px, py in ((-1, -1, 0, 0), (1, -1, end, 0), (-1, 1, 0, end), (1, 1, end, end)):
        if solid(cx + sx, cy) and solid(cx, cy + sy) and not solid(cx + sx, cy + sy):
            screen.plot(x0 + px, y0 + py, WALL_COLOR)                   # 斜めだけが通路 = 内側の角


def draw_pacman(screen: Screen, pac: Pacman, frame: int) -> None:
    """パックマンを連続した位置に描く。トンネルでは反対側にも重ねて、切れずに抜けるように見せる。"""
    fx, fy = pac.pos
    spr = PAC_SPRITES[pac.facing][frame]
    x = fx * CELL + CELL // 2 - spr.width // 2
    y = HUD_H + fy * CELL + CELL // 2 - spr.height // 2
    screen.blit(spr, x, y)
    if x < 0:
        screen.blit(spr, x + WIDTH, y)
    elif x + spr.width > WIDTH:
        screen.blit(spr, x - WIDTH, y)


def draw(screen: Screen, maze: Maze, pac: Pacman, eaten: set[tuple[int, int]], score: int, t: float) -> None:
    """1 コマぶん。得点欄 → 迷路 → パックマンの順に重ねる。"""
    screen.clear()
    draw_maze(screen, maze, eaten, blink=int(t * 5) % 2 == 0)
    draw_pacman(screen, pac, MOUTH[int(t * 12) % 4])
    screen.text(f"{score:06d}", 2, 1)
    screen.text(f"{len(maze.pellets()) - len(eaten):03d}", WIDTH - 14, 1)


def eat(maze: Maze, pac: Pacman, eaten: set[tuple[int, int]]) -> int:
    """今いるマスのエサを食べる。食べた分の点を返す（何も無ければ 0）。"""
    if pac.cell in eaten:
        return 0
    match maze[pac.cell]:
        case ".":
            eaten.add(pac.cell)
            return PELLET_SCORE
        case "o":
            eaten.add(pac.cell)
            return POWER_SCORE
    return 0


def sight(maze: Maze, pac: Pacman, eaten: set[tuple[int, int]]) -> dict[Direction, int]:
    """4 方向それぞれについて、壁までの通路に残っているエサの数。"""
    return {d: sum(p not in eaten and maze[p] in (PELLET, POWER) for p in maze.corridor(pac.cell, d))
            for d in Direction}


@dataclass
class Game:
    """1 回ぶんの遊び。迷路・パックマン・食べたエサ・得点をここにまとめる。"""

    maze_text: InitVar[str] = MAZE_TEXT             # 組み立てにだけ使い、フィールドとしては残さない
    seed: int | None = None
    score: int = 0
    elapsed: float = 0.0
    result: str | None = None                       # None のうちは続行。"clear" / "quit" で終わり

    def __post_init__(self, maze_text: str) -> None:    # InitVar はここに引数として届く
        self.maze = Maze.from_text(maze_text)
        self.pac = Pacman(self.maze.start())
        self.eaten: set[tuple[int, int]] = set()
        self.total = len(self.maze.pellets())
        self.rng = random.Random(self.seed)

    @property
    def remaining(self) -> int:
        return self.total - len(self.eaten)

    def control(self, keys: list[str]) -> None:
        """押されたキーを受ける。"""
        for key in keys:
            if key == "quit":
                self.result = "quit"
            elif key in KEY_TO_DIR:
                self.pac.press(self.maze, KEY_TO_DIR[key])

    def update(self, dt: float, auto: bool = False) -> None:
        """dt 秒ぶん進める。auto なら向きは autopilot が決める。"""
        if self.result:
            return
        self.elapsed += dt
        self.pac.step(self.maze, dt, self.autopilot if auto else None)
        self.score += eat(self.maze, self.pac, self.eaten)
        if self.remaining == 0:
            self.result = "clear"

    def autopilot(self) -> Direction:
        """見える所にエサがあればそちらへ。無ければ幅優先探索で一番近いエサを目指す。"""
        view = sight(self.maze, self.pac, self.eaten)
        open_dirs = [d for d in Direction if not self.maze.wall(self.maze.ahead(self.pac.cell, d))]
        best = max(view.values())
        choices = [d for d in open_dirs if view[d] == best] if best else (self.toward_nearest() or open_dirs)
        if len(choices) > 1 and self.pac.facing.opposite in choices:
            choices.remove(self.pac.facing.opposite)        # 引き返しは行き止まりのときだけ
        return self.rng.choice(choices)

    def toward_nearest(self) -> list[Direction]:
        """一番近いエサへの最初の 1 歩。通路を幅優先で広げ、最初に見つかったエサまでの道の 1 歩目を返す。"""
        first: dict[tuple[int, int], Direction] = {}
        queue: deque[tuple[int, int]] = deque()
        for d in Direction:
            nxt = self.maze.ahead(self.pac.cell, d)
            if not self.maze.wall(nxt) and nxt not in first:
                first[nxt] = d
                queue.append(nxt)
        seen = {self.pac.cell} | set(first)
        while queue:
            pos = queue.popleft()
            if pos not in self.eaten and self.maze[pos] in (PELLET, POWER):
                return [first[pos]]
            for d in Direction:
                nxt = self.maze.ahead(pos, d)
                if not self.maze.wall(nxt) and nxt not in seen:
                    seen.add(nxt)
                    first[nxt] = first[pos]
                    queue.append(nxt)
        return []

    def draw(self, screen: Screen) -> None:
        draw(screen, self.maze, self.pac, self.eaten, self.score, self.elapsed)

    def status(self) -> str:
        return f"{self.score:6d} 点   残り {self.remaining:3d}   {self.elapsed:5.1f} 秒"
# --- ここから下はブラウザ版だけ。CLI 版の play() / read_keys() / Screen.render() にあたる ---

canvas = document.querySelector("#screen")
ctx = canvas.getContext("2d")
ctx.imageSmoothingEnabled = False
image = ctx.createImageData(WIDTH, HEIGHT)                  # 126 × 86 の画素の板。毎コマここへ流し込む
score_label = document.querySelector("#score")
left_label = document.querySelector("#left")
time_label = document.querySelector("#progress")
message = document.querySelector("#message")
start_button = document.querySelector("#start-btn")
auto_button = document.querySelector("#auto-btn")
pad_buttons = document.querySelectorAll(".pad button")


class CanvasScreen(Screen):
    """CLI 版の Screen をそのまま使い、描き終えた画素をまとめて canvas へ送る。

    端末版は Screen.render() で文字にしていた。ここでは同じ pixels を RGBA の並びに直して
    putImageData に 1 回で渡す。Game.draw() の側は端末版と 1 文字も変わらない。
    """

    def flush(self) -> None:
        buf = bytearray(WIDTH * HEIGHT * 4)
        i = 0
        for row in self.pixels:
            for color in row:
                if color is not None:
                    buf[i], buf[i + 1], buf[i + 2] = color
                buf[i + 3] = 255                            # 透明なところは黒
                i += 4
        image.data.assign(bytes(buf))
        ctx.putImageData(image, 0, 0)


screen = CanvasScreen()
game = Game()
auto = False
running = False


def refresh():
    """CLI 版の Game.draw() + Screen.render() にあたる。

    共有部分に module 直下の draw() があるので、ここで draw という名前は使えない
    （Game.draw が呼ぶのはこの module の draw で、上書きすると引数が合わずに落ちる）。
    """
    game.draw(screen)
    screen.flush()
    score_label.textContent = f"{game.score}"
    left_label.textContent = f"{game.remaining}"
    time_label.textContent = f"{game.elapsed:.1f} 秒"
    if game.result is not None:
        message.textContent = RESULT_TEXT[game.result].format(game=game)


async def loop():
    """1/FPS 秒ごとに更新して描く。CLI 版の play() の while と同じ。"""
    global running
    running = True
    last = window.performance.now() / 1000
    while game.result is None:
        now = window.performance.now() / 1000
        dt = min(now - last, 0.1)
        last = now
        game.update(dt, auto)
        refresh()
        await asyncio.sleep(1 / FPS)
    refresh()
    running = False


def start(demo: bool = False):
    global game, auto
    game = Game()
    auto = demo
    message.textContent = "自動プレイ" if demo else ""
    for button in pad_buttons:
        button.disabled = demo
    if not running:
        asyncio.ensure_future(loop())


KEYS = {"ArrowLeft": "left", "a": "left", "ArrowRight": "right", "d": "right",
        "ArrowUp": "up", "w": "up", "ArrowDown": "down", "s": "down"}


@when("keydown", "body")
def on_keydown(event):
    global auto
    key = KEYS.get(event.key)
    if key is None:
        return
    event.preventDefault()
    auto = False                                            # 何か押したら自分で操縦
    game.control([key])


@when("pointerdown", ".pad button")
def on_pad_down(event):
    global auto
    auto = False
    game.control([event.target.getAttribute("data-key")])


@when("click", "#start-btn")
def on_start(event):
    start()


@when("click", "#auto-btn")
def on_auto(event):
    start(demo=True)


# Pyodide の読み込みが終わってから実行される＝ここが準備完了の合図
document.querySelector("#loading").hidden = True
start_button.disabled = False
auto_button.disabled = False
start()
