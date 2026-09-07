"""将棋 — 完成: 詰将棋。王手の連続で受け方に手がなくなる手順を、深さを限った全探索で見つける。問題集を解いて、自分でも解く。"""

import argparse
import random
import sys
import time
from collections import deque
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from itertools import islice
from enum import IntFlag
from itertools import product
from typing import NamedTuple

SENTE = "b"                                 # 先手（SFEN では black）
GOTE = "w"                                  # 後手（white）
START_SFEN = "lnsgkgsnl/1r5b1/ppppppppp/9/9/9/PPPPPPPPP/1B5R1/LNSGKGSNL b - 1"

RESULT_TEXT = {
    SENTE: "先手の勝ち（詰み）",
    GOTE: "後手の勝ち（詰み）",
    "sente-stalemate": "先手の勝ち（後手に指せる手がない）",
    "gote-stalemate": "後手の勝ち（先手に指せる手がない）",
    "sente-perpetual": "先手の勝ち（後手の連続王手の千日手）",
    "gote-perpetual": "後手の勝ち（先手の連続王手の千日手）",
    "repetition": "千日手（引き分け）",
    "tsume-fail": "手数を超えました（詰みませんでした）",     # ←
    "quit": "やめました。",
}
REPETITIONS = 4                             # 同じ局面がこの回数で千日手
FULL_SET = {"P": 18, "L": 4, "N": 4, "S": 4, "G": 4, "B": 2, "R": 2}   # 玉以外の駒の総数（詰将棋の受け方は残り全部が持ち駒）
MAX_TSUME_DEPTH = 9                         # ここまでの手数で探す

HINT_NODES = 3000                           # ヒントや受けを考えるときの上限（ブラウザで固まらないように） # ←

# 詰将棋の問題集。(題名, SFEN の盤と攻め方の持ち駒, 答えの手順)。受け方の持ち駒は「残り全部」なので書かない
PROBLEMS = [
    ("頭金", "k8/9/P8/9/9/9/9/9/4K4 b G", "G*9b"),
    ("腹金", "5k3/9/4S4/9/9/9/9/9/4K4 b G", "G*4b"),
    ("飛車を打って成る", "4k4/3n5/4G4/9/9/9/9/9/4K4 b R", "R*5b 5a4a 5b4b+"),
    ("金を捨てて角", "7k1/8n/5G3/9/9/9/9/9/4K4 b BG", "G*3b 2a1a B*2b"),
    ("角の利きを使う", "6l2/6k2/9/9/4B4/9/9/9/4K4 b 2G", "G*3c 3b2a 3c2b"),
    ("飛車と角", "4k4/9/5B3/9/9/9/9/9/4K4 b R", "R*5b 5a4a 5b3b+ 4a5a 3b5b"),
    ("馬を作る", "9/5B1k1/5G3/9/9/9/9/9/4K4 b R", "4b3c+ 2b2a 4c3b 2a1b 3c2b"),
    ("端に追う", "9/1k7/1n7/2+S6/9/9/9/9/4K4 b GS", "S*7c 8b9b G*8b 9b9c 7d8d"),
]

sys.setrecursionlimit(10_000)               # 探索の再帰は手数の 2 倍ほど。既定の 1000 でも足りるが、余裕を持たせておく

# Zobrist ハッシュ。マス×駒、持ち駒の枚数、手番、それぞれに 64 ビットの乱数を割り当てて XOR で局面を 1 つの数に
_zobrist_rng = random.Random(20260907)      # 種を固定して、いつ動かしても同じ表になるように


class Piece(IntFlag):
    """駒。種類は 1 ビットずつ、それに PROMOTED（成り）と GOTE（後手）のビットを重ねる。"""

    NONE = 0
    FU = 1                                                  # 歩
    KY = 2                                                  # 香
    KE = 4                                                  # 桂
    GI = 8                                                  # 銀
    KI = 16                                                 # 金
    KA = 32                                                 # 角
    HI = 64                                                 # 飛
    OU = 128                                                # 玉
    PROMOTED = 256
    GOTE = 512


KINDS = [Piece.FU, Piece.KY, Piece.KE, Piece.GI, Piece.KI, Piece.KA, Piece.HI, Piece.OU]
KANJI = {Piece.FU: "歩", Piece.KY: "香", Piece.KE: "桂", Piece.GI: "銀", Piece.KI: "金", Piece.KA: "角", Piece.HI: "飛", Piece.OU: "玉"}
PROMOTED_KANJI = {Piece.FU: "と", Piece.KY: "杏", Piece.KE: "圭", Piece.GI: "全", Piece.KA: "馬", Piece.HI: "龍"}
SFEN_LETTER = {Piece.FU: "P", Piece.KY: "L", Piece.KE: "N", Piece.GI: "S", Piece.KI: "G", Piece.KA: "B", Piece.HI: "R", Piece.OU: "K"}
LETTER_KIND = {v: k for k, v in SFEN_LETTER.items()}
HAND_ORDER = [Piece.HI, Piece.KA, Piece.KI, Piece.GI, Piece.KE, Piece.KY, Piece.FU]   # 持ち駒を並べる順（大きい駒から）
ALL_PIECES = [kind | flags for kind in KINDS for flags in (Piece.NONE, Piece.PROMOTED, Piece.GOTE, Piece.PROMOTED | Piece.GOTE)]

