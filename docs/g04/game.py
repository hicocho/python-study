"""テトリス（ブラウザ版）

CLI 版（g04-tetris/main.py）と盤面まわりは同じ。
can_place() / place() / rotate() / clear_lines() / spawn() は
1 文字も変えずにそのまま持ってきている。

違うのは入口と出口だけ。
入口は os.read() の代わりにキーイベント、出口は文字の盤面の代わりに Three.js の立体ブロック 200 個。
時間を進めるのも select の時間切れではなく、asyncio の待ち合わせになっている。

（2026-09-18）出口を 200 個の <div> から Three.js に差し替えた。
盤面まわりの 5 関数は変えていない。変わったのは draw() と、その前の「舞台づくり」だけ。
"""

import asyncio
import random
import time

from pyodide.ffi import to_js
from pyscript import document, when, window

WIDTH = 10
HEIGHT = 20
FALL_SECONDS = 0.8

SCORES = [0, 100, 300, 500, 800]

SHAPES = {  # CLI 版と同じ 7 種類
    "I": [[1, 1, 1, 1]],
    "O": [[1, 1],
          [1, 1]],
    "T": [[0, 1, 0],
          [1, 1, 1]],
    "S": [[0, 1, 1],
          [1, 1, 0]],
    "Z": [[1, 1, 0],
          [0, 1, 1]],
    "J": [[1, 0, 0],
          [1, 1, 1]],
    "L": [[0, 0, 1],
          [1, 1, 1]],
}

KEYS = {  # ブラウザが送ってくる名前 → CLI 版と同じ呼び名
    "ArrowLeft": "left",
    "ArrowRight": "right",
    "ArrowUp": "up",
    "ArrowDown": "down",
    " ": "drop",
}


# --- ここから 5 つは CLI 版からそのまま ---

def make_board():
    """空の盤面を作って返す。0 が空きマス。"""
    return [[0] * WIDTH for _ in range(HEIGHT)]


def can_place(board, shape, x, y):
    """はみ出さず、ほかのブロックとも重ならないなら True。"""
    for dy in range(len(shape)):
        for dx in range(len(shape[dy])):
            if shape[dy][dx] == 0:
                continue

            bx = x + dx
            by = y + dy

            if not (0 <= bx < WIDTH and 0 <= by < HEIGHT):
                return False
            if board[by][bx] != 0:
                return False

    return True


def place(board, shape, x, y, name):
    """ミノを書き込んだ新しい盤面を返す。元の盤面は変えない。"""
    new_board = [row[:] for row in board]

    for dy in range(len(shape)):
        for dx in range(len(shape[dy])):
            if shape[dy][dx] != 0:
                new_board[y + dy][x + dx] = name

    return new_board


def rotate(shape):
    """上下をひっくり返してから、行と列を入れ替える。"""
    return [list(row) for row in zip(*reversed(shape))]


def clear_lines(board):
    """埋まった行を取り除き、そのぶん空の行を上に足す。"""
    kept = []

    for row in board:
        if 0 in row:
            kept.append(row)

    cleared = HEIGHT - len(kept)

    for _ in range(cleared):
        kept.insert(0, [0] * WIDTH)

    return kept, cleared


def spawn():
    """ミノの名前・形・出てくる位置（横）を返す。"""
    name = random.choice(list(SHAPES))
    shape = SHAPES[name]
    x = WIDTH // 2 - len(shape[0]) // 2
    return name, shape, x


# --- ここから下がブラウザ版だけの部分 ---

score_label = document.querySelector("#score")
lines_label = document.querySelector("#lines")
message = document.querySelector("#message")
start_button = document.querySelector("#start-btn")
canvas = document.querySelector("#screen")

# ── Three.js の舞台 ──────────────────────────────────────────────────────
#   index.html が window.THREE と window.ADDONS を置いてくれている。
#   Python からは「JS のクラスを .new() で作る」「引数の辞書は js() で JS のオブジェクトに直す」の 2 つだけ覚えればよい。

THREE = window.THREE
ADDONS = window.ADDONS
VIEW_W, VIEW_H = 360, 640

COLORS = {  # <div> 時代の CSS（.c-I など）と同じ 7 色
    "I": 0x4AA3C7,
    "O": 0xD4A72C,
    "T": 0x9A6BD4,
    "S": 0x4AA96C,
    "Z": 0xD4685E,
    "J": 0x4A72C7,
    "L": 0xD4894A,
}
BACK = 0x121222        # 画面の背景
BOARD = 0x1C1C34       # 盤の板
BOARD_LINE = 0x2C2C4A  # 板に引くマス目
FRAME = 0x4E5378       # 盤を囲む金属のふち


