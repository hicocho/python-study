# g30 シナリオ（世界を TOML で）

テキストアドベンチャー 5 段階の 4 つ目。g27〜g29 でコードに書いていた部屋・通路・仕掛けを、**TOML ファイル**に移しました。
プログラムはファイルを読んで世界を組み立てるだけ。「夜の洋館」と、新しく書いた「海辺の洞窟」を同じ `Game` で遊べます。
読めないファイルや足りない項目は、遊ぶ前に**どこが悪いかを文で**返します。

今回の主題は 4 つです。

- **`tomllib`** — 標準ライブラリで TOML を読む（3.11〜）。部屋は `[[rooms]]` の配列、目につくものは `[rooms.things]` の表
- **自作例外と `raise … from`** — `ScenarioError` に「どのファイルの何が悪いか」を持たせる。元の `TOMLDecodeError` は `__cause__` に残す
- **`__getattr__`** — `scenario.title` のように TOML のキーを属性で読む。無い名前は `AttributeError`（`from None` で連鎖を消す）
- **`pathlib.glob`** — `scenarios/*.toml` を集めて `--list`。ブラウザ版では PyScript の仮想ファイルにも同じ `glob` が効く

## ブラウザ版

インストールせずに遊べます → **https://hicocho.github.io/python-study/g30/**

ソースは [`docs/g30/game.py`](../docs/g30/game.py)。`@command` デコレータ、`Direction` / `Command` / `Room` / `Reveal` / `ScenarioError` / `Scenario`、`load_scenario()` 〜 `make_world()` の関数 18 個、そして `class Game` を **1 文字も変えずに**持ってきています。
持ってこなかったのは `Game.render()` と `main()` だけ。TOML は PyScript の `config` で仮想ファイルシステムに置き、同じ `SCENARIO_DIR.glob("*.toml")` でセレクトボックスを作ります。

## 遊び方（ターミナル）

```bash
python3 main.py                          # 夜の洋館（既定）
python3 main.py --scenario cave          # 海辺の洞窟
python3 main.py --list                   # 遊べるシナリオの一覧
python3 main.py --check scenarios/cave.toml   # シナリオの検証だけ
python3 main.py --scenario my.toml       # 自分で書いた TOML
```

```
$ python3 main.py --list
  cave       海辺の洞窟  （部屋 5、仕掛け 2）
  mansion    夜の洋館  （部屋 11、仕掛け 3）
$ python3 main.py --scenario cave
【海辺の洞窟】 満ち潮が迫っている。洞窟を抜けて舟へ。

【浜】
濡れた砂。崖の下に、黒い洞窟の口が開いている。
目につくもの: 崖
落ちているもの: 松明
出口: 東

> e
【洞窟】
暗い。水音が奥から聞こえる。
目につくもの: 壁
出口: 西、東

> e
【水たまりの間】
天井から水が滴る。岩の裂け目の向こうに光が見える。
目につくもの: 裂け目、岩
出口: 西、北

> 
```

## シナリオの書き方

[`scenarios/mansion.toml`](scenarios/mansion.toml) と [`scenarios/cave.toml`](scenarios/cave.toml) を見てください。

```toml
title = "海辺の洞窟"
start = "beach"
goal = "boat"
intro = "満ち潮が迫っている。洞窟を抜けて舟へ。"
ending = "舟に乗り込んだ。潮が満ちる前に岬を回れそうだ。"

[[rooms]]
id = "beach"
name = "浜"
x = 0
y = 0
description = "濡れた砂。崖の下に、黒い洞窟の口が開いている。"
items = ["松明"]
[rooms.things]
"崖" = "登れそうにない。"

[[exits]]
from = "beach"
direction = "east"
to = "cave"

[[puzzles]]
type = "push"
room = "pool"
direction = "east"
reason = "裂け目に岩が挟まって通れない。"
times = 5
tool = "槌"
partial = "押した。びくともしない（{n} 回目）。"
with_tool = "槌で叩くと、岩が砕けて裂け目が開いた。"
done = "5 度目でようやく岩が転がった。"
after = "東へ、光の方へ進める。"
already = "裂け目はもう開いている。"
verbs = [["push", "岩"], ["use", "槌"]]

[items]
"槌" = "錆びているが、まだ振れる。"
```

