"""テトリス（ブラウザ版）

CLI 版（g04-tetris/main.py）と盤面まわりは同じ。
can_place() / place() / rotate() / clear_lines() / spawn() は
1 文字も変えずにそのまま持ってきている。

違うのは入口と出口だけ。
入口は os.read() の代わりにキーイベント、出口は文字の盤面の代わりに 200 個の <div>。
時間を進めるのも select の時間切れではなく、asyncio の待ち合わせになっている。
"""

import asyncio
import random
import time

from pyscript import document, when

WIDTH = 10
HEIGHT = 20
FALL_SECONDS = 0.8

SCORES = [0, 100, 300, 500, 800]

SHAPES = {  # CLI 版と同じ 7 種類
    "I": [[1, 1, 1, 1]],
    "O": [[1, 1],
          [1, 1]],
    "T": [[0, 1, 0],
          [1, 1, 1]],
    "S": [[0, 1, 1],
          [1, 1, 0]],
    "Z": [[1, 1, 0],
          [0, 1, 1]],
    "J": [[1, 0, 0],
          [1, 1, 1]],
    "L": [[0, 0, 1],
          [1, 1, 1]],
}

KEYS = {  # ブラウザが送ってくる名前 → CLI 版と同じ呼び名
    "ArrowLeft": "left",
    "ArrowRight": "right",
    "ArrowUp": "up",
    "ArrowDown": "down",
    " ": "drop",
}


# --- ここから 5 つは CLI 版からそのまま ---

def make_board():
    """空の盤面を作って返す。0 が空きマス。"""
    return [[0] * WIDTH for _ in range(HEIGHT)]


def can_place(board, shape, x, y):
    """はみ出さず、ほかのブロックとも重ならないなら True。"""
    for dy in range(len(shape)):
        for dx in range(len(shape[dy])):
            if shape[dy][dx] == 0:
                continue

            bx = x + dx
            by = y + dy

            if not (0 <= bx < WIDTH and 0 <= by < HEIGHT):
                return False
            if board[by][bx] != 0:
                return False

    return True


def place(board, shape, x, y, name):
    """ミノを書き込んだ新しい盤面を返す。元の盤面は変えない。"""
    new_board = [row[:] for row in board]

    for dy in range(len(shape)):
        for dx in range(len(shape[dy])):
            if shape[dy][dx] != 0:
                new_board[y + dy][x + dx] = name

    return new_board


def rotate(shape):
    """上下をひっくり返してから、行と列を入れ替える。"""
    return [list(row) for row in zip(*reversed(shape))]


def clear_lines(board):
    """埋まった行を取り除き、そのぶん空の行を上に足す。"""
    kept = []

    for row in board:
        if 0 in row:
            kept.append(row)

    cleared = HEIGHT - len(kept)

    for _ in range(cleared):
        kept.insert(0, [0] * WIDTH)

    return kept, cleared


def spawn():
    """ミノの名前・形・出てくる位置（横）を返す。"""
    name = random.choice(list(SHAPES))
    shape = SHAPES[name]
    x = WIDTH // 2 - len(shape[0]) // 2
    return name, shape, x


# --- ここから下がブラウザ版だけの部分 ---

grid = document.querySelector("#grid")
score_label = document.querySelector("#score")
lines_label = document.querySelector("#lines")
message = document.querySelector("#message")
start_button = document.querySelector("#start-btn")

cells = []  # 200 個のマス。作るのは一度だけで、あとは色を塗り替える
for _ in range(WIDTH * HEIGHT):
    cell = document.createElement("div")
    cell.className = "cell"
    grid.appendChild(cell)
    cells.append(cell)

# CLI 版では素の変数だった board / x / y / score を、辞書にまとめて持つ。
# キーイベントから呼ばれるたびに中断・再開するので、ループの中には置けない。
state = {
    "board": make_board(),
    "name": "T",
    "shape": SHAPES["T"],
    "x": 4,
    "y": 0,
    "score": 0,
    "lines": 0,
    "playing": False,
    "next_fall": 0.0,
}


