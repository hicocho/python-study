"""ギャラガ風シューティング — 完成: 自機とスプライト。多色ドット絵を端末にトゥルーカラーで描き、動かして撃つ。class Game にまとめる。"""

import argparse
import base64
import os
import random
import select
import shutil
import struct
import sys
import termios
import time
import tty
import zlib
from dataclasses import dataclass, field
from functools import cache
from itertools import cycle
from pathlib import Path

WIDTH = 96                                  # 画面の横のドット数（端末では 1 ドット = 1 桁）
HEIGHT = 96                                 # 画面の縦のドット数（端末では 2 ドット = 1 行）
FPS = 30
PLAYER_SPEED = 60.0                         # ドット/秒
BULLET_SPEED = 120.0
MAX_BULLETS = 2
STAR_COUNT = 40

# パレット。ドット絵の 1 文字 → RGB。"." は透明
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

    def render(self) -> str:
        """端末用の文字列。1 行に 2 ドット分の行を詰める（上が前景 ▀、下が背景）。色が変わるときだけエスケープを出す。"""
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


def read_keys(fd: int) -> list[str]:
    """押されているキーを名前で。矢印は "left" "right"、スペースは "fire"、q。"""
    keys = []
    while select.select([fd], [], [], 0)[0]:
        data = os.read(fd, 64)
        text = data.decode(errors="ignore")
        for token, name in (("\x1b[D", "left"), ("\x1b[C", "right"), (" ", "fire"), ("q", "quit"), ("a", "left"), ("d", "right")):
            keys.extend([name] * text.count(token))
    return keys


def check_terminal() -> str | None:
    """画面が収まる大きさか。足りなければその旨。"""
    columns, lines = shutil.get_terminal_size()
    need_lines = HEIGHT // 2 + 3
    if columns < WIDTH or lines < need_lines:
        return f"端末を {WIDTH} 桁 × {need_lines} 行以上にしてください（今は {columns} × {lines}）。"
    return None


def play(game: Game) -> None:
    """端末で遊ぶ。1/FPS 秒ごとに更新して描く。"""
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    tty.setcbreak(fd)
    screen = Screen()
    held = {"left": 0.0, "right": 0.0}                       # 押した直後の少しの間だけ動き続ける
    try:
        sys.stdout.write("\x1b[2J\x1b[?25l")
        last = time.monotonic()
        while game.result is None:
            now = time.monotonic()
            dt = min(now - last, 0.1)
            last = now
            for key in read_keys(fd):
                if key == "quit":
                    game.result = "quit"
                elif key == "fire":
                    game.fire()
                elif key in held:
                    held[key] = now + 0.12
            direction = (1 if held["right"] > now else 0) - (1 if held["left"] > now else 0)
            game.move(direction, dt)
            game.update(dt)
            game.draw(screen)
            sys.stdout.write("\x1b[H" + screen.render() + game.status() + "   ←→ 移動  スペース 撃つ  q やめる\x1b[K\n")
            sys.stdout.flush()
            time.sleep(max(0.0, 1 / FPS - (time.monotonic() - now)))
    finally:
        sys.stdout.write("\x1b[0m\x1b[?25h")
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    print(f"\n{RESULT_TEXT[game.result]}  {game.status()}")


def main():
    parser = argparse.ArgumentParser(description="ギャラガ風シューティング（自機とスプライト）")
    parser.add_argument("--sheet", type=Path, metavar="FILE.png", help="スプライトを 1 枚の PNG に書き出して終わる")
    parser.add_argument("--scale", type=int, default=4, help="--sheet の拡大倍率")
    parser.add_argument("--show", action="store_true", help="スプライトを端末に描いて終わる（動かさない）")
    args = parser.parse_args()

    if args.sheet:
        args.sheet.write_bytes(png_bytes(sprite_sheet(ALL_SPRITES), args.scale, background=(16, 16, 32)))
        print(f"{args.sheet} に {len(ALL_SPRITES)} 枚（{args.scale} 倍）を書き出しました。")
        return
    if args.show:
        screen = Screen()
        x = 2
        for spr in ALL_SPRITES:
            screen.blit(spr, x, 4)
            x += spr.width + 3
        print(screen.render())
        return

    if (warning := check_terminal()) is not None:
        raise SystemExit(warning)
    play(Game())


if __name__ == "__main__":
    main()
