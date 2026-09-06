"""迷路レース（ブラウザ版）

CLI 版（g13-maze-race/main.py）と迷路の作り方・3 つの探索・ロボットの歩み・レースのルールはまったく同じ。
定数 6 つと SOLVERS、make_grid() / open_directions() / carve() / make_maze() / neighbors() /
dfs_steps() / bfs_steps() / distance() / astar_steps() / robot_walk() / trace()、そして class Game を、
ステップの目印コメント（# ←）を外しただけで 1 文字も変えずに持ってきている。

持ってこなかったのは maze_text() / show_search() / measure() と raw_mode() / read_key() / race() /
parse_args() / main()、それに Game.render() だけ。違うのは入口と出口で、
入口は select で待つ生キー入力ではなく asyncio の時計とキーイベント、
出口は ░▒ の文字列ではなく N×N 個の <div>。
探索のアニメも CLI 版の show_search() と同じジェネレータを回し、time.sleep の代わりに await で間を置く。
"""

import asyncio
import random
from collections import deque
from heapq import heappop, heappush
from itertools import count

from pyscript import document, when


# --- ここから class Game まで、CLI 版（g13-maze-race/main.py）からそのまま ---


SIZE = 21                                   # 奇数。壁と通路が 1 マスおきに並ぶ
FRAME_SECONDS = 0.02                        # 探索アニメの 1 歩ごとの間
TICK_SECONDS = 0.05                         # ← レース中、キーを待つ時間
ROBOT_EVERY = 3                             # ← ロボットは 3 ティック（0.15 秒）に 1 歩


WALL = "#"
PATH = " "


DIRECTIONS = [(0, 2), (2, 0), (0, -2), (-2, 0)]


MOVES = {
    "up": (-1, 0),
    "down": (1, 0),
    "left": (0, -1),
    "right": (0, 1),
}


RESULT_TEXT = {
    "player": "あなたの勝ち！",
    "robot": "ロボットの勝ち…",
    "quit": "やめました。",
}


def make_grid(size: int) -> list[list[str]]:
    """全部が壁の盤を作って返す。"""
    return [[WALL] * size for _ in range(size)]


def open_directions(grid: list[list[str]], row: int, col: int) -> list[tuple[int, int]]:
    """(row, col) から 2 マス先がまだ壁になっている方向を返す。"""
    size = len(grid)
    return [(dr, dc) for dr, dc in DIRECTIONS
            if 0 < row + dr < size - 1 and 0 < col + dc < size - 1
            and grid[row + dr][col + dc] == WALL]


