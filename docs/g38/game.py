"""将棋（反則と終局）ブラウザ版

CLI 版（g38-shogi-rules/main.py）と駒・盤・手の生成・成り・持ち駒はまったく同じ。
Piece / Square / Move / Board（do / undo / zobrist）、trying() / attacked() / in_check() / legal_moves()、make_move() / describe()、
そして class Game を、ステップの目印コメント（# ←）を外しただけで 1 文字も変えずに持ってきている。

持ってこなかったのは端末の input() と print() を使う main() だけ。
出口は 9×9 の <div> と持ち駒のボタン。クリックで選んで、クリックで指す。
"""

import asyncio
import random
from collections import deque
from contextlib import contextmanager
from enum import IntFlag
from itertools import product
from typing import NamedTuple

from pyscript import document, when
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
    "quit": "やめました。",
}


REPETITIONS = 4                             # 同じ局面がこの回数で千日手


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


class Game:
    """対局 1 回ぶん。盤・履歴・結果。表示と入力は持たない。"""

    def __init__(self, cpu: str | None = None, seed: int | None = None, sfen: str = START_SFEN):
        self.rng = random.Random(seed)
        self.board = Board.from_sfen(sfen)
        self.history: list[tuple[Board, Move]] = []                # (指す前の盤, 手)
        self.cpu = cpu                                              # CPU が持つ側。None なら 2 人
        self.result: str | None = None
        self.seen: dict[int, int] = {self.board.zobrist(): 1}       # 局面のハッシュ → 出た回数（千日手）
        self.checks: list[bool] = []                                # 各手が王手だったか（連続王手の千日手）
        self.recent: deque[str] = deque(maxlen=6)                   # 直前の手の日本語表記。古いものから消える

    @property
    def legal_moves(self) -> list[Move]:
        return legal_moves(self.board)

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
        """指した直後の結果。手番側に手がなければ負け（王手なら詰み）。同じ局面 4 回で千日手。"""
        mover = other(self.board.turn)
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
        move = self.rng.choice(self.legal_moves)
        self.play(move)
        return move

    def render(self) -> str:
        turn = "先手" if self.board.turn == SENTE else "後手"
        check = "   王手！" if self.in_check and self.result is None else ""
        recent = f"   {' '.join(self.recent)}" if self.recent else ""
        return f"{self.board}\n\n{len(self.history) + 1} 手目 {turn}の番{check}{recent}\n"
# --- ここから下はブラウザ版だけ。CLI 版の input() と print() と main() にあたる ---

CPU_WAIT = 0.35                                             # CPU が考えているように見せる間

board_grid = document.querySelector("#board")
turn_label = document.querySelector("#turn")
moves_label = document.querySelector("#moves")
message = document.querySelector("#message")
undo_button = document.querySelector("#undo-btn")
start_button = document.querySelector("#start-btn")
two_button = document.querySelector("#mode-two")
cpu_button = document.querySelector("#mode-cpu")
promotion_select = document.querySelector("#promotion")
hand_buttons = {SENTE: {}, GOTE: {}}                        # 側 → 種類 → <button>。HTML に置いてあるものを拾う
for color in (SENTE, GOTE):
    for button in document.querySelectorAll(f"#hand-{color} button"):
        hand_buttons[color][Piece[button.getAttribute("data-kind")]] = button

cells = {}                                                  # Square → <div>。作るのは一度だけ。９一 が左上
for rank in range(1, 10):
    for file in range(9, 0, -1):
        cell = document.createElement("div")
        cell.className = "cell"                             # @when("click", "#board .cell") は登録時に探すので先に付ける
        cell.setAttribute("data-square", Square(file, rank).usi)
        board_grid.appendChild(cell)
        cells[Square(file, rank)] = cell

game = Game(cpu=GOTE)
selected: Square | None = None                              # クリックで選んだ盤上の駒
selected_drop: Piece = Piece.NONE                           # クリックで選んだ持ち駒


def cpu_thinking() -> bool:
    return game.cpu is not None and game.board.turn == game.cpu and game.result is None


