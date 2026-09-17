"""ぶよぶよ ブラウザ版

CLI 版（g69-chain-drop/main.py）と中身はまったく同じ。盤（grid）、つながりの探索（find_groups）、落下（apply_gravity）、
点（score_for）、連鎖の状態機械（World.update）、自動プレイ（choose）は 1 文字も変えていない。

違うのは出口と入口だけ。端末は ▀ の 2D、ここでは同じ盤の玉を Three.js の球に写し、光・つや・消える粒は GPU に任せる。
入口は左右スワイプ（移動）・タップ（回転）・下スワイプ（一気に落とす）・キー。
"""

import asyncio
import base64
import io
import json
import math
import random
import wave
from array import array
from collections import deque
from dataclasses import dataclass, field
from enum import Enum

from pyodide.ffi import create_proxy, to_js
from pyscript import document, when, window


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


THEMES = (
    dict(name="夜", until=3, top=(34, 30, 70), bottom=(10, 10, 24), glow=(90, 110, 220), back=(18, 18, 34)),
    dict(name="夕焼け", until=6, top=(120, 50, 70), bottom=(30, 12, 40), glow=(255, 150, 80), back=(40, 20, 34)),
    dict(name="深海", until=9, top=(10, 50, 80), bottom=(4, 12, 30), glow=(60, 200, 220), back=(8, 24, 40)),
    dict(name="星雲", until=12, top=(70, 30, 110), bottom=(16, 8, 40), glow=(200, 120, 255), back=(28, 14, 44)),
    dict(name="黎明", until=999, top=(200, 150, 110), bottom=(60, 40, 70), glow=(255, 220, 160), back=(50, 36, 44)),
)


def theme_for(level: int) -> dict:
    """レベル → 場所。until 以下のレベルはその場所。"""
    for theme in THEMES:
        if level <= theme["until"]:
            return theme
    return THEMES[-1]


SLOW_CHAIN = 3                                      # この連鎖から、消える瞬間がスローモーション


SLOW_SCALE = 0.2                                    # スローの速さ（時間の進みの倍率）


SLOW_PART = 0.5                                     # POP のうち前半だけスロー


FEVER_CHAIN = 3                                     # この連鎖でフィーバーが始まる


FEVER_TIME = 12.0                                   # フィーバーの秒数（連鎖でさらに延びる）


FEVER_SCALE = 2                                     # フィーバー中の点の倍率


MISSION_BONUS = 500                                 # お題を達成した点


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


PALETTE = (
    dict(name="赤", rgb=(230, 70, 80)),
    dict(name="緑", rgb=(70, 200, 110)),
    dict(name="青", rgb=(70, 130, 240)),
    dict(name="黄", rgb=(240, 200, 60)),
    dict(name="紫", rgb=(180, 90, 230)),
)


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


BACK = (18, 18, 34)


BOARD = (30, 30, 52)


BOARD_LINE = (44, 44, 72)


FRAME = (110, 115, 150)


GHOST = (70, 70, 100)


INK = (200, 205, 230)


SPARK = (255, 230, 150)


def shade(color: tuple[int, int, int], k: float) -> tuple[int, int, int]:
    return tuple(max(0, min(255, int(c * k))) for c in color)


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
    impact: tuple[int, int, float] = (0, 0, -9.0)   # 最後に組が固まった (列, 行, 時刻)。着地の波に使う

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

    def time_scale(self) -> float:
        """時間の進みの倍率。深い連鎖の消える瞬間だけスロー（端末もブラウザも update に渡す dt にかける）。"""
        if self.phase == Phase.POP and self.chain >= SLOW_CHAIN and self.phase_left > POP_TIME * (1 - SLOW_PART):
            return SLOW_SCALE
        return 1.0

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
        self.impact = (p.col, min(r for _, r in p.cells()), self.time)
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
# --- ここから下はブラウザ版だけ。CLI 版の draw() / run() / Speaker / status() にあたる ---
#   端末の draw() が「マスの座標に丸を描く」ところを、ここでは「玉の uid ごとに球を 1 つ持ち、位置を写す」。
#   玉は消えるまで同じ uid なので、落ちても球は作り直さず動かすだけ。

THREE = window.THREE
ADDONS = window.ADDONS                              # 後処理（ブルーム）と部屋の環境（映り込み）。index.html で読み込む
VIEW_W, VIEW_H = 420, 600


def js(**kw):
    return to_js(kw, dict_converter=window.Object.fromEntries)


def rgb(color: tuple[int, int, int]) -> int:
    r, g, b = color
    return (r << 16) | (g << 8) | b


canvas = document.querySelector("#screen")
level_label = document.querySelector("#level")
mission_label = document.querySelector("#mission")
stars_label = document.querySelector("#stars")
score_label = document.querySelector("#score")
chain_label = document.querySelector("#chain")
cleared_label = document.querySelector("#cleared")
pieces_label = document.querySelector("#pieces")
best_label = document.querySelector("#best")
fps_label = document.querySelector("#fps")
note_label = document.querySelector("#note")
message = document.querySelector("#message")
again_button = document.querySelector("#again")
go_button = document.querySelector("#go")
SAVED = "g69-best"

# ── Three.js の舞台 ──────────────────────────────────────────────────────

