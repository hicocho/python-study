"""ぶよぶよ（落ちものパズル）

2 個組の玉が落ちてくる。同じ色が 4 つ以上つながると消え、上の玉が落ちてまたつながれば連鎖。
積み上がったら終わり（エンドレス）。消した数でレベルが上がり、落ちるのが速くなる。5 色。
今回の主題は「中身は Python、絵はブラウザで Three.js」の 2 本目。端末は ▀ の 2D で描く。
今回覚えるところ：
  盤は 2 次元の列      grid[行][列] に玉か None。行 0 が一番下。見えない行を 1 つ上に持つ（出てくる場所）
  つながりの探索       同じ色を幅優先で集める（flood fill）。4 つ以上なら消える
  連鎖の状態機械       FALL → SETTLE（落ちる）→ POP（消える）→ SETTLE → … → 次の玉。段階ごとに時間を持つ
  玉は id で追う       消えるまで同じ id。落ちても Three.js の球は作り直さず動かすだけ
  評価して選ぶ CPU    全部の置き方を試し、点と高さで選ぶ（検査とブラウザの自動プレイ）

    python3 main.py            遊ぶ（スペースで始める。← → で移動、↑ で回転、↓ で 1 段落とす、スペースで一気に落とす。q でやめる）
    python3 main.py --check    決まりを確かめる
    python3 main.py --sheet    遊んでいる場面を PNG に書き出す
"""

import io
import json
import math
import os
import random
import select
import sys
import time
import unicodedata
import wave
from array import array
from collections import deque
from dataclasses import dataclass, field
from enum import Enum

# ── 盤とゲームの決まり ────────────────────────────────────────────────────

COLS = 6
ROWS = 12                                           # 見える行
TOP = ROWS                                          # 見えない行（ここに出てくる）。grid は ROWS + 1 行
SPAWN_COL = 2
COLORS = 5
LINK = 4                                            # いくつつながると消えるか
STEP = 1 / 30
DROP_START = 0.9                                    # 1 段落ちる秒数（レベル 1）
DROP_STEP = 0.07                                    # レベルごとに縮む
DROP_MIN = 0.22
SOFT_DROP = 0.05                                    # ↓ を押している間
LEVEL_EVERY = 30                                    # この数消すごとにレベル +1
SETTLE_PER_ROW = 0.05                               # 1 段落ちる見た目の時間
SETTLE_MIN = 0.08
POP_TIME = 0.4                                      # 消える見た目の時間
LOCK_DELAY = 0.25                                   # 着地してから固まるまでの猶予（ずらせる）
CHAIN_BONUS = (0, 8, 16, 32, 64, 96, 128, 160, 192, 224, 256, 288, 320, 352, 384, 416, 448, 480, 512)
COLOR_BONUS = (0, 3, 6, 12, 24)
GROUP_BONUS = {4: 0, 5: 2, 6: 3, 7: 4, 8: 5, 9: 6, 10: 7}
ALL_CLEAR = 1000                                    # 盤が空になったら
ROT = ((0, 1), (1, 0), (0, -1), (-1, 0))            # 回転 0〜3 のときの相方の位置（上・右・下・左）
QUEUE = 2                                           # 次の玉を見せる数
FEVER_CHAIN = 3                                     # この連鎖でフィーバーが始まる
FEVER_TIME = 12.0                                   # フィーバーの秒数（連鎖でさらに延びる）
FEVER_SCALE = 2                                     # フィーバー中の点の倍率
MISSION_BONUS = 500                                 # お題を達成した点

# お題。順にクリアすると星が付く。check は世界を受けて達成かどうかを返す
MISSIONS = (
    dict(text="2 連鎖を出す", check=lambda w: w.max_chain >= 2),
    dict(text="30 個消す", check=lambda w: w.cleared >= 30),
    dict(text="3 連鎖を出す", check=lambda w: w.max_chain >= 3),
    dict(text="点を 3000 にする", check=lambda w: w.score >= 3000),
    dict(text="フィーバーを起こす", check=lambda w: w.fevers >= 1),
    dict(text="レベル 5 にする", check=lambda w: w.level >= 5),
    dict(text="4 連鎖を出す", check=lambda w: w.max_chain >= 4),
    dict(text="全消しする", check=lambda w: w.all_clears >= 1),
    dict(text="点を 20000 にする", check=lambda w: w.score >= 20000),
    dict(text="5 連鎖を出す", check=lambda w: w.max_chain >= 5),
)

# 玉の色。端末の色と、ブラウザの 16 進
PALETTE = (
    dict(name="赤", rgb=(230, 70, 80)),
    dict(name="緑", rgb=(70, 200, 110)),
    dict(name="青", rgb=(70, 130, 240)),
    dict(name="黄", rgb=(240, 200, 60)),
    dict(name="紫", rgb=(180, 90, 230)),
)

# 端末の板
WIDTH = 120
HEIGHT = 80
CELL = 6                                            # 1 マスのドット
BOARD_X = 42                                        # 盤の左端
BOARD_Y = 4                                         # 盤の上端（見える一番上の行）
NEXT_X = 88                                         # 次の玉を見せる場所

# ── 音（g73 と同じ作り方） ──────────────────────────────────────────────

RATE = 22050
VOLUME = 0.14


def tone(hz: float, seconds: float, volume: float = VOLUME) -> array:
    count = int(RATE * seconds)
    edge = RATE / 200
    samples = array("h")
    for i in range(count):
        fade = min(1.0, i / edge, (count - i) / edge)
        samples.append(int(32767 * volume * fade * math.sin(math.tau * hz * i / RATE)))
    return samples


def noise(seconds: float, volume: float, decay: float, seed: int = 1) -> array:
    luck = random.Random(seed)
    count = int(RATE * seconds)
    samples = array("h")
    for i in range(count):
        env = math.exp(-decay * i / RATE)
        samples.append(int(32767 * volume * env * luck.uniform(-1, 1)))
    return samples


