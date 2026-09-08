"""街づくり — 完成: 土地に建てて、道でつなぐ。つながった建物が「区画」になる。"""

import argparse
import os
import random
import select
import shutil
import sys
import termios
import time
import tty
from collections import deque
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Flag, auto
from typing import Literal

# タプルでまとめて代入すると、ブラウザ版へ切り出す道具（ast で名前を探す）が
# 見つけられない。共有に出す定数は 1 行に 1 つ。
CELL = 8                                            # 1 マスは 8 × 8 ドット
COLS = 16                                           # 土地の広さ（マス）
ROWS = 10
WIDTH = COLS * CELL
HEIGHT = ROWS * CELL


class Land(Flag):
    """土地の性質。**1 つのマスが複数の性質を持てる**ので Flag にする。

    「森のある丘」は HILL | FOREST。ふつうの Enum だと組み合わせの数だけ
    名前を作ることになる。in で「丘を含むか」を聞けるのも Flag の効き目。
    """

    PLAIN = 0                                       # 何も無い平地
    WATER = auto()
    HILL = auto()
    FOREST = auto()


# 資源の名前。**文字列そのものを型にする**ので、"powr" と書き間違えると型検査で止まる。
# 実行時はただの str なので、辞書の鍵にもそのまま使える。
Resource = Literal["power", "water", "food", "goods"]

# 建てられるものの名前。こちらも Literal。増やすときはここと BUILDS の 2 か所。
Kind = Literal["road", "house", "farm", "shop", "plant", "well", "park"]


@dataclass(frozen=True)
class Build:
    """建てられるもの 1 種類。値段と、要るもの・出すもの。

    要る／出すは g71（需給）で使う。ここでは画面に出すだけだが、
    **表を先に作っておく**と、次の課題で足すのが表への 1 行になる。
    """

    kind: Kind
    name: str
    cost: Decimal
    needs: frozenset = frozenset()
    gives: frozenset = frozenset()
    on_hill: bool = True                            # 丘に建てられるか
    on_water: bool = False                          # 水の上に建てられるか（道だけ＝橋）


# 橋（水の上の道）に足すお金。川で二つに割れた土地をつなぐ唯一の手。
BRIDGE = Decimal("15")

# 建てられるものの表。お金は **Decimal**（あとで足し引きするので、浮動小数では持たない）。
BUILDS = {
    "road": Build("road", "道路", Decimal("5"), on_water=True),
    "house": Build("house", "家", Decimal("25"), needs=frozenset({"power", "water", "food"})),
    "farm": Build("farm", "畑", Decimal("20"), needs=frozenset({"water"}),
                  gives=frozenset({"food"}), on_hill=False),
    "shop": Build("shop", "店", Decimal("40"), needs=frozenset({"power"}),
                  gives=frozenset({"goods"})),
    "plant": Build("plant", "発電所", Decimal("80"), gives=frozenset({"power"})),
    "well": Build("well", "井戸", Decimal("15"), gives=frozenset({"water"})),
    "park": Build("park", "公園", Decimal("10")),
}

ORDER = ("road", "house", "farm", "shop", "plant", "well", "park")

GRASS = (58, 92, 60)
GRASS_DOT = (72, 110, 72)
FOREST_C = (34, 68, 44)
FOREST_TOP = (54, 100, 62)
HILL_C = (108, 96, 70)
HILL_TOP = (134, 120, 88)
WATER_C = (44, 86, 132)
WATER_TOP = (68, 118, 168)
ROAD_C = (96, 96, 100)
ROAD_LINE = (168, 168, 172)
HOUSE_C = (206, 176, 140)
HOUSE_ROOF = (176, 92, 78)
FARM_C = (188, 158, 78)
FARM_LINE = (150, 122, 54)
SHOP_C = (92, 132, 186)
SHOP_TOP = (146, 182, 224)
PLANT_C = (110, 108, 118)
PLANT_TOP = (176, 176, 186)
WELL_C = (86, 150, 168)
PARK_C = (86, 156, 92)
BRIDGE_C = (150, 128, 96)
BRIDGE_RAIL = (196, 176, 140)
CURSOR = (250, 250, 240)
ALONE = (208, 88, 88)                               # 道につながっていない建物の印


