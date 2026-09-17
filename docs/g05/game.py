"""オセロ（ブラウザ版）

CLI 版（g05-othello/main.py）とルールまわりは同じ。
make_board() / opponent() / flips_in_direction() / flips_at() / valid_moves() /
apply_move() / count_stones() / move_name() / result_text() は
1 文字も変えずにそのまま持ってきている。

持ってこなかったのは board_text() と parse_move() と main() だけ。
つまり違うのは入口と出口で、入口は "d3" の文字入力ではなくマスのクリック、
出口は文字の盤面ではなく 64 個の <div> になっている。

ブラウザ版だけの追加として、白をコンピュータに任せるモードがある（choose_move）。

（2026-09-18・1 回目）出口を 64 個の <div> から Three.js の立体の盤に差し替えた。
入口も <div> のクリックから「画面の点 → 盤のマス」の変換（Raycaster）に変わった。
ルールの 9 関数は変えていない。
（2 回目）GSAP で動きを足した。置いた石は上から落ちて跳ね、挟んだ石は近い順に跳ねながら裏返る。
play() が async になり、動きが終わるまで手番を渡さない。
"""

import asyncio
import math

from pyodide.ffi import create_proxy, to_js
from pyscript import document, when, window

SIZE = 8

EMPTY = 0
BLACK = 1
WHITE = 2

MARKS = {
    EMPTY: "・",
    BLACK: "●",
    WHITE: "○",
}

DIRECTIONS = [
    (-1, -1), (-1, 0), (-1, 1),
    (0, -1),           (0, 1),
    (1, -1),  (1, 0),  (1, 1),
]

CPU_WAIT = 0.55  # コンピュータが考えているように見せるための間
PASS_WAIT = 0.9  # パスの表示を読む時間

DROP_SECONDS = 0.45   # 置いた石が落ちて跳ねるまで
FLIP_SECONDS = 0.35   # 石 1 枚が裏返るのにかかる時間
FLIP_STEP = 0.07      # 置いた石から 1 マス離れるごとに、裏返り始めが遅れる時間（波のように広がる）
FLIP_HOP = 0.6        # 裏返るとき、どれだけ跳ね上がるか


# --- ここから 9 つは CLI 版からそのまま ---

def make_board():
    """初期配置の盤面を作って返す。中央4マスに石が置かれた状態。"""
    board = [[EMPTY] * SIZE for _ in range(SIZE)]
    board[3][3] = WHITE
    board[3][4] = BLACK
    board[4][3] = BLACK
    board[4][4] = WHITE
    return board


def count_stones(board):
    """石の数を (黒, 白) のタプルで返す。"""
    black = sum(row.count(BLACK) for row in board)
    white = sum(row.count(WHITE) for row in board)
    return black, white


def opponent(player):
    """相手の色を返す。"""
    return WHITE if player == BLACK else BLACK


def flips_in_direction(board, row, col, dr, dc, player):
    """(row, col) に player が置いたとき、(dr, dc) 方向でひっくり返る石の座標リストを返す。

    ひっくり返せないときは空リスト。
    """
    flips = []

    r = row + dr
    c = col + dc

    # 相手の石が続くあいだ、その座標を覚えながら進む
    while 0 <= r < SIZE and 0 <= c < SIZE and board[r][c] == opponent(player):
        flips.append((r, c))
        r += dr
        c += dc

    # 止まった先が自分の石で、間に相手の石が1つ以上あれば「挟めた」
    if flips and 0 <= r < SIZE and 0 <= c < SIZE and board[r][c] == player:
        return flips

    return []


def flips_at(board, row, col, player):
    """(row, col) に player が置いたとき、8方向ぶんまとめてひっくり返る石を返す。"""
    if board[row][col] != EMPTY:
        return []

    flips = []
    for dr, dc in DIRECTIONS:
        flips += flips_in_direction(board, row, col, dr, dc, player)
    return flips


def valid_moves(board, player):
    """置けるマスと、そこに置いたときひっくり返る石を、辞書にして返す。

    キーが (行, 列)、値がひっくり返る石の座標リスト。
    """
    moves = {}
    for row in range(SIZE):
        for col in range(SIZE):
            flips = flips_at(board, row, col, player)
            if flips:
                moves[(row, col)] = flips
    return moves


