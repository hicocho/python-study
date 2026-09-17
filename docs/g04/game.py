"""テトリス（ブラウザ版）

CLI 版（g04-tetris/main.py）と盤面まわりは同じ。
can_place() / place() / rotate() / clear_lines() / spawn() は
1 文字も変えずにそのまま持ってきている。

違うのは入口と出口だけ。
入口は os.read() の代わりにキーイベント、出口は文字の盤面の代わりに Three.js の立体ブロック 200 個。
時間を進めるのも select の時間切れではなく、asyncio の待ち合わせになっている。

（2026-09-18・1 回目）出口を 200 個の <div> から Three.js に差し替えた。
盤面まわりの 5 関数は変えていない。変わったのは draw() と、その前の「舞台づくり」だけ。
（2026-09-18・2 回目）ゲーム性を足した。ゴースト・ホールド・7-bag・壁蹴り・レベル加速。
ライブラリは使わず Python だけ。spawn() は 7-bag の take() に置き換えた（残り 4 関数はそのまま）。
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
    "Shift": "hold",   # ここから 2 回目で足したホールド。Shift でも c でも
    "c": "hold",
    "C": "hold",
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

# ── 2 回目（2026-09-18）で足したゲーム性 ────────────────────────────────
#   ゴースト（落下位置の影）／ホールド／7 種を袋から引く（7-bag）／壁蹴り／レベルで加速。
#   どれもライブラリは使わず Python だけ。上の 5 関数のうち spawn() だけは
#   「袋から引く」方式に置き換えたので使わなくなった（残り 4 つはそのまま）。

NEXT_COUNT = 3                       # 先に見せる「つぎ」の数
KICKS = [(0, 0), (-1, 0), (1, 0), (-2, 0), (2, 0), (0, -1)]   # 壁蹴り：回して置けないとき、この順にずらして試す
LINES_PER_LEVEL = 10                 # この列数を消すごとにレベルが 1 上がる


def fall_seconds(level):
    """レベルごとの落下間隔。1 レベルごとに 15% 速く、最短 0.1 秒"""
    return max(0.1, FALL_SECONDS * (0.85 ** (level - 1)))


def refill(bag):
    """袋が空なら 7 種を 1 つずつ入れてかき混ぜる。同じミノが 3 回続く、I が 20 回来ない、が起きなくなる"""
    if not bag:
        bag.extend(SHAPES)
        random.shuffle(bag)


def take(name):
    """名前 → 形と出てくる位置（横）。spawn() の後半と同じ計算"""
    shape = SHAPES[name]
    x = WIDTH // 2 - len(shape[0]) // 2
    return shape, x


def ghost_y(board, shape, x, y):
    """いま手を離したらどこまで落ちるか。hard_drop() と同じ計算で、盤面は変えない"""
    while can_place(board, shape, x, y + 1):
        y += 1
    return y


# ── 画面の部品 ──────────────────────────────────────────────────────────

score_label = document.querySelector("#score")
level_label = document.querySelector("#level")
lines_label = document.querySelector("#lines")
message = document.querySelector("#message")
start_button = document.querySelector("#start-btn")
canvas = document.querySelector("#screen")

# ── Three.js の舞台 ──────────────────────────────────────────────────────
#   index.html が window.THREE と window.ADDONS を置いてくれている。
#   Python からは「JS のクラスを .new() で作る」「引数の辞書は js() で JS のオブジェクトに直す」の 2 つだけ覚えればよい。

THREE = window.THREE
ADDONS = window.ADDONS
VIEW_W, VIEW_H = 480, 640            # 2 回目で横に広げた。左にホールド、右に「つぎ」を置くため

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
GHOST_MATS = {  # ゴースト用。同じ色を薄く透かす
    name: THREE.MeshBasicMaterial.new(js(color=color, transparent=True, opacity=0.22))
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

# 盤の外の小さなミノ。左にホールド 1 つ、右に「つぎ」3 つ。どのミノも 4 マスなので 4 個ずつ持てば足りる
MINI = 0.5                                             # 盤のブロックの半分の大きさ
SLOT_X = WIDTH / 2 + 2.9                               # 盤のふちから外へどれだけ離すか
SLOTS = {"hold": (-SLOT_X, 7.6)}                       # 名前 → 舞台の (x, y)。ミノの中心をここに置く
for i in range(NEXT_COUNT):
    SLOTS[f"next{i}"] = (SLOT_X, 7.6 - i * 2.6)

minis = {}
for slot in SLOTS:
    group = []
    for _ in range(4):
        block = THREE.Mesh.new(BLOCK_GEO, BLOCK_MATS["T"])
        block.scale.set(MINI, MINI, MINI)
        block.visible = False
        scene.add(block)
        group.append(block)
    minis[slot] = group


def show_mini(slot, name):
    """盤の外の枠に、名前のミノを小さく置く。None なら隠す"""
    sx, sy = SLOTS[slot]
    blocks = minis[slot]
    for b in blocks:
        b.visible = False
    if name is None:
        return
    shape = SHAPES[name]
    w, h = len(shape[0]), len(shape)
    i = 0
    for dy in range(h):
        for dx in range(w):
            if shape[dy][dx] == 0:
                continue
            b = blocks[i]
            b.material = BLOCK_MATS[name]
            b.position.set(sx + (dx - w / 2 + 0.5) * MINI, sy - (dy - h / 2 + 0.5) * MINI, 0.0)
            b.visible = True
            i += 1


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
    "level": 1,
    "playing": False,
    "next_fall": 0.0,
    "bag": [],          # 7-bag。空になったら refill() で 7 種を補充
    "queue": [],        # これから出るミノの名前。先頭が次
    "hold": None,       # ホールド中のミノの名前
    "can_hold": True,   # このミノでまだホールドしていないか（1 ミノにつき 1 回）
}


def draw():
    """CLI 版の render() にあたる。200 個のブロックの「見せる／隠す」と色を切り替えて描き直す。

    盤面の上に、いまのミノ（濃い）とゴースト（薄い）を重ねる。両方あるマスは濃いほうが勝つ。
    """
    if state["playing"]:
        view = place(state["board"], state["shape"], state["x"], state["y"], state["name"])
        gy = ghost_y(state["board"], state["shape"], state["x"], state["y"])
        ghost = place(state["board"], state["shape"], state["x"], gy, state["name"])
    else:
        view = state["board"]
        ghost = view

    for y in range(HEIGHT):
        for x in range(WIDTH):
            value = view[y][x]
            block = cells[y * WIDTH + x]  # 1 本のリストを 2 次元として使う
            if value != 0:
                block.visible = True
                block.material = BLOCK_MATS[value]
            elif ghost[y][x] != 0:
                block.visible = True
                block.material = GHOST_MATS[ghost[y][x]]
            else:
                block.visible = False

    show_mini("hold", state["hold"])
    for i in range(NEXT_COUNT):
        show_mini(f"next{i}", state["queue"][i] if i < len(state["queue"]) else None)

    renderer.render(scene, camera)  # 盤面が変わったときだけ描く。動きの補間は次の回で
    score_label.textContent = str(state["score"])
    level_label.textContent = str(state["level"])
    lines_label.textContent = str(state["lines"])


def next_piece():
    """袋 → 待ち行列 → いまのミノ、と 1 つずつ送る。待ち行列は常に NEXT_COUNT 個見えている"""
    while len(state["queue"]) <= NEXT_COUNT:
        refill(state["bag"])
        state["queue"].append(state["bag"].pop())

    name = state["queue"].pop(0)
    shape, x = take(name)
    state["name"] = name
    state["shape"] = shape
    state["x"] = x
    state["y"] = 0
    state["can_hold"] = True


def move(dx):
    """左右に動かす。置けないときは何もしない。"""
    if can_place(state["board"], state["shape"], state["x"] + dx, state["y"]):
        state["x"] += dx
        draw()


def turn():
    """回して、置ける位置を KICKS の順に探す。どこにも置けなければ回さない（壁蹴り）。"""
    turned = rotate(state["shape"])
    for kx, ky in KICKS:
        if can_place(state["board"], turned, state["x"] + kx, state["y"] + ky):
            state["shape"] = turned
            state["x"] += kx
            state["y"] += ky
            draw()
            return


def hold():
    """いまのミノを脇に置き、代わりにホールドしていたミノ（なければ次のミノ）を出す。1 ミノにつき 1 回だけ。"""
    if not state["can_hold"]:
        return

    kept = state["hold"]
    state["hold"] = state["name"]

    if kept is None:
        next_piece()
    else:
        shape, x = take(kept)
        state["name"] = kept
        state["shape"] = shape
        state["x"] = x
        state["y"] = 0

    state["can_hold"] = False   # 出したミノはホールドし直せない（無限に入れ替えられてしまう）
    draw()


def lock():
    """落ちられなくなったミノを盤面に焼き付けて、次のミノを出す。"""
    board = place(state["board"], state["shape"], state["x"], state["y"], state["name"])
    board, cleared = clear_lines(board)

    state["board"] = board
    state["lines"] += cleared
    state["score"] += SCORES[cleared] * state["level"]              # レベルが上がるほど 1 列の値打ちが上がる
    state["level"] = state["lines"] // LINES_PER_LEVEL + 1

    next_piece()

    if not can_place(board, state["shape"], state["x"], 0):  # 出す場所がもう無い
        finish()


def fall():
    """1 マス落とす。落ちられなければ固定。CLI 版の "down" の枝と同じ。"""
    state["next_fall"] = time.time() + fall_seconds(state["level"])

    if can_place(state["board"], state["shape"], state["x"], state["y"] + 1):
        state["y"] += 1
    else:
        lock()

    draw()


def hard_drop():
    """一番下まで一気に落とす。次の tick でそのまま固定される。"""
    state["y"] = ghost_y(state["board"], state["shape"], state["x"], state["y"])
    state["next_fall"] = time.time()
    draw()


def finish():
    """ゲームオーバー。"""
    state["playing"] = False
    message.textContent = f"ゲームオーバー — スコア {state['score']}（レベル {state['level']}）"
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
    state["score"] = 0
    state["lines"] = 0
    state["level"] = 1
    state["bag"] = []
    state["queue"] = []
    state["hold"] = None
    next_piece()
    state["playing"] = True
    state["next_fall"] = time.time() + fall_seconds(1)

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
    elif key == "hold":
        hold()


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


@when("click", "#hold-btn")
def on_hold(event):
    act("hold")


# Pyodide の読み込みが終わってから実行される＝ここが準備完了の合図
document.querySelector("#loading").hidden = True
start_button.disabled = False
draw()
