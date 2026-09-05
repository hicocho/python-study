"""マインスイーパ（ブラウザ版）

CLI 版（g06-minesweeper/main.py）とルールまわりは同じ。
all_cells() / around() / place_mines() / count_around() / open_cell() /
is_clear() / move_name() は 1 文字も変えずにそのまま持ってきている。

持ってこなかったのは board_text() と parse_move() と main() だけ。
つまり違うのは入口と出口で、入口は "d3" の文字入力ではなくマスのクリック、
出口は文字の盤面ではなく 81 個の <div> になっている。

ブラウザ版だけの追加として、右クリック（またはモード切り替え）で旗を立てられる。
"""

import random

from pyscript import document, when

SIZE = 9
MINE_COUNT = 10

DIRECTIONS = [
    (-1, -1), (-1, 0), (-1, 1),
    (0, -1),           (0, 1),
    (1, -1),  (1, 0),  (1, 1),
]


# --- ここから 7 つは CLI 版からそのまま ---

def all_cells():
    """盤の全マスの座標をリストにして返す。"""
    return [(row, col) for row in range(SIZE) for col in range(SIZE)]


def around(row, col):
    """(row, col) 自身と、その周り8マスの座標の集合を返す。"""
    cells = {(row, col)}
    for dr, dc in DIRECTIONS:
        cells.add((row + dr, col + dc))
    return cells


def place_mines(count, safe):
    """safe に入っているマスを避けて、地雷を count 個ランダムに置く。"""
    candidates = [cell for cell in all_cells() if cell not in safe]
    return set(random.sample(candidates, count))


def count_around(mines, row, col):
    """(row, col) の周り8マスにある地雷の数を返す。"""
    return sum((row + dr, col + dc) in mines for dr, dc in DIRECTIONS)


def open_cell(mines, opened, row, col):
    """(row, col) を開く。周りに地雷が無ければ、その周り8マスも続けて開く。"""
    # 盤の外なら何もしない
    if not (0 <= row < SIZE and 0 <= col < SIZE):
        return

    # もう開いているなら何もしない（ここで再帰が止まる）
    if (row, col) in opened:
        return

    opened.add((row, col))

    # 周りに地雷が1個でもあれば、そこで打ち止め
    if count_around(mines, row, col) > 0:
        return

    # 周りに地雷が無いマスだけ、8方向へ広げる
    for dr, dc in DIRECTIONS:
        open_cell(mines, opened, row + dr, col + dc)


def is_clear(opened):
    """地雷以外を全部開いたら True。"""
    return len(opened) == SIZE * SIZE - MINE_COUNT


def move_name(row, col):
    """(2, 3) を "d3" のような表記にして返す。"""
    return chr(ord("a") + col) + str(row + 1)


# --- ここから下がブラウザ版だけの部分 ---

board_grid = document.querySelector("#board")
left_label = document.querySelector("#left")
status_label = document.querySelector("#status")
message = document.querySelector("#message")
open_button = document.querySelector("#mode-open")
flag_button = document.querySelector("#mode-flag")

cells = []  # 81 個のマス。作るのは一度だけで、あとは class と文字を塗り替える
for index in range(SIZE * SIZE):
    cell = document.createElement("div")
    cell.className = "cell"
    cell.setAttribute("data-index", str(index))  # クリックされた場所を知るための目印
    board_grid.appendChild(cell)
    cells.append(cell)

# CLI 版では素の変数だった mines / opened / flags を、辞書にまとめて持つ。
# クリックのたびに中断・再開するので、ループの中には置けない。
state = {
    "mines": set(),
    "opened": set(),
    "flags": set(),
    "playing": True,
    "revealed": False,   # 終わって地雷を見せている状態か
    "boom": None,        # 踏んでしまったマス
    "flag_mode": False,  # スマホ用。True のあいだはタップで旗が立つ
}


def set_message(text):
    message.textContent = text
    message.hidden = not text