def neighbours(spot: tuple[int, int]):
    """上下左右の 4 マス。土地の外は返さない。"""
    x, y = spot
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        if 0 <= x + dx < COLS and 0 <= y + dy < ROWS:
            yield (x + dx, y + dy)


def make_land(seed: int) -> list[list[Land]]:
    """土地を作る。**同じ種なら必ず同じ土地**（あとで面として配れる）。

    川を 1 本流し、丘と森をいくつか置く。丘の上に森が生えることもあるので、
    性質は | で重ねる。
    """
    rng = random.Random(seed)
    land = [[Land.PLAIN] * COLS for _ in range(ROWS)]
    x = rng.randrange(3, COLS - 3)                  # 川。上から下へ、少し蛇行する
    for y in range(ROWS):
        land[y][x] |= Land.WATER
        x = max(1, min(COLS - 2, x + rng.choice((-1, 0, 0, 1))))
    for _ in range(rng.randrange(2, 4)):            # 丘
        cx, cy = rng.randrange(COLS), rng.randrange(ROWS)
        for y in range(max(0, cy - 1), min(ROWS, cy + 2)):
            for x in range(max(0, cx - 1), min(COLS, cx + 2)):
                if not land[y][x] & Land.WATER:
                    land[y][x] |= Land.HILL
    for _ in range(rng.randrange(8, 14)):           # 森
        x, y = rng.randrange(COLS), rng.randrange(ROWS)
        if not land[y][x] & Land.WATER:
            land[y][x] |= Land.FOREST
    return land


