"""オセロ（ブラウザ版）

CLI 版（g05-othello/main.py）とルールまわりは同じ。
make_board() / opponent() / flips_in_direction() / flips_at() / valid_moves() /
apply_move() / count_stones() / move_name() / result_text() は
1 文字も変えずにそのまま持ってきている。

持ってこなかったのは board_text() と parse_move() と main() だけ。
つまり違うのは入口と出口で、入口は "d3" の文字入力ではなくマスのクリック、
出口は文字の盤面ではなく 64 個の <div> になっている。

ブラウザ版だけの追加として、白をコンピュータに任せるモードがある（choose_move）。
"""

import asyncio

from pyscript import document, when

SIZE = 8

EMPTY = 0
BLACK = 1
WHITE = 2

MARKS = {
    EMPTY: "・",
    BLACK: "●",
    WHITE: "○",
}

DIRECTIONS = [
    (-1, -1), (-1, 0), (-1, 1),
    (0, -1),           (0, 1),
    (1, -1),  (1, 0),  (1, 1),
]

CPU_WAIT = 0.55  # コンピュータが考えているように見せるための間
PASS_WAIT = 0.9  # パスの表示を読む時間


# --- ここから 9 つは CLI 版からそのまま ---

def make_board():
    """初期配置の盤面を作って返す。中央4マスに石が置かれた状態。"""
    board = [[EMPTY] * SIZE for _ in range(SIZE)]
    board[3][3] = WHITE
    board[3][4] = BLACK
    board[4][3] = BLACK
    board[4][4] = WHITE
    return board


def count_stones(board):
    """石の数を (黒, 白) のタプルで返す。"""
    black = sum(row.count(BLACK) for row in board)
    white = sum(row.count(WHITE) for row in board)
    return black, white


def opponent(player):
    """相手の色を返す。"""
    return WHITE if player == BLACK else BLACK


def flips_in_direction(board, row, col, dr, dc, player):
    """(row, col) に player が置いたとき、(dr, dc) 方向でひっくり返る石の座標リストを返す。

    ひっくり返せないときは空リスト。
    """
    flips = []

    r = row + dr
    c = col + dc

    # 相手の石が続くあいだ、その座標を覚えながら進む
    while 0 <= r < SIZE and 0 <= c < SIZE and board[r][c] == opponent(player):
        flips.append((r, c))
        r += dr
        c += dc

    # 止まった先が自分の石で、間に相手の石が1つ以上あれば「挟めた」
    if flips and 0 <= r < SIZE and 0 <= c < SIZE and board[r][c] == player:
        return flips

    return []


def flips_at(board, row, col, player):
    """(row, col) に player が置いたとき、8方向ぶんまとめてひっくり返る石を返す。"""
    if board[row][col] != EMPTY:
        return []

    flips = []
    for dr, dc in DIRECTIONS:
        flips += flips_in_direction(board, row, col, dr, dc, player)
    return flips


def valid_moves(board, player):
    """置けるマスと、そこに置いたときひっくり返る石を、辞書にして返す。

    キーが (行, 列)、値がひっくり返る石の座標リスト。
    """
    moves = {}
    for row in range(SIZE):
        for col in range(SIZE):
            flips = flips_at(board, row, col, player)
            if flips:
                moves[(row, col)] = flips
    return moves


def move_name(row, col):
    """(2, 3) を "d3" のような表記にして返す。"""
    return chr(ord("a") + col) + str(row + 1)


def apply_move(board, row, col, flips, player):
    """石を置き、flips に入っている石をすべて player の色にする。"""
    board[row][col] = player
    for r, c in flips:
        board[r][c] = player


def result_text(board):
    """終局の結果を文字列にして返す。print はしない。"""
    black, white = count_stones(board)

    if black > white:
        winner = "● の勝ち！"
    elif white > black:
        winner = "○ の勝ち！"
    else:
        winner = "引き分け"

    return f"● {black} - ○ {white}    {winner}"


# --- ここから下がブラウザ版だけの部分 ---

def choose_move(moves):
    """一番たくさんひっくり返せる手を選ぶ。先は読まない。"""
    return max(moves, key=lambda pos: len(moves[pos]))


