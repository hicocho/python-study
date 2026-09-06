# g12 迷路

穴掘り法で作った迷路を、矢印キーで左上から右下まで歩く CLI ゲームです。
`?` を押すと BFS で求めた最短路の「次の 1 歩」が `＊` で出ます。ゴールすると最短路と自分の歩数が比べられます。
`--size` で大きさ、`--seed` で同じ迷路を再現できます。

g13 と 2 段階の連作で、この g12 が「作る・歩く・最短路」、g13 が「探索を見る・ロボットと競走」です。

今回の主題は 3 つです。

- **`collections.deque` と BFS** — 先に入れたものを先に見る待ち行列で、最短路を求める
- **`@contextmanager`** — `with` で端末の設定を必ず戻す。`yield` の新しい使い道
- **`argparse`** — コマンドラインの `--size` `--seed` を読み、おかしければ使い方を出して止まる

そして伏線が 1 つ。穴掘り法を**再帰**で書いたので、大きな迷路では `sys.setrecursionlimit` が要ります。
これは g13 のステップ 1 で「再帰をスタックに書き換える」ことで解消します。

## ブラウザ版

インストールせずに遊べます → **https://hicocho.github.io/python-study/g12/**

ソースは [`docs/g12/game.py`](../docs/g12/game.py)。定数 4 つと `make_grid()` / `carve()` / `make_maze()` /
`neighbors()` / `shortest_path()` / `next_step()`、そして `class Game` を **1 文字も変えずに**持ってきています
（`ast` で切り出して文字列比較で確認済み）。

持ってこなかったのは `maze_text()` と `raw_mode()` / `read_key()` と `parse_args()` / `main()`、それに `Game.render()` だけ。
違うのは**入口と出口**で、

- 入口：`termios` の生キー入力 → キーイベントとボタン
- 出口：`██` の文字列 → N×N 個の `<div>`

ブラウザ版だけの追加は、大きさを 15 / 21 / 31 から選べるボタンです。

## 遊び方（ターミナル）

```bash
python3 main.py                # 21×21
python3 main.py --size 31      # 大きく
python3 main.py --seed 7       # 同じ数字なら同じ迷路
```

- 矢印キーで移動
- `?` ヒント（次の 1 歩が `＊`）
- `q` やめる

```
██████████████████████
██· · @ ＊  ██      ██
██████████  ██  ██  ██
██          ██  ██  ██
██  ██████████████  ██
██      ██          ██
██████  ██  ██████████
██  ██  ██          ██
██  ██  ██████████  ██
██                G ██
██████████████████████

2 歩（最短 24 歩）  矢印キーで移動 / ? でヒント / q でやめる
```

- `@` 自分 ／ `G` ゴール ／ `·` 通ったマス ／ `＊` ヒント ／ ゴール後は最短路が `▒` で出る

## 仕様

- 盤は奇数の正方形（既定 21）。外周は壁、奇数座標が部屋、その間の壁を抜いて通路にする
- **穴掘り法**：左上から掘り始め、掘れる方向をシャッフルして再帰的に掘り進む。行き止まりで戻る
- できる迷路は**木**（どの 2 マスの間も道が 1 本だけ）。通路の数はちょうど `部屋 × 2 − 1`
- スタートは左上 `(1, 1)`、ゴールは右下
- **最短路**は BFS。ゴールから `came_from` を逆にたどって復元する
- ヒントは「いまいる場所から」の最短路の 2 マス目。動くと消える
- `--size` は 5 以上の奇数。それ以外は `argparse` がエラーを出して止まる

## メモ

### 穴掘り法 — 再帰で「行き止まりまで掘って、戻る」

```python
def carve(grid, row, col):
    grid[row][col] = PATH
    directions = DIRECTIONS[:]
    random.shuffle(directions)

    for dr, dc in directions:
        nr, nc = row + dr, col + dc
        if 0 < nr < size - 1 and 0 < nc < size - 1 and grid[nr][nc] == WALL:
            grid[row + dr // 2][col + dc // 2] = PATH        # 間の壁を抜く
            carve(grid, nr, nc)
```

2 マス先がまだ壁なら、間の壁を抜いてそこから**また掘り始める**（再帰）。掘れる方向が無くなると関数が終わり、
1 つ前の場所に戻って残りの方向を試す。g06 の「0 のマスは連鎖して開く」と同じ再帰ですが、
今回は**シャッフルした順に試す**ので、毎回違う迷路になります。

`DIRECTIONS[:]` でコピーしてからシャッフルしているのは、元のリストを崩さないため。
`random.shuffle` はその場で並べ替えるので、コピーしないと全部の呼び出しで同じリストが混ざり続けます。

### 再帰の深さには限りがある

```python
sys.setrecursionlimit(10000)
```

Python は再帰を既定で 1000 段までしか許しません。穴掘り法は**部屋の数だけ深く**なりうるので、
45×45（部屋 484）あたりから危なく、81×81（部屋 1600）では確実に落ちます。
上限を広げれば動きますが、これは「深さを気にしなくていい書き方」ではありません。
**g13 のステップ 1 で、同じアルゴリズムを再帰なし（明示的なスタック）で書き直します。**