@dataclass
class Town:
    """街ひとつ。土地と、建てたものと、財布。"""

    seed: int = 1
    land: list = field(default_factory=list)
    tiles: dict = field(default_factory=dict)       # (x, y) → 建てたものの種類
    purse: Decimal = Decimal("300")
    spent: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if not self.land:
            self.land = make_land(self.seed)

    def at(self, spot: tuple[int, int]) -> Land:
        x, y = spot
        return self.land[y][x]

    def clearing(self, spot: tuple[int, int]) -> Decimal:
        """森をどけるお金。土地に手を入れる分だけ高くつく。"""
        return Decimal("8") if self.at(spot) & Land.FOREST else Decimal("0")

    def price(self, spot: tuple[int, int], kind: Kind) -> Decimal:
        """そこにそれを建てるのにかかるお金。**Decimal のまま足す。**

        水の上の道は橋なので高い。ここで足す物が増えても、浮動小数のような
        「0.1 + 0.2 が 0.30000000000000004」は起きない。
        """
        extra = BRIDGE if self.at(spot) & Land.WATER else self.clearing(spot)
        return BUILDS[kind].cost + extra

    def refuse(self, spot: tuple[int, int], kind: Kind) -> str | None:
        """建てられない理由。建てられるなら None。

        「なぜ駄目か」を返す形にすると、画面もテストも同じ言葉を使える。
        """
        if spot in self.tiles:
            return "もう何か建っている"
        if self.at(spot) & Land.WATER and not BUILDS[kind].on_water:
            return "水の上には建てられない（橋にできるのは道路だけ）"
        if self.at(spot) & Land.HILL and not BUILDS[kind].on_hill:
            return f"{BUILDS[kind].name}は丘に建てられない"
        if self.price(spot, kind) > self.purse:
            return f"お金が足りない（{self.price(spot, kind)} 要る）"
        return None

    def build(self, spot: tuple[int, int], kind: Kind) -> str:
        """建てる。建てられなければ、その理由を返す。"""
        if (why := self.refuse(spot, kind)) is not None:
            return why
        cost = self.price(spot, kind)
        self.purse -= cost
        self.spent += cost
        self.tiles[spot] = kind
        note = ("（橋を架けた）" if self.at(spot) & Land.WATER
                else "（森をどけた）" if self.clearing(spot) else "")
        return f"{BUILDS[kind].name}を建てた {cost} 円{note}"

    def remove(self, spot: tuple[int, int]) -> str:
        """壊す。半分だけ戻ってくる。"""
        kind = self.tiles.pop(spot, None)
        if kind is None:
            return "ここには何も無い"
        back = BUILDS[kind].cost / 2                # Decimal どうしなので、割っても Decimal
        self.purse += back
        return f"{BUILDS[kind].name}を壊した {back} 円もどった"

    def districts(self) -> dict:
        """道でつながったかたまりに番号を振る。建物は隣の道の番号をもらう。

        道から道へ幅優先で塗り、そのあと建物が周りを見る。**道に触れていない
        建物には番号が付かない**——それが「つながっていない」ということ。
        """
        number, mark = {}, 0
        for spot, kind in sorted(self.tiles.items()):
            if kind != "road" or spot in number:
                continue
            mark += 1
            number[spot] = mark
            queue = deque([spot])
            while queue:
                for near in neighbours(queue.popleft()):
                    if self.tiles.get(near) == "road" and near not in number:
                        number[near] = mark
                        queue.append(near)
        for spot, kind in sorted(self.tiles.items()):
            if kind == "road":
                continue
            near = [number[p] for p in neighbours(spot) if self.tiles.get(p) == "road"]
            if near:
                number[spot] = min(near)            # 2 つの道に挟まれたら、若い方に付く
        return number

    def alone(self) -> set:
        """道につながっていない建物。"""
        number = self.districts()
        return {spot for spot in self.tiles if spot not in number}

    @property
    def houses(self) -> list:
        return [spot for spot, kind in self.tiles.items() if kind == "house"]

    def linked(self) -> bool:
        """家が全部、ひとつの区画にいるか。"""
        number = self.districts()
        marks = {number.get(spot) for spot in self.houses}
        return len(marks) == 1 and None not in marks

    @property
    def done(self) -> bool:
        """目標: 家 6 軒が、ひとつの道でつながっている。"""
        return len(self.houses) >= 6 and self.linked()


@dataclass
class Game:
    """遊びの状態をひとまとめに。端末もブラウザも、ここだけを触る。"""

    seed: int = 1
    town: Town = None
    cursor: tuple[int, int] = (0, 0)
    picked: int = 0                                 # ORDER の何番目を建てるか
    note: str = "矢印でカーソル、数字で建てるもの、空白で建てる"

    def __post_init__(self) -> None:
        self.restart()

    def restart(self) -> None:
        self.town = Town(seed=self.seed)
        self.cursor = (0, 0)
        self.note = "矢印でカーソル、数字で建てるもの、空白で建てる"

    @property
    def kind(self) -> Kind:
        return ORDER[self.picked]

    def move(self, dx: int, dy: int) -> None:
        x = max(0, min(COLS - 1, self.cursor[0] + dx))
        y = max(0, min(ROWS - 1, self.cursor[1] + dy))
        self.cursor = (x, y)

    def build(self) -> None:
        self.note = self.town.build(self.cursor, self.kind)

    def remove(self) -> None:
        self.note = self.town.remove(self.cursor)

    def pick(self, n: int) -> None:
        self.picked = n % len(ORDER)
        self.note = f"{BUILDS[self.kind].name}を選んだ（{BUILDS[self.kind].cost} 円）"

    def status(self) -> str:
        """1 行の様子書き。桁を決めて書くので、上書きしても残らない。"""
        marks = set(self.town.districts().values())
        return (f"財布 {self.town.purse:>6} 円   家 {len(self.town.houses)}/6   "
                f"区画 {len(marks)}   はなれた建物 {len(self.town.alone()):2d}   "
                f"選択 {BUILDS[self.kind].name}"
                + ("   街びらき！" if self.town.done else ""))


