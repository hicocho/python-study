"""倉庫のロボット — 完成: 自作の言葉で荷物を運ぶ。字句解析・命令の組み立て・1 コマずつの実行。"""

import argparse
import os
import re
import select
import shutil
import sys
import termios
import time
import tty
from dataclasses import dataclass, field
from typing import NamedTuple

# タプルでまとめて代入すると、ブラウザ版へ切り出す道具（ast で名前を探す）が
# 見つけられない。共有に出す定数は 1 行に 1 つ。
CELL = 10                                           # 1 マスは 10 × 10 ドット
COLS = 12                                           # 倉庫の広さ（マス）
ROWS = 8
WIDTH = COLS * CELL
HEIGHT = ROWS * CELL

FLOOR = (38, 40, 50)
GRID = (52, 55, 68)
WALL = (128, 96, 72)
WALL_TOP = (162, 124, 94)
CRATE = (196, 146, 86)
CRATE_EDGE = (232, 186, 118)
DONE = (110, 178, 132)                              # 棚に載った荷物
DONE_EDGE = (168, 226, 186)
SHELF = (94, 150, 120)
ROBOT = (150, 190, 240)
ROBOT_EYE = (30, 34, 44)
HELD = (240, 208, 140)

# 向きは 0=右 1=下 2=左 3=上。画面の下が y の増える向きなので、この順に右回り。
WAYS = ((1, 0), (0, 1), (-1, 0), (0, -1))
FACING = ("→", "↓", "←", "↑")


class Token(NamedTuple):
    """語 1 つ。**どの行のどの桁にあったか**まで覚えておく。

    これがあるから、あとで「3 行目の 6 文字目が読めません」と言える。
    位置を捨ててしまうと、間違いの場所を指せなくなる。
    """

    kind: str
    text: str
    line: int
    col: int


# 語の種類。上から順に試され、最初に当たったものが採られる。
# **最後の bad は「ほかのどれでもない 1 文字」**。これを置いておくと、
# 読めない文字が黙って消えることがなくなる（必ずどれかの語になる）。
WORDS = re.compile(r"""
      (?P<space>[ \t]+)
    | (?P<comment>\#[^\n]*)
    | (?P<newline>\n)
    | (?P<number>\d+)
    | (?P<name>[A-Za-z_][A-Za-z_0-9]*)
    | (?P<bad>.)
""", re.VERBOSE)

SKIP = {"space", "comment"}                         # 語には切るが、あとの処理には渡さないもの


def scan(source: str) -> list[Token]:
    """文字の列を語の列にする（字句解析）。

    re.finditer は「当たったところ」を順に返す。名前付きの枠（?P<name>...）を
    並べておくと、m.lastgroup でどの枠に当たったかが分かる。
    行と桁は、改行を見つけるたびに数え直す。
    """
    tokens = []
    line, start = 1, 0                              # start はこの行が始まる位置
    for m in WORDS.finditer(source):
        kind = m.lastgroup
        if kind in SKIP:
            continue
        token = Token(kind, m.group(), line, m.start() - start + 1)
        tokens.append(token)
        if kind == "newline":
            line += 1
            start = m.end()
    return tokens


# 倉庫の地図。# 壁 / . 床 / @ ロボットの位置 / o 荷物 / = 棚（荷物を置く所）
MAP = """\
############
#@.........#
#....####..#
#..o.......#
#....####..#
#........=.#
#..........#
############"""


