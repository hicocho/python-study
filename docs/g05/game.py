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
（3 回目）Tone.js で音を足した。置く「カッ」、裏返る「パタ」（枚数ぶん音程が上がる）、パス、終局の和音。
鳴る時刻は動きと同じ計算から出している。
（4 回目）postprocessing で光。置ける場所の輪と最後の石の印がにじんで光り、画面の隅が暗くなる。
終局は勝った色の石が脈打って光り、カメラが盤のまわりを回る。
（5 回目）ゲーム性。CPU の強さ 3 段階（1 手読み／マスの値打ち表／3 手先読み）、待った、
ドラッグで盤を回して見る角度を変える（OrbitControls）。
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

# ── CPU（5 回目で 3 段階に）────────────────────────────────────────────

WEIGHTS = [  # マスの値打ち。角が最高、角の隣（取られると角を渡す）は最低。上下左右対称
    [120, -20,  20,   5,   5,  20, -20, 120],
    [-20, -40,  -5,  -5,  -5,  -5, -40, -20],
    [ 20,  -5,  15,   3,   3,  15,  -5,  20],
    [  5,  -5,   3,   3,   3,   3,  -5,   5],
    [  5,  -5,   3,   3,   3,   3,  -5,   5],
    [ 20,  -5,  15,   3,   3,  15,  -5,  20],
    [-20, -40,  -5,  -5,  -5,  -5, -40, -20],
    [120, -20,  20,   5,   5,  20, -20, 120],
]
SEARCH_DEPTH = 3     # 「つよい」が読む手数（自分・相手・自分）
LEVEL_KEY = "g05-level"


def choose_greedy(board, moves, player):
    """やさしい：一番たくさんひっくり返せる手。先は読まない（もとの choose_move）"""
    return max(moves, key=lambda pos: len(moves[pos]))


def evaluate(board, player):
    """player から見た盤面の点数。自分の石の値打ちの合計 − 相手の石の値打ちの合計"""
    score = 0
    for r in range(SIZE):
        for c in range(SIZE):
            v = board[r][c]
            if v == player:
                score += WEIGHTS[r][c]
            elif v != EMPTY:
                score -= WEIGHTS[r][c]
    return score


def after(board, pos, flips, player):
    """置いたあとの盤面を新しく作って返す。元の盤面は変えない（place() と同じ考え）"""
    new_board = [row[:] for row in board]
    apply_move(new_board, pos[0], pos[1], flips, player)
    return new_board


def choose_weighted(board, moves, player):
    """ふつう：置いたあとの盤面を WEIGHTS で採点して、一番高い手"""
    return max(moves, key=lambda pos: evaluate(after(board, pos, moves[pos], player), player))


def search(board, player, depth, alpha, beta):
    """つよい の中身：depth 手先まで読んで、player から見た最善の点数を返す（ネガマックス＋αβ枝刈り）。

    「自分の最善」は「相手の最善を最小にする手」なので、手番が替わるたびに符号を反転させて同じ関数で読む。
    alpha/beta は「これより悪い枝はもう読まなくてよい」という足切り線。
    """
    if depth == 0:
        return evaluate(board, player)

    moves = valid_moves(board, player)
    if not moves:
        if not valid_moves(board, opponent(player)):          # 両者とも置けない＝終局。石の差で決める
            black, white = count_stones(board)
            diff = black - white if player == BLACK else white - black
            return diff * 1000
        return -search(board, opponent(player), depth - 1, -beta, -alpha)   # パス

    best = -10 ** 9
    for pos, flips in sorted(moves.items(), key=lambda kv: -WEIGHTS[kv[0][0]][kv[0][1]]):  # 良さそうな手から読むと枝刈りが効く
        value = -search(after(board, pos, flips, player), opponent(player), depth - 1, -beta, -alpha)
        best = max(best, value)
        alpha = max(alpha, value)
        if alpha >= beta:
            break
    return best