def sound_bytes(kind: str) -> bytes:
    """出来事の音。pop1〜pop5 は連鎖の段で高くなる。"""
    if kind == "move":
        samples = tone(900, 0.02, VOLUME * 0.4)
    elif kind == "turn":
        samples = tone(700, 0.03, VOLUME * 0.5) + tone(1000, 0.03, VOLUME * 0.5)
    elif kind == "land":
        samples = noise(0.05, VOLUME * 0.8, 60.0, 4) + tone(300, 0.05, VOLUME * 0.5)
    elif kind.startswith("pop"):
        n = int(kind[3:])
        base = 520 * (1.19 ** (n - 1))               # 連鎖ごとに短 3 度ずつ上がる
        samples = tone(base, 0.08) + tone(base * 1.5, 0.12) + noise(0.08, VOLUME * 0.6, 50.0, n)
    elif kind == "level":
        samples = tone(660, 0.08) + tone(880, 0.08) + tone(1320, 0.18)
    elif kind == "fever":                           # フィーバー開始（駆け上がる）
        samples = sum((tone(440 * (1.12 ** i), 0.05, VOLUME * 0.8) for i in range(10)), array("h")) + tone(1320, 0.3)
    elif kind == "mission":                         # お題を達成（星）
        samples = tone(1047, 0.08) + tone(1319, 0.08) + tone(1568, 0.08) + tone(2093, 0.25)
    elif kind == "allclear":
        samples = tone(784, 0.1) + tone(988, 0.1) + tone(1175, 0.1) + tone(1568, 0.3)
    elif kind == "best":
        samples = tone(523, 0.1) + tone(659, 0.1) + tone(784, 0.1) + tone(1047, 0.3)
    else:                                           # end
        samples = tone(392, 0.15) + tone(330, 0.15) + tone(262, 0.4)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(samples.tobytes())
    return buffer.getvalue()


POPS = tuple(f"pop{n}" for n in range(1, 6))
EVENTS = ("end", "mission", "fever", "allclear", "level") + POPS[::-1] + ("land", "turn", "move")   # 目立つ順
SOUNDS = EVENTS + ("best",)

# ── 色（端末） ──────────────────────────────────────────────────────────

BACK = (18, 18, 34)
BOARD = (30, 30, 52)
BOARD_LINE = (44, 44, 72)
FRAME = (110, 115, 150)
GHOST = (70, 70, 100)
INK = (200, 205, 230)
SPARK = (255, 230, 150)


def shade(color: tuple[int, int, int], k: float) -> tuple[int, int, int]:
    return tuple(max(0, min(255, int(c * k))) for c in color)


# 3 × 5 の数字（g59・g68 と同じ）
FONT = {
    "0": ("###", "#.#", "#.#", "#.#", "###"), "1": (".#.", "##.", ".#.", ".#.", "###"),
    "2": ("###", "..#", "###", "#..", "###"), "3": ("###", "..#", "###", "..#", "###"),
    "4": ("#.#", "#.#", "###", "..#", "..#"), "5": ("###", "#..", "###", "..#", "###"),
    "6": ("###", "#..", "###", "#.#", "###"), "7": ("###", "..#", "..#", "..#", "..#"),
    "8": ("###", "#.#", "###", "#.#", "###"), "9": ("###", "#.#", "###", "..#", "###"),
    "x": ("...", "#.#", ".#.", "#.#", "..."), " ": ("...", "...", "...", "...", "..."),
}


def draw_text(screen: "Screen", text: str, x: int, y: int, scale: int, color: tuple[int, int, int], size: int = 1) -> None:
    for i, ch in enumerate(text):
        for row, line in enumerate(FONT.get(ch, FONT[" "])):
            for col, dot in enumerate(line):
                if dot == "#":
                    screen.box((x + i * 4 * size + col * size) * scale, (y + row * size) * scale, size * scale, size * scale, color)


# ── 板（g67〜g69 と同じ） ───────────────────────────────────────────────

class Screen:
    def __init__(self, width: int = WIDTH, height: int = HEIGHT):
        self.width, self.height = width, height
        self.rows = [bytearray(width * 3) for _ in range(height)]

    def band(self, top: int, bottom: int, color: tuple[int, int, int]) -> None:
        line = bytes(color) * self.width
        for y in range(max(0, top), min(self.height, bottom)):
            self.rows[y][:] = line

    def box(self, x0: int, y0: int, w: int, h: int, color: tuple[int, int, int]) -> None:
        paint = bytes(color)
        x0, x1 = max(0, x0), min(self.width, x0 + w)
        if x1 <= x0:
            return
        for y in range(max(0, y0), min(self.height, y0 + h)):
            self.rows[y][x0 * 3:x1 * 3] = paint * (x1 - x0)

    def ellipse(self, cx: float, cy: float, rx: float, ry: float, color: tuple[int, int, int]) -> None:
        for y in range(int(cy - ry), int(cy + ry) + 1):
            t = (y - cy) / ry
            if abs(t) > 1:
                continue
            half = rx * math.sqrt(1 - t * t)
            self.box(int(cx - half), y, int(2 * half) + 1, 1, color)

    def pixel(self, x: int, y: int) -> tuple[int, int, int]:
        return tuple(self.rows[y][x * 3:x * 3 + 3])

    def render(self) -> str:
        out = []
        for top, bottom in zip(self.rows[0::2], self.rows[1::2]):
            last = None
            for x in range(self.width):
                a, b = top[x * 3:x * 3 + 3], bottom[x * 3:x * 3 + 3]
                code = f"\x1b[38;2;{a[0]};{a[1]};{a[2]}m\x1b[48;2;{b[0]};{b[1]};{b[2]}m"
                if code != last:
                    out.append(code)
                    last = code
                out.append("▀")
            out.append("\x1b[0m\n")
        return "".join(out)


# ── 玉・盤・組 ──────────────────────────────────────────────────────────

@dataclass
class Blob:
    color: int
    uid: int


Grid = list[list[Blob | None]]                      # grid[行][列]。行 0 が一番下、行 TOP は見えない


def empty_grid() -> Grid:
    return [[None] * COLS for _ in range(ROWS + 1)]


def inside(col: int, row: int) -> bool:
    return 0 <= col < COLS and 0 <= row <= TOP


def find_groups(grid: Grid) -> list[list[tuple[int, int]]]:
    """同じ色が LINK 個以上つながっている組を全部返す（見える行だけ）。幅優先で集める。"""
    seen = set()
    groups = []
    for row in range(ROWS):
        for col in range(COLS):
            blob = grid[row][col]
            if blob is None or (col, row) in seen:
                continue
            group = []
            todo = deque([(col, row)])
            seen.add((col, row))
            while todo:
                c, r = todo.popleft()
                group.append((c, r))
                for dc, dr in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nc, nr = c + dc, r + dr
                    if 0 <= nc < COLS and 0 <= nr < ROWS and (nc, nr) not in seen:
                        other = grid[nr][nc]
                        if other is not None and other.color == blob.color:
                            seen.add((nc, nr))
                            todo.append((nc, nr))
            if len(group) >= LINK:
                groups.append(group)
    return groups


