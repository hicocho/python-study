# g26 チェスの棋譜（SAN と PGN）

チェス 5 段階の完成形。指した手が **SAN**（Nf3、exd5、O-O、Qxf7#…）で棋譜になり、**PGN** に保存して読み戻せます。
入力も SAN で（`e2e4` でも可）、`--save` で対局を残し、`--load` で続きから、`--replay` で 1 手ずつ再生。
他所の PGN（コメントや手数入り）も読めます。

今回の主題は 3 つです。

- **`re` の名前付きグループ** — `(?P<piece>[KQRBN])?(?P<to>[a-h][1-8])…` で SAN を分解し、`found["to"]` で取り出す。`re.VERBOSE` でコメント付きの正規表現
- **SAN を書く／読む** — 同じ駒が 2 つ行けるときの曖昧さの消し方（筋・段・両方）、`+` と `#`、キャスリング、成り
- **`textwrap.fill`** と PGN — ヘッダ・手・結果を 80 桁で折り返す。`@classmethod from_pgn` で文字列から `Game` を作る

## ブラウザ版

インストールせずに遊べます → **https://hicocho.github.io/python-study/g26/**

ソースは [`docs/g26/game.py`](../docs/g26/game.py)。定数と正規表現、`Square` / `Move` / `Board`、関数 22 個、`class Game` を **1 文字も変えずに**持ってきています。
持ってこなかったのは `Game.render()` / `save()` / `load()` と `perft_table()` / `replay()` / `main()` だけ。
盤の下に棋譜と PGN が出て、貼り付けた PGN を「読み込む」と `Game.from_pgn()` がそのまま読みます。

## 遊び方（ターミナル）

```bash
python3 main.py                              # 黒が CPU（1 秒）。SAN で指す
python3 main.py --save game.pgn              # 終わったら（q でも）棋譜を保存
python3 main.py --load game.pgn              # 続きから
python3 main.py --replay game.pgn            # 1 手ずつ再生（Enter で進む）
python3 main.py --two --fen "4k3/8/8/8/8/8/8/R3K2R b KQ - 0 40"   # 途中の局面から（PGN に FEN ヘッダが付く）
```

- `e4` `Nf3` `exd5` `O-O` `e8=Q` のように指す。`e2e4` でも可。曖昧なら `Nbd7` `R1a2` のように
- `pgn` で今の棋譜を表示 ／ `undo` ／ `q`

```
> O-O
CPU: d5   （3 手読み  1,899 局面  評価 +2.20）

8  r . b q k b . r
7  p p p . p p p p
6  . . n . . . . .
5  . . . p . . . .
4  . . B . n . . .
3  . . . . . N . .
2  P P P P . P P P
1  R N B Q . R K .
   a b c d e f g h

5 手目 白の番   直前 d7d5
棋譜  1. e4 Nf6 2. Nf3 Nxe4 3. Bc4 Nc6 4. O-O d5
> pgn
[Event "python-study g26"]
[Site "?"]
[Date "2026.09.07"]
[Round "-"]
[White "Hico"]
[Black "CPU"]
[Result "*"]

1. e4 Nf6 2. Nf3 Nxe4 3. Bc4 Nc6 4. O-O d5 *

```

## 仕様

- **SAN を書く**（`san`）: 駒の文字（ポーンは無し）＋ 曖昧さの記号 ＋ `x` ＋ 行き先 ＋ `=Q` ＋ `+`/`#`。キャスリングは `O-O` / `O-O-O`。ポーンが取るときは元の筋（`exd5`）
- **曖昧さ**: 同じ種類の駒がほかにも同じマスへ行けるとき、筋で区別できれば筋（`Rad1`）、だめなら段（`R1a2`）、それでもだめなら両方（`Qb1e4`）
- **SAN を読む**（`parse_move`）: 正規表現で分解し、合法手のうち条件に合うものが**ちょうど 1 つ**なら採用。`0-0` や末尾の `+#` も受ける。成りは `=Q` が必須
- **PGN**: 7 つのヘッダ（Event / Site / Date / Round / White / Black / Result、途中の局面なら FEN）、空行、手（80 桁で折り返し）、結果の記号（`1-0` `0-1` `1/2-1/2` `*`）
- **PGN を読む**: `{ }` のコメント、`;` の行コメント、手数（`1.` `1...`）、`$1` の注釈記号を取り除いてから 1 手ずつ。読めない手は `ValueError`（何手目のどの手か、そのときの FEN 付き）

### 検証

