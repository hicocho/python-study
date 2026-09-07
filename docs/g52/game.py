"""イー・アル・カンフー風（武器の敵）ブラウザ版

CLI 版（g52-kungfu-weapons/main.py）とドット絵・動き・当たり判定はまったく同じ。
定数とパレット、Sprite / sprite()、格闘家の絵、Screen、png_bytes() / data_uri()、Move / Animation / only_when_free / Fighter / Pose / 技の表 / flipped / recolored / DEFAULT_BRAIN / LEVELS / EnemyDef（TypedDict）/ Slot（Generic）/ Projectile / Option / Brain / 台本（yield from）/ ScriptBrain / ENEMIES / overlaps、
autopilot()、そして class Game を、ステップの目印コメント（# ←）を外しただけで 1 文字も変えずに持ってきている。

持ってこなかったのは端末に描く Screen.render() を使う play() / read_keys() / check_terminal() / main() だけ。
出口は canvas。Screen と同じ clear() / plot() / blit() を持つ CanvasScreen を渡して、Game.draw() をそのまま呼ぶ。
"""

import asyncio
import base64
import random
import struct
import zlib
from collections import ChainMap
from collections.abc import Callable, Generator
from dataclasses import dataclass, field, replace
from enum import Enum, auto
from functools import cache, wraps
from itertools import accumulate
from typing import Generic, Iterator, Literal, TypedDict, TypeVar

from js import Image, window
from pyscript import document, when

WIDTH = 128                                 # 横長の画面（端末では 1 ドット = 1 桁）


HEIGHT = 80                                 # 端末では 2 ドット = 1 行 → 40 行


FPS = 30


FLOOR_Y = 68                                # 地面の高さ（足がここに着く）


LEFT_EDGE = 2                               # 舞台の端（これより外へは歩けない）


RIGHT_EDGE = WIDTH - 2


WALK_SPEED = 42.0                           # 歩く速さ（ドット/秒）


JUMP_SPEED = 130.0                          # 跳んだ瞬間の上向きの速さ


GRAVITY = 380.0                             # 重力（ドット/秒²）


MAX_HP = 100


STUN_TIME = 0.35                            # 技を食らったあと動けない時間


PUSHBACK = 8.0                              # 食らったときに後ろへ下がる距離


REACH = 18.0                                # 技が届く間合い（体の中心どうしの距離）


CHAIN_REACH = 32.0                          # チェンの鎖が届く間合い


FIREBALL_SPEED = 70.0


SHURIKEN_SPEED = 90.0


SHURIKEN_GRAVITY = 160.0                    # 手裏剣は放物線を描いて落ちる


MAX_PROJECTILES = 2                         # 同時に飛んでいる飛び道具の数（1 人あたり）


PILOT_INTERVAL = 0.15                       # 自動操縦（腕前の物差し）が行動を決め直す間隔。AI の既定と同じ


DEFAULT_BRAIN = {
    "interval": 0.15,                       # 次の行動を決めるまでの秒
    "aggression": 0.8,                      # 間合いに入ったとき技を出したがる度合い（0〜1）
    "reaction": 0.12,                       # 人の技に気づくまでの秒（遅いほど食らう）
    "dodge": 0.5,                           # 気づいたときによける確率（難度の主な物差し）
    "jump_rate": 0.08,                      # 跳びたがり
    "crouch_rate": 0.15,                    # しゃがみたがり
    "retreat_gap": 10.0,                    # これより近ければ下がる
    "kick_rate": 0.4,                       # 技を出すときキックを選ぶ確率
}


LEVELS = {
    "easy": {"dodge": 0.2, "aggression": 0.4, "reaction": 0.3, "interval": 0.25},
    "normal": {},
    "hard": {"dodge": 0.95, "reaction": 0.08, "interval": 0.12},
}


BAR_WIDTH = 44                              # 体力バーの長さ（ドット）


DEMO_TIME = 60.0                            # --auto の上限（決着がつけばそこまで）


PALETTE = {
    "W": (255, 255, 255), "K": (30, 30, 40), "S": (240, 200, 160), "B": (50, 90, 220), "R": (220, 50, 50),
    "Y": (250, 220, 60), "N": (60, 40, 30), "G": (90, 190, 90), "D": (120, 20, 20), "L": (150, 190, 255), "O": (250, 140, 30),
}


SKY = (24, 24, 52)                          # 背景


SKY_LOW = (52, 36, 70)                      # 地平の近く


FLOOR = (150, 110, 70)                      # 床（板張り）


FLOOR_LINE = (90, 60, 40)


PILLAR = (70, 50, 60)                       # 奥の柱


BAR_BACK = (60, 60, 70)


BAR_PLAYER = (80, 220, 100)


BAR_ENEMY = (230, 80, 80)