def draw():
    """CLI 版の render() にあたる。文字列ではなく、マスの色を塗り替える。"""
    if state["playing"]:
        view = place(state["board"], state["shape"], state["x"], state["y"], state["name"])
    else:
        view = state["board"]

    for y in range(HEIGHT):
        row = view[y]
        for x in range(WIDTH):
            value = row[x]
            cell = cells[y * WIDTH + x]  # 1 本のリストを 2 次元として使う
            cell.className = "cell" if value == 0 else f"cell c-{value}"

    score_label.textContent = str(state["score"])
    lines_label.textContent = str(state["lines"])


def move(dx):
    """左右に動かす。置けないときは何もしない。"""
    if can_place(state["board"], state["shape"], state["x"] + dx, state["y"]):
        state["x"] += dx
        draw()


def turn():
    """回して、置けると分かってから採用する。"""
    turned = rotate(state["shape"])
    if can_place(state["board"], turned, state["x"], state["y"]):
        state["shape"] = turned
        draw()


def lock():
    """落ちられなくなったミノを盤面に焼き付けて、次のミノを出す。"""
    board = place(state["board"], state["shape"], state["x"], state["y"], state["name"])
    board, cleared = clear_lines(board)

    state["board"] = board
    state["lines"] += cleared
    state["score"] += SCORES[cleared]

    name, shape, x = spawn()
    state["name"] = name
    state["shape"] = shape
    state["x"] = x
    state["y"] = 0

    if not can_place(board, shape, x, 0):  # 出す場所がもう無い
        finish()


def fall():
    """1 マス落とす。落ちられなければ固定。CLI 版の "down" の枝と同じ。"""
    state["next_fall"] = time.time() + FALL_SECONDS

    if can_place(state["board"], state["shape"], state["x"], state["y"] + 1):
        state["y"] += 1
    else:
        lock()

    draw()


def hard_drop():
    """一番下まで一気に落とす。次の tick でそのまま固定される。"""
    while can_place(state["board"], state["shape"], state["x"], state["y"] + 1):
        state["y"] += 1

    state["next_fall"] = time.time()
    draw()


def finish():
    """ゲームオーバー。"""
    state["playing"] = False
    message.textContent = f"ゲームオーバー — スコア {state['score']}"
    message.hidden = False
    start_button.textContent = "もう一度"
    start_button.disabled = False


async def tick():
    """時間を進める係。CLI 版の select の時間切れにあたる。"""
    while state["playing"]:
        await asyncio.sleep(0.05)  # 0.05 秒ごとに「もう落ちる時刻か？」と見に来る
        if state["playing"] and time.time() >= state["next_fall"]:
            fall()


def start():
    state["board"] = make_board()
    name, shape, x = spawn()
    state["name"] = name
    state["shape"] = shape
    state["x"] = x
    state["y"] = 0
    state["score"] = 0
    state["lines"] = 0
    state["playing"] = True
    state["next_fall"] = time.time() + FALL_SECONDS

    message.hidden = True
    start_button.disabled = True
    draw()

    asyncio.ensure_future(tick())  # 待ち続ける係を裏で走らせる


def act(key):
    """CLI 版の while ループの中身と同じ振り分け。"""
    if not state["playing"]:
        return

    if key == "left":
        move(-1)
    elif key == "right":
        move(1)
    elif key == "up":
        turn()
    elif key == "down":
        fall()
    elif key == "drop":
        hard_drop()


@when("keydown", "body")
def on_key(event):
    key = KEYS.get(event.key)
    if key is None:
        return

    event.preventDefault()  # 矢印とスペースでページが動かないように
    act(key)


@when("click", "#start-btn")
def on_start(event):
    start()


@when("click", "#left-btn")
def on_left(event):
    act("left")


@when("click", "#right-btn")
def on_right(event):
    act("right")


@when("click", "#turn-btn")
def on_turn(event):
    act("up")


@when("click", "#down-btn")
def on_down(event):
    act("down")


@when("click", "#drop-btn")
def on_drop(event):
    act("drop")


# Pyodide の読み込みが終わってから実行される＝ここが準備完了の合図
document.querySelector("#loading").hidden = True
start_button.disabled = False
draw()
