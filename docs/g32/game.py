"""ギャラガ風（自機とスプライト）ブラウザ版

CLI 版（g32-galaga-sprites/main.py）とドット絵・動き・当たり判定はまったく同じ。
定数とパレット、Sprite / sprite()、全スプライト、Screen、png_bytes() / data_uri()、
Body / Enemy / Explosion、そして class Game を、ステップの目印コメント（# ←）を外しただけで 1 文字も変えずに持ってきている。

持ってこなかったのは端末に描く Screen.render() を使う play() / read_keys() / check_terminal() / main() だけ。
出口は canvas。各スプライトは data_uri()（Python が組み立てた PNG）を Image にして drawImage で置く。
"""

import asyncio
import base64
import random
import struct
import zlib
from dataclasses import dataclass, field
from functools import cache
from itertools import cycle

from js import Image, window
from pyscript import document, when


# --- ここから class Game まで、CLI 版（g32-galaga-sprites/main.py）からそのまま ---


WIDTH = 96                                  # 画面の横のドット数（端末では 1 ドット = 1 桁）
HEIGHT = 96                                 # 画面の縦のドット数（端末では 2 ドット = 1 行）
FPS = 30
PLAYER_SPEED = 60.0                         # ドット/秒
BULLET_SPEED = 120.0
MAX_BULLETS = 2
STAR_COUNT = 40


PALETTE = {
    "W": (255, 255, 255), "R": (230, 40, 40), "B": (40, 90, 230), "Y": (250, 220, 50),
    "G": (60, 200, 90), "C": (90, 220, 240), "M": (200, 70, 220), "O": (250, 140, 30),
    "K": (40, 40, 60), "L": (150, 190, 255), "P": (255, 140, 180), "D": (120, 20, 20),
}