def apply_gravity(grid: Grid) -> list[tuple[int, int, int, int]]:
    """浮いている玉を下へ詰める。動いた玉の (uid, 列, 前の行, 後の行) を返す。"""
    moves = []
    for col in range(COLS):
        write = 0
        for row in range(ROWS + 1):
            blob = grid[row][col]
            if blob is None:
                continue
            if row != write:
                grid[write][col] = blob
                grid[row][col] = None
                moves.append((blob.uid, col, row, write))
            write += 1
    return moves


def score_for(groups: list[list[tuple[int, int]]], grid: Grid, chain: int) -> int:
    """消えた玉の数 × 10 × ボーナス（連鎖・色数・組の大きさ）。ボーナスは最低 1。"""
    count = sum(len(g) for g in groups)
    colors = len({grid[r][c].color for g in groups for c, r in g})
    bonus = CHAIN_BONUS[min(chain - 1, len(CHAIN_BONUS) - 1)] + COLOR_BONUS[min(colors - 1, len(COLOR_BONUS) - 1)]
    bonus += sum(GROUP_BONUS.get(min(len(g), 10), 10) for g in groups)
    return count * 10 * max(1, bonus)


def resolve(grid: Grid) -> tuple[int, int, int]:
    """盤を落ち着くまで進める（連鎖を全部）。(点, 連鎖数, 消えた数) を返す。自動プレイの評価に使う。"""
    apply_gravity(grid)
    score = chain = cleared = 0
    while True:
        groups = find_groups(grid)
        if not groups:
            return score, chain, cleared
        chain += 1
        score += score_for(groups, grid, chain)
        for group in groups:
            for col, row in group:
                grid[row][col] = None
                cleared += 1
        apply_gravity(grid)


def copy_grid(grid: Grid) -> Grid:
    return [row[:] for row in grid]


@dataclass
class Piece:
    """落ちてくる 2 個組。軸の玉と相方。相方は ROT[rot] の向きにいる。"""
    col: int
    row: int
    rot: int
    axis: Blob
    mate: Blob

    def cells(self, col: int | None = None, row: int | None = None, rot: int | None = None) -> tuple[tuple[int, int], tuple[int, int]]:
        col = self.col if col is None else col
        row = self.row if row is None else row
        rot = self.rot if rot is None else rot
        dc, dr = ROT[rot]
        return (col, row), (col + dc, row + dr)


class Phase(Enum):
    FALL = "fall"                                   # 組が落ちている
    SETTLE = "settle"                               # 浮いた玉が落ちる（見た目の時間）
    POP = "pop"                                     # 消える（見た目の時間）
    OVER = "over"


@dataclass
class Best:
    score: int = 0
    chain: int = 0
    stars: int = 0                                  # 達成したお題の数（最大）

    def dump(self) -> str:
        return json.dumps({"score": self.score, "chain": self.chain, "stars": self.stars})

    @classmethod
    def parse(cls, text: str) -> "Best":
        try:
            data = json.loads(text)
            return cls(int(data.get("score", 0)), int(data.get("chain", 0)), int(data.get("stars", 0)))
        except (ValueError, TypeError, AttributeError):
            return cls()

    def take(self, world: "World") -> bool:
        improved = world.score > self.score
        self.score = max(self.score, world.score)
        self.chain = max(self.chain, world.max_chain)
        self.stars = max(self.stars, world.stars)
        return improved


