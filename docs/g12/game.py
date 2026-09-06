"""迷路（ブラウザ版）

CLI 版（g12-maze/main.py）と迷路の作り方・最短路・ヒントはまったく同じ。
定数 4 つと make_grid() / carve() / make_maze() / neighbors() / shortest_path() / next_step()、
そして class Game を、ステップの目印コメント（# ←）を外しただけで 1 文字も変えずに持ってきている。

持ってこなかったのは maze_text() と raw_mode() / read_key() と parse_args() / main()、
それに Game.render() だけ。つまり違うのは入口と出口で、
入口は termios の生キー入力ではなくキーイベントとボタン、
出口は ██ の文字列ではなく N×N 個の <div>。
"""

import random
import sys
from collections import deque

from pyscript import document, when

# CLI 版と同じく、大きい迷路でも再帰が途中で止まらないように広げておく
sys.setrecursionlimit(10000)


# --- ここから class Game まで、CLI 版（g12-maze/main.py）からそのまま ---


SIZE = 21                                   # 奇数。壁と通路が 1 マスおきに並ぶ


WALL = "#"
PATH = " "


DIRECTIONS = [(0, 2), (2, 0), (0, -2), (-2, 0)]


MOVES = {
    "up": (-1, 0),
    "down": (1, 0),
    "left": (0, -1),
    "right": (0, 1),
}


def make_grid(size: int) -> list[list[str]]:
    """全部が壁の盤を作って返す。"""
    return [[WALL] * size for _ in range(size)]