| 対象 | 結果 |
|---|---|
| SAN を書く | 駒・取る・キャスリング・`+`・`#`・成り・アンパッサン・曖昧さ 3 種の 15 ケース |
| SAN を読む | 駒・取る・`O-O` `0-0-0`・成り（`=Q` 無しは None）・曖昧なら None・`+#` は無視 |
| 往復 | ランダム対局 60 局 5,976 手すべてで `parse_move(san(...)) == move`（曖昧さの記号付きが 110 手） |
| PGN の往復 | 書いて読んで同じ局面・同じ棋譜・同じ局面の回数。全行 80 桁以内。172 手の長い棋譜も |
| 途中の局面 | `40... Kd8 41. O-O` の番号、FEN ヘッダ付きで往復 |
| 他所の PGN | コメント・行コメント・`??` 混じりのスカラーズメイトを読んで `1-0` |
| 読めない手 | `2 手目の 'Kxe2' が読めません（局面 …）` の `ValueError` |
| ブラウザ | CLI の PGN をブラウザ版が読める。貼り付け → 読み込む → 続きを指す → `Qxf7#` で `[Result "1-0"]` |

## メモ

### 名前付きグループ — 正規表現の結果に名前で触る

```python
SAN_PATTERN = re.compile(r"""
    ^(?P<piece>[KQRBN])?        # 駒。無ければポーン
    (?P<from_file>[a-h])?       # 同じ駒が 2 つ行けるときの、元の筋
    (?P<from_rank>[1-8])?       # 元の段
    (?P<capture>x)?             # 取る手
    (?P<to>[a-h][1-8])          # 行き先
    (?:=(?P<promotion>[QRBN]))? # 成る駒
    (?P<check>[+#])?$           # チェック / メイト
""", re.VERBOSE)

    found = SAN_PATTERN.match(text)
    kind = found["piece"] or "P"
```

`(?P<name>…)` で名前を付けると、`found["to"]` のように**辞書の感覚で**取り出せます。`found.group(5)` の番号より読めるし、パターンを直しても番号がずれません。
`re.VERBOSE` は空白と `#` のコメントを無視するので、長い正規表現を**行ごとに説明を付けて**書けます。`(?:…)` は名前も番号も付けないグループ（`=Q` の `=` をまとめるため）。
`re.compile` で先に作っておくと、1 手ごとに解釈し直さずに済みます。

### SAN の曖昧さは「合法手を見てから」決める

```python
    others = [m.src for m in legal_moves(board) if m.dst == move.dst and m.src != move.src and board[m.src] == piece]
    if not others:            where = ""
    elif all(o.file != move.src.file for o in others):   where = FILES[move.src.file]
    elif all(o.rank != move.src.rank for o in others):   where = RANKS[move.src.rank]
    else:                     where = move.src.name
```

「同じ種類の駒がほかにも同じマスへ行けるか」は、盤を見ただけでは決まりません（ピンされていれば行けない）。`legal_moves` を使うので、ルールと同じ基準で曖昧さが決まります。
読む側は逆に、条件に合う合法手が**ちょうど 1 つ**のときだけ採用（`len(candidates) == 1`）。`Rd1` が 2 つに当てはまれば `None`。

### `textwrap.fill` — 80 桁で折り返す

PGN の規格は 1 行 80 桁まで。`textwrap.fill(text, width=80)` は単語（＝手）の途中で切らずに改行を入れます。
画面の棋譜の行は `textwrap.shorten`（`…` で省略）と末尾表示の組み合わせ。

### `from_pgn` は `@classmethod`

g21 の `Game.load` と同じ「作る側の関数」。ヘッダは `PGN_TAG.findall` で `(key, value)` の一覧にして `dict` に。本文は `PGN_NOISE.sub(" ", body)` で
コメント・手数・注釈をまとめて空白に置き換えてから `split()`。あとは 1 手ずつ `parse_move` して `play`——**読むことは指し直すこと**なので、
千日手の回数も 50 手カウンタも自然にそろいます。`**kwargs` で CPU の設定を通すので、読み戻した対局を CPU 相手にそのまま続けられます。

### 途中の局面から始めたときの番号

`40... Kd8 41. O-O`。黒番から始まる棋譜は最初の手を `n...` で書きます。`movetext` は「最初の局面の手数と手番」から番号を計算し、PGN には `[FEN "…"]` ヘッダを付けて、読むときはそこから始めます。
ステップ 4 までは「初期局面から」しか考えていなかったので、これが最後のステップになりました。

### 5 段階のチェスで増えたもの

| # | 主題 | `Game` に増えたもの |
|---|---|---|
| g22 | `NamedTuple` / `__getitem__` / FEN | 盤・履歴・結果 |
| g23 | `__hash__` / `replace` / `cached_property` | 合法手・チェック・キャスリング・アンパッサン |
| g24 | `unittest` / `lru_cache` / `Counter` | 千日手・50 手・駒不足 |
| g25 | negamax / αβ / 例外で抜ける | 先読みする CPU |
| g26 | `re` / SAN / PGN / `textwrap` | 棋譜の読み書き |

`Board` → `legal_moves` → `Game` の層は g22 から変わらず、ブラウザ版は毎回 `Game` をそのまま持っていきました。