@dataclass
class World:
    seed: int = 0
    grid: Grid = field(default_factory=empty_grid)
    piece: Piece | None = None
    queue: list[tuple[int, int]] = field(default_factory=list)   # 次の組の色
    phase: Phase = Phase.FALL
    phase_left: float = 0.0                         # いまの段階の残り秒数
    time: float = 0.0
    started: bool = False
    over: bool = False
    score: int = 0
    chain: int = 0                                  # いま進んでいる連鎖の段
    max_chain: int = 0
    cleared: int = 0
    pieces: int = 0
    level: int = 1
    fall_left: float = DROP_START                   # 次に 1 段落ちるまで
    _soft: bool = False                             # ↓ を押している（soft で読み書き）
    lock_left: float = 0.0                          # 着地してから固まるまで
    moves: list[tuple[int, int, int, int]] = field(default_factory=list)   # SETTLE で落ちている玉
    pops: list[tuple[Blob, int, int]] = field(default_factory=list)        # POP で消えている玉 (玉, 列, 行)
    note: str = ""
    note_until: float = 0.0
    shake_until: float = 0.0
    shake_size: float = 0.0
    counter: int = 0
    fever_until: float = 0.0                        # フィーバーの終わり
    fevers: int = 0                                 # フィーバーが起きた回数
    all_clears: int = 0
    mission: int = 0                                # いまのお題の番号
    stars: int = 0                                  # 達成した数

    def __post_init__(self):
        self.luck = random.Random(self.seed)
        while len(self.queue) < QUEUE + 1:
            self.queue.append((self.luck.randrange(COLORS), self.luck.randrange(COLORS)))
        self.spawn()

    # ── 決まりごと ──
    def drop_time(self) -> float:
        return max(DROP_MIN, DROP_START - DROP_STEP * (self.level - 1))

    @property
    def fever(self) -> bool:
        return self.time < self.fever_until

    def mission_text(self) -> str:
        return MISSIONS[self.mission]["text"] if self.mission < len(MISSIONS) else "全部達成！"

    def check_mission(self) -> bool:
        """いまのお題を達成していれば星を付けて次へ（1 回に 1 つ）。"""
        if self.mission >= len(MISSIONS) or not MISSIONS[self.mission]["check"](self):
            return False
        self.stars += 1
        self.mission += 1
        self.score += MISSION_BONUS
        self.tell(f"★ お題達成 +{MISSION_BONUS}：" + ("次は " + self.mission_text() if self.mission < len(MISSIONS) else "全部達成！"), 2.5)
        return True

    def tell(self, text: str, seconds: float = 1.5) -> None:
        self.note, self.note_until = text, self.time + seconds

    def shake(self, size: float, seconds: float = 0.25) -> None:
        self.shake_size = max(self.shake_size if self.time < self.shake_until else 0.0, size)
        self.shake_until = self.time + seconds

    @property
    def soft(self) -> bool:
        return self._soft

    @soft.setter
    def soft(self, on: bool) -> None:
        """↓ を押した瞬間から速く落ちる（次の 1 段までの待ちを縮める）。"""
        self._soft = on
        if on:
            self.fall_left = min(self.fall_left, SOFT_DROP)

    def new_blob(self, color: int) -> Blob:
        self.counter += 1
        return Blob(color, self.counter)

    def free(self, col: int, row: int) -> bool:
        return inside(col, row) and self.grid[row][col] is None

    def fits(self, col: int, row: int, rot: int) -> bool:
        return all(self.free(c, r) for c, r in Piece(col, row, rot, None, None).cells())

    def spawn(self) -> None:
        """次の組を出す。出る場所がふさがっていたら終わり。"""
        c1, c2 = self.queue.pop(0)
        self.queue.append((self.luck.randrange(COLORS), self.luck.randrange(COLORS)))
        self.piece = Piece(SPAWN_COL, ROWS - 1, 0, self.new_blob(c1), self.new_blob(c2))
        self.phase = Phase.FALL
        self.fall_left = self.drop_time()
        self.lock_left = 0.0
        self.chain = 0
        if not self.fits(self.piece.col, self.piece.row, self.piece.rot):
            self.piece = None
            self.over = True
            self.phase = Phase.OVER
            self.tell("積み上がった…", 99)

    # ── 入力 ──
    def move(self, dx: int) -> str | None:
        p = self.piece
        if p is None or self.phase != Phase.FALL or not self.fits(p.col + dx, p.row, p.rot):
            return None
        p.col += dx
        return "move"

    def rotate(self, direction: int = 1) -> str | None:
        """回す。ぶつかるなら左右か上へずらして試す（壁蹴り）。どれも駄目なら回らない。"""
        p = self.piece
        if p is None or self.phase != Phase.FALL:
            return None
        rot = (p.rot + direction) % 4
        for dx, dy in ((0, 0), (-ROT[rot][0], 0), (1, 0), (-1, 0), (0, 1)):
            if self.fits(p.col + dx, p.row + dy, rot):
                p.col, p.row, p.rot = p.col + dx, p.row + dy, rot
                return "turn"
        return None

    def landing_row(self) -> int:
        """このまま落とすと軸が止まる行。"""
        p = self.piece
        row = p.row
        while self.fits(p.col, row - 1, p.rot):
            row -= 1
        return row

    def hard_drop(self) -> str | None:
        p = self.piece
        if p is None or self.phase != Phase.FALL:
            return None
        p.row = self.landing_row()
        return self.lock()

    # ── 進める ──
    def lock(self) -> str:
        """組を盤に固める。浮いた玉があれば SETTLE、無ければすぐ消える判定へ。"""
        p = self.piece
        for (c, r), blob in zip(p.cells(), (p.axis, p.mate)):
            self.grid[r][c] = blob
        self.piece = None
        self.pieces += 1
        self.begin_settle()
        return "land"

    def begin_settle(self) -> None:
        self.moves = apply_gravity(self.grid)
        if self.moves:
            self.phase = Phase.SETTLE
            self.phase_left = max(SETTLE_MIN, SETTLE_PER_ROW * max(a - b for _, _, a, b in self.moves))
        else:
            self.phase = Phase.SETTLE
            self.phase_left = 0.0

    def begin_pop(self) -> str | None:
        """消える組があれば POP へ（連鎖 +1）。無ければ次の組。"""
        groups = find_groups(self.grid)
        if not groups:
            happened = None
            if self.chain > 0 and all(cell is None for row in self.grid for cell in row):
                self.score += ALL_CLEAR
                self.all_clears += 1
                self.tell(f"全消し！ +{ALL_CLEAR}", 2.0)
                happened = "allclear"
            if self.check_mission():
                happened = "mission"
            self.spawn()
            return happened
        self.chain += 1
        self.max_chain = max(self.max_chain, self.chain)
        gained = score_for(groups, self.grid, self.chain) * (FEVER_SCALE if self.fever else 1)
        self.score += gained
        started_fever = False
        if self.chain >= FEVER_CHAIN:               # フィーバー：始まる、または延びる
            if not self.fever:
                self.fevers += 1
                started_fever = True
            self.fever_until = max(self.fever_until, self.time) + FEVER_TIME
        self.pops = [(self.grid[r][c], c, r) for g in groups for c, r in g]
        for blob, c, r in self.pops:
            self.grid[r][c] = None
        self.phase = Phase.POP
        self.phase_left = POP_TIME
        self.shake(0.5 + 0.5 * self.chain, 0.25)
        if started_fever:
            self.tell(f"{self.chain} 連鎖！ フィーバー！ 点 ×{FEVER_SCALE}", 2.0)
            return "fever"
        if self.chain >= 2:
            self.tell(f"{self.chain} 連鎖！ +{gained}" + ("（×2）" if self.fever else ""), 1.2)
        else:
            self.tell(f"+{gained}" + ("（×2）" if self.fever else ""), 0.8)
        return f"pop{min(self.chain, len(POPS))}"

    def update(self, dt: float) -> str | None:
        if not self.started or self.over:
            return None
        self.time += dt
        happened = None
        if self.phase == Phase.FALL:
            p = self.piece
            if self.fits(p.col, p.row - 1, p.rot):
                self.lock_left = 0.0
                self.fall_left -= dt
                if self.fall_left <= 0:
                    p.row -= 1
                    self.fall_left = SOFT_DROP if self.soft else self.drop_time()
            else:                                   # 着地：少しだけ動かせる猶予
                self.lock_left += dt
                if self.lock_left >= LOCK_DELAY or self.soft:
                    happened = self.lock()
        elif self.phase == Phase.SETTLE:
            self.phase_left -= dt
            if self.phase_left <= 0:
                self.moves = []
                happened = self.begin_pop()
        elif self.phase == Phase.POP:
            self.phase_left -= dt
            if self.phase_left <= 0:
                self.cleared += len(self.pops)
                self.pops = []
                level = 1 + self.cleared // LEVEL_EVERY
                if level > self.level:
                    self.level = level
                    self.tell(f"レベル {level}", 1.5)
                    happened = "level"
                self.begin_settle()
        if self.phase == Phase.FALL and self.time >= self.note_until and self.check_mission():   # レベルや点のお題は落ちている間にも
            happened = "mission"
        if self.over:
            return "end"
        return happened


