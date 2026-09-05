"""マインスイーパ — ステップ5: 旗・クリア判定・初手は必ず安全。"""

import random

SIZE = 9
MINE_COUNT = 10

# 開いたマスの表示。添字がそのまま「周りの地雷の数」になる
NUMBERS = "・１２３４５６７８"

HIDDEN = "■"
MINE = "＊"
FLAG = "Ｆ"

# 8方向ぶんの (行の進み, 列の進み)。真ん中（自分）は含めない
DIRECTIONS = [
    (-1, -1), (-1, 0), (-1, 1),
    (0, -1),           (0, 1),
    (1, -1),  (1, 0),  (1, 1),
]


def all_cells():
    """盤の全マスの座標をリストにして返す。"""
    return [(row, col) for row in range(SIZE) for col in range(SIZE)]


def around(row, col):
    """(row, col) 自身と、その周り8マスの座標の集合を返す。"""
    cells = {(row, col)}
    for dr, dc in DIRECTIONS:
        cells.add((row + dr, col + dc))
    return cells


def place_mines(count, safe):
    """safe に入っているマスを避けて、地雷を count 個ランダムに置く。"""
    candidates = [cell for cell in all_cells() if cell not in safe]
    return set(random.sample(candidates, count))


def count_around(mines, row, col):
    """(row, col) の周り8マスにある地雷の数を返す。"""
    return sum((row + dr, col + dc) in mines for dr, dc in DIRECTIONS)


def open_cell(mines, opened, row, col):
    """(row, col) を開く。周りに地雷が無ければ、その周り8マスも続けて開く。"""
    # 盤の外なら何もしない
    if not (0 <= row < SIZE and 0 <= col < SIZE):
        return

    # もう開いているなら何もしない（ここで再帰が止まる）
    if (row, col) in opened:
        return

    opened.add((row, col))

    # 周りに地雷が1個でもあれば、そこで打ち止め
    if count_around(mines, row, col) > 0:
        return

    # 周りに地雷が無いマスだけ、8方向へ広げる
    for dr, dc in DIRECTIONS:
        open_cell(mines, opened, row + dr, col + dc)


def is_clear(opened):
    """地雷以外を全部開いたら True。"""
    return len(opened) == SIZE * SIZE - MINE_COUNT


def board_text(mines, opened, flags, reveal=False):
    """盤面を文字列にして返す。reveal が True のときだけ地雷を見せる。"""
    lines = ["   a b c d e f g h i"]

    for row in range(SIZE):
        cells = []
        for col in range(SIZE):
            if reveal and (row, col) in mines:
                cells.append(MINE)
            elif (row, col) in opened:
                cells.append(NUMBERS[count_around(mines, row, col)])
            elif (row, col) in flags:
                cells.append(FLAG)
            else:
                cells.append(HIDDEN)
        lines.append(f"{row + 1}  {' '.join(cells)}")

    return "\n".join(lines)


def move_name(row, col):
    """(2, 3) を "d3" のような表記にして返す。"""
    return chr(ord("a") + col) + str(row + 1)


def parse_move(text):
    """ "d3" のような入力を (2, 3) にして返す。読めなければ None。"""
    text = text.strip().lower()

    if len(text) != 2:
        return None
    if not ("a" <= text[0] <= "i" and "1" <= text[1] <= "9"):
        return None

    col = ord(text[0]) - ord("a")
    row = int(text[1]) - 1
    return row, col


def main():
    mines = set()   # 最初は空。地雷を置くのは初手のあと
    opened = set()
    flags = set()
    message = ""

    while True:
        print()
        print(board_text(mines, opened, flags))
        print(f"\n開いたマス {len(opened)} / 残り地雷 {MINE_COUNT - len(flags)}")

        if message:
            print(message)
            message = ""

        text = input("どこを開く？（例 d3 / 旗は fd3 / q でやめる）> ").strip().lower()
        if text == "q":
            break

        flagging = len(text) == 3 and text[0] == "f"
        pos = parse_move(text[1:] if flagging else text)

        if pos is None:
            message = "その入力は読めません。"
            continue

        if flagging:
            if pos in opened:
                message = "開いたマスに旗は立てられません。"
            elif pos in flags:
                flags.remove(pos)
            else:
                flags.add(pos)
            continue

        if pos in flags:
            message = "旗が立っています。外してから開いてください。"
            continue
        if pos in opened:
            message = "そこはもう開いています。"
            continue

        row, col = pos

        if not mines:
            mines = place_mines(MINE_COUNT, around(row, col))

        if pos in mines:
            print()
            print(board_text(mines, opened, flags, reveal=True))
            print(f"\n{move_name(row, col)} は地雷でした。ゲームオーバー。")
            return

        open_cell(mines, opened, row, col)

        if is_clear(opened):
            print()
            print(board_text(mines, opened, flags, reveal=True))
            print("\n地雷以外を全部開きました。クリア！")
            return


if __name__ == "__main__":
    main()
