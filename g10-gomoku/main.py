"""五目ならべ — 完成: 待ったと勝ち筋の表示、状態は class Game にまとめる。"""

import random
from collections import defaultdict
from itertools import product

SIZE = 15
GOAL = 5
NEAR = 2

EMPTY = 0
BLACK = 1
WHITE = 2

MARKS = {
    EMPTY: "・",
    BLACK: "●",
    WHITE: "○",
}

WINNING_MARKS = {                           # ←
    BLACK: "◆",
    WHITE: "◇",
}

NAMES = {
    BLACK: "黒",
    WHITE: "白",
}

RESULT_TEXT = {                             # ←
    "black": "黒の勝ちです！",
    "white": "白（CPU）の勝ちです。",
    "draw": "盤が埋まりました。引き分けです。",
    "quit": "やめました。",
}

COLUMNS = "abcdefghijklmno"

# 線は4本ぶんでいい。逆向きは同じ線を反対からたどるだけなので、
# (0, -1) や (-1, 0) は数えるときに符号を反転して使う
DIRECTIONS = [
    (0, 1),   # →
    (1, 0),   # ↓
    (1, 1),   # ↘
    (1, -1),  # ↙
]

WIN_SCORE = 100000

# (並ぶ数, 空いている端の数) → 点数。
# 両端をふさがれた形は辞書に無い ＝ 0 点で、伸ばしても勝てない
SHAPE_POINTS = {
    (4, 2): 10000,   # 両端が空いた4。もう止めようがない
    (4, 1): 1000,    # 片端が空いた4。次の手で勝てる
    (3, 2): 500,     # 両端が空いた3。放っておくと (4, 2) になる
    (3, 1): 50,
    (2, 2): 20,
    (2, 1): 5,
    (1, 2): 2,
    (1, 1): 1,
}


def make_board():
    """空の盤面を作って返す。"""
    return [[EMPTY] * SIZE for _ in range(SIZE)]


def board_text(board, winning=()):          # ←
    """盤面を表示用の文字列にして返す。winning の石は ◆ ◇ で示す。"""
    lines = ["   " + "  ".join(COLUMNS)]
    for i, row in enumerate(board):
        cells = []
        for j, cell in enumerate(row):
            if (i, j) in winning:                           # ←
                cells.append(WINNING_MARKS[cell])           # ←
            else:                                           # ←
                cells.append(MARKS[cell])
        lines.append(f"{i + 1:2d} " + " ".join(cells))
    return "\n".join(lines)


def empty_cells(board):
    """空いているマスの座標を、(行, 列) のリストにして返す。"""
    return [(r, c) for r, c in product(range(SIZE), range(SIZE)) if board[r][c] == EMPTY]