board_grid = document.querySelector("#board")
black_label = document.querySelector("#black")
white_label = document.querySelector("#white")
turn_label = document.querySelector("#turn")
message = document.querySelector("#message")
two_button = document.querySelector("#mode-two")
cpu_button = document.querySelector("#mode-cpu")

cells = []  # 64 個のマス。作るのは一度だけで、あとは class を塗り替える
for index in range(SIZE * SIZE):
    cell = document.createElement("div")
    cell.className = "cell"
    cell.setAttribute("data-index", str(index))  # クリックされた場所を知るための目印
    board_grid.appendChild(cell)
    cells.append(cell)

# CLI 版では素の変数だった board / player / passes を、辞書にまとめて持つ。
# クリックのたびに中断・再開するので、ループの中には置けない。
state = {
    "board": make_board(),
    "player": BLACK,
    "moves": {},
    "passes": 0,
    "playing": False,
    "vs_cpu": True,
}


def set_message(text):
    message.textContent = text
    message.hidden = not text


def cpu_thinking():
    """コンピュータの手番かどうか。True のあいだはクリックを受けない。"""
    return state["vs_cpu"] and state["player"] == WHITE


def draw():
    """CLI 版の board_text() にあたる。文字列ではなく、マスの class を塗り替える。"""
    board = state["board"]
    show_hints = state["playing"] and not cpu_thinking()

    for index, cell in enumerate(cells):
        row, col = divmod(index, SIZE)  # 1本のリストを2次元として使う
        value = board[row][col]

        if value == BLACK:
            cell.className = "cell b"
        elif value == WHITE:
            cell.className = "cell w"
        elif show_hints and (row, col) in state["moves"]:
            cell.className = "cell hint"
        else:
            cell.className = "cell"

    black, white = count_stones(board)
    black_label.textContent = str(black)
    white_label.textContent = str(white)

    if not state["playing"]:
        turn_label.textContent = "終局"
    elif cpu_thinking():
        turn_label.textContent = "○ が考え中"
    else:
        turn_label.textContent = f"{MARKS[state['player']]} の番"


def play(pos):
    """石を置いて手番を渡す。CLI 版の while ループの後半と同じ。"""
    row, col = pos
    flips = state["moves"][pos]

    apply_move(state["board"], row, col, flips, state["player"])
    set_message(f"{MARKS[state['player']]} {move_name(row, col)} → {len(flips)} 枚ひっくり返した")

    state["player"] = opponent(state["player"])


def finish():
    """両者とも置けなくなった＝終局。"""
    state["playing"] = False
    state["moves"] = {}
    set_message(result_text(state["board"]))
    draw()


async def advance():
    """手番を進める係。CLI 版の while ループの前半（パス判定）がここに来ている。

    人が打つ番になったら return して、クリックを待つ。
    """
    while state["playing"]:
        state["moves"] = valid_moves(state["board"], state["player"])
        draw()

        if not state["moves"]:
            state["passes"] += 1
            if state["passes"] == 2:
                finish()
                return

            set_message(f"{MARKS[state['player']]} は置ける場所がないのでパス")
            state["player"] = opponent(state["player"])
            await asyncio.sleep(PASS_WAIT)
            continue

        state["passes"] = 0  # 置けたので、パスの連続は途切れた

        if not cpu_thinking():
            return  # ここから先は人のクリック待ち

        await asyncio.sleep(CPU_WAIT)
        play(choose_move(state["moves"]))


def start():
    state["board"] = make_board()
    state["player"] = BLACK
    state["moves"] = {}
    state["passes"] = 0
    state["playing"] = True

    set_message("")
    asyncio.ensure_future(advance())


def set_mode(vs_cpu):
    state["vs_cpu"] = vs_cpu
    two_button.className = "mode" if vs_cpu else "mode is-on"
    cpu_button.className = "mode is-on" if vs_cpu else "mode"
    start()


@when("click", "#board")
def on_board_click(event):
    """マスのクリックが CLI 版の input() にあたる。"""
    index = event.target.getAttribute("data-index")  # 盤の隙間なら None
    if index is None or not state["playing"] or cpu_thinking():
        return

    pos = divmod(int(index), SIZE)
    if pos not in state["moves"]:  # 置けないマスは黙って無視する
        return

    play(pos)
    asyncio.ensure_future(advance())


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
document.querySelector("#start-btn").disabled = False
start()