RESULT_TEXT = {
    "quit": "やめました。",
    "demo": "デモを終えました。",
    "win": "勝ち！",
    "lose": "負け…",
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


OOLONG_STAND = sprite("oolong-stand", """
.......KKKK.........
......KSSSSK........
......SSKSSS........
.......SSSS.........
......BBBBBB........
.....BBBBBBBB.......
....SBBBBBBBBSS.....
....S.BBBBBB.SS.....
......BBBBBB........
......YYYYYY........
......BBBBBB........
......BB..BB........
......BB..BB........
......BB..BB........
.....KKK..KKK.......
""")


OOLONG_CROUCH = sprite("oolong-crouch", """
.......KKKK.........
......KSSSSK........
......SSKSSS........
.....BBSSSSBB.......
....BBBBBBBBBBS.....
....SBBBBBBBBBS.....
......YYYYYYYY......
.....BBBBBBBBBB.....
....KKK......KKK....
""")


OOLONG_JUMP = sprite("oolong-jump", """
.......KKKK.........
......KSSSSK........
......SSKSSS........
.......SSSS.........
....S.BBBBBB.S......
....SBBBBBBBBS......
......BBBBBB........
......YYYYYY........
......BBBBBB........
.....BBB..BBB.......
....KKK....KKK......
""")


OOLONG_PUNCH = sprite("oolong-punch", """
.......KKKK.........
......KSSSSK........
......SSKSSS........
.......SSSS.........
......BBBBBBBBBBSS..
.....BBBBBBBBBBBSS..
....SBBBBBBBB.......
....S.BBBBBB........
......BBBBBB........
......YYYYYY........
......BBBBBB........
......BB..BB........
......BB..BB........
......BB..BB........
.....KKK..KKK.......
""")


OOLONG_KICK = sprite("oolong-kick", """
.......KKKK.........
......KSSSSK........
......SSKSSS........
.......SSSS.........
......BBBBBB........
.....BBBBBBBB.......
....SBBBBBBBBS......
....S.BBBBBB.S......
......BBBBBB........
......YYYYYY........
......BBBBBBBBBBBB..
......BB......KKKK..
......BB............
......BB............
.....KKK............
""")


OOLONG_CROUCH_PUNCH = sprite("oolong-crouch-punch", """
.......KKKK.........
......KSSSSK........
......SSKSSS........
.....BBSSSSBB.......
....BBBBBBBBBBBBSS..
....SBBBBBBBBBBBSS..
......YYYYYYYY......
.....BBBBBBBBBB.....
....KKK......KKK....
""")


OOLONG_JUMP_KICK = sprite("oolong-jump-kick", """
.......KKKK.........
......KSSSSK........
......SSKSSS........
.......SSSS.........
....S.BBBBBB.S......
....SBBBBBBBBS......
......BBBBBB........
......YYYYYY........
......BBBBBBBBBBB...
.....BBB......KKKK..
....KKK.............
""")


TAO_THROW = sprite("tao-throw", """
.......KKKK.........
......KSSSSK........
......SSKSSS........
.......SSSS.S.......
......BBBBBBS.......
.....BBBBBBBB.......
....SBBBBBBB........
....S.BBBBBB........
......BBBBBB........
......YYYYYY........
......BBBBBB........
......BB..BB........
......BB..BB........
......BB..BB........
.....KKK..KKK.......
""")


CHEN_CHAIN = sprite("chen-chain", """
.......KKKK.........................
......KSSSSK........................
......SSKSSS........................
.......SSSS.........................
......BBBBBBBBBBS.N.N.N.N.N.N.N.NNN.
.....BBBBBBBBBBBSN.N.N.N.N.N.N.N.NNN
....SBBBBBBBB.......................
....S.BBBBBB........................
......BBBBBB........................
......YYYYYY........................
......BBBBBB........................
......BB..BB........................
......BB..BB........................
......BB..BB........................
.....KKK..KKK.......................
""")


LANG_THROW = sprite("lang-throw", """
.......KKKK.........
......KSSSSK........
......SSKSSS........
.......SSSS.........
......BBBBBBBBSS....
.....BBBBBBBBBSS.W..
....SBBBBBBB........
....S.BBBBBB........
......BBBBBB........
......YYYYYY........
......BBBBBB........
......BB..BB........
......BB..BB........
......BB..BB........
.....KKK..KKK.......
""")


FIREBALL = sprite("fireball", """
.OO.
OYYO
OYYO
.OO.
""")


SHURIKEN = sprite("shuriken", """
.W.
WKW
.W.
""")


ENEMY_COLORS = {"B": "R", "L": "D"}       # 相手は道着を赤に


class EnemyDef(TypedDict):
    """敵 1 人ぶんの表。TypedDict なので辞書のまま書けて、鍵の名前と型が決まっている。"""

    colors: dict[str, str]                                  # 道着の色の置き換え
    brain: dict                                             # DEFAULT_BRAIN への上書き
    weapon: "Move | None"                                   # 武器の技（無ければ None）
    script: "Callable[[Game], Script] | None"               # 台本（無ければ点数で選ぶ AI）
    jump: float                                             # 跳ぶ速さ（ムーは高く跳ぶ）


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


@dataclass(frozen=True)
class Move:
    """技。コマの列（絵と長さ）と、当たり判定が出ている時間、攻撃ボックス（前方 dx・足元からの高さ dy）。"""

    name: str
    frames: tuple[tuple[Sprite, float], ...]                 # (絵, 秒) の列
    active: tuple[float, float]                             # 当たり判定が出ている時間（技の始めから何秒〜何秒）
    box: tuple[float, float, float, float]                  # 攻撃ボックス (前方 x0, 高さ y0, 前方 x1, 高さ y1)。前方は向いている方
    damage: int
    pose: "Pose | None" = None                              # この姿勢のときだけ出せる（None なら立ち・跳びどちらでも）
    projectile: str | None = None                           # 当たり判定の代わりに飛び道具を出す技（"fireball" / "shuriken"）

    @property
    def ends(self) -> tuple[float, ...]:
        """各コマが終わる時刻（累積）。accumulate で (0.08, 0.20, 0.30) のように。"""
        return tuple(accumulate(seconds for _, seconds in self.frames))

    @property
    def length(self) -> float:
        return self.ends[-1]


class Animation:
    """技のアニメ。next() を呼ぶたびに dt 秒進み、今のコマの絵を返す。終わったら StopIteration。"""

    def __init__(self, move: Move, dt: float):
        self.move = move
        self.dt = dt
        self.t = 0.0
        self.hit_done = False                               # この技でもう当てたか（1 回だけ当たる）

    def __iter__(self):
        return self

    def __next__(self) -> Sprite:
        if self.t >= self.move.length:
            raise StopIteration
        index = next(i for i, end in enumerate(self.move.ends) if self.t < end)
        self.t += self.dt
        return self.move.frames[index][0]

    @property
    def active(self) -> bool:
        start, end = self.move.active
        return start <= self.t < end and not self.hit_done


def only_when_free(method):
    """技のメソッドに付ける。硬直中か、別の技の途中なら何もしない（False を返す）。"""

    @wraps(method)                                          # 名前と docstring を元のメソッドのままに
    def wrapper(self: "Fighter", *args, **kwargs):
        if self.stun > 0 or self.anim is not None:
            return False
        return method(self, *args, **kwargs)

    return wrapper


@dataclass
class Fighter:
    """格闘家。位置は足元の中央 (x, y)。y は地面からの高さ（跳ぶと増える）。右向きの絵を基準に、左向きは反転。"""

    name: str
    x: float
    facing: Literal["left", "right"] = "right"
    y: float = 0.0
    vy: float = 0.0
    vx: float = 0.0                                         # 跳んでいる間の横の速さ（空中では変えられない）
    pose: "Pose" = None                                     # 型は下で定義（Enum）。既定は __post_init__ で
    colors: dict[str, str] = field(default_factory=dict)    # 絵の色の置き換え（相手は赤）
    anim: Animation | None = None                           # 出している技（無ければ None）
    stun: float = 0.0                                       # 食らって動けない残り時間
    weapon: Move | None = None                              # 武器の技（敵だけ）
    jump_speed: float = JUMP_SPEED
    hits: int = 0                                           # 当てた回数（集計用）
    _hp: int = field(default=MAX_HP, repr=False)
    _frame: Sprite | None = field(default=None, repr=False)

    def __post_init__(self):
        if self.pose is None:
            self.pose = Pose.STAND

    @property
    def hp(self) -> int:
        return self._hp

    @hp.setter
    def hp(self, value: int) -> None:
        """体力は 0〜MAX_HP に丸める。減らしすぎ・回復しすぎを呼ぶ側が気にしなくていい。"""
        self._hp = max(0, min(MAX_HP, int(value)))

    @property
    def grounded(self) -> bool:
        return self.y <= 0.0 and self.pose != Pose.JUMP

    @property
    def sprite(self) -> Sprite:
        base = self.frame if self.frame is not None else POSE_SPRITES[self.pose]
        if self.colors:
            base = recolored(base, tuple(sorted(self.colors.items())))
        return base if self.facing == "right" else flipped(base)

    @property
    def frame(self) -> Sprite | None:
        """技の途中ならそのコマの絵。"""
        return self._frame

    @property
    def top(self) -> float:
        """絵の上端の画面 y。"""
        return FLOOR_Y - self.y - self.sprite.height

    @property
    def left(self) -> float:
        """絵の左端。体は右向きの絵の 6〜13 列にあるので、幅が違う絵（鎖）でも体の位置がずれない。"""
        return self.x - 10 if self.facing == "right" else self.x - (self.sprite.width - 10)

    @property
    def box(self) -> tuple[float, float, float, float]:
        """体の矩形（食らい判定）(x0, y0, x1, y1)。絵は幅 20 で体は真ん中の 10 ドット。技で伸びた腕や脚は含めない。"""
        return self.x - 5, self.top, self.x + 5, FLOOR_Y - self.y

    def attack_box(self) -> tuple[float, float, float, float] | None:
        """今出している技の攻撃ボックス（画面座標）。当たり判定が出ていなければ None。"""
        if self.anim is None or not self.anim.active:
            return None
        fx0, fy0, fx1, fy1 = self.anim.move.box
        sign = 1 if self.facing == "right" else -1
        xs = sorted((self.x + sign * fx0, self.x + sign * fx1))
        return xs[0], FLOOR_Y - self.y - fy1, xs[1], FLOOR_Y - self.y - fy0

    @only_when_free
    def punch(self) -> bool:
        """パンチ。立っていれば上段、しゃがんでいれば下段。空中では出せない。"""
        if self.pose == Pose.JUMP:
            return False
        self.anim = Animation(CROUCH_PUNCH if self.pose == Pose.CROUCH else PUNCH, 1 / FPS)
        return True

    @only_when_free
    def kick(self) -> bool:
        """キック。立っていれば下段（足払い）、跳んでいれば跳び蹴り。しゃがんでは出せない。"""
        if self.pose == Pose.CROUCH:
            return False
        self.anim = Animation(JUMP_KICK if self.pose == Pose.JUMP else KICK, 1 / FPS)
        return True

    @only_when_free
    def use_weapon(self) -> bool:
        """武器の技。立っているときだけ。"""
        if self.weapon is None or self.pose != Pose.STAND:
            return False
        self.anim = Animation(self.weapon, 1 / FPS)
        return True

    def hurt(self, damage: int, from_right: bool) -> None:
        """食らう。体力を減らし、硬直し、少し下がる。出しかけの技は消える。"""
        self.hp -= damage
        self.stun = STUN_TIME
        self.anim, self._frame = None, None
        self.x += -PUSHBACK if from_right else PUSHBACK

    def jump(self) -> None:
        if self.grounded:
            self.pose = Pose.JUMP
            self.vy = self.jump_speed

    def face(self, other: "Fighter") -> None:
        """地面にいるときだけ相手の方を向く（空中では向きを変えない）。"""
        if self.grounded:
            self.facing = "right" if other.x >= self.x else "left"

    def update(self, dt: float) -> None:
        """重力と着地、技のコマ送り、硬直の回復。"""
        self.stun = max(0.0, self.stun - dt)
        if self.anim is not None:
            try:
                self._frame = next(self.anim)               # 次のコマ。終わったら StopIteration
            except StopIteration:
                self.anim, self._frame = None, None
        if self.pose == Pose.JUMP:
            self.vy -= GRAVITY * dt
            self.y += self.vy * dt
            self.x += self.vx * dt
            if self.y <= 0.0:                               # 着地
                self.y, self.vy, self.vx = 0.0, 0.0, 0.0
                self.pose = Pose.STAND
        self.x = max(LEFT_EDGE + self.sprite.width / 2, min(RIGHT_EDGE - self.sprite.width / 2, self.x))

    def draw(self, screen: Screen) -> None:
        screen.blit(self.sprite, self.left, self.top)


class Pose(Enum):
    """姿勢。入力から次の姿勢を決めるのは Game.control() の match 文。"""

    STAND = auto()
    CROUCH = auto()
    JUMP = auto()


POSE_SPRITES = {Pose.STAND: OOLONG_STAND, Pose.CROUCH: OOLONG_CROUCH, Pose.JUMP: OOLONG_JUMP}


PUNCH = Move("punch", ((OOLONG_STAND, 0.06), (OOLONG_PUNCH, 0.14), (OOLONG_STAND, 0.12)), active=(0.06, 0.16), box=(6, 9, 13, 12), damage=8)


KICK = Move("kick", ((OOLONG_STAND, 0.08), (OOLONG_KICK, 0.16), (OOLONG_STAND, 0.16)), active=(0.08, 0.20), box=(6, 2, 14, 6), damage=12)


CROUCH_PUNCH = Move("crouch-punch", ((OOLONG_CROUCH, 0.06), (OOLONG_CROUCH_PUNCH, 0.14), (OOLONG_CROUCH, 0.12)), active=(0.06, 0.16), box=(6, 3, 13, 6), damage=8, pose=Pose.CROUCH)


JUMP_KICK = Move("jump-kick", ((OOLONG_JUMP_KICK, 0.5),), active=(0.02, 0.5), box=(5, 1, 13, 4), damage=14, pose=Pose.JUMP)


FIRE_THROW = Move("fireball", ((TAO_THROW, 0.2), (OOLONG_STAND, 0.3)), active=(0.1, 0.2), box=(0, 0, 0, 0), damage=10, projectile="fireball")


CHAIN_SWING = Move("chain", ((OOLONG_STAND, 0.1), (CHEN_CHAIN, 0.2), (OOLONG_STAND, 0.25)), active=(0.1, 0.3), box=(8, 9, CHAIN_REACH + 4, 11), damage=10)


SHURIKEN_THROW = Move("shuriken", ((LANG_THROW, 0.15), (OOLONG_STAND, 0.25)), active=(0.05, 0.15), box=(0, 0, 0, 0), damage=6, projectile="shuriken")


T = TypeVar("T")


class Slot(Generic[T]):
    """決まった数までしか入らない入れ物。飛び道具は 1 人 MAX_PROJECTILES 発まで。T は中身の型（Slot[Projectile] のように書く）。"""

    def __init__(self, limit: int):
        self.limit = limit
        self.items: list[T] = []

    def add(self, item: T) -> bool:
        if len(self.items) >= self.limit:
            return False
        self.items.append(item)
        return True

    def keep(self, alive: Callable[[T], bool]) -> None:
        """条件に合うものだけ残す。"""
        self.items = [item for item in self.items if alive(item)]

    def __iter__(self) -> Iterator[T]:
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)


