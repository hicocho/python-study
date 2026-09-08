"""倉庫のロボット3 — 完成: 変数と手順。ChainMap でスコープを作り、再帰も書ける。"""

import argparse
import os
import re
import select
import shutil
import sys
import termios
import time
import tty
from collections import ChainMap
from dataclasses import dataclass, field
from functools import singledispatch
from operator import add, eq, floordiv, gt, lt, mul, ne, sub
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
# g68 で括弧（{ } ( )）、g69 で計算と比べ方の記号（+ - * / < > =）が加わった。
# **記号を 1 文字ずつ拾う**ので、= と = を並べれば == も書ける（今回は使わない）。
# **最後の bad は「ほかのどれでもない 1 文字」**。これを置いておくと、
# 読めない文字が黙って消えることがなくなる（必ずどれかの語になる）。
WORDS = re.compile(r"""
      (?P<space>[ \t]+)
    | (?P<comment>\#[^\n]*)
    | (?P<newline>\n)
    | (?P<number>\d+)
    | (?P<name>[A-Za-z_][A-Za-z_0-9]*)
    | (?P<punct>[{}()+\-*/<>=])
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

# 計算と比べ方。**演算子を自分で書かず、operator の関数を表に入れる。**
# こうすると「記号 → 何をするか」が 1 行になり、増やすのも 1 行で済む。
CALCS = {"+": add, "-": sub, "*": mul, "/": floordiv}
CHECKS = {"<": lt, ">": gt, "=": eq}

# 構文木の節。**どれも frozen** にしてある。木は作ったあと書き換えない。
# 「読む（表示する）」と「動かす（実行する）」を別の関数に分けるので、
# 節そのものは「何が書いてあったか」だけを持てばいい。


@dataclass(frozen=True)
class Number:
    """そのまま数。3 とか 12。"""

    value: int
    line: int
    col: int


@dataclass(frozen=True)
class Name:
    """変数の名前。実行するときに、その時の値を引く。"""

    text: str
    line: int
    col: int


@dataclass(frozen=True)
class Calc:
    """足し算・引き算・掛け算・割り算。左と右がまた式なので、木になる。"""

    op: str
    left: object
    right: object
    line: int
    col: int


@dataclass(frozen=True)
class Do:
    """命令 1 つ。move n のような葉。回数は**式**（数でも変数でも計算でもいい）。"""

    name: str
    count: object
    line: int
    col: int


@dataclass(frozen=True)
class Set:
    """set n = 式。変数に値を入れる。"""

    name: str
    value: object
    line: int
    col: int


@dataclass(frozen=True)
class Define:
    """to 名前 { ... }。手順を 1 つ決める（呼ばれるまで動かない）。"""

    name: str
    body: tuple
    line: int
    col: int


@dataclass(frozen=True)
class Call:
    """決めた手順を呼ぶ。"""

    name: str
    line: int
    col: int


@dataclass(frozen=True)
class Repeat:
    """repeat 式 { ... }。body の中にまた節が入るので、木になる。"""

    count: object
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
class Compare:
    """n > 0 のような比べ方。"""

    op: str
    left: object
    right: object
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

    def report(self, source: str) -> list[str]:
        """3 行の報告を組み立てる。行の中身・^・説明。"""
        rows = source.splitlines()
        text = rows[self.token.line - 1] if self.token.line <= len(rows) else ""
        width = max(len(self.token.text), 1) if self.token.kind != "newline" else 1
        return [f"{self.token.line} 行目 {self.token.col} 文字目: {self.args[0]}",
                f"  {text}",
                "  " + " " * (self.token.col - 1) + "^" * width]


# 言葉として決まっている名前。手順の名前には使えない。
KEYWORDS = {"repeat", "if", "else", "while", "set", "to",
            "not", "and", "or", "front", "is", "holding"}


class RunError(Exception):
    """**動かしてみて初めて分かった**間違い。書いている時点では気づけない。

    未定義の変数、決めていない手順、0 で割った、呼び出しが深すぎる——どれも
    「そこを通ったら分かる」もの。書き間違い（ProgramError）と分けて扱う。
    """

    def __init__(self, message: str, node):
        super().__init__(message)
        self.line = getattr(node, "line", 1)
        self.col = getattr(node, "col", 1)

    def report(self, source: str) -> list[str]:
        rows = source.splitlines()
        text = rows[self.line - 1] if self.line <= len(rows) else ""
        return [f"{self.line} 行目 {self.col} 文字目: {self.args[0]}",
                f"  {text}",
                "  " + " " * (self.col - 1) + "^"]


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

    def recover(self) -> None:
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
                count = self.expr()                 # 数だけでなく、変数や計算も書ける
                return Repeat(count, self.braced(), head.line, head.col)
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
            case "set":
                self.take()
                name = self.want("name", None, "set のあとは変数の名前です（例: set n = 3）")
                if name.text in KEYWORDS or name.text in ORDERS:
                    raise ProgramError(f"{name.text} は言葉として決まっているので、変数の名前にできません", name)
                self.want("punct", "=", "変数の名前のあとは = です（例: set n = 3）")
                node = Set(name.text, self.expr(), head.line, head.col)
                self.line_end()
                return node
            case "to":
                self.take()
                name = self.want("name", None, "to のあとは手順の名前です（例: to fetch {）")
                if name.text in KEYWORDS or name.text in ORDERS:
                    raise ProgramError(f"{name.text} は言葉として決まっているので、手順の名前にできません", name)
                return Define(name.text, self.braced(), head.line, head.col)
            case _:
                if head.text in ORDERS:
                    return self.order()
                self.take()                         # 命令でも合言葉でもなければ、手順の呼び出し
                self.line_end()
                return Call(head.text, head.line, head.col)

    def unreadable(self) -> None:
        """今いる語が「読めない文字」なら、そう言って止める。"""
        if self.at("bad"):
            raise ProgramError(f"読めない文字です（{self.here.text!r}）", self.here)

    def order(self):
        """move n のような、いちばん小さい文。回数は式でよい。"""
        head = self.take()
        self.unreadable()
        count = Number(1, head.line, head.col)
        if ORDERS[head.text]:
            if not (self.at("number") or self.at("name") or self.at("punct", "(")):
                raise ProgramError(f"{head.text} には回数が要ります（例: {head.text} 3）", head)
            count = self.expr()
        elif self.at("number"):
            raise ProgramError(f"{head.text} に回数は付けられません", self.here)
        self.line_end()
        return Do(head.text, count, head.line, head.col)

    # --- 式。優先順位は + − < × ÷ ---

    def expr(self):
        """足し算・引き算。**条件のときと同じ手で、弱い方から順に呼ぶ。**"""
        node = self.term()
        while self.at("punct", "+") or self.at("punct", "-"):
            op = self.take()
            node = Calc(op.text, node, self.term(), op.line, op.col)
        return node

    def term(self):
        """掛け算・割り算。足し算より強いので、内側で読む。"""
        node = self.factor()
        while self.at("punct", "*") or self.at("punct", "/"):
            op = self.take()
            node = Calc(op.text, node, self.factor(), op.line, op.col)
        return node

    def factor(self):
        """数・変数・かっこ。いちばん強いかたまり。"""
        token = self.here
        if self.at("punct", "("):
            self.take()
            node = self.expr()
            self.want("punct", ")", ") が足りません")
            return node
        if self.at("number"):
            self.take()
            return Number(int(token.text), token.line, token.col)
        if self.at("name") and token.text not in KEYWORDS:
            self.take()
            return Name(token.text, token.line, token.col)
        raise ProgramError("ここには数か変数が要ります", token)

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
            mark = self.i                           # 条件のかっこか、式のかっこか
            try:
                self.take()
                node = self.test()
                self.want("punct", ")", ") が足りません")
                return node
            except ProgramError:
                self.i = mark                       # 条件として読めなかった。式として読み直す
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
        if self.at("number") or self.at("punct", "(") or (self.at("name") and token.text not in KEYWORDS):
            left = self.expr()
            op = self.here
            if not (op.kind == "punct" and op.text in CHECKS):
                raise ProgramError(f"ここには比べ方（{' '.join(CHECKS)}）が要ります", op)
            self.take()
            return Compare(op.text, left, self.expr(), op.line, op.col)
        raise ProgramError("ここには条件が要ります（front is wall / holding / n > 0 / not …）", token)


def build(source: str) -> tuple:
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


DEPTH = 40                                          # 手順の呼び出しは、これ以上深くしない # ←


@dataclass
class Runtime:
    """走らせている間の持ち物。世界と、決めた手順と、**変数の置き場**。

    変数は ChainMap。**手前の段に書き、読むときは奥まで探す。**
    手順を呼ぶたびに new_child() で 1 段かぶせ、出るときに 1 段外す。
    """

    world: Warehouse
    procs: dict = field(default_factory=dict)
    vars: ChainMap = field(default_factory=ChainMap)
    depth: int = 0
    deepest: int = 0                                # いちばん深く潜ったところ（見るため）


def collect(body: tuple, procs: dict) -> dict:
    """`to …` を先に集めておく。**呼ぶ場所より後ろで決めていてもいい**ようにする。"""
    for node in body:
        if isinstance(node, Define):
            procs[node.name] = node.body
            collect(node.body, procs)
    return procs


@singledispatch
def value(node, run: "Runtime") -> int:
    """式の値を出す。数・変数・計算の 3 種類。"""
    raise TypeError(f"知らない式です: {node!r}")


@value.register
def value_number(node: Number, run: "Runtime") -> int:
    return node.value


@value.register
def value_name(node: Name, run: "Runtime") -> int:
    """変数を読む。**ChainMap なので、手前に無ければ奥の段を探しにいく。**"""
    if node.text not in run.vars:
        raise RunError(f"{node.text} という変数はまだありません", node)
    return run.vars[node.text]


@value.register
def value_calc(node: Calc, run: "Runtime") -> int:
    """計算。記号から関数を引くだけ（CALCS の表）。"""
    left, right = value(node.left, run), value(node.right, run)
    if node.op == "/" and right == 0:
        raise RunError("0 では割れません", node)
    return CALCS[node.op](left, right)


@singledispatch
def perform(node, run: "Runtime"):
    """節を 1 つ実行する。**節の種類ごとに、下で別々の関数を登録する。**

    if の連なりや match で振り分けてもいいが、singledispatch なら
    「節を 1 つ足したら、その節のための関数を 1 つ足す」だけで済む。
    木の側（dataclass）は何も知らなくていい。
    """
    raise TypeError(f"知らない木の節です: {node!r}")


@perform.register
def perform_do(node: Do, run: "Runtime"):
    """葉。move n は n コマに分ける（途中でぶつかった様子が見えるように）。"""
    for _ in range(max(value(node.count, run), 0)):
        yield Beat(node.line, act(run.world, node.name))


@perform.register
def perform_set(node: Set, run: "Runtime"):
    """変数に入れる。**ChainMap は「いちばん手前の段」に書く。**"""
    run.vars[node.name] = value(node.value, run)
    yield Beat(node.line, f"{node.name} = {run.vars[node.name]}")


@perform.register
def perform_define(node: Define, run: "Runtime"):
    """手順を決める。決めるだけで、まだ動かない。"""
    run.procs[node.name] = node.body
    yield Beat(node.line, f"{node.name} をおぼえた")


@perform.register
def perform_call(node: Call, run: "Runtime"):
    """決めた手順を呼ぶ。**入るとき 1 段かぶせ、出るとき 1 段外す。**

    かぶせるのは ChainMap.new_child()、外すのは .parents。これだけで
    「手順の中で作った変数は、外に漏れない。外の変数は中から見える」になる。
    """
    body = run.procs.get(node.name)
    if body is None:
        raise RunError(f"{node.name} という手順は決まっていません", node)
    if run.depth >= DEPTH:                            # ←
        raise RunError(f"手順の呼び出しが深すぎます（{DEPTH} 段まで）", node)
    yield Beat(node.line, f"{node.name} をよんだ")
    run.depth += 1
    run.deepest = max(run.deepest, run.depth)
    run.vars = run.vars.new_child()
    try:
        yield from walk(body, run)
    finally:
        run.vars = run.vars.parents                 # 途中で止めても、必ず戻す
        run.depth -= 1


@perform.register
def perform_repeat(node: Repeat, run: "Runtime"):
    """回数ぶん、中身をそのまま流す。**yield from が入れ子をつなぐ。**"""
    for _ in range(max(value(node.count, run), 0)):
        yield from walk(node.body, run)


@perform.register
def perform_if(node: If, run: "Runtime"):
    """条件を見て、どちらかの中身へ。見たこと自体も 1 コマにする。"""
    picked = ask(node.test, run)
    yield Beat(node.line, "条件は本当" if picked else "条件は違う")
    yield from walk(node.body if picked else node.other, run)


@perform.register
def perform_while(node: While, run: "Runtime"):
    """条件が本当である間、ずっと。**毎回 1 コマ使う**ので、止まらない
    プログラムも呼ぶ側の上限で必ず打ち切れる。"""
    while ask(node.test, run):
        yield Beat(node.line, "条件は本当")
        yield from walk(node.body, run)
    yield Beat(node.line, "条件は違う")


def walk(body: tuple, run: "Runtime"):
    """並んだ節を順に実行する。木をたどる入口。"""
    for node in body:
        yield from perform(node, run)


@singledispatch
def ask(node, run: "Runtime") -> bool:
    """条件を確かめる。こちらも節の種類ごとに登録する。"""
    raise TypeError(f"知らない条件です: {node!r}")


@ask.register
def ask_sense(node: Sense, run: "Runtime") -> bool:
    return run.world.sense(node.what)


@ask.register
def ask_holding(node: Holding, run: "Runtime") -> bool:
    return run.world.holding


@ask.register
def ask_compare(node: Compare, run: "Runtime") -> bool:
    """比べる。こちらも記号から関数を引くだけ（CHECKS の表）。"""
    return CHECKS[node.op](value(node.left, run), value(node.right, run))


@ask.register
def ask_not(node: Not, run: "Runtime") -> bool:
    return not ask(node.inner, run)


@ask.register
def ask_both(node: Both, run: "Runtime") -> bool:
    return ask(node.left, run) and ask(node.right, run)


@ask.register
def ask_either(node: Either, run: "Runtime") -> bool:
    return ask(node.left, run) or ask(node.right, run)


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
    return f"{node.name} {shape(node.count)}" if ORDERS[node.name] else node.name


@sketch.register
def sketch_set(node: Set) -> str:
    return f"set {node.name} = {shape(node.value)}"


@sketch.register
def sketch_define(node: Define) -> str:
    return f"to {node.name}\n" + indent(sketch_all(node.body), "    ")


@sketch.register
def sketch_call(node: Call) -> str:
    return f"{node.name}（よぶ）"


@sketch.register
def sketch_repeat(node: Repeat) -> str:
    return f"repeat {shape(node.count)}\n" + indent(sketch_all(node.body), "    ")


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
def shape(node) -> str:
    """式を字にする。"""
    return repr(node)


@shape.register
def shape_number(node: Number) -> str:
    return str(node.value)


@shape.register
def shape_name(node: Name) -> str:
    return node.text


@shape.register
def shape_calc(node: Calc) -> str:
    return f"({shape(node.left)} {node.op} {shape(node.right)})"


@singledispatch
def phrase(node) -> str:
    """条件を字にする。"""
    return repr(node)


@phrase.register
def phrase_compare(node: Compare) -> str:
    return f"{shape(node.left)} {node.op} {shape(node.right)}"


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
    """面 1 つ。地図と、お手本のプログラムと、**星 3 つの目安**（書いた文の数）。"""

    name: str
    ground: str
    example: str
    par: int


STAGES = (
    Stage("てじゅん", """\
############
#@.........#
#..........#
#..o.o.o...#
#..........#
#..=.=.=...#
#..........#
############""", """\
# 同じ動きに名前を付ける。to で決めて、名前で呼ぶ
to carry {
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

right
move 1
left
move 2
right
repeat 3 {
  carry
}
""", 18),
    Stage("かぞえる", """\
############
#@.........#
#..........#
#..........#
#....o.....#
#..........#
#........=.#
############""", """\
# 数を変数に入れて、計算で使う（* は + より強い）
set step = 2
right
move step
left
move step * 2
right
pick
move step + 1
left
move step + 1
drop
""", 12),
    Stage("さいき", """\
############
#@.........#
##########.#
#.........o#
#.##########
#=.........#
#..........#
############""", """\
# while を使わずに、自分を呼んで進む
to dig {
  if front is free {
    move 1
    dig
  }
}

to seek {
  if not front is shelf {
    move 1
    seek
  }
}

dig
right
dig
pick
dig
right
dig
left
seek
drop
""", 20),
)


@dataclass
class Game:
    """遊びの状態をひとまとめに。端末もブラウザも、ここだけを触る。"""

    level: int = 0
    source: str = ""
    world: Warehouse = field(default_factory=Warehouse)
    run: Runtime | None = None
    program: tuple = ()
    errors: list[ProgramError] = field(default_factory=list)
    crash: RunError | None = None
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

    def load(self, source: str) -> None:
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
        """倉庫を元に戻して、実行を最初から。プログラムはそのまま。

        **手順は走らせる前に集めておく**（collect）。そうすると、呼ぶ場所より
        後ろで決めた手順も呼べるし、自分を呼ぶ手順（再帰）も書ける。
        """
        self.world = Warehouse.read(self.stage.ground)
        self.run = Runtime(self.world, collect(self.program, {}))
        self.beats = self.beat = None
        self.moves = 0
        self.crash = None
        self.running = self.stopped = False

    def advance(self, limit: int = 4000) -> bool:
        """1 コマ進める。進めたら True、終わっていたら False。

        止まらないプログラム（while front is free の中で動かない、など）は
        書けてしまうし、**止まるかどうかを先に調べることはできない**ので、
        コマ数の上限で守る。
        """
        if self.errors or self.stopped or self.crash:
            return False
        if self.moves >= limit:
            self.stopped = True
            self.running = False
            return False
        if self.beats is None:
            self.beats = walk(self.program, self.run)
        try:
            beat = next(self.beats, None)
        except RunError as err:                     # 動かしてみて分かった間違い
            self.crash = err
            self.running = False
            return False
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

    @property
    def wrote(self) -> int:
        """書いた文の数。星の数はこれで決まる。"""
        return sum(count(node) for node in self.program)

    @property
    def stars(self) -> int:                           # ←
        """星 3 つ = 目安以下。半分増しまでで 2 つ、それより多ければ 1 つ。"""
        if not self.done:
            return 0
        if self.wrote <= self.stage.par:
            return 3
        return 2 if self.wrote <= self.stage.par * 3 // 2 else 1

    def tree(self) -> str:
        """構文木を字にしたもの。書けていれば、木の形がそのまま見える。"""
        return sketch_all(self.program)

    def report(self) -> list[str]:
        """今の様子。書き間違いがあれば**全部**、無ければ 1 行の状態。"""
        if self.errors:
            out = [f"書き間違いが {len(self.errors)} か所あります"]
            for err in self.errors:
                out.extend(err.report(self.source))
                out.append("")
            return out[:-1]
        if self.crash:
            return ["動かしてみたら、止まりました"] + self.crash.report(self.source)
        hand = "荷物を持っている" if self.world.holding else "手ぶら"
        note = f"{self.beat.line} 行目: {self.beat.note}" if self.beat else "はじめから"
        tail = ("  " + "★" * self.stars if self.done
                else ("  打ち切った（長すぎる）" if self.stopped else ""))
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
    "set 3 = n\nmove ★\n",
    "to move {\n  move 1\n}\n",
    "move 3 4\nleft 2\nset n =\n",
)

# 動かしてみないと分からない間違い。**書き間違いとは別**。
CRASHES = (
    "move n\n",
    "fetch\n",
    "set n = 3 / 0\n",
    "to loop {\n  loop\n}\nloop\n",
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
def count_define(node: Define) -> int:
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
    """回数が変数や計算のときは、ほどけないのでそのまま数える。"""
    times = node.count.value if isinstance(node.count, Number) else 1
    return times * sum(unroll(child) for child in node.body)


@unroll.register
def unroll_define(node: Define) -> int:
    return 1 + sum(unroll(child) for child in node.body)


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
        out.append(f"面 {level + 1} {stage.name:8} {mark}  "
                   f"書いた文 {game.wrote:2d}（目安 {stage.par}）→ {game.moves:3d} コマ  "
                   f"{'★' * game.stars:6}  手順 {len(game.run.procs)} 個  "
                   f"いちばん深い呼び出し {game.run.deepest} 段")
    return out


def show_mistakes() -> list[str]:
    """わざと間違えたプログラムを読ませて、報告を並べる。"""
    out = ["── 書く前に分かる間違い ──"]
    for source in MISTAKES:
        game = Game()
        game.load(source)
        out.extend(game.report() if game.errors else [f"（{source.strip()!r} は通ってしまった）"])
        out.append("")
    out.append("── 動かしてみて分かる間違い ──")
    for source in CRASHES:
        game = Game()
        game.load(source)
        game.finish()
        out.extend(game.report() if game.crash else [f"（{source.strip()!r} は止まらなかった）"])
        out.append("")
    return out[:-1]


def main():
    parser = argparse.ArgumentParser(description="倉庫のロボット3 — 変数と手順")
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