def choose_search(board, moves, player):
    """つよい：SEARCH_DEPTH 手先まで読んで一番点数の高い手"""
    best, best_pos = -10 ** 9, None
    for pos, flips in sorted(moves.items(), key=lambda kv: -WEIGHTS[kv[0][0]][kv[0][1]]):
        value = -search(after(board, pos, flips, player), opponent(player), SEARCH_DEPTH - 1, -10 ** 9, 10 ** 9)
        if value > best:
            best, best_pos = value, pos
    return best_pos


LEVELS = {1: choose_greedy, 2: choose_weighted, 3: choose_search}   # 強さ → 手を選ぶ関数


def choose_move(board, moves, player):
    return LEVELS[state["level"]](board, moves, player)


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
Tone = window.Tone                                    # 音。楽器（Synth）を作って triggerAttackRelease(音名, 長さ, 時刻)
PP = window.PP                                        # 後処理。描いた絵にブルーム（光のにじみ）とビネット（周辺減光）をかける
VIEW = 480
SOUND_KEY = "g05-sound"                               # 音のオン／オフを覚えておく localStorage のキー

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
renderer.toneMapping = THREE.NoToneMapping           # 色の丸め込みは後処理の最後で 1 回だけやる（2 重にかけると白っぽくなる）

scene = THREE.Scene.new()
scene.background = THREE.Color.new(0x1A1D24)
pmrem = THREE.PMREMGenerator.new(renderer)            # 「部屋」を映り込みの環境に。石のつやが本物のプラスチックになる
scene.environment = pmrem.fromScene(ADDONS.RoomEnvironment.new(), 0.04).texture

camera = THREE.PerspectiveCamera.new(40, 1.0, 0.5, 100)
CAM_Y, CAM_R = 9.8, 8.2                               # カメラの高さと、盤の中心からの水平距離
camera.position.set(0.0, CAM_Y, CAM_R)                # 手前の斜め上から盤を見下ろす
camera.lookAt(0.0, 0.0, 0.0)

# ドラッグで盤のまわりを回れる。真上と真横には行かせない、寄りすぎ・引きすぎもさせない
controls = ADDONS.OrbitControls.new(camera, canvas)
controls.enablePan = False
controls.minDistance = 10.0
controls.maxDistance = 17.0
controls.minPolarAngle = 0.15                         # 真上から（0）どれだけ傾けられるか
controls.maxPolarAngle = 1.15
controls.enableDamping = True                         # 指を離してもすっと止まらず、少し滑る
controls.autoRotateSpeed = 1.2                        # 終局に回る速さ

# 後処理の列。描く → ブルーム＋ビネット＋色の丸め込み → 画面
composer = PP.EffectComposer.new(renderer, js(frameBufferType=THREE.HalfFloatType))
composer.addPass(PP.RenderPass.new(scene, camera))
bloom = PP.BloomEffect.new(js(luminanceThreshold=2.0, luminanceSmoothing=0.1, intensity=1.0, mipmapBlur=True, radius=0.65))  # しきい値 2.0: 白い石の光の反射（角度によって 1.5 を超える）は拾わず、emissive を 3 以上にした物だけ光る
vignette = PP.VignetteEffect.new(js(darkness=0.5, offset=0.3))
composer.addPass(PP.EffectPass.new(camera, bloom, vignette, PP.ToneMappingEffect.new(js(mode=PP.ToneMappingMode.ACES_FILMIC))))

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
white_mat = THREE.MeshPhysicalMaterial.new(js(color=STONE_WHITE, roughness=0.45, metalness=0.0,
                                              clearcoat=0.8, clearcoatRoughness=0.35, envMapIntensity=0.5))  # 白はつやを抑える。強いと光の反射がブルームに拾われる
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

# 置ける場所の印。淡く光る輪（emissive をしきい値より明るくして、ブルームに拾わせる）
RING_GEO = THREE.TorusGeometry.new(0.3, 0.035, 8, 40)
ring_mat = THREE.MeshStandardMaterial.new(js(color=0xFFFFFF, emissive=0xFFF3C0, emissiveIntensity=3.0, transparent=True, opacity=0.5))
ring_hover_mat = THREE.MeshStandardMaterial.new(js(color=0xFFFFFF, emissive=0xFFF3C0, emissiveIntensity=5.0, transparent=True, opacity=0.95))
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