def carve(grid: list[list[str]], row: int, col: int) -> None:
    """(row, col) から穴掘り法で掘る。再帰の代わりに、来た道をスタックに積む。"""
    grid[row][col] = PATH
    stack = [(row, col)]                                    # いま居る場所までの道のり

    while stack:
        r, c = stack[-1]                                    # 取り出さずに、いちばん上を見る
        options = open_directions(grid, r, c)

        if not options:                                     # 行き止まり。来た道を 1 つ戻る
            stack.pop()
            continue

        dr, dc = random.choice(options)
        grid[r + dr // 2][c + dc // 2] = PATH               # 間の壁を抜く
        grid[r + dr][c + dc] = PATH
        stack.append((r + dr, c + dc))                      # 掘った先へ進む


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


def dfs_steps(grid, start, goal, came_from):
    """深さ優先探索。見たマスを 1 つずつ yield する。来た道は came_from に書き込む。"""
    stack = [start]
    came_from[start] = None

    while stack:
        pos = stack.pop()                                   # いちばん最近入れたものから
        yield pos
        if pos == goal:
            return
        for nxt in neighbors(grid, pos):
            if nxt not in came_from:
                came_from[nxt] = pos
                stack.append(nxt)


def bfs_steps(grid, start, goal, came_from):
    """幅優先探索。dfs_steps と違うのは、入れ物が deque で先頭から取ることだけ。"""
    queue = deque([start])
    came_from[start] = None

    while queue:
        pos = queue.popleft()                               # いちばん先に入れたものから
        yield pos
        if pos == goal:
            return
        for nxt in neighbors(grid, pos):
            if nxt not in came_from:
                came_from[nxt] = pos
                queue.append(nxt)


def distance(a: tuple[int, int], b: tuple[int, int]) -> int:
    """マンハッタン距離。壁を無視して、縦横に何マス離れているか。"""
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def astar_steps(grid, start, goal, came_from):
    """A*。「ここまでの歩数 + ゴールまでの見込み」が小さいマスから見る。"""
    order = count()                                         # 同点のときは先に入れたほうを先に
    heap = [(distance(start, goal), next(order), start)]
    came_from[start] = None
    cost = {start: 0}                                       # スタートからの歩数

    while heap:
        _, _, pos = heappop(heap)                           # いちばん小さいものが出てくる
        yield pos
        if pos == goal:
            return
        for nxt in neighbors(grid, pos):
            new_cost = cost[pos] + 1
            if nxt not in cost or new_cost < cost[nxt]:
                cost[nxt] = new_cost
                came_from[nxt] = pos
                heappush(heap, (new_cost + distance(nxt, goal), next(order), nxt))


SOLVERS = {                                 # 名前 → 探索の関数
    "DFS": dfs_steps,
    "BFS": bfs_steps,
    "A*": astar_steps,
}


def robot_walk(grid, start, goal):
    """深さ優先で「実際に歩く」順に位置を yield する。行き止まりでは来た道を戻る。

    dfs_steps は見るマスを飛び飛びに yield するが、こちらは 1 マスずつ隣へしか動かない。
    """
    stack = [start]
    seen = {start}
    yield start

    while stack:
        pos = stack[-1]
        if pos == goal:
            return

        options = [nxt for nxt in neighbors(grid, pos) if nxt not in seen]
        if options:
            nxt = random.choice(options)
            seen.add(nxt)
            stack.append(nxt)
            yield nxt                                       # 前へ 1 歩
        else:
            stack.pop()
            if stack:
                yield stack[-1]                             # 戻る 1 歩


def trace(came_from, goal) -> list[tuple[int, int]]:
    """came_from を goal から逆にたどって、経路をスタート順のリストで返す。"""
    if goal not in came_from:
        return []
    path = []
    pos = goal
    while pos is not None:
        path.append(pos)
        pos = came_from[pos]
    path.reverse()
    return path


class Game:
    """ロボットとの競走 1 回ぶん。迷路・二人の位置・歩数・結果を持つ。"""

    def __init__(self, size: int = SIZE, seed: int | None = None):
        if seed is not None:
            random.seed(seed)

        self.size = size
        self.maze = make_maze(size)
        self.start = (1, 1)
        self.goal = (size - 2, size - 2)

        self.player = self.start
        self.steps = 0
        self.robot = self.start
        self.robot_steps = 0
        self.walker = robot_walk(self.maze, self.start, self.goal)   # ロボットの歩みは、ジェネレータを持っておくだけ
        next(self.walker)                                   # 最初の yield（スタート）は読み捨てる
        self.cooldown = ROBOT_EVERY
        self.result: str | None = None                      # "player" / "robot" / "quit"

    def move(self, direction: str) -> bool:
        """自分が 1 マス動く。壁や決着後なら動かず False。"""
        if self.result is not None or direction not in MOVES:
            return False

        dr, dc = MOVES[direction]
        nxt = (self.player[0] + dr, self.player[1] + dc)
        if self.maze[nxt[0]][nxt[1]] != PATH:
            return False

        self.player = nxt
        self.steps += 1
        if self.player == self.goal:
            self.result = "player"
        return True

    def tick(self) -> None:
        """時間を 1 つ進める。ROBOT_EVERY 回に 1 回、ロボットが 1 歩動く。"""
        if self.result is not None:
            return

        self.cooldown -= 1
        if self.cooldown > 0:
            return
        self.cooldown = ROBOT_EVERY

        self.robot = next(self.walker)                      # ジェネレータから次の 1 歩をもらう
        self.robot_steps += 1
        if self.robot == self.goal:
            self.result = "robot"


# --- ここから下はブラウザ版だけ。CLI 版の race() / show_search() / read_key() にあたる ---

KEYS = {  # ブラウザが送ってくる名前 → CLI 版と同じ呼び名
    "ArrowUp": "up",
    "ArrowDown": "down",
    "ArrowLeft": "left",
    "ArrowRight": "right",
}

maze_grid = document.querySelector("#maze")
steps_label = document.querySelector("#steps")
robot_label = document.querySelector("#robot-steps")
message = document.querySelector("#message")
analysis_label = document.querySelector("#analysis")
start_button = document.querySelector("#start-btn")
size_buttons = document.querySelectorAll(".mode")
solver_buttons = document.querySelectorAll(".solver")

# 状態は Game が全部持っている。ブラウザ側が覚えるのは盤の大きさと「いま動いているか」だけ
size = SIZE
game = Game(size)
cells = []
playing = False                                             # レース中
busy = False                                                # 探索アニメ中


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


def draw(seen=frozenset(), path=frozenset(), cursor=None):
    """CLI 版の render() / maze_text() にあたる。探索アニメ中は seen / path / cursor も塗る。"""
    for index, cell in enumerate(cells):
        pos = divmod(index, game.size)                      # 1 本のリストを 2 次元として使う
        row, col = pos

        if game.maze[row][col] == WALL:
            names = ["cell", "wall"]
        elif pos in path:
            names = ["cell", "route"]
        elif pos in seen:
            names = ["cell", "seen"]
        else:
            names = ["cell", "floor"]

        if pos == game.player:
            names.append("player")
        if pos == game.robot:
            names.append("robot")
        if pos == game.goal:
            names.append("goal")
        if pos == cursor:
            names.append("cursor")

        cell.className = " ".join(names)

    steps_label.textContent = str(game.steps)
    robot_label.textContent = str(game.robot_steps)

    for button in size_buttons:
        button.className = "mode is-on" if int(button.getAttribute("data-size")) == size else "mode"
        button.disabled = playing or busy
    for button in solver_buttons:
        button.disabled = playing or busy
    start_button.disabled = playing or busy


def finish():
    global playing

    playing = False
    message.textContent = f"{RESULT_TEXT[game.result]}  あなた {game.steps} 歩 / ロボット {game.robot_steps} 歩"
    start_button.textContent = "もう一度"
    draw()


async def tick():
    """時間を進める係。CLI 版の read_key(TICK_SECONDS) の待ち時間にあたる。"""
    while playing:
        await asyncio.sleep(TICK_SECONDS)
        if playing:
            game.tick()
            draw()
            if game.result is not None:
                finish()


def start():
    global game, playing

    game = Game(size)                                       # 作り直すだけで新しい迷路になる
    playing = True
    message.textContent = ""
    analysis_label.textContent = ""
    build()
    draw()
    asyncio.ensure_future(tick())                           # 待ち続ける係を裏で走らせる


def act(direction):
    """CLI 版の race() の while ループの中身と同じ振り分け。"""
    if not playing:
        return
    if game.move(direction):
        draw()
        if game.result is not None:
            finish()


async def animate(name):
    """CLI 版の show_search() と同じ。time.sleep の代わりに await で間を置く。"""
    global busy

    busy = True
    draw()
    came_from = {}
    seen = set()

    for pos in SOLVERS[name](game.maze, game.start, game.goal, came_from):
        seen.add(pos)
        draw(seen, cursor=pos)
        analysis_label.textContent = f"{name}: {len(seen)} マス見た"
        await asyncio.sleep(FRAME_SECONDS)

    path = trace(came_from, game.goal)
    analysis_label.textContent = f"{name}: {len(seen)} マス見た → 経路 {len(path) - 1} 歩"
    busy = False
    draw(seen, set(path))


@when("click", ".pad button")
def on_pad(event):
    act(event.target.getAttribute("data-dir"))


@when("click", ".mode")
def on_size(event):
    global size, game

    if playing or busy:
        return
    size = int(event.target.getAttribute("data-size"))
    game = Game(size)
    message.textContent = ""
    analysis_label.textContent = ""
    start_button.textContent = "スタート"
    build()
    draw()


@when("click", ".solver")
def on_solver(event):
    if playing or busy:
        return
    asyncio.ensure_future(animate(event.target.getAttribute("data-solver")))


@when("click", "#start-btn")
def on_start(event):
    if not playing and not busy:
        start()


@when("keydown", "body")
def on_key(event):
    if event.key == "Enter":
        if not playing and not busy:
            start()
        return

    direction = KEYS.get(event.key)
    if direction is None:
        return

    event.preventDefault()                                  # 矢印でページが動かないように
    act(direction)


# Pyodide の読み込みが終わってから実行される＝ここが準備完了の合図
document.querySelector("#loading").hidden = True
build()
draw()
