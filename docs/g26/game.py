"""チェスの棋譜（ブラウザ版）

CLI 版（g26-chess-pgn/main.py）とルールも CPU も棋譜の読み書きもまったく同じ。
定数と Square / Move / Board、ray() 〜 count_moves()、そして class Game を、
ステップの目印コメント（# ←）を外しただけで 1 文字も変えずに持ってきている。

持ってこなかったのは Board.__str__ を使う Game.render() と Game.save() / load()、perft_table() / replay() / main() だけ。
出口は 64 個の <div> と、PGN の <textarea>。貼り付けた PGN は Game.from_pgn() でそのまま読む。
"""

import asyncio
import math
import random
import re
import textwrap
import time
from collections import Counter
from datetime import date
from dataclasses import dataclass, field, replace
from functools import cached_property, lru_cache
from typing import NamedTuple

from pyscript import document, when


# --- ここから class Game まで、CLI 版（g26-chess-pgn/main.py）からそのまま ---


FILES = "abcdefgh"                          # 筋（左から）
RANKS = "12345678"                          # 段（下から）
START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
FIFTY_MOVE_PLIES = 100                      # ポーンも取る手も無いまま 100 手（50 手ずつ）で引き分け
REPETITIONS = 3                             # 同じ局面がこの回数で千日手
THINK_SECONDS = 1.0                         # CPU が考える時間（反復深化の上限）
MATE = 100000                               # メイトの点。手数が短いほど大きくする
WHITE = "w"
BLACK = "b"


PIECE_NAMES = {"K": "キング", "Q": "クイーン", "R": "ルーク", "B": "ビショップ", "N": "ナイト", "P": "ポーン"}


KNIGHT_JUMPS = [(1, 2), (2, 1), (2, -1), (1, -2), (-1, -2), (-2, -1), (-2, 1), (-1, 2)]
KING_STEPS = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)]
ROOK_DIRS = [(1, 0), (-1, 0), (0, 1), (0, -1)]
BISHOP_DIRS = [(1, 1), (1, -1), (-1, 1), (-1, -1)]


RESULT_TEXT = {
    WHITE: "白の勝ち（チェックメイト）",
    BLACK: "黒の勝ち（チェックメイト）",
    "stalemate": "ステイルメイト。引き分け",
    "repetition": "千日手（同じ局面が 3 回）。引き分け",
    "fifty": "50 手ルール（ポーンも取る手も無いまま 50 手）。引き分け",
    "material": "駒不足（どちらもチェックメイトできない）。引き分け",
    "quit": "やめました。",
}


RESULT_TOKENS = {WHITE: "1-0", BLACK: "0-1", "stalemate": "1/2-1/2", "repetition": "1/2-1/2",
                 "fifty": "1/2-1/2", "material": "1/2-1/2", "quit": "*", None: "*"}


SAN_PATTERN = re.compile(r"""
    ^(?P<piece>[KQRBN])?        # 駒。無ければポーン
    (?P<from_file>[a-h])?       # 同じ駒が 2 つ行けるときの、元の筋
    (?P<from_rank>[1-8])?       # 元の段
    (?P<capture>x)?             # 取る手
    (?P<to>[a-h][1-8])          # 行き先
    (?:=(?P<promotion>[QRBN]))? # 成る駒
    (?P<check>[+#])?$           # チェック / メイト
""", re.VERBOSE)


COORD_PATTERN = re.compile(r"^[a-h][1-8][a-h][1-8][qrbn]?$")   # e2e4 形式


PGN_TAG = re.compile(r'\[(?P<key>\w+)\s+"(?P<value>[^"]*)"\]')   # [Event "..."]


PGN_NOISE = re.compile(r"\{[^}]*\}|;[^\n]*|\d+\.(?:\.\.)?|\$\d+")   # コメント、手数、注釈記号


PIECE_VALUES = {"P": 100, "N": 320, "B": 330, "R": 500, "Q": 900, "K": 0}