@dataclass
class Warehouse:
    """倉庫 1 つ。地図の文字から、壁・荷物・棚・ロボットの位置を作る。"""

    walls: set[tuple[int, int]] = field(default_factory=set)
    shelves: set[tuple[int, int]] = field(default_factory=set)
    crates: set[tuple[int, int]] = field(default_factory=set)
    start: tuple[int, int] = (1, 1)
    at: tuple[int, int] = (1, 1)
    facing: int = 0
    holding: bool = False

    @classmethod
    def read(cls, text: str) -> "Warehouse":
        """地図の文字列から倉庫を作る。"""
        world = cls()
        for y, row in enumerate(text.splitlines()):
            for x, mark in enumerate(row):
                match mark:
                    case "#":
                        world.walls.add((x, y))
                    case "o":
                        world.crates.add((x, y))
                    case "=":
                        world.shelves.add((x, y))
                    case "@":
                        world.start = world.at = (x, y)
        return world

    def ahead(self) -> tuple[int, int]:
        """今向いている先の 1 マス。"""
        dx, dy = WAYS[self.facing]
        return self.at[0] + dx, self.at[1] + dy

    def blocked(self, spot: tuple[int, int]) -> bool:
        """そこへ入れないか。壁と、置いてある荷物は通れない。"""
        return spot in self.walls or spot in self.crates

    def forward(self) -> bool:
        """1 マス進む。進めたら True。"""
        spot = self.ahead()
        if self.blocked(spot):
            return False
        self.at = spot
        return True

    def turn(self, way: int) -> None:
        """右へ +1、左へ −1。4 で割った余りにするので、はみ出さない。"""
        self.facing = (self.facing + way) % 4

    def pick(self) -> str:
        """目の前の荷物を持つ。手はひとつしかない。"""
        if self.holding:
            return "もう持っている"
        spot = self.ahead()
        if spot not in self.crates:
            return "目の前に荷物がない"
        self.crates.discard(spot)
        self.holding = True
        return "持ち上げた"

    def drop(self) -> str:
        """目の前へ置く。棚の上なら、そこで運び終わり。"""
        if not self.holding:
            return "何も持っていない"
        spot = self.ahead()
        if self.blocked(spot):
            return "目の前が塞がっている"
        self.crates.add(spot)
        self.holding = False
        return "棚に置いた" if spot in self.shelves else "置いた"

    @property
    def done(self) -> bool:
        """全部の棚に荷物が載ったか。集合の包含で 1 行。"""
        return self.shelves <= self.crates


# 命令の表。名前 → 数を取るかどうか。ここ 1 か所で「言葉」が決まる。
ORDERS = {"move": True, "left": False, "right": False,
          "pick": False, "drop": False, "wait": True}


class ProgramError(Exception):
    """書き間違い。**どの語が悪かったか**を覚えていて、そのまま画面に出せる。

    Python 自身の SyntaxError も、出しているのは同じ 3 つ——行の中身、
    どこかを指す ^、そして説明。位置を持った Token を作っておいたのは、
    このためだった。
    """

    def __init__(self, message: str, token: Token):
        super().__init__(message)
        self.token = token

    def report(self, source: str) -> list[str]:     # ←
        """3 行の報告を組み立てる。行の中身・^・説明。"""
        rows = source.splitlines()
        text = rows[self.token.line - 1] if self.token.line <= len(rows) else ""
        width = max(len(self.token.text), 1) if self.token.kind != "newline" else 1
        return [f"{self.token.line} 行目 {self.token.col} 文字目: {self.args[0]}",
                f"  {text}",
                "  " + " " * (self.token.col - 1) + "^" * width]


@dataclass(frozen=True)
class Order:
    """命令 1 つ。名前と回数、そして書いてあった場所。"""

    name: str
    count: int
    line: int
    col: int


def build(tokens: list[Token]) -> list[Order]:
    """語の列を命令の列にする。1 行に 1 命令。

    行ごとに区切るので、改行に出会ったところで 1 つぶんを組み立てる。
    """
    program, row = [], []
    for token in tokens:
        if token.kind == "newline":
            if row:
                program.append(make_order(row))
            row = []
        else:
            row.append(token)
    if row:                                         # 最後の行に改行が無いこともある
        program.append(make_order(row))
    return program


def make_order(row: list[Token]) -> Order:
    """1 行ぶんの語から命令を 1 つ。おかしければ ProgramError を投げる。

    見るのは 5 つ。読めない文字・命令でない先頭・知らない命令・
    数の要る要らない・行の余り。**どれも「どの語が悪いか」を渡して投げる。**
    """
    for token in row:
        if token.kind == "bad":
            raise ProgramError(f"読めない文字です（{token.text!r}）", token)
    head, rest = row[0], row[1:]
    if head.kind != "name":
        raise ProgramError("行のはじめは命令の名前です", head)
    if head.text not in ORDERS:
        near = "・".join(ORDERS)
        raise ProgramError(f"{head.text} という命令はありません（使えるのは {near}）", head)
    if ORDERS[head.text]:
        if not rest or rest[0].kind != "number":
            raise ProgramError(f"{head.text} には回数が要ります（例: {head.text} 3）", head)
        count = int(rest[0].text)
        if count == 0:
            raise ProgramError("0 回では何も起きません", rest[0])
        rest = rest[1:]
    else:
        count = 1
        if rest and rest[0].kind == "number":
            raise ProgramError(f"{head.text} に回数は付けられません", rest[0])
    if rest:
        raise ProgramError("この行には余分な語があります", rest[0])
    return Order(head.text, count, head.line, head.col)


