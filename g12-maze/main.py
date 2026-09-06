"""迷路 — 完成: class Game にまとめ、--size と --seed で好きな迷路を出す。"""

import argparse                             # ←
import random
import os
import sys
import termios
import tty
from collections import deque
from contextlib import contextmanager

SIZE = 21                                   # 奇数。壁と通路が 1 マスおきに並ぶ

WALL = "#"
PATH = " "

# 2 マスずつ掘る。間の 1 マスが壁として残るか、抜かれるかで迷路になる
DIRECTIONS = [(0, 2), (2, 0), (0, -2), (-2, 0)]

TILES = {
    WALL: "██",
    PATH: "  ",
}

ARROWS = {
    "\x1b[A": "up",
    "\x1b[B": "down",
    "\x1b[C": "right",
    "\x1b[D": "left",
}

MOVES = {
    "up": (-1, 0),
    "down": (1, 0),
    "left": (0, -1),
    "right": (0, 1),
}

# 再帰の深さは既定で 1000 まで。迷路が大きいと足りなくなるので広げておく
sys.setrecursionlimit(10000)


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


def maze_text(grid: list[list[str]], player: tuple[int, int], goal: tuple[int, int],
              route: set[tuple[int, int]] = frozenset(), trail: set[tuple[int, int]] = frozenset(),
              hint: tuple[int, int] | None = None) -> str:
    """迷路を表示用の文字列にして返す。@ 自分 / G ゴール / ▒ 最短路 / · 足あと / ＊ ヒント。"""
    lines = []
    for r, row in enumerate(grid):
        cells = []
        for c, cell in enumerate(row):
            if (r, c) == player:
                cells.append("@ ")
            elif (r, c) == goal:
                cells.append("G ")
            elif (r, c) == hint:
                cells.append("＊")
            elif (r, c) in route:
                cells.append("▒▒")
            elif (r, c) in trail:
                cells.append("· ")
            else:
                cells.append(TILES[cell])
        lines.append("".join(cells))
    return "\n".join(lines)


class Game:                                 # ←
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

    def render(self) -> str:
        """端末に出す文字列。ゴール後は最短路を重ねる。"""
        route = set(self.route) if self.finished else frozenset()
        return maze_text(self.maze, self.player, self.goal, route, self.trail, self.hint)


@contextmanager
def raw_mode():
    """このブロックの中だけ、キーを 1 文字ずつ読める端末にする。抜けたら必ず戻す。"""
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    tty.setcbreak(fd)
    try:
        yield
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def read_key() -> str:
    """キーを 1 つ読む。矢印なら "up" などの名前、それ以外は押された文字そのもの。"""
    with raw_mode():
        data = os.read(sys.stdin.fileno(), 8)              # 矢印は ESC [ A の 3 バイトがまとめて届く
    key = data.decode()
    return ARROWS.get(key, key)


def parse_args() -> argparse.Namespace:     # ←
    """コマンドラインの --size と --seed を読む。"""
    parser = argparse.ArgumentParser(description="迷路。矢印キーで歩いてゴールへ。")
    parser.add_argument("--size", type=int, default=SIZE, help="盤の一辺（5 以上の奇数）。既定 21")
    parser.add_argument("--seed", type=int, help="同じ数字を渡すと同じ迷路になる")
    args = parser.parse_args()

    if args.size < 5 or args.size % 2 == 0:
        parser.error("--size は 5 以上の奇数にしてください")

    return args


def main():                                 # ←
    args = parse_args()
    game = Game(args.size, args.seed)

    while True:
        print("\x1b[2J\x1b[H", end="")                      # 画面を消して左上へ
        print(game.render())

        if game.finished:
            print(f"\nゴール！  あなた {game.steps} 歩 / 最短 {game.best} 歩（+{game.steps - game.best}）")
            break

        print(f"\n{game.steps} 歩（最短 {game.best} 歩）  矢印キーで移動 / ? でヒント / q でやめる")

        key = read_key()
        if key == "q":
            print("やめました。")
            break
        if key == "?":
            game.show_hint()
        else:
            game.move(key)


if __name__ == "__main__":
    main()
