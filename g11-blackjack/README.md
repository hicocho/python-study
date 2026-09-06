# g11 ブラックジャック

ディーラーと 21 を競う CLI ゲームです。チップ 100 枚から始めて、ラウンドごとに賭け、
最初の 2 枚で 21 なら**ブラックジャック**で 1.5 倍。最初の 2 枚のときだけ、賭け金を倍にして
1 枚だけ引く**ダブルダウン**ができます。ディーラーは 17 になるまで引きます。

今回は「新しいデータの持ち方」がテーマです。g07〜g10 は `class` に `__init__` で値を詰めてきましたが、
Python には**書くだけで形が決まる**道具があります。

今回の主題は 3 つです。

- **`dataclass` と `Enum`** — カードとマークを「値の組」として定義する。型ヒントが必須になる
- **`@property`** — `hand.total` と書いて、そのたびに計算させる。A の 1／11 はここで決まる
- **`match` 文** — 入力と精算を、`if`-`elif` ではなく「形で分ける」

## ブラウザ版

インストールせずに遊べます → **https://hicocho.github.io/python-study/g11/**

ソースは [`docs/g11/game.py`](../docs/g11/game.py)。定数 4 つと `Suit` / `RANKS` / `FACES` /
`RESULT_TEXT` / `RECORD_LABEL`、`Card` / `Hand` の 2 クラス、`make_deck()` / `cards_text()` /
`dealer_play()` / `judge()` / `payout()`、そして `class Game` を **1 文字も変えずに**持ってきています
（ステップの目印コメント `# ←` を外しただけ。`ast` で切り出して文字列比較で確認済み）。

持ってこなかったのは `hidden_text()` と `ask_bet()` と `ask_action()` と `main()`、それに `Game.render()` だけ。
違うのは**入口と出口**で、

- 入口：`h` / `s` / `d` の文字入力 → ボタン（キーボードの H / S / D も効く）
- 出口：`[♠A] [♥10]` の文字列 → `<div>` のカード
- チップの置き場：CLI 版は 1 回きり → `localStorage` に持ち越す

## 遊び方（ターミナル）

```bash
python3 main.py
```

- 賭ける枚数を数字で入れる（`0` でやめる）
- `h` もう 1 枚 ／ `s` 止める ／ `d` ダブルダウン（最初の 2 枚のときだけ）

```
チップ 100 枚。いくら賭けますか？（0 でやめる）> 10

ディーラー: [♥8] [??]
あなた:     [♣9] [♠7]  = 16
賭け金 10 枚 / 山 48 枚

h: もう 1 枚 / s: 止める / d: ダブルダウン > s

ディーラー: [♥8] [♦K]  = 18
あなた:     [♣9] [♠7]  = 16
賭け金 10 枚 / 山 48 枚

ディーラーの勝ち  -10 枚
```

- `[??]` はディーラーの伏せ札。勝負が決まると開きます
- `(soft)` は A を 11 として数えている状態

## 仕様

- 1 デッキ 52 枚。残りが 15 枚を切ったら次のラウンドで切り直す
- 最初の 2 枚で 21 が**ブラックジャック**。配当 1.5 倍（10 枚賭けて +15）。3 枚以上の 21 はただの 21
- どちらかが最初からブラックジャックなら、その場で決着（両方なら引き分け）
- **ディーラー**は合計 17 以上になるまで引く。ソフト 17（A+6）でも止まる
- **ダブルダウン**は最初の 2 枚のとき、同額をもう一度出せるなら。賭け金を倍にして 1 枚だけ引き、そのまま勝負
- スプリット・インシュランス・サレンダーは無し
- チップが 0 になるか、賭け金に `0` を入れたら終了。戦績（勝ち・負け・引き分け・BJ・バースト）が出る

## メモ

### `dataclass` — 「値の組」を書くだけで作る

```python
@dataclass(frozen=True)
class Card:
    suit: Suit
    rank: str
```

これで `__init__` も `__repr__` も `==` も付いてきます。g07 からずっと書いてきた
`def __init__(self, x, y): self.x = x; self.y = y` の定型を、**属性の名前と型を並べるだけ**に置き換えるもの。

`frozen=True` は「作ったら変えられない」。カードは配られたあとに絵柄が変わったりしないので、
変えられないほうが正しいし、変えられないものは**辞書のキーや集合の要素**にもできます。

`suit: Suit` の `: Suit` は**型ヒント**。`dataclass` はこの注釈を見て属性を決めるので、ここでは飾りではなく必須です。
それ以外の場所（`def judge(player: Hand, dealer: Hand) -> str:`）では実行に影響しませんが、
関数の入口と出口が読めるので、今回から付けています。

### `Enum` — 4 つしかないものは 4 つしかないと書く

```python
class Suit(Enum):
    SPADE = "♠"
    HEART = "♥"
    DIAMOND = "♦"
    CLUB = "♣"
```

マークを `"♠"` の文字列で持ってもゲームは動きます。`Enum` にする理由は、
**`Suit.SPADE` 以外の値が存在しないことをコードが保証する**からです。`for suit in Suit` と回せば
4 つ全部が出てきて、5 つ目を作ることはできません。表示に使う記号は `.value` で取り出します。