# ── 描く（端末） ────────────────────────────────────────────────────────

def cell_xy(col: int, row: float) -> tuple[float, float]:
    """列と行（小数でもよい）→ 板のマスの左上（ドット）。行 0 が一番下。"""
    return BOARD_X + col * CELL, BOARD_Y + (ROWS - 1 - row) * CELL


def draw_blob(screen: Screen, x: float, y: float, color: int, scale: int, size: float = 1.0, dim: float = 1.0) -> None:
    rgb = shade(PALETTE[color]["rgb"], dim)
    r = CELL / 2 * 0.9 * size * scale
    cx, cy = (x + CELL / 2) * scale, (y + CELL / 2) * scale
    screen.ellipse(cx, cy, r, r, shade(rgb, 0.6))
    screen.ellipse(cx, cy, r * 0.85, r * 0.85, rgb)
    screen.ellipse(cx - r * 0.3, cy - r * 0.3, r * 0.3, r * 0.25, shade(rgb, 1.5))


def draw(screen: Screen, world: World) -> None:
    scale = screen.width // WIDTH
    screen.band(0, screen.height, BACK)
    ox = oy = 0.0
    if world.time < world.shake_until:
        k = world.shake_size * (world.shake_until - world.time) / 0.25
        ox, oy = math.sin(world.time * 90) * k, math.cos(world.time * 70) * k * 0.6
    if world.fever:                                                 # フィーバー：背景が脈打つ
        k = 0.5 + 0.5 * math.sin(world.time * 6)
        screen.band(0, screen.height, (int(40 + 30 * k), int(20 + 10 * k), int(60 + 30 * k)))
    bx, by = (BOARD_X + ox) * scale, (BOARD_Y + oy) * scale
    screen.box(int(bx - scale), int(by - scale), (COLS * CELL + 2) * scale, (ROWS * CELL + 2) * scale, FRAME if not world.fever else (255, 200, 90))
    screen.box(int(bx), int(by), COLS * CELL * scale, ROWS * CELL * scale, BOARD)
    for c in range(1, COLS):
        screen.box(int(bx + c * CELL * scale), int(by), 1, ROWS * CELL * scale, BOARD_LINE)
    for r in range(1, ROWS):
        screen.box(int(bx), int(by + r * CELL * scale), COLS * CELL * scale, 1, BOARD_LINE)
    moving = {uid: (col, a, b) for uid, col, a, b in world.moves}
    t = 1.0 - world.phase_left / max(1e-9, max(SETTLE_MIN, SETTLE_PER_ROW * max([a - b for _, _, a, b in world.moves] or [1])))
    ease = 1 - (1 - min(1.0, max(0.0, t))) ** 2
    for row in range(ROWS):
        for col in range(COLS):
            blob = world.grid[row][col]
            if blob is None:
                continue
            show_row = row
            if blob.uid in moving:
                _, a, b = moving[blob.uid]
                show_row = a + (b - a) * ease
            x, y = cell_xy(col, show_row)
            draw_blob(screen, x + ox, y + oy, blob.color, scale)
            right = world.grid[row][col + 1] if col + 1 < COLS else None      # 同じ色の隣とつなぐ
            if right is not None and right.color == blob.color and blob.uid not in moving and right.uid not in moving:
                screen.box(int((x + ox + CELL * 0.6) * scale), int((y + oy + CELL * 0.35) * scale), int(CELL * 0.8 * scale), int(CELL * 0.3 * scale), PALETTE[blob.color]["rgb"])
            up = world.grid[row + 1][col] if row + 1 < ROWS else None
            if up is not None and up.color == blob.color and blob.uid not in moving and up.uid not in moving:
                screen.box(int((x + ox + CELL * 0.35) * scale), int((y + oy - CELL * 0.4) * scale), int(CELL * 0.3 * scale), int(CELL * 0.8 * scale), PALETTE[blob.color]["rgb"])
    if world.pops:                                                  # 消えている玉：縮む
        k = max(0.0, world.phase_left / POP_TIME)
        for blob, c, r in world.pops:
            x, y = cell_xy(c, r)
            draw_blob(screen, x + ox, y + oy, blob.color, scale, size=k, dim=1.0 + (1 - k))
    p = world.piece
    if p is not None and world.phase == Phase.FALL:
        land = world.landing_row()
        for (c, r), blob in zip(p.cells(p.row if False else p.col, land), (p.axis, p.mate)):   # 影（落ちる先）
            if r < ROWS:
                x, y = cell_xy(c, r)
                screen.ellipse((x + ox + CELL / 2) * scale, (y + oy + CELL / 2) * scale, CELL * 0.35 * scale, CELL * 0.35 * scale, GHOST)
        for (c, r), blob in zip(p.cells(), (p.axis, p.mate)):
            if r < ROWS:
                x, y = cell_xy(c, r)
                draw_blob(screen, x + ox, y + oy, blob.color, scale)
    screen.box(int(bx), int(by - scale), COLS * CELL * scale, scale, BACK)   # 見えない行との境目
    nx = NEXT_X * scale                                             # 次の玉
    for i, (c1, c2) in enumerate(world.queue[:QUEUE]):
        ny = (BOARD_Y + 2 + i * 16) * scale
        screen.box(nx - scale, ny - scale, (CELL + 2) * scale, (CELL * 2 + 2) * scale, FRAME)
        screen.box(nx, ny, CELL * scale, CELL * 2 * scale, BOARD)
        draw_blob(screen, NEXT_X, BOARD_Y + 2 + i * 16, c2, scale)
        draw_blob(screen, NEXT_X, BOARD_Y + 2 + i * 16 + CELL, c1, scale)
    draw_text(screen, str(world.level), 8, 6, scale, INK, 2)      # レベル（左）
    if world.chain >= 2 or (world.time < world.note_until and world.max_chain >= 2 and world.note.endswith("！") is False):
        pass
    chain = world.chain if world.phase == Phase.POP else 0
    if chain >= 2:
        draw_text(screen, f"{chain}x", 8, 40, scale, SPARK, 2)


# ── 端末 ────────────────────────────────────────────────────────────────

