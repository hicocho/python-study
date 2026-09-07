"""チェスの終局 — 完成: 千日手・50 手・駒不足の引き分け。perft は lru_cache で速く。unittest で検証する。"""

import argparse
import random
import time
from collections import Counter
from dataclasses import dataclass, field, replace
from functools import cached_property, lru_cache
from typing import NamedTuple

FILES = "abcdefgh"                          # 筋（左から）
RANKS = "12345678"                          # 段（下から）
START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
FIFTY_MOVE_PLIES = 100                      # ポーンも取る手も無いまま 100 手（50 手ずつ）で引き分け
REPETITIONS = 3                             # 同じ局面がこの回数で千日手
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


# キャスリングの権利。キングかルークが動いたら（ルークが取られても）消える
CASTLING_RIGHTS = {
    Square.parse("e1"): "KQ", Square.parse("a1"): "Q", Square.parse("h1"): "K",
    Square.parse("e8"): "kq", Square.parse("a8"): "q", Square.parse("h8"): "k",
}
# 権利 → (キングの行き先, ルークの元, ルークの行き先, キングが通るマス)
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
    def attacked(self) -> dict[str, set[Square]]:
        """色ごとの「利き」（その色の駒が取れるマス）。一度計算したら覚えておく。"""
        return {color: attacked_squares(self, color) for color in (WHITE, BLACK)}

    @property
    def in_check(self) -> bool:
        """手番のキングが相手の利きに入っているか。"""
        return self.king_square(self.turn) in self.attacked[other(self.turn)]

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


def attacked_squares(board: Board, color: str) -> set[Square]:
    """color の駒が利かせているマス全部。"""
    result: set[Square] = set()
    for sq, piece in board:
        if color_of(piece) != color:
            continue
        if piece.upper() == "P":
            result.update(pawn_attacks(sq, color))
        else:
            result.update(piece_targets(board, sq))
    return result


def castling_moves(board: Board) -> list[Move]:
    """手番側のキャスリング。権利があり、間が空いていて、通り道が利きに入っていないこと。"""
    color = board.turn
    king = board.king_square(color)
    if king is None or board.in_check:
        return []
    enemy = board.attacked[other(color)]
    moves = []
    for right in ("KQ" if color == WHITE else "kq"):
        if right not in board.castling:
            continue
        king_dst, rook_src, rook_dst, path = CASTLING[right]
        if all(board[sq] is None for sq in path) and not any(sq in enemy for sq in path[:2]):
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
        if after.king_square(board.turn) not in after.attacked[after.turn]:
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


def perft_table(fen: str, max_depth: int) -> list[tuple[int, int, float]]:
    """深さごとの (深さ, 手の数, 秒) を返す。"""
    rows = []
    for depth in range(1, max_depth + 1):
        count_moves.cache_clear()
        start = time.perf_counter()
        rows.append((depth, count_moves(Board.from_fen(fen), depth), time.perf_counter() - start))
    return rows


class Game:
    """対局 1 回ぶん。局面・履歴・結果。表示と入力は持たない。"""

    def __init__(self, cpu: str | None = None, seed: int | None = None, fen: str = START_FEN): # ←
        if seed is not None:
            random.seed(seed)
        self.board = Board.from_fen(fen)    # ←
        self.history: list[tuple[Board, Move]] = []                # (指す前の局面, 手)
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
            self.positions[self.board] -= 1 # ←
            self.board, _ = self.history.pop()
        self.result = None
        return True

    def cpu_move(self) -> Move | None:
        """CPU の番なら、合法手からランダムに 1 つ指す。"""
        if self.result is not None or self.board.turn != self.cpu:
            return None
        move = random.choice(self.legal_moves)
        self.play(move)
        return move

    def render(self) -> str:
        turn = "白" if self.board.turn == WHITE else "黒"
        last = f"   直前 {self.last_move}" if self.last_move else ""
        check = "   チェック！" if self.board.in_check and self.result is None else ""
        again = f"   同じ局面 {self.repetitions} 回目" if self.repetitions > 1 else "" # ←
        return (f"{self.board}\n\n{self.board.fullmove} 手目 {turn}の番{last}{check}{again}\n"   # ←
                f"50 手カウンタ {self.board.halfmove}\n")


def main():
    parser = argparse.ArgumentParser(description="チェス（終局と検証）")
    parser.add_argument("--cpu", choices=["w", "b"], help="この色をランダム CPU に任せる")
    parser.add_argument("--fen", default=START_FEN, help="この局面から始める")
    parser.add_argument("--perft", type=int, metavar="DEPTH", help="対局せず、この深さまで perft を数えて終わる")
    args = parser.parse_args()

    if args.perft:
        print(f"perft  {args.fen}")
        for depth, count, seconds in perft_table(args.fen, args.perft):
            print(f"  {depth} 手先  {count:>10,} 通り  {seconds:6.2f} 秒")
        return

    game = Game(cpu=args.cpu, fen=args.fen) # ←
    print("e2e4 のように指す。キャスリングはキングを 2 つ動かす（e1g1）。成るときは e7e8q。undo で戻す、q でやめる。\n")

    while game.result is None:
        print(game.render())
        if game.board.turn == game.cpu:
            print(f"CPU: {game.cpu_move()}\n")
            continue
        text = input("> ").strip().lower()
        if text == "q":
            game.result = "quit"
        elif text == "undo":
            game.undo()
        else:
            try:
                move = Move.parse(text)
            except (ValueError, IndexError):
                print("e2e4 の形で入力してください。\n")
                continue
            if not game.play(move):
                piece = game.board[move.src]
                what = PIECE_NAMES[piece.upper()] if piece else "駒がない"
                print(f"{move} は指せません（{what}）。\n")

    print(game.render())
    print(RESULT_TEXT[game.result])


if __name__ == "__main__":
    main()
