# g27 冒険（部屋と移動）

テキストアドベンチャー 5 段階の 1 つ目。夜の洋館に閉じ込められた。部屋を歩いて出口を探します。
方角（`n` `north` `北`）で歩き、`look` で見回し、`map` で行った部屋の地図。出口に着いたらクリア。

今回の主題は 3 つです。

- **`enum.StrEnum`** — `Direction.NORTH == "north"`。値が文字列そのものなので、表示にも辞書のキーにもそのまま使える。`parse` で別名（`n` `北`）を受ける
- **`textwrap`** — `dedent` で字下げした説明文を戻し、`fill` で折り返す。日本語は空白が無いので文字数で折る
- **`__str__` と `__repr__`** — `print(room)` はプレイヤー向けの文章、`[room]` やデバッガでは `Room('pantry', exits=['south'])`

## ブラウザ版

インストールせずに遊べます → **https://hicocho.github.io/python-study/g27/**

ソースは [`docs/g27/game.py`](../docs/g27/game.py)。定数と `Direction` / `Room`、`connect()` / `make_world()` / `draw_map()`、そして `class Game` を **1 文字も変えずに**持ってきています。
持ってこなかったのは `Game.render()` と `main()` だけ。出口は `<pre>` のログで、`print(game.go(...))` が「ログに 1 段落足す」に変わります。方角のボタンは行ける方角だけ押せます。

## 遊び方（ターミナル）

```bash
python3 main.py
python3 main.py --width 40     # 文章の折り返し幅（文字数）
```

- `n` `s` `e` `w` `u` `d`（`north` `北` でも）で歩く
- `look`（`l`）で見回す、`map`（`m`）で地図、`q` でやめる

```
> n
【広間】
シャンデリアの下、大きな階段が二階へ伸びている。床の埃に、自
分以外の足跡はない。
出口: 南、西、東、北

> w
【台所】
冷えた竈と、鍋がいくつか。奥の扉の向こうから、かすかに風の音
がする。
出口: 南、東、北

> map


  [台所]     広間
           玄関

> 
```

## 仕様

- 部屋は 11（玄関・食堂・書斎・台所・広間・温室・貯蔵庫・階段の踊り場・バルコニー・屋根裏・外）。3×3 と屋根裏、外
- 出口はすべて双方向（`connect` が逆向きも作る）。全部屋に到達でき、出口までは最短 4 歩
- 地図は行った部屋だけを、北を上・西を左に、今いる部屋を `[ ]` で
- この段階では鍵も物も無い（g28 でコマンド解析、g29 でアイテムと仕掛け、g30 でシナリオを TOML から、g31 でセーブと自動テスト）

## メモ

### `StrEnum` — 値が文字列そのもの

```python
class Direction(StrEnum):
    NORTH = "north"
    ...

Direction.NORTH == "north"          # True
{Direction.NORTH: "hall"}["north"]  # 文字列でも引ける
f"{Direction.NORTH}"                # "north"
```

g11 の `Enum` は `Suit.HEART.value` と `.value` を挟む必要がありました。`StrEnum`（3.11〜）は**メンバーが `str` でもある**ので、
辞書のキー・比較・f-string にそのまま使え、しかも `Direction.NORTH` と名前で参照できて打ち間違いに強い。
`Direction("north")` で文字列から作れて、無い値は `ValueError`——`parse` はそれを `None` に変えるだけです。
`label`（日本語）と `opposite`（逆方向）は `@property` で。

### `textwrap` — 説明文をコードの中に書く

```python
        Room("entrance", "玄関", """
            重い扉は背後で閉まってしまった。
            天井の高いホールに、埃っぽい絨毯が続いている。""", 1, 0),

        text = "".join(line.strip() for line in textwrap.dedent(self.description).splitlines())
        body = textwrap.fill(text, width=WIDTH)
```

三重引用符の文章はコードの字下げがそのまま入るので、`dedent` で共通の字下げを消します。
`fill` は幅で折り返しますが、**単語の区切り（空白）で折る**仕組みなので、空白の無い日本語は 1 単語扱い——`break_long_words`（既定で有効）が文字数で切ってくれます。
元の改行を一度捨てて（`"".join`）から折り直すので、幅を `--width` で変えても文章が崩れません。

### `__str__` と `__repr__` — 誰に見せるか

```python
    def __str__(self) -> str:   # print(room) / f"{room}"
    def __repr__(self) -> str:  # repr(room) / [room] / f"{room!r}" / デバッガ
```

`print(room)` は `__str__`、リストの中や `!r` は `__repr__`。プレイヤー向けの文章と、開発者向けの短い形を分けておくと、
`print(rooms.values())` したときに画面が文章で埋まりません。`dataclass` は `__repr__` を自動で作りますが、`exits` の `Direction` が長く表示されるので自分で書き直しました。

### `connect` — 出口は双方向に

`rooms[a].exits[d] = b` と `rooms[b].exits[d.opposite] = a` を 1 か所で。片方だけ書いて「戻れない部屋」ができるのを防ぎます。テストで全出口の逆向きを確かめました。

### 地図は座標から描く

部屋に `x, y` を持たせ、`draw_map` は `y` の大きい順（北が上）に行を作り、`str.center(8)` で幅をそろえます。行った部屋（`visited`）だけを出すので、歩くほど地図が埋まる。