PST = {
    "P": [0, 0, 0, 0, 0, 0, 0, 0,
          50, 50, 50, 50, 50, 50, 50, 50,
          10, 10, 20, 30, 30, 20, 10, 10,
          5, 5, 10, 25, 25, 10, 5, 5,
          0, 0, 0, 20, 20, 0, 0, 0,
          5, -5, -10, 0, 0, -10, -5, 5,
          5, 10, 10, -20, -20, 10, 10, 5,
          0, 0, 0, 0, 0, 0, 0, 0],
    "N": [-50, -40, -30, -30, -30, -30, -40, -50,
          -40, -20, 0, 0, 0, 0, -20, -40,
          -30, 0, 10, 15, 15, 10, 0, -30,
          -30, 5, 15, 20, 20, 15, 5, -30,
          -30, 0, 15, 20, 20, 15, 0, -30,
          -30, 5, 10, 15, 15, 10, 5, -30,
          -40, -20, 0, 5, 5, 0, -20, -40,
          -50, -40, -30, -30, -30, -30, -40, -50],
    "B": [-20, -10, -10, -10, -10, -10, -10, -20,
          -10, 0, 0, 0, 0, 0, 0, -10,
          -10, 0, 5, 10, 10, 5, 0, -10,
          -10, 5, 5, 10, 10, 5, 5, -10,
          -10, 0, 10, 10, 10, 10, 0, -10,
          -10, 10, 10, 10, 10, 10, 10, -10,
          -10, 5, 0, 0, 0, 0, 5, -10,
          -20, -10, -10, -10, -10, -10, -10, -20],
    "R": [0, 0, 0, 0, 0, 0, 0, 0,
          5, 10, 10, 10, 10, 10, 10, 5,
          -5, 0, 0, 0, 0, 0, 0, -5,
          -5, 0, 0, 0, 0, 0, 0, -5,
          -5, 0, 0, 0, 0, 0, 0, -5,
          -5, 0, 0, 0, 0, 0, 0, -5,
          -5, 0, 0, 0, 0, 0, 0, -5,
          0, 0, 0, 5, 5, 0, 0, 0],
    "Q": [-20, -10, -10, -5, -5, -10, -10, -20,
          -10, 0, 0, 0, 0, 0, 0, -10,
          -10, 0, 5, 5, 5, 5, 0, -10,
          -5, 0, 5, 5, 5, 5, 0, -5,
          0, 0, 5, 5, 5, 5, 0, -5,
          -10, 5, 5, 5, 5, 5, 0, -10,
          -10, 0, 5, 0, 0, 0, 0, -10,
          -20, -10, -10, -5, -5, -10, -10, -20],
    "K": [-30, -40, -40, -50, -50, -40, -40, -30,
          -30, -40, -40, -50, -50, -40, -40, -30,
          -30, -40, -40, -50, -50, -40, -40, -30,
          -30, -40, -40, -50, -50, -40, -40, -30,
          -20, -30, -30, -40, -40, -30, -30, -20,
          -10, -20, -20, -20, -20, -20, -20, -10,
          20, 20, 0, 0, 0, 0, 20, 20,
          20, 30, 10, 0, 0, 10, 30, 20],
}


class Square(NamedTuple):
    """マス。file は 0〜7（a〜h）、rank は 0〜7（1〜8）。"""

    file: int
    rank: int

    @property
    def name(self) -> str:
        return FILES[self.file] + RANKS[self.rank]

    @property
    def on_board(self) -> bool:
        return 0 <= self.file < 8 and 0 <= self.rank < 8

    @classmethod
    def parse(cls, text: str) -> "Square":
        """"e4" → Square(4, 3)。"""
        return cls(FILES.index(text[0]), RANKS.index(text[1]))

    def shift(self, df: int, dr: int) -> "Square":
        return Square(self.file + df, self.rank + dr)


class Move(NamedTuple):
    """1 手。どこからどこへ。ポーンが最終段に着くときは成る駒。"""

    src: Square
    dst: Square
    promotion: str | None = None

    def __str__(self) -> str:
        return self.src.name + self.dst.name + (self.promotion.lower() if self.promotion else "")

    @classmethod
    def parse(cls, text: str) -> "Move":
        """"e2e4" や "e7e8q" → Move。"""
        promotion = text[4].upper() if len(text) > 4 else None
        return cls(Square.parse(text[:2]), Square.parse(text[2:4]), promotion)


CASTLING_RIGHTS = {
    Square.parse("e1"): "KQ", Square.parse("a1"): "Q", Square.parse("h1"): "K",
    Square.parse("e8"): "kq", Square.parse("a8"): "q", Square.parse("h8"): "k",
}


CASTLING = {
    "K": (Square.parse("g1"), Square.parse("h1"), Square.parse("f1"), (Square.parse("f1"), Square.parse("g1"))),
    "Q": (Square.parse("c1"), Square.parse("a1"), Square.parse("d1"), (Square.parse("d1"), Square.parse("c1"), Square.parse("b1"))),
    "k": (Square.parse("g8"), Square.parse("h8"), Square.parse("f8"), (Square.parse("f8"), Square.parse("g8"))),
    "q": (Square.parse("c8"), Square.parse("a8"), Square.parse("d8"), (Square.parse("d8"), Square.parse("c8"), Square.parse("b8"))),
}


def color_of(piece: str) -> str:
    """大文字が白、小文字が黒。"""
    return WHITE if piece.isupper() else BLACK


def other(color: str) -> str:
    return BLACK if color == WHITE else WHITE