# ── 音 ────────────────────────────────────────────────────────────────
#   ブラウザは「利用者が触るまで音を出せない」。Tone.start() をクリックの中で呼んで許可をもらう。

FLIP_NOTES = ["C5", "D5", "E5", "G5", "A5", "C6", "D6", "E6", "G6", "A6", "C7"]   # 裏返る順に上がる（ペンタトニック）


class Speaker:
    """出来事 → 音。楽器は 4 つ。start() までは鳴らない。

    楽器はすべて PolySynth（同時発音できる）にしてある。単音の Synth は「時刻が前より必ず後」でないと
    例外を投げるので、同じ距離の石が 2 枚同時に裏返る（＝同じ時刻に 2 音）とゲームごと止まってしまった。
    """

    def __init__(self):
        self.on = (window.localStorage.getItem(SOUND_KEY) or "on") == "on"
        self.ready = False
        self.clack = Tone.PolySynth.new(Tone.MembraneSynth, js(pitchDecay=0.02, octaves=3,
                                                                envelope=js(attack=0.001, decay=0.12, sustain=0.0, release=0.05))).toDestination()
        self.clack.volume.value = -6
        self.pata = Tone.PolySynth.new(Tone.Synth, js(oscillator=js(type="triangle"),
                                                      envelope=js(attack=0.005, decay=0.12, sustain=0.0, release=0.08))).toDestination()
        self.pata.volume.value = -10
        self.soft = Tone.PolySynth.new(Tone.Synth, js(oscillator=js(type="sine"),
                                                      envelope=js(attack=0.02, decay=0.3, sustain=0.0, release=0.2))).toDestination()
        self.soft.volume.value = -12
        self.chord = Tone.PolySynth.new(Tone.Synth, js(oscillator=js(type="triangle"),
                                                       envelope=js(attack=0.02, decay=0.6, sustain=0.2, release=1.2))).toDestination()
        self.chord.volume.value = -14

    def start(self):
        """利用者が触った瞬間に呼ぶ。2 回目からは何もしない"""
        if not self.ready:
            Tone.start()
            self.ready = True

    def can(self):
        return self.on and self.ready

    def play(self, synth, note, length, delay, velocity=1.0):
        """1 音鳴らす。音の失敗（時刻の重なりなど）でゲームを止めないよう、例外はここで握りつぶす"""
        if not self.can():
            return
        try:
            synth.triggerAttackRelease(note, length, Tone.now() + delay, velocity)
        except Exception as e:                        # 音が 1 つ抜けるだけ。盤は進む
            print("sound:", e)

    def place(self, delay):
        self.play(self.clack, "C2", "16n", delay)             # 盤に当たる
        self.play(self.clack, "C2", "32n", delay + 0.17, 0.4)  # 小さく跳ね返る

    def flip(self, order, delay):
        note = FLIP_NOTES[min(order, len(FLIP_NOTES) - 1)]
        self.play(self.pata, note, "16n", delay + order * 0.012)   # 同じ距離の石も少しだけずらす

    def pass_turn(self):
        self.play(self.soft, "G4", "8n", 0.0)
        self.play(self.soft, "E4", "8n", 0.18)

    def finish(self, winner):
        notes = ["C4", "E4", "G4", "C5"] if winner != EMPTY else ["C4", "Eb4", "G4", "Bb4"]  # 勝ちは明るく、引き分けは少し曇る
        for i, n in enumerate(notes):
            self.play(self.chord, n, "2n", i * 0.08)

    def toggle(self):
        self.on = not self.on
        window.localStorage.setItem(SOUND_KEY, "on" if self.on else "off")
        sound_button.textContent = "🔊 音" if self.on else "🔇 音"
        sound_button.className = "mode is-on" if self.on else "mode"


sound_button = document.querySelector("#sound-btn")
speaker = Speaker()
sound_button.textContent = "🔊 音" if speaker.on else "🔇 音"
sound_button.className = "mode is-on" if speaker.on else "mode"

