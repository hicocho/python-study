"""ダンジョン — 完成: 部屋と廊下を作り、霧の中を歩いて階段を降りる。class Game にまとめる。"""

import os
import random
import sys
import termios
import tty
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass
from itertools import combinations

WIDTH = 48                                  # ダンジョンの横のマス数
HEIGHT = 20                                 # ダンジョンの縦のマス数
ROOM_MIN = 4                                # 部屋の一辺の最小
ROOM_MAX = 9                                # 部屋の横幅の最大（縦は 6 まで）
MAX_ROOMS = 7
ROOM_TRIES = 60                             # 部屋を置こうとする回数の上限
SIGHT = 5                                   # 何マス先まで見えるか
FLOORS = 5                                  # この階まで降りたらクリア

WALL = "#"
FLOOR = "."
STAIRS = ">"

ARROWS = {
    "\x1b[A": "up",
    "\x1b[B": "down",
    "\x1b[C": "right",
    "\x1b[D": "left",
}

MOVES = {
    "up": (0, -1),
    "down": (0, 1),
    "left": (-1, 0),
    "right": (1, 0),
}

RESULT_TEXT = {
    "clear": "最下層にたどり着いた！",
    "quit": "やめました。",
}


@dataclass(frozen=True)
class Rect:
    """部屋の枠。左上 (x, y) と幅・高さ。"""

    x: int
    y: int
    w: int
    h: int

    @property
    def x2(self) -> int:
        return self.x + self.w

    @property
    def y2(self) -> int:
        return self.y + self.h

    @property
    def center(self) -> tuple[int, int]:
        return (self.x + self.w // 2, self.y + self.h // 2)

    def __contains__(self, pos: tuple[int, int]) -> bool:
        """pos in room と書けるように。"""
        px, py = pos
        return self.x <= px < self.x2 and self.y <= py < self.y2

    def overlaps(self, other: "Rect") -> bool:
        """壁 1 マスぶんの隙間も含めて、重なっているか。"""
        return (self.x - 1 < other.x2 and other.x - 1 < self.x2
                and self.y - 1 < other.y2 and other.y - 1 < self.y2)


def make_rooms() -> list[Rect]:
    """重ならない部屋を、置ける限り MAX_ROOMS 個まで置く。"""
    rooms: list[Rect] = []
    for _ in range(ROOM_TRIES):
        w = random.randint(ROOM_MIN, ROOM_MAX)
        h = random.randint(ROOM_MIN, min(ROOM_MAX, 6))
        room = Rect(random.randint(1, WIDTH - w - 1), random.randint(1, HEIGHT - h - 1), w, h)
        if not any(room.overlaps(other) for other in rooms):
            rooms.append(room)
        if len(rooms) == MAX_ROOMS:
            break
    return rooms


def rooms_apart(rooms: list[Rect]) -> bool:
    """どの 2 部屋も重なっていないか。組み合わせを全部見る。"""
    return all(not a.overlaps(b) for a, b in combinations(rooms, 2))


def carve_room(grid: list[list[str]], room: Rect) -> None:
    for y in range(room.y, room.y2):
        for x in range(room.x, room.x2):
            grid[y][x] = FLOOR


def carve_line(grid: list[list[str]], a: tuple[int, int], b: tuple[int, int]) -> None:
    """a から b へ、縦か横にまっすぐ掘る（どちらかの座標が同じこと）。"""
    (ax, ay), (bx, by) = a, b
    for x in range(min(ax, bx), max(ax, bx) + 1):
        for y in range(min(ay, by), max(ay, by) + 1):
            grid[y][x] = FLOOR


def carve_corridor(grid: list[list[str]], a: tuple[int, int], b: tuple[int, int]) -> None:
    """a から b へ L 字の廊下を掘る。曲がり角を右上にするか左下にするかはランダム。"""
    (ax, ay), (bx, by) = a, b
    corner = (bx, ay) if random.random() < 0.5 else (ax, by)
    carve_line(grid, a, corner)
    carve_line(grid, corner, b)


def make_dungeon() -> tuple[list[list[str]], list[Rect]]:
    """1 階ぶんのダンジョンを作る。(盤, 部屋のリスト) を返す。"""
    grid = [[WALL] * WIDTH for _ in range(HEIGHT)]
    rooms = make_rooms()
    for room in rooms:
        carve_room(grid, room)
    for a, b in zip(rooms, rooms[1:]):                      # 置いた順に隣どうしをつなぐ
        carve_corridor(grid, a.center, b.center)
    sx, sy = rooms[-1].center
    grid[sy][sx] = STAIRS                                   # 最後の部屋に下り階段
    return grid, rooms


def reachable(grid: list[list[str]], start: tuple[int, int]) -> set[tuple[int, int]]:
    """start から歩いて行けるマスの集合（BFS）。"""
    seen = {start}
    queue = deque([start])
    while queue:
        x, y = queue.popleft()
        for dx, dy in MOVES.values():
            nxt = (x + dx, y + dy)
            if nxt not in seen and grid[nxt[1]][nxt[0]] != WALL:
                seen.add(nxt)
                queue.append(nxt)
    return seen


def visible_cells(pos: tuple[int, int]) -> set[tuple[int, int]]:
    """pos から SIGHT マス以内のマス。"""
    px, py = pos
    return {(x, y)
            for y in range(max(0, py - SIGHT), min(HEIGHT, py + SIGHT + 1))
            for x in range(max(0, px - SIGHT), min(WIDTH, px + SIGHT + 1))
            if (x - px) ** 2 + (y - py) ** 2 <= SIGHT * SIGHT}


def dungeon_text(grid: list[list[str]], player: tuple[int, int],
                 seen: set[tuple[int, int]], visible: set[tuple[int, int]]) -> str:
    """見えているマスはそのまま、覚えているだけのマスは薄く、まだのマスは空白。"""
    lines = []
    for y in range(HEIGHT):
        row = []
        for x in range(WIDTH):
            if (x, y) == player:
                row.append("@")
            elif (x, y) in visible:
                row.append(grid[y][x])
            elif (x, y) in seen:
                row.append("·" if grid[y][x] == FLOOR else grid[y][x])
            else:
                row.append(" ")
        lines.append("".join(row))
    return "\n".join(lines)


class Game:
    """冒険 1 回ぶん。いまの階・ダンジョン・自分の位置・覚えたマス・歩数を持つ。"""

    def __init__(self, seed: int | None = None):
        if seed is not None:
            random.seed(seed)
        self.floor = 0
        self.steps = 0
        self.result: str | None = None
        self.descend()

    def descend(self) -> None:
        """次の階へ。ダンジョンを作り直し、最初の部屋から始める。"""
        self.floor += 1
        self.grid, self.rooms = make_dungeon()
        self.player = self.rooms[0].center
        self.seen: set[tuple[int, int]] = set()
        self.look()

    def look(self) -> None:
        """いま見えているマスを覚える。"""
        self.visible = visible_cells(self.player)
        self.seen |= self.visible

    def move(self, direction: str) -> bool:
        """1 マス動く。壁なら動かず False。階段の上に乗ったら次の階。"""
        if self.result is not None or direction not in MOVES:
            return False
        dx, dy = MOVES[direction]
        nxt = (self.player[0] + dx, self.player[1] + dy)
        if self.grid[nxt[1]][nxt[0]] == WALL:
            return False

        self.player = nxt
        self.steps += 1
        self.look()
        if self.grid[nxt[1]][nxt[0]] == STAIRS:
            if self.floor == FLOORS:
                self.result = "clear"
            else:
                self.descend()
        return True

    def render(self) -> str:
        board = dungeon_text(self.grid, self.player, self.seen, self.visible)
        return f"{board}\n地下 {self.floor} 階   {self.steps:4d} 歩   > で下へ   矢印で移動 / q でやめる\n"


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
        data = os.read(sys.stdin.fileno(), 8)
    key = data.decode()
    return ARROWS.get(key, key)


def main():
    game = Game()

    while game.result is None:
        print("\x1b[2J\x1b[H", end="")
        print(game.render())

        key = read_key()
        if key == "q":
            game.result = "quit"
        else:
            game.move(key)

    print("\x1b[2J\x1b[H", end="")
    print(game.render())
    print(f"\n{RESULT_TEXT[game.result]}  {game.steps} 歩")


if __name__ == "__main__":
    main()