class Beat(NamedTuple):
    """実行の 1 コマ。**どの行を実行したか**と、そのとき起きたこと。

    ジェネレータでこれを返すので、呼ぶ側は 1 コマずつ受け取って、
    その行を光らせたり、途中で止めたりできる。
    """

    line: int
    note: str


def run(world: Warehouse, program: list[Order]):
    """プログラムを 1 コマずつ実行する。**ジェネレータなので途中で止められる。**

    move 3 は「1 マス進む」を 3 コマに分ける。まとめて動かすと、
    途中で壁にぶつかった様子が見えない。
    """
    for order in program:
        for _ in range(max(order.count, 1)):
            yield Beat(order.line, act(world, order.name))


def act(world: Warehouse, name: str) -> str:
    """命令を 1 回ぶん実行して、起きたことを短く返す。"""
    match name:
        case "move":
            return "進んだ" if world.forward() else "ぶつかった"
        case "left":
            world.turn(-1)
            return "左を向いた"
        case "right":
            world.turn(1)
            return "右を向いた"
        case "pick":
            return world.pick()
        case "drop":
            return world.drop()
        case _:
            return "待った"


@dataclass(frozen=True)
class Stage:                                        # ←
    """面 1 つ。地図と、お手本のプログラム。"""

    name: str
    ground: str
    example: str


STAGES = (                                          # ←
    Stage("はこびだし", """\
############
#@.........#
#....####..#
#..o.......#
#....####..#
#........=.#
#..........#
############""", """\
# 荷物を棚まで運ぶ
right
move 2
left
move 1
pick
move 8
right
move 2
right
drop
"""),
    Stage("ふたつ", """\
############
#@.........#
#....##....#
#..o....o..#
#....##....#
#.=......=.#
#..........#
############""", """\
# 左の荷物を左の棚へ
right
move 2
left
move 1
pick
right
move 1
drop
# 右の荷物を右の棚へ
right
right
move 1
right
move 5
pick
move 2
right
move 1
drop
"""),
    Stage("ながいみち", """\
############
#@.........#
#########.##
#....o.....#
#.##########
#.........=#
#..........#
############""", """\
# 遠回りして荷物を取り、また遠回りして棚へ
move 8
right
move 2
right
move 3
pick
move 5
left
move 2
left
move 8
drop
"""),
)


@dataclass
class Game:                                         # ←
    """遊びの状態をひとまとめに。端末もブラウザも、ここだけを触る。

    プログラムの文字列を load() で受け取り、advance() で 1 コマずつ進める。
    読み込みの失敗（error）と、実行の途中（beat）を別々に持つのが要点。
    """

    level: int = 0
    source: str = ""
    world: Warehouse = field(default_factory=Warehouse)
    program: list[Order] = field(default_factory=list)
    error: ProgramError | None = None
    beat: Beat | None = None
    beats: object = None                            # 実行中のジェネレータ（無ければ None）
    moves: int = 0
    running: bool = False

    def __post_init__(self) -> None:
        self.open_stage(self.level)

    @property
    def stage(self) -> Stage:
        return STAGES[self.level]

    def open_stage(self, level: int) -> None:       # ←
        """面を開く。お手本のプログラムを入れた状態から始める。"""
        self.level = level % len(STAGES)
        self.load(self.stage.example)

    def load(self, source: str) -> None:            # ←
        """プログラムを読み込む。書き間違いはここで捕まえ、実行には進まない。"""
        self.source = source
        self.restart()
        try:
            self.program = build(scan(source))
            self.error = None
        except ProgramError as err:
            self.program, self.error = [], err

    def restart(self) -> None:                      # ←
        """倉庫を元に戻して、実行を最初から。プログラムはそのまま。"""
        self.world = Warehouse.read(self.stage.ground)
        self.beats = self.beat = None
        self.moves = 0
        self.running = False

    def advance(self) -> bool:                      # ←
        """1 コマ進める。進めたら True、終わっていたら False。

        ジェネレータを持っておいて next() を 1 回呼ぶだけ。
        「どこまで実行したか」を自分で数えなくていいのが、ジェネレータの効き目。
        """
        if self.error:
            return False
        if self.beats is None:
            self.beats = run(self.world, self.program)
        beat = next(self.beats, None)
        if beat is None:                            # 終わっても最後のコマは消さない
            self.running = False                    # （消すと画面が「はじめから」に戻ってしまう）
            return False
        self.beat = beat
        self.moves += 1
        return True

    def finish(self, limit: int = 2000) -> None:    # ←
        """終わりまで一気に進める。限りを付けておく（長いプログラムで固まらない）。"""
        for _ in range(limit):
            if not self.advance():
                return

    @property
    def done(self) -> bool:
        return self.world.done

    def report(self) -> list[str]:                  # ←
        """今の様子。書き間違いがあればその報告、無ければ 1 行の状態。"""
        if self.error:
            return self.error.report(self.source)
        hand = "荷物を持っている" if self.world.holding else "手ぶら"
        note = f"{self.beat.line} 行目: {self.beat.note}" if self.beat else "はじめから"
        return [f"{note:26} {hand:16} "
                f"棚 {len(self.world.shelves & self.world.crates)}/{len(self.world.shelves)}  "
                f"{self.moves} コマ" + ("  運び終わった！" if self.done else "")]


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

    def box(self, x: int, y: int, w: int, h: int, color: tuple[int, int, int]) -> None:
        for row in range(y, y + h):
            for col in range(x, x + w):
                self.plot(col, row, color)

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


