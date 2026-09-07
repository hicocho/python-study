# g31 セーブと自動テスト（完成形）

テキストアドベンチャー 5 段階の完成形。「セーブ」は状態ではなく**コマンドの記録**を保存し、「つづきから」はそれを指し直して同じところへ戻ります（g26 の PGN と同じ考え方）。
記録とシナリオには SHA-256 の指紋を付け、書き換えられていれば断る。セーブはシナリオごと zip に同梱。
攻略ファイル（1 行 1 コマンド）を全部遊んでクリアできるか確かめる `--selftest` と、docstring の例を確かめる `--doctest` で自動テスト。

今回の主題は 4 つです。

- **`hashlib`** — `sha256(text.encode()).hexdigest()` で指紋。1 文字違えば別の値。記録・シナリオの改ざん検知に
- **`zipfile`** — `save.json` と `scenario.toml` を 1 つの zip に。`writestr` / `write` / `read`、`BadZipFile`
- **`doctest`** — docstring の `>>>` がそのままテスト。`doctest.testmod()` で 11 例
- **`io.StringIO` と `contextlib.redirect_stdout`** — 画面への出力を文字列に捕まえて、自動テストの中で検査する

## ブラウザ版

インストールせずに遊べます → **https://hicocho.github.io/python-study/g31/**

ソースは [`docs/g31/game.py`](../docs/g31/game.py)。`@command` / `Direction` / `Command` / `Room` / `Reveal` / `ScenarioError` / `SaveError` / `Scenario`、`fingerprint()` 〜 `make_world()` の関数 19 個、そして `class Game` を **1 文字も変えずに**持ってきています。
持ってこなかったのは `Game.render()` と zip を読み書きする `save()` / `load()`、攻略ファイルの関数と `main()` だけ。セーブは `save_data()` の辞書を JSON にして `localStorage` へ、つづきからは同じ `from_save()`。指紋の検証も同じ関数なので、`localStorage` を書き換えると「コマンドの記録が書き換えられている」と断ります。

## 遊び方（ターミナル）

```bash
python3 main.py --save save.zip            # q でやめるとセーブ
python3 main.py --load save.zip            # 続きから
python3 main.py --scenario cave --walkthrough walkthroughs/cave.txt   # 攻略ファイルを再生
python3 main.py --selftest                 # 全シナリオの攻略ファイルを遊んで確かめる
python3 main.py --doctest                  # docstring の例を確かめる
```

```
$ python3 main.py --save save.zip
> w
> n
> look 鍋
鍋の底の塊を剥がすと、小さな鍵が出てきた。

> take 鍵
鍵を拾った。

> q
やめました。

2 歩  行った部屋 3/11  解いた仕掛け 1/3
save.zip にセーブしました（コマンド 4 個）。--load save.zip で続きから。

$ python3 main.py --load save.zip
save.zip の続きから（4 コマンド、2 歩）。

$ python3 main.py --selftest
攻略ファイルで自動テスト:
  cave       海辺の洞窟      9 手  仕掛け 2/2  クリア
  mansion    夜の洋館      13 手  仕掛け 3/3  クリア

$ python3 main.py --doctest
doctest: 11 例のうち失敗 0
```

## 仕様

- **記録**: 世界を変える動詞（go / look / take / drop / use / open / push）だけを `"go w"` の形で `Game.record` に。map / help / inventory / 分からない語は入れない
- **セーブ**（`save.json`）: `version`、`scenario`（名前）、`scenario_sha256`（TOML の指紋）、`record`、`record_sha256`。状態そのものは入れない
- **zip**: `save.json` と `scenario.toml`。読むときは同梱のシナリオを検証して使うので、`scenarios/` が無い場所でも続きから遊べる
- **つづきから**: `Game(scenario)` を作って記録を順に `execute`。仕掛けの状態（押した回数、出したか）も自然にそろう
- **断る**: 形式が違う／記録の指紋が合わない／シナリオの指紋が合わない／zip でない・中身が足りない → `SaveError`
- **攻略ファイル**: `walkthroughs/<シナリオ名>.txt`。`#` から後ろと空行は無視。`--selftest` は `glob` で全部見つけ、出力を `StringIO` に捕まえて、クリアしたかだけを表にする。1 つでもクリアできなければ終了コード 1