def draw():
    """CLI 版の Board.__str__ + Game.render() にあたる。"""
    global selected, selected_drop
    if selected is not None and game.board[selected] is None:
        selected = None
    legal = game.legal_moves
    if selected is not None:
        targets = {m.dst for m in legal if m.src == selected}
    elif selected_drop:
        targets = {m.dst for m in legal if m.drop == selected_drop}
    else:
        targets = set()
    last = game.last_move

    for square, cell in cells.items():
        piece = game.board[square]
        names = ["cell"]
        if piece is not None:
            names.append("gote" if Piece.GOTE in piece else "sente")
            if Piece.PROMOTED in piece:
                names.append("promoted")
        if square == selected:
            names.append("selected")
        if square in targets:
            names.append("capture" if piece is not None else "target")
        if last is not None and (square == last.dst or square == last.src):
            names.append("last")
        if piece is not None and kind_of(piece) == Piece.OU and color_of(piece) == game.board.turn and game.in_check:
            names.append("check")
        cell.className = " ".join(names)
        cell.textContent = kanji_of(piece) if piece is not None else ""

    for color in (SENTE, GOTE):
        for kind, button in hand_buttons[color].items():
            n = game.board.hands[color].get(kind, 0)
            button.hidden = n == 0
            button.textContent = KANJI[kind] + (f"×{n}" if n > 1 else "")
            button.className = "selected" if color == game.board.turn and kind == selected_drop else ""

    board_grid.className = "" if game.result is not None or cpu_thinking() else f"turn-{game.board.turn}"
    moves_label.textContent = str(len(game.history) + 1)
    undo_button.disabled = not game.history
    if game.result is not None:
        turn_label.textContent = "終局"
    elif cpu_thinking():
        turn_label.textContent = "後手（CPU）が考え中"
    else:
        turn_label.textContent = "先手の番" if game.board.turn == SENTE else "後手の番"


def after_move(before: Board, move: Move):
    message.textContent = describe(before, move) + ("　王手" if game.in_check and game.result is None else "")
    draw()
    if game.result is not None:
        message.textContent = RESULT_TEXT[game.result] + f"　{len(game.history)} 手"
    elif cpu_thinking():
        asyncio.ensure_future(cpu_turn())


async def cpu_turn():
    """CPU の手番。CLI 版との違いは、間を置くことだけ。"""
    await asyncio.sleep(CPU_WAIT)
    if not cpu_thinking():                                  # 待っているあいだに「待った」が押されたかもしれない
        return
    before = game.board
    after_move(before, game.cpu_move())


def start():
    global game, selected, selected_drop
    cpu = GOTE if cpu_button.classList.contains("is-on") else None
    game = Game(cpu=cpu)
    selected = None
    selected_drop = Piece.NONE
    message.textContent = ""
    draw()


def try_move(candidates: list[Move]) -> bool:
    """行き先が同じ手が 2 つ（成る・成らない）なら選択欄で決める。指せたら True。"""
    if not candidates:
        return False
    move = candidates[0]
    if len(candidates) == 2:
        want = promotion_select.value == "1"
        move = next(m for m in candidates if m.promote == want)
    before = game.board
    if game.play(move):
        clear_selection()                                   # 描く前に選択を外す（相手の持ち駒が選ばれたままにならないように）
        after_move(before, move)
        return True
    return False


def clear_selection():
    global selected, selected_drop
    selected = None
    selected_drop = Piece.NONE


@when("click", "#board .cell")
def on_cell(event):
    global selected, selected_drop
    if game.result is not None or cpu_thinking():
        return
    square = Square.parse(event.target.getAttribute("data-square"))
    piece = game.board[square]

    if selected is not None:
        if try_move([m for m in game.legal_moves if m.src == selected and m.dst == square]):
            return
    elif selected_drop:
        if try_move([m for m in game.legal_moves if m.drop == selected_drop and m.dst == square]):
            return
    # 自分の駒をクリック → 選び直し。それ以外 → 選択解除
    selected = square if piece is not None and color_of(piece) == game.board.turn else None
    selected_drop = Piece.NONE
    draw()


@when("click", ".hand button")
def on_hand(event):
    global selected, selected_drop
    if game.result is not None or cpu_thinking():
        return
    color = GOTE if event.target.parentElement.id == "hand-w" else SENTE
    if color != game.board.turn:
        return
    kind = Piece[event.target.getAttribute("data-kind")]
    selected_drop = Piece.NONE if selected_drop == kind else kind
    selected = None
    draw()


@when("click", "#undo-btn")
def on_undo(event):
    global selected, selected_drop
    if game.undo():
        selected = None
        selected_drop = Piece.NONE
        message.textContent = "待った"
        draw()


@when("click", "#start-btn")
def on_start(event):
    start()


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
draw()