def draw(screen: Screen, world: Warehouse) -> None:
    """倉庫 1 枚。床 → 棚 → 壁 → 荷物 → ロボット の順に重ねる。"""
    screen.clear()
    for y in range(ROWS):
        for x in range(COLS):
            screen.box(x * CELL, y * CELL, CELL, CELL, FLOOR)
            screen.plot(x * CELL, y * CELL, GRID)   # マスの目印を左上に 1 ドット
    for x, y in world.shelves:
        frame(screen, x, y, SHELF)
    for x, y in world.walls:
        screen.box(x * CELL, y * CELL, CELL, CELL, WALL)
        screen.box(x * CELL, y * CELL, CELL, 3, WALL_TOP)
    for x, y in world.crates:
        crate(screen, x, y, (x, y) in world.shelves)
    robot(screen, world)


def frame(screen: Screen, x: int, y: int, color: tuple[int, int, int]) -> None:
    """マスの枠だけを描く（棚に使う）。"""
    for i in range(CELL):
        screen.plot(x * CELL + i, y * CELL, color)
        screen.plot(x * CELL + i, y * CELL + CELL - 1, color)
        screen.plot(x * CELL, y * CELL + i, color)
        screen.plot(x * CELL + CELL - 1, y * CELL + i, color)


def crate(screen: Screen, x: int, y: int, delivered: bool = False) -> None:
    """荷物 1 つ。ふちを明るくすると、床から浮いて見える。棚に載ったら色を変える。"""
    screen.box(x * CELL + 1, y * CELL + 1, CELL - 2, CELL - 2, DONE if delivered else CRATE)
    frame(screen, x, y, DONE_EDGE if delivered else CRATE_EDGE)


def robot(screen: Screen, world: Warehouse) -> None:
    """ロボット。向きが分かるように、正面に目を 2 つ描く。"""
    x, y = world.at
    screen.box(x * CELL + 2, y * CELL + 2, CELL - 4, CELL - 4, ROBOT)
    dx, dy = WAYS[world.facing]
    cx, cy = x * CELL + CELL // 2, y * CELL + CELL // 2
    for side in (-1, 1):
        screen.plot(cx + dx * 2 - dy * side, cy + dy * 2 + dx * side, ROBOT_EYE)
    if world.holding:                               # 持っている荷物は頭の上に
        screen.box(x * CELL + 3, y * CELL, CELL - 6, 2, HELD)


# わざと間違えたプログラム。エラーの出し方を確かめるために置いてある。
MISTAKES = (
    "move 3\njmp 2\n",
    "move\n",
    "left 2\n",
    "move 3 4\n",
    "move ★\n",
    "3 move\n",
    "move 0\n",
)


def show_tokens(source: str) -> list[str]:
    """語の一覧を表にする。字句解析が正しく切れているかは、これで目で見る。"""
    out = [f"{'行':>3} {'桁':>3}  {'種類':8} 中身"]
    for token in scan(source):
        text = "改行" if token.kind == "newline" else token.text
        out.append(f"{token.line:3d} {token.col:3d}  {token.kind:8} {text}")
    return out


def listing(source: str, here: int = 0) -> list[str]:
    """プログラムの一覧。今の行に印を付ける。"""
    out = []
    for n, text in enumerate(source.splitlines(), start=1):
        mark = "▶" if n == here else " "
        out.append(f"{mark}{n:3d} | {text}")
    return out


