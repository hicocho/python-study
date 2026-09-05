"""オセロ — ステップ5: パスと終局判定。勝敗を出して終わる。"""

SIZE = 8

EMPTY = 0
BLACK = 1
WHITE = 2

MARKS = {
    EMPTY: "・",
    BLACK: "●",
    WHITE: "○",
}

# 8方向ぶんの (行の進み, 列の進み)。真ん中（自分）は含めない
DIRECTIONS = [
    (-1, -1), (-1, 0), (-1, 1),
    (0, -1),           (0, 1),
    (1, -1),  (1, 0),  (1, 1),
]


def make_board():
    """初期配置の盤面を作って返す。中央4マスに石が置かれた状態。"""
    board = [[EMPTY] * SIZE for _ in range(SIZE)]
    board[3][3] = WHITE
    board[3][4] = BLACK
    board[4][3] = BLACK
    board[4][4] = WHITE
    return board


def board_text(board, moves=()):
    """盤面を表示用の文字列にして返す。moves にある空きマスは ＊ で示す。"""
    lines = ["   a b c d e f g h"]
    for i, row in enumerate(board):
        cells = []
        for j, cell in enumerate(row):
            if cell == EMPTY and (i, j) in moves:
                cells.append("＊")
            else:
                cells.append(MARKS[cell])
        lines.append(f"{i + 1}  {' '.join(cells)}")
    return "\n".join(lines)


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


def parse_move(text):
    """ "d3" のような入力を (2, 3) にして返す。読めなければ None。"""
    text = text.strip().lower()

    if len(text) != 2:
        return None
    if not ("a" <= text[0] <= "h" and "1" <= text[1] <= "8"):
        return None

    col = ord(text[0]) - ord("a")
    row = int(text[1]) - 1
    return row, col


def apply_move(board, row, col, flips, player):
    """石を置き、flips に入っている石をすべて player の色にする。"""
    board[row][col] = player
    for r, c in flips:
        board[r][c] = player


def result_text(board):  # ← 追加
    """終局の結果を文字列にして返す。print はしない。"""
    black, white = count_stones(board)

    if black > white:
        winner = "● の勝ち！"
    elif white > black:
        winner = "○ の勝ち！"
    else:
        winner = "引き分け"

    return f"● {black} - ○ {white}    {winner}"


def main():
    board = make_board()
    player = BLACK
    message = ""
    passes = 0  # ← 追加。パスが何回続いたか

    while True:
        moves = valid_moves(board, player)

        print()
        print(board_text(board, moves))

        black, white = count_stones(board)
        print(f"\n● {black} - ○ {white}    手番: {MARKS[player]}")

        if message:
            print(message)
            message = ""

        if not moves:  # ← ここから書き換え
            passes += 1
            if passes == 2:
                print("両者とも置ける場所がありません。終局です。")
                break
            message = f"{MARKS[player]} は置ける場所がないのでパス。"
            player = opponent(player)
            continue

        passes = 0  # ← 置けたので、パスの連続は途切れた

        text = input("どこに置く？（例 d3 / q でやめる）> ")
        if text.strip().lower() == "q":
            break

        pos = parse_move(text)
        if pos is None or pos not in moves:
            message = "そこには置けません。"
            continue

        row, col = pos
        apply_move(board, row, col, moves[pos], player)
        message = f"{MARKS[player]} が {move_name(row, col)} に置いて {len(moves[pos])} 個ひっくり返した"
        player = opponent(player)

    print()
    print(board_text(board))  # ← 終局後は ＊ なしの盤を出す
    print(result_text(board))


if __name__ == "__main__":
    main()