# 表示用の変換表。半角数字 → 全角、段の数字 → 漢数字
ZENKAKU = str.maketrans("123456789", "１２３４５６７８９")
RANK_KANJI = str.maketrans("123456789", "一二三四五六七八九")
USI_RANKS = "abcdefghi"                     # USI の段。a が一段目


def kind_of(piece: Piece) -> Piece:
    """種類だけ（成りと後手のビットを落とす）。"""
    return Piece(piece & 255)


def color_of(piece: Piece) -> str:
    return GOTE if Piece.GOTE in piece else SENTE


def other(color: str) -> str:
    return GOTE if color == SENTE else SENTE


def kanji_of(piece: Piece) -> str:
    kind = kind_of(piece)
    return PROMOTED_KANJI[kind] if Piece.PROMOTED in piece else KANJI[kind]


class Square(NamedTuple):
    """マス。file は 1〜9（右から左へ）、rank は 1〜9（上から下へ、先手から見て）。７六 は Square(7, 6)。"""

    file: int
    rank: int

    @property
    def on_board(self) -> bool:
        return 1 <= self.file <= 9 and 1 <= self.rank <= 9

    @property
    def usi(self) -> str:
        """USI の "7f"。"""
        return f"{self.file}{USI_RANKS[self.rank - 1]}"

    def __str__(self) -> str:
        """日本語の "７六"。"""
        return str(self.file).translate(ZENKAKU) + str(self.rank).translate(RANK_KANJI)

    @classmethod
    def parse(cls, text: str) -> "Square":
        """"7f" → Square(7, 6)。"""
        return cls(int(text[0]), USI_RANKS.index(text[1]) + 1)

    def shift(self, dx: int, dy: int) -> "Square":
        return Square(self.file + dx, self.rank + dy)


ZOBRIST_SQUARE = {(Square(f, r), piece): _zobrist_rng.getrandbits(64)
                  for f in range(1, 10) for r in range(1, 10) for piece in ALL_PIECES}
ZOBRIST_HAND = {(color, kind, n): _zobrist_rng.getrandbits(64)
                for color in (SENTE, GOTE) for kind in HAND_ORDER for n in range(1, 19)}
ZOBRIST_GOTE_TURN = _zobrist_rng.getrandbits(64)


class Move(NamedTuple):
    """1 手。盤上の駒を動かす（src あり）か、持ち駒を打つ（drop あり）。promote は成るかどうか。"""

    dst: Square
    src: Square | None = None
    promote: bool = False
    drop: Piece = Piece.NONE

    @property
    def usi(self) -> str:
        """USI の "7g7f" / "2b3c+" / "P*5e"。"""
        if self.src is None:
            return f"{SFEN_LETTER[self.drop]}*{self.dst.usi}"
        return self.src.usi + self.dst.usi + ("+" if self.promote else "")

    @classmethod
    def parse(cls, text: str) -> "Move":
        if "*" in text:
            letter, dst = text.split("*")
            return cls(Square.parse(dst), drop=LETTER_KIND[letter.upper()])
        return cls(Square.parse(text[2:4]), Square.parse(text[:2]), text.endswith("+"))


# 駒の動き（先手から見て。dy が -1 なら前）。後手は dy を反転する
GOLD_STEPS = [(0, -1), (-1, -1), (1, -1), (-1, 0), (1, 0), (0, 1)]
ORTHOGONAL = [(0, -1), (0, 1), (-1, 0), (1, 0)]
DIAGONAL = [(-1, -1), (1, -1), (-1, 1), (1, 1)]
STEPS = {
    Piece.FU: [(0, -1)],
    Piece.KE: [(-1, -2), (1, -2)],
    Piece.GI: [(0, -1), (-1, -1), (1, -1), (-1, 1), (1, 1)],
    Piece.KI: GOLD_STEPS,
    Piece.OU: ORTHOGONAL + DIAGONAL,
}
RAYS = {Piece.KY: [(0, -1)], Piece.KA: DIAGONAL, Piece.HI: ORTHOGONAL}


