"""五目ならべ（ブラウザ版）

CLI 版（g10-gomoku/main.py）とルールも CPU もまったく同じ。
定数 6 つと make_board() / empty_cells() / candidate_cells() / move_text() / is_empty() /
stones_from() / count_same() / line_shape() / shapes() / winning_line() / opponent() /
shape_counts() / shape_score() / score_move() / choose_move()、そして class Game を、
ステップの目印コメント（# ←）を外しただけで、1 文字も変えずに持ってきている。

持ってこなかったのは board_text() と parse_move() と ask_move() と main()、
それに Game.render() だけ。つまり違うのは入口と出口で、
入口は "h8" の文字入力ではなく交点のクリック、
出口は文字の盤面ではなく 225 個の <div> になっている。

ブラウザ版だけの追加は 3 つ——碁盤の星、最後の手の赤い点、そして「2人で交互」モード。
"""

import asyncio
import random
from collections import defaultdict
from itertools import product

from pyscript import document, when


# --- ここから class Game まで、CLI 版（g10-gomoku/main.py）からそのまま ---


SIZE = 15
GOAL = 5
NEAR = 2


EMPTY = 0
BLACK = 1
WHITE = 2


COLUMNS = "abcdefghijklmno"


DIRECTIONS = [
    (0, 1),   # →
    (1, 0),   # ↓
    (1, 1),   # ↘
    (1, -1),  # ↙
]


WIN_SCORE = 100000


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


def winning_line(board, row, col, player):
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


class Game:
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


# --- ここから下はブラウザ版だけ。CLI 版の ask_move() と main() にあたる ---

CPU_WAIT = 0.35        # CPU が考えているように見せるための間

STARS = {(3, 3), (3, 11), (7, 7), (11, 3), (11, 11)}   # 碁盤の星。飾りだけ

MARKS = {BLACK: "●", WHITE: "○"}

board_grid = document.querySelector("#board")
turn_label = document.querySelector("#turn")
moves_label = document.querySelector("#moves")
message = document.querySelector("#message")
undo_button = document.querySelector("#undo-btn")
start_button = document.querySelector("#start-btn")
two_button = document.querySelector("#mode-two")
cpu_button = document.querySelector("#mode-cpu")

cells = []  # 225 個のマス。作るのは一度だけで、あとは class を塗り替える
for index in range(SIZE * SIZE):
    cell = document.createElement("div")
    cell.className = "cell"
    cell.setAttribute("data-index", str(index))  # クリックされた場所を知るための目印
    board_grid.appendChild(cell)
    cells.append(cell)

# 1局ぶんの状態は Game が全部持っている。
# ブラウザ側が覚えているのは「相手は CPU か」だけ。
game = Game()
vs_cpu = True


def set_message(text):
    message.textContent = text


def cpu_thinking():
    """CPU の手番かどうか。True のあいだはクリックを受けない。"""
    return vs_cpu and game.player == WHITE and game.result is None


def draw():
    """CLI 版の render() にあたる。文字列ではなく、マスの class を塗り替える。"""
    winning = set(game.winning)
    last = game.history[-1] if game.history else None

    for index, cell in enumerate(cells):
        pos = divmod(index, SIZE)  # 1本のリストを2次元として使う
        row, col = pos
        names = ["cell"]

        value = game.board[row][col]
        if value == BLACK:
            names.append("b")
        elif value == WHITE:
            names.append("w")
        elif pos in STARS:
            names.append("star")

        if pos in winning:
            names.append("win")
        if pos == last:
            names.append("last")

        cell.className = " ".join(names)

    # 自分の番のあいだだけ、カーソルと薄い石を出すための目印
    if game.result is None and not cpu_thinking():
        board_grid.className = f"turn-{'b' if game.player == BLACK else 'w'}"
    else:
        board_grid.className = ""

    moves_label.textContent = str(len(game.history))
    undo_button.disabled = not game.history

    if game.result is not None:
        turn_label.textContent = "終局"
    elif cpu_thinking():
        turn_label.textContent = "○ が考え中"
    else:
        turn_label.textContent = f"{MARKS[game.player]} の番"


def finish():
    """決着したときの一言。CLI 版の RESULT_TEXT にあたる。"""
    if game.result == "draw":
        set_message(f"盤が埋まりました。引き分けです（{len(game.history)} 手）")
        return

    winner = BLACK if game.result == "black" else WHITE
    who = "（CPU）" if vs_cpu and winner == WHITE else ""
    set_message(f"{MARKS[winner]}{who} の勝ち！　{len(game.history)} 手")


def after_move(player, move):
    """1手ぶんの後始末。打った人と手を表示して、次が CPU なら考えさせる。"""
    set_message(f"{MARKS[player]} {move_text(move)}")
    draw()

    if game.result is not None:
        finish()
    elif cpu_thinking():
        asyncio.ensure_future(cpu_turn())


async def cpu_turn():
    """CPU の手番。CLI 版との違いは、間を置くことだけ。"""
    await asyncio.sleep(CPU_WAIT)

    if not cpu_thinking():  # 待っているあいだに「待った」が押されたかもしれない
        return

    player = game.player
    after_move(player, game.cpu_move())


def start():
    global game

    # 状態は Game が全部持っているので、作り直すだけで初期化になる
    game = Game()
    set_message("")
    draw()


def set_mode(cpu):
    global vs_cpu

    vs_cpu = cpu
    two_button.className = "mode" if cpu else "mode is-on"
    cpu_button.className = "mode is-on" if cpu else "mode"
    start()


@when("click", "#board")
def on_board_click(event):
    """交点のクリックが CLI 版の input() にあたる。"""
    index = event.target.getAttribute("data-index")  # 盤の枠なら None
    if index is None or game.result is not None or cpu_thinking():
        return

    move = divmod(int(index), SIZE)
    row, col = move
    if game.board[row][col] != EMPTY:  # 石があるマスは黙って無視する
        return

    player = game.player
    game.place(move)
    after_move(player, move)


@when("click", "#undo-btn")
def on_undo(event):
    """待った。CLI 版の u と同じで、CPU の手と自分の手をまとめて戻す。"""
    if not game.history:
        return

    game.undo()
    if vs_cpu and game.player == WHITE and game.history:
        game.undo()

    set_message("")
    draw()


@when("click", "#start-btn")
def on_start(event):
    start()


@when("click", "#mode-two")
def on_mode_two(event):
    set_mode(False)


@when("click", "#mode-cpu")
def on_mode_cpu(event):
    set_mode(True)


# Pyodide の読み込みが終わってから実行される＝ここが準備完了の合図
document.querySelector("#loading").hidden = True
start_button.disabled = False
draw()