def move_name(row, col):
    """(2, 3) を "d3" のような表記にして返す。"""
    return chr(ord("a") + col) + str(row + 1)


def apply_move(board, row, col, flips, player):
    """石を置き、flips に入っている石をすべて player の色にする。"""
    board[row][col] = player
    for r, c in flips:
        board[r][c] = player


def result_text(board):
    """終局の結果を文字列にして返す。print はしない。"""
    black, white = count_stones(board)

    if black > white:
        winner = "● の勝ち！"
    elif white > black:
        winner = "○ の勝ち！"
    else:
        winner = "引き分け"

    return f"● {black} - ○ {white}    {winner}"


# --- ここから下がブラウザ版だけの部分 ---

def choose_move(moves):
    """一番たくさんひっくり返せる手を選ぶ。先は読まない。"""
    return max(moves, key=lambda pos: len(moves[pos]))


canvas = document.querySelector("#screen")
black_label = document.querySelector("#black")
white_label = document.querySelector("#white")
turn_label = document.querySelector("#turn")
message = document.querySelector("#message")
two_button = document.querySelector("#mode-two")
cpu_button = document.querySelector("#mode-cpu")

# ── Three.js の舞台 ──────────────────────────────────────────────────────
#   index.html が window.THREE と window.ADDONS を置いてくれている。
#   「JS のクラスは .new() で作る」「引数の辞書は js() で JS のオブジェクトに直す」の 2 つだけ覚えればよい。

THREE = window.THREE
ADDONS = window.ADDONS
gsap = window.gsap                                    # 動きの補間。「y を 0.45 秒で 0.11 に、跳ねながら」を 1 行で
VIEW = 480

WOOD = 0x7A4E2A        # 盤の木枠
FELT = 0x2A6B4C        # 盤の緑のフェルト
FELT_LINE = 0x1F5A3E   # マス目の線
STONE_BLACK = 0x0A0C10
STONE_WHITE = 0xF2F2EE
STONE_Y = 0.11         # 石の中心の高さ（フェルトの上面 0.06 ＋ 厚み 0.1 の半分）


def js(**kw):
    """Python のキーワード引数 → JS のオブジェクト。Three.js のコンストラクタは {color: ..., roughness: ...} を受け取る"""
    return to_js(kw, dict_converter=window.Object.fromEntries)


renderer = THREE.WebGLRenderer.new(js(canvas=canvas, antialias=True))
renderer.setPixelRatio(min(2.0, window.devicePixelRatio))
renderer.setSize(VIEW, VIEW, False)                   # False: CSS の大きさは触らない（スマホでは縮む）
renderer.shadowMap.enabled = True                     # 石の影を落とす
renderer.shadowMap.type = THREE.PCFSoftShadowMap
renderer.toneMapping = THREE.ACESFilmicToneMapping

scene = THREE.Scene.new()
scene.background = THREE.Color.new(0x1A1D24)
pmrem = THREE.PMREMGenerator.new(renderer)            # 「部屋」を映り込みの環境に。石のつやが本物のプラスチックになる
scene.environment = pmrem.fromScene(ADDONS.RoomEnvironment.new(), 0.04).texture

camera = THREE.PerspectiveCamera.new(40, 1.0, 0.5, 100)
camera.position.set(0.0, 9.8, 8.2)                    # 手前の斜め上から盤を見下ろす
camera.lookAt(0.0, 0.0, 0.0)

key_light = THREE.DirectionalLight.new(0xFFF4E0, 1.8)   # 主光。少し暖かい色で右上から
key_light.position.set(5.0, 10.0, 4.0)
key_light.castShadow = True
key_light.shadow.mapSize.set(2048, 2048)
key_light.shadow.camera.left = -6.0                     # 影を計算する範囲。盤がすっぽり入る大きさ
key_light.shadow.camera.right = 6.0
key_light.shadow.camera.top = 6.0
key_light.shadow.camera.bottom = -6.0
key_light.shadow.camera.near = 1.0
key_light.shadow.camera.far = 30.0
key_light.shadow.bias = -0.0005
scene.add(key_light)
scene.add(THREE.HemisphereLight.new(0xBFD4FF, 0x3A2A1A, 0.4))  # 空からの青と地面からの茶。影の中を真っ黒にしない


