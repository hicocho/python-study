# g39 将棋（詰将棋）

将棋 6 段階の 3 つ目。**詰将棋**を解きます。攻め方（先手）は王手だけ、受け方は最も長く粘る手を指し、手数以内に受け方の手がなくなれば詰み。1 手詰から 5 手詰まで 8 題。答えは**深さを限った全探索のソルバー**が確かめたもので、`--solve` で解かせることもできます。

今回の主題は 4 つです。

- **再帰ジェネレータ** — `mates()` は「詰む手順」を見つけるたびに `yield` する。`next(gen, None)` で最初の 1 つ、`islice(gen, 2)` で 2 つ目まで（余詰の検出）。全部を作らずに済む
- **`dataclass(slots=True)`** — `Solver` は `nodes` と `seconds` と `max_nodes` を持つだけの小さなクラス。`slots=True` で `__dict__` を作らない（g37 の `__slots__` を dataclass で）
- **`time.perf_counter`** — 探索の秒数を測って「局面/秒」を出す。`try / finally` で途中で抜けても足す
- **自作例外で上限** — `SearchLimit` を投げて、調べる局面の数が上限を超えたら探索ごと抜ける。ブラウザで固まらないように

そして受け方の手を「玉が逃げる・取る・合駒」に絞る `evasions()`（受け方の持ち駒は残り全部なので、絞らないと打つ手が 500 通りになる）。

## ブラウザ版

インストールせずに遊べます → **https://hicocho.github.io/python-study/g39/**

ソースは [`docs/g39/game.py`](../docs/g39/game.py)。`Solver`、`evasions`、`PROBLEMS`、`class Game` を **1 文字も変えずに**持ってきています。問題を選び、王手になる手だけが点で出ます。「次の一手」でヒント。

## 遊び方（ターミナル）

```bash
python3 main.py --tsume          # 問題集を見る
python3 main.py --tsume 3        # 3 番を自分で解く（hint で次の一手）
python3 main.py --solve 0        # 全部をソルバーが解く（手順・局面数・秒）
python3 main.py --cpu w          # 普通の対局（g38 と同じ）
```

## 仕様

- 詰将棋の局面: SFEN の盤と攻め方の持ち駒。受け方の持ち駒は「玉以外の 40 枚から盤上と攻め方の持ち駒を引いた残り全部」
- 攻め方は王手の手だけ（`check_moves`）。手数を超えるか王手が続かなければ失敗
- 受け方（CPU）は、答えの手順どおりなら答えの受け、外れたら残りの手数で詰まされない手を探す（上限 3000 局面）。詰まされるなら最も粘る手
- ソルバー: 1 手詰、3 手詰、… と深さを増やす。攻め方の局面では王手を 1 つずつ試し、受け方の局面では全部の受けが詰まないと失敗。8 題で合計 7649 局面、6.5 秒
- 問題は「答えの手数で詰み、2 手短くは詰まず、初手が 1 通り（余詰なし）」をソルバーで確かめてある

## メモ

### 再帰ジェネレータ — 見つけたら `yield`、全部は作らない

```python
def mates(self, board, depth):
    for move in check_moves(board):
        with trying(board, move):
            line = self.defend(board, depth - 1)
        if line is not None:
            yield [move, *line]

line = next(self.mates(board, depth), None)      # 最初の 1 つ
firsts = {line[0] for line in islice(self.mates(board, depth), 2)}   # 余詰の検出
```

`mates` と `defend` が互いを呼ぶ。`mates` はジェネレータなので、呼ぶ側が `next` で 1 つ取れば探索はそこで止まる。「答えが 1 つあればいい」ときと「2 つ目があるか知りたい」ときで、同じ関数を使い分けられる。
注意: `check_moves` の `yield` は `with trying` の**外**で。中で `yield` すると、呼ぶ側が動いている間、盤が指したままになる（最初はこれで壊れた）。

### 受けの手を絞る

王手されている側の手は「玉を動かす」「王手した駒を取る」「間に駒を入れる」の 3 種類しかない。`evasions()` はその候補だけ作って、`trying` で本当に王手が解けるか確かめる。テストで「王手の局面では `legal_moves` と同じ集合」を確かめた。両王手なら玉を動かすだけ。

### `dataclass(slots=True)` と `time.perf_counter`

```python
@dataclass(slots=True)
class Solver:
    nodes: int = 0
    seconds: float = 0.0
    max_nodes: int | None = None
```

探索の状態（数えた局面、かかった秒数）をまとめる入れ物。`solve()` の `try / finally` で `perf_counter` の差を足すので、`SearchLimit` で抜けても秒数が残る。

### 問題はソルバーで作った

ランダムに玉と数枚の駒を置き、ソルバーで「N 手で詰み、N−2 手では詰まず、余詰なし」の局面だけ残した（4000 局面の上限つきで 1 分に 200 局面ほど試せる）。人が作った詰将棋のような妙手はないが、答えが正しいことは確か。
