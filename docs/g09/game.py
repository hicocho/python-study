"""シューティング3 — スペースインベーダー（ブラウザ版）

CLI 版（g09-invaders/main.py）とルールは同じ。
Entity / Ship / Bullet / EnemyBullet / Enemy / ToughEnemy / Barrier の 7 クラスと
make_enemies() / make_barriers() / move_interval() / can_move() / move_enemies() /
front_enemies() / collide()、そして class Game を、ステップの目印コメントを除いて
1 文字も変えずに持ってきている。外したのは Game の render() と draw()。

違うのは入口と出口だけ。
入口は os.read() の代わりにキーイベント、出口は文字の盤面の代わりに 294 個の <div>。
記録の置き場も、ファイルの代わりに localStorage になっている。
そして CLI 版には無いものが 1 つある——ドット絵のインベーダー。
"""

import asyncio
import random
import time

from js import localStorage
from pyscript import document, when

WIDTH = 21
HEIGHT = 14
TICK_SECONDS = 0.08
MAX_BULLETS = 3
ENEMY_MOVE_TICKS = 6
ENEMY_MIN_TICKS = 2
ENEMY_SHOT_CHANCE = 0.06
SHIP_LIVES = 3
BARRIER_HP = 3
CLEAR_BONUS = 100

HIGHSCORE_KEY = "python-study-g09-highscore"   # CLI 版の highscore.json にあたる

KEYS = {  # ブラウザが送ってくる名前 → CLI 版と同じ呼び名
    "ArrowLeft": "left",
    "ArrowRight": "right",
    " ": "shoot",
}

CELL_CLASS = {  # CLI 版の mark を、そのまま CSS の名前に読み替える
    "A": "c-ship",
    "|": "c-bullet",
    "!": "c-ebullet",
    "*": "c-enemy",
    "W": "c-tough",
    "w": "c-tough-hit",
    "#": "c-barrier3",
    "=": "c-barrier2",
    "-": "c-barrier1",
}


# --- ドット絵（ブラウザ版だけ。CLI 版は "*" や "W" の文字で足りている）---

from urllib.parse import quote

# 敵（1発で落ちる）。編隊が1歩動くごとに 1 → 2 → 1 と切り替える
CRAB_1 = [
    "..#.....#..",
    "...#...#...",
    "..#######..",
    ".##.###.##.",
    "###########",
    "#.#######.#",
    "#.#.....#.#",
    "...##.##...",
]
CRAB_2 = [
    "..#.....#..",
    "#..#...#..#",
    "#.#######.#",
    "###.###.###",
    "###########",
    ".#########.",
    "..#.....#..",
    ".#.......#.",
]

# 固い敵（2発必要）
SQUID_1 = [
    "...##...",
    "..####..",
    ".######.",
    "##.##.##",
    "########",
    "..#..#..",
    ".#.##.#.",
    "#.#..#.#",
]
SQUID_2 = [
    "...##...",
    "..####..",
    ".######.",
    "##.##.##",
    "########",
    ".#.##.#.",
    "#......#",
    ".#....#.",
]

SHIP = [
    ".....#.....",
    "....###....",
    "....###....",
    ".#########.",
    "###########",
    "###########",
    "###########",
    "###########",
]

BULLET = ["#", "#", "#"]

ENEMY_BULLET = [
    ".#.",
    "..#",
    ".#.",
    "#..",
    ".#.",
]

# バリア。上から削れていく
BARRIER_3 = ["########"] * 8
BARRIER_2 = [
    "#.#..#.#",
    "########",
    "########",
    "########",
    "########",
    "########",
    "########",
    "########",
]
BARRIER_1 = [
    "........",
    "........",
    "........",
    ".#.#..#.",
    "########",
    "########",
    "########",
    "########",
]


def sprite_url(rows, color):
    """ドット絵を SVG の data URI にする。CSS の background-image にそのまま入る。"""
    height = len(rows)
    width = len(rows[0])
    dots = "".join(
        f"<rect x='{x}' y='{y}' width='1' height='1'/>"
        for y, row in enumerate(rows)
        for x, dot in enumerate(row)
        if dot == "#"
    )
    svg = (f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 {width} {height}' "
           f"fill='{color}'>{dots}</svg>")
    return f'url("data:image/svg+xml,{quote(svg, safe="")}")'


SPRITES = {  # 名前 → (1こま目, 2こま目, 色)。2こま目が無いものは None
    "enemy": (CRAB_1, CRAB_2, "#d4685e"),
    "tough": (SQUID_1, SQUID_2, "#8250df"),
    "tough-hit": (SQUID_1, SQUID_2, "#b9a0e8"),
    "ship": (SHIP, None, "#4aa3c7"),
    "bullet": (BULLET, None, "#d4a72c"),
    "ebullet": (ENEMY_BULLET, None, "#cf5b4e"),
    "barrier3": (BARRIER_3, None, "#4f9a6f"),
    "barrier2": (BARRIER_2, None, "#4f9a6f"),
    "barrier1": (BARRIER_1, None, "#4f9a6f"),
}