def cell_pos(row, col):
    """盤面の (row, col)（左上が 0,0）→ 舞台の (x, z)。盤の中心が原点、row が手前（+z）に増える"""
    return (col - SIZE / 2 + 0.5, row - SIZE / 2 + 0.5)


# 盤。木枠の上に緑のフェルト、その上にマス目の線。一度作ったら動かない
frame = THREE.Mesh.new(THREE.BoxGeometry.new(SIZE + 1.2, 0.6, SIZE + 1.2),
                       THREE.MeshStandardMaterial.new(js(color=WOOD, roughness=0.55, metalness=0.0)))
frame.position.set(0.0, -0.3, 0.0)
frame.receiveShadow = True
scene.add(frame)

felt = THREE.Mesh.new(THREE.BoxGeometry.new(SIZE + 0.1, 0.06, SIZE + 0.1),
                      THREE.MeshStandardMaterial.new(js(color=FELT, roughness=1.0, metalness=0.0)))
felt.position.set(0.0, 0.03, 0.0)
felt.receiveShadow = True
scene.add(felt)

line_mat = THREE.MeshBasicMaterial.new(js(color=FELT_LINE))
for i in range(SIZE + 1):
    v = THREE.Mesh.new(THREE.BoxGeometry.new(0.03, 0.012, SIZE), line_mat)
    v.position.set(i - SIZE / 2, 0.065, 0.0)
    scene.add(v)
    h = THREE.Mesh.new(THREE.BoxGeometry.new(SIZE, 0.012, 0.03), line_mat)
    h.position.set(0.0, 0.065, i - SIZE / 2)
    scene.add(h)
for sx, sz in [(-2, -2), (2, -2), (-2, 2), (2, 2)]:     # 本物の盤にある 4 つの点
    dot = THREE.Mesh.new(THREE.CylinderGeometry.new(0.07, 0.07, 0.012, 16), line_mat)
    dot.position.set(sx, 0.066, sz)
    scene.add(dot)

# 石。円盤の上面が黒、下面が白。黒を見せるときは上向き、白は 180 度回して下面を見せる
STONE_GEO = THREE.CylinderGeometry.new(0.42, 0.42, 0.1, 40)
side_mat = THREE.MeshStandardMaterial.new(js(color=0x8A8A88, roughness=0.5, metalness=0.0))
black_mat = THREE.MeshPhysicalMaterial.new(js(color=STONE_BLACK, roughness=0.35, metalness=0.0,
                                              clearcoat=1.0, clearcoatRoughness=0.15, envMapIntensity=0.35))  # 映り込みが強いと黒が灰色になる
white_mat = THREE.MeshPhysicalMaterial.new(js(color=STONE_WHITE, roughness=0.3, metalness=0.0,
                                              clearcoat=1.0, clearcoatRoughness=0.2, envMapIntensity=0.5))
STONE_MATS = to_js([side_mat, black_mat, white_mat])   # CylinderGeometry の面の順: 側面・上面・下面
FACE_UP = {BLACK: 0.0, WHITE: math.pi}                 # 色 → 石の回転（x 軸まわり）

stones = []   # 64 個の石。作るのは一度だけで、あとは「見せる／隠す」と向きを切り替える
for row in range(SIZE):
    for col in range(SIZE):
        x, z = cell_pos(row, col)
        stone = THREE.Mesh.new(STONE_GEO, STONE_MATS)
        stone.position.set(x, STONE_Y, z)
        stone.castShadow = True
        stone.visible = False
        scene.add(stone)
        stones.append(stone)

# 置ける場所の印。薄い輪
RING_GEO = THREE.TorusGeometry.new(0.3, 0.035, 8, 40)
ring_mat = THREE.MeshBasicMaterial.new(js(color=0xFFFFFF, transparent=True, opacity=0.35))
ring_hover_mat = THREE.MeshBasicMaterial.new(js(color=0xFFFFFF, transparent=True, opacity=0.8))
rings = []
for row in range(SIZE):
    for col in range(SIZE):
        x, z = cell_pos(row, col)
        ring = THREE.Mesh.new(RING_GEO, ring_mat)
        ring.position.set(x, 0.075, z)
        ring.rotation.x = math.pi / 2                  # 輪を寝かせる
        ring.visible = False
        scene.add(ring)
        rings.append(ring)

