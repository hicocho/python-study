"""シューティング（ブラウザ版）

CLI 版（g07-shooting/main.py）とルールは同じ。
Ship / Bullet / Target の 3 クラスと make_targets() / collide() は
1 文字も変えずにそのまま持ってきている。

違うのは入口と出口だけ。
入口は os.read() の代わりにキーイベント、出口は文字の盤面の代わりに 252 個の <div>。
時間を進めるのも select の時間切れではなく、asyncio の待ち合わせになっている。
"""

import asyncio
import time

from pyscript import document, when

WIDTH = 21
HEIGHT = 12
TICK_SECONDS = 0.08
MAX_BULLETS = 3

KEYS = {  # ブラウザが送ってくる名前 → CLI 版と同じ呼び名
    "ArrowLeft": "left",
    "ArrowRight": "right",
    " ": "shoot",
}

CELL_CLASS = {  # CLI 版の mark を、そのまま CSS の名前に読み替える
    "A": "c-ship",
    "|": "c-bullet",
    "*": "c-target",
}


# --- ここから 5 つは CLI 版からそのまま ---

class Ship:
    """自機。位置と見た目を自分で持つ。"""

    def __init__(self, x, y):
        self.x = x
        self.y = y
        self.mark = "A"

    def move(self, dx):
        """左右に動く。画面の外へは出ない。"""
        new_x = self.x + dx
        if 0 <= new_x < WIDTH:
            self.x = new_x

    def shoot(self):
        """自分の1つ上に弾を1発つくって返す。"""
        return Bullet(self.x, self.y - 1)


class Bullet:
    """自機が撃った弾。まっすぐ上へ飛ぶ。"""

    def __init__(self, x, y):
        self.x = x
        self.y = y
        self.mark = "|"

    def update(self):
        """1段ぶん上へ進む。"""
        self.y -= 1

    def alive(self):
        """まだ画面の中にいるなら True。"""
        return 0 <= self.y < HEIGHT

    def hits(self, other):
        """相手と同じマスにいるなら True。"""
        return self.x == other.x and self.y == other.y


class Target:
    """撃ち落とす的。その場から動かない。"""

    def __init__(self, x, y):
        self.x = x
        self.y = y
        self.mark = "*"


def make_targets():
    """的を2列ぶん並べて、リストにして返す。"""
    return [Target(x, y) for y in (1, 3) for x in range(2, WIDTH - 1, 2)]


def collide(bullets, targets):
    """当たった弾と的を取り除いて、新しい2つのリストと命中数を返す。"""
    live_bullets = []
    live_targets = list(targets)

    for bullet in bullets:
        hit = None

        for target in live_targets:
            if bullet.hits(target):
                hit = target
                break

        if hit is None:
            live_bullets.append(bullet)
        else:
            live_targets.remove(hit)

    return live_bullets, live_targets, len(targets) - len(live_targets)


# --- ここから下がブラウザ版だけの部分 ---

grid = document.querySelector("#grid")
left_label = document.querySelector("#left")
ammo_label = document.querySelector("#ammo")
time_label = document.querySelector("#time")
message = document.querySelector("#message")
start_button = document.querySelector("#start-btn")

cells = []  # 252 個のマス。作るのは一度だけで、あとは色を塗り替える
for _ in range(WIDTH * HEIGHT):
    cell = document.createElement("div")
    cell.className = "cell"
    grid.appendChild(cell)
    cells.append(cell)

# CLI 版では素の変数だった ship / bullets / targets / shots を、辞書にまとめて持つ。
# キーイベントから呼ばれるたびに中断・再開するので、ループの中には置けない。
state = {
    "ship": Ship(WIDTH // 2, HEIGHT - 1),
    "bullets": [],
    "targets": make_targets(),
    "shots": 0,
    "hits": 0,
    "elapsed": 0.0,
    "playing": False,
    "start_time": 0.0,
}


def draw():
    """CLI 版の render() にあたる。文字列ではなく、マスの色を塗り替える。"""
    marks = [None] * (WIDTH * HEIGHT)  # 1 本のリストを 2 次元として使う

    for target in state["targets"]:               # 描く順番は CLI 版と同じ。
        marks[target.y * WIDTH + target.x] = target.mark

    for bullet in state["bullets"]:               # あとに書いたものが上に見える
        marks[bullet.y * WIDTH + bullet.x] = bullet.mark

    ship = state["ship"]
    marks[ship.y * WIDTH + ship.x] = ship.mark

    for index, cell in enumerate(cells):
        mark = marks[index]
        cell.className = "cell" if mark is None else f"cell {CELL_CLASS[mark]}"

    left_label.textContent = str(len(state["targets"]))
    ammo_label.textContent = f"{len(state['bullets'])}/{MAX_BULLETS}"
    time_label.textContent = f"{state['elapsed']:.1f}"


def shoot():
    """スペースを押したときの枝。撃てるのは3発まで。"""
    if len(state["bullets"]) < MAX_BULLETS:
        state["bullets"].append(state["ship"].shoot())
        state["shots"] += 1
        draw()


def step():
    """CLI 版の「時間が来たら世界を1つ進める」と同じ中身。"""
    bullets = state["bullets"]

    for bullet in bullets:
        bullet.update()

    bullets = [b for b in bullets if b.alive()]
    bullets, targets, hit_count = collide(bullets, state["targets"])

    state["bullets"] = bullets
    state["targets"] = targets
    state["hits"] += hit_count
    state["elapsed"] = time.time() - state["start_time"]

    draw()

    if not targets:
        finish()


def finish():
    """全部落とした。"""
    state["playing"] = False

    shots = state["shots"]
    accuracy = state["hits"] / shots * 100 if shots else 0.0
    message.textContent = (
        f"クリア！ {state['elapsed']:.1f} 秒 — "
        f"撃った {shots} 発 / 命中率 {accuracy:.0f}%"
    )
    message.hidden = False

    start_button.textContent = "もう一度"
    start_button.disabled = False


async def tick():
    """時間を進める係。CLI 版の select の時間切れにあたる。"""
    while state["playing"]:
        await asyncio.sleep(TICK_SECONDS)
        if state["playing"]:
            step()


def start():
    state["ship"] = Ship(WIDTH // 2, HEIGHT - 1)
    state["bullets"] = []
    state["targets"] = make_targets()
    state["shots"] = 0
    state["hits"] = 0
    state["elapsed"] = 0.0
    state["playing"] = True
    state["start_time"] = time.time()

    message.hidden = True
    start_button.disabled = True
    draw()

    asyncio.ensure_future(tick())  # 待ち続ける係を裏で走らせる


def act(key):
    """CLI 版の while ループの中身と同じ振り分け。"""
    if not state["playing"]:
        return

    if key == "left":
        state["ship"].move(-1)
        draw()
    elif key == "right":
        state["ship"].move(1)
        draw()
    elif key == "shoot":
        shoot()


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
