"""倉庫のロボット2 — 完成: 繰り返しと条件。再帰下降で構文木を作り、singledispatch で実行する。"""

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
from functools import singledispatch
from textwrap import indent
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
# g68 では括弧（{ } ( )）が加わった。中身のある言葉になると、
# 「まとまり」を表す記号が要る。
# **最後の bad は「ほかのどれでもない 1 文字」**。これを置いておくと、
# 読めない文字が黙って消えることがなくなる（必ずどれかの語になる）。
WORDS = re.compile(r"""
      (?P<space>[ \t]+)
    | (?P<comment>\#[^\n]*)
    | (?P<newline>\n)
    | (?P<number>\d+)
    | (?P<name>[A-Za-z_][A-Za-z_0-9]*)
    | (?P<punct>[{}()])
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

    def sense(self, what: str) -> bool:
        """目の前を見る。free は「通れるか」（壁でも荷物でもない）。"""
        spot = self.ahead()
        match what:
            case "wall":
                return spot in self.walls
            case "crate":
                return spot in self.crates
            case "shelf":
                return spot in self.shelves
            case _:
                return not self.blocked(spot)

    @property
    def done(self) -> bool:
        """全部の棚に荷物が載ったか。集合の包含で 1 行。"""
        return self.shelves <= self.crates


# 命令の表。名前 → 数を取るかどうか。ここ 1 か所で「言葉」が決まる。
ORDERS = {"move": True, "left": False, "right": False,
          "pick": False, "drop": False, "wait": True}

# 目の前を見る言葉。front is ○○ の ○○ に書ける。
SENSES = ("wall", "free", "crate", "shelf")

# 構文木の節。**どれも frozen** にしてある。木は作ったあと書き換えない。
# 「読む（表示する）」と「動かす（実行する）」を別の関数に分けるので、
# 節そのものは「何が書いてあったか」だけを持てばいい。


@dataclass(frozen=True)
class Do:
    """命令 1 つ。move 3 のような葉。"""

    name: str
    count: int
    line: int
    col: int


@dataclass(frozen=True)
class Repeat:
    """repeat N { ... }。body の中にまた節が入るので、木になる。"""

    count: int
    body: tuple
    line: int
    col: int


@dataclass(frozen=True)
class If:
    """if 条件 { ... } else { ... }。else が無ければ other は空。"""

    test: object
    body: tuple
    other: tuple
    line: int
    col: int


@dataclass(frozen=True)
class While:
    """while 条件 { ... }。条件が真である間ずっと。"""

    test: object
    body: tuple
    line: int
    col: int


@dataclass(frozen=True)
class Sense:
    """front is wall のような問い。"""

    what: str
    line: int
    col: int


@dataclass(frozen=True)
class Holding:
    """荷物を持っているか。"""

    line: int
    col: int


@dataclass(frozen=True)
class Not:
    """not 条件。"""

    inner: object


@dataclass(frozen=True)
class Both:
    """条件 and 条件。"""

    left: object
    right: object


@dataclass(frozen=True)
class Either:
    """条件 or 条件。"""

    left: object
    right: object


class ProgramError(Exception):
    """書き間違い。**どの語が悪かったか**を覚えていて、そのまま画面に出せる。

    Python 自身の SyntaxError も、出しているのは同じ 3 つ——行の中身、
    どこかを指す ^、そして説明。位置を持った Token を作っておいたのは、
    このためだった。
    """

    def __init__(self, message: str, token: Token):
        super().__init__(message)
        self.token = token

    def report(self, source: str) -> list[str]:       # ←
        """3 行の報告を組み立てる。行の中身・^・説明。"""
        rows = source.splitlines()
        text = rows[self.token.line - 1] if self.token.line <= len(rows) else ""
        width = max(len(self.token.text), 1) if self.token.kind != "newline" else 1
        return [f"{self.token.line} 行目 {self.token.col} 文字目: {self.args[0]}",
                f"  {text}",
                "  " + " " * (self.token.col - 1) + "^" * width]


class Parser:
    """語の列を読んで構文木を作る（再帰下降）。

    「文を読む関数」が「中身の文を読む関数」を呼ぶ——という形が、そのまま
    入れ子の構造になる。repeat の中に if があり、その中にまた repeat があっても、
    同じ関数が再帰で呼ばれるだけ。

    **1 つ目の間違いで止まらない。** 見つけた間違いは errors に貯めて、
    次の行まで読み飛ばしてから続きを読む（recover）。
    """

    def __init__(self, tokens: list[Token], source: str):
        self.tokens = tokens
        self.source = source
        self.i = 0
        self.errors: list[ProgramError] = []

    # --- 語を見る道具 ---

    @property
    def here(self) -> Token:
        if self.i < len(self.tokens):
            return self.tokens[self.i]
        last = self.tokens[-1] if self.tokens else Token("newline", "\n", 1, 1)
        return Token("end", "", last.line, last.col)

    def take(self) -> Token:
        token = self.here
        self.i += 1
        return token

    def at(self, kind: str, text: str | None = None) -> bool:
        return self.here.kind == kind and (text is None or self.here.text == text)

    def skip_blank(self) -> None:
        while self.at("newline"):
            self.i += 1

    def want(self, kind: str, text: str, message: str) -> Token:
        if not self.at(kind, text):
            raise ProgramError(message, self.here)
        return self.take()

    def recover(self) -> None:                        # ←
        """次の行の頭まで読み飛ばす。

        **必ず 1 つは進める**のが肝。悪かった語の上で止まったまま次を読もうとすると、
        同じ語でまた失敗して、永遠に回り続ける（実際にそうなって固まった）。
        そのあとは改行か } まで飛ばす。} を食べないのは、かたまりの終わりを見失うから。
        """
        if not self.at("end"):
            self.i += 1
        while not self.at("end") and not self.at("newline") and not self.at("punct", "}"):
            self.i += 1
        self.skip_blank()

    # --- 文法 ---

    def block(self, closing: str | None = None) -> tuple:
        """文を並べて読む。closing が来たら、そこで終わり。"""
        body = []
        while True:
            self.skip_blank()
            if self.at("end") or (closing and self.at("punct", closing)):
                return tuple(body)
            try:
                body.append(self.statement())
            except ProgramError as err:
                self.errors.append(err)
                self.recover()

    def braced(self) -> tuple:
        """{ から } まで。中身は block がそのまま読む（＝再帰）。"""
        self.want("punct", "{", "ここには { が要ります")
        body = self.block(closing="}")
        self.want("punct", "}", "} が足りません")
        return body

    def statement(self):
        """1 つの文。頭の語で、どの形かが決まる。"""
        head = self.here
        if head.kind == "bad":
            raise ProgramError(f"読めない文字です（{head.text!r}）", head)
        if head.kind != "name":
            raise ProgramError("行のはじめは命令か repeat / if / while です", head)
        match head.text:
            case "repeat":
                self.take()
                if not self.at("number"):
                    raise ProgramError("repeat には回数が要ります（例: repeat 4 {）", self.here)
                return Repeat(int(self.take().text), self.braced(), head.line, head.col)
            case "if":
                self.take()
                test = self.test()
                body = self.braced()
                other = ()
                mark = self.i
                self.skip_blank()
                if self.at("name", "else"):
                    self.take()
                    other = self.braced()
                else:
                    self.i = mark                   # else が無ければ、改行を戻す
                return If(test, body, other, head.line, head.col)
            case "while":
                self.take()
                test = self.test()
                return While(test, self.braced(), head.line, head.col)
            case _:
                return self.order()

    def unreadable(self) -> None:
        """今いる語が「読めない文字」なら、そう言って止める。"""
        if self.at("bad"):
            raise ProgramError(f"読めない文字です（{self.here.text!r}）", self.here)

    def order(self):
        """move 3 のような、いちばん小さい文。"""
        head = self.take()
        self.unreadable()
        if head.text not in ORDERS:
            near = "・".join(ORDERS)
            raise ProgramError(f"{head.text} という命令はありません（使えるのは {near}）", head)
        count = 1
        if ORDERS[head.text]:
            if not self.at("number"):
                raise ProgramError(f"{head.text} には回数が要ります（例: {head.text} 3）", head)
            count = int(self.take().text)
            if count == 0:
                raise ProgramError("0 回では何も起きません", self.tokens[self.i - 1])
        elif self.at("number"):
            raise ProgramError(f"{head.text} に回数は付けられません", self.here)
        self.line_end()
        return Do(head.text, count, head.line, head.col)

    def line_end(self) -> None:
        """命令のあとは、改行か } か終わりのはず。"""
        self.unreadable()
        if not (self.at("newline") or self.at("end") or self.at("punct", "}")):
            raise ProgramError("この行には余分な語があります", self.here)

    # --- 条件。優先順位は or < and < not < かたまり ---

    def test(self):
        """条件式。or がいちばん弱く、not がいちばん強い。

        「弱い方から順に関数を呼ぶ」と、優先順位がそのまま関数の呼び出しの
        深さになる。掛け算が足し算より強い、を同じ形で書ける。
        """
        node = self.and_test()
        while self.at("name", "or"):
            self.take()
            node = Either(node, self.and_test())
        return node

    def and_test(self):
        node = self.not_test()
        while self.at("name", "and"):
            self.take()
            node = Both(node, self.not_test())
        return node

    def not_test(self):
        if self.at("name", "not"):
            self.take()
            return Not(self.not_test())             # not not front is wall も書ける
        return self.atom()

    def atom(self):
        token = self.here
        if self.at("punct", "("):
            self.take()
            node = self.test()
            self.want("punct", ")", ") が足りません")
            return node
        if self.at("name", "front"):
            self.take()
            self.want("name", "is", "front のあとは is です（front is wall）")
            what = self.here
            if what.kind != "name" or what.text not in SENSES:
                raise ProgramError(f"front is のあとは {' / '.join(SENSES)} です", what)
            self.take()
            return Sense(what.text, token.line, token.col)
        if self.at("name", "holding"):
            self.take()
            return Holding(token.line, token.col)
        raise ProgramError("ここには条件が要ります（front is wall / holding / not …）", token)


def build(source: str) -> tuple:                      # ←
    """文字列から構文木を作る。書き間違いは**全部**集めてから、まとめて投げる。

    ExceptionGroup は「同時に起きた複数の失敗」を 1 つにまとめて運ぶ入れ物。
    1 つ目で止めると、直しては走らせ、を間違いの数だけ繰り返すことになる。
    """
    parser = Parser(scan(source), source)
    body = parser.block()
    if parser.errors:
        raise ExceptionGroup("プログラムに書き間違いがあります", parser.errors)
    return body


class Beat(NamedTuple):
    """実行の 1 コマ。**どの行を実行したか**と、そのとき起きたこと。"""

    line: int
    note: str


@singledispatch
def perform(node, world: Warehouse):
    """節を 1 つ実行する。**節の種類ごとに、下で別々の関数を登録する。**

    if の連なりや match で振り分けてもいいが、singledispatch なら
    「節を 1 つ足したら、その節のための関数を 1 つ足す」だけで済む。
    木の側（dataclass）は何も知らなくていい。
    """
    raise TypeError(f"知らない木の節です: {node!r}")


@perform.register
def perform_do(node: Do, world: Warehouse):
    """葉。move 3 は 3 コマに分ける（途中でぶつかった様子が見えるように）。"""
    for _ in range(node.count):
        yield Beat(node.line, act(world, node.name))


@perform.register
def perform_repeat(node: Repeat, world: Warehouse):
    """回数ぶん、中身をそのまま流す。**yield from が入れ子をつなぐ。**"""
    for _ in range(node.count):
        yield from walk(node.body, world)


@perform.register
def perform_if(node: If, world: Warehouse):
    """条件を見て、どちらかの中身へ。見たこと自体も 1 コマにする。"""
    picked = ask(node.test, world)
    yield Beat(node.line, "条件は本当" if picked else "条件は違う")
    yield from walk(node.body if picked else node.other, world)


@perform.register
def perform_while(node: While, world: Warehouse):
    """条件が本当である間、ずっと。**毎回 1 コマ使う**ので、止まらない
    プログラムも呼ぶ側の上限で必ず打ち切れる。"""
    while ask(node.test, world):
        yield Beat(node.line, "条件は本当")
        yield from walk(node.body, world)
    yield Beat(node.line, "条件は違う")


def walk(body: tuple, world: Warehouse):
    """並んだ節を順に実行する。木をたどる入口。"""
    for node in body:
        yield from perform(node, world)


@singledispatch
def ask(node, world: Warehouse) -> bool:
    """条件を確かめる。こちらも節の種類ごとに登録する。"""
    raise TypeError(f"知らない条件です: {node!r}")


@ask.register
def ask_sense(node: Sense, world: Warehouse) -> bool:
    return world.sense(node.what)


@ask.register
def ask_holding(node: Holding, world: Warehouse) -> bool:
    return world.holding


@ask.register
def ask_not(node: Not, world: Warehouse) -> bool:
    return not ask(node.inner, world)


@ask.register
def ask_both(node: Both, world: Warehouse) -> bool:
    return ask(node.left, world) and ask(node.right, world)


@ask.register
def ask_either(node: Either, world: Warehouse) -> bool:
    return ask(node.left, world) or ask(node.right, world)


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


@singledispatch
def sketch(node) -> str:
    """節を字にする。**実行とまったく同じ木に、別のふるまいを足しただけ。**

    木（dataclass）には表示のコードが 1 行も入っていない。
    あとから「木を絵にする」を足したくなっても、木は触らなくていい。
    """
    return repr(node)


@sketch.register
def sketch_do(node: Do) -> str:
    return f"{node.name} {node.count}" if ORDERS[node.name] else node.name


@sketch.register
def sketch_repeat(node: Repeat) -> str:
    return f"repeat {node.count}\n" + indent(sketch_all(node.body), "    ")


@sketch.register
def sketch_if(node: If) -> str:
    text = f"if {phrase(node.test)}\n" + indent(sketch_all(node.body), "    ")
    if node.other:
        text += "\nelse\n" + indent(sketch_all(node.other), "    ")
    return text


@sketch.register
def sketch_while(node: While) -> str:
    return f"while {phrase(node.test)}\n" + indent(sketch_all(node.body), "    ")


def sketch_all(body: tuple) -> str:
    """並んだ節を、1 行 1 節で。indent がこれを丸ごと字下げする。"""
    return "\n".join(sketch(node) for node in body)


@singledispatch
def phrase(node) -> str:
    """条件を字にする。"""
    return repr(node)


@phrase.register
def phrase_sense(node: Sense) -> str:
    return f"front is {node.what}"


@phrase.register
def phrase_holding(node: Holding) -> str:
    return "holding"


@phrase.register
def phrase_not(node: Not) -> str:
    return f"not {phrase(node.inner)}"


@phrase.register
def phrase_both(node: Both) -> str:
    return f"({phrase(node.left)} and {phrase(node.right)})"


@phrase.register
def phrase_either(node: Either) -> str:
    return f"({phrase(node.left)} or {phrase(node.right)})"


@dataclass(frozen=True)
class Stage:
    """面 1 つ。地図と、お手本のプログラム。"""

    name: str
    ground: str
    example: str


STAGES = (
    Stage("くりかえし", """\
