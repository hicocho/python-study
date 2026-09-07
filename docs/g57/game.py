"""パックマン風（パワーエサとイジケ）ブラウザ版

CLI 版（g57-pacman-power/main.py）と迷路・動き・エサの判定はまったく同じ。
定数と MAZE_TEXT、Maze / Direction、ドット絵と Sprite / Screen / png_bytes()、Walker / Pacman、
Mode と 4 体のおばけ、イジケ・目玉の絵、Popup、draw 一式、eat() / sight()、そして class Game を、
ステップの目印コメント（# ←）を外しただけで 1 文字も変えずに持ってきている。

持ってこなかったのは端末に描く Screen.render() と、それを使う play() / read_keys() /
check_terminal() / main() だけ。出口は canvas。Screen をそのまま使って画素の板を作り、
最後に ImageData へ 1 回で流し込む（塗る点が 2000 を超えるので、1 点ずつ fillRect すると間に合わない）。
"""

import asyncio
import base64
import random
import struct
import zlib
from bisect import bisect_right
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import InitVar, dataclass, field
from enum import Enum, auto
from functools import cache, singledispatchmethod
from itertools import accumulate, batched, count, takewhile
from types import MappingProxyType
from typing import ClassVar, Final, Self, assert_never

from js import window
from pyscript import document, when

WALL = "#"
DOOR = "-"                                          # 巣の扉。パックマンは通れない
PELLET = "."
POWER = "o"
EMPTY = " "
START = "P"                                         # パックマンの出発点（エサは無い）
FPS = 30
SPEED = 6.0                                         # 自機が 1 秒に進むマス数
GHOST_SPEED = 5.4                                   # おばけは少し遅い（自機の 90%）
TUNNEL_SLOW = 0.5                                   # トンネルの中ではおばけがさらに遅くなる
PELLET_SCORE = 10
POWER_SCORE = 50
LIVES = 3
DEATH_PAUSE = 1.2                                   # 捕まってから動き出すまでの秒数
FRIGHT_TIME = 8.0                                   # パワーエサ 1 個でイジケている秒数
FRIGHT_BLINK = 2.0                                  # 残りこの秒数から白く点滅して知らせる
FRIGHT_SPEED = 3.6                                  # イジケているおばけは遅い
EATEN_SPEED = 12.0                                  # 目玉だけになると速く巣へ帰る
GHOST_SCORES: Final = (200, 400, 800, 1600)         # 続けて食べるほど倍々に
POPUP_TIME = 1.0                                    # 点数をその場に出しておく秒数
HOME_SEAT = (10, 6)                                 # 目玉が帰る巣の中
CATCH_RANGE = 0.7                                   # これより近づくと捕まる（マス単位）
DOOR_CELL = (10, 5)                                 # 巣の扉
HOME_EXIT = (10, 4)                                 # 扉のすぐ外。おばけはまずここを目指す
TUNNEL_ROW = 7


type Cell = tuple[int, int]                         # 迷路のマスの位置。この 1 行で全部の注釈が短くなる


RESULT_TEXT = {
    "clear": "クリア！ {game.score} 点、{game.elapsed:.1f} 秒。",
    "over": "ゲームオーバー。{game.score} 点、残り {game.remaining} 個。",
    "quit": "やめました。{game.score} 点、残り {game.remaining} 個。",
}