def movement(piece: Piece) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """その駒の (1 歩の向き, 走る向き)。成り駒は金の動きか、角・飛に 1 歩を足したもの。"""
    kind = kind_of(piece)
    if Piece.PROMOTED in piece:
        if kind == Piece.KA:
            steps, rays = ORTHOGONAL, DIAGONAL
        elif kind == Piece.HI:
            steps, rays = DIAGONAL, ORTHOGONAL
        else:
            steps, rays = GOLD_STEPS, []
    else:
        steps, rays = STEPS.get(kind, []), RAYS.get(kind, [])
    if Piece.GOTE in piece:
        steps = [(dx, -dy) for dx, dy in steps]
        rays = [(dx, -dy) for dx, dy in rays]
    return steps, rays


class Board:
    """盤と持ち駒と手番。駒のあるマスだけ {Square: Piece} で持つ。"""

    __slots__ = ("pieces", "hands", "turn")                 # 属性はこの 3 つだけ。打ち間違いを AttributeError にする

    def __init__(self, pieces: dict[Square, Piece], hands: dict[str, dict[Piece, int]] | None = None, turn: str = SENTE):
        self.pieces = pieces
        self.hands = hands or {SENTE: {}, GOTE: {}}
        self.turn = turn

    @classmethod
    def from_sfen(cls, sfen: str) -> "Board":
        """SFEN（一段目から順に、数字は空きマスの数、+ は成り、大文字が先手）を読む。"""
        rows, turn, hand_text = sfen.split()[:3]
        pieces: dict[Square, Piece] = {}
        for rank, row in enumerate(rows.split("/"), 1):
            file = 9
            promoted = False
            for ch in row:
                if ch.isdigit():
                    file -= int(ch)
                elif ch == "+":
                    promoted = True
                else:
                    piece = LETTER_KIND[ch.upper()] | (Piece.GOTE if ch.islower() else Piece.NONE) | (Piece.PROMOTED if promoted else Piece.NONE)
                    pieces[Square(file, rank)] = piece
                    file -= 1
                    promoted = False
        hands: dict[str, dict[Piece, int]] = {SENTE: {}, GOTE: {}}
        count = 0
        for ch in hand_text if hand_text != "-" else "":
            if ch.isdigit():
                count = count * 10 + int(ch)
            else:
                hands[GOTE if ch.islower() else SENTE][LETTER_KIND[ch.upper()]] = max(1, count)
                count = 0
        return cls(pieces, hands, turn)

    @property
    def sfen(self) -> str:
        rows = []
        for rank in range(1, 10):
            row = ""
            empty = 0
            for file in range(9, 0, -1):
                piece = self.pieces.get(Square(file, rank))
                if piece is None:
                    empty += 1
                    continue
                letter = SFEN_LETTER[kind_of(piece)]
                text = ("+" if Piece.PROMOTED in piece else "") + (letter.lower() if Piece.GOTE in piece else letter)
                row += (str(empty) if empty else "") + text
                empty = 0
            rows.append(row + (str(empty) if empty else ""))
        hand = ""
        for color in (SENTE, GOTE):
            for kind in HAND_ORDER:
                n = self.hands[color].get(kind, 0)
                if n:
                    letter = SFEN_LETTER[kind]
                    hand += (str(n) if n > 1 else "") + (letter.lower() if color == GOTE else letter)
        return f"{'/'.join(rows)} {self.turn} {hand or '-'} 1"

    def __getitem__(self, key: "Square | str") -> Piece | None:
        """board["7g"] でも board[Square(7, 7)] でも。空きマスは None。"""
        if isinstance(key, str):
            key = Square.parse(key)
        return self.pieces.get(key)

    def __setitem__(self, key: "Square | str", piece: Piece | None) -> None:
        if isinstance(key, str):
            key = Square.parse(key)
        if piece is None:
            self.pieces.pop(key, None)
        else:
            self.pieces[key] = piece

    def __iter__(self):
        yield from self.pieces.items()

    def copy(self) -> "Board":
        return Board(dict(self.pieces), {c: dict(h) for c, h in self.hands.items()}, self.turn)

    def king_square(self, color: str) -> Square | None:
        king = Piece.OU | (Piece.GOTE if color == GOTE else Piece.NONE)
        return next((sq for sq, piece in self if piece == king), None)

    def zobrist(self) -> int:
        """局面のハッシュ。同じ配置・持ち駒・手番なら同じ数（千日手の判定に使う）。"""
        key = ZOBRIST_GOTE_TURN if self.turn == GOTE else 0
        for square, piece in self.pieces.items():
            key ^= ZOBRIST_SQUARE[square, piece]
        for color, hand in self.hands.items():
            for kind, n in hand.items():
                key ^= ZOBRIST_HAND[color, kind, n]
        return key

    def do(self, move: Move) -> tuple[Piece | None, Piece | None]:
        """その場で指す（盤を書き換える）。戻すための (取った駒, 動かす前の駒) を返す。"""
        color = self.turn
        if move.src is None:
            piece, captured, before = move.drop | (Piece.GOTE if color == GOTE else Piece.NONE), None, None
            self.hands[color][move.drop] -= 1
            if self.hands[color][move.drop] == 0:
                del self.hands[color][move.drop]
        else:
            before = self.pieces.pop(move.src)
            captured = self.pieces.get(move.dst)
            if captured is not None:
                assert color_of(captured) != color, "自分の駒は取れない"
                kind = kind_of(captured)
                self.hands[color][kind] = self.hands[color].get(kind, 0) + 1
            piece = before | Piece.PROMOTED if move.promote else before
        self.pieces[move.dst] = piece
        self.turn = other(color)
        return captured, before

    def undo(self, move: Move, captured: Piece | None, before: Piece | None) -> None:
        """do() を元に戻す。"""
        color = other(self.turn)
        del self.pieces[move.dst]
        if move.src is None:
            self.hands[color][move.drop] = self.hands[color].get(move.drop, 0) + 1
        else:
            self.pieces[move.src] = before
            if captured is not None:
                self.pieces[move.dst] = captured
                kind = kind_of(captured)
                self.hands[color][kind] -= 1
                if self.hands[color][kind] == 0:
                    del self.hands[color][kind]
        self.turn = color

    def hand_text(self, color: str) -> str:
        parts = [KANJI[kind] + (str(n) if n > 1 else "") for kind in HAND_ORDER if (n := self.hands[color].get(kind, 0))]
        return " ".join(parts) if parts else "なし"

    def __str__(self) -> str:
        lines = [f"☖持ち駒: {self.hand_text(GOTE)}", "  ９ ８ ７ ６ ５ ４ ３ ２ １"]
        for rank in range(1, 10):
            cells = []
            for file in range(9, 0, -1):
                piece = self.pieces.get(Square(file, rank))
                if piece is None:
                    cells.append(" ・")
                else:
                    cells.append(("v" if Piece.GOTE in piece else " ") + kanji_of(piece))
            lines.append("".join(cells) + " " + str(rank).translate(RANK_KANJI))
        lines.append(f"☗持ち駒: {self.hand_text(SENTE)}")
        return "\n".join(lines)