@dataclass
class Board:
    """局面。駒の配置に加えて、手番・キャスリングの権利・アンパッサンできるマスを持つ。

    make_move で新しい Board を作り、作ったあとは変えない（cached_property で利きを覚えるため）。
    """

    pieces: dict[Square, str]
    turn: str = WHITE
    castling: frozenset[str] = frozenset("KQkq")
    en_passant: Square | None = None                        # 直前にポーンが 2 歩進んだとき、通り過ぎたマス
    halfmove: int = field(default=0, compare=False)         # ポーンも取る手も無い手が続いた数（50 手ルール用）
    fullmove: int = field(default=1, compare=False)         # 何手目か。黒が指すと増える

    def __hash__(self) -> int:
        """辞書は hash できないので、frozenset に変えてから。同じ局面なら同じ値になる（手数は含めない）。"""
        return hash((frozenset(self.pieces.items()), self.turn, self.castling, self.en_passant))

    @classmethod
    def from_fen(cls, fen: str) -> "Board":
        """FEN（配置 手番 キャスリング アンパッサン 50手カウンタ 手数）を読む。後ろ 2 つは省略できる。"""
        parts = fen.split()
        rows, turn, castling, en_passant, halfmove, fullmove = parts + ["-", "-", "0", "1"][len(parts) - 2:]
        pieces: dict[Square, str] = {}
        for i, row in enumerate(rows.split("/")):
            rank = 7 - i
            file = 0
            for ch in row:
                if ch.isdigit():
                    file += int(ch)
                else:
                    pieces[Square(file, rank)] = ch
                    file += 1
        return cls(pieces, turn, frozenset(castling.replace("-", "")),
                   None if en_passant == "-" else Square.parse(en_passant), int(halfmove), int(fullmove))

    @property
    def fen(self) -> str:
        """局面を FEN の文字列に戻す。"""
        rows = []
        for rank in range(7, -1, -1):
            row = ""
            empty = 0
            for file in range(8):
                piece = self.pieces.get(Square(file, rank))
                if piece is None:
                    empty += 1
                else:
                    row += (str(empty) if empty else "") + piece
                    empty = 0
            rows.append(row + (str(empty) if empty else ""))
        castling = "".join(c for c in "KQkq" if c in self.castling) or "-"
        en_passant = self.en_passant.name if self.en_passant else "-"
        return f"{'/'.join(rows)} {self.turn} {castling} {en_passant} {self.halfmove} {self.fullmove}"

    def __getitem__(self, key: "Square | str") -> str | None:
        """board["e4"] でも board[Square(4, 3)] でも。空きマスは None。"""
        if isinstance(key, str):
            key = Square.parse(key)
        return self.pieces.get(key)

    def __iter__(self):
        """for square, piece in board: の形で駒を順に。"""
        yield from self.pieces.items()

    def king_square(self, color: str) -> Square | None:
        king = "K" if color == WHITE else "k"
        return next((sq for sq, piece in self if piece == king), None)

    @cached_property
    def in_check(self) -> bool:
        """手番のキングが相手の利きに入っているか。"""
        return is_attacked(self, self.king_square(self.turn), other(self.turn))

    def __str__(self) -> str:
        lines = []
        for rank in range(7, -1, -1):
            row = " ".join(self.pieces.get(Square(file, rank), ".") for file in range(8))
            lines.append(f"{RANKS[rank]}  {row}")
        lines.append("   " + " ".join(FILES))
        return "\n".join(lines)


def ray(board: Board, start: Square, df: int, dr: int):
    """start から (df, dr) の向きへ、駒にぶつかるまでのマス。ぶつかった駒のマスも含む。"""
    sq = start.shift(df, dr)
    while sq.on_board:
        yield sq
        if board[sq] is not None:
            return
        sq = sq.shift(df, dr)


def piece_targets(board: Board, src: Square) -> list[Square]:
    """ポーン以外の駒が届くマス（味方の駒のマスも含む＝守っているマス）。"""
    kind = board[src].upper()
    if kind == "N":
        targets = [src.shift(df, dr) for df, dr in KNIGHT_JUMPS]
    elif kind == "K":
        targets = [src.shift(df, dr) for df, dr in KING_STEPS]
    else:
        dirs = {"R": ROOK_DIRS, "B": BISHOP_DIRS, "Q": ROOK_DIRS + BISHOP_DIRS}[kind]
        targets = [sq for df, dr in dirs for sq in ray(board, src, df, dr)]
    return [sq for sq in targets if sq.on_board]


def pawn_attacks(src: Square, color: str) -> list[Square]:
    """ポーンが利かせている斜め前の 2 マス。"""
    forward = 1 if color == WHITE else -1
    return [sq for sq in (src.shift(-1, forward), src.shift(1, forward)) if sq.on_board]