### `@property` — 計算した値を、変数のように読む

```python
    @property
    def total(self) -> int:
        return self.hard_total + 10 if self.is_soft else self.hard_total
```

`hand.total()` ではなく `hand.total` と書けます。読むたびに計算されるので、
`add()` でカードが増えても**古い値が残る心配がありません**。合計を `self.total` に持っておいて
`add()` のたびに更新する書き方もできますが、それは「同じ事実を 2 か所に持つ」形で、片方の更新を忘れた瞬間に嘘になります。

### A は「1 で数えて、余裕があれば 10 を足す」

A を 1 にするか 11 にするかは、手札全体を見ないと決まりません。総当たりで組み合わせを試す書き方もありますが、
実は答えは 1 つです。

```python
    @property
    def is_soft(self) -> bool:
        has_ace = any(card.rank == "A" for card in self.cards)
        return has_ace and self.hard_total + 10 <= TARGET
```

**11 として数える A は多くても 1 枚**（2 枚で 22 になる）ので、「A が 1 枚以上あって、10 足しても 21 以下」なら足す、
それだけ。`Card.point` が A を 1 として返しているのは、この計算を `Hand` 側に寄せるためです。
20000 手を「A の 1／11 の全組み合わせ」と突き合わせて一致しました。

### `match` 文 — 入力を「形」で分ける

```python
        match answer:
            case "h" | "hit":
                return "hit"
            case "s" | "stand":
                return "stand"
            case "d" | "double" if can_double:
                return "double"
            case _:
                print("h か s で答えてください。")
```

`if answer in ("h", "hit"): ... elif ...` と同じことですが、**`|` で「どれか」、`if` で条件、`_` で「それ以外」**が
1 つの構文に収まっています。`case "d" | "double" if can_double:` の `if` は**ガード**と呼ばれ、
ダブルダウンできないときは `"d"` を打っても `case _` に落ちます。

`payout()` も `match` です。

```python
    match result:
        case "blackjack":
            return bet + bet * 3 // 2
        case "win":
            return bet * 2
        case "push":
            return bet
        case "lose" | "bust":
            return 0
    raise ValueError(f"知らない結果: {result}")
```

`match` の下の `raise` は「どの `case` にも当たらなかった」ときにだけ届きます。
結果の種類を増やして `payout` の直し忘れがあると、黙って 0 を返す代わりにここで落ちます。

### 賭け金は先に卓へ出す

```python
        self.chips -= bet                                   # 賭け金は先に卓へ出す
        ...
        self.chips += payout(self.result, self.bet)         # 戻ってくる額（賭け金込み）
```

「勝ったら +bet、負けたら −bet」と書くと、ブラックジャック（+1.5 倍）やダブルダウン（賭け金が途中で変わる）で
場合分けが増えます。**賭けた瞬間に減らし、精算で「戻る額」を足す**と、`payout()` は「戻る額」だけを答えればよく、
ラウンドの途中で賭け金が倍になっても同じ式で済みます。

20000 ラウンドを乱暴に回して、**毎回 `手持ち = 前 − 賭け金 + 戻り`** が成り立つことを確かめました。

### `Counter` — 数えるだけの辞書

```python
        self.record = Counter()
        self.record[self.result] += 1
        ...
        game.record.most_common()
```

g10 の `defaultdict(int)` と同じ「無いキーは 0」に加えて、`most_common()` で**多い順に並べて**くれます。
戦績の表示が 1 行で済むのはこのためです。

### `dealer_play(hand, draw)` — 山ではなく「引く関数」を渡す

```python
def dealer_play(hand: Hand, draw) -> None:
    while hand.total < DEALER_STOP:
        hand.add(draw())
```

ステップ 3 では `deck` を渡して `deck.pop()` していました。ステップ 5 で `Game.draw()` に
「山が尽きたら新しい山を切る」を足したので、`dealer_play` には**山そのものではなく、引くための関数**を渡しています。
g10 の `key=lambda` と同じ「関数を値として渡す」形で、`dealer_play` は山の中身を知らなくてよくなりました。

### ブラウザ版：`@dataclass` が消えていた

共有部分は `ast` で切り出していますが、`node.lineno` は `class` の行を指し、
**その上にあるデコレータ行は範囲に入りません**。組み立てた `game.py` の `Card` は
ただのクラスになっていて、`Card() takes no arguments` で落ちました。
g10 にはトップレベルのデコレータが無かったので気づかなかった穴で、
`decorator_list` の最初の行から取るように直しました。

見つけたのは Playwright ではなく、その手前の「同じ乱数の種で CLI 版とブラウザ版を自動対局させる」検証です。
配る前に落ちたので 1 ラウンド目で分かりました。

### ブラウザ版だけの追加：チップの持ち越し

```python
game = Game(load_chips())
...
save_chips(game.chips)
```

CLI 版は起動ごとに 100 枚ですが、ブラウザ版は `localStorage` に残します。
`Game` が `chips` を引数で受け取る作りにしてあるので、差し替えは外側だけで済みました（g09 のハイスコアと同じ形）。
