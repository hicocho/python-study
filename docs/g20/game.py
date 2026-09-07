"""モンスター（ブラウザ版）

CLI 版（g20-monsters/main.py）とダンジョン・敵・戦闘のルールはまったく同じ。
定数 16 個と Trait / Kind / Monster / Rect、KINDS、make_rooms() 〜 make_dungeon()、
spawn_monsters() / line() / can_see() / visible_cells() / next_step_toward()、そして class Game を、
ステップの目印コメント（# ←）を外しただけで 1 文字も変えずに持ってきている。

持ってこなかったのは dungeon_text() と raw_mode() / read_key() / main()、それに Game.render() だけ。
出口は文字の盤ではなく 960 個の <div>。敵は文字で置き、体力はバーで見せる。
"""

import random
from collections import deque
from dataclasses import dataclass
from enum import Flag, auto
from itertools import combinations

from pyscript import document, when


# --- ここから class Game まで、CLI 版（g20-monsters/main.py）からそのまま ---


WIDTH = 48                                  # ダンジョンの横のマス数
HEIGHT = 20                                 # ダンジョンの縦のマス数
ROOM_MIN = 4                                # 部屋の一辺の最小
ROOM_MAX = 9                                # 部屋の横幅の最大（縦は 6 まで）
MAX_ROOMS = 7
ROOM_TRIES = 60                             # 部屋を置こうとする回数の上限
SIGHT = 6                                   # 何マス先まで見えるか
FLOORS = 5                                  # この階まで降りたらクリア
PLAYER_HP = 20
PLAYER_ATTACK = 4
REGEN_EVERY = 5                             # 毒でなければ、この歩数ごとに体力が 1 戻る
MONSTERS_PER_FLOOR = (2, 4)                 # 1 階に置く敵の数の範囲（階が進むと +階数）
POISON_TURNS = 4                            # 毒が続くターン数


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
    "over": "倒れてしまった…",
    "quit": "やめました。",
}


class Trait(Flag):
    """敵の性質。組み合わせられる（FAST | ARMORED のように）。"""

    NONE = 0
    FAST = auto()                                           # 1 ターンに 2 歩
    POISONOUS = auto()                                      # 当たると毒
    ARMORED = auto()                                        # 受けるダメージが半分


@dataclass(frozen=True)
class Kind:
    """敵の種類。名前・記号・体力・攻撃力・性質・出やすさ。"""

    name: str
    char: str
    hp: int
    attack: int
    traits: Trait
    weight: int                                             # random.choices の重み


KINDS = [
    Kind("ねずみ", "r", 3, 1, Trait.FAST, 5),
    Kind("へび", "s", 4, 1, Trait.POISONOUS, 3),
    Kind("ゴブリン", "g", 6, 2, Trait.NONE, 3),
    Kind("オーク", "O", 10, 2, Trait.ARMORED, 1),
    Kind("トロル", "T", 12, 3, Trait.FAST | Trait.ARMORED, 1),
]


@dataclass
class Monster:
    """敵 1 体。種類と位置と残り体力。"""

    kind: Kind
    pos: tuple[int, int]
    hp: int

    @property
    def alive(self) -> bool:
        return self.hp > 0


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


def spawn_monsters(grid: list[list[str]], rooms: list[Rect], floor: int) -> list[Monster]:
    """最初の部屋以外に、種類を重みで選んで置く。深いほど多い。"""
    low, high = MONSTERS_PER_FLOOR
    count = random.randint(low, high) + floor - 1
    monsters: list[Monster] = []
    while len(monsters) < count and len(rooms) > 1:
        room = random.choice(rooms[1:])
        pos = (random.randint(room.x, room.x2 - 1), random.randint(room.y, room.y2 - 1))
        if grid[pos[1]][pos[0]] == FLOOR and all(m.pos != pos for m in monsters):
            (kind,) = random.choices(KINDS, weights=[k.weight for k in KINDS])
            monsters.append(Monster(kind, pos, kind.hp))
    return monsters


def line(a: tuple[int, int], b: tuple[int, int]):
    """a から b まで、通るマスを順に返す（両端を含む）。ブレゼンハムの線。"""
    (x0, y0), (x1, y1) = a, b
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
    err = dx + dy
    while True:
        yield (x0, y0)
        if (x0, y0) == (x1, y1):
            return
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy


def can_see(grid: list[list[str]], a: tuple[int, int], b: tuple[int, int]) -> bool:
    """a から b が見えるか。距離 SIGHT 以内で、間に壁が無い。"""
    if (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 > SIGHT * SIGHT:
        return False
    for x, y in line(a, b):
        if (x, y) != b and (x, y) != a and grid[y][x] == WALL:
            return False
    return True


def visible_cells(grid: list[list[str]], pos: tuple[int, int]) -> set[tuple[int, int]]:
    """pos から見えるマス。壁そのものは見えるが、壁の向こうは見えない。"""
    px, py = pos
    return {(x, y)
            for y in range(max(0, py - SIGHT), min(HEIGHT, py + SIGHT + 1))
            for x in range(max(0, px - SIGHT), min(WIDTH, px + SIGHT + 1))
            if can_see(grid, pos, (x, y))}


def next_step_toward(grid: list[list[str]], start: tuple[int, int], goal: tuple[int, int],
                     blocked: set[tuple[int, int]]) -> tuple[int, int] | None:
    """start から goal へ向かう最短路の次の 1 マス。blocked のマスは通れない。無ければ None。"""
    queue = deque([start])
    came_from = {start: None}
    while queue:
        pos = queue.popleft()
        if pos == goal:
            break
        x, y = pos
        for dx, dy in MOVES.values():
            nxt = (x + dx, y + dy)
            if nxt not in came_from and grid[nxt[1]][nxt[0]] != WALL and (nxt not in blocked or nxt == goal):
                came_from[nxt] = pos
                queue.append(nxt)
    if goal not in came_from:
        return None
    pos = goal
    while came_from[pos] != start:
        pos = came_from[pos]
    return pos


class Game:
    """冒険 1 回ぶん。階・ダンジョン・自分・敵・体力・毒・記録を持つ。"""

    def __init__(self, seed: int | None = None):
        if seed is not None:
            random.seed(seed)
        self.floor = 0
        self.steps = 0
        self.hp = PLAYER_HP
        self.poison = 0                                     # 毒の残りターン
        self.kills = 0
        self.log: list[str] = []
        self.result: str | None = None
        self.descend()

    def descend(self) -> None:
        """次の階へ。ダンジョンと敵を作り直し、最初の部屋から始める。"""
        self.floor += 1
        self.grid, self.rooms = make_dungeon()
        self.player = self.rooms[0].center
        self.monsters = spawn_monsters(self.grid, self.rooms, self.floor)
        self.seen: set[tuple[int, int]] = set()
        self.look()

    def look(self) -> None:
        self.visible = visible_cells(self.grid, self.player)
        self.seen |= self.visible

    def say(self, text: str) -> None:
        """記録に 1 行足す。直近の数行だけ見せる。"""
        self.log.append(text)
        self.log = self.log[-3:]

    def monster_at(self, pos: tuple[int, int]) -> Monster | None:
        return next((m for m in self.monsters if m.alive and m.pos == pos), None)

    def move(self, direction: str) -> bool:
        """1 マス動く。敵がいれば攻撃。そのあと敵のターン。"""
        if self.result is not None or direction not in MOVES:
            return False
        dx, dy = MOVES[direction]
        nxt = (self.player[0] + dx, self.player[1] + dy)
        if self.grid[nxt[1]][nxt[0]] == WALL:
            return False

        target = self.monster_at(nxt)
        if target is not None:
            self.attack(target)
        else:
            self.player = nxt
            self.steps += 1
            self.look()
            if self.grid[nxt[1]][nxt[0]] == STAIRS:
                if self.floor == FLOORS:
                    self.result = "clear"
                    return True
                self.say(f"地下 {self.floor + 1} 階へ降りた。")
                self.descend()
                return True

        self.monsters_turn()
        self.end_turn()
        return True

    def attack(self, target: Monster) -> None:
        damage = PLAYER_ATTACK // 2 if Trait.ARMORED in target.kind.traits else PLAYER_ATTACK
        target.hp -= damage
        if target.alive:
            self.say(f"{target.kind.name}に {damage} のダメージ（残り {target.hp}）。")
        else:
            self.kills += 1
            self.say(f"{target.kind.name}を倒した！")

    def monsters_turn(self) -> None:
        """見えている敵は近づいてきて、隣なら噛みつく。FAST は 2 回動く。"""
        for monster in self.monsters:
            if not monster.alive:
                continue
            moves = 2 if Trait.FAST in monster.kind.traits else 1
            for _ in range(moves):
                if self.is_adjacent(monster.pos, self.player):
                    self.bitten(monster)
                    break
                if not can_see(self.grid, monster.pos, self.player):
                    break
                occupied = {m.pos for m in self.monsters if m.alive and m is not monster}
                step = next_step_toward(self.grid, monster.pos, self.player, occupied | {self.player})
                if step is None or step == self.player:
                    break
                monster.pos = step

    @staticmethod
    def is_adjacent(a: tuple[int, int], b: tuple[int, int]) -> bool:
        return abs(a[0] - b[0]) + abs(a[1] - b[1]) == 1

    def bitten(self, monster: Monster) -> None:
        self.hp -= monster.kind.attack
        text = f"{monster.kind.name}に {monster.kind.attack} のダメージを受けた。"
        if Trait.POISONOUS in monster.kind.traits and self.poison == 0:
            self.poison = POISON_TURNS
            text += " 毒だ！"
        self.say(text)

    def end_turn(self) -> None:
        """ターンの終わり。毒が回るか、少しずつ回復する。体力が尽きたら終わり。"""
        if self.poison > 0:
            self.hp -= 1
            self.poison -= 1
            if self.poison == 0:
                self.say("毒が抜けた。")
        elif self.steps > 0 and self.steps % REGEN_EVERY == 0:   # 歩いたときだけ、少しずつ回復
            self.hp = min(PLAYER_HP, self.hp + 1)
        if self.hp <= 0:
            self.hp = 0
            self.result = "over"


# --- ここから下はブラウザ版だけ。CLI 版の read_key() / render() / main() にあたる ---

KEYS = {
    "ArrowUp": "up",
    "ArrowDown": "down",
    "ArrowLeft": "left",
    "ArrowRight": "right",
}
STRONG = Trait.ARMORED                                      # 赤い字で出す敵

grid_el = document.querySelector("#maze")
floor_label = document.querySelector("#floor")
hp_label = document.querySelector("#hp")
hp_fill = document.querySelector("#hp-fill")
poison_label = document.querySelector("#poison")
kills_label = document.querySelector("#kills")
steps_label = document.querySelector("#steps")
log_el = document.querySelector("#log")
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
    """CLI 版の dungeon_text() にあたる。敵は見えているときだけ文字を置く。"""
    chars = {m.pos: m for m in game.monsters if m.alive and m.pos in game.visible}

    for index, cell in enumerate(cells):
        y, x = divmod(index, WIDTH)
        pos = (x, y)
        names = ["cell"]
        text = ""

        if pos in game.visible or pos in game.seen:
            names.append("wall" if game.grid[y][x] == WALL else "floor")
            if pos not in game.visible:
                names.append("seen")
            if game.grid[y][x] == STAIRS:
                names.append("stairs")
        if pos == game.player:
            names.append("player")
        elif pos in chars:
            monster = chars[pos]
            names.append("monster")
            if STRONG in monster.kind.traits:
                names.append("strong")
            text = monster.kind.char

        cell.className = " ".join(names)
        cell.textContent = text

    floor_label.textContent = str(game.floor)
    hp_label.textContent = str(game.hp)
    hp_fill.style.width = f"{game.hp / PLAYER_HP * 100:.0f}%"
    hp_fill.className = "low" if game.hp <= PLAYER_HP // 4 else ""
    poison_label.textContent = f" ・ 毒 {game.poison}" if game.poison else ""
    kills_label.textContent = str(game.kills)
    steps_label.textContent = str(game.steps)
    log_el.textContent = game.log[-1] if game.log else ""
    if game.result is not None:
        message.textContent = f"{RESULT_TEXT[game.result]}  地下 {game.floor} 階  倒した敵 {game.kills}"


def start():
    global game

    game = Game()                                           # 作り直すだけで新しい冒険になる
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
