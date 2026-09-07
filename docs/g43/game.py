"""グラディウス風（自機と横スクロール）ブラウザ版

CLI 版（g43-gradius-scroll/main.py）とドット絵・地形・当たり判定はまったく同じ。
定数とパレット、Sprite / sprite()、スプライト、Screen、png_bytes() / data_uri()、Body / Drawable / Terrain / Starfield / Player / Shot / Explosion、
autopilot()、そして class Game を、ステップの目印コメント（# ←）を外しただけで 1 文字も変えずに持ってきている。

持ってこなかったのは端末に描く Screen.render() を使う play() / read_keys() / check_terminal() / main() だけ。
出口は canvas。Screen と同じ clear() / plot() / blit() を持つ CanvasScreen を渡して、Game.draw() をそのまま呼ぶ。
"""

import asyncio
import base64
import random
import struct
import zlib
from bisect import bisect_right
from dataclasses import dataclass, field
from functools import cache
from itertools import pairwise
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


ALL_SPRITES = [VIC, BULLET, *EXPLOSION]


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


@dataclass
class Player(Body):
    """自機。復活直後は点滅する。"""

    safe: float = 0.0                                       # 無敵の残り秒数

    def draw(self, screen: Screen, scroll: float) -> None:
        if self.safe > 0 and int(self.safe * 10) % 2 == 0:
            return                                          # 点滅の消える側
        screen.blit(self.spr, self.x, self.y)


@dataclass
class Shot(Body):
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
        self.shots: list[Shot] = []
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
        return [self.stars, self.terrain, *self.shots, *self.explosions, self.player]

    def move(self, dx: int, dy: int, dt: float) -> None:
        """自機を上下左右に。dx, dy は -1 / 0 / 1。画面の外には出ない。"""
        if not self.alive:
            return
        self.player.x = max(0.0, min(WIDTH - VIC.width, self.player.x + dx * PLAYER_SPEED * dt))
        self.player.y = max(0.0, min(HEIGHT - VIC.height, self.player.y + dy * PLAYER_SPEED * dt))

    def fire(self) -> bool:
        if not self.alive or len(self.shots) >= MAX_BULLETS:
            return False
        self.shots.append(Shot(self.player.x + VIC.width, self.player.y + VIC.height // 2, BULLET))
        self.shots_fired += 1
        return True

    def explode(self, body: Body) -> None:
        self.explosions.append(Explosion(body.x + body.spr.width / 2 - EXPLOSION[0].width / 2,
                                         body.y + body.spr.height / 2 - EXPLOSION[0].height / 2, EXPLOSION[0]))

    def hit_player(self) -> None:
        """撃墜。残機を減らし、少し置いて画面の左の中央に戻す。"""
        self.explode(self.player)
        self.lives -= 1
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
        self.score = int(self.scroll / 10)                  # 進んだ距離が得点
        if self.dead_timer > 0:
            self.dead_timer = max(0.0, self.dead_timer - dt)
            if self.dead_timer == 0.0:                      # 復活。地形に埋まらない高さを探す
                self.player.x = 16.0
                floor, ceiling = self.terrain.heights(self.player.x + VIC.width / 2 + self.scroll)
                self.player.y = (ceiling + (HEIGHT - floor)) / 2 - VIC.height / 2
                self.player.safe = SAFE_TIME
        self.player.safe = max(0.0, self.player.safe - dt)
        for shot in self.shots:
            shot.x += BULLET_SPEED * dt
        self.shots = [s for s in self.shots if s.x < WIDTH and not self.terrain.hits(s, self.scroll)]
        if self.alive and self.player.safe == 0 and self.terrain.hits(self.player, self.scroll):
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
        return f"SCORE {self.score:5d}   残機 {'▲' * max(0, self.lives - 1):<2}   進み {min(100, self.scroll / STAGE_LENGTH * 100):3.0f}%   {self.time:5.1f} 秒"


def autopilot(game: Game, dt: float) -> tuple[int, int]:
    """自動操縦。少し先の地形の真ん中へ寄る。デモと難しさの確認に使う。"""
    ahead = game.player.x + VIC.width + 12 + game.scroll
    floor, ceiling = game.terrain.heights(ahead)
    target = (ceiling + (HEIGHT - floor)) / 2 - VIC.height / 2
    dy = 0 if abs(target - game.player.y) < 2 else (1 if target > game.player.y else -1)
    return 0, dy
# --- ここから下はブラウザ版だけ。CLI 版の play() / read_keys() / Screen.render() にあたる ---

canvas = document.querySelector("#screen")
ctx = canvas.getContext("2d")
ctx.imageSmoothingEnabled = False
score_label = document.querySelector("#turn")
lives_label = document.querySelector("#lives")
progress_label = document.querySelector("#progress")
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
            if game.rng.random() < 0.2:
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


KEYS = {"ArrowLeft": "left", "a": "left", "ArrowRight": "right", "d": "right", "ArrowUp": "up", "w": "up", "ArrowDown": "down", "s": "down", " ": "fire"}


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
