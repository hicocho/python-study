# g22 チェス（盤と駒の動き）

チェスの 1 段階目。盤と駒の動きだけを作りました。2 人で交互に指すか、ランダムに指す CPU を相手にできます。
キャスリング・アンパッサン・チェックはまだ無く、**相手のキングを取ったら勝ち**です（g23 でルールを足し、g24 で詰みと引き分け、g25 で先読みする CPU、g26 で棋譜）。

今回の主題は 3 つです。

- **`NamedTuple`** — `Square(file, rank)` と `Move(src, dst, promotion)`。タプルの軽さのまま、名前と `@property` とメソッドが持てる
- **`__getitem__` / `__setitem__` / `__iter__`** — `board["e4"]` で駒を見て、`board["e4"] = "P"` で置いて、`for square, piece in board:` で回す
- **FEN** — 局面を 1 行の文字列で読み書きする（`from_fen` と `fen`）。テストで好きな局面を作れる

## ブラウザ版

インストールせずに遊べます → **https://hicocho.github.io/python-study/g22/**

ソースは [`docs/g22/game.py`](../docs/g22/game.py)。定数と `Square` / `Move` / `Board`、`ray()` 〜 `count_moves()`、そして `class Game` を **1 文字も変えずに**持ってきています（`ast` で切り出して文字列比較で確認済み）。
持ってこなかったのは `Board.__str__` を使う `Game.render()` と `main()` だけ。出口は 64 個の `<div>` に Unicode のチェス記号（♔♞…）で、クリックで選んでクリックで指します。

## 遊び方（ターミナル）

```bash
python3 main.py            # 2 人で交互に
python3 main.py --cpu b    # 黒をランダム CPU に
```

- `e2e4` のように「元のマス＋先のマス」で指す。ポーンが最終段に着くときは `e7e8q`（q/r/b/n）
- `undo` で戻す（CPU 相手なら 2 手戻る）／ `q` でやめる

```
8  r n b q k b n r
7  p . p p p p . .
6  . . . . . . . p
5  . p . . . . p .
4  . . B . P . . .
3  . . . . . N . .
2  P P P P . P P P
1  R N B Q K . . R
   a b c d e f g h

4 手目 白の番   直前 g7g5

> e1g1
e1g1 は指せません（キング）。
```

大文字が白、小文字が黒。`K` キング `Q` クイーン `R` ルーク `B` ビショップ `N` ナイト `P` ポーン。

## 仕様

- 駒の動きは本物どおり（ナイトの跳び、飛び駒は味方で止まる、ポーンは前に 1 つ・初期位置なら 2 つ・斜め前の敵を取る・最終段で成る）
- **無いもの**: キャスリング、アンパッサン、チェックとチェックメイト、ステイルメイト、千日手。これらは g23・g24 で
- 相手のキングを取ったら勝ち。自分のキングを取られる手も指せる（g23 で「チェックのまま放置できない」を入れる）
- 初期局面から 1 手・2 手・3 手先の組み合わせは 20 / 400 / 8902（既知の値と一致。3 手以内にチェックは起きないので、特殊ルール抜きでも同じ数になる）

## メモ

### `NamedTuple` — 名前つきのタプル

```python
class Square(NamedTuple):
    file: int
    rank: int

    @property
    def name(self) -> str:
        return FILES[self.file] + RANKS[self.rank]
```

g11 以来の `dataclass(frozen=True)` と似ていますが、`NamedTuple` は**本当にタプル**です。`file, rank = square` とほどけて、辞書のキーになり、
`(4, 3) == Square(4, 3)` が `True`。`Square(4, 3).name` のように `@property` やメソッド（`shift`、`parse`）も持てます。
「座標」のように小さくて不変で、タプルとして扱いたいものに向いています。`Move` も同じで、`move in all_moves(board)` の比較がタプルの比較で済みます。

### `__getitem__` / `__setitem__` / `__iter__` — 盤を「入れ物」として使う

```python
    def __getitem__(self, key):          # board["e4"] / board[Square(4, 3)]
    def __setitem__(self, key, piece):   # board["e4"] = "P"、None で消す
    def __iter__(self):                  # for square, piece in board:
```

g19 の `__contains__` に続く「入れ物のふるまい」。`board["e4"]` は `board.__getitem__("e4")` で、文字列でも `Square` でも受けるようにしました。
中身は `dict[Square, str]` で**駒のあるマスだけ**を持ちます。空きマスを 64 個持たないので `for square, piece in board` は 32 回で済み、
`copy()` も辞書のコピー 1 回。

### FEN — 局面を 1 行で

```
rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w
```

8 段目から順に、駒は文字、空きマスは数で書く世界共通の記法です。`from_fen` で読み、`fen` で書き戻します。
テストでは `"8/8/8/3N4/8/8/8/8 w"` のように**駒 1 つだけの局面を作って手数を数える**（ナイト 8、ルーク 14、ビショップ 13、クイーン 27）。
局面を文字列で作れると、テストが書きやすくなります。

### `ray` — 飛び駒は「ぶつかるまで」

```python
def ray(board, start, df, dr):
    sq = start.shift(df, dr)
    while sq.on_board:
        yield sq
        if board[sq] is not None:
            return
        sq = sq.shift(df, dr)
```

ルーク・ビショップ・クイーンは向きが違うだけ。`ray` は駒にぶつかったマスまでを `yield` して止まるので、
呼ぶ側で「味方なら除く」だけで済みます（敵なら取れる）。ナイトとキングは跳ぶ先のリスト、ポーンだけ別関数。

### 指すと新しい盤が返る

`make_move` は盤を書き換えず、コピーして返します。`history` に「指す前の盤」を積んでおけば `undo` は `pop` するだけ。
`count_moves`（perft）も、盤を戻す処理を書かずに再帰できます。

### 検証は既知の数で

初期局面から 1・2・3 手先の組み合わせ 20 / 400 / 8902 は世界中のチェスプログラムが使う検証値です。
自分で正解を作らなくても、この数が合えば駒の動きは正しい。g24 で特殊ルール込みの局面（キャスリング・アンパッサン・成り）でも数を合わせます。