renderer = THREE.WebGLRenderer.new(js(canvas=canvas, antialias=True))
PIXEL_RATIO = min(2.0, window.devicePixelRatio)
renderer.setPixelRatio(PIXEL_RATIO)
renderer.setSize(VIEW_W, VIEW_H, False)
renderer.toneMapping = THREE.ACESFilmicToneMapping   # 明るい所を白飛びさせず、フィルムのように丸める
renderer.toneMappingExposure = 1.0
renderer.shadowMap.enabled = True                   # 影（3 回目の直し）
renderer.shadowMap.type = THREE.PCFSoftShadowMap
scene = THREE.Scene.new()
scene.background = THREE.Color.new(rgb(BACK))
scene.fog = THREE.FogExp2.new(rgb(BACK), 0.012)     # 奥ほど霞む（背景の板と光の柱が奥に感じられる）
pmrem = THREE.PMREMGenerator.new(renderer)          # 「部屋」を映り込みの環境に。球のつやが本物のガラス玉になる
scene.environment = pmrem.fromScene(ADDONS.RoomEnvironment.new(), 0.04).texture
camera = THREE.PerspectiveCamera.new(40, VIEW_W / VIEW_H, 0.5, 100)
CAM = (0.6, 0.6, 21.0)                              # 少し右上から盤を見る（基本の位置）
camera.position.set(*CAM)
camera.lookAt(0.0, 0.0, 0.0)
# カメラは「いま」と「行きたい所」を持ち、毎コマ少しずつ近づく（寄る・引く・沈む・回る）
cam = {"x": CAM[0], "y": CAM[1], "z": CAM[2], "look_x": 0.0, "look_y": 0.0, "spin": 0.0,
       "focus": None, "focus_until": -9.0, "pull_until": -9.0, "dip_at": -9.0, "spin_at": -9.0, "fevers": 0, "pieces": 0}
CAM_EASE = 0.12

key_light = THREE.DirectionalLight.new(0xffffff, 1.8)   # 主光：ゆっくり動いて影が流れる
key_light.position.set(5, 10, 12)
key_light.castShadow = True
key_light.shadow.mapSize.set(1024, 1024)
for name, value in (("left", -9), ("right", 9), ("top", 10), ("bottom", -10), ("near", 1), ("far", 40)):
    setattr(key_light.shadow.camera, name, value)
key_light.shadow.bias = -0.0005
scene.add(key_light)
fill_light = THREE.DirectionalLight.new(0x8fa8ff, 0.8)
fill_light.position.set(-8, -4, 8)
scene.add(fill_light)
ambient = THREE.AmbientLight.new(0x404060, 0.5)
scene.add(ambient)
glint = THREE.PointLight.new(0xffffff, 18.0, 30.0)  # 玉のつやを作る近くの光
glint.position.set(-3, 6, 6)
scene.add(glint)
spot = THREE.SpotLight.new(0xffd080, 0.0, 40.0, 0.5, 0.6)   # フィーバー中に盤を舐めるスポットライト
spot.position.set(0, 12, 10)
scene.add(spot)
scene.add(spot.target)

# 後処理：描いた絵の明るい所だけをにじませて重ねる（ブルーム）。連鎖とフィーバーで強くする
composer = ADDONS.EffectComposer.new(renderer)
composer.setPixelRatio(PIXEL_RATIO)
composer.setSize(VIEW_W, VIEW_H)
composer.addPass(ADDONS.RenderPass.new(scene, camera))
bloom = ADDONS.UnrealBloomPass.new(THREE.Vector2.new(VIEW_W, VIEW_H), 0.35, 0.5, 0.85)   # 強さ・広がり・しきい値
composer.addPass(bloom)
composer.addPass(ADDONS.OutputPass.new())
BLOOM_BASE = 0.35


def cell_pos(col: float, row: float) -> tuple[float, float]:
    """列と行 → 舞台の x, y。盤の中央が (0, 0)。"""
    return col - (COLS - 1) / 2, row - (ROWS - 1) / 2


def linear(c: int) -> float:
    """sRGB の 0〜255 → 頂点色に入れる線形の値。そのまま入れると明るく飛ぶ。"""
    return (c / 255) ** 2.2


def gradient_plane(w: float, h: float, top: tuple[int, int, int], bottom: tuple[int, int, int]) -> object:
    """上下で色が変わる板（頂点の色）。背景に使う。"""
    geo = THREE.PlaneGeometry.new(w, h)
    colors = []
    for color in (top, top, bottom, bottom):        # PlaneGeometry の頂点は 左上・右上・左下・右下
        colors += [linear(c) for c in color]
    geo.setAttribute("color", THREE.Float32BufferAttribute.new(to_js(colors), 3))
    return THREE.Mesh.new(geo, THREE.MeshBasicMaterial.new(js(vertexColors=True)))


backdrop = gradient_plane(60, 80, THEMES[0]["top"], THEMES[0]["bottom"])
backdrop.position.set(0, 0, -8)
scene.add(backdrop)


def paint_backdrop(top: tuple[int, int, int], bottom: tuple[int, int, int]) -> None:
    colors = []
    for color in (top, top, bottom, bottom):
        colors += [linear(c) for c in color]
    backdrop.geometry.attributes.color.array.set(to_js(colors))
    backdrop.geometry.attributes.color.needsUpdate = True


