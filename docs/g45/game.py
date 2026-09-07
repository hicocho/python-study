"""グラディウス風（パワーアップ）ブラウザ版

CLI 版（g45-gradius-powerup/main.py）とドット絵・地形・当たり判定はまったく同じ。
定数とパレット、Sprite / sprite()、スプライト、Screen、png_bytes() / data_uri()、Body / Drawable / Terrain / Starfield / Kind / Spawn / Bullet / Enemy、FACTORY、make_script()、Power / Capsule / Missile / Laser / Weapon（ABC）と hit()（singledispatch）、Player / Shot / Explosion、
autopilot()、そして class Game を、ステップの目印コメント（# ←）を外しただけで 1 文字も変えずに持ってきている。

持ってこなかったのは端末に描く Screen.render() を使う play() / read_keys() / check_terminal() / main() だけ。
出口は canvas。Screen と同じ clear() / plot() / blit() を持つ CanvasScreen を渡して、Game.draw() をそのまま呼ぶ。
"""

import asyncio
import base64
import math
import random
import struct
import zlib
from abc import ABC, abstractmethod
from bisect import bisect_right
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum, auto
from functools import cache, partial, singledispatch
from itertools import groupby, pairwise
from typing import Protocol, runtime_checkable

from js import Image, window
from pyscript import document, when
WIDTH = 128                                 # 横長の画面（端末では 1 ドット = 1 桁）


HEIGHT = 80                                 # 端末では 2 ドット = 1 行 → 40 行


FPS = 30


PLAYER_SPEED = 55.0                         # ドット/秒


BULLET_SPEED = 150.0


MAX_BULLETS = 3


SCROLL_SPEED = 24.0                         # 地形が流れる速さ（ドット/秒）


STAGE_LENGTH = 2400                         # ステージの長さ（世界座標のドット）。100 秒で終わる


SEGMENT = 24                                # 地形の折れ線の間隔


LIVES = 3


RESPAWN_DELAY = 1.5


SAFE_TIME = 2.0                             # 復活直後の無敵（点滅）


STAR_COUNT = 30


FAN_SPEED = 40.0                            # ファン（波打って飛ぶ）の速さ


GARUN_SPEED = 85.0                          # ガルン（まっすぐ速い）


DUCKER_SPEED = 30.0                         # ダッカー（地面を歩く）


ENEMY_BULLET_SPEED = 44.0


CANNON_INTERVAL = 2.2                       # 砲台が撃つ間隔（秒）


CAPSULE_EVERY = 3                           # 何体倒すごとにカプセルが出るか


CAPSULE_SPEED = 20.0                        # カプセルが左へ流れる速さ


SPEED_STEP = 12.0                           # スピードアップ 1 段の増分（最大 3 段）


MISSILE_SPEED = 70.0


LASER_LENGTH = 24


SHIELD_HITS = 3                             # シールドが受けられる回数


PALETTE = {
    "W": (255, 255, 255), "R": (230, 40, 40), "B": (40, 90, 230), "Y": (250, 220, 50),
    "G": (60, 200, 90), "C": (90, 220, 240), "M": (200, 70, 220), "O": (250, 140, 30),
    "K": (40, 40, 60), "L": (150, 190, 255), "P": (255, 140, 180), "D": (120, 20, 20),
}


GROUND = (110, 80, 50)                      # 地形の色（下）


GROUND_EDGE = (70, 190, 90)                 # 地面の表面


CEILING = (90, 70, 110)                     # 地形の色（上）


CEILING_EDGE = (150, 120, 200)


RESULT_TEXT = {
    "clear": "ステージを抜けた！",
    "over": "撃墜された…",
    "quit": "やめました。",
}


@dataclass(frozen=True)
class Sprite:
    """ドット絵 1 枚。rows は 1 行 1 文字列で、文字がパレットの色、. が透明。"""

    name: str
    rows: tuple[str, ...]
    palette: dict[str, tuple[int, int, int]] = field(default_factory=lambda: PALETTE, hash=False, compare=False)

    @property
    def width(self) -> int:
        return len(self.rows[0])

    @property
    def height(self) -> int:
        return len(self.rows)

    @property
    def pixels(self) -> list[tuple[int, int, tuple[int, int, int]]]:
        """(x, y, 色) の一覧。透明は含まない。"""
        return [(x, y, self.palette[ch]) for y, row in enumerate(self.rows) for x, ch in enumerate(row) if ch != "."]

    def recolor(self, mapping: dict[str, str]) -> "Sprite":
        """文字を別の色の文字に置き換えた新しいスプライト（例: 緑のボスを紫に）。"""
        table = str.maketrans(mapping)
        return Sprite(self.name, tuple(row.translate(table) for row in self.rows), self.palette)

    def __str__(self) -> str:
        return "\n".join(self.rows)


def sprite(name: str, art: str) -> Sprite:
    """三重引用符のドット絵から Sprite を作る。空行は無視、幅は最長の行にそろえる。"""
    rows = [line for line in art.splitlines() if line.strip()]
    width = max(len(r) for r in rows)
    return Sprite(name, tuple(r.ljust(width, ".") for r in rows))


VIC = sprite("vic", """
..W.............
..WW............
..WWWBB.........
.WWWWBBWWWWWW...
LWWWWWWWWWWWWWWW
RWWWWBBWWWWWWWW.
..WWWBB.........
..WW............
..W.............
""")