def candidate_cells(board):
    """CPU が考える価値のあるマスだけを返す。石から NEAR マス以内の空きマス。"""
    stones = [(r, c) for r, c in product(range(SIZE), range(SIZE)) if board[r][c] != EMPTY]

    if not stones:                                          # まっさらな盤なら真ん中
        return [(SIZE // 2, SIZE // 2)]

    near = set()
    for r, c in stones:
        for dr, dc in product(range(-NEAR, NEAR + 1), repeat=2):
            if is_empty(board, r + dr, c + dc):
                near.add((r + dr, c + dc))

    return sorted(near)                                     # 集合は順番がないので並べ直す


def parse_move(text):
    """"h8" のような入力を (行, 列) に直して返す。読めなければ None。"""
    text = text.strip().lower()

    if len(text) < 2:
        return None

    col = COLUMNS.find(text[0])
    if col < 0:
        return None

    if not text[1:].isdigit():
        return None

    row = int(text[1:]) - 1
    if not 0 <= row < SIZE:
        return None

    return row, col


def move_text(move):
    """(行, 列) を "h8" のような表示に直して返す。"""
    row, col = move
    return f"{COLUMNS[col]}{row + 1}"


def is_empty(board, r, c):
    """(r, c) が盤の中の空きマスなら True。盤の外は False。"""
    return 0 <= r < SIZE and 0 <= c < SIZE and board[r][c] == EMPTY


def stones_from(board, row, col, dr, dc):
    """(row, col) の隣から (dr, dc) 方向へ、盤の端まで石を1つずつ返す。"""
    r = row + dr
    c = col + dc

    while 0 <= r < SIZE and 0 <= c < SIZE:
        yield board[r][c]
        r += dr
        c += dc


def count_same(board, row, col, dr, dc, player):
    """(row, col) の隣から (dr, dc) 方向へ、player の石が何個続くかを返す。"""
    count = 0

    for stone in stones_from(board, row, col, dr, dc):
        if stone != player:
            break
        count += 1

    return count


def line_shape(board, row, col, dr, dc, player):
    """その線の形を (並ぶ数, 空いている端の数) で返す。端の数は 0・1・2。"""
    forward = count_same(board, row, col, dr, dc, player)
    backward = count_same(board, row, col, -dr, -dc, player)

    # 続いている石の、さらに1つ先が空いているか
    ends = 0
    if is_empty(board, row + dr * (forward + 1), col + dc * (forward + 1)):
        ends += 1
    if is_empty(board, row - dr * (backward + 1), col - dc * (backward + 1)):
        ends += 1

    return 1 + forward + backward, ends


def shapes(board, row, col, player):
    """(row, col) の石を含む4本の線の形を、1つずつ返す。"""
    for dr, dc in DIRECTIONS:
        yield line_shape(board, row, col, dr, dc, player)


def winning_line(board, row, col, player):  # ←
    """(row, col) の石で 5 個以上そろっているなら、その石の座標を並べて返す。

    そろっていなければ空リスト。
    """
    for dr, dc in DIRECTIONS:
        forward = count_same(board, row, col, dr, dc, player)
        backward = count_same(board, row, col, -dr, -dc, player)
        length = 1 + forward + backward

        if length >= GOAL:
            # いちばん手前の石まで戻ってから、線に沿って並べ直す
            start_row = row - dr * backward
            start_col = col - dc * backward
            return [(start_row + dr * i, start_col + dc * i) for i in range(length)]

    return []


def opponent(player):
    """相手の色を返す。"""
    return WHITE if player == BLACK else BLACK


def shape_counts(board, row, col, player):
    """(row, col) に player が置いたときにできる形を数えて、{形: 本数} で返す。"""
    counts = defaultdict(int)                               # 無いキーは 0 から始まる辞書

    board[row][col] = player                                # 置いてみて
    for shape in shapes(board, row, col, player):
        counts[shape] += 1
    board[row][col] = EMPTY                                 # 元に戻す

    return counts


def shape_score(counts):
    """形の集まりを点数にして返す。5 個そろう形があれば、それだけで最高点。"""
    total = 0

    for (length, ends), n in counts.items():
        if length >= GOAL:
            return WIN_SCORE
        total += SHAPE_POINTS.get((length, ends), 0) * n    # 辞書に無い形は 0 点

    return total


def score_move(board, move, player):
    """その手の点数を返す。大きいほど良い手。"""
    row, col = move

    mine = shape_score(shape_counts(board, row, col, player))
    yours = shape_score(shape_counts(board, row, col, opponent(player)))

    # 同じ価値なら攻めたいので、守りだけ 1 割引く
    return mine * 10 + yours * 9


def choose_move(board, player):
    """CPU の手を1つ選んで (行, 列) で返す。"""
    scores = {move: score_move(board, move, player) for move in candidate_cells(board)}
    best = max(scores.values())

    # 最高点が並んだときは、その中から気まぐれに選ぶ
    return random.choice([move for move, score in scores.items() if score == best])


class Game:                                 # ←
    """1局ぶんの状態。盤・手番・打った手・結果をまとめて持つ。"""

    def __init__(self):
        self.board = make_board()
        self.player = BLACK                                 # 黒が先手
        self.history = []                                   # 打たれた手を古い順に
        self.winning = []                                   # 勝ちを決めた石の座標
        self.result = None                                  # 決着したら文字列が入る

    def place(self, move):
        """今の手番の石を置く。置けなければ False。"""
        row, col = move

        if self.board[row][col] != EMPTY:
            return False

        self.board[row][col] = self.player
        self.history.append(move)

        line = winning_line(self.board, row, col, self.player)
        if line:
            self.winning = line
            self.result = "black" if self.player == BLACK else "white"
        elif not empty_cells(self.board):
            self.result = "draw"
        else:
            self.player = opponent(self.player)

        return True

    def undo(self):
        """最後の1手を取り消す。戻す手が無ければ False。"""
        if not self.history:
            return False

        row, col = self.history.pop()
        self.board[row][col] = EMPTY

        # 黒が先手なので、残った手数が偶数なら次は黒
        self.player = BLACK if len(self.history) % 2 == 0 else WHITE
        self.winning = []
        self.result = None

        return True

    def cpu_move(self):
        """CPU の手を選んで置く。置いた手を返す。"""
        move = choose_move(self.board, self.player)
        self.place(move)
        return move

    def render(self):
        """盤面と手数を、端末に出す文字列にして返す。"""
        return f"{board_text(self.board, self.winning)}\n\n{len(self.history)} 手目"


def ask_move(game):                         # ←
    """人に手を聞いて (行, 列) を返す。q でやめたなら None。"""
    while True:
        answer = input(f"\n{NAMES[game.player]}の番です（例: h8、u で待った、q でやめる）> ")
        answer = answer.strip().lower()

        if answer == "q":
            return None

        if answer == "u":
            if not game.history:
                print("まだ戻せません。")
                continue
            game.undo()                                     # CPU の手
            game.undo()                                     # 自分の手
            print()
            print(game.render())
            continue

        move = parse_move(answer)
        if move is None:
            print("「列＋行」で入れてください（a1 〜 o15）。")
            continue

        row, col = move
        if game.board[row][col] != EMPTY:
            print("そこには もう石があります。")
            continue

        return move


def main():
    game = Game()                           # ←

    print("あなたは黒 ●、白 ○ は CPU です。")
    print("h8 のように置く場所を入れます。u で待った、q でやめる。")

    while game.result is None:
        print()
        print(game.render())

        if game.player == BLACK:
            move = ask_move(game)
            if move is None:
                game.result = "quit"
                break
            game.place(move)
        else:
            move = game.cpu_move()
            print(f"\n白（CPU）は {move_text(move)} に置きました。")

    print()
    print(game.render())
    print(f"\n{RESULT_TEXT[game.result]}")


if __name__ == "__main__":
    main()