def make_stars(count: int) -> object:
    luck = random.Random(11)
    flat = []
    for _ in range(count):
        flat += [luck.uniform(-30, 30), luck.uniform(-40, 40), luck.uniform(-7, -3)]
    geo = THREE.BufferGeometry.new()
    geo.setAttribute("position", THREE.Float32BufferAttribute.new(to_js(flat), 3))
    return THREE.Points.new(geo, THREE.PointsMaterial.new(js(color=0x6070c0, size=0.09, transparent=True, opacity=0.6)))


stars = make_stars(500)                             # 奥でゆっくり回る光の粒（ブルームで少し光る）
scene.add(stars)
def soft_texture() -> object:
    """真ん中が明るく端が透ける帯の絵（canvas）。光の柱の形。"""
    cv = document.createElement("canvas")
    cv.width, cv.height = 64, 256
    ctx = cv.getContext("2d")
    grad = ctx.createLinearGradient(0, 0, 64, 0)
    grad.addColorStop(0.0, "rgba(255,255,255,0)")
    grad.addColorStop(0.5, "rgba(255,255,255,1)")
    grad.addColorStop(1.0, "rgba(255,255,255,0)")
    ctx.fillStyle = grad
    ctx.fillRect(0, 0, 64, 256)
    vert = ctx.createLinearGradient(0, 0, 0, 256)
    vert.addColorStop(0.0, "rgba(0,0,0,1)")
    vert.addColorStop(0.3, "rgba(0,0,0,0)")
    vert.addColorStop(0.8, "rgba(0,0,0,0)")
    vert.addColorStop(1.0, "rgba(0,0,0,1)")
    ctx.globalCompositeOperation = "destination-out"
    ctx.fillStyle = vert
    ctx.fillRect(0, 0, 64, 256)
    return THREE.CanvasTexture.new(cv)


PILLAR_TEX = soft_texture()
pillars = []                                        # 盤の後ろの柔らかい光の柱（足し算で重ねる半透明の板）
for i, (x, w) in enumerate(((-4.5, 2.2), (0.8, 3.0), (5.2, 1.8))):
    mat = THREE.MeshBasicMaterial.new(js(color=0x6070ff, transparent=True, opacity=0.35, blending=THREE.AdditiveBlending, depthWrite=False, map=PILLAR_TEX))
    m = THREE.Mesh.new(THREE.PlaneGeometry.new(w, 30), mat)
    m.position.set(x, 2, -4.5)
    scene.add(m)
    pillars.append(m)
theme_shown = None
board_mat = THREE.MeshStandardMaterial.new(js(color=rgb(BOARD), roughness=0.9, metalness=0.0, envMapIntensity=0.15))
board = THREE.Mesh.new(THREE.BoxGeometry.new(COLS + 0.3, ROWS + 0.3, 0.4), board_mat)
board.position.set(0, 0, -0.55)
board.receiveShadow = True
scene.add(board)
frame_mat = THREE.MeshStandardMaterial.new(js(color=rgb(FRAME), roughness=0.4, metalness=0.6, envMapIntensity=0.4))
for x, y, w, h in ((-(COLS + 0.5) / 2, 0, 0.2, ROWS + 0.5), ((COLS + 0.5) / 2, 0, 0.2, ROWS + 0.5), (0, -(ROWS + 0.5) / 2, COLS + 0.7, 0.2)):
    rail = THREE.Mesh.new(THREE.BoxGeometry.new(w, h, 0.9), frame_mat)
    rail.position.set(x, y, -0.1)
    rail.castShadow = True
    scene.add(rail)
line_mat = THREE.MeshBasicMaterial.new(js(color=rgb(BOARD_LINE)))
for c in range(1, COLS):                            # 薄い格子
    line = THREE.Mesh.new(THREE.BoxGeometry.new(0.02, ROWS, 0.02), line_mat)
    line.position.set(cell_pos(c, 0)[0] - 0.5, 0, -0.34)
    scene.add(line)
for r in range(1, ROWS):
    line = THREE.Mesh.new(THREE.BoxGeometry.new(COLS, 0.02, 0.02), line_mat)
    line.position.set(0, cell_pos(0, r)[1] - 0.5, -0.34)
    scene.add(line)

BALL_GEO = THREE.SphereGeometry.new(0.44, 28, 18)
EYE_GEO = THREE.SphereGeometry.new(0.09, 10, 8)
PUPIL_GEO = THREE.SphereGeometry.new(0.045, 8, 6)
EYE_MAT = THREE.MeshStandardMaterial.new(js(color=0xffffff, roughness=0.3))
PUPIL_MAT = THREE.MeshStandardMaterial.new(js(color=0x202030, roughness=0.5))
BALL_MATS = [THREE.MeshPhysicalMaterial.new(js(color=rgb(p["rgb"]), roughness=0.3, metalness=0.0, clearcoat=1.0, clearcoatRoughness=0.1,
                                               envMapIntensity=0.3, emissive=rgb(p["rgb"]), emissiveIntensity=0.0)) for p in PALETTE]
POP_MATS = [THREE.MeshPhysicalMaterial.new(js(color=rgb(shade(p["rgb"], 1.3)), roughness=0.2, emissive=rgb(p["rgb"]), emissiveIntensity=2.2)) for p in PALETTE]
LINK_GEO = THREE.BoxGeometry.new(0.55, 0.42, 0.55)
LINK_GEO_V = THREE.BoxGeometry.new(0.42, 0.55, 0.55)
GHOST_MATS = [THREE.MeshBasicMaterial.new(js(color=rgb(p["rgb"]), transparent=True, opacity=0.22)) for p in PALETTE]
balls: dict[int, object] = {}                       # uid → 玉（体と目の Group）
links: list[object] = []                            # 同じ色をつなぐ橋（使い回し）
ghosts = [THREE.Mesh.new(BALL_GEO, GHOST_MATS[0]) for _ in range(2)]
for g in ghosts:
    g.scale.set(0.8, 0.8, 0.8)
    scene.add(g)
