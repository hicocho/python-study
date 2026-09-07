# g41 将棋（CPU）

将棋 6 段階の 5 つ目。ランダムに指していた CPU を、**駒割りの評価と αβ 探索**で先読みする CPU にします。深さ 2 でランダム相手に 3 戦 3 勝、深さ 3 は 1 手 1〜2 秒。詰将棋モード（g39〜g40）もそのまま残っています。

今回の主題は 4 つです。

- **`array`** — 駒の価値を `array("i", [...])` に。添字は種類のビット位置（`kind.bit_length()`）。リストより小さく、型が固定される
- **αβ 探索（ネガマックス）** — 手番から見た評価を返し、相手が選ばない枝は読まない。詰みは「早いほど高く」（`MATE_SCORE - ply`）
- **手の並べ替え** — 取る手を「取られる駒の価値 − 取る駒の価値 / 10」（MVV-LVA）で先に、刈り込みを起こした手を**キラームーブ**として次に。深さ 3 で 9872 局面 → 1612 局面
- **反復深化と時間制限** — 深さ 1, 2, … と読み、`TimeUp` 例外で抜けて最後に読み切った手を指す。`--profile` で **`cProfile` / `pstats`** の一覧を出す

## ブラウザ版

インストールせずに遊べます → **https://hicocho.github.io/python-study/g41/**

ソースは [`docs/g41/game.py`](../docs/g41/game.py)。`evaluate` / `Cpu` / `class Game` を **1 文字も変えずに**持ってきています。強さは「ランダム / 深さ 1 / 深さ 2 / 深さ 3」。深さ 2 で 1 手 0.5 秒ほど。

## 遊び方（ターミナル）

```bash
python3 main.py --cpu w                 # 後手が深さ 3 の CPU
python3 main.py --cpu w --depth 2       # 深さ 2（速い）
python3 main.py --cpu w --time 2        # 1 手 2 秒まで（深さは上限 3）
python3 main.py --eval --sfen "..."     # 局面の評価と CPU の手
python3 main.py --profile --depth 3     # 1 手を cProfile で測る
python3 main.py --selfplay 2            # 深さ 2 の CPU vs ランダム
```

## 仕様

- 評価: 盤上の駒 + 持ち駒（+20）を手番から見て足し引き。歩 100、香 300、桂 350、銀 500、金 550、角 800、飛 1000。成り駒は と・杏・圭・全 550、馬 1100、龍 1300。玉 0
- 探索: ネガマックス + αβ。合法手がなければ `-MATE_SCORE + ply`（王手でなくても負け）。深さ 0 で評価
- 並べ替え: 取る手（MVV-LVA）→ キラームーブ（深さごとに 2 つ）→ 成る手 → その他
- 反復深化: 深さ 1 から `depth` まで。256 局面ごとに時計を見て `TimeUp`。詰みを見つけたら打ち切り
- 深さ 2 vs ランダム: 3 局 3 勝（59〜90 手）

## メモ

### `array` — 型のある配列

```python
PIECE_VALUE = array("i", [0, 100, 300, 350, 500, 550, 800, 1000, 0])
index = kind_of(piece).bit_length()      # FU=1 → 1、KY=2 → 2、KE=4 → 3、…、OU=128 → 8
```

`IntFlag` の種類が 1 ビットずつなので `bit_length()` が 1〜8 の連番になる。`array` は C の配列と同じで要素が全部同じ型（`"i"` は int）。リストと使い方は同じだがメモリが小さい。`typecode` で型が確かめられる。

### ネガマックス

```python
def search(self, board, depth, alpha, beta, ply):
    ...
    for move in self.ordered(board, moves, ply):
        with trying(board, move):
            score = -self.search(board, depth - 1, -beta, -alpha, ply + 1)
```

ミニマックスを「常に手番から見た値」で書くと、相手の値の符号を反転するだけで max だけになる。α と β も入れ替えて反転。g25 のチェスは max と min を分けて書いたが、こちらが短い。

### 並べ替えが効く理由

αβ は「良い手を先に読む」ほど刈り込みが増える。取る手を先に、しかも「安い駒で高い駒を取る」順（MVV-LVA: Most Valuable Victim, Least Valuable Attacker）。刈り込みを起こした手は同じ深さの別の枝でも効くことが多いので、キラームーブとして覚える。深さ 3 で局面数が 1/6。

### `TimeUp` と反復深化

深さを固定すると、序盤は速く終盤は遅い。深さ 1 から順に読んで、時間が来たら `raise TimeUp` で探索の奥から一気に抜け、最後に読み切った深さの手を使う。`trying` の `finally` が各階層で盤を戻すので、例外で抜けても盤は元どおり（g39 の `SearchLimit` と同じ形）。

### `cProfile` / `pstats`

```python
profiler = cProfile.Profile()
move = profiler.runcall(cpu.choose, board.copy())
pstats.Stats(profiler).sort_stats("cumulative").print_stats(12)
```

どの関数に時間がかかっているかの一覧。`legal_moves` → `trying` → `in_check` → `attacked` の順に重い。次に速くするなら「王手の判定を差分で」だと分かる。g25 では「局面/秒」を測ってから直したが、今回は関数ごとに見る。
