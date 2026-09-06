# g18 ランキング

g17 の小惑星に、名前つきの得点表を付けました。遊び終わると名前を聞いて `sqlite3` のファイルに記録し、
上位 10 件と自分の順位を出します。`--top` で表だけ、`--reset` で全部消せます。

g16 → g17 → g18 の 3 段階の連作の最後で、ゲーム部分（`class Game` まで）は g17 と **1 文字も変えていません**。
足したのは「記録する・並べる・見せる」だけです。

今回の主題は 3 つです。

- **`sqlite3`** — 表を作る `CREATE TABLE`、足す `INSERT`、並べて取る `SELECT … ORDER BY … LIMIT`。値は `?` で渡す
- **`pathlib` と `datetime`** — 記録ファイルは `Path(__file__).with_name("ranking.db")` で `main.py` の隣に。日時は `datetime.now().isoformat()`
- **`unicodedata.east_asian_width`** — 全角は 2 桁ぶん。名前に日本語が混ざっても列が揃う `pad()`

## ブラウザ版

インストールせずに遊べます → **https://hicocho.github.io/python-study/g18/**

ソースは [`docs/g18/game.py`](../docs/g18/game.py)。g17 の 4 クラス・4 関数・`class Game` と `TOP_N` を **1 文字も変えずに**持ってきています。

持ってこなかったのは `class Ranking` と `display_width()` / `pad()` / `ranking_text()`、それに端末まわりです。
ブラウザには `sqlite3` のファイルが無いので、**同じ名前のメソッド（`add` / `top` / `count` / `reset`）を `localStorage` の JSON で作り直しました**。
違うのは保存先だけで、呼ぶ側は同じ形です。表は文字ではなく `<table>`。

## 遊び方（ターミナル）

```bash
python3 main.py              # 上位 3 件を見せてから、小惑星を遊ぶ。終わったら名前を聞かれる
python3 main.py --top 5      # 遊ばずに上位 5 件
python3 main.py --name ひこ  # 名前入力を省く
python3 main.py --reset      # 記録を全部消す（y で確定）
```

```
   名前          得点    ウェーブ  日時
  1 ひこ            6280         4  2026-09-07 01:26
  2 名無し          1200         2  2026-09-07 01:26
  3 Alice            810         2  2026-09-07 01:26
```

- 0 点のときは記録しない。名前は 12 文字まで、空なら「名無し」
- 記録は `ranking.db`（`.gitignore` 済み）。`--db` で場所を変えられる

## 仕様

- 表 `scores`：`id`（自動）/ `name` / `score` / `wave` / `played_at`（ISO 形式の日時）
- 順位は「自分より高い得点の件数 + 1」。**同点は先に出した人が上**（`ORDER BY score DESC, id ASC` と、順位の計算の `OR (score = ? AND id < ?)` で揃えている）
- 上位 10 件を表にし、自分の行に `★`
- 名前の列は 12 桁ぶん。全角 1 文字を 2 桁と数えて揃える

## メモ

### `sqlite3` — ファイル 1 つがデータベース

```python
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute("INSERT INTO scores (name, score, wave, played_at) VALUES (?, ?, ?, ?)", (...))
            conn.commit()
```

g09 では `json` で 1 つの数を保存しました。件数が増えて「並べ替えて上位だけ」となると、自分でリストを読み書きするより、
**並べ替えも絞り込みも SQL に任せる**ほうが短く正確です。`sqlite3` は Python に最初から入っていて、サーバーもいりません。

`?` に値を渡すのが大事で、`f"... VALUES ('{name}')"` と文字列で組み立てると、名前に `'` が入っただけで壊れます
（そして他人が悪い文字列を入れると、表を消されることもある）。**値は文字列に混ぜず、`?` で別に渡す。**

### `closing()` — `with` で閉じる

`sqlite3.connect()` の返り値は `with` に入れてもコミットの管理だけで、閉じてはくれません。`contextlib.closing` で包むと、
ブロックを抜けたときに `close()` が呼ばれます。g12 の `@contextmanager` で自作した「必ず後始末」の既製品です。

### 順位は「自分より上の件数 + 1」

```python
            (above,) = conn.execute(
                "SELECT COUNT(*) FROM scores WHERE score > ? OR (score = ? AND id < ?)",
                (score, score, cursor.lastrowid),
            ).fetchone()
            return above + 1
```

最初は `score > ?` だけで数えていました。すると同点が 2 人いると両方 1 位になるのに、表では `id` 順で 2 位に並ぶ——
**表示と順位の計算で「同点の扱い」がずれていました**。同点なら先に出した人（`id` が小さい）が上、と両方に書いて揃えています。
`(above,)` は「1 列だけの行」をほどく書き方です。

### `Path(__file__).with_name("ranking.db")`

g09 では `os.path.join(os.path.dirname(__file__), ...)` と書きました。`pathlib` なら `with_name` の 1 呼び出し。
`Path` は `/` でつなげたり `.exists()` で確かめたり、文字列より扱いやすいので、今後はこちらを使います。

### `datetime.now().isoformat(timespec="seconds")`

`2026-09-07T01:27:16` の形。文字列なのに**並べ替えると時刻順になる**のが ISO 形式の利点で、DB に入れるならこれ一択です。
表示では `[:16]` で秒を落とし、`T` を空白に替えています。

### 全角は 2 桁

```python
def display_width(text):
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)
```

g13 の比較表で「全角は 2 桁ぶんなので手で揃える」と書きました。今回はそれを関数にしました。
`unicodedata.east_asian_width` は文字ごとに `W`（全角）`F`（全角英数）`Na`（半角）などを返すので、`W` と `F` を 2 と数えれば幅が出ます。
`pad()` は `str.ljust` の全角対応版で、「ひこ」と「Alice」の次の列がぴったり揃います。

### ゲームは g17 のまま、外側だけ足す

```python
    game = play()
    name = args.name or ask_name()
    rank = ranking.add(name, game.score, game.wave)
```

`play()` は g17 の `main` をそのまま関数にして `Game` を返すようにしたもの。`Game` に「記録する」を足していないので、
ブラウザ版は保存先だけ差し替えれば済みました。g09 の「`Game` にファイルを触らせない」の続きです。
検証では、`class Game` を g17 と g18 の両方から切り出して**文字列として一致**することを確かめています。

### ブラウザ版：同じメソッド名で `localStorage`

```python
class Ranking:
    def add(self, name, score, wave): ...
    def top(self, n=TOP_N): ...
    def count(self): ...
    def reset(self): ...
```

CLI 版の `Ranking` と同じ 4 つを、JSON のリストで作り直しました。`top()` の `sorted(..., key=lambda row: -row["score"])` は
**安定ソート**なので、同点は元の順（先に足したほうが先）のまま——SQL の `ORDER BY score DESC, id ASC` と同じ結果になります。