next_balls: list[object] = []
next_shown: tuple = ()
SPARKS = 300
spark_geo = THREE.BufferGeometry.new()              # 粒は短い線（尾を引く）：1 粒 = 2 頂点
spark_geo.setAttribute("position", THREE.Float32BufferAttribute.new(to_js([0.0, -999.0, 0.0] * (SPARKS * 2)), 3))
spark_geo.setAttribute("color", THREE.Float32BufferAttribute.new(to_js([1.0, 1.0, 1.0] * (SPARKS * 2)), 3))
sparks_lines = THREE.LineSegments.new(spark_geo, THREE.LineBasicMaterial.new(js(vertexColors=True, transparent=True, opacity=0.95)))
scene.add(sparks_lines)
sparks: list[list[float]] = []                      # [x, y, z, vx, vy, vz, life, r, g, b]
popped_seen: set[int] = set()
luck = random.Random(3)
landed: dict[int, float] = {}                       # uid → 着地した時刻（ぷるんと潰れる）
was_falling: set[int] = set()                       # 前のコマに落ちていた（組か SETTLE の）玉
SQUASH_TIME = 0.28
RINGS = 24                                          # 消えた所に広がる輪（使い回し）
ring_mat = THREE.MeshBasicMaterial.new(js(color=0xffffff, transparent=True, opacity=0.6, side=THREE.DoubleSide, depthWrite=False))
rings = []
for _ in range(RINGS):
    m = THREE.Mesh.new(THREE.RingGeometry.new(0.36, 0.5, 32), ring_mat.clone())
    m.visible = False
    scene.add(m)
    rings.append(m)
ring_live: list[list] = []                          # [mesh, 始まった時刻, 色]
POP_STAGGER = 0.03                                  # 消える玉は 1 つずつこれだけ遅れて弾ける
WAVE_DELAY = 0.045                                  # 着地の波：1 マス離れるごとの遅れ
RING_TIME = 0.4
labels: dict[str, object] = {}                      # 文字 → 板（CanvasTexture）。連鎖の数を浮かべる
label_live: list = []                               # [sprite, 始まった時刻]
LABEL_TIME = 1.1


def vignette_texture() -> object:
    """真ん中が透けて端が暗い絵。スローの間だけ画面の端を暗くする。"""
    cv = document.createElement("canvas")
    cv.width, cv.height = 256, 256
    ctx = cv.getContext("2d")
    grad = ctx.createRadialGradient(128, 128, 60, 128, 128, 180)
    grad.addColorStop(0.0, "rgba(0,0,0,0)")
    grad.addColorStop(1.0, "rgba(0,0,0,1)")
    ctx.fillStyle = grad
    ctx.fillRect(0, 0, 256, 256)
    return THREE.CanvasTexture.new(cv)


vignette = THREE.Sprite.new(THREE.SpriteMaterial.new(js(map=vignette_texture(), transparent=True, opacity=0.0, depthTest=False)))
vignette.scale.set(22, 22, 1)
vignette.position.set(0, 0, -12)                    # カメラの 12 手前に張り付ける（カメラの子）
camera.add(vignette)
scene.add(camera)


def make_label(text: str, color: str) -> object:
    """文字を canvas に描いて板に貼る（TextGeometry より軽い）。"""
    cv = document.createElement("canvas")
    cv.width, cv.height = 512, 160
    ctx = cv.getContext("2d")
    ctx.font = "bold 96px sans-serif"
    ctx.textAlign = "center"
    ctx.textBaseline = "middle"
    ctx.lineWidth = 14
    ctx.strokeStyle = "rgba(20,10,40,0.9)"
    ctx.strokeText(text, 256, 80)
    ctx.fillStyle = color
    ctx.fillText(text, 256, 80)
    tex = THREE.CanvasTexture.new(cv)
    mat = THREE.SpriteMaterial.new(js(map=tex, transparent=True, depthTest=False))
    sprite = THREE.Sprite.new(mat)
    sprite.scale.set(6.4, 2.0, 1)
    sprite.visible = False
    scene.add(sprite)
    return sprite


def show_label(text: str, color: str, x: float, y: float, now: float) -> None:
    sprite = labels.get(text)
    if sprite is None:
        sprite = make_label(text, color)
        labels[text] = sprite
    sprite.position.set(x, y, 2.5)
    sprite.visible = True
    label_live.append([sprite, now])


def squash(uid: int, now: float, col: int = -1, row: int = -1, impact: tuple = (0, 0, -9.0)) -> tuple[float, float]:
    """着地直後の潰れ：横に広がり縦に縮んで戻る。(横, 縦) の倍率。
    着地の波：固まった組から離れた玉ほど遅れて、小さく潰れる（時間差がダイナミックさの正体）。"""
    t = now - landed.get(uid, -9.0)
    amount = 1.0
    if t < 0 or t > SQUASH_TIME:
        ic, ir, when = impact
        dist = abs(col - ic) + max(0, row - ir) * 0.5
        t = now - when - dist * WAVE_DELAY
        amount = max(0.0, 0.6 - dist * 0.12)
        if t < 0 or t > SQUASH_TIME or amount <= 0:
            return 1.0, 1.0
    k = math.sin(math.pi * t / SQUASH_TIME) * (1 - t / SQUASH_TIME) * amount
    return 1.0 + 0.28 * k, 1.0 - 0.32 * k