### 検証

| 対象 | 結果 |
|---|---|
| 記録 | 9 個の文のうち世界を変える 5 個だけが残る |
| save → load | zip に 2 ファイル（2,595 バイト）。読み戻して部屋・持ち物・歩数・仕掛けが同じ。続きから脱出 |
| 改ざん | 記録を書き換え／同梱シナリオを書き換え／version 違い／zip でない → すべて `SaveError` |
| `from_save` | シナリオが変わっていれば「セーブしたときと変わっている」 |
| 攻略ファイル | 洋館 13 手、洞窟 9 手、どちらもクリア。途中で止まる攻略はクリアにならない |
| `--selftest` | `redirect_stdout` で捕まえた出力に「クリア」が 2 つ、「クリアできない」は無し |
| `--doctest` | 11 例、失敗 0 |
| ブラウザ | セーブ → 開き直し → つづきからで同じ状態。`localStorage` を書き換えると断る |

## メモ

### 「読む＝指し直す」

g21 の `pickle` は状態を丸ごと保存しました。ここでは**コマンドの記録**だけを保存し、読むときに指し直す。
クロージャの中の `pushes`（g29）のように「保存しにくい状態」があっても、同じコマンドを同じ順で実行すれば同じところに着く。セーブの中身は人が読める JSON の 10 行になり、`Game` に「保存用の変換」を足す必要がありません。
g26 の PGN と同じ設計で、`from_save` は `from_pgn` と同じ形です。

### `hashlib` — 指紋

```python
def fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
```

SHA-256 は「同じ入力なら同じ 64 桁、1 文字違えば全く別の 64 桁」。記録の指紋を一緒に保存しておけば、記録を書き換えられたことが分かる（指紋自体も書き換えられれば分かりませんが、**うっかり壊した**ことは確実に見つかる）。
シナリオの指紋は「セーブしたときと世界が同じか」の確認。TOML を直したあとの古いセーブは、指し直しても同じところに着かないので断ります。

### `zipfile` — 複数ファイルを 1 つに

```python
with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
    archive.writestr("save.json", json.dumps(...))
    archive.write(self.scenario.path, "scenario.toml")
```

`writestr` は文字列から、`write` はファイルから。読むときは `archive.read("save.json")` が bytes。zip でないファイルは `BadZipFile`、中に無いファイルは `KeyError`——`except (OSError, zipfile.BadZipFile, KeyError, json.JSONDecodeError)` でまとめて `SaveError` に包む（g30 の `raise from`）。

### `doctest` — docstring の例がテストになる

```python
    >>> parse("look at the 扉")
    Command(verb='look', args=('扉',))
```

`>>>` の行を実行して、次の行と比べる。読む人への例と、壊れていないかの確認が**同じ場所**にある。`doctest.testmod()` はモジュール内の全 docstring を探す。`NamedTuple` の `__repr__`（g22）や `Direction` の `repr`（g27）が、ここで「出力の形」として役に立ちました。

### `io.StringIO` と `redirect_stdout`

```python
buffer = io.StringIO()
with redirect_stdout(buffer):
    replies = play_script(game, read_walkthrough(path))
```

`print` の行き先を一時的に文字列にする。テストの中で「画面に何が出たか」を検査したり、うるさい出力を捨てたりできる。この `Game` は `print` しない設計なので中身はほぼ空ですが、テストは「空であること」も確かめられます。

### 5 段階のテキストアドベンチャーで増えたもの

| # | 主題 | `Game` に増えたもの |
|---|---|---|
| g27 | `StrEnum` / `textwrap` / `__str__` `__repr__` | 部屋・方角・地図 |
| g28 | `shlex` / `difflib` / `match` | 文の解釈・目につくもの |
| g29 | デコレータ / クロージャ / `partial` / `__call__` | 持ち物・仕掛け・動詞の表 |
| g30 | `tomllib` / 自作例外 / `__getattr__` / `glob` | 世界を TOML から |
| g31 | `hashlib` / `zipfile` / `doctest` / `StringIO` | 記録・セーブ・自動テスト |