MAZE_TEXT = """
#####################
#.........#.........#
#o###.###.#.###.###o#
#...................#
#.#####.## ##.#####.#
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
    def __getitem__(self, pos: Cell) -> str:
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

    def wall(self, pos: Cell) -> bool:
        """パックマンが通れないマスか。迷路の外も壁とみなす。"""
        return self.get(pos, WALL) in (WALL, DOOR)  # 外は KeyError → get の既定値 WALL

    def ahead(self, pos: Cell, d: "Direction") -> Cell:
        """pos の d 方向の隣。左右は端で反対側につながる（トンネル）。"""
        x, y = pos
        return (x + d.dx) % self.width, y + d.dy                                # 横だけ剰余で回す

    def corridor(self, pos: Cell, d: "Direction") -> list[Cell]:
        """pos から d の向きに、壁にぶつかるまでのマスを順に。トンネルも通る。"""
        ahead = (self.reach(pos, d, n) for n in count(1))                                # 1 マス先、2 マス先…と無限に作り
        return list(takewhile(lambda p: not self.wall(p), ahead))                        # 壁が出るまでで打ち切る

    def reach(self, pos: Cell, d: "Direction", n: int) -> Cell:
        """pos から d の向きに n マス先。"""
        x, y = pos
        return (x + d.dx * n) % self.width, y + d.dy * n

    def start(self) -> Cell:
        """P の位置。"""
        for pos, ch in self.items():                # items も Mapping が用意したもの
            if ch == START:
                return pos
        raise ValueError("出発点 P がありません")

    def pellets(self) -> dict[Cell, str]:
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
GHOST_COLORS = {"R": (255, 0, 0), "P": (255, 184, 222), "C": (0, 255, 222), "O": (255, 184, 82)}
PALETTE = {"Y": PAC_COLOR, "W": (255, 255, 255), "K": (0, 0, 0), "U": (33, 33, 222),
           "B": (66, 66, 255)} | GHOST_COLORS


def tunnel_cells(maze: Maze) -> frozenset[Cell]:
    """左右の端でつながっている通路のマス。ここではおばけが遅くなる。"""
    cells = set()
    for edge, d in (((0, TUNNEL_ROW), Direction.RIGHT), ((maze.width - 1, TUNNEL_ROW), Direction.LEFT)):
        cells.add(edge)
        cells.update(maze.corridor(edge, d))
    return frozenset(cells)


TUNNEL = tunnel_cells(Maze.from_text(MAZE_TEXT))


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


GHOST_BODY = ("..###..",
              ".#####.",
              "#######",
              "#WW#WW#",
              "#WW#WW#",
              "#######",
              "#.#.#.#")
PUPILS = {                                          # 黒目を置く位置（左目と右目で 2 ドットずつ）
    Direction.LEFT:  ((1, 3), (1, 4), (4, 3), (4, 4)),
    Direction.RIGHT: ((2, 3), (2, 4), (5, 3), (5, 4)),
    Direction.UP:    ((1, 3), (2, 3), (4, 3), (5, 3)),
    Direction.DOWN:  ((1, 4), (2, 4), (4, 4), (5, 4)),
}


def ghost_sprite(label: str, color: str, d: Direction) -> Sprite:
    """おばけ 1 枚。体の色と目の向きだけが違う。名前を分けないと data_uri の @cache がぶつかる。"""
    rows = [list(row.replace("#", color)) for row in GHOST_BODY]
    for x, y in PUPILS[d]:
        rows[y][x] = "U"
    return Sprite(f"ghost-{label}-{d.name.lower()}", tuple("".join(row) for row in rows))


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
class Walker:
    """迷路の通路を走るもの。今いるマスと、次のマスへの進み具合（0.0〜1.0）で位置を持つ。

    パックマンもおばけもこれを継承する。違うのは「速さ」と「扉を通れるか」だけ。
    """

    cell: Cell
    facing: Direction = Direction.LEFT
    offset: float = 0.0
    wish: Direction | None = None

    @property
    def at_center(self) -> bool:
        """マスの中心にぴたりといるか。曲がれるのはこのときだけ。"""
        return self.offset == 0.0

    @property
    def pos(self) -> tuple[float, float]:
        """描画用の連続した座標。マス単位。"""
        x, y = self.cell
        return x + self.facing.dx * self.offset, y + self.facing.dy * self.offset

    def blocked(self, maze: Maze, pos: Cell) -> bool:
        """そのマスへ入れないか。パックマンは扉も壁。"""
        return maze.wall(pos)

    def speed(self, maze: Maze) -> float:
        """今いる場所での速さ（マス/秒）。"""
        return SPEED

    def step(self, maze: Maze, dt: float, decide: Callable[[], Direction] | None = None) -> None:
        """dt 秒ぶん進む。マスの中心に着くたびに、曲がるか・その先へ入れるかを決める。

        decide があれば中心に着くたびに呼んで向きを決めてもらう。1 コマの間に
        いくつも中心を通ることがあるので、外側の輪ではなくここで呼ぶ。
        """
        remaining = self.speed(maze) * dt
        while remaining > 1e-9:                                         # 小数の足し算で出る端数は無視する
            if self.at_center:                                          # マスの中心にいる
                if decide:
                    self.wish = decide()
                if self.wish and not self.blocked(maze, maze.ahead(self.cell, self.wish)):
                    self.facing = self.wish
                    self.wish = None                                    # 曲がれたときだけ忘れる。だめなら覚えておく
                if self.blocked(maze, maze.ahead(self.cell, self.facing)):
                    break                                               # 壁を向いている。止まったまま
            move = min(remaining, 1.0 - self.offset)
            self.offset += move
            remaining -= move
            if self.offset > 1.0 - 1e-9:                                # 次のマスに着いた（小数の誤差ぶん余裕を見る）
                self.cell = maze.ahead(self.cell, self.facing)
                self.offset = 0.0

    def reverse(self, maze: Maze) -> None:
        """その場で向きだけ逆にする。画面上の位置は 1 ドットも動かない。"""
        if self.offset > 0.0:
            self.cell = maze.ahead(self.cell, self.facing)              # 進みかけの「次のマス」から
            self.offset = 1.0 - self.offset                             # 逆向きに測り直す
        self.facing = self.facing.opposite
        self.wish = None


@dataclass
class Pacman(Walker):
    """自機。押されたキーは曲がれるまで覚えておく（先行入力）。"""

    def press(self, maze: Maze, d: Direction) -> None:
        """キーを受け取る。逆向きだけはその場で振り向ける（本家と同じ）。"""
        if d is self.facing.opposite:
            self.reverse(maze)
        else:
            self.wish = d


class Mode(Enum):
    """おばけの構え。"""

    HOME = auto()                                   # 巣の中で順番待ち
    LEAVING = auto()                                # 巣から出ようとしている
    SCATTER = auto()                                # 自分の隅へ散らばる
    CHASE = auto()                                  # 自機を追う
    FRIGHTENED = auto()                             # パワーエサを食べられて逃げている
    EATEN = auto()                                  # 目玉だけになって巣へ帰る


SCHEDULE = ((Mode.SCATTER, 7.0), (Mode.CHASE, 20.0), (Mode.SCATTER, 7.0), (Mode.CHASE, 20.0),
            (Mode.SCATTER, 5.0), (Mode.CHASE, 20.0), (Mode.SCATTER, 5.0))
PHASE_ENDS = list(accumulate(seconds for _, seconds in SCHEDULE))       # 切り替わる時刻


def phase_at(t: float) -> Mode:
    """t 秒の時点は散らばりか追いかけか。"""
    i = bisect_right(PHASE_ENDS, t)
    return SCHEDULE[i][0] if i < len(SCHEDULE) else Mode.CHASE


def dist2(maze: Maze, a: Cell, b: Cell) -> int:
    """2 マスの距離の 2 乗。左右はトンネルでつながっているので近い方をとる。"""
    dx = abs(a[0] - b[0])
    dx = min(dx, maze.width - dx)
    dy = a[1] - b[1]
    return dx * dx + dy * dy


CHOICE_ORDER = (Direction.UP, Direction.LEFT, Direction.DOWN, Direction.RIGHT)   # 同点のときの優先順


@dataclass
class Ghost(Walker):
    """おばけ 1 体。目標のマスを決めるところ（target）だけが 4 体で違う。"""

    mode: Mode = Mode.HOME
    wait: float = 0.0                               # 巣を出るまでの残り秒

    kinds: ClassVar[list[type["Ghost"]]] = []       # 定義された順に並ぶおばけの一覧
    label: ClassVar[str] = "?"
    color: ClassVar[str] = "R"                      # パレットの文字
    corner: ClassVar[Cell] = (1, 1)      # 散らばるときの目標
    seat: ClassVar[Cell] = (10, 6)       # 巣の中の待ち位置
    release: ClassVar[float] = 0.0                  # 何秒待ってから出るか

    def __init_subclass__(cls, **kwargs) -> None:
        """Ghost を継承したクラスは、定義しただけで kinds に載る。"""
        super().__init_subclass__(**kwargs)
        Ghost.kinds.append(cls)

    @classmethod
    def spawn(cls) -> "Ghost":
        """待ち位置に置いた 1 体を作る。巣の外から始まるのは待ち時間 0 のもの。"""
        return cls(cell=cls.seat, facing=Direction.LEFT,
                   mode=Mode.LEAVING if cls.release == 0 else Mode.HOME, wait=cls.release)

    def blocked(self, maze: Maze, pos: Cell) -> bool:
        """扉は巣を出るときだけ通れる。壁はいつでも通れない。"""
        if maze.get(pos, WALL) == DOOR:
            return self.mode not in (Mode.HOME, Mode.LEAVING, Mode.EATEN)
        return maze.wall(pos)

    def speed(self, maze: Maze) -> float:
        """構えごとの速さ。イジケていると遅く、目玉だけになると速い。"""
        match self.mode:
            case Mode.EATEN:
                return EATEN_SPEED
            case Mode.FRIGHTENED:
                return FRIGHT_SPEED
            case _:
                return GHOST_SPEED * (TUNNEL_SLOW if self.cell in TUNNEL else 1.0)

    def aim(self, game: "Game") -> Cell:
        """今の構えでの目標のマス。"""
        match self.mode:
            case Mode.HOME | Mode.LEAVING:
                return HOME_EXIT                    # 巣の外へ
            case Mode.SCATTER:
                return self.corner
            case Mode.CHASE:
                return self.target(game)
            case Mode.FRIGHTENED:
                return self.corner                  # 使わない（イジケているときの行き先はでたらめ）
            case Mode.EATEN:
                return HOME_SEAT                    # 巣の中へ帰る
            case _:
                assert_never(self.mode)             # Mode を増やして書き忘れたら型検査が教えてくれる

    def target(self, game: "Game") -> Cell:
        """追いかけるときの目標。おばけごとに違う。"""
        return game.pac.cell

    def choose(self, game: "Game") -> Direction:
        """交差点での向き。来た道以外で、目標に一番近くなるマスへ。同点なら 上・左・下・右 の順。"""
        if self.mode is Mode.LEAVING and self.cell == HOME_EXIT:
            self.mode = game.phase                  # 外に出た。時間割に合流する
        elif self.mode is Mode.EATEN and self.cell == HOME_SEAT:
            self.mode = Mode.LEAVING                # 巣に着いた。もう一度出直す
        goal = self.aim(game)
        back = self.facing.opposite
        options = [d for d in CHOICE_ORDER
                   if d is not back and not self.blocked(game.maze, game.maze.ahead(self.cell, d))]
        if not options:
            return back                             # 行き止まり。おばけが引き返すのはここだけ
        if self.mode is Mode.FRIGHTENED:
            return game.rng.choice(options)         # イジケているときは行き当たりばったり
        return min(options, key=lambda d: dist2(game.maze, game.maze.ahead(self.cell, d), goal))

    def update(self, game: "Game", dt: float) -> None:
        """1 コマぶん動かす。巣の中は数えるだけ、外に出たら時間割どおりの構えで走る。"""
        if self.mode is Mode.HOME:
            self.wait -= dt
            if self.wait <= 0:
                self.mode = Mode.LEAVING
            return
        self.step(game.maze, dt, lambda: self.choose(game))


class Blinky(Ghost):
    """赤。自機のいるマスをまっすぐ狙う。最初から巣の外にいる。"""

    label: ClassVar[str] = "BLINKY"
    color: ClassVar[str] = "R"
    corner: ClassVar[Cell] = (19, 1)
    seat: ClassVar[Cell] = HOME_EXIT
    release: ClassVar[float] = 0.0


class Pinky(Ghost):
    """桃。自機の 4 マス先へ回り込む。"""

    label: ClassVar[str] = "PINKY"
    color: ClassVar[str] = "P"
    corner: ClassVar[Cell] = (1, 1)
    seat: ClassVar[Cell] = (10, 6)
    release: ClassVar[float] = 2.0

    def target(self, game: "Game") -> Cell:
        return game.maze.reach(game.pac.cell, game.pac.facing, 4)


class Inky(Ghost):
    """水色。自機の 2 マス先を、ブリンキーから見て 2 倍に伸ばした所。2 体の位置で目標が動く。"""

    label: ClassVar[str] = "INKY"
    color: ClassVar[str] = "C"
    corner: ClassVar[Cell] = (19, 11)
    seat: ClassVar[Cell] = (9, 6)
    release: ClassVar[float] = 5.0

    def target(self, game: "Game") -> Cell:
        ax, ay = game.maze.reach(game.pac.cell, game.pac.facing, 2)
        bx, by = game.ghosts[0].cell                # ブリンキー（kinds の 1 番目）
        return (2 * ax - bx) % game.maze.width, 2 * ay - by


class Clyde(Ghost):
    """橙。遠いうちは自機を狙い、8 マスより近づくと自分の隅へ帰る。"""

    label: ClassVar[str] = "CLYDE"
    color: ClassVar[str] = "O"
    corner: ClassVar[Cell] = (1, 11)
    seat: ClassVar[Cell] = (11, 6)
    release: ClassVar[float] = 8.0

    def target(self, game: "Game") -> Cell:
        return game.pac.cell if dist2(game.maze, self.cell, game.pac.cell) > 8 * 8 else self.corner


GHOST_SPRITES = {(kind.label, d): ghost_sprite(kind.label, kind.color, d)
                 for kind in Ghost.kinds for d in Direction}


FRIGHT_BODY = ("..###..",
               ".#####.",
               "#######",
               "#W###W#",
               "#######",
               "#W#W#W#",
               "#.#.#.#")
EYES_BODY = (".......",
             ".......",
             ".......",
             ".WW.WW.",
             ".WW.WW.",
             ".......",
             ".......")


def fright_sprite(name: str, body: str, mark: str) -> Sprite:
    """イジケたおばけ。青い体に白い目と口、時間切れが近づくと白と赤に変わる。

    replace を 2 回つなぐと、1 回目で作った文字を 2 回目が拾ってしまう
    （# → W にしたあと W → R にすると体まで赤くなった）。translate なら 1 度に置き換わる。
    """
    table = str.maketrans({"#": body, "W": mark})
    return Sprite(name, tuple(row.translate(table) for row in FRIGHT_BODY))


def eyes_sprite(d: Direction) -> Sprite:
    """食べられたおばけ。体は消えて目玉だけが巣へ帰る。"""
    rows = [list(row) for row in EYES_BODY]
    for x, y in PUPILS[d]:
        rows[y][x] = "U"
    return Sprite(f"eyes-{d.name.lower()}", tuple("".join(row) for row in rows))


FRIGHT_SPRITES = (fright_sprite("fright-blue", "B", "W"), fright_sprite("fright-white", "W", "R"))
EYES_SPRITES = {d: eyes_sprite(d) for d in Direction}


def ghost_face(ghost: "Ghost", blink: bool) -> Sprite:
    """今の構えでの見た目。"""
    match ghost.mode:
        case Mode.EATEN:
            return EYES_SPRITES[ghost.facing]
        case Mode.FRIGHTENED:
            return FRIGHT_SPRITES[1 if blink else 0]
        case _:
            return GHOST_SPRITES[ghost.label, ghost.facing]


@dataclass
class Popup:
    """食べた点数を、その場に少しの間だけ出す。"""

    text: str
    pos: tuple[float, float]
    life: float = POPUP_TIME


MOUTH = (0, 1, 2, 1)                                # 口の開き方の順番（閉じ → 半開き → 開き → 半開き）


def draw_maze(screen: Screen, maze: Maze, eaten: set[Cell], blink: bool) -> None:
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


def draw_wall(screen: Screen, maze: Maze, pos: Cell, x0: int, y0: int) -> None:
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


def blit_wrapped(screen: Screen, spr: Sprite, fx: float, fy: float) -> None:
    """マス単位の位置に絵の中心を合わせて置く。画面からはみ出したら反対側にも重ねる。"""
    x = fx * CELL + CELL // 2 - spr.width // 2
    y = HUD_H + fy * CELL + CELL // 2 - spr.height // 2
    screen.blit(spr, x, y)
    if x < 0:
        screen.blit(spr, x + WIDTH, y)
    elif x + spr.width > WIDTH:
        screen.blit(spr, x - WIDTH, y)


def draw(screen: Screen, game: "Game") -> None:
    """1 コマぶん。得点欄 → 迷路 → おばけ → 自機 → 点数の順に重ねる。"""
    screen.clear()
    draw_maze(screen, game.maze, game.eaten, blink=int(game.elapsed * 5) % 2 == 0)
    actors = [*game.ghosts, *([] if game.dying > 0 else [game.pac]), *game.popups]
    for actor in actors:
        game.paint(actor, screen)                   # 型ごとに描き分けるのは Game.paint
    screen.text(f"{game.score:06d}", 2, 1)
    screen.text(f"{game.remaining:03d}", WIDTH - 14, 1)
    for i in range(game.lives - 1):                 # 残りの機（今使っているぶんは数えない）
        screen.blit(PAC_SPRITES[Direction.LEFT][2], 48 + i * 9, 1)


def eat(maze: Maze, pac: Pacman, eaten: set[Cell]) -> str | None:
    """今いるマスのエサを食べる。食べたものの文字を返す（何も無ければ None）。"""
    if pac.cell in eaten or maze[pac.cell] not in (PELLET, POWER):
        return None
    eaten.add(pac.cell)
    return maze[pac.cell]


def sight(maze: Maze, pac: Pacman, eaten: set[Cell]) -> dict[Direction, int]:
    """4 方向それぞれについて、壁までの通路に残っているエサの数。"""
    return {d: sum(p not in eaten and maze[p] in (PELLET, POWER) for p in maze.corridor(pac.cell, d))
            for d in Direction}


@dataclass
class Game:
    """1 回ぶんの遊び。迷路・自機・おばけ・食べたエサ・得点をここにまとめる。"""

    maze_text: InitVar[str] = MAZE_TEXT             # 組み立てにだけ使い、フィールドとしては残さない
    seed: int | None = None
    score: int = 0
    elapsed: float = 0.0
    lives: int = LIVES
    skill: int = 2                                  # 自動プレイの腕前。おばけから何歩まで近づかないか
    result: str | None = None                       # None のうちは続行。"clear" / "over" / "quit" で終わり

    def __post_init__(self, maze_text: str) -> None:    # InitVar はここに引数として届く
        self.maze = Maze.from_text(maze_text)
        self.eaten: set[Cell] = set()
        self.total = len(self.maze.pellets())
        self.rng = random.Random(self.seed)
        self.dying = 0.0                            # 捕まってから動き出すまでの残り秒
        self.fright = 0.0                           # イジケの残り秒
        self.chain = 0                              # このパワーエサで続けて食べた数
        self.popups: list[Popup] = []
        self.restart()

    def restart(self) -> None:
        """自機とおばけを出発点に戻す。エサと得点はそのまま。"""
        self.pac = Pacman(self.maze.start())
        self.ghosts = [kind.spawn() for kind in Ghost.kinds]
        self.round_time = 0.0                       # このやり直しが始まってからの秒数（時間割に使う）
        self.phase = phase_at(0.0)

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
        if self.dying > 0:                          # 捕まった直後はみんな止まる
            self.dying -= dt
            if self.dying <= 0:
                self.result = "over" if self.lives == 0 else None
                if self.lives:
                    self.restart()
            return
        self.round_time += dt
        self.switch_phase(phase_at(self.round_time))
        self.cool_down(dt)
        self.fade_popups(dt)
        self.pac.step(self.maze, dt, self.autopilot if auto else None)
        match eat(self.maze, self.pac, self.eaten):
            case ".":
                self.score += PELLET_SCORE
            case "o":
                self.score += POWER_SCORE
                self.frighten()
        for ghost in self.ghosts:
            ghost.update(self, dt)
        self.touch()
        if self.remaining == 0:
            self.result = "clear"

    def switch_phase(self, phase: Mode) -> None:
        """時間割が変わったら、外に出ているおばけの構えを変えて反転させる。"""
        if phase is self.phase:
            return
        self.phase = phase
        for ghost in self.ghosts:
            if ghost.mode in (Mode.SCATTER, Mode.CHASE):
                ghost.mode = phase
                ghost.reverse(self.maze)            # 切り替えのたびに向きを変えるのが本家

    def fade_popups(self, dt: float) -> None:
        """点数の表示を消していく。残り時間が尽きたものを外す。"""
        for popup in self.popups:
            popup.life -= dt
        self.popups = [p for p in self.popups if p.life > 0]

    def frighten(self) -> None:
        """パワーエサを食べた。外にいるおばけをイジケさせて反転させる。"""
        self.fright = FRIGHT_TIME
        self.chain = 0                              # 連続で食べた数。1 匹目から数え直す
        for ghost in self.ghosts:
            if ghost.mode in (Mode.SCATTER, Mode.CHASE):
                ghost.mode = Mode.FRIGHTENED
                ghost.reverse(self.maze)

    def cool_down(self, dt: float) -> None:
        """イジケの残り時間を減らす。切れたら時間割の構えに戻す。"""
        if self.fright <= 0:
            return
        self.fright -= dt
        if self.fright <= 0:
            for ghost in self.ghosts:
                if ghost.mode is Mode.FRIGHTENED:
                    ghost.mode = self.phase

    def overlapping(self) -> list["Ghost"]:
        """自機と重なっているおばけ。連続した座標で見る（マスだけだとすれ違いを取りこぼす）。"""
        px, py = self.pac.pos
        touching = []
        for ghost in self.ghosts:
            if ghost.mode is Mode.HOME:
                continue
            gx, gy = ghost.pos
            dx = abs(px - gx)
            dx = min(dx, self.maze.width - dx)      # トンネルをまたぐとき
            if dx * dx + (py - gy) ** 2 < CATCH_RANGE * CATCH_RANGE:
                touching.append(ghost)
        return touching

    def touch(self) -> None:
        """重なったおばけの始末。イジケていれば食べ、そうでなければ捕まる。"""
        for ghost in self.overlapping():
            if ghost.mode is Mode.FRIGHTENED:
                gain = GHOST_SCORES[min(self.chain, len(GHOST_SCORES) - 1)]
                self.score += gain
                self.chain += 1                     # 同じパワーエサの間は倍々に増える
                ghost.mode = Mode.EATEN
                self.popups.append(Popup(str(gain), ghost.pos))
            elif ghost.mode is not Mode.EATEN:
                self.lives -= 1
                self.dying = DEATH_PAUSE
                return

    def spread(self, sources: list[Cell]) -> dict[Cell, int]:
        """出発点をいくつも同時に置いた幅優先。どのマスが「一番近い出発点」から何歩か。"""
        far: dict[Cell, int] = {}
        queue: deque[Cell] = deque()
        for cell in sources:
            if cell not in far:
                far[cell] = 0
                queue.append(cell)
        while queue:
            pos = queue.popleft()
            for d in Direction:
                nxt = self.maze.ahead(pos, d)
                if not self.maze.wall(nxt) and nxt not in far:
                    far[nxt] = far[pos] + 1
                    queue.append(nxt)
        return far

    def autopilot(self) -> Direction:
        """怖いおばけから skill 歩より近い道を避け、イジケているおばけは追う。"""
        maze = self.maze
        open_dirs = [d for d in Direction if not self.pac.blocked(maze, maze.ahead(self.pac.cell, d))]
        far = self.spread([g.cell for g in self.ghosts if g.mode in (Mode.SCATTER, Mode.CHASE, Mode.LEAVING)])
        reach = {d: far.get(maze.ahead(self.pac.cell, d), 99) for d in open_dirs}
        dirs = [d for d in open_dirs if reach[d] > self.skill]
        if not dirs:                                # 逃げ場がない。一番遠ざかる道へ
            best_far = max(reach.values())
            dirs = [d for d in open_dirs if reach[d] == best_far]
        prey = self.spread([g.cell for g in self.ghosts if g.mode is Mode.FRIGHTENED])
        if prey and self.fright > FRIGHT_BLINK:     # 追いかける値打ちがあるうちは獲物へ
            near = min(prey.get(maze.ahead(self.pac.cell, d), 99) for d in dirs)
            if near < 8:
                return self.rng.choice([d for d in dirs if prey.get(maze.ahead(self.pac.cell, d), 99) == near])
        view = sight(maze, self.pac, self.eaten)
        best = max((view[d] for d in dirs), default=0)
        if best:
            choices = [d for d in dirs if view[d] == best]
        else:
            choices = [d for d in self.toward_nearest() if d in dirs] or dirs
        if len(choices) > 1 and self.pac.facing.opposite in choices:
            choices.remove(self.pac.facing.opposite)        # 引き返しは行き止まりのときだけ
        return self.rng.choice(choices)

    def toward_nearest(self) -> list[Direction]:
        """一番近いエサへの最初の 1 歩。通路を幅優先で広げ、最初に見つかったエサまでの道の 1 歩目を返す。"""
        first: dict[Cell, Direction] = {}
        queue: deque[Cell] = deque()
        for d in Direction:
            nxt = self.maze.ahead(self.pac.cell, d)
            if not self.pac.blocked(self.maze, nxt) and nxt not in first:
                first[nxt] = d
                queue.append(nxt)
        seen = {self.pac.cell} | set(first)
        while queue:
            pos = queue.popleft()
            if pos not in self.eaten and self.maze[pos] in (PELLET, POWER):
                return [first[pos]]
            for d in Direction:
                nxt = self.maze.ahead(pos, d)
                if not self.pac.blocked(self.maze, nxt) and nxt not in seen:
                    seen.add(nxt)
                    first[nxt] = first[pos]
                    queue.append(nxt)
        return []

    @singledispatchmethod
    def paint(self, actor, screen: Screen) -> None:
        """描くものの型ごとに分ける。register した型に合う 1 つが選ばれる。"""
        raise TypeError(f"描き方を知らない: {actor!r}")

    @paint.register
    def _(self, actor: Pacman, screen: Screen) -> None:
        blit_wrapped(screen, PAC_SPRITES[actor.facing][MOUTH[int(self.elapsed * 12) % 4]], *actor.pos)

    @paint.register
    def _(self, actor: Ghost, screen: Screen) -> None:
        blink = 0 < self.fright <= FRIGHT_BLINK and int(self.elapsed * 6) % 2 == 0
        blit_wrapped(screen, ghost_face(actor, blink), *actor.pos)

    @paint.register
    def _(self, actor: Popup, screen: Screen) -> None:
        x = actor.pos[0] * CELL + CELL // 2 - len(actor.text) * 2
        screen.text(actor.text, round(x), round(HUD_H + (actor.pos[1] - 0.6) * CELL))

    def draw(self, screen: Screen) -> None:
        draw(screen, self)

    def status(self) -> str:
        構え = "イジケ" if self.fright > 0 else ("散らばり" if self.phase is Mode.SCATTER else "追いかけ")
        return (f"{self.score:6d} 点   残り {self.remaining:3d}   機 {self.lives}   "
                f"{構え}   {self.elapsed:5.1f} 秒")
# --- ここから下はブラウザ版だけ。CLI 版の play() / read_keys() / Screen.render() にあたる ---

canvas = document.querySelector("#screen")
ctx = canvas.getContext("2d")
ctx.imageSmoothingEnabled = False
image = ctx.createImageData(WIDTH, HEIGHT)                  # 126 × 86 の画素の板。毎コマここへ流し込む
score_label = document.querySelector("#score")
left_label = document.querySelector("#left")
lives_label = document.querySelector("#lives")
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
    lives_label.textContent = f"{game.lives}"
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