BULLET = sprite("bullet", """
WLLW
""")


FAN = [sprite("fan-a", """
..OOOO..
.OYYYYO.
OYWWWWYO
OYWYYWYO
OYWYYWYO
OYWWWWYO
.OYYYYO.
..OOOO..
"""), sprite("fan-b", """
..OOOO..
.OYYYYO.
OYYWWYYO
OYWWWWYO
OYWWWWYO
OYYWWYYO
.OYYYYO.
..OOOO..
""")]


GARUN = sprite("garun", """
......MM..
..MMMMPPM.
MMPPPPWWPM
..MMMMPPM.
......MM..
""")


DUCKER = sprite("ducker", """
..GGGG..
.GGWWGG.
GGGGGGGG
.G.GG.G.
.G....G.
""")


CANNON = sprite("cannon", """
...CC...
..CWWC..
.CCCCCC.
KKKKKKKK
KKKKKKKK
""")


ENEMY_BULLET = sprite("enemy-bullet", """
RY
YR
""")


CAPSULE = sprite("capsule", """
.RRRR.
RWWWWR
RWRRWR
RWWWWR
.RRRR.
""")


MISSILE = sprite("missile", """
YO
""")


LASER = sprite("laser", """
CCCCCCCCCCCCCCCCCCCCCCCC
LLLLLLLLLLLLLLLLLLLLLLLL
""")


SHIELD = sprite("shield", """
.C
CC
CC
CC
CC
CC
CC
CC
.C
""")


EXPLOSION = [sprite("boom-1", """
.....Y.....
....YOY....
...YOWOY...
....YOY....
.....Y.....
"""), sprite("boom-2", """
....R.R....
..R.YOY.R..
...YOWOY...
.R.OWWWO.R.
...YOWOY...
..R.YOY.R..
....R.R....
"""), sprite("boom-3", """
..R.....R..
.R.O...O.R.
..O.Y.Y.O..
...Y.O.Y...
R..O.W.O..R
...Y.O.Y...
..O.Y.Y.O..
.R.O...O.R.
..R.....R..
"""), sprite("boom-4", """
R....D....R
.D.......D.
..R.....R..
...D...D...
....R.R....
D....D....D
....R.R....
...D...D...
..R.....R..
.D.......D.
R....D....R
""")]


class Screen:
    """WIDTH × HEIGHT のドットのキャンバス。1 ドットは RGB か None（黒）。"""

    def __init__(self):
        self.pixels: list[list[tuple[int, int, int] | None]] = [[None] * WIDTH for _ in range(HEIGHT)]

    def clear(self) -> None:
        for row in self.pixels:
            row[:] = [None] * WIDTH

    def plot(self, x: int, y: int, color: tuple[int, int, int]) -> None:
        if 0 <= x < WIDTH and 0 <= y < HEIGHT:
            self.pixels[y][x] = color

    def blit(self, spr: Sprite, x: float, y: float) -> None:
        """スプライトを (x, y) を左上にして置く。透明は上書きしない。"""
        ox, oy = round(x), round(y)
        for px, py, color in spr.pixels:
            self.plot(ox + px, oy + py, color)


def png_bytes(spr: Sprite, scale: int = 1, background: tuple[int, int, int] | None = None) -> bytes:
    """スプライトを PNG に。ライブラリなしで、チャンクを struct と zlib で組み立てる。background が無ければ透明。"""
    w, h = spr.width * scale, spr.height * scale
    colors = {(x, y): c for x, y, c in spr.pixels}
    blank = bytes(background) + b"\xff" if background else b"\x00\x00\x00\x00"
    raw = bytearray()
    for y in range(h):
        raw.append(0)                                       # フィルタ 0（そのまま）
        for x in range(w):
            c = colors.get((x // scale, y // scale))
            raw += bytes(c) + b"\xff" if c else blank

    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

    header = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)   # 8 ビット、RGBA
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b"")


@cache
def data_uri(spr: Sprite, scale: int = 1) -> str:
    """ブラウザで <img src=...> に入れる文字列。同じスプライトは一度だけ作る。"""
    return "data:image/png;base64," + base64.b64encode(png_bytes(spr, scale)).decode()


def sprite_sheet(sprites: list[Sprite], gap: int = 2) -> Sprite:
    """複数のスプライトを横に並べた 1 枚（README 用）。"""
    height = max(s.height for s in sprites)
    rows = []
    for y in range(height):
        line = ""
        for s in sprites:
            line += (s.rows[y] if y < s.height else "." * s.width) + "." * gap
        rows.append(line)
    return Sprite("sheet", tuple(rows))


ALL_SPRITES = [VIC, BULLET, *FAN, GARUN, DUCKER, CANNON, ENEMY_BULLET, CAPSULE, MISSILE, LASER, SHIELD, *EXPLOSION]


@dataclass
class Body:
    """動くもの。左上の座標とスプライト。"""

    x: float
    y: float
    spr: Sprite

    def overlaps(self, other: "Body") -> bool:
        """矩形どうしが重なるか。"""
        return (self.x < other.x + other.spr.width and other.x < self.x + self.spr.width
                and self.y < other.y + other.spr.height and other.y < self.y + self.spr.height)


@runtime_checkable
class Drawable(Protocol):
    """画面に描けるもの。draw(screen, scroll) を持っていればよい（継承は要らない）。"""

    def draw(self, screen: Screen, scroll: float) -> None: ...