@contextmanager
def trying(board: Board, move: Move):
    """with trying(board, move): の中だけ指した局面になり、抜けると必ず戻る。"""
    captured, before = board.do(move)
    try:
        yield board
    finally:
        board.undo(move, captured, before)


def attacked(board: Board, square: Square, by: str) -> bool:
    """by 側の駒が square を取れるか（王手の判定に使う）。"""
    for src, piece in board.pieces.items():
        if color_of(piece) != by:
            continue
        steps, rays = movement(piece)
        if any(src.shift(dx, dy) == square for dx, dy in steps):
            return True
        for dx, dy in rays:
            sq = src.shift(dx, dy)
            while sq.on_board:
                if sq == square:
                    return True
                if board[sq] is not None:
                    break
                sq = sq.shift(dx, dy)
    return False


def in_check(board: Board, color: str | None = None) -> bool:
    """color（省略なら手番）の玉に王手がかかっているか。"""
    color = color or board.turn
    king = board.king_square(color)
    return king is not None and attacked(board, king, other(color))


def promotion_zone(color: str, square: Square) -> bool:
    """敵陣（先手なら一〜三段目）か。"""
    return square.rank <= 3 if color == SENTE else square.rank >= 7


def must_promote(piece: Piece, dst: Square) -> bool:
    """行き所のない駒になるなら成らないといけない。歩・香は最終段、桂は 2 段目まで。"""
    kind = kind_of(piece)
    last = 1 if color_of(piece) == SENTE else 9
    if kind in (Piece.FU, Piece.KY):
        return dst.rank == last
    if kind == Piece.KE:
        return abs(dst.rank - last) <= 1
    return False


def can_promote(piece: Piece, src: Square, dst: Square) -> bool:
    """成れるか。金と玉と成り駒は成れない。出発か到着が敵陣なら成れる。"""
    if Piece.PROMOTED in piece or kind_of(piece) in (Piece.KI, Piece.OU):
        return False
    color = color_of(piece)
    return promotion_zone(color, src) or promotion_zone(color, dst)


def moves_from(board: Board, src: Square) -> list[Move]:
    """src の駒が動ける手。成れるときは成る手と成らない手の両方（成らないと行き所がないなら成る手だけ）。"""
    piece = board[src]
    color = color_of(piece)
    steps, rays = movement(piece)
    targets = [src.shift(dx, dy) for dx, dy in steps]
    for dx, dy in rays:
        sq = src.shift(dx, dy)
        while sq.on_board:
            targets.append(sq)
            if board[sq] is not None:
                break
            sq = sq.shift(dx, dy)
    moves = []
    for dst in targets:
        if not dst.on_board or (board[dst] is not None and color_of(board[dst]) == color):
            continue
        if can_promote(piece, src, dst):
            moves.append(Move(dst, src, True))
            if not must_promote(piece, dst):
                moves.append(Move(dst, src, False))
        else:
            moves.append(Move(dst, src))
    return moves


