# g28 コマンド解析（文で遊ぶ）

テキストアドベンチャー 5 段階の 2 つ目。部屋に「目につくもの」が増え、
`look at the 燭台` `examine 地図` `go north` `北へ` のように**文で**打てるようになりました。
言い換え（`examine` `x` `調べる`）は同じ動詞に寄せ、打ち間違い（`lok`、`燭代`）は「もしかして」で返します。

今回の主題は 3 つです。

- **`shlex.split`** — 引用符を考えて語に分ける。`look "old map"` が 2 語になる。閉じていない引用符は `ValueError`
- **`difflib.get_close_matches`** — 似た言葉を探す。`lok` → `look`、`燭代` → `燭台`
- **同義語の逆引き辞書と `match` 文** — `VERBS`（動詞 → 言い換えの集合）から `ALIASES`（言い換え → 動詞）を内包表記で作り、`Command` を `match` で振り分ける

## ブラウザ版

インストールせずに遊べます → **https://hicocho.github.io/python-study/g28/**

ソースは [`docs/g28/game.py`](../docs/g28/game.py)。定数と同義語の表、`Direction` / `Command` / `Room`、関数 7 個、そして `class Game` を **1 文字も変えずに**持ってきています。
持ってこなかったのは `Game.render()` と `main()` だけ。入力欄の文字列を `parse()` に渡し、`Game.execute()` の返事をログに足す——CLI 版のループ 1 回ぶんと同じです。

## 遊び方（ターミナル）

```bash
python3 main.py
```

- `look at the 扉` `examine 燭台` `x 地図` `調べる 窓` — 目につくものを調べる
- `go north` `walk n` `北へ` `n` — 歩く
- `map` `help` `quit`

```
> look at the 扉
押しても引いても動かない。外から閂がかかっているようだ。

> lok
「lok」は分からない。もしかして「look」？

> w
【食堂】
長いテーブルに、燭台が一つ。蝋はとうに燃え尽きている。
目につくもの: 燭台、テーブル
出口: 東、北

> examine 燭代
「燭代」は見当たらない。もしかして「燭台」？

> 
```

## 仕様

- 部屋ごとに「目につくもの」（名前 → 調べたときの文）。全 11 部屋で 15 個。燭台や地図に、出口の手がかりが書いてある
- 文の解釈: `shlex.split` で語に → 小文字に → 「北へ」「扉を」の助詞を落とす → `at` `the` `を` などの飾りの語を捨てる → 先頭が方角なら `go`、動詞なら `ALIASES` で正式名に、どちらでもなければ `unknown`
- 動詞 5 つ（go / look / map / help / quit）に言い換え 30 語
- 打ち間違い: 動詞は `ALIASES` の中から、物は今いる部屋の `things` の中から `get_close_matches(cutoff=0.5)` で 1 つ提案
- 行頭に来た句読点は前の行の末尾へ（禁則処理。g27 では「高すぎる／。」と割れていた）

## メモ

### `shlex.split` — シェルと同じ分け方

```python
    try:
        words = [w.lower() for w in shlex.split(text)]
    except ValueError:                                      # 引用符が閉じていない
        words = text.lower().split()
```

`str.split()` は空白で切るだけ。`shlex.split` は `"old map"` のように引用符で囲んだ部分を 1 語にし、`\ ` のエスケープも解釈します（シェルのコマンドラインと同じ規則）。
閉じていない引用符は `ValueError` になるので、そのときは普通の `split` に落とす。

### 逆引き辞書 — 書くのは片方だけ

```python
VERBS = {
    "go": {"walk", "move", "run", "行く", "進む", "移動"},
    "look": {"l", "examine", "x", "inspect", "見る", "調べる", "観察"},
    ...
}
ALIASES = {alias: verb for verb, names in VERBS.items() for alias in names | {verb}}
```

人が書きやすいのは「動詞ごとに言い換えを列挙する」形。プログラムが引きやすいのは「言い換え → 動詞」の形。
両方手で書くとずれるので、片方（`VERBS`）だけ書いて、もう片方（`ALIASES`）は辞書内包表記で作ります。`names | {verb}` で動詞自身も含める。`HELP_TEXT` も `VERBS` から作るので、言い換えを足せば help にも出ます。

### `Command` を `match` で振り分ける

```python
        match command:
            case Command("go", ()):
                return "どちらへ？（n s e w u d）"
            case Command("go", (word, *_)):
                ...
            case Command("look", ()):
                return self.look()
            case Command("look", (name, *_)):
                return self.examine(name)
```

g11 の `match` は値の比較でした。ここでは **`NamedTuple` の形で分ける**——「go で引数なし」「go で引数あり（先頭を `word` に）」「look で引数なし」……。
`(word, *_)` は「1 つ以上の引数があって、最初を `word` に入れる」。`if command.verb == "go" and len(command.args) == 0:` の連なりより、場合分けの全体が表として読めます。

### `difflib.get_close_matches` — 「もしかして」

```python
def suggest(word: str, choices) -> str | None:
    found = difflib.get_close_matches(word, list(choices), n=1, cutoff=0.5)
    return found[0] if found else None
```

`SequenceMatcher` の類似度（0〜1）で候補を並べ、`cutoff` 以上のものを `n` 個返します。英単語（`lok`/`look`）にも日本語（`燭代`/`燭台`、文字単位）にも同じように効く。
動詞なら `ALIASES` の全部、物なら**今いる部屋の**物だけを候補にすると、的外れな提案が減ります。

### 助詞を落とす

`北へ` `扉を` のように日本語では語の後ろに助詞が付くので、`w[:-1] if len(w) > 1 and w[-1] in "へにをの" else w`。完璧ではありません（「北へ行く」と空白なしで打たれると 1 語）が、`北へ` `扉を 調べる` は通ります。

### 禁則処理

`textwrap.fill` は句読点を知らないので、`。` が行頭に来ることがあります。折り返した後で「行頭の `。` `、` `」` `）`」を前の行の末尾へ移す `wrap_japanese` を挟みました。`__str__` は 1 行差し替えるだけ。