@dataclass
class Projectile:
    """飛び道具。左上 (x, y)、速さ (vx, vy)。手裏剣は重力で落ちる。"""

    x: float
    y: float
    vx: float
    vy: float
    spr: Sprite
    damage: int
    gravity: float = 0.0
    owner: str = ""

    @property
    def box(self) -> tuple[float, float, float, float]:
        return self.x, self.y, self.x + self.spr.width, self.y + self.spr.height

    def update(self, dt: float) -> None:
        self.vy += self.gravity * dt
        self.x += self.vx * dt
        self.y += self.vy * dt

    @property
    def gone(self) -> bool:
        return self.x + self.spr.width < 0 or self.x > WIDTH or self.y > FLOOR_Y

    def draw(self, screen: Screen) -> None:
        screen.blit(self.spr, self.x, self.y)


@cache
def flipped(spr: Sprite) -> Sprite:
    """左向きの絵。rows を 1 行ずつ反転した新しい Sprite を replace で作る（name も変える）。"""
    return replace(spr, name=spr.name + "-left", rows=tuple(row[::-1] for row in spr.rows))


@cache
def recolored(spr: Sprite, mapping: tuple[tuple[str, str], ...]) -> Sprite:
    return spr.recolor(dict(mapping))


ALL_SPRITES = [OOLONG_STAND, OOLONG_CROUCH, OOLONG_JUMP, OOLONG_PUNCH, OOLONG_KICK, OOLONG_CROUCH_PUNCH, OOLONG_JUMP_KICK, TAO_THROW, CHEN_CHAIN, LANG_THROW, FIREBALL, SHURIKEN, recolored(OOLONG_STAND, tuple(sorted(ENEMY_COLORS.items())))]