# --- ここから下は CLI 版からそのまま ---

class Entity:
    """位置と見た目を持つもの。自機・弾・敵の共通部分。"""

    def __init__(self, x, y, mark):
        self.x = x
        self.y = y
        self.mark = mark

    def hits(self, other):
        """相手と同じマスにいるなら True。"""
        return self.x == other.x and self.y == other.y


class Ship(Entity):
    """自機。敵弾に当たると残機が減る。"""

    def __init__(self, x, y):
        super().__init__(x, y, "A")
        self.lives = SHIP_LIVES

    def move(self, dx):
        """左右に動く。画面の外へは出ない。"""
        new_x = self.x + dx
        if 0 <= new_x < WIDTH:
            self.x = new_x

    def shoot(self):
        """自分の1つ上に弾を1発つくって返す。"""
        return Bullet(self.x, self.y - 1)

    def take_hit(self):
        """敵弾を1発受ける。残機が尽きたなら True。"""
        self.lives -= 1
        return self.lives <= 0


class Bullet(Entity):
    """自機が撃った弾。まっすぐ上へ飛ぶ。"""

    def __init__(self, x, y, mark="|"):
        super().__init__(x, y, mark)

    def update(self):
        """1段ぶん上へ進む。"""
        self.y -= 1

    def alive(self):
        """まだ画面の中にいるなら True。"""
        return 0 <= self.y < HEIGHT


class EnemyBullet(Bullet):
    """敵が撃った弾。上下が逆なだけで、あとは自機の弾と同じ。"""

    def __init__(self, x, y):
        super().__init__(x, y, "!")

    def update(self):
        """1段ぶん下へ進む。"""
        self.y += 1


class Enemy(Entity):
    """敵。編隊でそろって横に動く。1発で落ちる。"""

    POINTS = 10

    def __init__(self, x, y, mark="*"):
        super().__init__(x, y, mark)

    def update(self, dx, dy):
        """横に dx、下に dy だけ動く。"""
        self.x += dx
        self.y += dy

    def shoot(self):
        """自分の1つ下に弾を1発つくって返す。"""
        return EnemyBullet(self.x, self.y + 1)

    def take_hit(self):
        """弾を1発受ける。落ちたなら True。"""
        return True


class ToughEnemy(Enemy):
    """固い敵。2発当てないと落ちない。"""

    POINTS = 30

    def __init__(self, x, y):
        super().__init__(x, y, "W")
        self.hp = 2

    def take_hit(self):
        """弾を1発受ける。体力が尽きたなら True。"""
        self.hp -= 1

        if self.hp > 0:
            self.mark = "w"
            return False

        return True


class Barrier(Entity):
    """自機を守る壁。弾を受けるたびに削れ、3発でなくなる。"""

    MARKS = ["-", "=", "#"]

    def __init__(self, x, y):
        super().__init__(x, y, "#")
        self.hp = BARRIER_HP

    def take_hit(self):
        """弾を1発受ける。なくなったなら True。"""
        self.hp -= 1

        if self.hp > 0:
            self.mark = self.MARKS[self.hp - 1]
            return False

        return True


def make_enemies():
    """敵を3行ぶん並べる。いちばん上の行だけ固い敵。"""
    enemies = [ToughEnemy(x, 1) for x in range(4, 17, 2)]
    enemies += [Enemy(x, y) for y in (3, 5) for x in range(4, 17, 2)]
    return enemies


def make_barriers():
    """バリアを3つ、自機の少し上に置く。1つは横3マス。"""
    return [Barrier(x + dx, HEIGHT - 3) for x in (3, 9, 15) for dx in range(3)]


def move_interval(enemies, total):
    """残り数に応じた、敵が動く間隔。減るほど短く（速く）なる。"""
    ratio = len(enemies) / total
    return max(ENEMY_MIN_TICKS, round(ENEMY_MOVE_TICKS * ratio))


def can_move(enemies, dx):
    """編隊ぜんぶが dx の向きへ、あと1マス動けるなら True。"""
    if dx < 0:
        return min(enemy.x for enemy in enemies) + dx >= 0
    return max(enemy.x for enemy in enemies) + dx < WIDTH


def move_enemies(enemies, direction):
    """編隊を動かす。壁に着いていたら横へは進まず、1段下げて向きを変える。"""
    if can_move(enemies, direction):
        for enemy in enemies:
            enemy.update(direction, 0)
    else:
        direction = -direction
        for enemy in enemies:
            enemy.update(0, 1)

    return direction


