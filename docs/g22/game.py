"""チェス（ブラウザ版）

CLI 版（g22-chess/main.py）と盤・駒の動き・勝ち負けはまったく同じ。
定数と Square / Move / Board、ray() 〜 count_moves()、そして class Game を、
ステップの目印コメント（# ←）を外しただけで 1 文字も変えずに持ってきている。

持ってこなかったのは Board.__str__ を使う Game.render() と main() だけ。
出口は 64 個の <div>。駒は Unicode のチェス記号で置く。クリックで選んで、クリックで指す。
"""

import asyncio
import random
from typing import NamedTuple

from pyscript import document, when


# --- ここから class Game まで、CLI 版（g22-chess/main.py）からそのまま ---


FILES = "abcdefgh"                          # 筋（左から）
RANKS = "12345678"                          # 段（下から）
START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w"
WHITE = "w"
BLACK = "b"


PIECE_NAMES = {"K": "キング", "Q": "クイーン", "R": "ルーク", "B": "ビショップ", "N": "ナイト", "P": "ポーン"}


KNIGHT_JUMPS = [(1, 2), (2, 1), (2, -1), (1, -2), (-1, -2), (-2, -1), (-2, 1), (-1, 2)]
KING_STEPS = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)]
ROOK_DIRS = [(1, 0), (-1, 0), (0, 1), (0, -1)]
BISHOP_DIRS = [(1, 1), (1, -1), (-1, 1), (-1, -1)]