@dataclass(order=True)
class Option:
    """AI の行動の候補。点数で比べられる（order=True）。keys は比較に含めない。"""

    score: float
    name: str = field(compare=False)
    keys: frozenset[str] = field(compare=False, default=frozenset())


class Brain:
    """敵の頭。interval ごとに候補（寄る・下がる・技・跳ぶ・しゃがむ・待つ）に点を付けて一番高いものを選ぶ。人の技には reaction 秒遅れて気づき、dodge の確率でよける。"""

    def __init__(self, params: ChainMap | dict, rng: random.Random):
        self.params = params
        self.rng = rng
        self.timer = 0.0
        self.keys: frozenset[str] = frozenset()             # 今続けている行動
        self.noticed: Move | None = None                    # 気づいた相手の技
        self.notice_at = 0.0                                # 気づく時刻（game.time）

    def decide(self, game: "Game", dt: float) -> set[str]:
        me, you = game.enemy, game.player
        p = self.params
        self.timer -= dt
        # 相手の技に「反応の遅れ」をもって気づく
        if you.anim is not None and self.noticed is not you.anim.move:
            self.noticed, self.notice_at = you.anim.move, game.time + p["reaction"] * self.rng.uniform(0.5, 1.5)   # 遅れは毎回ばらつく（同じ間合いに同じ反応をしない）
        if self.noticed is not None and game.time >= self.notice_at and you.anim is not None and you.anim.move is self.noticed:
            self.noticed = None
            if self.rng.random() < p["dodge"] and me.grounded:
                high = you.anim.move.box[1] >= 8                # 上段（高さ 8 以上）はしゃがんでよけ、下段は跳んでよける
                self.timer = 0.3
                self.keys = frozenset({"down"} if high else {"up"})
                return set(self.keys)
        gap = abs(you.x - me.x)
        if self.timer > 0 and not (self.keys & {"left", "right"} and gap <= REACH - 2 and me.grounded):
            return set(self.keys)                           # 決めた行動を続ける（寄っている途中で間合いに入ったら、すぐ決め直す）
        toward = "left" if you.x < me.x else "right"
        away = "right" if toward == "left" else "left"
        return self.choose(game, gap, toward, away)

    def choose(self, game: "Game", gap: float, toward: str, away: str) -> set[str]:
        """候補に点を付けて選ぶ（台本の敵はここを差し替える）。"""
        p = self.params
        me, you = game.enemy, game.player
        self.timer = p["interval"]
        noise = lambda: self.rng.random() * 0.3
        options = [
            Option(0.2 + noise(), "wait"),
            Option((0.8 if gap > REACH else 0.1) + noise(), "approach", frozenset({toward})),
            Option((0.7 if gap < p["retreat_gap"] else 0.05) + noise(), "retreat", frozenset({away})),
            Option((p["aggression"] if gap <= REACH and you.pose != Pose.JUMP else 0.0) + noise(), "attack",
                   frozenset({"kick" if you.pose == Pose.CROUCH or self.rng.random() < p["kick_rate"] else "punch"})),   # しゃがんだ相手には下段
            Option(p["jump_rate"] + noise(), "jump", frozenset({"up", toward})),
            Option(p["crouch_rate"] + noise(), "crouch", frozenset({"down"})),
        ]
        best = max(options)                                 # order=True なので score で比べられる
        self.keys = best.keys
        return set(self.keys)