# 最後に置いた石の印。小さな赤い玉
marker = THREE.Mesh.new(THREE.SphereGeometry.new(0.07, 16, 12),
                        THREE.MeshStandardMaterial.new(js(color=0xE0483A, roughness=0.4, metalness=0.0)))
marker.visible = False
scene.add(marker)

# ── 画面の点 → 盤のマス（Raycaster）───────────────────────────────────
#   <div> のクリックが使えなくなった代わり。マウスの位置からカメラの向きに光線を飛ばし、
#   フェルトに当たった点の x, z をマスの番号に直す。

raycaster = THREE.Raycaster.new()
pointer = THREE.Vector2.new()


def pick(event):
    """クリックやマウスの位置 → (row, col)。盤の外なら None"""
    rect = canvas.getBoundingClientRect()
    pointer.x = (event.clientX - rect.left) / rect.width * 2 - 1     # 画面の左端 -1 〜 右端 +1
    pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1  # 上端 +1 〜 下端 -1（y は上が正）
    raycaster.setFromCamera(pointer, camera)
    hits = raycaster.intersectObject(felt)
    if hits.length == 0:
        return None
    point = hits[0].point
    col = math.floor(point.x + SIZE / 2)
    row = math.floor(point.z + SIZE / 2)
    if 0 <= row < SIZE and 0 <= col < SIZE:
        return (row, col)
    return None


# CLI 版では素の変数だった board / player / passes を、辞書にまとめて持つ。
# クリックのたびに中断・再開するので、ループの中には置けない。
state = {
    "board": make_board(),
    "player": BLACK,
    "moves": {},
    "passes": 0,
    "playing": False,
    "vs_cpu": True,
    "hover": None,      # マウスが乗っているマス
    "last": None,       # 最後に置いたマス
    "busy": False,      # 石が動いているあいだ True。クリックを受けない
}


def set_message(text):
    message.textContent = text
    message.hidden = not text


def cpu_thinking():
    """コンピュータの手番かどうか。True のあいだはクリックを受けない。"""
    return state["vs_cpu"] and state["player"] == WHITE


def draw_rings():
    """置ける場所の輪だけを描き直す。石が動いている最中にマウスが動いても、石には触らない"""
    show_hints = state["playing"] and not cpu_thinking() and not state["busy"]
    for index, ring in enumerate(rings):
        row, col = divmod(index, SIZE)
        ring.visible = show_hints and (row, col) in state["moves"]
        ring.material = ring_hover_mat if state["hover"] == (row, col) else ring_mat


def draw():
    """CLI 版の board_text() にあたる。64 個の石の「見せる／隠す」と向き、置ける場所の輪を盤面に合わせる。

    動きが終わったあとに呼んで、石の位置と向きを盤面の真実に揃える役目もある。
    """
    board = state["board"]

    for index, stone in enumerate(stones):
        row, col = divmod(index, SIZE)  # 1本のリストを2次元として使う
        value = board[row][col]
        stone.visible = value != EMPTY
        if value != EMPTY:
            stone.rotation.x = FACE_UP[value]
            stone.position.y = STONE_Y

    draw_rings()

    marker.visible = state["last"] is not None
    if state["last"] is not None:
        x, z = cell_pos(*state["last"])
        marker.position.set(x, STONE_Y + 0.05 + 0.07, z)

    black, white = count_stones(board)
    black_label.textContent = str(black)
    white_label.textContent = str(white)

    if not state["playing"]:
        turn_label.textContent = "終局"
    elif cpu_thinking():
        turn_label.textContent = "○ が考え中"
    else:
        turn_label.textContent = f"{MARKS[state['player']]} の番"


def animate_move(row, col, flips, player):
    """石を置く動きと、挟んだ石が裏返る動きを始める。終わるまでの秒数を返す。

    盤面（真実）は apply_move() ですでに書き換わっている。ここは見た目を後から追いつかせる係。
    """
    stone = stones[row * SIZE + col]
    stone.rotation.x = FACE_UP[player]
    stone.position.y = STONE_Y + 2.5                  # 上から落とす
    stone.visible = True
    gsap.to(stone.position, js(y=STONE_Y, duration=DROP_SECONDS, ease="bounce.out"))

    farthest = 0
    for r, c in flips:
        dist = max(abs(r - row), abs(c - col))        # 置いた石から何マス目か
        farthest = max(farthest, dist)
        delay = DROP_SECONDS * 0.6 + FLIP_STEP * dist  # 近い石から順に、波のように
        target = stones[r * SIZE + c]
        gsap.to(target.rotation, js(x=target.rotation.x + math.pi, duration=FLIP_SECONDS, delay=delay, ease="power2.inOut"))
        gsap.to(target.position, js(y=STONE_Y + FLIP_HOP, duration=FLIP_SECONDS / 2, delay=delay,
                                    yoyo=True, repeat=1, ease="power1.out"))

    return DROP_SECONDS * 0.6 + FLIP_STEP * farthest + FLIP_SECONDS + 0.05