def carve(grid: list[list[str]], row: int, col: int) -> None:
    """(row, col) を通路にして、掘れる方向へ再帰的に掘り進む。"""
    size = len(grid)
    grid[row][col] = PATH

    directions = DIRECTIONS[:]                              # 元のリストは崩さない
    random.shuffle(directions)

    for dr, dc in directions:
        nr, nc = row + dr, col + dc
        if 0 < nr < size - 1 and 0 < nc < size - 1 and grid[nr][nc] == WALL:
            grid[row + dr // 2][col + dc // 2] = PATH        # 間の壁を抜く
            carve(grid, nr, nc)                             # 掘った先からまた掘る


def make_maze(size: int = SIZE) -> list[list[str]]:
    """穴掘り法で迷路を作って返す。左上 (1, 1) から掘り始める。"""
    grid = make_grid(size)
    carve(grid, 1, 1)
    return grid


def neighbors(grid: list[list[str]], pos: tuple[int, int]):
    """pos の上下左右のうち、通路になっているマスを 1 つずつ返す。"""
    row, col = pos
    for dr, dc in MOVES.values():
        if grid[row + dr][col + dc] == PATH:
            yield row + dr, col + dc


def shortest_path(grid: list[list[str]], start: tuple[int, int], goal: tuple[int, int]) -> list[tuple[int, int]]:
    """start から goal への最短経路を、通るマスのリストで返す（両端を含む）。届かなければ空リスト。"""
    queue = deque([start])                                  # これから見るマス。先に入れたものを先に見る
    came_from = {start: None}                               # そのマスへ「どこから来たか」

    while queue:
        pos = queue.popleft()
        if pos == goal:
            break
        for nxt in neighbors(grid, pos):
            if nxt not in came_from:                        # 初めて着いたマスだけ
                came_from[nxt] = pos
                queue.append(nxt)

    if goal not in came_from:
        return []

    path = []                                               # goal から来た道を逆にたどる
    pos = goal
    while pos is not None:
        path.append(pos)
        pos = came_from[pos]
    path.reverse()
    return path


def next_step(grid: list[list[str]], pos: tuple[int, int], goal: tuple[int, int]) -> tuple[int, int] | None:
    """pos からゴールへ向かう最短路の、次の 1 マスを返す。もうゴールなら None。"""
    path = shortest_path(grid, pos, goal)
    return path[1] if len(path) > 1 else None


class Game:
    """1 回ぶんの迷路。盤・自分の位置・歩数・足あと・ヒントをまとめて持つ。"""

    def __init__(self, size: int = SIZE, seed: int | None = None):
        if seed is not None:
            random.seed(seed)                               # 同じ種なら同じ迷路になる

        self.size = size
        self.maze = make_maze(size)
        self.player = (1, 1)
        self.goal = (size - 2, size - 2)
        self.steps = 0
        self.trail = {self.player}                          # 通ったマス
        self.hint: tuple[int, int] | None = None            # ＊ を出すマス

        self.route = shortest_path(self.maze, self.player, self.goal)
        self.best = len(self.route) - 1                     # 最短の歩数

    @property
    def finished(self) -> bool:
        return self.player == self.goal

    def move(self, direction: str) -> bool:
        """1 マス動く。壁やゴール後なら動かず False。"""
        if self.finished or direction not in MOVES:
            return False

        dr, dc = MOVES[direction]
        nxt = (self.player[0] + dr, self.player[1] + dc)
        if self.maze[nxt[0]][nxt[1]] != PATH:
            return False

        self.player = nxt
        self.steps += 1
        self.trail.add(nxt)
        self.hint = None                                    # 動いたらヒントは消す
        return True

    def show_hint(self) -> tuple[int, int] | None:
        """いまの場所からの次の 1 歩を ＊ で出す。"""
        self.hint = next_step(self.maze, self.player, self.goal)
        return self.hint


# --- ここから下はブラウザ版だけ。CLI 版の read_key() / main() にあたる ---

KEYS = {  # ブラウザが送ってくる名前 → CLI 版と同じ呼び名
    "ArrowUp": "up",
    "ArrowDown": "down",
    "ArrowLeft": "left",
    "ArrowRight": "right",
}

maze_grid = document.querySelector("#maze")
steps_label = document.querySelector("#steps")
best_label = document.querySelector("#best")
message = document.querySelector("#message")
hint_button = document.querySelector("#hint-btn")
new_button = document.querySelector("#new-btn")
size_buttons = document.querySelectorAll(".mode")

# 状態は Game が全部持っている。ブラウザ側が覚えるのは盤の大きさだけ
size = SIZE
game = Game(size)
cells = []


def build():
    """盤の大きさに合わせて <div> を作り直す。迷路を新しくしたときだけ。"""
    global cells

    maze_grid.replaceChildren()
    maze_grid.style.gridTemplateColumns = f"repeat({game.size}, 1fr)"
    cells = []
    for _ in range(game.size * game.size):
        cell = document.createElement("div")
        cell.className = "cell"
        maze_grid.appendChild(cell)
        cells.append(cell)


def draw():
    """CLI 版の render() にあたる。文字列ではなく、マスの class を塗り替える。"""
    route = set(game.route) if game.finished else set()

    for index, cell in enumerate(cells):
        pos = divmod(index, game.size)                      # 1 本のリストを 2 次元として使う
        row, col = pos

        if game.maze[row][col] == WALL:
            names = ["cell", "wall"]
        elif pos in route:
            names = ["cell", "route"]
        elif pos in game.trail:
            names = ["cell", "trail"]
        else:
            names = ["cell", "floor"]

        if pos == game.player:
            names.append("player")
        elif pos == game.goal:
            names.append("goal")
        elif pos == game.hint:
            names.append("hint")

        cell.className = " ".join(names)

    steps_label.textContent = str(game.steps)
    best_label.textContent = str(game.best)
    hint_button.disabled = game.finished

    for button in size_buttons:
        button.className = "mode is-on" if int(button.getAttribute("data-size")) == size else "mode"

    if game.finished:
        message.textContent = f"ゴール！ {game.steps} 歩 / 最短 {game.best} 歩（+{game.steps - game.best}）"


def start():
    global game

    game = Game(size)                                       # 作り直すだけで新しい迷路になる
    message.textContent = ""
    build()
    draw()


def act(direction):
    """CLI 版の main の while ループの中身と同じ振り分け。"""
    if game.move(direction):
        draw()


@when("click", ".pad button")
def on_pad(event):
    act(event.target.getAttribute("data-dir"))


@when("click", ".mode")
def on_size(event):
    global size
    size = int(event.target.getAttribute("data-size"))
    start()


@when("click", "#hint-btn")
def on_hint(event):
    game.show_hint()
    draw()


@when("click", "#new-btn")
def on_new(event):
    start()


@when("keydown", "body")
def on_key(event):
    if event.key == "?":
        game.show_hint()
        draw()
        return

    direction = KEYS.get(event.key)
    if direction is None:
        return

    event.preventDefault()                                  # 矢印でページが動かないように
    act(direction)


# Pyodide の読み込みが終わってから実行される＝ここが準備完了の合図
document.querySelector("#loading").hidden = True
hint_button.disabled = False
new_button.disabled = False
build()
draw()
