# g24 チェスの終局（引き分け・perft・unittest）

チェスの 3 段階目。千日手（同じ局面が 3 回）・50 手ルール・駒不足の引き分けを足して、**ルールはこれで全部**です。
合わせて、perft を `lru_cache` で速くし、検証を `unittest` にまとめました。

今回の主題は 3 つです。

- **`unittest`** — `test_main.py` に perft 5 局面と全ルールのテスト。`python3 -m unittest -v` で 11 本
- **`functools.lru_cache`** — `Board` が hash できるので、perft の `count_moves(board, depth)` をそのまま覚えられる
- **`collections.Counter` と `field(compare=False)`** — 局面の回数を数えて千日手。50 手カウンタは「同じ局面」の比較に含めない

## ブラウザ版

インストールせずに遊べます → **https://hicocho.github.io/python-study/g24/**

ソースは [`docs/g24/game.py`](../docs/g24/game.py)。定数と表、`Square` / `Move` / `Board`、関数 14 個、そして `class Game` を **1 文字も変えずに**持ってきています。
持ってこなかったのは `Game.render()` と `perft_table()` / `main()` だけ。盤の下に 50 手カウンタと「同じ局面 n 回目」を出します。

## 遊び方（ターミナル）

```bash
python3 main.py                        # 2 人で交互に
python3 main.py --cpu b                # 黒をランダム CPU に
python3 main.py --fen "4k3/8/8/8/8/8/8/R3K3 w - - 99 80"   # この局面から（50 手カウンタ 99）
python3 main.py --perft 4              # 対局せず perft の表を出す
python3 -m unittest -v                 # 検証を全部走らせる
```

```
> f3g1
8  r n b q k b . r
7  p p p p p p p p
6  . . . . . n . .
5  . . . . . . . .
4  . . . . . . . .
3  . . . . . . . .
2  P P P P P P P P
1  R N B Q K B N R
   a b c d e f g h

4 手目 黒の番   直前 f3g1   同じ局面 2 回目
50 手カウンタ 7
> f6g8
8  r n b q k b n r
7  p p p p p p p p
6  . . . . . . . .
5  . . . . . . . .
4  . . . . . . . .
3  . . . . . . . .
2  P P P P P P P P
1  R N B Q K B N R
   a b c d e f g h

5 手目 白の番   直前 f6g8   同じ局面 3 回目
50 手カウンタ 8
千日手（同じ局面が 3 回）。引き分け
```

ナイトを 2 回往復すると初期局面が 3 回目になり、千日手で引き分け。

## 仕様

- **千日手**: 同じ局面（配置・手番・キャスリングの権利・アンパッサンのマス）が 3 回現れたら引き分け。`undo` すると回数も戻る
- **50 手ルール**: ポーンの手も取る手も無いまま 100 手（50 手ずつ）で引き分け。FEN の 5 項目目がそのカウンタ
- **駒不足**: K 対 K、K+N または K+B 対 K、同じ色のマスのビショップだけ、のとき引き分け
- FEN は 6 項目（配置 手番 キャスリング アンパッサン 50手カウンタ 手数）。後ろ 2 つは省略できる
- `--perft N` で深さごとの手の数と秒数。`lru_cache` の効果は控えめ（初期局面 4 手先で 13.3 秒 → 11.3 秒。浅いうちは「別の手順で同じ局面」が少ない）

### `python3 -m unittest -v` の 11 本

| クラス | 何を確かめるか |
|---|---|
| `PerftTest` | 5 局面の perft（初期局面 8,902、Kiwipete 97,862 など）が既知の値と一致 |
| `FenTest` | 6 項目の往復、カウンタの増減、カウンタ違いの同じ局面が `==` かつ同じ `hash` |
| `DrawTest` | 千日手、`undo` で回数が戻る、50 手（ポーンの手で振り出し）、駒不足 7 パターン |
| `RuleTest` | チェックメイト・ステイルメイト、キャスリングの可否、アンパッサン |

## メモ

### `unittest` — 検証をファイルに残す

```python
class DrawTest(unittest.TestCase):
    def setUp(self):
        self.game = Game()

    def test_repetition(self):
        shuffle = ["g1f3", "g8f6", "f3g1", "f6g8"]
        self.play(*shuffle)
        self.assertEqual(self.game.repetitions, 2)
        self.play(*shuffle)
        self.assertEqual(self.game.result, "repetition")
```

g22・g23 の検証は使い捨てのスクリプトでした。`unittest` にすると、**`python3 -m unittest -v` の 1 コマンドで全部走り、どれが落ちたか名前で分かる**。
`TestCase` を継承したクラスの `test_` で始まるメソッドが 1 本のテスト。`setUp` は各テストの前に呼ばれる準備。
`assertEqual` は失敗したとき「期待 / 実際」を両方見せてくれるので、`assert a == b` より原因が早く分かります。
`with self.subTest(name=..., depth=...)` は、表を回すテストで**どの行で落ちたか**を残す仕組み（perft の 5 局面 × 深さで使用）。

### `lru_cache` — hash できる引数なら、関数の結果を覚えられる

```python
@lru_cache(maxsize=None)
def count_moves(board: Board, depth: int) -> int:
```

g23 で `Board` に `__hash__` を書いたので、`(board, depth)` をキーに結果を覚えられます。別の手順で同じ局面に着いたら計算しない。
チェスプログラムの「トランスポジションテーブル」の最小版です。`cache_info()` で hits/misses が見え、初期局面 4 手先で hits 1,300 / misses 8,023 でした。
**効果は 15% ほど**——浅い探索では同じ局面に別の手順で着くことが少ない。g25 の先読みではもっと効きます。
`cache_clear()` で忘れられるので、`--perft` の計測は深さごとに空にしてから測っています。

### `field(compare=False)` — 比較に入れないフィールド

```python
    halfmove: int = field(default=0, compare=False)
    fullmove: int = field(default=1, compare=False)
```

千日手の「同じ局面」は配置・手番・権利・アンパッサンで決まり、50 手カウンタや手数は関係ありません。
dataclass の `field(compare=False)` で `__eq__` から外し、`__hash__` にも入れない。これで `Counter[Board]` が「局面そのもの」を数えます。
`from_fen` の既定値の埋め方（`parts + ["-", "-", "0", "1"][len(parts) - 2:]`）は、4 項目でも 6 項目でも読めるようにするため。

### `Counter` で千日手

```python
        self.positions: Counter[Board] = Counter([self.board])
        ...
        self.positions[self.board] += 1
        self.result = "repetition" if self.repetitions >= REPETITIONS else result_of(self.board)
```

g11 の `Counter` は文字を数えました。ここでは**局面を数える**。`__hash__` と `__eq__` がそろっているからキーにできます。
`undo` で `-= 1` しないと、戻したあと同じ手を指したとき回数が合いません（`--fen` で始めたときに初期局面を数え忘れる不具合も、ステップ 5 で `Game(fen=)` に直しました）。
千日手だけ `Game` で判定するのは、履歴が要るから。50 手と駒不足は局面だけで決まるので `result_of` に置きました。

### 駒不足は「ビショップのマスの色」まで見る

`(sq.file + sq.rank) % 2` が同じなら同じ色のマス。両方がビショップ 1 つずつでも、色が同じなら互いにメイトできません。