def ball_for(blob: Blob) -> object:
    """玉 1 つ = 体（球）＋ 目 2 つ＋ 黒目 2 つの Group。作るのは最初の 1 回だけ。"""
    group = balls.get(blob.uid)
    if group is None:
        group = THREE.Group.new()
        body = THREE.Mesh.new(BALL_GEO, BALL_MATS[blob.color])
        body.castShadow = True
        group.add(body)
        for side in (-1, 1):
            eye = THREE.Mesh.new(EYE_GEO, EYE_MAT)
            eye.position.set(side * 0.15, 0.1, 0.38)
            group.add(eye)
            pupil = THREE.Mesh.new(PUPIL_GEO, PUPIL_MAT)
            pupil.position.set(side * 0.15, 0.1, 0.45)
            group.add(pupil)
        scene.add(group)
        balls[blob.uid] = group
    return group


def set_face(group: object, blob: Blob, now: float, pupil_dx: float = 0.0) -> None:
    """目の瞬きと黒目の向き。瞬きは玉ごとにずれた周期で。"""
    blink = (now + blob.uid * 1.7) % 3.8 < 0.13
    for i in (1, 3):
        group.children[i].scale.set(1, 0.12 if blink else 1, 1)
    for i in (2, 4):
        pupil = group.children[i]
        pupil.position.x = (-0.15 if i == 2 else 0.15) + pupil_dx
        pupil.visible = not blink


def link_at(index: int, x: float, y: float, vertical: bool, color: int) -> None:
    while len(links) <= index:
        m = THREE.Mesh.new(LINK_GEO, BALL_MATS[0])
        m.castShadow = True
        scene.add(m)
        links.append(m)
    m = links[index]
    m.geometry = LINK_GEO_V if vertical else LINK_GEO
    m.material = BALL_MATS[color]
    m.position.set(x, y, 0)
    m.visible = True


def apply_theme(theme: dict, fever_pulse: float | None) -> None:
    """場所の色を背景・霧・柱・粒に。フィーバー中は脈打つ紫。"""
    top, bottom, glow = theme["top"], theme["bottom"], theme["glow"]
    if fever_pulse is not None:
        top = (70 + int(30 * fever_pulse), 28, 100)
        bottom = (22, 8, 38)
        glow = (255, 190, 90)
    paint_backdrop(top, bottom)
    scene.fog.color.setHex(rgb(bottom))
    scene.background = scene.fog.color
    for m in pillars:
        m.material.color.setHex(rgb(glow))
    stars.material.color.setHex(rgb(tuple(int(c * 0.6) for c in glow)))