Script = Generator[set[str], None, None]                    # 台本: 毎コマ「押しているキーの集合」を yield するジェネレータ


def hold(keys: set[str], seconds: float) -> Script:
    """同じキーを seconds 秒押し続ける。"""
    for _ in range(max(1, round(seconds * FPS))):
        yield keys


def approach(game: "Game", gap: float) -> Script:
    """間合いが gap になるまで寄る。"""
    me, you = game.enemy, game.player
    while abs(you.x - me.x) > gap and not game.result:
        yield {"left" if you.x < me.x else "right"}


def retreat(game: "Game", gap: float, seconds: float = 1.5) -> Script:
    """間合いが gap になるまで下がる（端に着いたら諦める。最長 seconds 秒）。"""
    me, you = game.enemy, game.player
    for _ in range(round(seconds * FPS)):
        if abs(you.x - me.x) >= gap or me.x <= LEFT_EDGE + 12 or me.x >= RIGHT_EDGE - 12:
            break
        yield {"right" if you.x < me.x else "left"}


def tao_script(game: "Game") -> Script:
    """タオ: 離れて火の玉を 2 発。近づかれたらキックで追い返す。"""
    while True:
        if abs(game.player.x - game.enemy.x) <= REACH + 6:
            yield from hold({"kick"}, 1 / FPS)
            yield from hold(set(), 0.45)
            continue
        yield from retreat(game, 44, 0.8)
        for _ in range(2):
            yield from hold({"weapon"}, 1 / FPS)
            yield from hold(set(), 0.5)


def chen_script(game: "Game") -> Script:
    """チェン: 鎖の届く間合いまで寄って振り、少し下がる。近づかれたらキック。"""
    while True:
        yield from approach(game, CHAIN_REACH - 4)
        if abs(game.player.x - game.enemy.x) <= REACH:
            yield from hold({"kick"}, 1 / FPS)
            yield from hold(set(), 0.5)
        else:
            yield from hold({"weapon"}, 1 / FPS)
            yield from hold(set(), 0.6)
        yield from retreat(game, CHAIN_REACH, 0.5)