class Screen:
    """WIDTH × HEIGHT のドットの板。1 ドットは RGB か None（黒）。"""

    def __init__(self):
        self.pixels: list[list[tuple[int, int, int] | None]] = [[None] * WIDTH for _ in range(HEIGHT)]

    def clear(self) -> None:
        for row in self.pixels:
            row[:] = [None] * WIDTH

    def plot(self, x: int, y: int, color: tuple[int, int, int]) -> None:
        if 0 <= x < WIDTH and 0 <= y < HEIGHT:
            self.pixels[y][x] = color

    def box(self, x: int, y: int, w: int, h: int, color: tuple[int, int, int]) -> None:
        for row in range(y, y + h):
            for col in range(x, x + w):
                self.plot(col, row, color)

    def frame(self, x: int, y: int, w: int, h: int, color: tuple[int, int, int]) -> None:
        for i in range(w):
            self.plot(x + i, y, color)
            self.plot(x + i, y + h - 1, color)
        for i in range(h):
            self.plot(x, y + i, color)
            self.plot(x + w - 1, y + i, color)

    def render(self) -> str:
        """端末用の文字列。1 行に 2 ドット分の行を詰める（上が前景 ▀、下が背景）。"""
        out = []
        last = None
        for top, bottom in zip(self.pixels[0::2], self.pixels[1::2]):
            for a, b in zip(top, bottom):
                if a is None and b is None:
                    code, ch = "\x1b[0m", " "
                elif b is None:
                    code, ch = f"\x1b[0m\x1b[38;2;{a[0]};{a[1]};{a[2]}m", "▀"
                elif a is None:
                    code, ch = f"\x1b[0m\x1b[38;2;{b[0]};{b[1]};{b[2]}m", "▄"
                else:
                    code, ch = f"\x1b[38;2;{a[0]};{a[1]};{a[2]}m\x1b[48;2;{b[0]};{b[1]};{b[2]}m", "▀"
                if code != last:
                    out.append(code)
                    last = code
                out.append(ch)
            out.append("\x1b[0m\n")
            last = None
        return "".join(out)


def ground(screen: Screen, town: Town, spot: tuple[int, int]) -> None:
    """土地そのもの。水 → 丘 → 平地 の順に色を決め、森はその上に木を置く。"""
    x, y = spot
    px, py = x * CELL, y * CELL
    land = town.at(spot)
    if land & Land.WATER:
        screen.box(px, py, CELL, CELL, WATER_C)
        for i in range(1, CELL, 3):                 # 波の線
            screen.plot(px + i, py + 2 + (i % 2) * 3, WATER_TOP)
        return
    screen.box(px, py, CELL, CELL, GRASS)           # まず草地。丘も森もこの上に乗せる
    screen.plot(px + 2, py + 5, GRASS_DOT)
    screen.plot(px + 5, py + 2, GRASS_DOT)
    if land & Land.HILL:                            # 丘は「盛り上がり」。四角く塗ると建物に見える
        screen.box(px + 1, py + 4, CELL - 2, 3, HILL_C)
        screen.box(px + 2, py + 3, CELL - 4, 2, HILL_TOP)
    if land & Land.FOREST:
        screen.box(px + 2, py + 4, 4, 3, FOREST_C)
        screen.box(px + 3, py + 1, 2, 4, FOREST_TOP)