def front_enemies(enemies):
    """列ごとに、いちばん下にいる敵だけを返す。撃てるのはこの敵だけ。"""
    front = {}

    for enemy in enemies:
        if enemy.x not in front or enemy.y > front[enemy.x].y:
            front[enemy.x] = enemy

    return list(front.values())


def collide(bullets, targets):
    """当たった弾を消し、壊れた的を取り除いて、残った弾・残った的・壊れた的を返す。"""
    live_bullets = []
    live_targets = list(targets)
    broken = []

    for bullet in bullets:
        hit = None

        for target in live_targets:
            if bullet.hits(target):
                hit = target
                break

        if hit is None:
            live_bullets.append(bullet)
        elif hit.take_hit():
            live_targets.remove(hit)
            broken.append(hit)

    return live_bullets, live_targets, broken


def load_highscore():
    """保存してあるハイスコアを読む。CLI 版はファイル、ここでは localStorage。"""
    try:
        return int(localStorage.getItem(HIGHSCORE_KEY) or 0)
    except (TypeError, ValueError):
        return 0


def save_highscore(score):
    """ハイスコアを localStorage に書き出す。このブラウザにだけ残る。"""
    localStorage.setItem(HIGHSCORE_KEY, str(score))


class Game:
    """自機・弾・敵と、勝敗や記録をまとめて持つ。時間を1こまずつ進める。"""

    def __init__(self, high=0):
        self.ship = Ship(WIDTH // 2, HEIGHT - 1)
        self.bullets = []
        self.enemy_bullets = []
        self.enemies = make_enemies()
        self.barriers = make_barriers()
        self.total = len(self.enemies)
        self.direction = 1
        self.cooldown = ENEMY_MOVE_TICKS
        self.shots = 0
        self.downed = 0
        self.score = 0
        self.high = high
        self.result = None

    def over(self):
        """勝負がついているなら True。"""
        return self.result is not None

    def quit(self):
        """やめる。"""
        self.result = "quit"

    def move_ship(self, dx):
        """自機を左右に動かす。"""
        self.ship.move(dx)

    def shoot(self):
        """撃てる残りがあれば1発撃つ。"""
        if len(self.bullets) < MAX_BULLETS:
            self.bullets.append(self.ship.shoot())
            self.shots += 1

    def enemy_shoot(self):
        """ときどき、最前列の敵が1体だけ撃ってくる。"""
        if self.enemies and random.random() < ENEMY_SHOT_CHANCE:
            shooter = random.choice(front_enemies(self.enemies))
            self.enemy_bullets.append(shooter.shoot())

    def hit_ship(self):
        """自機に当たった敵弾を消し、当たっていたら残機を1つ減らす。"""
        hits = [b for b in self.enemy_bullets if b.hits(self.ship)]
        self.enemy_bullets = [b for b in self.enemy_bullets if not b.hits(self.ship)]

        if hits and self.ship.take_hit():
            self.result = "over"

    def crush_barriers(self):
        """敵が重なったバリアは、削れる間もなく壊れる。"""
        self.barriers = [
            barrier
            for barrier in self.barriers
            if not any(enemy.hits(barrier) for enemy in self.enemies)
        ]

    def update(self):
        """時間を1こま進める。"""
        for bullet in self.bullets + self.enemy_bullets:
            bullet.update()

        self.enemy_shoot()

        self.cooldown -= 1
        if self.cooldown <= 0:
            self.direction = move_enemies(self.enemies, self.direction)
            self.cooldown = move_interval(self.enemies, self.total)
            self.crush_barriers()

        self.bullets = [b for b in self.bullets if b.alive()]
        self.enemy_bullets = [b for b in self.enemy_bullets if b.alive()]

        self.bullets, self.barriers, _ = collide(self.bullets, self.barriers)
        self.enemy_bullets, self.barriers, _ = collide(self.enemy_bullets, self.barriers)
        self.bullets, self.enemies, downed = collide(self.bullets, self.enemies)

        self.downed += len(downed)
        self.score += sum(enemy.POINTS for enemy in downed)

        self.hit_ship()

        if self.over():
            return

        if not self.enemies:
            self.score += self.ship.lives * CLEAR_BONUS
            self.result = "clear"
        elif max(enemy.y for enemy in self.enemies) >= self.ship.y:
            self.result = "over"

    def accuracy(self):
        """撃った弾に対する撃破の割合。1発も撃っていなければ 0。"""
        return self.downed / self.shots * 100 if self.shots else 0.0

# --- ここから下がブラウザ版だけの部分 ---

for name, (frame_a, frame_b, color) in SPRITES.items():
    document.documentElement.style.setProperty(f"--s-{name}", sprite_url(frame_a, color))
    if frame_b:
        document.documentElement.style.setProperty(f"--s-{name}-b", sprite_url(frame_b, color))

grid = document.querySelector("#grid")
left_label = document.querySelector("#left")
lives_label = document.querySelector("#lives")
score_label = document.querySelector("#score")
high_label = document.querySelector("#high")
time_label = document.querySelector("#time")
message = document.querySelector("#message")
start_button = document.querySelector("#start-btn")

cells = []  # 294 個のマス。作るのは一度だけで、あとは中身を差し替える
for _ in range(WIDTH * HEIGHT):
    cell = document.createElement("div")
    cell.className = "cell"
    grid.appendChild(cell)
    cells.append(cell)

# CLI 版で素の変数だったものは、ぜんぶ Game の中にある。
# ブラウザ版が自分で持つのは「遊んでいる最中か」「時刻」「いまどちらのこまか」だけ。
game = Game(load_highscore())
playing = False
start_time = 0.0
elapsed = 0.0
frame = 0
prev_cooldown = game.cooldown


def draw():
    """CLI 版の Game.render() にあたる。文字列ではなく、マスの見た目を差し替える。"""
    marks = [None] * (WIDTH * HEIGHT)  # 1 本のリストを 2 次元として使う

    for entity in (game.enemies + game.barriers + game.bullets
                   + game.enemy_bullets + [game.ship]):  # 並べる順＝描く順。
        marks[entity.y * WIDTH + entity.x] = entity.mark  # あとに書いたものが上

    grid.className = "f2" if frame else ""  # 編隊のパタパタ。2 こま目かどうか

    for index, cell in enumerate(cells):
        mark = marks[index]
        cell.className = "cell" if mark is None else f"cell {CELL_CLASS[mark]}"

    left_label.textContent = str(len(game.enemies))
    lives_label.textContent = str(game.ship.lives)
    score_label.textContent = str(game.score)
    high_label.textContent = str(game.high)
    time_label.textContent = f"{elapsed:.1f}"


def step():
    """CLI 版の「時間が来たら世界を1つ進める」と同じ中身。"""
    global elapsed, frame, prev_cooldown

    game.update()

    # cooldown は毎ティック 1 減り、編隊が動いた回だけ入れ直される。
    # つまり「増えていたら動いた」。Game に何も足さずに動いた瞬間が分かる。
    if game.cooldown > prev_cooldown:
        frame = 1 - frame
    prev_cooldown = game.cooldown

    elapsed = time.time() - start_time
    draw()

    if game.over():
        finish()


def finish():
    """勝負がついた。記録の更新もここで見る。"""
    global playing

    playing = False

    if game.result == "clear":
        headline = f"クリア！ {elapsed:.1f} 秒"
    elif game.ship.lives <= 0:
        headline = f"撃ち落とされた… 残り {len(game.enemies)} 体"
    else:
        headline = f"攻め込まれた… 残り {len(game.enemies)} 体"

    if game.score > game.high:
        save_highscore(game.score)
        record = f"ハイスコア更新！ {game.high} → {game.score} 点"
    else:
        record = f"{game.score} 点 / 最高 {game.high} 点"

    message.textContent = f"{headline} — {record}"
    message.hidden = False

    start_button.textContent = "もう一度"
    start_button.disabled = False


async def tick():
    """時間を進める係。CLI 版の select の時間切れにあたる。"""
    while playing:
        await asyncio.sleep(TICK_SECONDS)
        if playing:
            step()


def start():
    global game, playing, start_time, elapsed, frame, prev_cooldown

    # 状態は Game が全部持っているので、作り直すだけで初期化になる。
    # 前回までの最高得点だけは、外から読んで渡す。
    game = Game(load_highscore())
    playing = True
    start_time = time.time()
    elapsed = 0.0
    frame = 0
    prev_cooldown = game.cooldown

    message.hidden = True
    start_button.disabled = True
    draw()

    asyncio.ensure_future(tick())  # 待ち続ける係を裏で走らせる


def act(key):
    """CLI 版の while ループの中身と同じ振り分け。"""
    if not playing:
        return

    if key == "left":
        game.move_ship(-1)
        draw()
    elif key == "right":
        game.move_ship(1)
        draw()
    elif key == "shoot":
        game.shoot()
        draw()


@when("keydown", "body")
def on_key(event):
    key = KEYS.get(event.key)
    if key is None:
        return

    event.preventDefault()  # 矢印とスペースでページが動かないように
    act(key)


@when("click", "#start-btn")
def on_start(event):
    start()


@when("click", "#left-btn")
def on_left(event):
    act("left")


@when("click", "#right-btn")
def on_right(event):
    act("right")


@when("click", "#shoot-btn")
def on_shoot(event):
    act("shoot")


# Pyodide の読み込みが終わってから実行される＝ここが準備完了の合図
document.querySelector("#loading").hidden = True
start_button.disabled = False
draw()