- 通路は片方向だけ書けば、戻り道は自動（`connect`）
- 仕掛けは `type` が 3 種類: `lock`（鍵で開く。`key` `verbs`）、`reveal`（調べると物が出る。`thing` `item`）、`push`（何度か押すか道具で開く。`times` `tool`）
- 日本語のキー（`"崖" = …`）は引用符で囲む（TOML の素のキーは英数字だけ）

## 仕様

- 検証 8 種: TOML として読めない／`title` `start` `goal` `rooms` `exits` が無い／部屋に `id` `name` `description` `x` `y` が無い／`start` `goal` が無い部屋／通路の `from` `to` が無い部屋／`direction` が方角でない／仕掛けの `room` が無い部屋／仕掛けの `type` を知らない
- 読めないときは `ScenarioError`。`main()` はそれを受けて `SystemExit` で 1 行のメッセージ（トレースバックを見せない）
- 仕掛けの状態（押した回数、出したかどうか）は `Game` ごと。同じシナリオから 2 つ `Game` を作っても混ざらない

## メモ

### `tomllib` — 設定ファイルを標準ライブラリで

```python
data = tomllib.loads(path.read_text(encoding="utf-8"))
```

`json` より人が書きやすく（コメント、複数行文字列、`[[rooms]]` の配列）、`pickle` と違って安全に読めます。読むだけ（書く関数は無い）なので、シナリオのように「人が書いてプログラムが読む」ものに向く。
文字列の中の改行は `"""…"""` で書け、g27 の `dedent` と同じ処理で字下げを消します。

### 自作例外と `raise … from`

```python
class ScenarioError(Exception):
    """シナリオのファイルがおかしい。どこが悪いかを文で持つ。"""

    try:
        data = tomllib.loads(...)
    except tomllib.TOMLDecodeError as error:
        raise ScenarioError(f"{path} は TOML として読めない: {error}") from error
```

g25 の `TimeUp` は「合図」のための例外でした。`ScenarioError` は**理由を運ぶ**例外。`tomllib` の `TOMLDecodeError` や `OSError` を受けて、ファイル名を足した自分の例外に包み直す。
`from error` で元の例外が `__cause__` につながり、トレースバックに「この例外が原因で」と両方出ます。`main()` では `except ScenarioError` だけ書けば、TOML の文法エラーも足りない項目もファイルが無いのも 1 か所で受けられる。

### `__getattr__` — 無い属性が来たときだけ

```python
class Scenario:
    def __getattr__(self, name):
        try:
            return self._data[name]
        except KeyError:
            raise AttributeError(f"シナリオに {name!r} という項目は無い") from None
```

`__getattr__` は**普通の属性の探索に失敗したときだけ**呼ばれます（`__getattribute__` は毎回）。`scenario.title` → `_data["title"]`。`scenario.path` は普通の属性なので呼ばれない。
無いキーは `AttributeError` にする——`hasattr` や `getattr(x, name, default)` がそれを期待しているから。`from None` は「`KeyError` が原因」という連鎖を消して、使う側に `AttributeError` だけを見せる。

### `pathlib.glob`

`sorted(SCENARIO_DIR.glob("*.toml"))` で候補を集め、`path.stem` を名前にする。読めないファイルがあっても `--list` は止まらず「読めない: …」と出す。ブラウザ版は PyScript の `config` で TOML を仮想 FS に置くので、**同じ `glob` がそのまま動きます**。

### 世界を作る関数は 1 つに戻った

g27 の `make_world()` は部屋を 11 個手で書いていました。g30 の `make_world(scenario)` は `for r in scenario.rooms` の 3 行。仕掛けは `BUILDERS[puzzle["type"]](rooms, puzzle)` で `type` ごとの作り方を辞書で引く（g29 の `partial` / クロージャ / `__call__` はそのまま中で使っています）。