class Terrain:
    """上下の地形。世界座標 x ごとの高さを、SEGMENT ごとの折れ線で持つ。"""

    def __init__(self, rng: random.Random, length: int = STAGE_LENGTH):
        self.xs = list(range(0, length + SEGMENT * 3, SEGMENT))
        self.floors: list[float] = []                       # 各 x での地面の高さ（画面の下から）
        self.ceilings: list[float] = []                     # 天井の高さ（画面の上から）
        center = HEIGHT / 2                                 # 通り道の真ん中。上下にふらつく
        for x in self.xs:
            narrow = min(1.0, x / length)                   # 先へ行くほど狭くなる
            gap = 60 - 26 * narrow + rng.uniform(-4, 4)     # 通り道の広さ 60 → 34
            if x >= SEGMENT * 2:                            # 出だし 2 本は平ら
                center = max(gap / 2 + 2, min(HEIGHT - gap / 2 - 2, center + rng.uniform(-12, 12)))
            self.ceilings.append(max(0.0, center - gap / 2))
            self.floors.append(max(0.0, HEIGHT - (center + gap / 2)))
        self.segments = list(pairwise(zip(self.xs, self.floors, self.ceilings)))   # 隣り合う 2 点の組

    def heights(self, world_x: float) -> tuple[float, float]:
        """世界座標 x での (地面の高さ, 天井の高さ)。折れ線の間は直線で補間。"""
        i = min(max(bisect_right(self.xs, world_x) - 1, 0), len(self.segments) - 1)
        (x0, f0, c0), (x1, f1, c1) = self.segments[i]
        t = min(max((world_x - x0) / (x1 - x0), 0.0), 1.0)
        return f0 + (f1 - f0) * t, c0 + (c1 - c0) * t

    def hits(self, body: Body, scroll: float) -> bool:
        """体の矩形が地形に触れているか。横 1 ドットごとに高さを見る。"""
        for column in range(int(body.x), int(body.x + body.spr.width)):
            floor, ceiling = self.heights(column + scroll)
            if body.y < ceiling or body.y + body.spr.height > HEIGHT - floor:
                return True
        return False

    def draw(self, screen: Screen, scroll: float) -> None:
        for column in range(WIDTH):
            floor, ceiling = self.heights(column + scroll)
            top = int(ceiling)
            for y in range(top):
                screen.plot(column, y, CEILING_EDGE if y == top - 1 else CEILING)
            bottom = HEIGHT - int(floor)
            for y in range(bottom, HEIGHT):
                screen.plot(column, y, GROUND_EDGE if y == bottom else GROUND)


class Starfield:
    """奥の星。地形より遅く流れる（視差）。"""

    def __init__(self, rng: random.Random):
        self.stars = [(rng.uniform(0, WIDTH), rng.uniform(0, HEIGHT), rng.choice([0.2, 0.4, 0.6])) for _ in range(STAR_COUNT)]

    def draw(self, screen: Screen, scroll: float) -> None:
        for x, y, depth in self.stars:
            sx = int((x - scroll * depth) % WIDTH)
            screen.plot(sx, int(y), (90, 90, 130) if depth < 0.5 else (170, 170, 220))


class Kind(Enum):
    """敵の種類。auto() で値を自動に（値そのものは使わない）。"""

    FAN = auto()                                            # 波打って飛んでくる。4 体 1 組
    GARUN = auto()                                          # まっすぐ速い
    DUCKER = auto()                                         # 地面を歩く
    CANNON = auto()                                         # 地面の砲台。動かず、自機を狙って撃つ


@dataclass(kw_only=True)
class Spawn:
    """出現表の 1 行。スクロールが at に達したら kind を count 体、gap ドットおきに出す。"""

    at: int                                                 # 世界座標（画面の右端がここに来たら）
    kind: Kind
    count: int = 1
    gap: int = 14
    y: float | None = None                                  # 出す高さ。None なら種類ごとの既定（地上の敵は地面）


@dataclass
class Bullet(Body):
    """敵の弾。向きを持つ。"""

    vx: float = -ENEMY_BULLET_SPEED
    vy: float = 0.0

    def draw(self, screen: Screen, scroll: float) -> None:
        screen.blit(self.spr, self.x, self.y)


@dataclass
class Enemy(Body):
    """敵。動きは mover（関数）に任せる。"""

    kind: Kind = Kind.FAN
    points: int = 100
    hp: int = 1
    mover: "Callable[[Enemy, Game, float], None] | None" = None
    frames: list[Sprite] = field(default_factory=list)      # アニメのコマ（あれば）
    base_y: float = 0.0                                     # 波の中心など、動きの基準
    phase: float = 0.0
    age: float = 0.0
    timer: float = 0.0                                      # 砲台の発射間隔など
    alive: bool = True

    def draw(self, screen: Screen, scroll: float) -> None:
        spr = self.frames[int(self.age * 6) % len(self.frames)] if self.frames else self.spr
        screen.blit(spr, self.x, self.y)


def fan_move(enemy: Enemy, game: "Game", dt: float) -> None:
    """左へ飛びながら上下に波打つ。"""
    enemy.x -= FAN_SPEED * dt
    enemy.y = enemy.base_y + 12 * math.sin(enemy.age * 4 + enemy.phase)


