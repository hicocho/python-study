"""街づくり2（需給と人口と災害）ブラウザ版

CLI 版（g71-town-life/main.py）と中身はまったく同じ。資源の配り方（heapq.merge）も、
満足度（math.prod）も、人口とお金の動きも、災害の乱数の持ち方も、キーを受ける
obey も 1 文字も変えずに持ってきている。

持ってこなかったのは端末に描く Screen.render() と、それを使う play() /
read_keys() / show() / check_terminal() と、自動プレイと検査だけ。
違うのは入口（クリックとボタン）と出口（canvas と HTML）だけ。
"""

import random
from collections import deque
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Flag, auto
from heapq import merge
from math import prod
from typing import Literal

from pyscript import document, when

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


Resource = Literal["power", "water", "food", "goods"]


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
    supply: int = 0                                 # 出せる数（何軒ぶんまかなえるか）
    upkeep: Decimal = Decimal("0")                  # 毎月かかるお金


BRIDGE = Decimal("15")


HOUSE_ROOM = 4                                      # 満ち足りた家 1 軒に住める人数


GOODS_ROOM = 1                                      # 品物も届いていれば、もう 1 人


TAX = Decimal("1")                                  # 1 人あたりの月の税


MONTHS = 30                                         # ここまでにどれだけ育てられるか


GOAL = 60                                           # 目標の人口


KEEP = Decimal("50")                                # 自動プレイが手元に残しておくお金


FIRE = 0.10                                         # 月ごとの火事の起きやすさ


FLOOD = 0.06                                        # 月ごとの洪水の起きやすさ


BUILDS = {
    "road": Build("road", "道路", Decimal("5"), on_water=True, upkeep=Decimal("0.2")),
    "house": Build("house", "家", Decimal("25"), needs=frozenset({"power", "water", "food"})),
    "farm": Build("farm", "畑", Decimal("20"), needs=frozenset({"water"}),
                  gives=frozenset({"food"}), on_hill=False, supply=4, upkeep=Decimal("0.5")),
    "shop": Build("shop", "店", Decimal("40"), needs=frozenset({"power"}),
                  gives=frozenset({"goods"}), supply=6, upkeep=Decimal("1")),
    "plant": Build("plant", "発電所", Decimal("30"), gives=frozenset({"power"}),
                   supply=4, upkeep=Decimal("1")),
    "well": Build("well", "井戸", Decimal("15"), gives=frozenset({"water"}),
                  supply=6, upkeep=Decimal("0.5")),
    "park": Build("park", "公園", Decimal("10"), upkeep=Decimal("0.5")),
}


ORDER = ("road", "house", "farm", "shop", "plant", "well", "park")


NAMES = {"power": "電気", "water": "水", "food": "食べもの", "goods": "品物"}


FILLS = {"power": "plant", "water": "well", "food": "farm", "goods": "shop"}


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


UNHAPPY = (232, 176, 64)                            # 何かが足りていない家の印


BURNT = (52, 48, 52)                                # 焼け跡


FIRE_C = (240, 148, 60)


RESOURCES = ("power", "water", "food", "goods")


