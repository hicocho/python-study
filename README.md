# python-study

Python を一から学びながら、小さなプログラムを作っていく記録です。
1 課題 = 1 フォルダ。番号順に少しずつ扱う文法を増やしています。

## ブラウザで遊ぶ

インストール不要。リンクを開くだけで遊べます。

**▶ https://hicocho.github.io/python-study/**（課題一覧）

Python のコードがブラウザの中でそのまま動いています（[PyScript](https://pyscript.net/)）。
サーバーは使っていません。

## 課題一覧

| # | 課題 | 内容 | 扱った文法 |
|---|------|------|-----------|
| g01 | [数当てゲーム](g01-number-guess/) | 1〜100 の数字を 7 回以内に当てる CLI ゲーム | `while` / `if`-`elif`-`else` / `try`-`except` / f-string / `while`-`else` |
| g02 | [じゃんけん](g02-janken/) | `g`/`c`/`p` で何度でも勝負。やめると戦績が出る CLI ゲーム | `list` / `dict` / `def`-`return` / `break`-`continue` / `.lower()` |
| g03 | [タイピングゲーム](g03-typing/) | 表示された文章を5問打つ。正解数と「1秒あたり何文字」が出る CLI ゲーム | `for` / `random.shuffle` / `time` / 辞書のリスト / 書式指定 `:.1f` |
| g04 | [テトリス](g04-tetris/) | 矢印キーで操作する CLI テトリス。0.8秒ごとに落ちてきて、そろった列が消える | 2次元リスト / リスト内包表記 / `zip` と転置 / タプル / `termios`・`select` の生入力 |
| g05 | [オセロ](g05-othello/) | 8×8 の盤で挟んでひっくり返す CLI オセロ。置ける場所が `＊` で出る | 8方向の探索 / タプルをキーにした辞書 / `and` の短絡評価 / `chr`・`ord` / 連続パスのカウンタ |
| g06 | [マインスイーパ](g06-minesweeper/) | 9×9 に隠れた 10 個の地雷を避ける CLI マインスイーパ。0 のマスは連鎖して開く | 集合 `set` / 再帰関数 / `random.sample` / ジェネレータ式と `sum` / キーワード引数 |
| g07 | [シューティング](g07-shooting/) | 自機を左右に動かして弾を撃ち、並んだ 18 個の的を落とす CLI ゲーム。撃てるのは同時に 3 発まで | `class` / `__init__`・`self` / メソッド / オブジェクトのリスト / 内包表記でのフィルタ / 条件式 |
| g08 | [敵の編隊](g08-formation/) | 左右に動きながら 1 段ずつ降りてくる敵 21 体を落とす CLI シューティング。上の行は 2 発当てないと落ちない | 継承 / `super()` / メソッドの上書き / デフォルト引数 / `min`・`max` とジェネレータ式 / 状態をまとめる `class Game` |
| g09 | [スペースインベーダー](g09-invaders/) | 撃ち返してくる敵 21 体を、バリアに隠れながら落とす CLI シューティング。自機は 3 機、ハイスコアはファイルに残る | クラス変数 / 関数の一般化 / `random.random`・`random.choice` / `any()` / ファイル入出力 `with open` / `json` / 複数の例外をまとめて受ける `except` |
| g10 | [五目ならべ](g10-gomoku/) | 15×15 の碁盤で先に 5 個そろえたら勝ち。白は石の「形」を読む CPU。待ったで何手でも戻せる | ジェネレータ `yield` / `lambda` と `key=` / `collections.defaultdict` / 辞書内包表記 / `itertools.product` / リストをスタックに使う `pop` |
| g11 | [ブラックジャック](g11-blackjack/) | ディーラーと 21 を競う CLI ゲーム。チップを賭けて、ダブルダウンあり、ブラックジャックは 1.5 倍 | `dataclass` / `Enum` / `@property` / `match` 文（`|`・ガード・`_`） / 型ヒント / `collections.Counter` |
| g12 | [迷路](g12-maze/) | 穴掘り法で作った迷路を矢印キーで歩く CLI ゲーム。`?` で最短路のヒント、`--size` `--seed` で迷路を選べる | 再帰のバックトラック / `sys.setrecursionlimit` / `collections.deque` と BFS / `@contextmanager` / `os.read` / `argparse` |
| g13 | [迷路レース](g13-maze-race/) | 深さ優先で「実際に歩く」ロボットと競走する CLI ゲーム。`--show` で DFS・BFS・A* のアニメ、`--compare` で比較表 | 再帰 → 明示的なスタック / 探索をジェネレータに / `heapq` と A* / `itertools.count` / `time.perf_counter` / ジェネレータを持って `next()` で進める |
| g14 | [ブロック崩し](g14-breakout/) | パドルで打ち返して 40 個のブロックを壊す CLI ゲーム。端に当てるほど横に飛び、壊すほど速くなる | 演算子オーバーロード `__add__` `__mul__` `__rmul__` `__neg__` `__abs__` `__iter__` / `float` の物理と `round` / `math.floor` / `time.monotonic` と dt |
| g15 | [ピンボール](g15-pinball/) | 重力で落ちるボールをフリッパーで打ち返し、バンパーで得点する CLI ピンボール。斜めの壁で反射する | `math.sin` `cos` `radians` / `__matmul__` で内積 / `__truediv__` / 法線での反射 `v − 2(v·n)n` / サブステップ / `@property` で線分を作る |
| g16 | [宇宙船](g16-spaceship/) | 慣性で滑る宇宙船で、星の引力に引かれながら 5 つのリングをくぐる CLI タイムアタック | `complex` を 2D ベクトルに / `cmath.rect` `cmath.phase` / 複素数のかけ算で回転 / 小数の `%` でループ / `0.5 ** (dt / 半減期)` / `for`-`else` |
| g17 | [小惑星](g17-asteroids/) | 宇宙船で小惑星を弾で砕く CLI シューティング。撃つと 2 つに割れ、全部砕くと次のウェーブ | `abc.ABC` と `@abstractmethod` / `super().update(dt)` / 円と円の当たり判定 / `random.gauss` `random.uniform` / `self` から破片を作る `split` |
| g18 | [ランキング](g18-ranking/) | g17 の小惑星に名前つきの得点表を付ける。sqlite3 に記録し、上位 10 件と自分の順位を出す | `sqlite3`（`CREATE TABLE` `INSERT` `SELECT … ORDER BY … LIMIT`、`?` で値を渡す） / `contextlib.closing` / `pathlib.Path` / `datetime.isoformat` / `unicodedata.east_asian_width` / `argparse` の `store_true` |
| g19 | [ダンジョン](g19-dungeon/) | 部屋と廊下をランダムに作り、霧の中を歩いて階段を探す CLI ローグライク。地下 5 階でクリア | `__contains__`（`in` を自分の型に） / `itertools.combinations` / `dataclass` の `@property` / BFS で到達を確かめる / 集合の和 `|=` |
| g20 | [モンスター](g20-monsters/) | ダンジョンに敵。見えている敵が追ってきて噛みつく。体当たりで攻撃、へびは毒、オークは硬い | `enum.Flag`（`\|` と `in`） / `random.choices(weights=)` / ブレゼンハムの線で視線 / BFS の次の 1 歩に「通れないマス」 / `@staticmethod` |
| g21 | [アイテムとセーブ](g21-items/) | ダンジョンに落ちている薬草・剣・鎧を拾って使う。`s` でセーブして次回は続きから。記録は `dungeon.log` に | `typing.Protocol` と `@runtime_checkable` / `pickle` で `Game` をまるごと保存 / `random.getstate` `setstate` / `logging`（`getLogger` `basicConfig` `debug`） / `@classmethod` / `argparse` の `type=Path` |
| g22 | [チェス](g22-chess/) | 盤と駒の動き。2 人で交互か、ランダムに指す CPU 相手。相手のキングを取ったら勝ち（連作 5 段階の 1 つ目） | `typing.NamedTuple`（`@property`・メソッド付き） / `__getitem__` `__setitem__` `__iter__` / FEN の読み書き / `yield` で「ぶつかるまで」 / perft で既知の数と照合 |
| g23 | [チェスのルール](g23-chess-rules/) | チェック・キャスリング・アンパッサン・成り。合法手だけ指せて、チェックメイトかステイルメイトで終わる。perft 5 局面が既知の値と一致 | `@dataclass` の `__eq__` と自作 `__hash__`（`frozenset`） / `dataclasses.replace` / `functools.cached_property` / 「指してみて確かめる」合法手 / FEN 4 項目 |
| g24 | [チェスの終局](g24-chess-endings/) | 千日手・50 手ルール・駒不足の引き分け。これでルールは全部。perft を `lru_cache` で、検証は `unittest` 11 本 | `unittest`（`TestCase` `setUp` `subTest` `assertEqual`） / `functools.lru_cache`（`cache_info` `cache_clear`） / `collections.Counter` で局面を数える / `dataclasses.field(compare=False)` / `--perft` の表 |
| g25 | [チェスの CPU](g25-chess-cpu/) | 先読みする CPU。評価関数、ミニマックス（negamax）、αβ 枝刈り、反復深化と時間制限。18,000 局面/秒 | negamax と αβ / `math.inf` / 利きの逆引き（`:=` 代入式） / 例外で探索から抜ける（`class TimeUp(Exception)`） / `time.monotonic` の締め切り / 局面/秒を測って直す |
| g26 | [チェスの棋譜](g26-chess-pgn/) | SAN で指して棋譜になり、PGN に保存・読み戻し・再生。他所の PGN も読める。チェス 5 段階の完成形 | `re.compile` と名前付きグループ `(?P<name>…)` / `re.VERBOSE` / `re.sub` `findall` / SAN の曖昧さ / `textwrap.fill` `shorten` / `@classmethod from_pgn`（読む＝指し直す） / `date.today().strftime` |
| g27 | [冒険](g27-adventure/) | 夜の洋館を歩いて出口を探すテキストアドベンチャー。部屋・方角・地図（連作 5 段階の 1 つ目） | `enum.StrEnum`（値が文字列、`parse` で別名） / `textwrap.dedent` `fill` / `__str__` と `__repr__` の使い分け / `dataclass` の `field(default_factory=)` / `while`-`else` の復習 |
| g28 | [コマンド解析](g28-parser/) | 「look at the 燭台」のような文を分解して受ける。言い換えは同じ動詞に、打ち間違いは「もしかして」 | `shlex.split` / `difflib.get_close_matches` / 逆引き辞書を内包表記で / `NamedTuple` を `match` で形分け（`(word, *_)`） / 禁則処理 |

## 動かし方

Python 3 があれば、追加インストールなしで動きます（標準ライブラリのみ）。

```bash
git clone https://github.com/hicocho/python-study.git
cd python-study/g01-number-guess
python3 main.py
```

## 環境

- Python 3.13
- macOS