def js(**kw):
    """Python の キーワード引数 → JS のオブジェクト。Three.js のコンストラクタは {color: ..., roughness: ...} を受け取る"""
    return to_js(kw, dict_converter=window.Object.fromEntries)


renderer = THREE.WebGLRenderer.new(js(canvas=canvas, antialias=True))
renderer.setPixelRatio(min(2.0, window.devicePixelRatio))
renderer.setSize(VIEW_W, VIEW_H, False)               # False: CSS の大きさは触らない（スマホでは縮む）
renderer.toneMapping = THREE.ACESFilmicToneMapping   # 明るい所を白飛びさせず、フィルムのように丸める
renderer.toneMappingExposure = 1.0

scene = THREE.Scene.new()
scene.background = THREE.Color.new(BACK)
pmrem = THREE.PMREMGenerator.new(renderer)            # 「部屋」を映り込みの環境に。ブロックのつやが本物のガラスになる
scene.environment = pmrem.fromScene(ADDONS.RoomEnvironment.new(), 0.04).texture

camera = THREE.PerspectiveCamera.new(42, VIEW_W / VIEW_H, 0.5, 100)
camera.position.set(1.2, 2.0, 28.0)                   # 少し右上から盤を見下ろす。ブロックの側面がのぞく
camera.lookAt(0.0, 0.0, 0.0)

key_light = THREE.DirectionalLight.new(0xFFFFFF, 1.3)   # 主光。右上から
key_light.position.set(6.0, 12.0, 14.0)
scene.add(key_light)
fill_light = THREE.DirectionalLight.new(0x8FA8FF, 0.6)  # 補助光。左下から青っぽく
fill_light.position.set(-8.0, -6.0, 10.0)
scene.add(fill_light)
scene.add(THREE.AmbientLight.new(0x404060, 0.5))


def cell_pos(x, y):
    """盤面の (x, y)（左上が 0,0）→ 舞台の座標（盤の中心が 0,0）"""
    return (x - WIDTH / 2 + 0.5, HEIGHT / 2 - 0.5 - y, 0.0)


# 盤の板・マス目・ふち。一度作ったら動かない
board_mat = THREE.MeshStandardMaterial.new(js(color=BOARD, roughness=0.9, metalness=0.0, envMapIntensity=0.15))
board_plate = THREE.Mesh.new(THREE.BoxGeometry.new(WIDTH + 0.3, HEIGHT + 0.3, 0.4), board_mat)
board_plate.position.set(0.0, 0.0, -0.7)
scene.add(board_plate)

line_mat = THREE.MeshBasicMaterial.new(js(color=BOARD_LINE))
for i in range(WIDTH + 1):
    line = THREE.Mesh.new(THREE.BoxGeometry.new(0.02, HEIGHT, 0.02), line_mat)
    line.position.set(i - WIDTH / 2, 0.0, -0.49)
    scene.add(line)
for i in range(HEIGHT + 1):
    line = THREE.Mesh.new(THREE.BoxGeometry.new(WIDTH, 0.02, 0.02), line_mat)
    line.position.set(0.0, HEIGHT / 2 - i, -0.49)
    scene.add(line)

frame_mat = THREE.MeshStandardMaterial.new(js(color=FRAME, roughness=0.4, metalness=0.7, envMapIntensity=0.3))
for w, h, px, py in [(0.4, HEIGHT + 0.7, -(WIDTH / 2 + 0.35), 0.0),   # 左
                     (0.4, HEIGHT + 0.7, WIDTH / 2 + 0.35, 0.0),      # 右
                     (WIDTH + 1.1, 0.4, 0.0, -(HEIGHT / 2 + 0.35))]:  # 下
    rail = THREE.Mesh.new(THREE.BoxGeometry.new(w, h, 1.0), frame_mat)
    rail.position.set(px, py, -0.3)
    scene.add(rail)

# ブロック。角の丸い立方体にガラスのような表面（clearcoat）
BLOCK_GEO = ADDONS.RoundedBoxGeometry.new(0.92, 0.92, 0.92, 4, 0.12)
BLOCK_MATS = {
    name: THREE.MeshPhysicalMaterial.new(js(color=color, roughness=0.3, metalness=0.0,
                                            clearcoat=1.0, clearcoatRoughness=0.1, envMapIntensity=0.45))  # 映り込みは控えめ。強いと色が白っぽく飛ぶ
    for name, color in COLORS.items()
}

