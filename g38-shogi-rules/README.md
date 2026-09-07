# g38 将棋（反則と終局）

将棋 6 段階の 2 つ目。g37 の「相手の玉を取ったら勝ち」を本物のルールにします。**王手放置・二歩・打ち歩詰め・行き所のない駒**は指せず、**詰み**（指せる手がない）で終わり、同じ局面が 4 回で**千日手**、追い回した側が連続王手なら負け。

今回の主題は 4 つです。

- **`contextlib.contextmanager`** — 「指して戻す」を `with trying(board, move):` に。中だけ指した局面になり、抜けると必ず戻る（例外でも）。王手放置の判定と perft で使う
- **Zobrist ハッシュ** — マス×駒、持ち駒の枚数、手番のそれぞれに `random.getrandbits(64)` の乱数を割り当て、XOR で局面を 1 つの整数に。手順が違っても同じ局面なら同じ数（千日手の判定）
- **`collections.deque`** — `deque(maxlen=6)` で「直前の 6 手」だけ残す。7 手目を入れると古いものが自動で消える
- **`assert`** — `do()` の中で「自分の駒は取れない」を確かめる。壊れたらそこで止まる

そして perft 4 手 = **719731**（既知の値）に一致。合法手の生成がすべて正しいことの証拠です。

## ブラウザ版

インストールせずに遊べます → **https://hicocho.github.io/python-study/g38/**

ソースは [`docs/g38/game.py`](../docs/g38/game.py)。`Board.do` / `undo` / `zobrist`、`trying`、`attacked` / `in_check` / `legal_moves`、`class Game` を **1 文字も変えずに**持ってきています。王手がかかると玉が赤くなり、反則の手は点が出ません。

## 遊び方（ターミナル）

```bash
python3 main.py                  # 2 人で交互
python3 main.py --cpu w          # 後手をランダム CPU に
python3 main.py --perft 4        # 4 手先までの手の数（719731、35 秒ほど）
python3 main.py --sfen "k8/9/1S7/9/9/9/9/9/4K4 b G 1"   # 途中の局面から（頭金で詰み）
```

- 手は USI 形式（`7g7f`、`2b3c+`、`P*5e`）。`undo` で戻す、`q` でやめる
- 画面に「王手！」と直前の 6 手が出る

## 仕様

- 合法手 = 疑似合法手のうち、指した後に自分の玉が取られないもの。打つ手はさらに二歩・行き所のないマスを除き、歩を打って詰ませる手（打ち歩詰め）も除く
- 終局: 手番に合法手がなければ負け（王手なら「詰み」、そうでなければ「指せる手がない」）。同じ局面（配置・持ち駒・手番）が 4 回目で千日手。その間ずっと片方だけが王手をかけていたら、その側の負け
- perft: 1 手 30、2 手 900、3 手 25470、4 手 719731

## メモ

### `contextmanager` — 「指して戻す」を `with` に

```python
@contextmanager
def trying(board, move):
    captured, before = board.do(move)
    try:
        yield board
    finally:
        board.undo(move, captured, before)

with trying(board, move):
    if in_check(board, color):
        continue          # 王手放置
```

g37 の `make_move` は盤を複写して返した。探索では 1 手ごとに複写すると遅いので、`do`（その場で書き換える）と `undo`（戻す）を作り、`contextmanager` で「必ず戻る」形にした。`yield` の前が `__enter__`、後が `__exit__`。`finally` に置くので、中で `continue` しても例外が出ても戻る。3 重に入れ子にしても、打つ手でも戻ることをテストで確かめた。

### Zobrist ハッシュ

```python
ZOBRIST_SQUARE = {(Square(f, r), piece): rng.getrandbits(64) for ...}
key = ZOBRIST_GOTE_TURN if turn == GOTE else 0
for square, piece in pieces.items():
    key ^= ZOBRIST_SQUARE[square, piece]
```

局面を「マスに駒がある」の集合と見て、要素ごとの乱数を XOR で合成する。XOR は順番に依らず、同じものを 2 回かけると消えるので、駒を動かしたときの差分更新もできる（g41 で使う）。乱数は `random.Random(20260907)` と種を固定して、いつ動かしても同じ表になるように。テストで「手順が違っても同じ局面なら同じ数」「手番が違えば違う」を確かめた。

### 連続王手の千日手

同じ局面が 4 回目になったとき、その局面が最初に出た手からの `checks`（各手が王手だったか）を見る。片方の手が全部王手なら、その側の負け。テストは龍で玉を追い回す 13 手。

### `deque(maxlen=6)`

「直前の 6 手」。`append` すると古いものが落ちる。`undo` のときは `pop()` で消す。

### 手の順を固定する

`do` / `undo` は辞書の順を変える（戻した駒が末尾に付く）。`all_moves` を `sorted(board.pieces.items())` にしないと、`legal_moves` を呼んだ回数で手の順が変わり、ランダム CPU の手が CLI 版とブラウザ版で食い違った。同値テストで見つけた。