RESULT_TEXT = {
    WHITE: "白の勝ち（黒のキングを取った）",
    BLACK: "黒の勝ち（白のキングを取った）",
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


def color_of(piece: str) -> str:
    """大文字が白、小文字が黒。"""
    return WHITE if piece.isupper() else BLACK


def other(color: str) -> str:
    return BLACK if color == WHITE else WHITE


class Board:
    """盤。駒のあるマスだけ {Square: 駒の文字} で持つ。"""

    def __init__(self, pieces: dict[Square, str], turn: str = WHITE):
        self.pieces = pieces
        self.turn = turn

    @classmethod
    def from_fen(cls, fen: str) -> "Board":
        """FEN（8 段目から順に、数字は空きマスの数）を読む。"""
        rows, turn = fen.split()[:2]
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
        return cls(pieces, turn)

    @property
    def fen(self) -> str:
        """盤を FEN の文字列に戻す。"""
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
        return "/".join(rows) + " " + self.turn

    def __getitem__(self, key: "Square | str") -> str | None:
        """board["e4"] でも board[Square(4, 3)] でも。空きマスは None。"""
        if isinstance(key, str):
            key = Square.parse(key)
        return self.pieces.get(key)

    def __setitem__(self, key: "Square | str", piece: str | None) -> None:
        """board["e4"] = "P"。None を入れると空きマスになる。"""
        if isinstance(key, str):
            key = Square.parse(key)
        if piece is None:
            self.pieces.pop(key, None)
        else:
            self.pieces[key] = piece

    def __iter__(self):
        """for square, piece in board: の形で駒を順に。"""
        yield from self.pieces.items()

    def copy(self) -> "Board":
        return Board(dict(self.pieces), self.turn)

    def king_square(self, color: str) -> Square | None:
        king = "K" if color == WHITE else "k"
        return next((sq for sq, piece in self if piece == king), None)

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


def pawn_moves(board: Board, src: Square) -> list[Move]:
    """ポーン。前に 1 つ（初期位置なら 2 つ）、斜め前の敵を取る。最終段では成る。"""
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
    for df in (-1, 1):
        diag = src.shift(df, forward)
        if diag.on_board and board[diag] is not None and color_of(board[diag]) != color:
            targets.append(diag)

    moves = []
    for dst in targets:
        if dst.rank == last:
            moves.extend(Move(src, dst, piece) for piece in "QRBN")
        else:
            moves.append(Move(src, dst))
    return moves


def moves_from(board: Board, src: Square) -> list[Move]:
    """src にある駒が動けるマス（自分の駒があるマスは除く）。"""
    piece = board[src]
    color = color_of(piece)
    kind = piece.upper()
    if kind == "P":
        return pawn_moves(board, src)
    if kind == "N":
        targets = [src.shift(df, dr) for df, dr in KNIGHT_JUMPS]
    elif kind == "K":
        targets = [src.shift(df, dr) for df, dr in KING_STEPS]
    else:
        dirs = {"R": ROOK_DIRS, "B": BISHOP_DIRS, "Q": ROOK_DIRS + BISHOP_DIRS}[kind]
        targets = [sq for df, dr in dirs for sq in ray(board, src, df, dr)]
    return [Move(src, dst) for dst in targets
            if dst.on_board and (board[dst] is None or color_of(board[dst]) != color)]


def all_moves(board: Board, color: str | None = None) -> list[Move]:
    """color（省略なら手番）の駒が動ける手を全部。"""
    color = color or board.turn
    return [move for sq, piece in list(board) if color_of(piece) == color for move in moves_from(board, sq)]


def make_move(board: Board, move: Move) -> Board:
    """指した後の盤を新しく作って返す（元の盤は変えない）。"""
    new = board.copy()
    piece = new[move.src]
    new[move.src] = None
    if move.promotion:
        piece = move.promotion if color_of(piece) == WHITE else move.promotion.lower()
    new[move.dst] = piece
    new.turn = other(board.turn)
    return new


def count_moves(board: Board, depth: int) -> int:
    """depth 手先までの手の組み合わせの数（perft）。動きの実装を数で検証するための関数。"""
    if depth == 0:
        return 1
    return sum(count_moves(make_move(board, move), depth - 1) for move in all_moves(board))


class Game:
    """対局 1 回ぶん。盤・履歴・結果。表示と入力は持たない。"""

    def __init__(self, cpu: str | None = None, seed: int | None = None):
        if seed is not None:
            random.seed(seed)
        self.board = Board.from_fen(START_FEN)
        self.history: list[tuple[Board, Move]] = []                # (指す前の盤, 手)
        self.cpu = cpu                                              # CPU が持つ色。None なら 2 人
        self.result: str | None = None

    @property
    def legal_moves(self) -> list[Move]:
        return all_moves(self.board)

    @property
    def last_move(self) -> Move | None:
        return self.history[-1][1] if self.history else None

    def play(self, move: Move) -> bool:
        """1 手指す。指せない手なら False。相手のキングを取ったら勝ち。"""
        if self.result is not None or move not in self.legal_moves:
            return False
        self.history.append((self.board, move))
        self.board = make_move(self.board, move)
        if self.board.king_square(self.board.turn) is None:
            self.result = other(self.board.turn)
        return True

    def undo(self) -> bool:
        """1 手戻す。CPU 相手なら 2 手（自分の番まで）。"""
        if not self.history:
            return False
        steps = 2 if self.cpu and len(self.history) >= 2 else 1
        for _ in range(steps):
            self.board, _ = self.history.pop()
        self.result = None
        return True

    def cpu_move(self) -> Move | None:
        """CPU の番なら、動ける手からランダムに 1 つ指す。"""
        if self.result is not None or self.board.turn != self.cpu:
            return None
        move = random.choice(self.legal_moves)
        self.play(move)
        return move


# --- ここから下はブラウザ版だけ。CLI 版の input() と render() と main() にあたる ---

CPU_WAIT = 0.35                                             # CPU が考えているように見せる間
GLYPHS = {"K": "♔", "Q": "♕", "R": "♖", "B": "♗", "N": "♘", "P": "♙",
          "k": "♚", "q": "♛", "r": "♜", "b": "♝", "n": "♞", "p": "♟"}

board_grid = document.querySelector("#board")
turn_label = document.querySelector("#turn")
moves_label = document.querySelector("#moves")
message = document.querySelector("#message")
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
        cell.className = " ".join(names)
        cell.textContent = GLYPHS.get(piece, "")

    board_grid.className = "" if game.result is not None or cpu_thinking() else f"turn-{game.board.turn}"
    moves_label.textContent = str(len(game.history) // 2 + 1)
    undo_button.disabled = not game.history
    if game.result is not None:
        turn_label.textContent = "終局"
    elif cpu_thinking():
        turn_label.textContent = "黒（CPU）が考え中"
    else:
        turn_label.textContent = "白の番" if game.board.turn == WHITE else "黒の番"


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
    """CPU の手番。CLI 版との違いは、間を置くことだけ。"""
    await asyncio.sleep(CPU_WAIT)
    if not cpu_thinking():                                  # 待っているあいだに「待った」が押されたかもしれない
        return
    after_move(game.cpu_move())


def start():
    global game, selected
    cpu = BLACK if cpu_button.classList.contains("is-on") else None
    game = Game(cpu=cpu)
    selected = None
    message.textContent = ""
    draw()


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