# 最後に置いた石の印。小さな赤い玉
marker = THREE.Mesh.new(THREE.SphereGeometry.new(0.07, 16, 12),
                        THREE.MeshStandardMaterial.new(js(color=0xE0483A, emissive=0xFF3A2A, emissiveIntensity=4.0, roughness=0.4)))
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
    "level": int(window.localStorage.getItem(LEVEL_KEY) or "2"),   # CPU の強さ 1〜3
    "history": [],      # 「待った」で戻る先。人が打つ直前の盤面の写し
    "press": None,      # pointerdown の画面位置。動いていたらドラッグ（盤を回した）なのでクリックにしない
    "gen": 0,           # 局の世代。「はじめから」「待った」で増える。古い世代の advance() は目を覚ましたら黙って終わる
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
    speaker.place(DROP_SECONDS * 0.36)                # bounce.out が最初に底に着く時刻

    farthest = 0
    ordered = sorted(flips, key=lambda rc: max(abs(rc[0] - row), abs(rc[1] - col)))  # 近い順
    for order, (r, c) in enumerate(ordered):
        dist = max(abs(r - row), abs(c - col))        # 置いた石から何マス目か
        farthest = max(farthest, dist)
        delay = DROP_SECONDS * 0.6 + FLIP_STEP * dist  # 近い石から順に、波のように
        target = stones[r * SIZE + c]
        gsap.to(target.rotation, js(x=target.rotation.x + math.pi, duration=FLIP_SECONDS, delay=delay, ease="power2.inOut"))
        gsap.to(target.position, js(y=STONE_Y + FLIP_HOP, duration=FLIP_SECONDS / 2, delay=delay,
                                    yoyo=True, repeat=1, ease="power1.out"))
        speaker.flip(order, delay + FLIP_SECONDS / 2)  # 跳ねの頂点で鳴る。近い石ほど低く、遠くへ行くほど高く

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
    try:
        await asyncio.sleep(animate_move(row, col, flips, player))
    finally:
        state["busy"] = False                         # 動きの途中で何かが失敗しても、クリックを受けない状態のままにしない
    draw()                                            # 回転を 0 / π に揃え直す（π を足し続けない）


def finish():
    """両者とも置けなくなった＝終局。"""
    state["playing"] = False
    state["moves"] = {}
    set_message(result_text(state["board"]))
    black, white = count_stones(state["board"])
    winner = BLACK if black > white else WHITE if white > black else EMPTY
    speaker.finish(winner)
    draw()
    celebrate(winner)


def celebrate(winner):
    """終局の演出。勝った色の石が脈打つように光り、カメラが盤のまわりを回り始める"""
    controls.autoRotate = True
    if winner == BLACK:
        black_mat.emissive.set(0xFFB347)               # 黒は金色に、白はそのまま白く光る
        gsap.to(black_mat, js(emissiveIntensity=4.0, duration=0.9, yoyo=True, repeat=-1, ease="sine.inOut"))
    elif winner == WHITE:
        white_mat.emissive.set(0xFFFFFF)
        gsap.to(white_mat, js(emissiveIntensity=3.0, duration=0.9, yoyo=True, repeat=-1, ease="sine.inOut"))


async def advance():
    """手番を進める係。CLI 版の while ループの前半（パス判定）がここに来ている。

    人が打つ番になったら return して、クリックを待つ。
    """
    gen = state["gen"]
    while state["playing"] and state["gen"] == gen:
        state["moves"] = valid_moves(state["board"], state["player"])
        draw()

        if not state["moves"]:
            state["passes"] += 1
            if state["passes"] == 2:
                finish()
                return

            set_message(f"{MARKS[state['player']]} は置ける場所がないのでパス")
            speaker.pass_turn()
            state["player"] = opponent(state["player"])
            await asyncio.sleep(PASS_WAIT)
            continue

        state["passes"] = 0  # 置けたので、パスの連続は途切れた

        if not cpu_thinking():
            state["history"].append(snapshot())        # 人が打つ直前を覚えておく＝「待った」で戻る先
            return  # ここから先は人のクリック待ち

        await asyncio.sleep(CPU_WAIT)
        if state["gen"] != gen:                        # 眠っているあいだに「はじめから」か「待った」が押された
            return
        await play(choose_move(state["board"], state["moves"], state["player"]))


