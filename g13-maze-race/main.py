"""迷路2 — 完成: 探索ロボットと競走する。"""

import argparse
import os                                   # ←
import random
import select                               # ←
import sys
import termios                              # ←
import time
import tty                                  # ←
from collections import deque
from contextlib import contextmanager       # ←
from heapq import heappop, heappush
from itertools import count
from time import perf_counter

SIZE = 21                                   # 奇数。壁と通路が 1 マスおきに並ぶ
FRAME_SECONDS = 0.02                        # 探索アニメの 1 歩ごとの間
TICK_SECONDS = 0.05                         # ← レース中、キーを待つ時間
ROBOT_EVERY = 3                             # ← ロボットは 3 ティック（0.15 秒）に 1 歩

WALL = "#"
PATH = " "

# 2 マスずつ掘る。間の 1 マスが壁として残るか、抜かれるかで迷路になる
DIRECTIONS = [(0, 2), (2, 0), (0, -2), (-2, 0)]

# 1 マスずつ歩くときの 4 方向
MOVES = {
    "up": (-1, 0),
    "down": (1, 0),
    "left": (0, -1),
    "right": (0, 1),
}

ARROWS = {                                  # ←
    "\x1b[A": "up",
    "\x1b[B": "down",
    "\x1b[C": "right",
    "\x1b[D": "left",
}

TILES = {
    WALL: "██",
    PATH: "  ",
}

RESULT_TEXT = {                             # ←
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


def robot_walk(grid, start, goal):          # ←
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


def maze_text(grid: list[list[str]], seen=frozenset(), path=frozenset(),
              current=None, start=None, goal=None, robot=None) -> str:      # ←
    """迷路を表示用の文字列にして返す。░ 見たマス / ▒ 経路 / @ 自分 / R ロボット / S G 両端。"""
    lines = []
    for r, row in enumerate(grid):
        cells = []
        for c, cell in enumerate(row):
            pos = (r, c)
            if pos == current:
                cells.append("@ ")
            elif pos == robot:                              # ←
                cells.append("R ")                          # ←
            elif pos == start:
                cells.append("S ")
            elif pos == goal:
                cells.append("G ")
            elif pos in path:
                cells.append("▒▒")
            elif pos in seen:
                cells.append("░░")
            else:
                cells.append(TILES[cell])
        lines.append("".join(cells))
    return "\n".join(lines)


def show_search(name, steps, grid, start, goal):
    """探索を 1 歩ずつ描く。steps はジェネレータ。"""
    came_from = {}
    seen = set()

    for pos in steps(grid, start, goal, came_from):
        seen.add(pos)
        sys.stdout.write("\x1b[H" + maze_text(grid, seen, current=pos, start=start, goal=goal))
        sys.stdout.write(f"\n{name}: {len(seen):4d} マス見た\n")
        sys.stdout.flush()
        time.sleep(FRAME_SECONDS)

    path = trace(came_from, goal)
    sys.stdout.write("\x1b[H" + maze_text(grid, seen, set(path), start=start, goal=goal))
    sys.stdout.write(f"\n{name}: {len(seen):4d} マス見た → 経路 {len(path) - 1} 歩\n")
    sys.stdout.flush()


def measure(steps, grid, start, goal) -> tuple[int, int, float]:
    """探索を最後まで回して (見たマス数, 経路の歩数, かかった秒) を返す。描かない。"""
    came_from = {}
    began = perf_counter()
    seen = sum(1 for _ in steps(grid, start, goal, came_from))    # ジェネレータを使い切る
    elapsed = perf_counter() - began
    return seen, len(trace(came_from, goal)) - 1, elapsed


class Game:                                 # ←
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

    def render(self) -> str:
        """端末に出す文字列。上書きで描くので、行の長さは毎回同じにする。"""
        board = maze_text(self.maze, current=self.player, goal=self.goal, robot=self.robot)
        status = f"あなた {self.steps:4d} 歩   ロボット {self.robot_steps:4d} 歩   矢印で移動 / q でやめる"
        return f"{board}\n{status}\n"


@contextmanager                             # ←
def raw_mode():
    """このブロックの中だけ、キーを 1 文字ずつ読める端末にする。抜けたら必ず戻す。"""
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    tty.setcbreak(fd)
    try:
        yield
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def read_key(timeout: float) -> str | None:    # ←
    """timeout 秒まで待ってキーを 1 つ読む。来なければ None。"""
    if not select.select([sys.stdin], [], [], timeout)[0]:
        return None
    data = os.read(sys.stdin.fileno(), 8)                  # 矢印は 3 バイトまとめて届く
    key = data.decode()
    return ARROWS.get(key, key)


def race(size: int, seed: int | None) -> None:     # ←
    """ロボットと競走する。キーを待つ時間がそのまま時計になる。"""
    game = Game(size, seed)

    print("\x1b[2J", end="")
    with raw_mode():
        while game.result is None:
            sys.stdout.write("\x1b[H" + game.render())
            sys.stdout.flush()

            key = read_key(TICK_SECONDS)
            if key == "q":
                game.result = "quit"
            elif key is not None:
                game.move(key)

            game.tick()

    sys.stdout.write("\x1b[H" + game.render())
    print(f"\n{RESULT_TEXT[game.result]}  あなた {game.steps} 歩 / ロボット {game.robot_steps} 歩")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="探索ロボットと迷路で競走する。")
    parser.add_argument("--size", type=int, default=SIZE, help="盤の一辺（5 以上の奇数）。既定 21")
    parser.add_argument("--seed", type=int, help="同じ数字を渡すと同じ迷路になる")
    parser.add_argument("--show", choices=SOLVERS, help="競走せず、この探索だけアニメで見る")
    parser.add_argument("--compare", action="store_true", help="競走せず、3 つの探索を比べる")   # ←
    args = parser.parse_args()

    if args.size < 5 or args.size % 2 == 0:
        parser.error("--size は 5 以上の奇数にしてください")

    return args


def main():
    args = parse_args()

    if args.show or args.compare:                           # ← 見るだけのモード
        if args.seed is not None:
            random.seed(args.seed)
        maze = make_maze(args.size)
        start = (1, 1)
        goal = (args.size - 2, args.size - 2)

        if args.show:
            print("\x1b[2J", end="")
            show_search(args.show, SOLVERS[args.show], maze, start, goal)
            return

        print(f"{args.size}×{args.size} の迷路で 3 つを比べる\n")
        print("探索  " + "見たマス" + "    経路" + "      時間")           # 全角は 2 桁ぶんなので手で揃える
        for name, steps in SOLVERS.items():
            seen, length, elapsed = measure(steps, maze, start, goal)
            print(f"{name:<6}{seen:>8}{length:>8}{elapsed * 1000:>7.2f} ms")
        return

    race(args.size, args.seed)                              # ←


if __name__ == "__main__":
    main()