def read_keys(fd: int) -> list[str]:
    keys = []
    while select.select([fd], [], [], 0)[0]:
        text = os.read(fd, 64).decode(errors="ignore")
        i = 0
        while i < len(text):
            ch = text[i]
            if ch == "\x1b" and text[i + 1:i + 2] == "[":
                keys.append({"A": "rotate", "B": "down", "C": "right", "D": "left"}.get(text[i + 2:i + 3], ""))
                i += 3
                continue
            if ch in ("a", "j"):
                keys.append("left")
            elif ch in ("d", "l"):
                keys.append("right")
            elif ch in ("w", "i", "x"):
                keys.append("rotate")
            elif ch == "z":
                keys.append("rotate_back")
            elif ch in ("s", "k"):
                keys.append("down")
            elif ch in (" ", "\r", "\n"):
                keys.append("go")
            elif ch in ("q", "\x1b"):
                keys.append("quit")
            i += 1
    return [k for k in keys if k]


def obey(world: World, key: str) -> str | None:
    """キーを 1 つ受ける。go は始める／一気に落とす。"""
    if key == "go":
        if not world.started:
            world.started = True
            return None
        return world.hard_drop()
    if key == "left":
        return world.move(-1)
    if key == "right":
        return world.move(1)
    if key == "rotate":
        return world.rotate(1)
    if key == "rotate_back":
        return world.rotate(-1)
    if key == "down":                               # 端末は押しっぱなしが取れないので 1 段ずつ
        p = world.piece
        if p is not None and world.phase == Phase.FALL:
            if world.fits(p.col, p.row - 1, p.rot):
                p.row -= 1
                world.fall_left = world.drop_time()
            else:
                return world.lock()
    return None


class Speaker:
    def __init__(self):
        import shutil
        import tempfile

        self.player = shutil.which("afplay") or shutil.which("aplay")
        self.folder = tempfile.mkdtemp(prefix="chain-")
        self.paths = {}
        for kind in SOUNDS:
            path = os.path.join(self.folder, f"{kind}.wav")
            with open(path, "wb") as out:
                out.write(sound_bytes(kind))
            self.paths[kind] = path

    def say(self, kind: str | None) -> None:
        import subprocess

        if kind is None or self.player is None:
            return
        subprocess.Popen([self.player, self.paths[kind]], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def close(self) -> None:
        import shutil

        shutil.rmtree(self.folder, ignore_errors=True)


RECORDS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "records.json")


def load_best() -> Best:
    try:
        with open(RECORDS, encoding="utf-8") as src:
            return Best.parse(src.read())
    except OSError:
        return Best()


def save_best(best: Best) -> None:
    with open(RECORDS, "w", encoding="utf-8") as out:
        out.write(best.dump())