def snapshot():
    return ([row[:] for row in state["board"]], state["player"], state["last"], state["passes"])


def undo():
    """待った。人が最後に打つ直前の盤面に戻す。CPU の返しも一緒に消える"""
    if state["busy"] or not state["history"]:
        return
    if state["playing"] and not cpu_thinking():
        state["history"].pop()                         # いま人の番なら、その直前の写しは「今」なので 1 つ捨てて、その前へ
        if not state["history"]:
            return
    board, player, last, passes = state["history"].pop()

    gsap.globalTimeline.clear()
    black_mat.emissiveIntensity = 0.0
    white_mat.emissiveIntensity = 0.0
    controls.autoRotate = False
    state["gen"] += 1
    state["board"] = board
    state["player"] = player
    state["last"] = last
    state["passes"] = passes
    state["playing"] = True
    set_message("待った")
    draw()
    asyncio.ensure_future(advance())


def start():
    gsap.globalTimeline.clear()                       # 動いている途中の石や、終局の光があれば止める
    black_mat.emissiveIntensity = 0.0
    white_mat.emissiveIntensity = 0.0
    controls.autoRotate = False
    gsap.to(camera.position, js(x=0.0, y=CAM_Y, z=CAM_R, duration=0.8, ease="power2.out"))   # カメラを正面に戻す
    state["history"] = []
    state["gen"] += 1
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
    gen = state["gen"]
    await play(pos)
    if state["gen"] == gen:
        await advance()


def set_mode(vs_cpu):
    state["vs_cpu"] = vs_cpu
    two_button.className = "mode" if vs_cpu else "mode is-on"
    cpu_button.className = "mode is-on" if vs_cpu else "mode"
    start()


def set_level(level):
    """CPU の強さ。途中で変えてもよい（次の CPU の手から効く）"""
    state["level"] = level
    window.localStorage.setItem(LEVEL_KEY, str(level))
    for n in LEVELS:
        document.querySelector(f"#lv-{n}").className = "mode is-on" if n == level else "mode"


set_level(state["level"])


@when("pointerdown", "#screen")
def on_board_down(event):
    state["press"] = (event.clientX, event.clientY)


@when("click", "#screen")
def on_board_click(event):
    """盤のクリックが CLI 版の input() にあたる。ドラッグ（盤を回した）の終わりは着手にしない。"""
    speaker.start()                                   # 音の許可は「触った中」でしか取れない
    press = state["press"]
    if press and abs(event.clientX - press[0]) + abs(event.clientY - press[1]) > 8:
        return
    if not state["playing"] or cpu_thinking() or state["busy"]:
        return

    pos = pick(event)
    if pos is None or pos not in state["moves"]:  # 置けないマスは黙って無視する
        return

    state["busy"] = True                              # 次の行の play() が動き出す前に 2 回目のクリックが来ても弾く
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
    speaker.start()
    start()


@when("click", "#sound-btn")
def on_sound(event):
    speaker.start()
    speaker.toggle()


@when("click", "#lv-1")
def on_lv1(event):
    set_level(1)


@when("click", "#lv-2")
def on_lv2(event):
    set_level(2)


@when("click", "#lv-3")
def on_lv3(event):
    set_level(3)


@when("click", "#undo-btn")
def on_undo(event):
    speaker.start()
    undo()


@when("click", "#mode-two")
def on_mode_two(event):
    set_mode(False)


@when("click", "#mode-cpu")
def on_mode_cpu(event):
    set_mode(True)


# ── 描画の輪。ブラウザの描画のたび（1 秒に 60 回ほど）に 1 枚描く ──────────

def frame(t):
    controls.update()                                 # ドラッグの滑り・終局の自動回転はここで進む
    composer.render()
    window.requestAnimationFrame(frame_proxy)


frame_proxy = create_proxy(frame)   # Python の関数を JS に渡すときは proxy で包む
window.requestAnimationFrame(frame_proxy)

# Pyodide の読み込みが終わってから実行される＝ここが準備完了の合図
document.querySelector("#loading").hidden = True
document.querySelector("#start-btn").disabled = False
start()