### `deque` — 先に入れたものを先に見る

```python
    queue = deque([start])
    came_from = {start: None}

    while queue:
        pos = queue.popleft()
        ...
            if nxt not in came_from:
                came_from[nxt] = pos
                queue.append(nxt)
```

BFS（幅優先探索）は「近いマスから順に」見ます。それには**先に入れたものを先に取り出す**入れ物が要ります。
リストの `pop(0)` でもできますが、先頭を抜くたびに全部ずれるので遅い。`deque` は両端が速い入れ物で、
`popleft()` が先頭からの取り出しです。g10 のスタック（`append` / `pop`）が「後入れ先出し」、
こちらが「先入れ先出し」。**同じリスト状の入れ物でも、どちらの端から取るかで探索の形が変わります。**

### `came_from` — 訪問済みの印と、道しるべを 1 つの辞書で

`came_from[nxt] = pos` は「`nxt` には `pos` から来た」の記録です。同時に `nxt not in came_from` が
「まだ来ていないか」の判定になっているので、訪問済みの `set` を別に持つ必要がありません。

ゴールに着いたら、`came_from` をゴールから逆にたどるだけで経路になります。

```python
    pos = goal
    while pos is not None:
        path.append(pos)
        pos = came_from[pos]
    path.reverse()
```

`came_from[start]` を `None` にしておいたので、`while pos is not None` がスタートで自然に止まります。

### BFS の開始点を引数にしておくと、ヒントがただで付いてくる

```python
def next_step(grid, pos, goal):
    path = shortest_path(grid, pos, goal)
    return path[1] if len(path) > 1 else None
```

`shortest_path(grid, start, goal)` は最初から「どこからでも」使える形で書いてあります。
ヒントは**いまの場所を `start` にして**同じ関数を呼び、2 マス目を取るだけ。
g09 の `collide()` を敵にもバリアにも使い回したのと同じで、引数を絞りすぎないと後で効きます。

### `@contextmanager` — `with` で必ず戻す

```python
@contextmanager
def raw_mode():
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    tty.setcbreak(fd)
    try:
        yield
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
```

g04・g09 では端末の設定を `try` / `finally` で戻していました。今回はそれを `with raw_mode():` と書ける形にしています。
`yield` の**上が入るとき、下が出るとき**。`with` ブロックの中で例外が起きても `finally` が走るので、
端末が壊れたまま終わることがありません。

g10 の `yield` は「値を 1 つずつ流す」ためでしたが、ここでは**値を渡さず、処理の前後を挟む**ために使っています。
同じ `yield` でも役割が違う。`with open()` が閉じ忘れを防ぐのと同じ仕組みを、自分で作れるということです。

### `sys.stdin.read(1)` ではなく `os.read()`

最初は `sys.stdin.read(1)` で 1 文字ずつ読んでいました。すると矢印キーが `ESC` `[` `A` の
バラバラ 3 回に分かれて届き、`ARROWS` の辞書に当たらない。
原因は `sys.stdin` が**中でまとめて読み込んで小出しにしている**ことで、2 文字目以降は
もう Python の手元にあり、`select` で待っても「まだ来ていない」ように見えます。

```python
        data = os.read(sys.stdin.fileno(), 8)              # 矢印は ESC [ A の 3 バイトがまとめて届く
```

`os.read()` は端末から届いたぶんを**そのまま**返すので、矢印は 3 バイトが 1 回で取れます。
g04・g09 が `os.read` を使っていた理由がここで分かりました。

見つけたのは、擬似端末（`pty`）で本物のキー入力を流すテストです。`termios` は端末が無いと動かないので、
パイプではなく `pty.fork()` で子プロセスを起動し、矢印キーのバイト列を書いて画面を読みました。

### `argparse` — 使い方を自動で作る

```python
    parser = argparse.ArgumentParser(description="迷路。矢印キーで歩いてゴールへ。")
    parser.add_argument("--size", type=int, default=SIZE, help="盤の一辺（5 以上の奇数）。既定 21")
    parser.add_argument("--seed", type=int, help="同じ数字を渡すと同じ迷路になる")
    args = parser.parse_args()

    if args.size < 5 or args.size % 2 == 0:
        parser.error("--size は 5 以上の奇数にしてください")
```

`--help` を付けると、この定義から使い方の文章が出ます。`type=int` で数字でなければ自動でエラー。
`parser.error()` は自分で見つけた間違いを、同じ形式で出して終わる書き方です。
`sys.argv` を自分で切るより短く、間違いの扱いがそろいます。

### `--seed` は検証のため

`random.seed(seed)` を通すと、乱数の並びが決まって**同じ迷路が出ます**。遊ぶ側には「あの迷路をもう一度」ですが、
作る側には**同じ盤で CLI 版とブラウザ版を突き合わせる**手段です。10 個の種で 200 手ずつ、
迷路・最短路・ヒント・移動の結果がすべて一致することを確かめました。