def columns(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def status(world: World, best: Best, improved: bool = False) -> str:
    note = world.note if world.time < world.note_until else ""
    if not world.started:
        note, tail = "スペースで始める", "← → 移動 ↑ 回転 ↓ 1 段 スペース 一気に q やめる"
    elif world.over:
        note = "積み上がった" + (" ベスト更新！" if improved else "")
        tail = "スペースでもう一度"
    else:
        tail = f"★{world.stars} お題: {world.mission_text()}" + ("  フィーバー！" if world.fever else "")
    head = f" レベル {world.level} 点 {world.score:6d} 消した {world.cleared:3d} 最大 {world.max_chain} 連鎖 組 {world.pieces:3d} "
    room = WIDTH - columns(head) - columns(tail) - 1
    while columns(note) > room:
        note = note[:-1]
    return head + note + " " * (room - columns(note) + 1) + tail


def run() -> None:
    import termios
    import tty

    world = World(seed=int(time.time()))
    best = load_best()
    improved = False
    screen = Screen()
    speaker = Speaker()
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        sys.stdout.write("\x1b[2J\x1b[?25l")
        last = time.perf_counter()
        lag = 0.0
        while True:
            now = time.perf_counter()
            for key in read_keys(fd):
                if key == "quit":
                    return
                if key == "go" and world.over:
                    world = World(seed=int(time.time()))
                    world.started = True
                    improved = False
                else:
                    speaker.say(obey(world, key))
            lag = min(lag + now - last, 0.25)
            last = now
            while lag >= STEP:
                event = world.update(STEP)
                if event == "end":
                    improved = best.take(world)
                    save_best(best)
                    event = "best" if improved else event
                speaker.say(event)
                lag -= STEP
            draw(screen, world)
            sys.stdout.write("\x1b[H" + screen.render() + status(world, best, improved) + "\x1b[K")
            sys.stdout.flush()
            time.sleep(max(0.0, STEP - (time.perf_counter() - now)))
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
        sys.stdout.write("\x1b[?25h\x1b[2J\x1b[H")
        speaker.close()


# ── 自動で遊ぶ（検査とブラウザの自動プレイ） ────────────────────────────

def choose(world: World) -> tuple[int, int] | None:
    """全部の置き方（列 × 回転）を試し、点が高く・山が低く・同じ色が隣り合う置き方を選ぶ。"""
    p = world.piece
    if p is None:
        return None
    best_key, best_move = None, None
    for rot in range(4):
        for col in range(COLS):
            if not world.fits(col, ROWS - 1, rot) and not world.fits(col, ROWS, rot):
                continue
            row = ROWS - 1
            if not world.fits(col, row, rot):
                continue
            while world.fits(col, row - 1, rot):
                row -= 1
            grid = copy_grid(world.grid)
            for (c, r), blob in zip(Piece(col, row, rot, None, None).cells(), (p.axis, p.mate)):
                grid[r][c] = blob
            score, chain, cleared = resolve(grid)
            heights = [next((ROWS - r for r in range(ROWS) if grid[r][c] is not None), 0) for c in range(COLS)]
            height = max(heights)
            same = 0                                # 置いた玉の隣に同じ色があるか（連鎖の種）
            for (c, r), blob in zip(Piece(col, row, rot, None, None).cells(), (p.axis, p.mate)):
                for dc, dr in ((1, 0), (-1, 0), (0, -1)):
                    nc, nr = c + dc, r + dr
                    if inside(nc, nr) and world.grid[nr][nc] is not None and world.grid[nr][nc].color == blob.color:
                        same += 1
            placed = max(r for (c, r) in Piece(col, row, rot, None, None).cells())   # 置いた組の一番上の行
            bumpy = sum(abs(a - b) for a, b in zip(heights, heights[1:]))           # でこぼこ
            danger = 400 if heights[SPAWN_COL] >= ROWS - 3 else 0
            key = (score * (1 if height < ROWS - 4 else 3) + same * 12 - placed * placed * 2 - height * 4 - bumpy * 2 - danger, -rot)
            if best_key is None or key > best_key:
                best_key, best_move = key, (col, rot)
    return best_move


def autopilot(world: World) -> None:
    """選んだ置き方へ動かし、一気に落とす。"""
    if world.phase != Phase.FALL or world.piece is None:
        return
    target = choose(world)
    if target is None:
        return
    col, rot = target
    p = world.piece
    for _ in range(4):
        if p.rot == rot:
            break
        world.rotate(1)
    if p.col != col:
        world.move(1 if col > p.col else -1)
        return
    if p.rot == rot:
        world.hard_drop()


def play_out(world: World, limit: float = 600.0) -> dict[str, int]:
    counts = {k: 0 for k in EVENTS}
    world.started = True
    while not world.over and world.time < limit:
        autopilot(world)
        got = world.update(STEP)
        if got:
            counts[got] += 1
    return counts


def until(world: World, frames: int = 60) -> str | None:
    for _ in range(frames):
        got = world.update(STEP)
        if got:
            return got
    return None


def fill(grid: Grid, rows: list[str]) -> None:
    """検査用：文字で盤を作る。上の行から書く。. は空き、0〜4 が色。"""
    uid = 1000
    for i, line in enumerate(rows):
        row = len(rows) - 1 - i
        for col, ch in enumerate(line):
            if ch != ".":
                uid += 1
                grid[row][col] = Blob(int(ch), uid)


def check() -> None:
    print("● 盤とつながり")
    grid = empty_grid()
    fill(grid, ["....1.",
                "0001..",
                "0012..",
                "22221."])
    groups = find_groups(grid)
    assert len(groups) == 2 and sorted(len(g) for g in groups) == [5, 5], [len(g) for g in groups]
    assert grid[0][4].color == 1 and all((4, 0) not in g for g in groups), "1 は 4 つあっても斜めはつながらない"
    grid = empty_grid()
    fill(grid, ["0.....",
                "......",
                "1....."])
    moves = apply_gravity(grid)
    assert moves == [(1001, 0, 2, 1)] and grid[1][0].color == 0 and grid[2][0] is None, moves
    print("  同じ色 4 つ以上が組（幅優先）。浮いた玉は落ちて (uid, 列, 前, 後) が返る")

    print("● 点")
    grid = empty_grid()
    fill(grid, ["0000.."])
    assert score_for(find_groups(grid), grid, 1) == 40, "4 つ 1 連鎖は 40"
    grid = empty_grid()
    fill(grid, ["00000."])
    assert score_for(find_groups(grid), grid, 1) == 50 * 2, "5 つは組のボーナス 2"
    grid = empty_grid()
    fill(grid, ["0000..", "1111.."])
    assert score_for(find_groups(grid), grid, 2) == 80 * (8 + 3), "2 連鎖で 2 色"
    grid = empty_grid()
    fill(grid, ["...0..",
                "...0..",
                "...1..",
                "...1..",
                "...1..",
                "0001.."])
    score, chain, cleared = resolve(grid)
    assert chain == 2 and cleared == 9 and score == 40 + 50 * (8 + 2), (score, chain, cleared)
    assert all(cell is None for row in grid for cell in row), "全部消える"
    print("  消した数 × 10 × ボーナス（連鎖 0/8/16/32…、色 0/3/6…、組の大きさ）。resolve は 1 が消えて 0 が落ちる 2 連鎖で 540")

    print("● 組の動き")
    world = World(seed=1)
    world.started = True
    p = world.piece
    assert p.col == SPAWN_COL and p.row == ROWS - 1 and p.rot == 0 and p.cells()[1] == (SPAWN_COL, ROWS)
    assert world.move(-1) == "move" and world.move(-1) == "move" and world.move(-1) is None, "左の壁"
    assert p.col == 0
    assert world.rotate(1) == "turn" and p.rot == 1
    assert world.rotate(1) == "turn" and p.rot == 2 and world.rotate(1) == "turn" and p.rot == 3 and p.col == 1, "左端で左向きは壁蹴りで右へ"
    world.rotate(1)
    assert p.rot == 0 and p.col == 1
    row0 = p.row
    for _ in range(int(DROP_START / STEP) + 2):
        world.update(STEP)
    assert p.row == row0 - 1, "時間で 1 段落ちる"
    world.soft = True
    for _ in range(4):
        world.update(STEP)
    assert p.row <= row0 - 2, "↓ で速く"
    world.soft = False
    land = world.landing_row()
    assert land == 0
    assert world.hard_drop() == "land" and world.piece is None and world.grid[0][1] is not None and world.grid[1][1] is not None
    assert world.phase == Phase.SETTLE and world.pieces == 1
    got = until(world)
    assert got is None and world.piece is not None and world.phase == Phase.FALL, "消えなければ次の組"
    world = World(seed=1)
    world.started = True
    fill(world.grid, ["......",
                      "..0...",
                      "..0...",
                      "..0..."])
    world.piece = Piece(1, 6, 1, world.new_blob(0), world.new_blob(3))     # 横向き：相方が柱の上に乗る
    world.hard_drop()
    assert world.grid[0][1] is not None and world.grid[3][2].color == 3 and world.grid[3][2] is not None, "軸は床、相方は柱の上に"
    assert world.moves == [] or all(a > b for _, _, a, b in world.moves)
    print("  出る場所は列 2 の一番上、壁蹴り、時間と ↓ で落ち、一気に落とすと固まる。横向きは別々の高さに着く")

    print("● 連鎖の状態機械")
    world = World(seed=1)
    world.started = True
    fill(world.grid, ["..0...",
                      "..0...",
                      "0011.."])
    world.piece = Piece(3, 6, 2, world.new_blob(1), world.new_blob(1))     # 縦 2 つの 1 を列 3 に落とすと… 1 が 4 つで消え、0 が落ちて 4 つ
    events = []
    world.hard_drop()
    for _ in range(120):
        got = world.update(STEP)
        if got:
            events.append(got)
        if world.phase == Phase.FALL and world.piece is not None:
            break
    assert events[:2] == ["pop1", "pop2"] and world.max_chain == 2 and world.chain == 0, events
    assert world.cleared == 8 and world.score == 40 + 40 * 8 + ALL_CLEAR + MISSION_BONUS, (world.cleared, world.score)   # お題「2 連鎖」も達成
    assert "mission" in events and world.all_clears == 1, "全消しと同時にお題も達成（お題の音が勝つ）"
    print("  FALL → SETTLE → POP（連鎖 1）→ SETTLE → POP（連鎖 2）→ SETTLE → 全消し +1000 → 次の組")

    print("● フィーバーとお題")
    world = World(seed=1)
    world.started = True
    fill(world.grid, ["..0...",
                      "..0...",
                      "..3...",
                      "..3...",
                      "0011..",
                      "3311.."])
    world.piece = Piece(3, 6, 2, world.new_blob(1), world.new_blob(1))     # 1 が消え → 0 が落ちて消え → 3 が落ちて消える 3 連鎖
    world.hard_drop()
    events = []
    for _ in range(200):
        got = world.update(STEP)
        if got:
            events.append(got)
        if world.phase == Phase.FALL and world.piece is not None:
            break
    assert events[:3] == ["pop1", "pop2", "fever"] and world.fever and world.fevers == 1, events
    assert world.score == 60 * 3 + 40 * 8 + 40 * 16 + ALL_CLEAR + MISSION_BONUS, world.score   # 1 が 6 つ、3 が 4 つ、0 が 4 つ。×2 は次の消しから。全消し、お題「2 連鎖」
    assert world.stars == 1 and world.mission == 1 and "mission" in events, (world.stars, events)
    assert world.max_chain == 3 and events.count("mission") == 1, "お題は 1 回に 1 つ（3 連鎖はまだ）"
    world.time = world.fever_until + 0.01
    assert not world.fever
    world.tell("", 0)
    world.update(STEP)
    assert world.stars == 1 and world.mission_text() == "30 個消す", "3 連鎖はもう出ているが、お題は順番どおり（まだ 14 個）"
    world.cleared = 30
    world.update(STEP)                              # 30 個 → ★2
    world.tell("", 0)
    world.update(STEP)                              # 3 連鎖はもう出ている → ★3
    assert world.stars == 3 and world.mission_text() == "点を 3000 にする", (world.stars, world.mission_text())
    assert all(m["check"](World(seed=9)) is False for m in MISSIONS), "始めは全部未達成"
    best = Best.parse(Best(1, 2, 3).dump())
    assert best.stars == 3
    print(f"  {FEVER_CHAIN} 連鎖でフィーバー {FEVER_TIME:.0f} 秒（点 ×{FEVER_SCALE}、連鎖で延びる）。お題 {len(MISSIONS)} 個を順に、達成で ★ と +{MISSION_BONUS}")

    print("● レベルと終わり")
    world = World(seed=1)
    assert abs(world.drop_time() - DROP_START) < 1e-9
    world.level = 20
    assert world.drop_time() == DROP_MIN
    world = World(seed=1)
    world.started = True
    fill(world.grid, ["..0..."] * ROWS)
    world.spawn()
    assert world.over and world.piece is None, "出る場所がふさがると終わり"
    fill(world.grid, [])
    print(f"  {LEVEL_EVERY} 個消すごとにレベル +1、1 段 {DROP_START} → {DROP_MIN} 秒。列 {SPAWN_COL} の一番上がふさがると終わり")

    print("● 自動で遊ぶ")
    stats = []
    for seed in (2, 3, 4):
        world = World(seed=seed)
        counts = play_out(world, limit=1200)
        stats.append((world.pieces, world.score, world.max_chain, world.level, world.over))
    assert all(s[0] > 40 for s in stats) and max(s[2] for s in stats) >= 2, stats
    print("  " + "、".join(f"種 {seed}: {p} 組・{sc} 点・最大 {ch} 連鎖・レベル {lv}{'・終了' if ov else ''}" for seed, (p, sc, ch, lv, ov) in zip((2, 3, 4), stats)))
    a, b = World(seed=5), World(seed=5)
    assert a.queue == b.queue and a.piece.axis.color == b.piece.axis.color, "同じ種は同じ順"

    print("● 板の大きさ")
    world = World(seed=2)
    play_out(world, limit=30)
    small, big = Screen(), Screen(WIDTH * 4, HEIGHT * 4)
    started = time.perf_counter()
    draw(small, world)
    took_small = time.perf_counter() - started
    started = time.perf_counter()
    draw(big, world)
    took_big = time.perf_counter() - started
    print(f"  {WIDTH}×{HEIGHT} を描くのに {took_small * 1000:.1f} ms、{WIDTH * 4}×{HEIGHT * 4} は {took_big * 1000:.1f} ms")
    assert took_small < 0.02

    print("● 記録と音と状態行")
    best = Best.parse(Best(120, 3).dump())
    assert (best.score, best.chain) == (120, 3) and Best.parse("xx").score == 0
    assert len({sound_bytes(k) for k in SOUNDS}) == len(SOUNDS)
    world = World(seed=1)
    for started, over in ((False, False), (True, False), (True, True)):
        world.started, world.over = started, over
        world.tell("5 連鎖！ +12345（×2）", 9)
        world.fever_until = 99
        world.mission = 8
        assert columns(status(world, best, True)) == WIDTH, columns(status(world, best, True))
    print(f"  ベストは点と最大連鎖。音は {len(SOUNDS)} つ全部別（連鎖ごとに高く）。状態行は {WIDTH} 桁ちょうど")
    print("\nぜんぶ通った。")


def png_bytes(screen: Screen, scale: int = 1) -> bytes:
    import struct
    import zlib

    rows = b""
    for row in screen.rows:
        line = b"\x00" + b"".join(bytes(row[x * 3:x * 3 + 3]) * scale for x in range(screen.width))
        rows += line * scale

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", screen.width * scale, screen.height * scale, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def sheet(path: str) -> None:
    world = World(seed=5)
    play_out(world, limit=40.0)
    screen = Screen(WIDTH * 5, HEIGHT * 5)
    draw(screen, world)
    with open(path, "wb") as out:
        out.write(png_bytes(screen, 1))
    print(f"{path} に書き出した")


def main() -> None:
    if "--check" in sys.argv:
        check()
    elif "--sheet" in sys.argv:
        sheet(sys.argv[sys.argv.index("--sheet") + 1] if len(sys.argv) > 2 else "scene.png")
    else:
        run()


if __name__ == "__main__":
    main()
