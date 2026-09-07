"""ダンジョン（ブラウザ版）

CLI 版（g19-dungeon/main.py）とダンジョンの作り方・霧・階段のルールはまったく同じ。
定数 11 個と Rect、make_rooms() / rooms_apart() / carve_room() / carve_line() / carve_corridor() /
make_dungeon() / reachable() / visible_cells()、そして class Game を、
ステップの目印コメント（# ←）を外しただけで 1 文字も変えずに持ってきている。

持ってこなかったのは dungeon_text() と raw_mode() / read_key() / main()、それに Game.render() だけ。
違うのは入口と出口で、入口は termios の生キー入力ではなくキーイベントとパッド、
出口は文字の盤ではなく 960 個の <div>（見えている／覚えている／未知で色を変える）。
"""

import random
from collections import deque
from dataclasses import dataclass
from itertools import combinations

from pyscript import document, when


# --- ここから class Game まで、CLI 版（g19-dungeon/main.py）からそのまま ---


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


# --- ここから下はブラウザ版だけ。CLI 版の read_key() / render() / main() にあたる ---

KEYS = {
    "ArrowUp": "up",
    "ArrowDown": "down",
    "ArrowLeft": "left",
    "ArrowRight": "right",
}

grid_el = document.querySelector("#maze")
floor_label = document.querySelector("#floor")
steps_label = document.querySelector("#steps")
message = document.querySelector("#message")
new_button = document.querySelector("#new-btn")

game = Game()
cells = []


def build():
    """<div> を WIDTH × HEIGHT 個作る。最初の 1 回だけ。"""
    global cells

    grid_el.replaceChildren()
    grid_el.style.gridTemplateColumns = f"repeat({WIDTH}, 1fr)"
    cells = []
    for _ in range(WIDTH * HEIGHT):
        cell = document.createElement("div")
        cell.className = "cell"
        grid_el.appendChild(cell)
        cells.append(cell)


def draw():
    """CLI 版の dungeon_text() にあたる。見えている／覚えている／未知で class を分ける。"""
    for index, cell in enumerate(cells):
        y, x = divmod(index, WIDTH)
        pos = (x, y)
        names = ["cell"]

        if pos in game.visible or pos in game.seen:
            names.append("wall" if game.grid[y][x] == WALL else "floor")
            if pos not in game.visible:
                names.append("seen")
            if game.grid[y][x] == STAIRS:
                names.append("stairs")
        if pos == game.player:
            names.append("player")

        cell.className = " ".join(names)

    floor_label.textContent = str(game.floor)
    steps_label.textContent = str(game.steps)
    if game.result is not None:
        message.textContent = f"{RESULT_TEXT[game.result]}  {game.steps} 歩"


def start():
    global game

    game = Game()                                           # 作り直すだけで新しいダンジョンになる
    message.textContent = ""
    draw()


def act(direction):
    if game.move(direction):
        draw()


@when("click", ".pad button")
def on_pad(event):
    act(event.target.getAttribute("data-dir"))


@when("click", "#new-btn")
def on_new(event):
    start()


@when("keydown", "body")
def on_key(event):
    direction = KEYS.get(event.key)
    if direction is None:
        return
    event.preventDefault()
    act(direction)


# Pyodide の読み込みが終わってから実行される＝ここが準備完了の合図
document.querySelector("#loading").hidden = True
new_button.disabled = False
build()
draw()