def lang_script(game: "Game") -> Script:
    """ラン: 遠くから手裏剣を 2 枚、跳んで近づいてパンチ、また離れる。"""
    while True:
        yield from retreat(game, 56)
        for _ in range(2):
            yield from hold({"weapon"}, 1 / FPS)
            yield from hold(set(), 0.5)
        yield from approach(game, 40)
        toward = "left" if game.player.x < game.enemy.x else "right"
        yield from hold({"up", toward}, 1 / FPS)
        yield from hold(set(), 0.12)
        yield from hold({"kick"}, 1 / FPS)                  # 跳び蹴りで飛び込む
        while not game.enemy.grounded and not game.result:
            yield set()
        yield from hold(set(), 0.3)


def mu_script(game: "Game") -> Script:
    """ムー: 高く跳んで、空中から跳び蹴りで飛び込む。着地したら少し隙があり、それから離れる。"""
    while True:
        yield from approach(game, game.rng.uniform(34, 44))
        toward = "left" if game.player.x < game.enemy.x else "right"
        yield from hold({"up", toward}, 1 / FPS)
        yield from hold(set(), 0.35)                        # 落ち始めてから蹴る（低い相手にも当たる）
        yield from hold({"kick"}, 1 / FPS)
        while not game.enemy.grounded and not game.result:
            yield set()
        yield from hold(set(), 0.35)                        # 着地の隙
        yield from retreat(game, 36, 0.6)


class ScriptBrain(Brain):
    """台本で動く頭。よけ（反応の遅れ）は Brain と同じで、それ以外は台本の次のキーを使う。"""

    def __init__(self, params: ChainMap | dict, rng: random.Random, script: Callable[["Game"], Script], game: "Game"):
        super().__init__(params, rng)
        self.make_script = script
        self.game = game
        self.script = script(game)

    def choose(self, game: "Game", gap: float, toward: str, away: str) -> set[str]:
        try:
            return next(self.script)
        except StopIteration:                               # 台本が終わったら最初から
            self.script = self.make_script(game)
            return next(self.script)


ENEMIES: dict[str, EnemyDef] = {
    "WANG": {"colors": {"B": "R", "L": "D"}, "brain": {"kick_rate": 0.5}, "weapon": None, "script": None, "jump": JUMP_SPEED},
    "TAO": {"colors": {"B": "O", "L": "Y"}, "brain": {"dodge": 0.4}, "weapon": FIRE_THROW, "script": tao_script, "jump": JUMP_SPEED},
    "CHEN": {"colors": {"B": "G", "L": "Y"}, "brain": {"dodge": 0.5}, "weapon": CHAIN_SWING, "script": chen_script, "jump": JUMP_SPEED},
    "LANG": {"colors": {"B": "W", "L": "K"}, "brain": {"dodge": 0.6}, "weapon": SHURIKEN_THROW, "script": lang_script, "jump": JUMP_SPEED},
    "MU": {"colors": {"B": "K", "L": "W"}, "brain": {"dodge": 0.3}, "weapon": None, "script": mu_script, "jump": 150.0},
}


ENEMY_ORDER = list(ENEMIES)