def draw():
    """CLI 版の board_text() にあたる。文字列ではなく、マスの class を塗り替える。"""
    mines = state["mines"]
    opened = state["opened"]
    flags = state["flags"]
    revealed = state["revealed"]

    for index, cell in enumerate(cells):
        row, col = divmod(index, SIZE)  # 1本のリストを2次元として使う
        pos = (row, col)
        classes = ["cell"]
        text = ""

        if pos in opened:
            classes.append("open")
            count = count_around(mines, row, col)
            if count:
                text = str(count)
                classes.append(f"n{count}")
        elif revealed and pos in mines:
            classes.append("mine")
            text = "✕" if pos in flags else "●"
            if pos == state["boom"]:
                classes.append("boom")
            elif pos in flags:
                classes.append("found")
        elif revealed and pos in flags:
            classes.append("wrong")
            text = "⚑"
        elif pos in flags:
            classes.append("flag")
            text = "⚑"

        cell.className = " ".join(classes)
        cell.textContent = text

    left_label.textContent = str(MINE_COUNT - len(flags))

    if state["playing"]:
        status_label.textContent = f"開いた {len(opened)} / 71"
    else:
        status_label.textContent = "おわり"


def open_at(pos):
    """マスを開く。CLI 版の while ループの後半と同じ。"""
    row, col = pos

    if not state["mines"]:  # 初手だけここを通る。踏んだマスと周りを避けて配置する
        state["mines"] = place_mines(MINE_COUNT, around(row, col))

    if pos in state["mines"]:
        state["playing"] = False
        state["revealed"] = True
        state["boom"] = pos
        set_message(f"{move_name(row, col)} は地雷でした。ゲームオーバー")
        return

    open_cell(state["mines"], state["opened"], row, col)

    if is_clear(state["opened"]):
        state["playing"] = False
        state["revealed"] = True
        state["flags"] = set(state["mines"])  # 残りは全部地雷なので旗を立てて見せる
        set_message("地雷以外を全部開きました。クリア！")


def toggle_flag(pos):
    """旗を立てる／外す。CLI 版の fd3 にあたる。"""
    if pos in state["opened"]:
        return

    if pos in state["flags"]:
        state["flags"].remove(pos)
    else:
        state["flags"].add(pos)


def cell_at(event):
    """クリックされたマスの座標を返す。盤の隙間なら None。"""
    index = event.target.getAttribute("data-index")
    if index is None:
        return None
    return divmod(int(index), SIZE)


def start():
    state["mines"] = set()
    state["opened"] = set()
    state["flags"] = set()
    state["playing"] = True
    state["revealed"] = False
    state["boom"] = None

    set_message("")
    draw()


def set_mode(flag_mode):
    state["flag_mode"] = flag_mode
    open_button.className = "mode is-on" if not flag_mode else "mode"
    flag_button.className = "mode is-on" if flag_mode else "mode"


@when("click", "#board")
def on_board_click(event):
    """マスのクリックが CLI 版の input() にあたる。"""
    pos = cell_at(event)
    if pos is None or not state["playing"]:
        return

    if state["flag_mode"]:
        toggle_flag(pos)
    elif pos in state["flags"]:  # 旗の上は開けない
        set_message("旗が立っています。外してから開いてください")
    else:
        set_message("")
        open_at(pos)

    draw()


@when("contextmenu", "#board")
def on_board_right_click(event):
    """右クリックで旗。ブラウザのメニューは出さない。"""
    event.preventDefault()

    pos = cell_at(event)
    if pos is None or not state["playing"]:
        return

    toggle_flag(pos)
    draw()


@when("click", "#start-btn")
def on_start(event):
    start()


@when("click", "#mode-open")
def on_mode_open(event):
    set_mode(False)


@when("click", "#mode-flag")
def on_mode_flag(event):
    set_mode(True)


# Pyodide の読み込みが終わってから実行される＝ここが準備完了の合図
document.querySelector("#loading").hidden = True
document.querySelector("#start-btn").disabled = False
start()