############
#@.........#
#..........#
#..o.o.o...#
#..........#
#..=.=.=...#
#..........#
############""", """\
# 同じ手順を 3 回。repeat が無ければ 32 行かかる
right
move 1
left
move 2
right
repeat 3 {
  pick
  move 2
  drop
  right
  right
  move 2
  right
  move 2
  right
}
"""),
    Stage("つきあたり", """\
############
#@.........#
##########.#
#.........o#
#.##########
#=.........#
#..........#
############""", """\
# 何マスあるか数えない。「進めるあいだ進む」と書く
while front is free {
  move 1
}
right
while front is free {
  move 1
}
pick
while front is free {
  move 1
}
right
while front is free {
  move 1
}
left
while not front is shelf {
  move 1
}
drop
"""),
    Stage("ぐるり", """\
############
#@........o#
#.########.#
#.########.#
#.########.#
#=.........#
#..........#
############""", """\
# 見たものに合わせて動く。道順は書かない
while not holding {
  if front is crate {
    pick
  } else {
    if front is free {
      move 1
    } else {
      right
    }
  }
}
while not front is shelf {
  if front is free {
    move 1
  } else {
    right
  }
}
drop
"""),
)


@dataclass
class Game:
    """遊びの状態をひとまとめに。端末もブラウザも、ここだけを触る。"""

    level: int = 0
    source: str = ""
    world: Warehouse = field(default_factory=Warehouse)
    program: tuple = ()
    errors: list[ProgramError] = field(default_factory=list) # ←
    beat: Beat | None = None
    beats: object = None                            # 実行中のジェネレータ（無ければ None）
    moves: int = 0
    running: bool = False
    stopped: bool = False                           # 上限に当たって打ち切ったか

    def __post_init__(self) -> None:
        self.open_stage(self.level)

    @property
    def stage(self) -> Stage:
        return STAGES[self.level]

    def open_stage(self, level: int) -> None:
        """面を開く。お手本のプログラムを入れた状態から始める。"""
        self.level = level % len(STAGES)
        self.load(self.stage.example)

    def load(self, source: str) -> None:              # ←
        """プログラムを読み込む。**書き間違いは全部まとめて受け取る。**

        except* は ExceptionGroup を「その種類だけ」取り出す書き方。
        1 つ目で止まらないので、直しては走らせ、を繰り返さずに済む。
        """
        self.source = source
        self.restart()
        self.errors = []
        try:
            self.program = build(source)
        except* ProgramError as group:
            self.program = ()
            self.errors = list(group.exceptions)

    def restart(self) -> None:
        """倉庫を元に戻して、実行を最初から。プログラムはそのまま。"""
        self.world = Warehouse.read(self.stage.ground)
        self.beats = self.beat = None
        self.moves = 0
        self.running = self.stopped = False

    def advance(self, limit: int = 4000) -> bool:
        """1 コマ進める。進めたら True、終わっていたら False。

        止まらないプログラム（while front is free の中で動かない、など）は
        書けてしまうし、**止まるかどうかを先に調べることはできない**ので、
        コマ数の上限で守る。
        """
        if self.errors or self.stopped:
            return False
        if self.moves >= limit:
            self.stopped = True
            self.running = False
            return False
        if self.beats is None:
            self.beats = walk(self.program, self.world)
        beat = next(self.beats, None)
        if beat is None:                            # 終わっても最後のコマは消さない
            self.running = False
            return False
        self.beat = beat
        self.moves += 1
        return True

    def finish(self, limit: int = 4000) -> None:
        """終わりまで一気に進める。"""
        while self.advance(limit):
            pass

    @property
    def done(self) -> bool:
        return self.world.done

    def tree(self) -> str:
        """構文木を字にしたもの。書けていれば、木の形がそのまま見える。"""
        return sketch_all(self.program)

    def report(self) -> list[str]:                    # ←
        """今の様子。書き間違いがあれば**全部**、無ければ 1 行の状態。"""
        if self.errors:
            out = [f"書き間違いが {len(self.errors)} か所あります"]
            for err in self.errors:
                out.extend(err.report(self.source))
                out.append("")
            return out[:-1]
        hand = "荷物を持っている" if self.world.holding else "手ぶら"
        note = f"{self.beat.line} 行目: {self.beat.note}" if self.beat else "はじめから"
        tail = "  運び終わった！" if self.done else ("  打ち切った（長すぎる）" if self.stopped else "")
        return [f"{note:26} {hand:16} "
                f"棚 {len(self.world.shelves & self.world.crates)}/{len(self.world.shelves)}  "
                f"{self.moves} コマ" + tail]


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


# わざと間違えたプログラム。**1 つの中に複数の間違い**を入れてある。
MISTAKES = (
    "repeat 3 {\n  jmp 2\n  move\n}\n",
    "if front is sky {\n  move 1\n}\n",
    "repeat {\n  move 1\n}\n",
    "while front is free {\n  move 1\n",
    "move 3 4\nleft 2\nmove ★\n",
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


def obey(game: Game, key: str) -> bool:
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
    need = HEIGHT // 2 + 20
    if columns < WIDTH or lines < need:
        return f"端末を {WIDTH} 桁 × {need} 行以上にしてください（今は {columns} × {lines}）。"
    return None


def play(game: Game) -> None:
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
            time.sleep(0.09 if game.running else 0.03)
    finally:
        sys.stdout.write("\x1b[0m\x1b[?25h")
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    print()


@singledispatch
def count(node) -> int:
    """書いた文の数。入れ子の中も数える。"""
    return 1


@count.register
def count_repeat(node: Repeat) -> int:
    return 1 + sum(count(child) for child in node.body)


@count.register
def count_if(node: If) -> int:
    return 1 + sum(count(child) for child in node.body + node.other)


@count.register
def count_while(node: While) -> int:
    return 1 + sum(count(child) for child in node.body)


@singledispatch
def unroll(node) -> int:
    """repeat を全部ほどいたら何文になるか。**repeat の効き目を数で見るため。**

    while と if はほどけない（何回まわるかは動かしてみないと分からない）ので、
    そのまま数える。ここが同じ数なら「repeat では短くなっていない」という意味。
    """
    return 1


@unroll.register
def unroll_repeat(node: Repeat) -> int:
    return node.count * sum(unroll(child) for child in node.body)


@unroll.register
def unroll_if(node: If) -> int:
    return 1 + sum(unroll(child) for child in node.body + node.other)


@unroll.register
def unroll_while(node: While) -> int:
    return 1 + sum(unroll(child) for child in node.body)


def check_stages() -> list[str]:
    """全部の面で、お手本のプログラムが本当に解けるかを見る。"""
    out = []
    for level, stage in enumerate(STAGES):
        game = Game(level=level)
        game.finish()
        mark = "解けた" if game.done else "解けない"
        wrote = sum(count(node) for node in game.program)
        opened = sum(unroll(node) for node in game.program)
        out.append(f"面 {level + 1} {stage.name:8} {mark}  "
                   f"書いた文 {wrote:2d}（repeat を開くと {opened:3d}）→ {game.moves:3d} コマ  "
                   f"書き間違い {len(game.errors)} か所")
    return out


def show_mistakes() -> list[str]:
    """わざと間違えたプログラムを読ませて、報告を並べる。"""
    out = []
    for source in MISTAKES:
        game = Game()
        game.load(source)
        out.extend(game.report() if game.errors else [f"（{source.strip()!r} は通ってしまった）"])
        out.append("")
    return out


def main():
    parser = argparse.ArgumentParser(description="倉庫のロボット2 — 繰り返しと条件")
    parser.add_argument("file", nargs="?", help="プログラムの入ったファイル（省略するとお手本）")
    parser.add_argument("--stage", type=int, default=1, help="面（1 から）")
    parser.add_argument("--tokens", action="store_true", help="語の一覧を出す")
    parser.add_argument("--tree", action="store_true", help="構文木を出す")
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
    if args.tree:
        for line in game.report() if game.errors else [game.tree()]:
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