def drops(board: Board, color: str | None = None) -> list[Move]:
    """持ち駒を打つ手。二歩と、行き所のないマス（歩・香の最終段、桂の 2 段目まで）は除く。打ち歩詰めは legal_moves で外す。"""
    color = color or board.turn
    empties = [Square(f, r) for f, r in product(range(1, 10), range(1, 10)) if Square(f, r) not in board.pieces]
    own_pawn = Piece.FU | (Piece.GOTE if color == GOTE else Piece.NONE)
    pawn_files = {sq.file for sq, piece in board.pieces.items() if piece == own_pawn}   # 自分の歩がある筋（二歩）
    moves = []
    for kind in HAND_ORDER:
        if not board.hands[color].get(kind, 0):
            continue
        piece = kind | (Piece.GOTE if color == GOTE else Piece.NONE)
        for sq in empties:
            if must_promote(piece, sq):                     # 打った瞬間に動けない
                continue
            if kind == Piece.FU and sq.file in pawn_files:
                continue
            moves.append(Move(sq, drop=kind))
    return moves


def all_moves(board: Board, color: str | None = None) -> list[Move]:
    """color（省略なら手番）の指せる手を全部。動かす手と打つ手。"""
    color = color or board.turn
    moving = [move for sq, piece in sorted(board.pieces.items()) if color_of(piece) == color for move in moves_from(board, sq)]   # マス順に。do/undo で辞書の順が変わっても手の順が同じになるように
    return moving + drops(board, color)


def legal_moves(board: Board) -> list[Move]:
    """手番の合法手。王手放置（指した後に自分の玉が取られる）と打ち歩詰めを外す。"""
    color = board.turn
    moves = []
    for move in all_moves(board):
        with trying(board, move):
            if in_check(board, color):
                continue
            if move.drop == Piece.FU and in_check(board) and not any_escape(board):
                continue                                    # 打ち歩詰め
            moves.append(move)
    return moves


def any_escape(board: Board) -> bool:
    """手番に、王手を逃れる手が 1 つでもあるか（打ち歩詰めの判定用。全部は数えない）。"""
    color = board.turn
    for move in all_moves(board):
        with trying(board, move):
            if not in_check(board, color):
                return True
    return False


def make_move(board: Board, move: Move) -> Board:
    """指した後の盤を新しく作って返す（元の盤は変えない）。取った駒は成りを解いて持ち駒に。"""
    new = board.copy()
    color = board.turn
    if move.src is None:
        piece = move.drop | (Piece.GOTE if color == GOTE else Piece.NONE)
        new.hands[color][move.drop] -= 1
        if new.hands[color][move.drop] == 0:
            del new.hands[color][move.drop]
    else:
        piece = new[move.src]
        new[move.src] = None
        captured = new[move.dst]
        if captured is not None:
            kind = kind_of(captured)
            new.hands[color][kind] = new.hands[color].get(kind, 0) + 1
        if move.promote:
            piece |= Piece.PROMOTED
    new[move.dst] = piece
    new.turn = other(color)
    return new


def describe(board: Board, move: Move) -> str:
    """指す前の盤で、手を日本語に。☗７六歩、☖３四歩、☗２二角成、☗５五角打。"""
    mark = "☗" if board.turn == SENTE else "☖"
    if move.src is None:
        return f"{mark}{move.dst}{KANJI[move.drop]}打"
    piece = board[move.src]
    return f"{mark}{move.dst}{kanji_of(piece)}" + ("成" if move.promote else "")


def count_moves(board: Board, depth: int) -> int:
    """depth 手先までの手の組み合わせの数（perft）。動きの実装を数で検証するための関数。"""
    if depth == 0:
        return 1
    total = 0
    for move in legal_moves(board):
        with trying(board, move):
            total += count_moves(board, depth - 1)
    return total


def tsume_board(sfen: str) -> Board:
    """詰将棋の局面。盤と攻め方の持ち駒を読み、受け方の持ち駒は残り全部にする。"""
    board = Board.from_sfen(sfen + " 1" if len(sfen.split()) == 3 else sfen)
    remaining = {LETTER_KIND[letter]: n for letter, n in FULL_SET.items()}
    for piece in board.pieces.values():
        if kind_of(piece) != Piece.OU:
            remaining[kind_of(piece)] -= 1
    for kind, n in board.hands[SENTE].items():
        remaining[kind] -= n
    board.hands[GOTE] = {kind: n for kind, n in remaining.items() if n > 0}
    board.turn = SENTE
    return board