def sync(world: World, dt: float) -> None:
    global was_falling, theme_shown
    now = world.time
    alive = set()
    falling_now: set[int] = set()
    moving = {uid: (col, a, b) for uid, col, a, b in world.moves}
    total = max(SETTLE_MIN, SETTLE_PER_ROW * max([a - b for _, _, a, b in world.moves] or [1]))
    t = 1.0 - world.phase_left / total
    ease = 1 - (1 - min(1.0, max(0.0, t))) ** 2
    n_links = 0
    p = world.piece
    piece_x = cell_pos(p.col, 0)[0] if p is not None else 0.0
    for row in range(ROWS + 1):
        for col in range(COLS):
            blob = world.grid[row][col]
            if blob is None:
                continue
            alive.add(blob.uid)
            group = ball_for(blob)
            show_row = row
            if blob.uid in moving:
                _, a, b = moving[blob.uid]
                show_row = a + (b - a) * ease
                falling_now.add(blob.uid)
            elif blob.uid in was_falling:            # いま着地した
                landed[blob.uid] = now
            x, y = cell_pos(col, show_row)
            if blob.uid in moving:
                sx, sy = 0.92, 1.12                 # 落ちている間は縦に伸びる
            else:
                sx, sy = squash(blob.uid, now, col, row, world.impact)
                breath = 1.0 + 0.025 * math.sin(now * 2.0 + blob.uid * 0.7)   # 待っている間は呼吸
                sx, sy = sx * breath, sy / breath
            group.position.set(x, y - (1 - sy) * 0.44, 0)
            group.scale.set(sx, sy, sx)
            group.children[0].material = BALL_MATS[blob.color]
            group.visible = row < ROWS
            set_face(group, blob, now, max(-0.05, min(0.05, (piece_x - x) * 0.02)))   # 黒目は落ちてくる組の方を見る
            if blob.uid in moving:
                continue
            right = world.grid[row][col + 1] if col + 1 < COLS else None
            if right is not None and right.color == blob.color and right.uid not in moving and row < ROWS:
                link_at(n_links, x + 0.5, y, False, blob.color)
                n_links += 1
            up = world.grid[row + 1][col] if row + 1 < ROWS else None
            if up is not None and up.color == blob.color and up.uid not in moving:
                link_at(n_links, x, y + 0.5, True, blob.color)
                n_links += 1
    for m in links[n_links:]:
        m.visible = False
    elapsed = POP_TIME - world.phase_left if world.pops else 0.0
    span = max(0.1, POP_TIME - POP_STAGGER * len(world.pops))     # 1 つが縮むのにかけられる時間
    for i, (blob, col, row) in enumerate(world.pops):   # 消えている玉：1 つずつ遅れて光って縮む。弾けた瞬間に粒と輪
        alive.add(blob.uid)
        group = ball_for(blob)
        x, y = cell_pos(col, row)
        mine = elapsed - i * POP_STAGGER                # この玉の経過（まだなら負）
        k = 1.0 if mine < 0 else max(0.0, 1 - mine / span)
        group.position.set(x, y, 0.2)
        group.scale.set(k * 1.3, k * 1.3, k * 1.3)
        group.children[0].material = POP_MATS[blob.color] if mine >= 0 else BALL_MATS[blob.color]
        group.visible = True
        if mine >= 0 and blob.uid not in popped_seen:
            popped_seen.add(blob.uid)
            r, g, b = [c / 255 for c in PALETTE[blob.color]["rgb"]]
            for _ in range(10 + 4 * world.chain):
                a = luck.uniform(0, math.tau)
                s = luck.uniform(1.5, 5.0 + world.chain)
                sparks.append([x, y, 0.3, math.cos(a) * s, math.sin(a) * s + 2.0, luck.uniform(0.5, 2.5), luck.uniform(0.35, 0.7), r, g, b])
            free = [m for m in rings if not m.visible]
            if free:
                ring = free[0]
                ring.position.set(x, y, 0.6)
                ring.material.color.setHex(rgb(PALETTE[blob.color]["rgb"]))
                ring.visible = True
                ring_live.append([ring, now])
    if world.pops and world.phase_left > POP_TIME - 0.05 and not any(l[1] == now for l in label_live):   # 連鎖の数を浮かべる
        if world.chain >= 2:
            cx = sum(cell_pos(c, r)[0] for _, c, r in world.pops) / len(world.pops)
            cy = sum(cell_pos(c, r)[1] for _, c, r in world.pops) / len(world.pops)
            show_label(f"{world.chain} 連鎖!", "#ffd75e" if world.chain < 4 else "#ff8fe0", cx, cy + 0.6, now)
    for item in ring_live:                          # 輪：広がって薄くなる
        ring, born = item
        t = (now - born) / RING_TIME
        if t >= 1:
            ring.visible = False
        else:
            ring.scale.set(1 + 4 * t, 1 + 4 * t, 1)
            ring.material.opacity = 0.7 * (1 - t)
    ring_live[:] = [it for it in ring_live if it[0].visible]
    for item in label_live:                         # 文字：ぽんと出て、上がりながら消える
        sprite, born = item
        t = (now - born) / LABEL_TIME
        if t >= 1:
            sprite.visible = False
        else:
            pop = 1.0 + 0.6 * math.exp(-8 * t) * math.sin(12 * t) if t < 0.5 else 1.0
            sprite.scale.set(6.4 * pop, 2.0 * pop, 1)
            sprite.position.y += 1.2 * dt
            sprite.material.opacity = 1.0 if t < 0.6 else 1 - (t - 0.6) / 0.4
    label_live[:] = [it for it in label_live if it[0].visible]
    if p is not None and world.phase == Phase.FALL:
        land = world.landing_row()
        for ghost, (c, r), blob in zip(ghosts, p.cells(p.col, land), (p.axis, p.mate)):
            x, y = cell_pos(c, r)
            ghost.position.set(x, y, 0)
            ghost.material = GHOST_MATS[blob.color]
            ghost.visible = r < ROWS
        for (c, r), blob in zip(p.cells(), (p.axis, p.mate)):
            alive.add(blob.uid)
            falling_now.add(blob.uid)
            group = ball_for(blob)
            x, y = cell_pos(c, r)
            group.position.set(x, y, 0)
            group.scale.set(0.94, 1.08, 0.94)
            group.visible = r < ROWS
            set_face(group, blob, now)
    else:
        for ghost in ghosts:
            ghost.visible = False
    was_falling = falling_now
    for uid in list(balls):
        if uid not in alive:
            scene.remove(balls.pop(uid))
            landed.pop(uid, None)
    global next_shown
    shown = tuple(world.queue[:QUEUE])
    if shown != next_shown:
        next_shown = shown
        for m in next_balls:
            scene.remove(m)
        next_balls.clear()
        for i, (c1, c2) in enumerate(shown):
            for j, color in enumerate((c1, c2)):
                m = THREE.Mesh.new(BALL_GEO, BALL_MATS[color])
                m.scale.set(0.7, 0.7, 0.7)
                m.position.set(COLS / 2 + 1.4, ROWS / 2 - 1.0 - i * 2.2 - (1 - j) * 0.75, 0)
                scene.add(m)
                next_balls.append(m)
    flat, colors = [], []
    for s in sparks:
        s[0] += s[3] * dt
        s[1] += s[4] * dt
        s[2] += s[5] * dt
        s[4] -= 9.0 * dt
        s[6] -= dt
    sparks[:] = [s for s in sparks if s[6] > 0][-SPARKS:]
    for s in sparks:
        flat += [s[0], s[1], s[2], s[0] - s[3] * 0.05, s[1] - s[4] * 0.05, s[2] - s[5] * 0.05]   # 頭と尾
        colors += [s[7], s[8], s[9], s[7] * 0.3, s[8] * 0.3, s[9] * 0.3]
    flat += [0.0, -999.0, 0.0] * (2 * (SPARKS - len(sparks)))
    colors += [1.0, 1.0, 1.0] * (2 * (SPARKS - len(sparks)))
    spark_geo.attributes.position.array.set(to_js(flat))
    spark_geo.attributes.position.needsUpdate = True
    spark_geo.attributes.color.array.set(to_js(colors))
    spark_geo.attributes.color.needsUpdate = True
    ox = oy = 0.0
    if now < world.shake_until:
        k = world.shake_size * (world.shake_until - now) / 0.25 * 0.08
        ox, oy = math.sin(now * 90) * k, math.cos(now * 70) * k
    # ── カメラ：出来事ごとに行きたい所を決め、少しずつ近づく
    if world.pops and world.phase_left > POP_TIME - 0.05:            # 消えた：その場所へ寄る（深い連鎖は引いて全体を見せる）
        cx = sum(cell_pos(c, r)[0] for _, c, r in world.pops) / len(world.pops)
        cy = sum(cell_pos(c, r)[1] for _, c, r in world.pops) / len(world.pops)
        cam["focus"] = (cx * 0.5, cy * 0.5, 21.0 - 3.0 if world.chain < 3 else 21.0 + 2.5 + 0.5 * world.chain)
        cam["focus_until"] = now + (0.5 if world.chain < 3 else 0.9)
    if world.pieces != cam["pieces"]:                                # 固まった：下へ小さく沈む
        cam["pieces"] = world.pieces
        cam["dip_at"] = now
    if world.fevers != cam["fevers"]:                                # フィーバー突入：カメラが大きく振れる
        cam["fevers"] = world.fevers
        cam["spin_at"] = now
    slow = world.time_scale() < 1.0
    want = list(CAM)
    look = [0.0, 0.0]
    if now < cam["focus_until"] and cam["focus"] is not None:
        fx, fy, fz = cam["focus"]
        want = [CAM[0] + fx, CAM[1] + fy, fz]
        look = [fx, fy]
    if slow:                                                          # スロー：さらに寄る
        want[2] -= 2.0
    dip = now - cam["dip_at"]
    if 0 <= dip < 0.25:
        want[1] -= 0.5 * math.sin(math.pi * dip / 0.25)
    spin_t = now - cam["spin_at"]
    angle = 0.0
    if 0 <= spin_t < 1.4:
        angle = 0.55 * math.sin(math.tau * spin_t / 1.4) * (1 - spin_t / 1.4)   # 左右へ大きく振って戻る（一周すると盤の裏が見える）
    for key, value in (("x", want[0]), ("y", want[1]), ("z", want[2]), ("look_x", look[0]), ("look_y", look[1])):
        cam[key] += (value - cam[key]) * CAM_EASE
    radius = cam["z"]
    camera.position.set(cam["x"] + ox + radius * math.sin(angle), cam["y"] + oy, radius * math.cos(angle))
    camera.lookAt(cam["look_x"] + ox, cam["look_y"] + oy, 0.0)
    vignette.material.opacity += ((0.75 if slow else 0.0) - vignette.material.opacity) * 0.2
    vignette.visible = vignette.material.opacity > 0.01
    stars.rotation.z = now * 0.02
    key_light.position.set(5 + 4 * math.sin(now * 0.25), 10, 12 + 2 * math.cos(now * 0.25))   # 主光がゆっくり動く
    for i, m in enumerate(pillars):                                    # 光の柱はゆっくり揺れる
        m.position.x = (-4.5, 0.8, 5.2)[i] + 0.6 * math.sin(now * 0.3 + i * 2.1)
        m.material.opacity = 0.22 + 0.1 * math.sin(now * 0.7 + i)
    chain = world.chain if world.phase == Phase.POP else 0            # 連鎖が深いほど光が強く、フィーバーは脈打つ
    glow = BLOOM_BASE + 0.18 * chain
    flash = world.phase == Phase.POP and world.phase_left > POP_TIME - 0.07   # 消えた瞬間、全体が一瞬明るく
    ambient.intensity = 0.5 + (0.8 + 0.3 * chain if flash else 0.0)
    theme = theme_for(world.level)
    if world.fever:
        pulse = 0.5 + 0.5 * math.sin(now * 6)
        glow += 0.08 + 0.1 * pulse
        apply_theme(theme, pulse)
        theme_shown = None
        frame_mat.emissive.setHex(0xffb040)
        frame_mat.emissiveIntensity = 0.4 + 0.5 * pulse
        spot.intensity = 9.0
        spot.position.x = 6 * math.sin(now * 1.3)
        spot.target.position.set(4 * math.sin(now * 1.3), -2, 0)
    else:
        if theme_shown is not theme:
            apply_theme(theme, None)
            theme_shown = theme
        frame_mat.emissiveIntensity = 0.0
        spot.intensity = 0.0
    bloom.strength = min(1.6, glow)