async def play(pos):
    """石を置いて手番を渡す。CLI 版の while ループの後半と同じ。動きが終わるまで待つ。"""
    row, col = pos
    flips = state["moves"][pos]
    player = state["player"]

    apply_move(state["board"], row, col, flips, player)
    set_message(f"{MARKS[player]} {move_name(row, col)} → {len(flips)} 枚ひっくり返した")
    state["last"] = pos
    state["player"] = opponent(player)

    state["busy"] = True
    draw_rings()                                      # 動いている最中は輪を消す
    await asyncio.sleep(animate_move(row, col, flips, player))
    state["busy"] = False
    draw()                                            # 回転を 0 / π に揃え直す（π を足し続けない）


def finish():
    """両者とも置けなくなった＝終局。"""
    state["playing"] = False
    state["moves"] = {}
    set_message(result_text(state["board"]))
    draw()


async def advance():
    """手番を進める係。CLI 版の while ループの前半（パス判定）がここに来ている。

    人が打つ番になったら return して、クリックを待つ。
    """
    while state["playing"]:
        state["moves"] = valid_moves(state["board"], state["player"])
        draw()

        if not state["moves"]:
            state["passes"] += 1
            if state["passes"] == 2:
                finish()
                return

            set_message(f"{MARKS[state['player']]} は置ける場所がないのでパス")
            state["player"] = opponent(state["player"])
            await asyncio.sleep(PASS_WAIT)
            continue

        state["passes"] = 0  # 置けたので、パスの連続は途切れた

        if not cpu_thinking():
            return  # ここから先は人のクリック待ち

        await asyncio.sleep(CPU_WAIT)
        await play(choose_move(state["moves"]))


def start():
    gsap.globalTimeline.clear()                       # 動いている途中の石があれば止める
    state["board"] = make_board()
    state["player"] = BLACK
    state["moves"] = {}
    state["passes"] = 0
    state["playing"] = True
    state["last"] = None
    state["busy"] = False

    set_message("")
    asyncio.ensure_future(advance())


async def human_turn(pos):
    await play(pos)
    await advance()


def set_mode(vs_cpu):
    state["vs_cpu"] = vs_cpu
    two_button.className = "mode" if vs_cpu else "mode is-on"
    cpu_button.className = "mode is-on" if vs_cpu else "mode"
    start()


@when("click", "#screen")
def on_board_click(event):
    """盤のクリックが CLI 版の input() にあたる。"""
    if not state["playing"] or cpu_thinking() or state["busy"]:
        return

    pos = pick(event)
    if pos is None or pos not in state["moves"]:  # 置けないマスは黙って無視する
        return

    asyncio.ensure_future(human_turn(pos))


@when("pointermove", "#screen")
def on_board_move(event):
    """マウスが乗っている置ける場所の輪を濃くする"""
    pos = pick(event)
    if pos != state["hover"]:
        state["hover"] = pos
        draw_rings()


@when("click", "#start-btn")
def on_start(event):
    start()


@when("click", "#mode-two")
def on_mode_two(event):
    set_mode(False)


@when("click", "#mode-cpu")
def on_mode_cpu(event):
    set_mode(True)


# ── 描画の輪。ブラウザの描画のたび（1 秒に 60 回ほど）に 1 枚描く ──────────

def frame(t):
    renderer.render(scene, camera)
    window.requestAnimationFrame(frame_proxy)


frame_proxy = create_proxy(frame)   # Python の関数を JS に渡すときは proxy で包む
window.requestAnimationFrame(frame_proxy)

# Pyodide の読み込みが終わってから実行される＝ここが準備完了の合図
document.querySelector("#loading").hidden = True
document.querySelector("#start-btn").disabled = False
start()