def far(a: tuple[int, int], b: tuple[int, int]) -> int:
    """2 マスの遠さ。道をたどらず、縦横の差の合計で見る（同じ区画にいる前提）。"""
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


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
    purse: Decimal = Decimal("500")
    spent: Decimal = Decimal("0")
    month: int = 0
    people: int = 0
    burnt: set = field(default_factory=set)         # 焼け跡・流された跡
    luck: object = None                             # 災害の乱数（街づくりのものと**別**）
    news: str = ""

    def __post_init__(self) -> None:
        if not self.land:
            self.land = make_land(self.seed)
        if self.luck is None:
            self.luck = random.Random(self.seed * 1000 + 7)

    def at(self, spot: tuple[int, int]) -> Land:
        x, y = spot
        return self.land[y][x]

    def clearing(self, spot: tuple[int, int]) -> Decimal:
        """森をどけるお金。土地に手を入れる分だけ高くつく。"""
        return Decimal("8") if self.at(spot) & Land.FOREST else Decimal("0")

    def price(self, spot: tuple[int, int], kind: Kind) -> Decimal:
        """そこにそれを建てるのにかかるお金。**Decimal のまま足す。**

        水の上の道は橋なので高い。**焼け跡は半額**——建て直せない街は死ぬので、
        立ち直る道を残しておく（火事で発電所を失うと詰んだ。実際に詰んだ）。
        """
        extra = BRIDGE if self.at(spot) & Land.WATER else self.clearing(spot)
        cost = BUILDS[kind].cost + extra
        return cost / 2 if spot in self.burnt else cost

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
        self.burnt.discard(spot)                    # 建て直したら焼け跡は消える
        note = ("（跡地なので半額）" if spot in self.burnt
                else "（橋を架けた）" if self.at(spot) & Land.WATER
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

    def deliver(self) -> dict:
        """区画ごとに、近い順で資源を配る。返すのは「どこに何が届いたか」。

        出す建物ごとに「同じ区画で、それを要る建物」を**近い順に並べた列**を作り、
        heapq.merge でひとつの流れにまとめる。**もう並んでいる列どうしを混ぜるだけ**
        なので、全部を集めて並べ直すより素直で、足りなくなった時点で打ち切れる。
        """
        number = self.districts()
        got = {spot: set() for spot in self.tiles}
        for resource in RESOURCES:
            streams, left = [], {}
            takers = [s for s, k in self.tiles.items()
                      if resource in BUILDS[k].needs and s in number]
            for spot, kind in sorted(self.tiles.items()):
                if resource not in BUILDS[kind].gives or spot not in number:
                    continue
                left[spot] = BUILDS[kind].supply
                streams.append(sorted((far(spot, t), t, spot) for t in takers
                                      if number[t] == number[spot]))
            for _, taker, giver in merge(*streams):
                if left[giver] and resource not in got[taker]:
                    left[giver] -= 1
                    got[taker].add(resource)
        return got

    def happy(self, spot: tuple[int, int], got: dict) -> bool:
        """満ち足りているか。**どれかが 0 なら全体も 0**——それを掛け算で表す。

        prod は空っぽのとき 1 を返すので、何も要らない建物（道路や公園）は
        いつでも満ち足りている扱いになる。if を並べるより、この方が短い。
        """
        needs = BUILDS[self.tiles[spot]].needs
        return prod(1 if r in got.get(spot, ()) else 0 for r in needs) == 1

    def room(self, got: dict) -> int:
        """住める人数の合計。品物も届いている家は、もう 1 人入る。"""
        total = 0
        for spot in self.houses:
            if self.happy(spot, got):
                total += HOUSE_ROOM + (GOODS_ROOM if "goods" in got[spot] else 0)
        return total

    def lacking(self, got: dict) -> dict:
        """足りていないものの数え上げ。画面に「何が足りないか」を出すため。"""
        short = {r: 0 for r in RESOURCES}
        for spot, kind in self.tiles.items():
            for resource in BUILDS[kind].needs:
                if resource not in got.get(spot, ()):
                    short[resource] += 1
        return {r: n for r, n in short.items() if n}

    @property
    def upkeep(self) -> Decimal:
        """毎月かかるお金。建てるほど重くなる。"""
        return sum((BUILDS[k].upkeep for k in self.tiles.values()), Decimal("0"))

    def advance(self) -> dict:
        """1 か月ぶん進める。配る → 人が動く → 精算 → 災害。

        **順番が大事**。災害を先に起こすと、その月の税が入る前に建物が消える。
        毎月きっかりこの順なので、「なぜ人口が減ったか」を追える。
        """
        self.month += 1
        got = self.deliver()
        room = self.room(got)
        gap = room - self.people
        step = (abs(gap) + 2) // 3                  # 一度に全部は動かない
        self.people += step if gap > 0 else -min(step, self.people)
        self.purse += TAX * self.people - self.upkeep
        self.news = self.disaster()
        return got

    def disaster(self) -> str:
        """月の終わりに、たまに何かが起きる。**乱数は街づくりのものと別に持つ。**

        しかも**毎月きっかり 4 つの数を引く**。引く数が建物の数で変わると、
        遊び方しだいで災害の並びが変わってしまい、「同じ種なら同じ災害」が
        崩れる（g54 のリプレイで覚えたのと同じ話）。
        """
        fire, flood, pick_a, pick_b = (self.luck.random() for _ in range(4))
        news = []
        if fire < FIRE:
            burnable = sorted(s for s, k in self.tiles.items() if k != "road")
            if burnable:
                spot = burnable[int(pick_a * len(burnable))]
                news.append(f"{BUILDS[self.tiles.pop(spot)].name}が焼けた")
                self.burnt.add(spot)
        if flood < FLOOD:
            wet = sorted(s for s in self.tiles
                         if any(self.at(n) & Land.WATER for n in neighbours(s)))
            if wet:
                spot = wet[int(pick_b * len(wet))]
                news.append(f"{BUILDS[self.tiles.pop(spot)].name}が流された")
                self.burnt.add(spot)
        return "  ".join(news)

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
        """目標: MONTHS か月のうちに、人口 GOAL 人。"""
        return self.people >= GOAL

    @property
    def over(self) -> bool:
        """おしまい: 月を使い切ったか、お金が尽きた。"""
        return self.month >= MONTHS or self.purse < 0


@dataclass
class Game:
    """遊びの状態をひとまとめに。端末もブラウザも、ここだけを触る。"""

    seed: int = 1
    town: Town = None
    cursor: tuple[int, int] = (0, 0)
    picked: int = 0                                 # ORDER の何番目を建てるか
    got: dict = field(default_factory=dict)         # 先月どこに何が届いたか
    note: str = "矢印でカーソル、数字で建てるもの、空白で建てる、n で次の月"

    def __post_init__(self) -> None:
        self.restart()

    def restart(self) -> None:
        self.town = Town(seed=self.seed)
        self.cursor = (0, 0)
        self.got = {}
        self.note = "矢印でカーソル、数字で建てるもの、空白で建てる、n で次の月"

    def next_month(self) -> None:
        """次の月へ。決着していたら、もう進まない。"""
        if self.town.done or self.town.over:
            return
        self.got = self.town.advance()
        short = self.town.lacking(self.got)
        lack = "・".join(f"{NAMES[r]}が {n}" for r, n in short.items()) or "足りないものは無い"
        self.note = f"{self.town.month} 月  {lack}"
        if self.town.news:
            self.note += f"  ★{self.town.news}"

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
        tail = ("   目標達成！" if self.town.done
                else "   おしまい" if self.town.over else "")
        return (f"{self.town.month:2d}/{MONTHS} 月   人 {self.town.people:3d}/{GOAL}   "
                f"財布 {self.town.purse:>7} 円（毎月 −{self.town.upkeep}）   "
                f"区画 {len(marks)}   はなれ {len(self.town.alone()):2d}   "
                f"選択 {BUILDS[self.kind].name}" + tail)


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


def scorch(screen: Screen, spot: tuple[int, int]) -> None:
    """焼け跡・流された跡。建て直すと消える。"""
    x, y = spot
    screen.box(x * CELL + 1, y * CELL + 3, CELL - 2, CELL - 4, BURNT)
    screen.plot(x * CELL + 2, y * CELL + 4, FIRE_C)
    screen.plot(x * CELL + 5, y * CELL + 5, FIRE_C)


def draw(screen: Screen, town: Town, cursor: tuple[int, int] | None = None,
         got: dict | None = None) -> None:
    """1 枚ぶん。土地 → 焼け跡 → 建物 → 印 → カーソル。"""
    screen.clear()
    for y in range(ROWS):
        for x in range(COLS):
            ground(screen, town, (x, y))
    for spot in town.burnt:
        scorch(screen, spot)
    for spot, kind in town.tiles.items():
        if kind == "road" and town.at(spot) & Land.WATER:
            bridge(screen, spot)                    # 水の上の道は橋の絵にする
        else:
            building(screen, kind, spot)
    if got:                                         # 何かが足りていない建物は黄色い枠
        for spot in town.tiles:
            if not town.happy(spot, got):
                screen.frame(spot[0] * CELL, spot[1] * CELL, CELL, CELL, UNHAPPY)
    for x, y in town.alone():                       # 道に触れていない建物は赤い枠で囲む
        screen.frame(x * CELL, y * CELL, CELL, CELL, ALONE)
    if cursor is not None:
        screen.frame(cursor[0] * CELL, cursor[1] * CELL, CELL, CELL, CURSOR)


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
        case "month":
            game.next_month()
        case "reset":
            game.restart()
    return True


def menu() -> str:
    """建てられるものの一覧（番号つき）。"""
    return "  ".join(f"{n + 1} {BUILDS[k].name}{BUILDS[k].cost}" for n, k in enumerate(ORDER))


# --- ここから下はブラウザ版だけ。CLI 版の play() / Screen.render() にあたる ---

canvas = document.querySelector("#screen")
ctx = canvas.getContext("2d")
ctx.imageSmoothingEnabled = False
image = ctx.createImageData(WIDTH, HEIGHT)
purse_label = document.querySelector("#purse")
month_label = document.querySelector("#month")
people_label = document.querySelector("#people")
lack_label = document.querySelector("#lack")
picked_label = document.querySelector("#picked")
message = document.querySelector("#message")
pad = document.querySelector("#pad")


class CanvasScreen(Screen):
    """CLI 版の Screen をそのまま使い、描き終えた画素をまとめて canvas へ送る。"""

    def flush(self) -> None:
        buf = bytearray(WIDTH * HEIGHT * 4)
        i = 0
        for row in self.pixels:
            for color in row:
                if color is not None:
                    buf[i], buf[i + 1], buf[i + 2] = color
                buf[i + 3] = 255
                i += 4
        image.data.assign(bytes(buf))
        ctx.putImageData(image, 0, 0)


screen = CanvasScreen()
game = Game()


def make_buttons() -> None:
    """建てるものボタンを、共有部分の BUILDS から作る。**一覧を 2 か所に書かない。**"""
    for n, kind in enumerate(ORDER):
        button = document.createElement("button")
        button.textContent = f"{BUILDS[kind].name} {BUILDS[kind].cost}"
        button.setAttribute("data-pick", str(n))
        button.className = "kind"                   # 先に付ける（あとからだとクリックが効かない）
        pad.appendChild(button)


def refresh() -> None:
    """CLI 版の show() にあたる。draw() を canvas へ、様子を HTML へ。"""
    draw(screen, game.town, game.cursor, game.got)
    screen.flush()
    purse_label.textContent = f"{game.town.purse}（毎月 −{game.town.upkeep}）"
    month_label.textContent = f"{game.town.month}/{MONTHS}"
    people_label.textContent = f"{game.town.people}/{GOAL}"
    short = game.town.lacking(game.got) if game.got else {}
    lack_label.textContent = ("・".join(f"{NAMES[r]}{n}" for r, n in short.items())
                              or ("—" if not game.got else "なし"))
    picked_label.textContent = BUILDS[game.kind].name
    message.textContent = ("目標達成！ 人口が {} 人になりました。".format(game.town.people)
                           if game.town.done else
                           "おしまい。月を使い切りました。" if game.town.over else game.note)
    message.className = "done" if game.town.done else ("bad" if game.town.over else "")
    for button in document.querySelectorAll(".kind"):
        on = int(button.getAttribute("data-pick")) == game.picked
        button.className = "kind on" if on else "kind"


@when("click", "#pad")
def on_pick(event):
    """建てるものを選ぶ。入れ物の側で受ける（@when は登録時に在る要素にしか付かない）。"""
    picked = event.target.getAttribute("data-pick")
    if picked is None:
        return
    obey(game, f"pick{picked}")                     # 判断は CLI 版と同じ関数
    refresh()


@when("click", "#screen")
def on_map(event):
    """土地をクリック。**画面の大きさから、どのマスかを割り出す。**"""
    box = canvas.getBoundingClientRect()
    x = int((event.clientX - box.left) / box.width * COLS)
    y = int((event.clientY - box.top) / box.height * ROWS)
    game.cursor = (max(0, min(COLS - 1, x)), max(0, min(ROWS - 1, y)))
    obey(game, "build")
    refresh()


@when("click", ".tools")
def on_tool(event):
    key = event.target.getAttribute("data-key")
    if key is None:
        return
    obey(game, key)
    refresh()


KEYS = {"ArrowUp": "up", "ArrowDown": "down", "ArrowLeft": "left", "ArrowRight": "right",
        " ": "build", "x": "remove", "n": "month", "r": "reset"}


@when("keydown", "body")
def on_key(event):
    key = KEYS.get(event.key)
    if key is None and event.key.isdigit() and 1 <= int(event.key) <= len(ORDER):
        key = f"pick{int(event.key) - 1}"
    if key is None:
        return
    event.preventDefault()
    obey(game, key)
    refresh()


# Pyodide の読み込みが終わってから実行される＝ここが準備完了の合図
make_buttons()
document.querySelector("#loading").hidden = True
refresh()