def show(game: Game) -> None:
    """画面を 1 枚。上が倉庫、下がプログラムと様子。"""
    screen = Screen()
    draw(screen, game.world)
    out = ["\x1b[H" + screen.render() + "\x1b[0m",
           f"面 {game.level + 1} {game.stage.name}\x1b[K\n"]
    here = game.beat.line if game.beat else 0
    for line in listing(game.source, here):
        out.append(line + "\x1b[K\n")
    for line in game.report():
        out.append(line + "\x1b[K\n")
    out.append("空白 1 コマ  r 一気に  b もどす  n 次の面  q やめる\x1b[K\n\x1b[J")
    sys.stdout.write("".join(out))
    sys.stdout.flush()


def read_keys(fd: int) -> list[str]:
    """押されたキーを名前で。"""
    keys = []
    while select.select([fd], [], [], 0)[0]:
        text = os.read(fd, 64).decode(errors="ignore")
        for token, name in ((" ", "step"), ("r", "run"), ("b", "back"),
                            ("n", "next"), ("q", "quit")):
            keys.extend([name] * text.count(token))
    return keys


def obey(game: Game, key: str) -> bool:             # ←
    """キー 1 つ。やめるなら False。端末でもブラウザでも同じ物を使う。"""
    match key:
        case "quit":
            return False
        case "step":
            game.running = False
            game.advance()
        case "run":
            game.running = True
        case "back":
            game.restart()
        case "next":
            game.open_stage(game.level + 1)
    return True


def check_terminal() -> str | None:
    columns, lines = shutil.get_terminal_size()
    need = HEIGHT // 2 + 16
    if columns < WIDTH or lines < need:
        return f"端末を {WIDTH} 桁 × {need} 行以上にしてください（今は {columns} × {lines}）。"
    return None


def play(game: Game) -> None:                       # ←
    """端末で動かす。r で走り出し、空白で 1 コマずつ。"""
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    tty.setcbreak(fd)
    try:
        sys.stdout.write("\x1b[2J\x1b[?25l")
        while True:
            for key in read_keys(fd):
                if not obey(game, key):
                    return
            if game.running and not game.advance():
                game.running = False
            show(game)
            time.sleep(0.12 if game.running else 0.03)
    finally:
        sys.stdout.write("\x1b[0m\x1b[?25h")
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    print()


def check_stages() -> list[str]:                    # ←
    """全部の面で、お手本のプログラムが本当に解けるかを見る。"""
    out = []
    for level, stage in enumerate(STAGES):
        game = Game(level=level)
        game.finish()
        mark = "解けた" if game.done else "解けない"
        out.append(f"面 {level + 1} {stage.name:8} {mark}  "
                   f"{len(game.program):2d} 命令 → {game.moves:3d} コマ  "
                   f"書き間違い {'あり' if game.error else 'なし'}")
    return out


def show_mistakes() -> list[str]:
    """わざと間違えたプログラムを順に読ませて、報告を並べる。"""
    out = []
    for source in MISTAKES:
        game = Game()
        game.load(source)
        out.extend(game.report() if game.error else [f"（{source.strip()!r} は通ってしまった）"])
        out.append("")
    return out


def main():
    parser = argparse.ArgumentParser(description="倉庫のロボット — 自作の言葉で荷物を運ぶ")
    parser.add_argument("file", nargs="?", help="プログラムの入ったファイル（省略するとお手本）")
    parser.add_argument("--stage", type=int, default=1, help="面（1 から）")
    parser.add_argument("--tokens", action="store_true", help="語の一覧を出す")
    parser.add_argument("--trace", action="store_true", help="1 コマずつ、何が起きたかを書き出す")
    parser.add_argument("--check", action="store_true", help="お手本が全部の面を解けるか見る")
    parser.add_argument("--mistakes", action="store_true", help="わざと間違えて、報告の出方を見る")
    args = parser.parse_args()
    if args.check:
        for line in check_stages():
            print(line)
        return
    if args.mistakes:
        for line in show_mistakes():
            print(line)
        return
    game = Game(level=args.stage - 1)
    if args.file:
        game.load(open(args.file, encoding="utf-8").read())
    if args.tokens:
        for line in show_tokens(game.source):
            print(line)
        return
    if args.trace:
        while game.advance():
            print(f"{game.beat.line:3d} 行目  {game.beat.note:10}  "
                  f"{game.world.at} {FACING[game.world.facing]}")
        for line in game.report():
            print(line)
        return
    if problem := check_terminal():
        print(problem)
        return
    play(game)


if __name__ == "__main__":
    main()
