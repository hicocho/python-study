# g37 将棋（盤と駒の動き）

将棋 6 段階の 1 つ目。盤上の駒を動かし、敵陣で**成り**、取った駒は**持ち駒**になって打てます。王手・二歩・打ち歩詰めなどの反則はまだ無く（g38 で入れます）、**相手の玉を取ったら勝ち**。2 人で交互に指すか、ランダムに指す CPU 相手。

今回の主題は 4 つです。

- **`IntFlag`** — 駒を「種類のビット | 成りのビット | 後手のビット」の 1 つの整数で持つ。`Piece.PROMOTED in piece` で調べ、`piece | Piece.PROMOTED` で成る。`.name` は `KA|GOTE`
- **`__slots__`** — `Board` の属性を `pieces` `hands` `turn` の 3 つに固定する。打ち間違い `board.trun = ...` が `AttributeError` になる
- **`itertools.product`** — 9×9 の全マスを `for f, r in product(range(1, 10), range(1, 10))` で回す（打つ手の生成）
- **`str.maketrans` / `translate`** — 半角数字を全角（７）と漢数字（六）に。`Square.__str__` が「７六」を返す

そして **SFEN**（将棋の局面の文字列）の読み書き、USI 形式の手（`7g7f`、`2b3c+`、`P*5e`）、日本語の表記（☗７六歩、☗２二角成、☗５五角打）、**perft** で既知の数（30 → 900 → 25470）と照合。

## ブラウザ版

インストールせずに遊べます → **https://hicocho.github.io/python-study/g37/**

ソースは [`docs/g37/game.py`](../docs/g37/game.py)。`Piece` / `Square` / `Move` / `Board`、手の生成、`make_move`、`describe`、そして `class Game` を **1 文字も変えずに**持ってきています。出口は 9×9 の `<div>` と持ち駒のボタン。後手の駒は CSS で 180° 回転。

## 遊び方（ターミナル）

```bash
python3 main.py                  # 2 人で交互
python3 main.py --cpu w          # 後手をランダム CPU に
python3 main.py --moves 8h       # そのマスの駒が動ける手を出す
python3 main.py --perft 3        # 3 手先までの手の数
python3 main.py --sfen "..."     # 途中の局面から
```

- 手は USI 形式。`7g7f`（７七の駒を７六へ）、`2b3c+`（成る）、`P*5e`（歩を５五に打つ）。`undo` で戻す、`q` でやめる
- 表示は先手が ` 歩`、後手が `v歩`。成り駒は と・杏・圭・全・馬・龍

## 仕様

- 盤は `{Square: Piece}` の辞書。`Square(file, rank)` は file が 1〜9（右から左）、rank が 1〜9（上から下）。７六 = `Square(7, 6)`
- 成れるのは金・玉・成り駒以外で、出発か到着が敵陣（先手なら一〜三段目）のとき。成る手と成らない手の両方を生成。歩・香が一段目、桂が一・二段目に行くときは成る手だけ
- 取った駒は成りを解いて持ち駒に。打つ手は空きマス全部（二歩などは g38）
- perft: 初期局面から 1 手 30、2 手 900、3 手 25470（既知の値と一致）

## メモ

### `IntFlag` — ビットで駒を表す

```python
class Piece(IntFlag):
    NONE = 0
    FU = 1; KY = 2; KE = 4; GI = 8; KI = 16; KA = 32; HI = 64; OU = 128
    PROMOTED = 256
    GOTE = 512
```

`Piece.KA | Piece.GOTE | Piece.PROMOTED` が後手の馬。種類は `piece & 255`、成りは `Piece.PROMOTED in piece`、後手は `Piece.GOTE in piece`。`IntFlag` は `Enum` と違って `|` `&` `in` が使えて、値は普通の整数（`str()` は数字、`.name` が `KA|GOTE`）。チェス（g22）は大文字小文字で色を分けていたが、将棋は成りもあるのでビットが楽。
注意: 種類の値を 1, 2, 3, … にすると `3 == FU | KY` になって名前が壊れる。**種類ごとに 1 ビット**。

### `__slots__`

```python
class Board:
    __slots__ = ("pieces", "hands", "turn")
```

インスタンスに `__dict__` を作らず、この 3 つだけを持つ。メモリが小さくなり、属性の打ち間違いが `AttributeError` になる。g23 の `dataclass` にも `slots=True` があるが、ここでは素のクラスで書いてみた。

### `str.maketrans` / `translate`

```python
ZENKAKU = str.maketrans("123456789", "１２３４５６７８９")
RANK_KANJI = str.maketrans("123456789", "一二三四五六七八九")
str(7).translate(ZENKAKU) + str(6).translate(RANK_KANJI)   # "７六"
```

1 文字ずつの置き換え表。g32 の `Sprite.recolor` と同じ道具で、今回は表示に使う。

### SFEN と USI

SFEN は一段目から順に、右（９）から左へ。数字は空きマスの数、`+` は成り、大文字が先手。手番と持ち駒（`S2Pb` = 先手が銀と歩 2、後手が角）が続く。USI の手は「元のマス + 先のマス + `+`」か「駒の文字 + `*` + 打つマス」。どちらも将棋ソフトの標準なので、他所の局面や棋譜がそのまま読める。

### 走る駒は `while` で「ぶつかるまで」

g22 の `ray` と同じ。香・角・飛（と馬・龍の走る向き）は `while sq.on_board:` で進み、駒があれば含めて止まる。後手は `dy` を反転するだけで同じ表を使える（`movement()`）。
