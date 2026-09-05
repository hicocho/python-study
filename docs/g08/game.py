"""シューティング2 — 敵の編隊（ブラウザ版）

CLI 版（g08-formation/main.py）とルールは同じ。
Entity / Ship / Bullet / Enemy / ToughEnemy の 5 クラスと
make_enemies() / move_interval() / can_move() / move_enemies() / collide()、
そして class Game を、ステップの目印コメントを除いて 1 文字も変えずに持ってきている。
外したのは Game の render() と draw()（端末に文字で書く係）だけ。

違うのは入口と出口だけ。
入口は os.read() の代わりにキーイベント、出口は文字の盤面の代わりに 294 個の <div>。
時間を進めるのも select の時間切れではなく、asyncio の待ち合わせになっている。
"""

import asyncio
import time

from pyscript import document, when

WIDTH = 21
HEIGHT = 14
TICK_SECONDS = 0.08
MAX_BULLETS = 3
ENEMY_MOVE_TICKS = 6
ENEMY_MIN_TICKS = 2

KEYS = {  # ブラウザが送ってくる名前 → CLI 版と同じ呼び名
    "ArrowLeft": "left",
    "ArrowRight": "right",
    " ": "shoot",
}

CELL_CLASS = {  # CLI 版の mark を、そのまま CSS の名前に読み替える
    "A": "c-ship",
    "|": "c-bullet",
    "*": "c-enemy",
    "W": "c-tough",
    "w": "c-tough-hit",
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
    """自機。位置と見た目は親から受け継ぐ。"""

    def __init__(self, x, y):
        super().__init__(x, y, "A")

    def move(self, dx):
        """左右に動く。画面の外へは出ない。"""
        new_x = self.x + dx
        if 0 <= new_x < WIDTH:
            self.x = new_x

    def shoot(self):
        """自分の1つ上に弾を1発つくって返す。"""
        return Bullet(self.x, self.y - 1)


class Bullet(Entity):
    """自機が撃った弾。まっすぐ上へ飛ぶ。"""

    def __init__(self, x, y):
        super().__init__(x, y, "|")

    def update(self):
        """1段ぶん上へ進む。"""
        self.y -= 1

    def alive(self):
        """まだ画面の中にいるなら True。"""
        return 0 <= self.y < HEIGHT


class Enemy(Entity):
    """敵。編隊でそろって横に動く。1発で落ちる。"""

    def __init__(self, x, y, mark="*"):
        super().__init__(x, y, mark)

    def update(self, dx, dy):
        """横に dx、下に dy だけ動く。"""
        self.x += dx
        self.y += dy

    def take_hit(self):
        """弾を1発受ける。落ちたなら True。"""
        return True


class ToughEnemy(Enemy):
    """固い敵。2発当てないと落ちない。"""

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


def make_enemies():
    """敵を3行ぶん並べる。いちばん上の行だけ固い敵。"""
    enemies = [ToughEnemy(x, 1) for x in range(4, 17, 2)]
    enemies += [Enemy(x, y) for y in (3, 5) for x in range(4, 17, 2)]
    return enemies


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


def collide(bullets, enemies):
    """当たった弾を消し、落ちた敵を取り除いて、新しい2つのリストと撃破数を返す。"""
    live_bullets = []
    live_enemies = list(enemies)

    for bullet in bullets:
        hit = None

        for enemy in live_enemies:
            if bullet.hits(enemy):
                hit = enemy
                break

        if hit is None:
            live_bullets.append(bullet)
        elif hit.take_hit():
            live_enemies.remove(hit)

    return live_bullets, live_enemies, len(enemies) - len(live_enemies)


class Game:
    """自機・弾・敵と、勝敗や記録をまとめて持つ。時間を1こまずつ進める。"""

    def __init__(self):
        self.ship = Ship(WIDTH // 2, HEIGHT - 1)
        self.bullets = []
        self.enemies = make_enemies()
        self.total = len(self.enemies)
        self.direction = 1
        self.cooldown = ENEMY_MOVE_TICKS
        self.shots = 0
        self.downed = 0
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

    def update(self):
        """時間を1こま進める。"""
        for bullet in self.bullets:
            bullet.update()

        self.cooldown -= 1
        if self.cooldown <= 0:
            self.direction = move_enemies(self.enemies, self.direction)
            self.cooldown = move_interval(self.enemies, self.total)

        self.bullets = [b for b in self.bullets if b.alive()]
        self.bullets, self.enemies, down_count = collide(self.bullets, self.enemies)
        self.downed += down_count

        if not self.enemies:
            self.result = "clear"
        elif max(enemy.y for enemy in self.enemies) >= self.ship.y:
            self.result = "over"

    def accuracy(self):
        """撃った弾に対する撃破の割合。1発も撃っていなければ 0。"""
        return self.downed / self.shots * 100 if self.shots else 0.0

# --- ここから下がブラウザ版だけの部分 ---

grid = document.querySelector("#grid")
left_label = document.querySelector("#left")
ammo_label = document.querySelector("#ammo")
time_label = document.querySelector("#time")
message = document.querySelector("#message")
start_button = document.querySelector("#start-btn")

cells = []  # 294 個のマス。作るのは一度だけで、あとは色を塗り替える
for _ in range(WIDTH * HEIGHT):
    cell = document.createElement("div")
    cell.className = "cell"
    grid.appendChild(cell)
    cells.append(cell)

# CLI 版で素の変数だったものは、ぜんぶ Game の中にある。
# ブラウザ版が自分で持つのは「遊んでいる最中か」と時刻だけ。
game = Game()
playing = False
start_time = 0.0
elapsed = 0.0


def draw():
    """CLI 版の Game.render() にあたる。文字列ではなく、マスの色を塗り替える。"""
    marks = [None] * (WIDTH * HEIGHT)  # 1 本のリストを 2 次元として使う

    for entity in game.enemies + game.bullets + [game.ship]:  # 並べる順＝描く順。
        marks[entity.y * WIDTH + entity.x] = entity.mark      # あとに書いたものが上

    for index, cell in enumerate(cells):
        mark = marks[index]
        cell.className = "cell" if mark is None else f"cell {CELL_CLASS[mark]}"

    left_label.textContent = str(len(game.enemies))
    ammo_label.textContent = f"{len(game.bullets)}/{MAX_BULLETS}"
    time_label.textContent = f"{elapsed:.1f}"


def step():
    """CLI 版の「時間が来たら世界を1つ進める」と同じ中身。"""
    global elapsed

    game.update()
    elapsed = time.time() - start_time
    draw()

    if game.over():
        finish()


def finish():
    """勝負がついた。"""
    global playing

    playing = False

    if game.result == "clear":
        headline = f"クリア！ {elapsed:.1f} 秒"
    else:
        headline = f"やられた… 残り {len(game.enemies)} 体"

    message.textContent = (
        f"{headline} — 撃った {game.shots} 発 / 命中率 {game.accuracy():.0f}%"
    )
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
    global game, playing, start_time, elapsed

    game = Game()  # 状態は Game が全部持っているので、作り直すだけで初期化になる
    playing = True
    start_time = time.time()
    elapsed = 0.0

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