cells = []  # 200 個のブロック。作るのは一度だけで、あとは「見せる／隠す」と色を切り替える
for y in range(HEIGHT):
    for x in range(WIDTH):
        block = THREE.Mesh.new(BLOCK_GEO, BLOCK_MATS["T"])
        block.position.set(*cell_pos(x, y))
        block.visible = False
        scene.add(block)
        cells.append(block)

# CLI 版では素の変数だった board / x / y / score を、辞書にまとめて持つ。
# キーイベントから呼ばれるたびに中断・再開するので、ループの中には置けない。
state = {
    "board": make_board(),
    "name": "T",
    "shape": SHAPES["T"],
    "x": 4,
    "y": 0,
    "score": 0,
    "lines": 0,
    "playing": False,
    "next_fall": 0.0,
}


def draw():
    """CLI 版の render() にあたる。文字列ではなく、200 個のブロックの「見せる／隠す」と色を切り替えて描き直す。"""
    if state["playing"]:
        view = place(state["board"], state["shape"], state["x"], state["y"], state["name"])
    else:
        view = state["board"]

    for y in range(HEIGHT):
        row = view[y]
        for x in range(WIDTH):
            value = row[x]
            block = cells[y * WIDTH + x]  # 1 本のリストを 2 次元として使う
            block.visible = value != 0
            if value != 0:
                block.material = BLOCK_MATS[value]

    renderer.render(scene, camera)  # 盤面が変わったときだけ描く。動きの補間は次の回で
    score_label.textContent = str(state["score"])
    lines_label.textContent = str(state["lines"])


def move(dx):
    """左右に動かす。置けないときは何もしない。"""
    if can_place(state["board"], state["shape"], state["x"] + dx, state["y"]):
        state["x"] += dx
        draw()


def turn():
    """回して、置けると分かってから採用する。"""
    turned = rotate(state["shape"])
    if can_place(state["board"], turned, state["x"], state["y"]):
        state["shape"] = turned
        draw()


def lock():
    """落ちられなくなったミノを盤面に焼き付けて、次のミノを出す。"""
    board = place(state["board"], state["shape"], state["x"], state["y"], state["name"])
    board, cleared = clear_lines(board)

    state["board"] = board
    state["lines"] += cleared
    state["score"] += SCORES[cleared]

    name, shape, x = spawn()
    state["name"] = name
    state["shape"] = shape
    state["x"] = x
    state["y"] = 0

    if not can_place(board, shape, x, 0):  # 出す場所がもう無い
        finish()


def fall():
    """1 マス落とす。落ちられなければ固定。CLI 版の "down" の枝と同じ。"""
    state["next_fall"] = time.time() + FALL_SECONDS

    if can_place(state["board"], state["shape"], state["x"], state["y"] + 1):
        state["y"] += 1
    else:
        lock()

    draw()


def hard_drop():
    """一番下まで一気に落とす。次の tick でそのまま固定される。"""
    while can_place(state["board"], state["shape"], state["x"], state["y"] + 1):
        state["y"] += 1

    state["next_fall"] = time.time()
    draw()


def finish():
    """ゲームオーバー。"""
    state["playing"] = False
    message.textContent = f"ゲームオーバー — スコア {state['score']}"
    message.hidden = False
    start_button.textContent = "もう一度"
    start_button.disabled = False


async def tick():
    """時間を進める係。CLI 版の select の時間切れにあたる。"""
    while state["playing"]:
        await asyncio.sleep(0.05)  # 0.05 秒ごとに「もう落ちる時刻か？」と見に来る
        if state["playing"] and time.time() >= state["next_fall"]:
            fall()


def start():
    state["board"] = make_board()
    name, shape, x = spawn()
    state["name"] = name
    state["shape"] = shape
    state["x"] = x
    state["y"] = 0
    state["score"] = 0
    state["lines"] = 0
    state["playing"] = True
    state["next_fall"] = time.time() + FALL_SECONDS

    message.hidden = True
    start_button.disabled = True
    draw()

    asyncio.ensure_future(tick())  # 待ち続ける係を裏で走らせる


def act(key):
    """CLI 版の while ループの中身と同じ振り分け。"""
    if not state["playing"]:
        return

    if key == "left":
        move(-1)
    elif key == "right":
        move(1)
    elif key == "up":
        turn()
    elif key == "down":
        fall()
    elif key == "drop":
        hard_drop()


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


@when("click", "#turn-btn")
def on_turn(event):
    act("up")


@when("click", "#down-btn")
def on_down(event):
    act("down")


@when("click", "#drop-btn")
def on_drop(event):
    act("drop")


# Pyodide の読み込みが終わってから実行される＝ここが準備完了の合図
document.querySelector("#loading").hidden = True
start_button.disabled = False
draw()