def attacks(board: Board, src: Square, target: Square) -> bool:
    """src の駒の利きが target に届くか。"""
    steps, rays = movement(board[src])
    if any(src.shift(dx, dy) == target for dx, dy in steps):
        return True
    for dx, dy in rays:
        sq = src.shift(dx, dy)
        while sq.on_board:
            if sq == target:
                return True
            if board[sq] is not None:
                break
            sq = sq.shift(dx, dy)
    return False


def between(a: Square, b: Square) -> list[Square]:
    """a と b が同じ筋・段・斜めにあるとき、その間のマス（両端は含まない）。"""
    dx, dy = b.file - a.file, b.rank - a.rank
    if not (dx == 0 or dy == 0 or abs(dx) == abs(dy)):
        return []
    sx, sy = (dx > 0) - (dx < 0), (dy > 0) - (dy < 0)
    squares = []
    sq = a.shift(sx, sy)
    while sq != b:
        squares.append(sq)
        sq = sq.shift(sx, sy)
    return squares


def evasions(board: Board) -> list[Move]:
    """王手を受ける手だけ。玉を動かす、王手している駒を取る、間に駒を入れる（合駒）。王手でなければ合法手全部。"""
    color = board.turn
    king = board.king_square(color)
    attackers = [sq for sq, piece in board.pieces.items() if color_of(piece) != color and attacks(board, sq, king)]
    if not attackers:
        return legal_moves(board)
    candidates = moves_from(board, king)
    if len(attackers) == 1:                                 # 両王手なら玉を動かすしかない
        target = attackers[0]
        blocks = set(between(king, target))
        for sq, piece in sorted(board.pieces.items()):
            if color_of(piece) == color and sq != king:
                candidates += [m for m in moves_from(board, sq) if m.dst == target or m.dst in blocks]
        candidates += [m for m in drops(board) if m.dst in blocks]
    moves = []
    for move in candidates:
        with trying(board, move):
            if not in_check(board, color):
                moves.append(move)
    return moves


def check_moves(board: Board) -> Iterator[Move]:
    """攻め方の手のうち、王手になるものだけ。"""
    for move in legal_moves(board):
        with trying(board, move):
            gives_check = in_check(board)
        if gives_check:                                         # with を抜けてから yield する（中で yield すると盤が指したままになる）
            yield move


class SearchLimit(Exception):
    """調べる局面の数が上限を超えた。"""


@dataclass(slots=True)
class Solver:
    """深さを限った全探索の詰将棋ソルバー。攻め方は王手だけ、受け方は王手を受ける手だけ。"""

    nodes: int = 0                                          # 調べた局面の数
    seconds: float = 0.0
    max_nodes: int | None = None                            # 超えたら SearchLimit（ブラウザで固まらないように）

    def visit(self) -> None:
        self.nodes += 1
        if self.max_nodes is not None and self.nodes > self.max_nodes:
            raise SearchLimit(self.nodes)

    def solve(self, board: Board, max_depth: int = MAX_TSUME_DEPTH) -> list[Move] | None:
        """1 手詰、3 手詰、… と手数を増やして、最初に見つかった手順（最も長く粘る受けに対するもの）を返す。"""
        start = time.perf_counter()
        try:
            for depth in range(1, max_depth + 1, 2):
                line = next(self.mates(board, depth), None)
                if line is not None:
                    return line
            return None
        finally:
            self.seconds += time.perf_counter() - start

    def mates(self, board: Board, depth: int) -> Iterator[list[Move]]:
        """攻め方の手番。depth 手以内に詰む手順を、見つかるたびに yield する（2 つ以上あれば余詰）。"""
        self.visit()
        if depth < 1:
            return
        for move in check_moves(board):
            with trying(board, move):
                line = self.defend(board, depth - 1)
            if line is not None:
                yield [move, *line]

    def defend(self, board: Board, depth: int) -> list[Move] | None:
        """受け方の手番。どう受けても depth 手以内に詰むなら、最も長く粘る受けからの手順を返す。1 つでも逃れられれば None。"""
        self.visit()
        replies = evasions(board)
        if not replies:
            return []                                       # 手がない = 詰み
        if depth < 1:
            return None
        longest: list[Move] | None = None
        for reply in replies:
            with trying(board, reply):
                line = next(self.mates(board, depth - 1), None)
            if line is None:
                return None
            if longest is None or len(line) > len(longest) - 1:
                longest = [reply, *line]
        return longest

    def extra_solutions(self, board: Board, depth: int) -> bool:
        """余詰があるか（初手が違う手順が 2 つ以上）。"""
        firsts = {line[0] for line in islice(self.mates(board, depth), 2)}
        return len(firsts) >= 2


