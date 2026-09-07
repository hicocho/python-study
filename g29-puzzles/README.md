# g29 アイテムと仕掛け（拾う・使う・開ける）

テキストアドベンチャー 5 段階の 3 つ目。屋根裏への扉には鍵がかかり、窓は歪んで開かない。
鍋を調べて鍵を見つけ、温室の鉄の棒を拾い、扉を開け、窓をこじ開けて脱出します。

今回の主題は 4 つです。

- **自作デコレータ** — `@command("take", "get", "拾う")` で `Game` のメソッドを「動詞の表」に登録する。g28 の長い `match` が消えた
- **クロージャと `nonlocal`** — 屋根裏の窓は「押した回数」を閉じ込めた関数。3 回押すか、鉄の棒があれば 1 回で外れる
- **`functools.partial`** — 「鍵で塞ぎを解く」共通の処理に、部屋ごとの違い（方角・鍵・文）を埋めて仕掛けにする
- **`__call__`** — 「調べると 1 回だけ物が出る」仕掛けは、状態を持つオブジェクトを関数のように呼ぶ

## ブラウザ版

インストールせずに遊べます → **https://hicocho.github.io/python-study/g29/**

ソースは [`docs/g29/game.py`](../docs/g29/game.py)。定数、`@command` デコレータ、`Direction` / `Command` / `Room` / `Reveal`、関数 12 個、そして `class Game` を **1 文字も変えずに**持ってきています。
持ってこなかったのは `Game.render()` と `main()` だけ。持ち物と解いた仕掛けの数を盤の下に出します。

## 遊び方（ターミナル）

```bash
python3 main.py
```

- `look 鍋` `examine 窓` — 調べる（仕掛けがあれば動く）
- `take 鍵` `drop 鍵` `inventory` — 拾う・置く・持ち物
- `open 扉` `use 鍵` `use 鉄の棒` `push 窓` — 仕掛けを解く
- `help` で使える言葉と言い換え

```
> look 鍋
鍋の底の塊を剥がすと、小さな鍵が出てきた。

> take 鍵
鍵を拾った。

> u
天井の扉には鍵がかかっている。

> open 扉
鍵が回った。扉が開き、梯子を上がれる。

> 
```

## 仕様

- 落ちているもの: 温室に「鉄の棒」。台所の鍋を調べると「鍵」が出る（1 回だけ）
- 仕掛け 2 つ: 階段の踊り場の天井の扉（`open 扉` / `use 鍵`。鍵が要る）、屋根裏の窓（`push 窓` 3 回、または `use 鉄の棒` / `open 窓` で 1 回）
- 塞がっている方角へ歩こうとすると理由が出る（「天井の扉には鍵がかかっている。」）
- 動詞 11（go / look / take / drop / inventory / use / open / push / map / help / quit）に言い換え 50 語。`help` はデコレータに書いた説明から作る
- 「鉄の棒」を `鉄の 棒` と分けて打っても `"".join(args)` で戻す。助詞は `へにを` だけ落とす（`の` は物の名前に入る）

## メモ

### 自作デコレータ — 「登録」という副作用

```python
ALIASES: dict[str, str] = {}
HANDLERS: dict[str, tuple[str, str, str]] = {}

def command(*names: str, doc: str = ""):
    def register(method):
        for name in names:
            ALIASES[name] = names[0]
        HANDLERS[names[0]] = (method.__name__, " / ".join(names[1:]), doc)
        return method
    return register

class Game:
    @command("take", "get", "pick", "拾う", "取る", doc="拾う")
    def do_take(self, *args: str) -> str:
        ...
```

`@command("take", ...)` は `do_take = command("take", ...)(do_take)` と同じ。`command` は引数を受けて `register` を返し、`register` がメソッドを受け取って**表に書き込んでからそのまま返す**。
メソッド自体は変わらないので、g11 以来使ってきた `@property` や `@dataclass` と違って「包む」のではなく「登録する」だけのデコレータです。
これで、動詞の表（`ALIASES`）・振り分け（`HANDLERS`）・`help` の 3 つが**メソッドの定義の真上**に集まり、動詞を足すときに触る場所が 1 か所になりました。
`execute` は `getattr(self, method_name)(*command.args)` で名前からメソッドを引く——g28 の `match` の 11 個の `case` が消えています。

### クロージャと `nonlocal` — 関数に状態を閉じ込める

```python
def make_window():
    pushes = 0

    def push(game):
        nonlocal pushes
        ...
        pushes += 1
        ...
    return push
```

`make_window()` が返す `push` は、外側の `pushes` を覚えたまま生き続けます（クロージャ）。`pushes += 1` と書き換えるには `nonlocal` が要る——書かないと `push` の中の新しい変数になってしまう。
窓のことしか知らない小さな状態を、クラスを作らずに持てます。`Game` ごとに `make_world()` → `make_window()` が呼ばれるので、別の対局とは混ざりません（テストで確認）。

### `functools.partial` — 共通の処理に、違いだけ埋める

```python
def unlock(game, direction, key, message): ...

open_door = partial(unlock, direction=Direction.UP, key="鍵", message="鍵が回った。扉が開き、梯子を上がれる。")
rooms["stairs"].actions[("open", "扉")] = open_door
```

「鍵で塞ぎを解く」は、どの扉でも同じ手順。`partial` は引数の一部を先に埋めた新しい関数を作るので、部屋ごとの違い（方角・鍵・文）だけを渡して仕掛けにできます。
`lambda game: unlock(game, Direction.UP, "鍵", "...")` でも同じですが、`partial` は「何を埋めたか」が `open_door.keywords` で見え、名前も付く。

### `__call__` — 関数のように呼べるオブジェクト

```python
class Reveal:
    def __init__(self, item, text, again): ...
    def __call__(self, game):
        if self.done:
            return self.again
        self.done = True
        game.room.items.append(self.item)
        return self.text
```

`actions` の値は「`game` を受けて文を返すもの」なら何でもよく、関数（クロージャ）も `partial` も `Reveal` のインスタンスも同じ形で呼べます（`action(self)`）。
クロージャで済むものと `__call__` の使い分け: 状態が 1 つで短ければクロージャ、状態が複数あって名前を付けたければクラス。鍋の仕掛けは `item` `text` `again` `done` の 4 つを持つのでクラスにしました。

### 仕掛けは `(動詞, 対象)` で引く

`room.actions[("open", "扉")]`。`do_open` `do_use` `do_push` `do_look` はまず `trigger(verb, target)` で仕掛けを探し、無ければ普通の返事。同じ仕掛けを複数のキーに登録できる（窓は `push` / `open` / `use 鉄の棒`）。