class Speaker:
    def __init__(self):
        self.made = {}
        for kind in SOUNDS:
            uri = "data:audio/wav;base64," + base64.b64encode(sound_bytes(kind)).decode()
            self.made[kind] = window.Audio.new(uri)

    def say(self, kind: str | None) -> None:
        if kind is None:
            return
        sound = self.made[kind]
        sound.currentTime = 0
        sound.play()


speaker = Speaker()
world = World(seed=int(window.performance.now()))
best = Best.parse(window.localStorage.getItem(SAVED) or "")
improved = False
frames = []


def refresh(dt: float = STEP) -> None:
    sync(world, dt)
    composer.render()
    level_label.textContent = str(world.level)
    mission_label.textContent = world.mission_text() + ("（フィーバー中 ×2）" if world.fever else "")
    stars_label.textContent = "★" * world.stars + "☆" * (len(MISSIONS) - world.stars)
    score_label.textContent = str(world.score)
    chain_label.textContent = str(world.max_chain)
    cleared_label.textContent = str(world.cleared)
    pieces_label.textContent = str(world.pieces)
    best_label.textContent = f"{best.score}（{best.chain} 連鎖・★{best.stars}）"
    note_label.textContent = (world.note if world.time < world.note_until else "") or " "
    if world.over:
        message.textContent = (f"積み上がった。点 {world.score}、消した {world.cleared} 個、最大 {world.max_chain} 連鎖、レベル {world.level}、お題 {world.stars}/{len(MISSIONS)}"
                               + ("  ベスト更新！" if improved else ""))
    elif not world.started:
        message.textContent = "「スタート」で始める。左右スワイプで移動、タップで回転、下スワイプで一気に落とす（パソコンは ← → ↑ ↓ とスペース）"
    else:
        message.textContent = ""
    again_button.hidden = not world.over
    go_button.hidden = world.started