def line_text(board: Board, line: list[Move]) -> str:
    """手順を日本語で。指す前の盤が要るので、順に指しながら作る。"""
    board = board.copy()
    parts = []
    for move in line:
        parts.append(describe(board, move))
        board = make_move(board, move)
    return " ".join(parts)


class Game:
    """対局 1 回ぶん。盤・履歴・結果。表示と入力は持たない。"""

    def __init__(self, cpu: str | None = None, seed: int | None = None, sfen: str = START_SFEN, tsume: str | None = None): # ←
        self.rng = random.Random(seed)
        self.answer = [Move.parse(u) for u in tsume.split()] if tsume else []   # 詰将棋の答えの手順 # ←
        self.tsume = len(self.answer)                               # 詰将棋なら手数（0 なら普通の対局） # ←
        self.board = tsume_board(sfen) if tsume else Board.from_sfen(sfen) # ←
        self.history: list[tuple[Board, Move]] = []                # (指す前の盤, 手)
        self.cpu = cpu                                              # CPU が持つ側。None なら 2 人
        self.result: str | None = None
        self.seen: dict[int, int] = {self.board.zobrist(): 1}       # 局面のハッシュ → 出た回数（千日手）
        self.checks: list[bool] = []                                # 各手が王手だったか（連続王手の千日手）
        self.recent: deque[str] = deque(maxlen=6)                   # 直前の手の日本語表記。古いものから消える

    @property
    def legal_moves(self) -> list[Move]:
        if self.tsume and self.board.turn == SENTE: # ←
            return list(check_moves(self.board))                    # 詰将棋の攻め方は王手だけ
        return legal_moves(self.board)

    @property
    def on_track(self) -> bool:             # ←
        """ここまで答えの手順どおりか。"""
        return [move for _, move in self.history] == self.answer[:len(self.history)]

    @property
    def hint(self) -> Move | None:          # ←
        """詰将棋で、次の一手。答えの手順から外れていたら、上限つきで探し直す。"""
        if not self.tsume or self.result is not None:
            return None
        if self.on_track:                   # ←
            return self.answer[len(self.history)]
        try:
            line = Solver(max_nodes=HINT_NODES).solve(self.board.copy(), self.tsume - len(self.history))
        except SearchLimit:
            return None
        return line[0] if line else None

    @property
    def in_check(self) -> bool:
        return in_check(self.board)

    @property
    def last_move(self) -> Move | None:
        return self.history[-1][1] if self.history else None

    def play(self, move: Move) -> bool:
        """1 手指す。指せない手なら False。詰み・指せる手なし・千日手で終わる。"""
        if self.result is not None or move not in self.legal_moves:
            return False
        self.recent.append(describe(self.board, move))
        self.history.append((self.board, move))
        self.board = make_move(self.board, move)
        self.checks.append(in_check(self.board))
        key = self.board.zobrist()
        self.seen[key] = self.seen.get(key, 0) + 1
        self.result = self.judge(key)
        return True

    def judge(self, key: int) -> str | None:
        """指した直後の結果。手番側に手がなければ負け（王手なら詰み）。同じ局面 4 回で千日手。詰将棋は手数を超えたら失敗。"""
        mover = other(self.board.turn)
        if self.tsume and self.board.turn == SENTE and (len(self.history) >= self.tsume or not self.legal_moves): # ←
            return "tsume-fail"                                     # 手数いっぱい、または王手が続かない
        if not self.legal_moves:
            return mover if self.in_check else f"{'sente' if mover == SENTE else 'gote'}-stalemate"
        if self.seen[key] >= REPETITIONS:
            # 初めてこの局面になってからの手を見て、片方がずっと王手なら、その側の負け
            first = next(i for i, (board, _) in enumerate(self.history) if board.zobrist() == key)
            since = self.checks[first:]
            for color, offset in ((SENTE, 0), (GOTE, 1)):
                own = [c for i, c in enumerate(since) if (first + i) % 2 == offset]   # その側が指した手だけ
                if own and all(own):
                    return f"{'gote' if color == SENTE else 'sente'}-perpetual"
            return "repetition"
        return None

    def undo(self) -> bool:
        """1 手戻す。CPU 相手なら 2 手（自分の番まで）。"""
        if not self.history:
            return False
        steps = 2 if self.cpu and len(self.history) >= 2 else 1
        for _ in range(steps):
            self.seen[self.board.zobrist()] -= 1
            self.board, _ = self.history.pop()
            self.checks.pop()
            if self.recent:
                self.recent.pop()
        self.result = None
        return True

    def cpu_move(self) -> Move | None:
        if self.result is not None or self.board.turn != self.cpu:
            return None
        if self.tsume:                      # ←
            move = self.best_defense()
        else:
            move = self.rng.choice(self.legal_moves)
        self.play(move)
        return move

    def best_defense(self) -> Move:         # ←
        """受け方の手。答えの手順どおりなら答えの受け。外れていたら、残りの手数で詰まされない手を探す（上限つき）。"""
        if self.on_track:
            return self.answer[len(self.history)]
        remaining = self.tsume - len(self.history)
        solver = Solver(max_nodes=HINT_NODES)
        replies = evasions(self.board)
        try:
            for reply in replies:
                with trying(self.board, reply):
                    escaped = next(solver.mates(self.board, remaining - 1), None) is None
                if escaped:
                    return reply                                    # 詰まされない受け
            line = solver.defend(self.board.copy(), remaining)
            return line[0] if line else replies[0]                  # 全部詰むなら最も粘る受け
        except SearchLimit:
            return replies[0]

    def render(self) -> str:
        turn = "先手" if self.board.turn == SENTE else "後手"
        check = "   王手！" if self.in_check and self.result is None else ""
        recent = f"   {' '.join(self.recent)}" if self.recent else ""
        return f"{self.board}\n\n{len(self.history) + 1} 手目 {turn}の番{check}{recent}\n"