def building(screen: Screen, kind: Kind, spot: tuple[int, int]) -> None:
    """建てたもの 1 つ。8 × 8 なので、形は思い切って単純にする。"""
    x, y = spot
    px, py = x * CELL, y * CELL
    match kind:
        case "road":
            screen.box(px, py, CELL, CELL, ROAD_C)
            for i in range(1, CELL, 3):
                screen.plot(px + i, py + CELL // 2, ROAD_LINE)
        case "house":
            screen.box(px + 1, py + 3, CELL - 2, CELL - 4, HOUSE_C)
            screen.box(px + 1, py + 2, CELL - 2, 2, HOUSE_ROOF)
        case "farm":
            screen.box(px + 1, py + 1, CELL - 2, CELL - 2, FARM_C)
            for i in range(2, CELL - 1, 2):
                screen.plot(px + i, py + 2, FARM_LINE)
                screen.plot(px + i, py + 5, FARM_LINE)
        case "shop":
            screen.box(px + 1, py + 2, CELL - 2, CELL - 3, SHOP_C)
            screen.box(px + 2, py + 3, CELL - 4, 2, SHOP_TOP)
        case "plant":
            screen.box(px + 1, py + 3, CELL - 2, CELL - 4, PLANT_C)
            screen.box(px + 2, py, 2, 4, PLANT_TOP)
        case "well":
            screen.box(px + 2, py + 2, CELL - 4, CELL - 4, WELL_C)
            screen.plot(px + 3, py + 3, WATER_TOP)
        case "park":
            screen.box(px + 1, py + 1, CELL - 2, CELL - 2, PARK_C)
            screen.plot(px + 3, py + 3, FOREST_TOP)
            screen.plot(px + 4, py + 4, FOREST_TOP)


def bridge(screen: Screen, spot: tuple[int, int]) -> None:
    """橋。水を残したまま、板と欄干だけを描く。"""
    x, y = spot
    px, py = x * CELL, y * CELL
    screen.box(px, py + 2, CELL, CELL - 4, BRIDGE_C)
    for i in range(0, CELL):
        screen.plot(px + i, py + 2, BRIDGE_RAIL)
        screen.plot(px + i, py + CELL - 3, BRIDGE_RAIL)


def draw(screen: Screen, town: Town, cursor: tuple[int, int] | None = None) -> None:
    """1 枚ぶん。土地 → 建物 → つながっていない印 → カーソル。"""
    screen.clear()
    for y in range(ROWS):
        for x in range(COLS):
            ground(screen, town, (x, y))
    for spot, kind in town.tiles.items():
        if kind == "road" and town.at(spot) & Land.WATER:
            bridge(screen, spot)                    # 水の上の道は橋の絵にする
        else:
            building(screen, kind, spot)
    for x, y in town.alone():                       # 道に触れていない建物は赤い枠で囲む
        screen.frame(x * CELL, y * CELL, CELL, CELL, ALONE)
    if cursor is not None:
        screen.frame(cursor[0] * CELL, cursor[1] * CELL, CELL, CELL, CURSOR)


def read_keys(fd: int) -> list[str]:
    """押されたキーを名前で。"""
    keys = []
    while select.select([fd], [], [], 0)[0]:
        text = os.read(fd, 64).decode(errors="ignore")
        for token, name in (("\x1b[A", "up"), ("\x1b[B", "down"), ("\x1b[D", "left"),
                            ("\x1b[C", "right"), (" ", "build"), ("x", "remove"),
                            ("r", "reset"), ("q", "quit")):
            keys.extend([name] * text.count(token))
        for n in range(len(ORDER)):
            keys.extend([f"pick{n}"] * text.count(str(n + 1)))
    return keys


def obey(game: Game, key: str) -> bool:
    """キー 1 つ。やめるなら False。端末でもブラウザでも同じ物を使う。"""
    if key.startswith("pick"):
        game.pick(int(key[4:]))
        return True
    match key:
        case "quit":
            return False
        case "up":
            game.move(0, -1)
        case "down":
            game.move(0, 1)
        case "left":
            game.move(-1, 0)
        case "right":
            game.move(1, 0)
        case "build":
            game.build()
        case "remove":
            game.remove()
        case "reset":
            game.restart()
    return True


def menu() -> str:
    """建てられるものの一覧（番号つき）。"""
    return "  ".join(f"{n + 1} {BUILDS[k].name}{BUILDS[k].cost}" for n, k in enumerate(ORDER))


def show(game: Game) -> None:
    """画面を 1 枚。上が土地、下が様子。"""
    screen = Screen()
    draw(screen, game.town, game.cursor)
    sys.stdout.write("\x1b[H" + screen.render() + "\x1b[0m"
                     + game.status() + "\x1b[K\n"
                     + menu() + "\x1b[K\n"
                     + game.note + "\x1b[K\n"
                     + "空白 建てる  x 壊す  r やり直し  q やめる\x1b[K\n\x1b[J")
    sys.stdout.flush()


def check_terminal() -> str | None:
    columns, lines = shutil.get_terminal_size()
    need = HEIGHT // 2 + 6
    if columns < WIDTH or lines < need:
        return f"端末を {WIDTH} 桁 × {need} 行以上にしてください（今は {columns} × {lines}）。"
    return None


def play(game: Game) -> None:
    """端末で遊ぶ。押されたキーを obey に渡すだけ。"""
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    tty.setcbreak(fd)
    try:
        sys.stdout.write("\x1b[2J\x1b[?25l")
        show(game)
        while True:
            for key in read_keys(fd):
                if not obey(game, key):
                    return
                show(game)
            time.sleep(0.03)
    finally:
        sys.stdout.write("\x1b[0m\x1b[?25h")
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    print()


def autobuild(town: Town) -> list[str]:               # ←
    """自動で街を作る。**目標が達成できる土地かどうか**を、これで確かめる。

    やり方は素朴に「水と丘を避けて、横一本の道を通し、その上下に家を置く」。
    人が遊ぶより下手でいいが、これで届かない土地は配ってはいけない。
    """
    out = []
    best, score = None, -1
    for y in range(1, ROWS - 1):                    # いちばん陸の多い行に道を通す
        free = sum(not town.at((x, y)) & Land.WATER for x in range(COLS))
        if free > score:
            best, score = y, free
    for x in range(COLS):
        town.build((x, best), "road")               # 水の上は橋になる
    for y in (best - 1, best + 1):
        for x in range(COLS):
            if len(town.houses) >= 6:
                break
            if town.refuse((x, y), "house") is None and town.tiles.get((x, best)) == "road":
                town.build((x, y), "house")
    out.append(f"道 {sum(k == 'road' for k in town.tiles.values()):2d} 本  "
               f"家 {len(town.houses)} 軒  残り {town.purse:>6} 円  "
               f"区画 {len(set(town.districts().values()))}  "
               f"{'街びらき' if town.done else 'まだ'}")
    return out


def check_seeds(count: int = 8) -> list[str]:         # ←
    """配る土地が、どれも目標にたどり着けるかを見る。"""
    out = []
    for seed in range(1, count + 1):
        town = Town(seed=seed)
        water = sum(bool(land & Land.WATER) for row in town.land for land in row)
        hill = sum(bool(land & Land.HILL) for row in town.land for land in row)
        forest = sum(bool(land & Land.FOREST) for row in town.land for land in row)
        line = autobuild(town)[0]
        out.append(f"種 {seed}  水 {water:2d} 丘 {hill:2d} 森 {forest:2d}  {line}")
    return out


def main():
    parser = argparse.ArgumentParser(description="街づくり — 土地と建物と道")
    parser.add_argument("--seed", type=int, default=1, help="土地の種")
    parser.add_argument("--check", action="store_true", help="配る土地が目標に届くか見る")
    parser.add_argument("--auto", action="store_true", help="自動で街を作ってみせる")
    args = parser.parse_args()
    if args.check:
        for line in check_seeds():
            print(line)
        return
    if args.auto:
        town = Town(seed=args.seed)
        for line in autobuild(town):
            print(line)
        return
    if problem := check_terminal():
        print(problem)
        return
    play(Game(seed=args.seed))


if __name__ == "__main__":
    main()