async def loop():
    global improved
    lag = 0.0
    last = window.performance.now() / 1000
    while True:
        now = window.performance.now() / 1000
        frame_dt = min(0.1, now - last)
        lag = min(lag + now - last, 0.25)
        last = now
        while lag >= STEP:
            event = world.update(STEP * world.time_scale())
            if event == "end":
                improved = best.take(world)
                window.localStorage.setItem(SAVED, best.dump())
                event = "best" if improved else event
            speaker.say(event)
            lag -= STEP
        refresh(frame_dt * world.time_scale())
        frames.append(window.performance.now() / 1000)
        del frames[:-30]
        if len(frames) >= 2:
            fps_label.textContent = f"{(len(frames) - 1) / (frames[-1] - frames[0]):.0f}"
        spent = window.performance.now() / 1000 - now
        await asyncio.sleep(max(0.002, STEP - spent))


def wake_sound() -> None:
    if not wake_sound.done:
        wake_sound.done = True
        speaker.say("move")


wake_sound.done = False


def begin() -> None:
    if not world.started:
        world.started = True


@when("keydown", "body")
def on_down(event):
    key = event.key
    if key in ("ArrowLeft", "a"):
        event.preventDefault()
        speaker.say(world.move(-1))
    elif key in ("ArrowRight", "d"):
        event.preventDefault()
        speaker.say(world.move(1))
    elif key in ("ArrowUp", "x", "w"):
        event.preventDefault()
        if not event.repeat:
            speaker.say(world.rotate(1))
    elif key == "z":
        if not event.repeat:
            speaker.say(world.rotate(-1))
    elif key in ("ArrowDown", "s"):
        event.preventDefault()
        world.soft = True
    elif key in (" ", "Enter"):
        event.preventDefault()
        if not event.repeat:
            wake_sound()
            if not world.started:
                begin()
            else:
                speaker.say(world.hard_drop())
            refresh()


@when("keyup", "body")
def on_up(event):
    if event.key in ("ArrowDown", "s"):
        world.soft = False


# --- 指：左右スワイプで 1 マスずつ、タップで回転、下スワイプで一気に落とす
touch = {"x": 0.0, "y": 0.0, "t": 0.0, "anchor": 0.0, "moved": False}
SWIPE_CELL = 30.0                                   # 何ピクセル動いたら 1 マス
SWIPE_DOWN = 50.0


@when("pointerdown", "#screen")
def press(event):
    event.preventDefault()
    wake_sound()
    if not world.started:
        begin()
        refresh()
    touch.update(x=event.clientX, y=event.clientY, t=window.performance.now(), anchor=event.clientX, moved=False)


@when("pointermove", "#screen")
def slide(event):
    if event.pointerType == "mouse" and event.buttons == 0:
        return
    event.preventDefault()
    dx = event.clientX - touch["anchor"]
    while abs(dx) >= SWIPE_CELL:
        step = 1 if dx > 0 else -1
        speaker.say(world.move(step))
        touch["anchor"] += step * SWIPE_CELL
        touch["moved"] = True
        dx -= step * SWIPE_CELL


@when("pointerup", "#screen")
def release(event):
    dx, dy = event.clientX - touch["x"], event.clientY - touch["y"]
    held = window.performance.now() - touch["t"]
    if dy > SWIPE_DOWN and abs(dy) > abs(dx) * 1.5:
        speaker.say(world.hard_drop())
    elif not touch["moved"] and abs(dx) < 12 and abs(dy) < 12 and held < 400:
        speaker.say(world.rotate(1))


@when("click", "#go")
def go(event):
    wake_sound()
    begin()
    go_button.blur()
    refresh()


@when("click", "#again")
def again(event):
    global world, improved, next_shown
    world = World(seed=int(window.performance.now()))
    for uid in list(balls):
        scene.remove(balls.pop(uid))
    popped_seen.clear()
    landed.clear()
    sparks.clear()
    world.started = True
    improved = False
    refresh()


refresh()
document.querySelector("#loading").hidden = True
asyncio.ensure_future(loop())