def garun_move(enemy: Enemy, game: "Game", dt: float) -> None:
    """まっすぐ速く。"""
    enemy.x -= GARUN_SPEED * dt


def ducker_move(enemy: Enemy, game: "Game", dt: float) -> None:
    """地面に沿って歩く。スクロールと一緒に流れ、さらに自分でも左へ。"""
    enemy.x -= (SCROLL_SPEED + DUCKER_SPEED) * dt
    floor, _ = game.terrain.heights(enemy.x + enemy.spr.width / 2 + game.scroll)
    enemy.y = HEIGHT - floor - enemy.spr.height


def cannon_move(enemy: Enemy, game: "Game", dt: float) -> None:
    """地面に据わったまま流れ、間隔ごとに自機を狙って撃つ。"""
    enemy.x -= SCROLL_SPEED * dt
    floor, _ = game.terrain.heights(enemy.x + enemy.spr.width / 2 + game.scroll)
    enemy.y = HEIGHT - floor - enemy.spr.height
    enemy.timer += dt
    if enemy.timer >= CANNON_INTERVAL and game.alive and game.player.x + 24 < enemy.x < WIDTH:   # 真上に来たら撃たない（避けられない）
        enemy.timer = 0.0
        game.enemy_fire(enemy)


FACTORY = {
    Kind.FAN: partial(Enemy, spr=FAN[0], frames=FAN, kind=Kind.FAN, points=100, mover=fan_move),
    Kind.GARUN: partial(Enemy, spr=GARUN, kind=Kind.GARUN, points=150, mover=garun_move),
    Kind.DUCKER: partial(Enemy, spr=DUCKER, kind=Kind.DUCKER, points=200, hp=2, mover=ducker_move),
    Kind.CANNON: partial(Enemy, spr=CANNON, kind=Kind.CANNON, points=300, hp=2, mover=cannon_move),
}


def make_script(rng: random.Random, length: int = STAGE_LENGTH) -> list[Spawn]:
    """出現表。150〜260 ドットおきに何かを出す。先へ行くほど間隔が詰まる。"""
    script = []
    x = 200
    while x < length - 200:
        kind = rng.choice([Kind.FAN, Kind.FAN, Kind.GARUN, Kind.DUCKER, Kind.CANNON])
        if kind == Kind.FAN:
            script.append(Spawn(at=x, kind=kind, count=4, gap=14, y=rng.uniform(20, 50)))
        elif kind == Kind.GARUN:
            script.append(Spawn(at=x, kind=kind, count=3, gap=20, y=rng.uniform(16, 56)))
        elif kind == Kind.DUCKER:
            script.append(Spawn(at=x, kind=kind, count=2, gap=16))
        else:
            script.append(Spawn(at=x, kind=kind))
        x += int(rng.uniform(150, 260) * (1 - 0.4 * x / length))
    return script


def script_summary(script: list[Spawn]) -> list[str]:
    """種類ごとに何組・何体か。groupby は並べてから使う。"""
    lines = []
    for kind, group in groupby(sorted(script, key=lambda sp: sp.kind.name), key=lambda sp: sp.kind):
        rows = list(group)
        lines.append(f"{kind.name:6s} {len(rows):2d} 組 {sum(r.count for r in rows):3d} 体")
    return lines


class Power(Enum):
    """パワーアップのゲージ。この順に並び、カプセルを取るたびに次へ進む（最後の次は最初へ）。"""

    SPEED = auto()
    MISSILE = auto()
    DOUBLE = auto()
    LASER = auto()
    SHIELD = auto()

    @property
    def next(self) -> "Power":
        members = list(Power)
        return members[(members.index(self) + 1) % len(members)]

    @property
    def label(self) -> str:
        return {Power.SPEED: "SPEED", Power.MISSILE: "MISSILE", Power.DOUBLE: "DOUBLE", Power.LASER: "LASER", Power.SHIELD: "?"}[self]


@dataclass
class Capsule(Body):
    """パワーカプセル。倒した敵の所に出て、ゆっくり左へ流れる。"""

    def draw(self, screen: Screen, scroll: float) -> None:
        screen.blit(self.spr, self.x, self.y)


@dataclass
class Missile(Body):
    """ミサイル。斜め下へ落ち、地面に着いたら地面を這う。"""

    grounded: bool = False

    def draw(self, screen: Screen, scroll: float) -> None:
        screen.blit(self.spr, self.x, self.y)


@dataclass
class Laser(Body):
    """レーザー。長い光の線で、敵を貫く（当たっても消えない）。"""

    hits: set[int] = field(default_factory=set)             # もう当てた敵（id）

    def draw(self, screen: Screen, scroll: float) -> None:
        screen.blit(self.spr, self.x, self.y)


class Weapon(ABC):
    """武器。fire() が弾のリストを返す。種類ごとに違うのはそこだけ。"""

    name = "?"
    max_shots = 3

    @abstractmethod
    def fire(self, player: "Player") -> list[Body]: ...