def pawn_moves(board: Board, src: Square) -> list[Move]:
    """ポーン。前に 1 つ（初期位置なら 2 つ）、斜め前の敵を取る。アンパッサン。最終段では成る。"""
    color = color_of(board[src])
    forward = 1 if color == WHITE else -1
    home = 1 if color == WHITE else 6
    last = 7 if color == WHITE else 0

    targets = []
    one = src.shift(0, forward)
    if one.on_board and board[one] is None:
        targets.append(one)
        two = src.shift(0, 2 * forward)
        if src.rank == home and board[two] is None:
            targets.append(two)
    for diag in pawn_attacks(src, color):
        enemy = board[diag] is not None and color_of(board[diag]) != color
        if enemy or diag == board.en_passant:
            targets.append(diag)

    moves = []
    for dst in targets:
        if dst.rank == last:
            moves.extend(Move(src, dst, piece) for piece in "QRBN")
        else:
            moves.append(Move(src, dst))
    return moves


def moves_from(board: Board, src: Square) -> list[Move]:
    """src にある駒が動けるマス（自分の駒があるマスは除く）。キングを晒すかどうかはまだ見ない。"""
    piece = board[src]
    if piece.upper() == "P":
        return pawn_moves(board, src)
    color = color_of(piece)
    return [Move(src, dst) for dst in piece_targets(board, src)
            if board[dst] is None or color_of(board[dst]) != color]


def is_attacked(board: Board, square: Square, color: str) -> bool:
    """square に color の駒の利きがあるか。マスから逆向きに探すので、全部の駒の利きを作らなくていい。"""
    knight, king, pawn = ("N", "K", "P") if color == WHITE else ("n", "k", "p")
    if any(board[sq] == knight for df, dr in KNIGHT_JUMPS if (sq := square.shift(df, dr)).on_board):
        return True
    if any(board[sq] == king for df, dr in KING_STEPS if (sq := square.shift(df, dr)).on_board):
        return True
    forward = 1 if color == WHITE else -1                    # color のポーンは square の手前（進行方向の逆）にいる
    if any(board[sq] == pawn for df in (-1, 1) if (sq := square.shift(df, -forward)).on_board):
        return True
    for dirs, kinds in ((ROOK_DIRS, "RQ"), (BISHOP_DIRS, "BQ")):
        for df, dr in dirs:
            for sq in ray(board, square, df, dr):
                piece = board[sq]
                if piece is not None:
                    if color_of(piece) == color and piece.upper() in kinds:
                        return True
                    break
    return False


def castling_moves(board: Board) -> list[Move]:
    """手番側のキャスリング。権利があり、間が空いていて、通り道が利きに入っていないこと。"""
    color = board.turn
    king = board.king_square(color)
    if king is None or board.in_check:
        return []
    moves = []
    for right in ("KQ" if color == WHITE else "kq"):
        if right not in board.castling:
            continue
        king_dst, rook_src, rook_dst, path = CASTLING[right]
        if all(board[sq] is None for sq in path) and not any(is_attacked(board, sq, other(color)) for sq in path[:2]):
            moves.append(Move(king, king_dst))
    return moves


def all_moves(board: Board, color: str | None = None) -> list[Move]:
    """color（省略なら手番）の駒が動ける手を全部（キングを晒す手も含む）。"""
    color = color or board.turn
    return [move for sq, piece in list(board) if color_of(piece) == color for move in moves_from(board, sq)]


def legal_moves(board: Board) -> list[Move]:
    """手番が指せる手。指したあとに自分のキングが取られる形になる手は除く。"""
    moves = []
    for move in all_moves(board) + castling_moves(board):
        after = make_move(board, move)
        if not is_attacked(after, after.king_square(board.turn), after.turn):
            moves.append(move)
    return moves


