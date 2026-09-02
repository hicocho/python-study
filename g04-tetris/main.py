"""テトリス — ステップ5: 押さなくても落ちてくる。"""

import os        # ← 追加
import random
import select    # ← 追加。「入力を待つが、待ちすぎない」ための道具
import sys
import termios
import time      # ← 追加
import tty

WIDTH = 10
HEIGHT = 20
FALL_SECONDS = 0.8  # ← 追加。何秒ごとに1マス落ちるか

SCORES = [0, 100, 300, 500, 800]

ARROWS = {
    "\x1b[A": "up",
    "\x1b[B": "down",
    "\x1b[C": "right",
    "\x1b[D": "left",
}

SHAPES = {
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


def render(board):
    """盤面を1つの文字列にして返す。print はしない。"""
    lines = []

    for row in board:
        cells = ""
        for cell in row:
            if cell == 0:
                cells += "."
            else:
                cells += "#"
        lines.append("|" + cells + "|")

    lines.append("+" + "-" * WIDTH + "+")
    return "\n".join(lines)


def clear_screen():
    print("\x1b[2J\x1b[H", end="")


def read_key(timeout):  # ← 引数が増え、中身も入れ替え
    """timeout 秒だけキーを待つ。何も押されなければ None を返す。"""
    fd = sys.stdin.fileno()

    ready, _, _ = select.select([fd], [], [], timeout)
    if not ready:
        return None                              # 時間切れ

    key = os.read(fd, 3).decode(errors="ignore")  # 矢印キーの3文字ぶんまで一度に読む
    return ARROWS.get(key, key)


board = make_board()
name, shape, x = spawn()
y = 0
score = 0
lines = 0
game_over = False

fd = sys.stdin.fileno()             # ← try / finally がループの外に出た
saved = termios.tcgetattr(fd)

try:
    tty.setcbreak(fd)               # ゲームのあいだ、ずっとこのモードのまま
    next_fall = time.time() + FALL_SECONDS  # 次に自然落下する時刻

    while True:
        clear_screen()
        print(render(place(board, shape, x, y, name)))
        print(f"スコア {score}   消した列 {lines}")
        print("← → 移動 / ↑ 回転 / ↓ 落下 / スペース 一気に / q やめる")

        key = read_key(max(next_fall - time.time(), 0))  # 落下時刻までの残り時間だけ待つ

        if key is None:
            key = "down"            # 時間切れ＝自分で ↓ を押したことにする

        if key == "q":
            break
        elif key == "left" and can_place(board, shape, x - 1, y):
            x -= 1
        elif key == "right" and can_place(board, shape, x + 1, y):
            x += 1
        elif key == "up":
            turned = rotate(shape)
            if can_place(board, turned, x, y):
                shape = turned
        elif key == " ":            # ← 一気に落とす
            while can_place(board, shape, x, y + 1):
                y += 1
            next_fall = time.time()  # 次の周回ですぐ固定される
        elif key == "down":
            next_fall = time.time() + FALL_SECONDS  # 落ちた瞬間から測り直す

            if can_place(board, shape, x, y + 1):
                y += 1
            else:
                board = place(board, shape, x, y, name)
                board, cleared = clear_lines(board)
                lines += cleared
                score += SCORES[cleared]

                name, shape, x = spawn()
                y = 0

                if not can_place(board, shape, x, y):
                    game_over = True
                    break
finally:
    termios.tcsetattr(fd, termios.TCSADRAIN, saved)  # 何があっても端末を元に戻す

clear_screen()
print(render(board))
if game_over:
    print("ゲームオーバー")
print(f"スコア {score}   消した列 {lines}")