def overlaps(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    """矩形 (x0, y0, x1, y1) どうしが重なるか。"""
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


class Game:
    """1 試合。2 人の格闘家と舞台。表示と入力は持たない。"""

    def __init__(self, seed: int | None = None, enemy: str = "WANG", level: str = "normal"):
        self.rng = random.Random(seed)
        spec = ENEMIES[enemy]
        self.player = Fighter("OOLONG", 36.0, "right")
        self.enemy = Fighter(enemy, 92.0, "left", colors=spec["colors"], weapon=spec["weapon"], jump_speed=spec["jump"])
        params = ChainMap(LEVELS[level], spec["brain"], DEFAULT_BRAIN)   # 難度 → 敵ごと → 既定 の 3 層。手前から順に引く
        self.brain = ScriptBrain(params, self.rng, spec["script"], self) if spec["script"] else Brain(params, self.rng)
        self.level = level
        self.projectiles: dict[str, Slot[Projectile]] = {f.name: Slot(MAX_PROJECTILES) for f in (self.player, self.enemy)}
        self.pilot_timer = 0.0                              # 自動操縦（autopilot）の判断の間隔
        self.pilot_keys: set[str] = set()
        self.time = 0.0
        self.result: str | None = None

    @property
    def fighters(self) -> list[Fighter]:
        return [self.player, self.enemy]

    def control(self, who: Fighter, keys: set[str], dt: float) -> None:
        """入力（押されているキーの集合）から姿勢と移動と技を決める。硬直中は何もできない。"""
        if who.stun > 0 or self.result is not None:
            return
        if "punch" in keys:
            who.punch()
        if "kick" in keys:
            who.kick()
        if "weapon" in keys:
            who.use_weapon()
        if who.anim is not None and who.pose != Pose.JUMP:  # 技の途中は歩けない・しゃがめない（跳び蹴りは飛び続ける）
            return
        dx = (1 if "right" in keys else 0) - (1 if "left" in keys else 0)
        match who.pose, "up" in keys, "down" in keys:
            case Pose.JUMP, _, _:                           # 空中では何もできない
                pass
            case _, True, _:                                # 上で跳ぶ（横を押していればその方向へ）
                who.vx = dx * WALK_SPEED
                who.jump()
            case _, False, True:                            # 下でしゃがむ
                who.pose = Pose.CROUCH
            case Pose.CROUCH, False, False:                 # 下を離したら立つ
                who.pose = Pose.STAND
            case Pose.STAND, False, False:                  # 立っているときだけ歩ける
                who.x += dx * WALK_SPEED * dt

    def separate(self) -> None:
        """2 人が重なったら、地面にいる方（両方なら両方）を押し戻す。"""
        a, b = self.player, self.enemy
        if not (a.grounded and b.grounded):
            return
        ax0, _, ax1, _ = a.box
        bx0, _, bx1, _ = b.box
        overlap = min(ax1, bx1) - max(ax0, bx0)
        if overlap <= 0:
            return
        sign = 1 if a.x <= b.x else -1
        a.x -= sign * overlap / 2
        b.x += sign * overlap / 2

    def update(self, dt: float) -> None:
        if self.result is not None:
            return
        self.time += dt
        for f in self.fighters:
            f.update(dt)
        for attacker, victim in ((self.player, self.enemy), (self.enemy, self.player)):
            self.resolve(attacker, victim)
            self.fly(attacker, victim, dt)
        self.separate()
        for f, other in ((self.player, self.enemy), (self.enemy, self.player)):
            f.face(other)
        if self.enemy.hp == 0:
            self.result = "win"
        elif self.player.hp == 0:
            self.result = "lose"

    def fly(self, owner: Fighter, victim: Fighter, dt: float) -> None:
        """owner の飛び道具を進め、相手に当たれば消す。画面の外か地面に着いても消す。"""
        slot = self.projectiles[owner.name]
        for shot in slot:
            shot.update(dt)
            if overlaps(shot.box, victim.box) and victim.stun == 0:
                victim.hurt(shot.damage, from_right=shot.vx < 0)
                owner.hits += 1
                shot.x = -100                               # 当たったら消す（gone にする）
        slot.keep(lambda shot: not shot.gone)

    def throw(self, attacker: Fighter, kind: str) -> None:
        """飛び道具を出す。火の玉はまっすぐ、手裏剣は少し上へ投げて落ちてくる。"""
        sign = 1 if attacker.facing == "right" else -1
        if kind == "fireball":
            height = self.rng.choice((13, 6))               # 高い玉はしゃがんでよけ、低い玉は跳んでよける
            shot = Projectile(attacker.x + sign * 8, FLOOR_Y - height, sign * FIREBALL_SPEED, 0.0, FIREBALL, FIRE_THROW.damage, owner=attacker.name)
        else:
            shot = Projectile(attacker.x + sign * 8, FLOOR_Y - 16, sign * SHURIKEN_SPEED, -40.0, SHURIKEN, SHURIKEN_THROW.damage, gravity=SHURIKEN_GRAVITY, owner=attacker.name)
        self.projectiles[attacker.name].add(shot)           # いっぱいなら出ない

    def resolve(self, attacker: Fighter, victim: Fighter) -> None:
        """攻撃ボックスが相手の体に重なったら当たり。1 つの技で 1 回だけ。飛び道具の技は当たり判定の代わりに 1 発出す。"""
        if attacker.anim is not None and attacker.anim.move.projectile and attacker.anim.active:
            attacker.anim.hit_done = True                   # 出すのは 1 回
            self.throw(attacker, attacker.anim.move.projectile)
            return
        box = attacker.attack_box()
        if box is None:
            return
        if overlaps(box, victim.box):
            attacker.anim.hit_done = True
            attacker.hits += 1
            victim.hurt(attacker.anim.move.damage, from_right=attacker.x > victim.x)

    def draw(self, screen: Screen) -> None:
        screen.clear()
        for y in range(FLOOR_Y):                            # 空。下ほど明るい
            t = y / FLOOR_Y
            color = tuple(int(SKY[i] + (SKY_LOW[i] - SKY[i]) * t) for i in range(3))
            for x in range(WIDTH):
                screen.plot(x, y, color)
        for px in (12, 40, 88, 116):                        # 奥の柱
            for y in range(18, FLOOR_Y):
                for x in range(px, px + 4):
                    screen.plot(x, y, PILLAR)
        for y in range(FLOOR_Y, HEIGHT):                    # 床
            for x in range(WIDTH):
                screen.plot(x, y, FLOOR_LINE if y == FLOOR_Y or (y - FLOOR_Y) % 4 == 0 else FLOOR)
        self.draw_bars(screen)
        for f in sorted(self.fighters, key=lambda f: f.y):  # 高い方を後に（手前に）描く
            f.draw(screen)
        for slot in self.projectiles.values():
            for shot in slot:
                shot.draw(screen)

    def draw_bars(self, screen: Screen) -> None:
        """体力バー。自機は左から右へ、相手は右から左へ減る。"""
        for f, x0, color, rtl in ((self.player, 6, BAR_PLAYER, False), (self.enemy, WIDTH - 6 - BAR_WIDTH, BAR_ENEMY, True)):
            filled = round(BAR_WIDTH * f.hp / MAX_HP)
            for i in range(BAR_WIDTH):
                on = (BAR_WIDTH - 1 - i < filled) if rtl else (i < filled)
                for y in range(4, 8):
                    screen.plot(x0 + i, y, color if on else BAR_BACK)

    def status(self) -> str:
        p, e = self.player, self.enemy
        action = p.anim.move.name if p.anim else ("stun" if p.stun > 0 else p.pose.name.lower())
        return f"{p.name} {p.hp:3d} {'█' * (p.hp // 10):<10}  vs  {'█' * (e.hp // 10):>10} {e.hp:3d} {e.name}   {action}"


def autopilot(game: Game, dt: float) -> set[str]:
    """自機の自動操縦（デモ用）。相手と逆のことをする: 相手が寄れば跳んで越え、離れれば追う。"""
    p, e = game.player, game.enemy
    keys: set[str] = set()
    gap = abs(e.x - p.x)
    game.pilot_timer -= dt
    if game.pilot_timer > 0 and not (game.pilot_keys & {"left", "right"} and gap <= REACH - 2):
        return set(game.pilot_keys)                         # 人と同じく、決めた行動を少しの間続ける（寄っている途中で間合いに入ればすぐ決め直す）
    game.pilot_timer = PILOT_INTERVAL
    game.pilot_keys = keys
    if p.anim is not None:
        return keys
    incoming = [s for s in game.projectiles[e.name] if (s.vx < 0) == (s.x > p.x) and abs(s.x - p.x) < 30]
    if incoming and p.grounded and game.rng.random() < 0.5:
        shot = min(incoming, key=lambda s: abs(s.x - p.x))
        keys.add("up" if shot.y + shot.spr.height > FLOOR_Y - 8 else "down")   # 低い飛び道具は跳んで、高いのはしゃがんでよける（半分は間に合わない）
    elif e.anim is not None and gap <= (CHAIN_REACH if e.anim.move is CHAIN_SWING else REACH) + 4 and p.grounded and game.rng.random() < 0.5:   # 相手の技が見えたら半分はよける
        keys.add("down" if e.anim.move.box[1] >= 8 else "up")
    elif gap > REACH:
        keys.add("right" if p.x < e.x else "left")          # 技の届く間合いまで寄る
    elif e.pose == Pose.JUMP:
        keys.add("down")                                    # 跳んできたらしゃがんでやり過ごす
    elif e.pose == Pose.CROUCH:
        keys.add("kick")                                    # しゃがんだ相手には下段
    else:
        keys.add("punch" if game.rng.random() < 0.6 else "kick")
    return keys
# --- ここから下はブラウザ版だけ。CLI 版の play() / read_keys() / Screen.render() にあたる ---

canvas = document.querySelector("#screen")
ctx = canvas.getContext("2d")
ctx.imageSmoothingEnabled = False
player_label = document.querySelector("#turn")
enemy_label = document.querySelector("#lives")
time_label = document.querySelector("#progress")
hud = document.querySelector("#hud")
message = document.querySelector("#message")
start_button = document.querySelector("#start-btn")
auto_button = document.querySelector("#auto-btn")
pad_buttons = document.querySelectorAll(".pad button")

QUERY = dict(pair.split("=", 1) for pair in str(window.location.search).lstrip("?").split("&") if "=" in pair)
LEVEL = QUERY.get("level", "normal") if QUERY.get("level") in LEVELS else "normal"           # /g52/?level=hard で難度
ENEMY = QUERY.get("enemy", "WANG").upper() if QUERY.get("enemy", "WANG").upper() in ENEMIES else "WANG"   # /g52/?enemy=tao で相手

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
game = Game(enemy=ENEMY, level=LEVEL)
pressed = {"left": False, "right": False, "up": False, "down": False, "punch": False, "kick": False}
auto = False                                                # 自機も自動（デモ）
running = False


def draw():
    """CLI 版の Game.draw() + Screen.render() にあたる。描く先を CanvasScreen に差し替えて Game.draw() を呼ぶ。"""
    game.draw(canvas_screen)
    player_label.textContent = f"{game.player.name} {game.player.hp}"
    enemy_label.textContent = str(game.enemy.hp)
    time_label.textContent = f"{game.time:.1f} 秒"
    hud.textContent = game.status()
    if game.result is not None:
        message.textContent = f"{RESULT_TEXT[game.result]}　{game.time:.1f} 秒　当てた {game.player.hits} / 食らった {game.enemy.hits}"


async def loop():
    """1/FPS 秒ごとに更新して描く。CLI 版の play() の while と同じ。"""
    global running
    running = True
    last = window.performance.now() / 1000
    while game.result is None:
        now = window.performance.now() / 1000
        dt = min(now - last, 0.1)
        last = now
        keys = autopilot(game, dt) if auto else {k for k, down in pressed.items() if down}
        game.control(game.player, keys, dt)
        game.control(game.enemy, game.brain.decide(game, dt), dt)
        game.update(dt)
        draw()
        await asyncio.sleep(1 / FPS)
    draw()
    running = False


def start(demo: bool = False):
    global game, auto
    game = Game(enemy=ENEMY, level=LEVEL)
    auto = demo
    message.textContent = f"デモ（自機も自動、{ENEMY} / {LEVEL}）" if demo else f"相手 {ENEMY} / 難度 {LEVEL}"
    for button in pad_buttons:
        button.disabled = demo
    if not running:
        asyncio.ensure_future(loop())


KEYS = {"ArrowLeft": "left", "a": "left", "ArrowRight": "right", "d": "right", "ArrowUp": "up", "w": "up", "ArrowDown": "down", "s": "down", "z": "punch", "j": "punch", "x": "kick", "k": "kick"}


@when("keydown", "body")
def on_keydown(event):
    global auto
    key = KEYS.get(event.key)
    if key is None:
        return
    event.preventDefault()
    auto = False                                            # 何か押したら自分で操縦
    pressed[key] = True


@when("keyup", "body")
def on_keyup(event):
    key = KEYS.get(event.key)
    if key in pressed:
        pressed[key] = False


@when("pointerdown", ".pad button")
def on_pad_down(event):
    pressed[event.target.getAttribute("data-key")] = True


@when("pointerup", ".pad button")
def on_pad_up(event):
    pressed[event.target.getAttribute("data-key")] = False


@when("pointerleave", ".pad button")
def on_pad_leave(event):
    pressed[event.target.getAttribute("data-key")] = False


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