def make_move(board: Board, move: Move) -> Board:
    """指した後の局面を新しく作って返す。キャスリングのルーク、アンパッサンで取られるポーン、権利の更新もここで。"""
    pieces = dict(board.pieces)
    piece = pieces.pop(move.src)
    kind = piece.upper()
    captured = move.dst in pieces or (kind == "P" and move.dst == board.en_passant)

    if kind == "P" and move.dst == board.en_passant:        # アンパッサン。通り過ぎたポーンを取る
        pieces.pop(Square(move.dst.file, move.src.rank))
    if kind == "K" and abs(move.dst.file - move.src.file) == 2:   # キャスリング。ルークも動く
        for right, (king_dst, rook_src, rook_dst, _) in CASTLING.items():
            if move.dst == king_dst:
                pieces[rook_dst] = pieces.pop(rook_src)
    if move.promotion:
        piece = move.promotion if color_of(piece) == WHITE else move.promotion.lower()
    pieces[move.dst] = piece

    lost = CASTLING_RIGHTS.get(move.src, "") + CASTLING_RIGHTS.get(move.dst, "")   # 動かした駒／取られた駒のぶん
    en_passant = None
    if kind == "P" and abs(move.dst.rank - move.src.rank) == 2:
        en_passant = Square(move.src.file, (move.src.rank + move.dst.rank) // 2)

    return replace(board, pieces=pieces, turn=other(board.turn),
                   castling=board.castling - set(lost), en_passant=en_passant,
                   halfmove=0 if kind == "P" or captured else board.halfmove + 1,   # ポーンか取る手で振り出し
                   fullmove=board.fullmove + (1 if board.turn == BLACK else 0))


def insufficient_material(board: Board) -> bool:
    """どちらもチェックメイトできない駒しか残っていないか。K 対 K、K+N/B 対 K、同色マスのビショップだけ。"""
    others = [(sq, piece.upper()) for sq, piece in board if piece.upper() != "K"]
    if not others:
        return True
    if len(others) == 1 and others[0][1] in "NB":
        return True
    if all(kind == "B" for _, kind in others):
        colors = {(sq.file + sq.rank) % 2 for sq, _ in others}
        return len(colors) == 1
    return False


def result_of(board: Board) -> str | None:
    """終局なら結果。合法手が無ければメイトかステイルメイト。50 手ルールと駒不足もここで（千日手は履歴が要るので Game で）。"""
    if not legal_moves(board):
        return other(board.turn) if board.in_check else "stalemate"
    if board.halfmove >= FIFTY_MOVE_PLIES:
        return "fifty"
    if insufficient_material(board):
        return "material"
    return None


@lru_cache(maxsize=None)
def count_moves(board: Board, depth: int) -> int:
    """depth 手先までの合法手の組み合わせの数（perft）。同じ局面に別の手順で着いたら、覚えた数を使う。"""
    if depth == 0:
        return 1
    if depth == 1:
        return len(legal_moves(board))
    return sum(count_moves(make_move(board, move), depth - 1) for move in legal_moves(board))


def square_value(piece: str, sq: Square) -> int:
    """その駒がそのマスにいる点。表は白の向きなので、黒は段を裏返す。"""
    row = 7 - sq.rank if color_of(piece) == WHITE else sq.rank
    return PST[piece.upper()][row * 8 + sq.file]


def evaluate(board: Board) -> int:
    """手番側から見た局面の点。駒の価値 + 位置の点。プラスなら手番側が良い。"""
    score = 0
    for sq, piece in board:
        value = PIECE_VALUES[piece.upper()] + square_value(piece, sq)
        score += value if color_of(piece) == WHITE else -value
    return score if board.turn == WHITE else -score


class TimeUp(Exception):
    """考える時間が切れた。探索の途中から一気に抜けるための例外。"""


def order_moves(board: Board, moves: list[Move]) -> list[Move]:
    """良さそうな手を先に。取る手（価値の高い駒から）と成る手を前に出すと、αβ の枝刈りがよく効く。"""
    def priority(move: Move) -> int:
        target = board[move.dst]
        gain = PIECE_VALUES[target.upper()] if target else 0
        return -(gain + (PIECE_VALUES[move.promotion] if move.promotion else 0))
    return sorted(moves, key=priority)


def negamax(board: Board, depth: int, alpha: float, beta: float, ply: int,
            deadline: float | None, stats: dict[str, int]) -> float:
    """手番側から見た最善の点。相手の番は「相手の最善の点」に -1 を掛けるので、min と max を分けなくていい。"""
    stats["nodes"] += 1
    if deadline is not None and stats["nodes"] % 256 == 0 and time.monotonic() > deadline:
        raise TimeUp

    if board.halfmove >= FIFTY_MOVE_PLIES or insufficient_material(board):
        return 0
    if depth == 0:
        return evaluate(board)                              # 葉。合法手は作らない（そこがいちばん数が多い）
    moves = legal_moves(board)
    if not moves:
        return -MATE + ply if board.in_check else 0        # 手が無い＝メイトされた（早いほど悪い）かステイルメイト

    best = -math.inf
    for move in order_moves(board, moves):
        score = -negamax(make_move(board, move), depth - 1, -beta, -alpha, ply + 1, deadline, stats)
        best = max(best, score)
        alpha = max(alpha, score)
        if alpha >= beta:                                   # 相手はこの枝を選ばない → 残りは見なくていい
            break
    return best


def search(board: Board, depth: int, deadline: float | None = None,
           stats: dict[str, int] | None = None) -> tuple[Move, float]:
    """depth 手先まで読んで、いちばん良い手と点を返す。"""
    stats = stats if stats is not None else {"nodes": 0}
    best_move, best = None, -math.inf
    alpha, beta = -math.inf, math.inf
    for move in order_moves(board, legal_moves(board)):
        score = -negamax(make_move(board, move), depth - 1, -beta, -alpha, 1, deadline, stats)
        if score > best:
            best_move, best = move, score
        alpha = max(alpha, score)
    return best_move, best


def think(board: Board, seconds: float | None = None, max_depth: int | None = None) -> tuple[Move, float, int, int]:
    """反復深化。深さ 1 から順に読み、時間が切れたら最後に読み切った深さの手を使う。(手, 点, 深さ, ノード数)。"""
    deadline = time.monotonic() + seconds if seconds else None
    stats = {"nodes": 0}
    result = None
    for depth in range(1, (max_depth or 99) + 1):
        try:
            move, score = search(board, depth, deadline, stats)
        except TimeUp:
            break
        result = (move, score, depth, stats["nodes"])
        if abs(score) >= MATE - 100:                        # メイトを見つけたら、それ以上読まない
            break
    return result


def san(board: Board, move: Move) -> str:
    """手を SAN（代数記法）で書く。Nf3、exd5、e8=Q、O-O、Qh4+、Qxf7# など。"""
    piece = board[move.src]
    kind = piece.upper()
    after = make_move(board, move)
    suffix = ("#" if not legal_moves(after) else "+") if after.in_check else ""

    if kind == "K" and abs(move.dst.file - move.src.file) == 2:
        return ("O-O" if move.dst.file == 6 else "O-O-O") + suffix
    capture = board[move.dst] is not None or (kind == "P" and move.dst == board.en_passant)
    if kind == "P":
        text = (FILES[move.src.file] + "x" if capture else "") + move.dst.name
        if move.promotion:
            text += "=" + move.promotion
        return text + suffix

    # 同じ種類の駒がほかにも同じマスへ行けるなら、筋か段（両方要ることも）で区別する
    others = [m.src for m in legal_moves(board) if m.dst == move.dst and m.src != move.src and board[m.src] == piece]
    if not others:
        where = ""
    elif all(o.file != move.src.file for o in others):
        where = FILES[move.src.file]
    elif all(o.rank != move.src.rank for o in others):
        where = RANKS[move.src.rank]
    else:
        where = move.src.name
    return kind + where + ("x" if capture else "") + move.dst.name + suffix


def parse_move(board: Board, text: str) -> Move | None:
    """e2e4 でも Nf3 でも読む。指せる手が 1 つに決まらなければ None。"""
    text = text.strip()
    if COORD_PATTERN.match(text):
        move = Move.parse(text)
        return move if move in legal_moves(board) else None

    text = text.replace("0", "O").rstrip("+#")               # 0-0 と書かれても、+ や # が付いていても
    if text in ("O-O", "O-O-O"):
        king = board.king_square(board.turn)
        move = Move(king, Square(6 if text == "O-O" else 2, king.rank))
        return move if move in legal_moves(board) else None

    found = SAN_PATTERN.match(text)
    if found is None:
        return None
    kind = found["piece"] or "P"
    dst = Square.parse(found["to"])
    candidates = [m for m in legal_moves(board)
                  if m.dst == dst and board[m.src].upper() == kind
                  and (found["from_file"] is None or FILES[m.src.file] == found["from_file"])
                  and (found["from_rank"] is None or RANKS[m.src.rank] == found["from_rank"])
                  and m.promotion == found["promotion"]]
    return candidates[0] if len(candidates) == 1 else None


class Game:
    """対局 1 回ぶん。局面・履歴・結果。表示と入力は持たない。"""

    def __init__(self, cpu: str | None = None, seed: int | None = None, fen: str = START_FEN,
                 seconds: float | None = THINK_SECONDS, depth: int | None = None):
        if seed is not None:
            random.seed(seed)
        self.seconds = seconds                                      # CPU の持ち時間（None なら深さだけ）
        self.depth = depth                                          # CPU の読みの深さ（None なら時間だけ）
        self.thought: tuple[Move, float, int, int] | None = None    # CPU が最後に考えた結果
        self.board = Board.from_fen(fen)
        self.history: list[tuple[Board, Move]] = []                # (指す前の局面, 手)
        self.sans: list[str] = []                                   # 手を SAN で。棋譜そのもの
        self.headers = {"Event": "python-study g26", "Site": "?", "Date": date.today().strftime("%Y.%m.%d"),
                        "Round": "-", "White": "?", "Black": "?"}
        if fen != START_FEN:
            self.headers["FEN"] = fen
        self.positions: Counter[Board] = Counter([self.board])      # 局面が何回現れたか（千日手用）
        self.cpu = cpu                                              # CPU が持つ色。None なら 2 人
        self.result: str | None = None

    @property
    def legal_moves(self) -> list[Move]:
        return legal_moves(self.board)

    @property
    def last_move(self) -> Move | None:
        return self.history[-1][1] if self.history else None

    @property
    def repetitions(self) -> int:
        """今の局面が何回目か。"""
        return self.positions[self.board]

    def play(self, move: Move) -> bool:
        """1 手指す。合法手でなければ False。指したあと終局なら result が入る。"""
        if self.result is not None or move not in self.legal_moves:
            return False
        self.history.append((self.board, move))
        self.sans.append(san(self.board, move))
        self.board = make_move(self.board, move)
        self.positions[self.board] += 1
        self.result = "repetition" if self.repetitions >= REPETITIONS else result_of(self.board)
        return True

    def undo(self) -> bool:
        """1 手戻す。CPU 相手なら 2 手（自分の番まで）。局面の回数も戻す。"""
        if not self.history:
            return False
        steps = 2 if self.cpu and len(self.history) >= 2 else 1
        for _ in range(steps):
            self.positions[self.board] -= 1
            self.board, _ = self.history.pop()
            self.sans.pop()
        self.result = None
        return True

    @property
    def movetext(self) -> str:
        """1. e4 e5 2. Nf3 ... の形。途中から始めた局面なら黒の手を 1... で。"""
        start = self.history[0][0] if self.history else self.board
        parts = []
        for i, text in enumerate(self.sans):
            number = start.fullmove + (i + (1 if start.turn == BLACK else 0)) // 2
            if i == 0 and start.turn == BLACK:
                parts.append(f"{number}... {text}")
            elif (i + (1 if start.turn == BLACK else 0)) % 2 == 0:
                parts.append(f"{number}. {text}")
            else:
                parts.append(text)
        return " ".join(parts)

    @property
    def pgn(self) -> str:
        """PGN の文字列。ヘッダ、空行、手（80 桁で折り返し）、結果。"""
        headers = dict(self.headers, Result=RESULT_TOKENS[self.result])
        lines = [f'[{key} "{value}"]' for key, value in headers.items()]
        body = textwrap.fill(f"{self.movetext} {RESULT_TOKENS[self.result]}".strip(), width=80)
        return "\n".join(lines) + "\n\n" + body + "\n"


    @classmethod
    def from_pgn(cls, text: str, **kwargs) -> "Game":
        """PGN を読んで、手を順に指し直した Game を返す。読めない手があれば ValueError。"""
        headers = dict(PGN_TAG.findall(text))
        body = text[text.rindex("]") + 1:] if "]" in text else text
        game = cls(fen=headers.get("FEN", START_FEN), **kwargs)
        game.headers.update({k: v for k, v in headers.items() if k != "Result"})
        for token in PGN_NOISE.sub(" ", body).split():
            if token in ("1-0", "0-1", "1/2-1/2", "*"):
                break
            move = parse_move(game.board, token)
            if move is None:
                raise ValueError(f"{len(game.sans) // 2 + 1} 手目の {token!r} が読めません（局面 {game.board.fen}）")
            game.play(move)
        return game


    def cpu_move(self) -> Move | None:
        """CPU の番なら、先読みして指す。"""
        if self.result is not None or self.board.turn != self.cpu:
            return None
        self.thought = think(self.board, self.seconds, self.depth)
        move = self.thought[0]
        self.play(move)
        return move

    def thought_text(self) -> str:
        """CPU が何をどれだけ考えたか。"""
        if self.thought is None:
            return ""
        move, score, depth, nodes = self.thought
        if abs(score) >= MATE - 100:
            plies = MATE - abs(score)
            verdict = f"{(plies + 1) // 2} 手でメイト" if score > 0 else f"{(plies + 1) // 2} 手でメイトされる"
        else:
            verdict = f"評価 {score / 100:+.2f}"
        return f"{depth} 手読み  {nodes:,} 局面  {verdict}"


# --- ここから下はブラウザ版だけ。CLI 版の input() と render() と main() にあたる ---

CPU_WAIT = 0.35                                             # CPU が考えているように見せる間
GLYPHS = {"K": "♔", "Q": "♕", "R": "♖", "B": "♗", "N": "♘", "P": "♙",
          "k": "♚", "q": "♛", "r": "♜", "b": "♝", "n": "♞", "p": "♟"}

board_grid = document.querySelector("#board")
turn_label = document.querySelector("#turn")
moves_label = document.querySelector("#moves")
message = document.querySelector("#message")
clock = document.querySelector("#clock")
thought = document.querySelector("#thought")
score_el = document.querySelector("#score")
pgn_area = document.querySelector("#pgn")
load_button = document.querySelector("#load-btn")
undo_button = document.querySelector("#undo-btn")
start_button = document.querySelector("#start-btn")
two_button = document.querySelector("#mode-two")
cpu_button = document.querySelector("#mode-cpu")
promotion_select = document.querySelector("#promotion")

cells = {}                                                  # Square → <div>。作るのは一度だけ
for rank in range(7, -1, -1):
    for file in range(8):
        cell = document.createElement("div")
        cell.className = "cell"                             # @when("click", "#board .cell") は登録時に探すので先に付ける
        cell.setAttribute("data-square", Square(file, rank).name)
        board_grid.appendChild(cell)
        cells[Square(file, rank)] = cell

game = Game(cpu=BLACK)
selected: Square | None = None                              # クリックで選んだ駒のマス


def cpu_thinking() -> bool:
    return game.cpu is not None and game.board.turn == game.cpu and game.result is None


def draw():
    """CLI 版の Board.__str__ + Game.render() にあたる。"""
    global selected
    if selected is not None and game.board[selected] is None:
        selected = None
    targets = {m.dst for m in game.legal_moves if m.src == selected} if selected else set()
    last = game.last_move

    for square, cell in cells.items():
        piece = game.board[square]
        names = ["cell", "dark" if (square.file + square.rank) % 2 == 0 else "light"]
        if piece is not None:
            names.append("white" if color_of(piece) == WHITE else "black")
        if square == selected:
            names.append("selected")
        if square in targets:
            names.append("capture" if piece is not None else "target")
        if last is not None and square in (last.src, last.dst):
            names.append("last")
        if game.board.in_check and game.result is None and square == game.board.king_square(game.board.turn):
            names.append("check")
        cell.className = " ".join(names)
        cell.textContent = GLYPHS.get(piece, "")

    board_grid.className = "" if game.result is not None or cpu_thinking() else f"turn-{game.board.turn}"
    moves_label.textContent = str(game.board.fullmove)
    again = f"　同じ局面 {game.repetitions} 回目" if game.repetitions > 1 else ""
    clock.textContent = f"50 手カウンタ {game.board.halfmove}{again}"
    thought.textContent = f"CPU: {game.thought_text()}" if game.thought else ""
    score_el.textContent = game.movetext
    pgn_area.value = game.pgn
    undo_button.disabled = not game.history
    if game.result is not None:
        turn_label.textContent = "終局"
    elif cpu_thinking():
        turn_label.textContent = "黒（CPU）が考え中…"
    else:
        check = "　チェック！" if game.board.in_check else ""
        turn_label.textContent = ("白の番" if game.board.turn == WHITE else "黒の番") + check


def after_move(move: Move):
    who = "白" if game.board.turn == BLACK else "黒"         # 指した側（手番はもう替わっている）
    piece = game.board[move.dst]
    message.textContent = f"{who} {PIECE_NAMES[piece.upper()]} {move}"
    draw()
    if game.result is not None:
        message.textContent = RESULT_TEXT[game.result] + f"　{len(game.history)} 手"
    elif cpu_thinking():
        asyncio.ensure_future(cpu_turn())


async def cpu_turn():
    """CPU の手番。CLI 版との違いは、「考え中」を描いてから読み始めることだけ。"""
    await asyncio.sleep(CPU_WAIT)                           # 先に draw() の「考え中」を画面に出す
    if not cpu_thinking():                                  # 待っているあいだに「待った」が押されたかもしれない
        return
    after_move(game.cpu_move())


def start():
    global game, selected
    cpu = BLACK if cpu_button.classList.contains("is-on") else None
    game = Game(cpu=cpu)
    game.headers["White"] = "Hico"
    game.headers["Black"] = "CPU" if cpu else "Hico"
    selected = None
    message.textContent = ""
    draw()


def load_pgn():
    """CLI 版の --load にあたる。textarea の PGN から Game を作り直す。"""
    global game, selected
    cpu = BLACK if cpu_button.classList.contains("is-on") else None
    try:
        game = Game.from_pgn(pgn_area.value, cpu=cpu)
    except ValueError as error:
        message.textContent = f"読めません: {error}"
        return
    selected = None
    message.textContent = f"PGN を読み込みました（{len(game.sans)} 手）"
    draw()
    if cpu_thinking():
        asyncio.ensure_future(cpu_turn())


@when("click", "#board .cell")
def on_cell(event):
    global selected
    if game.result is not None or cpu_thinking():
        return
    square = Square.parse(event.target.getAttribute("data-square"))
    piece = game.board[square]

    if selected is not None:
        promotion = None
        if game.board[selected].upper() == "P" and square.rank in (0, 7):
            promotion = promotion_select.value
        move = Move(selected, square, promotion)
        if game.play(move):
            selected = None
            after_move(move)
            return
    # 自分の駒をクリック → 選び直し。それ以外 → 選択解除
    selected = square if piece is not None and color_of(piece) == game.board.turn else None
    draw()


@when("click", "#undo-btn")
def on_undo(event):
    global selected
    if game.undo():
        selected = None
        message.textContent = "待った"
        draw()


@when("click", "#start-btn")
def on_start(event):
    start()


@when("click", "#load-btn")
def on_load(event):
    load_pgn()


@when("click", "#mode-two")
def on_two(event):
    two_button.classList.add("is-on")
    cpu_button.classList.remove("is-on")
    start()


@when("click", "#mode-cpu")
def on_cpu(event):
    cpu_button.classList.add("is-on")
    two_button.classList.remove("is-on")
    start()


# Pyodide の読み込みが終わってから実行される＝ここが準備完了の合図
document.querySelector("#loading").hidden = True
start_button.disabled = False
load_button.disabled = False
game.headers["White"] = "Hico"
game.headers["Black"] = "CPU"
draw()