RESULT_TEXT = {
    "clear": "編隊を全滅させた！",
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


FIGHTER = sprite("fighter", """
......W......
......W......
.....WWW.....
.....WWW.....
....WWRWW....
....WWRWW....
.B..WWRWW..B.
.B.WWWRWWW.B.
.BWWWRRRWWWB.
WBBWWWRWWWBBW
WWBWWWRWWWBWW
WWWWW.R.WWWWW
.W.WW...WW.W.
...W.....W...
""")


BEE = [sprite("bee-a", """
..B......B..
.BB......BB.
.BB.YYYY.BB.
..BYYYYYYB..
..YYBYYBYY..
.YYYYYYYYYY.
YYYYYYYYYYYY
.YY.YYYY.YY.
..Y.YYYY.Y..
....Y..Y....
"""), sprite("bee-b", """
............
............
....YYYY....
.B.YYYYYY.B.
BBBYYBYYBYBB
BBYYYYYYYYBB
YBYYYYYYYYBY
.YY.YYYY.YY.
..Y.YYYY.Y..
....Y..Y....
""")]


BUTTERFLY = [sprite("butterfly-a", """
.R........R.
.RR......RR.
..RRWWWWRR..
..RWWBBWWR..
.RRWWBBWWRR.
RRWWWWWWWWRR
.R.WWWWWW.R.
...WW..WW...
...W....W...
..W......W..
"""), sprite("butterfly-b", """
............
....WWWW....
...WWBBWW...
.R.WWBBWW.R.
.RRWWWWWWRR.
RRRWWWWWWRRR
.R.WWWWWW.R.
...WW..WW...
...W....W...
..W......W..
""")]


BOSS = [sprite("boss-a", """
.G..........G.
.GG........GG.
.GG.BBBBBB.GG.
..GBBGGGGBBG..
..BBGGGGGGBB..
.BBGGCGGCGGBB.
BBBGGGGGGGGBBB
.BBGGGGGGGGBB.
..BBBG..GBBB..
...BB....BB...
...B......B...
..B........B..
"""), sprite("boss-b", """
..............
....BBBBBB....
.G.BBGGGGBB.G.
.GGBGGGGGGBGG.
.GGGGCGGCGGGG.
BGGGGGGGGGGGGB
.BBGGGGGGGGBB.
..BBBG..GBBB..
...BB....BB...
...B......B...
..B........B..
""")]


BULLET = sprite("bullet", """
W
L
L
W
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


ALL_SPRITES = [FIGHTER, *BEE, *BUTTERFLY, *BOSS, BOSS[0].recolor({"G": "M"}), BULLET, *EXPLOSION]


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


@dataclass
class Enemy(Body):
    frames: cycle = field(default_factory=lambda: cycle(BEE))
    points: int = 50
    alive: bool = True

    def flap(self) -> None:
        self.spr = next(self.frames)


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


class Game:
    """1 回のプレイ。自機・弾・敵・爆発・星。表示と入力は持たない。"""

    def __init__(self, seed: int | None = None):
        rng = random.Random(seed)
        self.player = Body(WIDTH / 2 - FIGHTER.width / 2, HEIGHT - FIGHTER.height - 2, FIGHTER)
        self.bullets: list[Body] = []
        self.enemies: list[Enemy] = []
        for row, (frames, points) in enumerate([(BOSS, 150), (BUTTERFLY, 80), (BUTTERFLY, 80), (BEE, 50), (BEE, 50)]):
            count, pitch = (4, 16) if frames is BOSS else (7, 13)   # 1 列の数と、列の間隔
            for i in range(count):
                x = WIDTH / 2 - count * pitch / 2 + i * pitch + (pitch - frames[0].width) / 2
                flapping = cycle(frames)                        # 最初のコマを取っておくと、次の next() で 2 コマ目になる
                self.enemies.append(Enemy(x, 8 + row * 12, next(flapping), flapping, points))
        self.explosions: list[Explosion] = []
        self.stars = [[rng.uniform(0, WIDTH), rng.uniform(0, HEIGHT), rng.choice([8, 16, 28])] for _ in range(STAR_COUNT)]
        self.score = 0
        self.shots = 0
        self.hits = 0
        self.time = 0.0
        self.flap_timer = 0.0
        self.boom_timer = 0.0
        self.result: str | None = None

    def move(self, direction: int, dt: float) -> None:
        """自機を左右に。direction は -1 / 0 / 1。"""
        self.player.x = max(0.0, min(WIDTH - FIGHTER.width, self.player.x + direction * PLAYER_SPEED * dt))

    def fire(self) -> bool:
        if self.result is not None or len(self.bullets) >= MAX_BULLETS:
            return False
        self.bullets.append(Body(self.player.x + FIGHTER.width // 2, self.player.y - BULLET.height, BULLET))
        self.shots += 1
        return True

    def update(self, dt: float) -> None:
        """時間を dt 秒進める。"""
        if self.result is not None:
            return
        self.time += dt
        for star in self.stars:                             # 星は下へ流れる。速さは 3 種類（奥行き）
            star[1] += star[2] * dt
            if star[1] >= HEIGHT:
                star[1] -= HEIGHT
        for bullet in self.bullets:
            bullet.y -= BULLET_SPEED * dt
        self.bullets = [b for b in self.bullets if b.y + BULLET.height > 0]
        self.flap_timer += dt
        if self.flap_timer >= 0.5:                          # 0.5 秒ごとに羽ばたき
            self.flap_timer -= 0.5
            for enemy in self.enemies:
                enemy.flap()
        for bullet in list(self.bullets):
            target = next((e for e in self.enemies if e.alive and e.overlaps(bullet)), None)
            if target is not None:
                target.alive = False
                self.bullets.remove(bullet)
                self.hits += 1
                self.score += target.points
                self.explosions.append(Explosion(target.x + target.spr.width / 2 - EXPLOSION[0].width / 2,
                                                 target.y + target.spr.height / 2 - EXPLOSION[0].height / 2, EXPLOSION[0]))
        self.boom_timer += dt
        if self.boom_timer >= 1 / 12:                       # 爆発は 1 秒に 12 コマ
            self.boom_timer -= 1 / 12
            self.explosions = [boom for boom in self.explosions if boom.advance()]
        if not any(e.alive for e in self.enemies):
            self.result = "clear"

    def draw(self, screen: Screen) -> None:
        """今の状態を Screen に描く。"""
        screen.clear()
        for x, y, speed in self.stars:
            screen.plot(int(x), int(y), (90, 90, 130) if speed < 20 else (170, 170, 220))
        for enemy in self.enemies:
            if enemy.alive:
                screen.blit(enemy.spr, enemy.x, enemy.y)
        for bullet in self.bullets:
            screen.blit(BULLET, bullet.x, bullet.y)
        for boom in self.explosions:
            screen.blit(boom.spr, boom.x, boom.y)
        if self.result != "over":
            screen.blit(FIGHTER, self.player.x, self.player.y)

    def status(self) -> str:
        left = sum(1 for e in self.enemies if e.alive)
        accuracy = f"{self.hits / self.shots * 100:3.0f}%" if self.shots else "  -"
        return f"SCORE {self.score:6d}   敵 {left:2d}   命中率 {accuracy}   {self.time:5.1f} 秒"


# --- ここから下はブラウザ版だけ。CLI 版の play() / read_keys() / Screen.render() にあたる ---

canvas = document.querySelector("#screen")
ctx = canvas.getContext("2d")
ctx.imageSmoothingEnabled = False
score_label = document.querySelector("#turn")
left_label = document.querySelector("#left")
acc_label = document.querySelector("#acc")
hud = document.querySelector("#hud")
message = document.querySelector("#message")
start_button = document.querySelector("#start-btn")
pad_buttons = document.querySelectorAll(".pad button")

images: dict[str, object] = {}                              # スプライト名 → Image。PNG は Python が作る


def image_of(spr: Sprite):
    key = spr.name + "".join(spr.rows)
    if key not in images:
        img = Image.new()
        img.src = data_uri(spr)
        images[key] = img
    return images[key]


game = Game()
screen = Screen()                                           # CLI 版と同じ「描く先」。ここでは星の位置だけに使う
pressed = {"left": False, "right": False}
running = False


def draw():
    """CLI 版の Game.draw() + Screen.render() にあたる。星は 1 ドットの矩形、スプライトは PNG。"""
    ctx.fillStyle = "#000"
    ctx.fillRect(0, 0, WIDTH, HEIGHT)
    for x, y, speed in game.stars:
        ctx.fillStyle = "#5a5a82" if speed < 20 else "#aaaadc"
        ctx.fillRect(int(x), int(y), 1, 1)
    for enemy in game.enemies:
        if enemy.alive:
            ctx.drawImage(image_of(enemy.spr), round(enemy.x), round(enemy.y))
    for bullet in game.bullets:
        ctx.drawImage(image_of(BULLET), round(bullet.x), round(bullet.y))
    for boom in game.explosions:
        ctx.drawImage(image_of(boom.spr), round(boom.x), round(boom.y))
    if game.result != "over":
        ctx.drawImage(image_of(FIGHTER), round(game.player.x), round(game.player.y))
    score_label.textContent = f"SCORE {game.score}"
    left_label.textContent = str(sum(1 for e in game.enemies if e.alive))
    acc_label.textContent = f"{game.hits / game.shots * 100:.0f}%" if game.shots else "-"
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
        game.move((1 if pressed["right"] else 0) - (1 if pressed["left"] else 0), dt)
        game.update(dt)
        draw()
        await asyncio.sleep(1 / FPS)
    draw()
    running = False


def start():
    global game
    game = Game()
    message.textContent = ""
    for button in pad_buttons:
        button.disabled = False
    if not running:
        asyncio.ensure_future(loop())


KEYS = {"ArrowLeft": "left", "a": "left", "ArrowRight": "right", "d": "right", " ": "fire"}


@when("keydown", "body")
def on_keydown(event):
    key = KEYS.get(event.key)
    if key is None:
        return
    event.preventDefault()
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


# Pyodide の読み込みが終わってから実行される＝ここが準備完了の合図
document.querySelector("#loading").hidden = True
start_button.disabled = False
start()