def main():
    parser = argparse.ArgumentParser(description="将棋（詰将棋）")
    parser.add_argument("--tsume", type=int, nargs="?", const=0, metavar="N", help="詰将棋。番号なしで問題集を出す。N で N 番を自分で解く") # ←
    parser.add_argument("--solve", type=int, metavar="N", help="N 番をソルバーが解いて終わる（0 で全部）")
    parser.add_argument("--cpu", choices=[SENTE, GOTE], help="この側をランダム CPU に任せる（b 先手 / w 後手）")
    parser.add_argument("--sfen", default=START_SFEN, help="開始局面（SFEN）")
    parser.add_argument("--moves", metavar="SQ", help="そのマスの駒が動ける手を出して終わる（7g など）")
    parser.add_argument("--perft", type=int, metavar="N", help="N 手先までの手の数を出して終わる")
    args = parser.parse_args()

    if args.tsume == 0 and args.solve is None:
        for i, (title, sfen, answer) in enumerate(PROBLEMS, 1):
            print(f"{i}. {title}（{len(answer.split())} 手詰）")
        print("\npython3 main.py --tsume 番号 で解く。--solve 番号 で答えを見る。")
        return
    if args.solve is not None:
        targets = PROBLEMS if args.solve == 0 else [PROBLEMS[args.solve - 1]]
        for title, sfen, answer in targets:
            board = tsume_board(sfen)
            solver = Solver()
            line = solver.solve(board.copy())
            print(board)
            found = f"{line_text(board, line)}（{len(line)} 手詰）" if line else "詰みません"
            extra = "　余詰あり" if line and solver.extra_solutions(board.copy(), len(line)) else ""
            same = "" if line and " ".join(m.usi for m in line) == answer else "　※ 答えと違う"
            print(f"\n{title}: {found}{extra}{same}   {solver.nodes} 局面 {solver.seconds:.2f} 秒\n")
        return

    board = Board.from_sfen(args.sfen)
    if args.moves:
        src = Square.parse(args.moves)
        print(board)
        print(f"\n{src}{kanji_of(board[src]) if board[src] else '（空）'} の手: " + " ".join(describe(board, m) for m in moves_from(board, src)) if board[src] else "駒がありません")
        return
    if args.perft:
        for depth in range(1, args.perft + 1):
            print(f"{depth} 手: {count_moves(board, depth)}")
        return

    if args.tsume:                          # ←
        title, sfen, answer = PROBLEMS[args.tsume - 1]
        game = Game(cpu=GOTE, sfen=sfen, tsume=answer)
        print(f"{title}（{game.tsume} 手詰）。王手を続けて詰ませる。hint で次の一手、undo で戻す、q でやめる。\n")
    else:
        game = Game(cpu=args.cpu, sfen=args.sfen)
        print("7g7f のように指す（USI）。成るときは 2b3c+、打つときは P*5e。undo で戻す、q でやめる。\n")

    while game.result is None:
        print(game.render())
        if game.board.turn == game.cpu:
            before = game.board
            move = game.cpu_move()
            print(f"CPU: {describe(before, move)}\n")
            continue
        text = input("> ").strip()
        if text == "q":
            game.result = "quit"
        elif text == "undo":
            game.undo()
        elif text == "hint" and game.tsume: # ←
            move = game.hint
            print(f"次の一手: {describe(game.board, move) if move else 'ありません'}\n")
        else:
            try:
                move = Move.parse(text)
            except (ValueError, IndexError, KeyError):
                print("7g7f の形で入力してください。\n")
                continue
            if not game.play(move):
                print(f"{text} は指せません。\n")

    print(game.render())
    if game.tsume and game.result == SENTE: # ←
        print(f"詰みました！ {len(game.history)} 手")
    else:
        print(RESULT_TEXT[game.result])


if __name__ == "__main__":
    main()
