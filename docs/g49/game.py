"""イー・アル・カンフー風（舞台と格闘家）ブラウザ版

CLI 版（g49-kungfu-stage/main.py）とドット絵・動き・当たり判定はまったく同じ。
定数とパレット、Sprite / sprite()、格闘家の絵、Screen、png_bytes() / data_uri()、Fighter / Pose / flipped / recolored、
sparring() / autopilot()、そして class Game を、ステップの目印コメント（# ←）を外しただけで 1 文字も変えずに持ってきている。

持ってこなかったのは端末に描く Screen.render() を使う play() / read_keys() / check_terminal() / main() だけ。
出口は canvas。Screen と同じ clear() / plot() / blit() を持つ CanvasScreen を渡して、Game.draw() をそのまま呼ぶ。
"""

import asyncio
import base64
import random
import struct
import zlib
from dataclasses import dataclass, field, replace
from enum import Enum, auto
from functools import cache
from typing import Literal

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


BAR_WIDTH = 44                              # 体力バーの長さ（ドット）


DEMO_TIME = 20.0                            # --auto で見せる秒数


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
.....KKKK.......
....KSSSSK......
....SSKSSS......
.....SSSS.......
....BBBBBB......
...BBBBBBBB.....
..SBBBBBBBBSS...
..S.BBBBBB.SS...
....BBBBBB......
....YYYYYY......
....BBBBBB......
....BB..BB......
....BB..BB......
....BB..BB......
...KKK..KKK.....
""")


OOLONG_CROUCH = sprite("oolong-crouch", """
.....KKKK.......
....KSSSSK......
....SSKSSS......
...BBSSSSBB.....
..BBBBBBBBBBS...
..SBBBBBBBBBS...
....YYYYYYYY....
...BBBBBBBBBB...
..KKK......KKK..
""")


OOLONG_JUMP = sprite("oolong-jump", """
.....KKKK.......
....KSSSSK......
....SSKSSS......
.....SSSS.......
..S.BBBBBB.S....
..SBBBBBBBBS....
....BBBBBB......
....YYYYYY......
....BBBBBB......
...BBB..BBB.....
..KKK....KKK....
""")


ENEMY_COLORS = {"B": "R", "L": "D"}       # 相手は道着を赤に


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
    _hp: int = field(default=MAX_HP, repr=False)

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
        base = POSE_SPRITES[self.pose]
        if self.colors:
            base = recolored(base, tuple(sorted(self.colors.items())))
        return base if self.facing == "right" else flipped(base)

    @property
    def top(self) -> float:
        """絵の上端の画面 y。"""
        return FLOOR_Y - self.y - self.sprite.height

    @property
    def left(self) -> float:
        return self.x - self.sprite.width / 2

    @property
    def box(self) -> tuple[float, float, float, float]:
        """当たり判定の矩形 (x0, y0, x1, y1)。絵の透明でない部分より少し狭い。"""
        spr = self.sprite
        return self.left + 3, self.top, self.left + spr.width - 3, FLOOR_Y - self.y

    def jump(self) -> None:
        if self.grounded:
            self.pose = Pose.JUMP
            self.vy = JUMP_SPEED

    def face(self, other: "Fighter") -> None:
        """地面にいるときだけ相手の方を向く（空中では向きを変えない）。"""
        if self.grounded:
            self.facing = "right" if other.x >= self.x else "left"

    def update(self, dt: float) -> None:
        """重力と着地。"""
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


@cache
def flipped(spr: Sprite) -> Sprite:
    """左向きの絵。rows を 1 行ずつ反転した新しい Sprite を replace で作る（name も変える）。"""
    return replace(spr, name=spr.name + "-left", rows=tuple(row[::-1] for row in spr.rows))


@cache
def recolored(spr: Sprite, mapping: tuple[tuple[str, str], ...]) -> Sprite:
    return spr.recolor(dict(mapping))


ALL_SPRITES = [OOLONG_STAND, OOLONG_CROUCH, OOLONG_JUMP, recolored(OOLONG_STAND, tuple(sorted(ENEMY_COLORS.items()))), flipped(OOLONG_STAND)]


class Game:
    """1 試合。2 人の格闘家と舞台。表示と入力は持たない。"""

    def __init__(self, seed: int | None = None):
        self.rng = random.Random(seed)
        self.player = Fighter("OOLONG", 36.0, "right")
        self.enemy = Fighter("WANG", 92.0, "left", colors=ENEMY_COLORS)
        self.time = 0.0
        self.result: str | None = None
        self.enemy_timer = 0.0                              # 相手が次に何かするまで
        self.enemy_move = ""                                # 相手が今している気まぐれ（up / down / 無し）

    @property
    def fighters(self) -> list[Fighter]:
        return [self.player, self.enemy]

    def control(self, who: Fighter, keys: set[str], dt: float) -> None:
        """入力（押されているキーの集合）から姿勢と移動を決める。"""
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
        self.separate()
        for f, other in ((self.player, self.enemy), (self.enemy, self.player)):
            f.face(other)

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
        return f"{p.name} {p.hp:3d} {'█' * (p.hp // 10):<10}  vs  {'█' * (e.hp // 10):>10} {e.hp:3d} {e.name}   {p.pose.name.lower()} {p.facing}"


def sparring(game: Game, dt: float) -> set[str]:
    """相手の練習用の動き。間合い 30 ドットを保ち、ときどき跳ぶ・しゃがむ。返すのは押しているキーの集合。"""
    e, p = game.enemy, game.player
    game.enemy_timer -= dt
    if game.enemy_timer <= 0:
        game.enemy_timer = game.rng.uniform(0.6, 1.4)
        game.enemy_move = game.rng.choice(["", "", "up", "down"])
    keys: set[str] = set()
    gap = abs(e.x - p.x)
    if gap < 26:
        keys.add("left" if e.x < p.x else "right")          # 近すぎれば離れる
    elif gap > 34:
        keys.add("right" if e.x < p.x else "left")          # 遠ければ寄る
    if game.enemy_move:
        keys.add(game.enemy_move)
    return keys


def autopilot(game: Game, dt: float) -> set[str]:
    """自機の自動操縦（デモ用）。相手と逆のことをする: 相手が寄れば跳んで越え、離れれば追う。"""
    p, e = game.player, game.enemy
    keys: set[str] = set()
    gap = abs(e.x - p.x)
    if gap > 40:
        keys.add("right" if p.x < e.x else "left")
    elif gap < 22 and p.grounded:
        keys.add("up")
        keys.add("right" if p.x < e.x else "left")
    elif e.pose == Pose.JUMP and p.grounded:
        keys.add("down")
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
        message.textContent = RESULT_TEXT[game.result]


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
        game.control(game.enemy, sparring(game, dt), dt)
        game.update(dt)
        draw()
        await asyncio.sleep(1 / FPS)
    draw()
    running = False


def start(demo: bool = False):
    global game, auto
    game = Game()
    auto = demo
    message.textContent = "デモ（2 人とも自動）" if demo else ""
    for button in pad_buttons:
        button.disabled = demo
    if not running:
        asyncio.ensure_future(loop())


KEYS = {"ArrowLeft": "left", "a": "left", "ArrowRight": "right", "d": "right", "ArrowUp": "up", "w": "up", "ArrowDown": "down", "s": "down"}


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
