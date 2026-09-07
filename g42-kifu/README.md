# g42 将棋（棋譜）

将棋 6 段階の完成形。**日本語の表記**（７六歩、２二角成、５五角打、同銀）で指せて、対局が終わると **KIF 形式の棋譜**がファイルになります。他所の KIF を読んで並べ直し、途中の対局は **JSON** に保存して再開、棋譜は **zip の棋譜集**にまとめられます。CPU（g41）と詰将棋（g39〜g40）はそのまま。

今回の主題は 4 つです。

- **`re.VERBOSE` と名前付きグループ** — 「７六歩」「同　銀(31)」「５五角打」「２二角成」を 1 つの正規表現で。`(?P<dst>…)` `(?P<promote>…)` を名前で取り出す（g26 の PGN と同じ道具を日本語に）
- **`unicodedata.normalize("NFKC", …)`** — 全角の数字・記号を半角に。「７六」も「7六」も「☗７六」も同じに読める。漢数字は表で
- **`json`** — 手順（USI）と設定だけを保存し、読み戻すときは指し直す。ブラウザ版は同じ dict を localStorage に
- **`zipfile`** — 棋譜集。`ZipFile(path, "a")` で追記、`infolist()` で一覧

## ブラウザ版

インストールせずに遊べます → **https://hicocho.github.io/python-study/g42/**

ソースは [`docs/g42/game.py`](../docs/g42/game.py)。`parse_japanese` / `to_kif` / `from_kif` / `class Game` を **1 文字も変えずに**持ってきています。棋譜が下に育ち、貼り付けた KIF を並べ直せ、途中の対局はブラウザに残って開き直すと続きから。

## 遊び方（ターミナル）

```bash
python3 main.py --cpu w                    # 後手が CPU。７六歩 のように指す（7g7f でも）
python3 main.py --cpu w --archive kifu.zip # 終わったら棋譜を zip に足す
python3 main.py --load kifu/xxxx.kif       # KIF を並べて、続きから指す
python3 main.py --resume                   # save.json から再開（対局中に save）
python3 main.py --list kifu.zip            # 棋譜集の中身
```

- 対局中: `７六歩` / `２二角成` / `２二角不成` / `５五角打` / `同銀`、`undo`、`save`、`kif`（今の棋譜を表示）、`q`
- 終わると `kifu/YYYYMMDD-HHMMSS.kif` に書く

## 仕様

- 日本語の手: `MOVE_RE` で「同」か「マス」、駒、成/不成、打、元のマス `(77)` を読む。合法手の中から行き先・駒の種類・成りで絞り、1 つに決まれば指す。成る/成らないが両方あって「成」が付かなければ不成（KIF の約束）
- KIF: ヘッダ 5 行 + `   1 ７六歩(77)` + `まで N 手で先手の勝ち`（千日手・不詰も）。成香・成桂・成銀は KIF の表記に合わせる。読むときは消費時間 `( 0:03/00:00:03)` と `*` のコメント行を無視し、投了・中断で止まる
- JSON: `{"moves": ["7g7f", …], "cpu": "w", "depth": 2, "result": null, "saved": "…"}`
- zip: `ZIP_DEFLATED` で圧縮

## メモ

### 正規表現を `VERBOSE` で読めるように

```python
MOVE_RE = re.compile(r"""
    ^\s*(?:[☗☖▲△])?\s*
    (?P<dst>同|[1-9１-９][1-9１-９一二三四五六七八九])\s*
    (?P<piece>成?[歩香桂銀金角飛玉王と杏圭全馬龍竜])
    (?P<promote>成|不成)?
    (?P<drop>打)?
    (?:\((?P<src>[1-9]{2})\))?
""", re.VERBOSE)
```

`re.VERBOSE` なら空白と改行で区切って、部分ごとに書ける。名前付きグループは `m["dst"]` のように取り出す。「成銀」（成り駒が動く）と「銀成」（今成る）を `piece` と `promote` で区別する。

### `unicodedata.normalize`

全角の「７」は NFKC で「7」になる。「☗」や「（」も半角に寄る。漢数字の段（一〜九）は変わらないので `RANK_KANJI_INDEX` の表で引く。ユーザー入力も KIF も同じ関数で読めるのはこのおかげ。

### 「同」は直前の手の行き先

`parse_japanese(board, text, last)` に直前の手を渡す。`from_kif` は `game.last_move` を渡しながら 1 手ずつ指す。KIF の書き出しでも、直前と同じマスなら「同　」にする（全角スペースが KIF の流儀）。

### 保存は「手順だけ」

盤の状態を保存すると、SFEN・持ち駒・千日手の回数・履歴を全部書くことになる。手順（USI）だけ保存して読み戻すときに `play` で指し直せば、`Game` の中身がどう変わっても壊れない。g31 の `pickle` は丸ごと、こちらは「再生」。

### ブラウザ版の localStorage

`autosave()` は CLI 版の `save_json()` と同じ dict を `json.dumps` して localStorage に。開き直したときに `restore()` が指し直す。「はじめから」で消す。