class Normal(Weapon):
    name = "NORMAL"

    def fire(self, player: "Player") -> list[Body]:
        return [Shot(player.x + VIC.width, player.y + VIC.height // 2, BULLET)]


class Double(Weapon):
    """前と斜め上に 1 発ずつ。"""

    name = "DOUBLE"
    max_shots = 4

    def fire(self, player: "Player") -> list[Body]:
        return [Shot(player.x + VIC.width, player.y + VIC.height // 2, BULLET),
                Shot(player.x + VIC.width - 4, player.y, BULLET, vy=-BULLET_SPEED)]


class LaserGun(Weapon):
    """レーザー。画面に 1 本だけ、敵を貫く。"""

    name = "LASER"
    max_shots = 1

    def fire(self, player: "Player") -> list[Body]:
        return [Laser(player.x + VIC.width, player.y + VIC.height // 2, LASER)]


@singledispatch
def hit(shot: Body, game: "Game", enemy: "Enemy") -> bool:
    """弾が敵に当たった。当たった弾を消すなら True。普通の弾は 1 発 1 ダメージで消える。"""
    game.damage(enemy, 1)
    return True


@hit.register(Laser)                                        # 型を引数で渡す（注釈だと "Game" の文字列を評価しようとして失敗する）
def _(shot, game: "Game", enemy: "Enemy") -> bool:
    """レーザーは貫く。当たった敵を覚えて、同じ敵には 1 回だけ。"""
    if id(enemy) not in shot.hits:                          # dataclass は hash できないので id で覚える
        shot.hits.add(id(enemy))
        game.damage(enemy, 2)
    return False


@hit.register(Missile)
def _(shot, game: "Game", enemy: "Enemy") -> bool:
    """ミサイルは 2 ダメージ。"""
    game.damage(enemy, 2)
    return True


@dataclass
class Player(Body):
    """自機。復活直後は点滅する。パワーアップの状態も持つ。"""

    safe: float = 0.0                                       # 無敵の残り秒数
    speed_level: int = 0                                    # スピードアップの段数（0〜3）
    missile: bool = False
    weapon: Weapon = field(default_factory=Normal)
    shield: int = 0                                         # シールドの残り回数
    gauge: Power | None = None                              # ゲージの今の位置。None なら消灯

    @property
    def speed(self) -> float:
        return PLAYER_SPEED + SPEED_STEP * self.speed_level

    def draw(self, screen: Screen, scroll: float) -> None:
        if self.safe > 0 and int(self.safe * 10) % 2 == 0:
            return                                          # 点滅の消える側
        screen.blit(self.spr, self.x, self.y)
        if self.shield > 0:
            screen.blit(SHIELD, self.x + VIC.width, self.y)


@dataclass
class Shot(Body):
    vy: float = 0.0                                         # ダブルの斜め上の弾は上へも進む

    def draw(self, screen: Screen, scroll: float) -> None:
        screen.blit(self.spr, self.x, self.y)


@dataclass
class Explosion(Body):
    frame: int = 0

    def advance(self) -> bool:
        """次のコマへ。終わったら False。"""
        self.frame += 1
        if self.frame >= len(EXPLOSION):
            return False
        self.spr = EXPLOSION[self.frame]
        return True

    def draw(self, screen: Screen, scroll: float) -> None:
        screen.blit(self.spr, self.x, self.y)


class Game:
    """1 回のプレイ。自機・弾・地形・星・爆発。表示と入力は持たない。"""

    def __init__(self, seed: int | None = None):
        self.rng = random.Random(seed)
        self.terrain = Terrain(self.rng)
        self.stars = Starfield(self.rng)
        self.player = Player(16.0, HEIGHT / 2 - VIC.height / 2, VIC)
        self.shots: list[Body] = []                        # 弾・レーザー・ミサイルが混ざる
        self.capsules: list[Capsule] = []
        self.enemies: list[Enemy] = []
        self.enemy_bullets: list[Bullet] = []
        self.script = make_script(self.rng)
        self.next_spawn = 0                                 # 出現表の何行目まで出したか
        self.kills = 0
        self.explosions: list[Explosion] = []
        self.scroll = 0.0                                   # 画面の左端の世界座標
        self.lives = LIVES
        self.dead_timer = 0.0
        self.score = 0
        self.shots_fired = 0
        self.time = 0.0
        self.boom_timer = 0.0
        self.result: str | None = None

    @property
    def alive(self) -> bool:
        return self.dead_timer == 0.0 and self.result is None

    @property
    def layers(self) -> list[Drawable]:
        """描く順（奥から手前）。Drawable なら何でも並べられる。"""
        return [self.stars, self.terrain, *self.enemies, *self.capsules, *self.shots, *self.enemy_bullets, *self.explosions, self.player]

    def move(self, dx: int, dy: int, dt: float) -> None:
        """自機を上下左右に。dx, dy は -1 / 0 / 1。画面の外には出ない。"""
        if not self.alive:
            return
        self.player.x = max(0.0, min(WIDTH - VIC.width, self.player.x + dx * self.player.speed * dt))
        self.player.y = max(0.0, min(HEIGHT - VIC.height, self.player.y + dy * self.player.speed * dt))

    def fire(self) -> bool:
        """今の武器で撃つ。ミサイルがあれば同時に 1 発（画面に 1 発まで）。"""
        weapon = self.player.weapon
        if not self.alive or sum(1 for s in self.shots if not isinstance(s, Missile)) >= weapon.max_shots:
            return False
        self.shots.extend(weapon.fire(self.player))
        if self.player.missile and not any(isinstance(s, Missile) for s in self.shots):
            self.shots.append(Missile(self.player.x + 4, self.player.y + VIC.height, MISSILE))
        self.shots_fired += 1
        return True

    def power_up(self) -> Power | None:
        """ゲージの位置のパワーアップを発動して、ゲージを消す。"""
        power = self.player.gauge
        if power is None or not self.alive:
            return None
        player = self.player
        if power == Power.SPEED:
            player.speed_level = min(3, player.speed_level + 1)
        elif power == Power.MISSILE:
            player.missile = True
        elif power == Power.DOUBLE:
            player.weapon = Double()
        elif power == Power.LASER:
            player.weapon = LaserGun()
        elif power == Power.SHIELD:
            player.shield = SHIELD_HITS
        player.gauge = None
        return power

    def damage(self, enemy: Enemy, amount: int) -> None:
        """敵にダメージ。倒したら得点と爆発、CAPSULE_EVERY 体ごとにカプセル。"""
        enemy.hp -= amount
        if enemy.hp > 0:
            return
        enemy.alive = False
        self.kills += 1
        self.score += enemy.points
        self.explode(enemy)
        if self.kills % CAPSULE_EVERY == 0:
            self.capsules.append(Capsule(enemy.x, min(enemy.y, HEIGHT - 12), CAPSULE))

    def spawn(self, sp: Spawn) -> None:
        """出現表の 1 行ぶんの敵を、画面の右の外に並べて出す。"""
        for i in range(sp.count):
            x = WIDTH + 2 + i * sp.gap
            y = sp.y if sp.y is not None else 0.0
            enemy = FACTORY[sp.kind](x=x, y=y, base_y=y, phase=i * 0.6)
            if sp.kind in (Kind.DUCKER, Kind.CANNON):       # 地上の敵は地面の上に置く
                floor, _ = self.terrain.heights(x + enemy.spr.width / 2 + self.scroll)
                enemy.y = HEIGHT - floor - enemy.spr.height
            self.enemies.append(enemy)

    def enemy_fire(self, enemy: Enemy) -> None:
        """自機に向けて撃つ。向きは atan2 で角度にしてから速さを掛ける。"""
        sx, sy = enemy.x + enemy.spr.width / 2, enemy.y
        angle = math.atan2(self.player.y + VIC.height / 2 - sy, self.player.x + VIC.width / 2 - sx)
        self.enemy_bullets.append(Bullet(sx, sy, ENEMY_BULLET, math.cos(angle) * ENEMY_BULLET_SPEED, math.sin(angle) * ENEMY_BULLET_SPEED))

    def explode(self, body: Body) -> None:
        self.explosions.append(Explosion(body.x + body.spr.width / 2 - EXPLOSION[0].width / 2,
                                         body.y + body.spr.height / 2 - EXPLOSION[0].height / 2, EXPLOSION[0]))

    def hit_player(self) -> None:
        """撃墜。残機を減らし、少し置いて画面の左の中央に戻す。パワーアップは全部失う。"""
        self.explode(self.player)
        self.lives -= 1
        self.player.speed_level, self.player.missile, self.player.weapon, self.player.shield, self.player.gauge = 0, False, Normal(), 0, None
        if self.lives <= 0:
            self.result = "over"
        else:
            self.dead_timer = RESPAWN_DELAY

    def update(self, dt: float) -> None:
        """時間を dt 秒進める。"""
        if self.result is not None:
            return
        self.time += dt
        self.scroll += SCROLL_SPEED * dt
        self.score += int((self.scroll + SCROLL_SPEED * dt) / 10) - int(self.scroll / 10)   # 進んだ距離も得点
        if self.dead_timer > 0:
            self.dead_timer = max(0.0, self.dead_timer - dt)
            if self.dead_timer == 0.0:                      # 復活。地形に埋まらない高さを探す
                self.player.x = 16.0
                floor, ceiling = self.terrain.heights(self.player.x + VIC.width / 2 + self.scroll)
                self.player.y = (ceiling + (HEIGHT - floor)) / 2 - VIC.height / 2
                self.player.safe = SAFE_TIME
        self.player.safe = max(0.0, self.player.safe - dt)
        while self.next_spawn < len(self.script) and self.script[self.next_spawn].at <= self.scroll + WIDTH:
            self.spawn(self.script[self.next_spawn])        # 画面の右端が at に達したら出す
            self.next_spawn += 1
        for enemy in self.enemies:
            enemy.age += dt
            enemy.mover(enemy, self, dt)
        self.enemies = [e for e in self.enemies if e.alive and e.x + e.spr.width > -8]
        for bullet in self.enemy_bullets:
            bullet.x += bullet.vx * dt
            bullet.y += bullet.vy * dt
        self.enemy_bullets = [b for b in self.enemy_bullets if -4 < b.x < WIDTH and -4 < b.y < HEIGHT and not self.terrain.hits(b, self.scroll)]
        for shot in self.shots:
            if isinstance(shot, Missile):                   # 斜め下へ。地面に着いたら這う
                shot.x += MISSILE_SPEED * dt
                if not shot.grounded:
                    shot.y += MISSILE_SPEED * dt
                    floor, _ = self.terrain.heights(shot.x + self.scroll)
                    if shot.y + shot.spr.height >= HEIGHT - floor:
                        shot.grounded = True
                else:
                    floor, _ = self.terrain.heights(shot.x + self.scroll)
                    shot.y = HEIGHT - floor - shot.spr.height
            else:
                shot.x += BULLET_SPEED * dt
                shot.y += shot.vy * dt if isinstance(shot, Shot) else 0
        self.shots = [s for s in self.shots if s.x < WIDTH and s.y + s.spr.height > 0 and (isinstance(s, Missile) and s.grounded or not self.terrain.hits(s, self.scroll))]
        for shot in list(self.shots):
            for target in [e for e in self.enemies if e.alive and e.overlaps(shot)]:
                if hit(shot, self, target):                 # 弾の種類で当たり方が違う（singledispatch）
                    self.shots.remove(shot)
                    break
        for capsule in self.capsules:
            capsule.x -= CAPSULE_SPEED * dt
        for capsule in list(self.capsules):
            if self.alive and self.player.overlaps(capsule):
                self.capsules.remove(capsule)
                self.player.gauge = Power.SPEED if self.player.gauge is None else self.player.gauge.next
        self.capsules = [c for c in self.capsules if c.x + c.spr.width > 0]
        if self.alive and self.player.safe == 0:
            for threat in [*self.enemies, *self.enemy_bullets]:
                if not self.player.overlaps(threat):
                    continue
                if self.player.shield > 0 and threat.x >= self.player.x + VIC.width / 2:   # 前からの当たりはシールドが受ける
                    self.player.shield -= 1
                    if isinstance(threat, Bullet):
                        self.enemy_bullets.remove(threat)
                    else:
                        self.damage(threat, 99)
                    continue
                self.hit_player()
                break
            if self.alive and self.terrain.hits(self.player, self.scroll):
                self.hit_player()
        self.boom_timer += dt
        if self.boom_timer >= 1 / 12:
            self.boom_timer -= 1 / 12
            self.explosions = [boom for boom in self.explosions if boom.advance()]
        if self.scroll >= STAGE_LENGTH:
            self.result = "clear"

    def draw(self, screen: Screen) -> None:
        """今の状態を Screen に描く。層を順に。"""
        screen.clear()
        for layer in self.layers:
            if layer is self.player and not self.alive:
                continue
            layer.draw(screen, self.scroll)

    def status(self) -> str:
        gauge = " ".join(f"[{p.label}]" if p == self.player.gauge else p.label for p in Power)
        return f"SCORE {self.score:5d}  残機 {'▲' * max(0, self.lives - 1):<2} 進み {min(100, self.scroll / STAGE_LENGTH * 100):3.0f}%  {gauge}  {self.player.weapon.name}{' +M' if self.player.missile else ''} S{self.player.speed_level}{' 盾' + str(self.player.shield) if self.player.shield else ''}"


def autopilot(game: Game, dt: float) -> tuple[int, int]:
    """自動操縦。少し先の地形の真ん中へ寄り、正面に来る敵と弾はよける。デモと難しさの確認に使う。"""
    ahead = game.player.x + VIC.width + 12 + game.scroll
    floor, ceiling = game.terrain.heights(ahead)
    target = (ceiling + (HEIGHT - floor)) / 2 - VIC.height / 2
    cx, cy = game.player.x + VIC.width / 2, game.player.y + VIC.height / 2
    arrivals = []                                           # 1.5 秒以内に自機の x へ来るものが、来たときの高さ
    for t in [*game.enemies, *game.enemy_bullets]:
        if isinstance(t, Bullet):
            vx, vy = t.vx, t.vy
        else:
            vx, vy = -{Kind.FAN: FAN_SPEED, Kind.GARUN: GARUN_SPEED, Kind.DUCKER: SCROLL_SPEED + DUCKER_SPEED, Kind.CANNON: SCROLL_SPEED}[t.kind], 0.0
        if t.x <= cx or vx >= 0:
            continue
        seconds = (t.x - cx) / -vx
        arrive = t.y + t.spr.height / 2 + vy * seconds
        if seconds < 1.5 and abs(arrive - cy) < 26:
            if isinstance(t, Enemy) and t.kind != Kind.CANNON and 0.3 < seconds and abs(arrive - cy) < 5:
                return 0, 0                                 # 正面から来る敵は動かずに撃ち落とす（弾は敵より 3 倍速い）
            arrivals.append(arrive)
    spans = [game.terrain.heights(x + game.scroll) for x in range(int(game.player.x), int(game.player.x) + 32, 4)]
    low = max(c for _, c in spans) + 3                      # 少し先までの通り道（自機の y の範囲）。天井は最も低い所、地面は最も高い所
    high = min(HEIGHT - f for f, _ in spans) - VIC.height - 3
    if arrivals:                                            # 上・真ん中・下のうち、来るものから最も遠い所へ
        candidates = [low, (low + high) / 2, high]
        target = max(candidates, key=lambda y: min(abs(a - (y + VIC.height / 2)) for a in arrivals))
    elif game.capsules:                                     # 危なくなければカプセルを取りに行く
        capsule = min(game.capsules, key=lambda c: abs(c.x - cx))
        target = capsule.y + capsule.spr.height / 2 - VIC.height / 2
    target = max(low, min(high, target))
    dy = 0 if abs(target - game.player.y) < 2 else (1 if target > game.player.y else -1)
    wanted = [Power.SPEED, Power.DOUBLE, Power.MISSILE, Power.LASER, Power.SHIELD]   # 自動操縦が欲しい順
    if game.player.gauge is not None and game.player.gauge == next((p for p in wanted if not has_power(game.player, p)), None):
        game.power_up()                                     # 欲しい所でゲージが止まったら発動
    return 0, dy


def has_power(player: Player, power: Power) -> bool:
    return {Power.SPEED: player.speed_level >= 1, Power.MISSILE: player.missile, Power.DOUBLE: isinstance(player.weapon, Double),
            Power.LASER: isinstance(player.weapon, LaserGun), Power.SHIELD: player.shield > 0}[power]
# --- ここから下はブラウザ版だけ。CLI 版の play() / read_keys() / Screen.render() にあたる ---

canvas = document.querySelector("#screen")
ctx = canvas.getContext("2d")
ctx.imageSmoothingEnabled = False
score_label = document.querySelector("#turn")
lives_label = document.querySelector("#lives")
progress_label = document.querySelector("#progress")
kills_label = document.querySelector("#kills")
hud = document.querySelector("#hud")
message = document.querySelector("#message")
start_button = document.querySelector("#start-btn")
auto_button = document.querySelector("#auto-btn")
pad_buttons = document.querySelectorAll(".pad button")

images: dict[str, object] = {}                              # スプライト名 → Image。PNG は Python が作る


def image_of(spr: Sprite):
    key = spr.name + "".join(spr.rows)
    if key not in images:
        img = Image.new()
        img.src = data_uri(spr)
        images[key] = img
    return images[key]


class CanvasScreen:
    """CLI 版の Screen と同じ clear() / plot() / blit() を canvas に対して行う。Game.draw() はこれを渡すだけ。"""

    def clear(self) -> None:
        ctx.fillStyle = "#000"
        ctx.fillRect(0, 0, WIDTH, HEIGHT)

    def plot(self, x: int, y: int, color: tuple[int, int, int]) -> None:
        r, g, b = color
        ctx.fillStyle = f"rgb({r},{g},{b})"
        ctx.fillRect(x, y, 1, 1)

    def blit(self, spr: Sprite, x: float, y: float) -> None:
        ctx.drawImage(image_of(spr), round(x), round(y))


canvas_screen = CanvasScreen()
game = Game()
pressed = {"left": False, "right": False, "up": False, "down": False}
auto = False                                                # 自動操縦（デモ）
running = False


def draw():
    """CLI 版の Game.draw() + Screen.render() にあたる。描く先を CanvasScreen に差し替えて Game.draw() を呼ぶ。"""
    game.draw(canvas_screen)
    score_label.textContent = f"SCORE {game.score}"
    lives_label.textContent = "▲" * max(0, game.lives - 1) or "0"
    progress_label.textContent = f"{min(100, game.scroll / STAGE_LENGTH * 100):.0f}%"
    kills_label.textContent = str(game.kills)
    hud.textContent = game.status()
    if game.result is not None:
        message.textContent = f"{RESULT_TEXT[game.result]}　{game.time:.1f} 秒"


async def loop():
    """1/FPS 秒ごとに更新して描く。CLI 版の play() の while と同じ。"""
    global running
    running = True
    last = window.performance.now() / 1000
    while game.result is None:
        now = window.performance.now() / 1000
        dt = min(now - last, 0.1)
        last = now
        if auto:
            dx, dy = autopilot(game, dt)
            if game.rng.random() < 0.4:
                game.fire()
        else:
            dx = (1 if pressed["right"] else 0) - (1 if pressed["left"] else 0)
            dy = (1 if pressed["down"] else 0) - (1 if pressed["up"] else 0)
        game.move(dx, dy, dt)
        game.update(dt)
        draw()
        await asyncio.sleep(1 / FPS)
    draw()
    running = False


def start(demo: bool = False):
    global game, auto
    game = Game()
    auto = demo
    message.textContent = "自動操縦（地形の真ん中へ寄る）" if demo else ""
    for button in pad_buttons:
        button.disabled = demo
    if not running:
        asyncio.ensure_future(loop())


KEYS = {"ArrowLeft": "left", "a": "left", "ArrowRight": "right", "d": "right", "ArrowUp": "up", "w": "up", "ArrowDown": "down", "s": "down", " ": "fire", "x": "power", "Enter": "power"}


@when("keydown", "body")
def on_keydown(event):
    global auto
    key = KEYS.get(event.key)
    if key is None:
        return
    event.preventDefault()
    auto = False                                            # 何か押したら自分で操縦
    if key == "fire":
        if not event.repeat:
            game.fire()
    elif key == "power":
        if not event.repeat:
            game.power_up()
    else:
        pressed[key] = True


@when("keyup", "body")
def on_keyup(event):
    key = KEYS.get(event.key)
    if key in pressed:
        pressed[key] = False


@when("pointerdown", ".pad button")
def on_pad_down(event):
    key = event.target.getAttribute("data-key")
    if key == "fire":
        game.fire()
    elif key == "power":
        game.power_up()
    else:
        pressed[key] = True


@when("pointerup", ".pad button")
def on_pad_up(event):
    key = event.target.getAttribute("data-key")
    if key in pressed:
        pressed[key] = False


@when("pointerleave", ".pad button")
def on_pad_leave(event):
    key = event.target.getAttribute("data-key")
    if key in pressed:
        pressed[key] = False


@when("click", "#start-btn")
def on_start(event):
    start()


@when("click", "#auto-btn")
def on_auto(event):
    start(demo=True)


# Pyodide の読み込みが終わってから実行される＝ここが準備完了の合図
document.querySelector("#loading").hidden = True
start_button.disabled = False
auto_button.disabled = False
start()
