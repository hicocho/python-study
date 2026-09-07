# g23 チェスのルール（チェック・キャスリング・アンパッサン）

チェスの 2 段階目。g22 の「駒の動き」に本物のルールを足しました。
自分のキングを晒す手は指せず、キャスリング・アンパッサン・成りが入り、チェックメイトかステイルメイトで終わります。

今回の主題は 3 つです。

- **`@dataclass` の `__eq__` と `__hash__`** — `Board` を dataclass にして局面を `==` で比べる。`dict` を持つので `__hash__` は自分で書く
- **`dataclasses.replace`** — 「この局面から手番と配置だけ変えた新しい局面」を 1 行で作る
- **`functools.cached_property`** — 利き（取れるマスの集合）を一度計算したら覚える。局面を変えない前提とセットで

## ブラウザ版

インストールせずに遊べます → **https://hicocho.github.io/python-study/g23/**

ソースは [`docs/g23/game.py`](../docs/g23/game.py)。定数と `Square` / `Move` / `Board`、`CASTLING` の表、`ray()` 〜 `count_moves()` の関数 13 個、そして `class Game` を **1 文字も変えずに**持ってきています。
持ってこなかったのは `Game.render()` と `main()` だけ。チェックされたキングは class で赤くします。

## 遊び方（ターミナル）

```bash
python3 main.py                # 2 人で交互に
python3 main.py --cpu b        # 黒をランダム CPU に
python3 main.py --fen "4k3/8/8/8/8/8/4r3/4K3 w - -"   # この局面から
```

- `e2e4` のように指す。キャスリングはキングを 2 マス動かす（`e1g1` / `e1c1`）。成るときは `e7e8q`
- `undo` で戻す（CPU 相手なら 2 手）／ `q` でやめる

```
> e1g1
8  r . b q k b . r
7  p p p p . p p p
6  . . n . . n . .
5  . . . . p . . .
4  . . B . P . . .
3  . . . . . N . .
2  P P P P . P P P
1  R N B Q . R K .
   a b c d e f g h

4 手目 黒の番   直前 e1g1
> 
```

キャスリングで `e1` のキングが `g1`、`h1` のルークが `f1` へ。

## 仕様

- **合法手** = 動ける手のうち「指したあと自分のキングが相手の利きに入らない」もの。チェック中はそれを解く手だけ
- **キャスリング**: 権利が残っていて（キングもそのルークも動いていない）、間が空いていて、キングが今チェックされておらず、通るマスと着くマスが利きに入っていない
- **アンパッサン**: 相手のポーンが 2 歩進んだ直後だけ。通り過ぎたマスを FEN の 4 項目目に持つ
- **成り**: 最終段に着くポーンは Q/R/B/N の 4 つの手に展開
- **終局**: 合法手が無くて、チェックされていれば負け、いなければステイルメイト（千日手・50 手・駒不足は g24 で）
- FEN は 4 項目（配置 手番 キャスリング アンパッサン）を読み書き

### perft（既知の値との照合）

| 局面 | 1 手 | 2 手 | 3 手 | 4 手 |
|---|---|---|---|---|
| 初期局面 | 20 | 400 | 8,902 | 197,281 |
| Kiwipete（キャスリング・アンパッサン・成りが混ざる局面） | 48 | 2,039 | 97,862 | |
| 局面 3 | 14 | 191 | 2,812 | 43,238 |
| 局面 4 | 6 | 264 | 9,467 | |
| 局面 5 | 44 | 1,486 | 62,379 | |

5 局面すべて既知の値と一致（合計 30 秒ほど）。これで特殊ルール込みの合法手が正しいと言えます。

## メモ

### `@dataclass` と `__hash__` — 局面を比べる、集合に入れる

```python
@dataclass
class Board:
    pieces: dict[Square, str]
    turn: str = WHITE
    castling: frozenset[str] = frozenset("KQkq")
    en_passant: Square | None = None

    def __hash__(self) -> int:
        return hash((frozenset(self.pieces.items()), self.turn, self.castling, self.en_passant))
```

`@dataclass` は `__eq__` を作ってくれるので、同じ配置・手番・権利なら `board1 == board2` が `True`。
ただし `eq=True` で `frozen=False` の dataclass は **`__hash__` が `None` にされて**集合や辞書のキーに使えなくなります（変わりうるものを hash すると壊れるから）。
ここでは「`make_move` で作ったあとは変えない」約束のもとで自分で `__hash__` を書きました。`dict` は hash できないので `frozenset(items())` に変えてから。
g24 の千日手（同じ局面が 3 回）はこの `__hash__` があって初めて `Counter` で数えられます。

### `dataclasses.replace` — 一部だけ変えた新しいもの

```python
    return replace(board, pieces=pieces, turn=other(board.turn),
                   castling=board.castling - set(lost), en_passant=en_passant)
```

`replace(obj, **changes)` は「obj のコピーを作って、指定したフィールドだけ差し替える」。
g22 の `copy()` ＋ 代入より意図が読めて、フィールドが増えても呼び出しが壊れません。`NamedTuple` の `_replace` と同じ考え方です。

### `cached_property` — 利きは局面ごとに 1 回

```python
    @cached_property
    def attacked(self) -> dict[str, set[Square]]:
        return {color: attacked_squares(self, color) for color in (WHITE, BLACK)}
```

「白の利き」「黒の利き」は合法手の判定・キャスリングの可否・チェック表示と何度も聞かれます。
`@property` だと毎回計算、`@cached_property` なら最初の 1 回だけ計算して `__dict__` に覚える。
**局面が変わらない**から成り立つ仕組みで、`__hash__` を自分で書いたのと同じ約束（作ったあとは変えない）に支えられています。

### 合法手は「指してみて確かめる」

```python
def legal_moves(board):
    moves = []
    for move in all_moves(board) + castling_moves(board):
        after = make_move(board, move)
        if after.king_square(board.turn) not in after.attacked[after.turn]:
            moves.append(move)
    return moves
```

ピン（動かすとキングが晒される駒）を個別に計算せず、全部指してみて「自分のキングが相手の利きに入っていないか」を見る。
遅いが単純で間違えにくい。`make_move` が新しい局面を返す作りだから、盤を戻す処理なしでこう書けます。

### 「利き」と「動ける手」は別

`piece_targets` は味方の駒のマスも含みます（味方を守っているマス）。g22 の `moves_from` から分けたのは、
キングが「守られている敵の駒」を取れないようにするため——攻撃側の視点では、自分の駒のマスも利きに入っている必要があります。
ポーンだけは「動く先」と「利き」がまったく違うので `pawn_attacks` を別に持ちました。

### キャスリングの権利は「失う」方向にだけ動く

```python
CASTLING_RIGHTS = {e1: "KQ", a1: "Q", h1: "K", e8: "kq", a8: "q", h8: "k"}
lost = CASTLING_RIGHTS.get(move.src, "") + CASTLING_RIGHTS.get(move.dst, "")
```

キングやルークが**動いた**ときも、ルークが**取られた**とき（`move.dst` が h1 など）も同じ表で引けます。権利は `frozenset` から引き算するだけ。
