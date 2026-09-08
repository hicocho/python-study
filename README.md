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
| g29 | [アイテムと仕掛け](g29-puzzles/) | 鍵を見つけ、扉を開け、窓をこじ開けて脱出。拾う・置く・使う・開ける・押す | 自作デコレータで動詞を登録（引数付き） / クロージャと `nonlocal` / `functools.partial` / `__call__` / `getattr` でメソッドを名前から / `Callable` の型ヒント |
| g30 | [シナリオ](g30-scenario/) | 世界を TOML で。洋館と洞窟の 2 つを同じプログラムで。読めないファイルはどこが悪いかを文で | `tomllib` / 自作例外と `raise … from`（`__cause__`） / `__getattr__` と `from None` / `pathlib.glob` `stem` / `SystemExit` で 1 行のエラー / type ごとの作り方を辞書で |
| g31 | [セーブと自動テスト](g31-save/) | コマンドの記録をセーブして続きから。指紋で改ざん検知。攻略ファイルと doctest で自動テスト（連作 5 段階の完成形） | `hashlib.sha256` / `zipfile`（`writestr` `read` `BadZipFile`） / `doctest.testmod` / `io.StringIO` と `contextlib.redirect_stdout` / 「読む＝指し直す」セーブ / `SystemExit` の終了コード |
| g32 | [ギャラガ風（自機とスプライト）](g32-galaga-sprites/) | 多色ドット絵の自機と敵、流れる星。撃って落とすと爆発（連作 5 段階の 1 つ目） | ドット絵をパレット＋文字列で / `str.maketrans` `translate` / トゥルーカラー ANSI と `▀` / `struct` + `zlib` で PNG を手書き / `functools.cache` / `itertools.cycle` / `shutil.get_terminal_size` |
| g33 | [ギャラガ風（入場曲線と編隊）](g33-galaga-formation/) | 敵が 5 つの波でベジェ曲線を描いて飛来し、席に着くと編隊が呼吸する | ベジェ曲線（`math.comb` のバーンスタイン基底） / ジェネレータで 1 コマごとの位置（速さ一定） / `itertools.chain` / `math.hypot` / `math.sin` の呼吸 / `StopIteration` を受けて席へ |
| g34 | [ギャラガ風（急降下と敵の弾）](g34-galaga-dive/) | 席の敵が状態機械で自機めがけて急降下し、弾を撃ってくる。残機 3 | `IntEnum` の状態機械 / `match` 文（`case A \| B`） / `random.choices` の重み / `@property` で残機と復活をそろえる / 自動プレイで難しさを測る |
| g35 | [ギャラガ風（ボスと牽引ビーム）](g35-galaga-tractor/) | ボスが降りてきてビームで自機を捕まえる。救出するとデュアルファイター | `send()` でジェネレータに値を渡す（コルーチン） / `heapq` のタイムライン / `__post_init__` / 描く先を差し替える（`CanvasScreen`） / `(enemy,) =` の 1 要素アンパック |
| g36 | [ギャラガ風（ステージと演出）](g36-galaga-stages/) | 全滅させると次のステージ、3 の倍数は虹色のチャレンジングステージ。スコア表は CSV | `colorsys`（色相を回す） / `csv.DictWriter` `DictReader` と `dataclasses.asdict` `fields` / `io.StringIO` で文字列と行き来 / `@property` で難度 / `@cache` と `Sprite` の同一性 |
| g37 | [将棋](g37-shogi/) | 盤と駒の動き。成り・持ち駒・打つ。2 人で交互か、ランダム CPU。相手の玉を取ったら勝ち（連作 6 段階の 1 つ目） | `IntFlag`（種類・成り・後手をビットで） / `__slots__` / `itertools.product` / `str.maketrans` `translate` で全角と漢数字 / SFEN と USI の読み書き / perft で既知の数と照合 |
| g38 | [将棋（反則と終局）](g38-shogi-rules/) | 王手放置・二歩・打ち歩詰め・行き所のない駒を外し、詰み・千日手・連続王手で終わる。perft 4 手 = 719731 | `contextlib.contextmanager` で「指して戻す」 / Zobrist ハッシュ（`random.getrandbits` と XOR） / `collections.deque(maxlen=)` / `assert` / 辞書の順に依らない手の生成 |
| g39 | [将棋（詰将棋）](g39-tsume/) | 王手を続けて玉を詰ませる。受け方は最も粘る手、次の一手のヒント。1〜5 手詰 8 題を全探索のソルバーで | 再帰ジェネレータ（`yield` と `next(gen, None)`） / `itertools.islice` で余詰 / `dataclass(slots=True)` / `time.perf_counter` / 自作例外 `SearchLimit` で上限 / `sys.setrecursionlimit` |
| g40 | [将棋（詰将棋 df-pn）](g40-dfpn/) | 証明数・反証数で「解けそうな所」から掘り、置換表で同じ局面を省く。7 手詰まで 11 題 | df-pn（証明数・反証数・しきい値） / 置換表 `dict[int, tuple]` / `math.inf` の扱い / `itertools.count` / `operator.itemgetter` / 5 手詰の延長で 7 手詰を作る |
| g41 | [将棋（CPU）](g41-shogi-cpu/) | 駒割りの評価と αβ 探索で先読みする CPU。取る手とキラームーブを先に読み、反復深化と時間制限。深さ 2 でランダムに 3 戦 3 勝 | `array` / ネガマックス αβ / MVV-LVA とキラームーブ / 反復深化と `TimeUp` 例外 / `cProfile` `pstats` / 局面数で並べ替えの効果を測る |
| g42 | [将棋（棋譜）](g42-kifu/) | 日本語の表記で指し、KIF を書いて読み戻し、JSON で再開、zip の棋譜集。将棋 6 段階の完成形 | `re.VERBOSE` と名前付きグループ（日本語） / `unicodedata.normalize("NFKC")` / KIF の読み書き / `json` で「手順だけ」保存 / `zipfile` の追記と `infolist` / `datetime` の書式 |
| g43 | [グラディウス風（自機と横スクロール）](g43-gradius-scroll/) | 上下の地形が流れる洞窟を飛ぶ。触れると撃墜、先へ行くほど狭い（連作 6 段階の 1 つ目） | `itertools.pairwise` で折れ線 / `bisect_right` で線分を引く / `typing.Protocol` と `@runtime_checkable` / 横スクロールと視差 / 自動操縦で難しさを決める |
| g44 | [グラディウス風（敵の出現）](g44-gradius-enemies/) | 出現表に沿ってファン・ガルン・ダッカー・砲台が出る。正面の敵は撃ち落とし、弾はよける | `enum.auto` / `dataclass(kw_only=True)` / `functools.partial` でクラスの工場 / `itertools.groupby`（並べてから） / 動きを関数に任せる / `math.atan2` で狙う |
| g45 | [グラディウス風（パワーアップ）](g45-gradius-powerup/) | カプセルでゲージが進み、選んで発動。スピード・ミサイル・ダブル・レーザー・シールド | `abc.ABC` `@abstractmethod` で武器の型 / `functools.singledispatch` で弾の型ごとの当たり方 / `Enum` の順送り / `register(型)` と前方参照の注意 / `id()` で dataclass を覚える |
| g46 | [グラディウス風（オプション）](g46-gradius-options/) | 自機の軌跡を遅れてたどる分身。最大 4 つ、同じ武器を撃つ。赤い敵は必ずカプセル | `array` のリングバッファ（剰余で回す） / `__len__` `__iter__` で入れ物らしく / `math.dist` / `functools.cache` と frozen dataclass / `Sprite.recolor` |
| g47 | [グラディウス風（ビッグコア）](g47-gradius-bigcore/) | ステージの終わりのボス。4 枚のバリアの奥のコアを撃つ。揺れる狙い、撃破の演出 | `enum.Flag` でバリアの組み合わせ / `random.gauss` で揺れ / `contextlib.suppress` / `Enum` で段階 / ボスも `Enemy` の子 |
| g48 | [グラディウス風（ステージと難度）](g48-gradius-stages/) | 砂漠・火山・要塞の 3 面を TOML の表で。ボスを倒すと次の面、周回で速く、ハイスコア | `tomllib` と `from_dict` / `functools.reduce` で難度 / `logging` は既定で黙る / `argparse` サブコマンド `set_defaults(func=)` |
| g49 | [イー・アル・カンフー風（舞台と格闘家）](g49-kungfu-stage/) | 2 人の格闘家。歩く・跳ぶ・しゃがむ、向きは相手の方へ、押し合い、体力バー | `match` 文（状態と入力の組で分岐） / `typing.Literal` / `dataclasses.replace` で反転した絵 / `property` の setter で 0〜100 |
| g50 | [イー・アル・カンフー風（技と当たり判定）](g50-kungfu-moves/) | パンチ・キック・しゃがみパンチ・跳び蹴り。攻撃ボックスが体に重なればダメージと硬直 | `itertools.accumulate` で累積時間 / `__next__` の自作イテレータ / `functools.wraps` のデコレータ / frozen dataclass の技の表 |
| g51 | [イー・アル・カンフー風（最初の敵ワンと AI）](g51-kungfu-ai/) | 間合いで行動に点を付けて選ぶ AI。遅れて気づいてよける。難度 3 段階を統計で調整 | `collections.ChainMap` で設定の層 / `dataclass(order=True)` と `compare=False` / `statistics` の mean・median・pstdev |
| g52 | [イー・アル・カンフー風（武器の敵）](g52-kungfu-weapons/) | タオの火の玉、チェンの鎖、ランの手裏剣、飛ぶムー。敵ごとの動きは台本 | `yield from` でジェネレータをつなぐ台本 / `typing.Generic` `TypeVar` の `Slot[T]` / `TypedDict` の敵の表 |
| g53 | [イー・アル・カンフー風（対戦の流れ）](g53-kungfu-tournament/) | 60 秒のラウンドを 2 本先取、5 人連戦、コンティニュー、結果の表 | `__format__` で書式を持つ / `functools.total_ordering` / `datetime.timedelta` / `__enter__` `__exit__` のクラス |
| g54 | [イー・アル・カンフー風（リプレイと記録）](g54-kungfu-replay/) | 毎コマの入力を記録して同じ試合を再生。巻き戻しの練習モード、記録の保存 | `__set_name__` の記述子 / `copy.deepcopy` と `__deepcopy__` / `itertools.zip_longest` / `shelve` |
| g55 | [パックマン風（迷路とパックマン）](g55-pacman-maze/) | 21×13 の迷路を走り、124 個のエサを全部食べたらクリア。曲がれない向きは覚えておく先行入力、左右のトンネル（連作 6 段階の 1 つ目） | `collections.abc.Mapping` の継承 / `typing.Self` / `zip(*rows, strict=True)` / `itertools.takewhile`・`batched` / 位置を「マス + 進み具合」で持つ |
| g56 | [パックマン風（4 体のおばけ）](g56-pacman-ghosts/) | 赤・桃・水・橙が 1 体ずつ違う狙い方で追ってくる。散らばりと追いかけを時間割で切り替え、そのたびに反転（連作 6 段階の 2 つ目） | `__init_subclass__` の自動登録 / `typing.ClassVar` / `typing.assert_never` / `itertools.accumulate` と `bisect_right` / 走るものを `Walker` にまとめる |
| g57 | [パックマン風（パワーエサとイジケ）](g57-pacman-power/) | パワーエサでおばけが青くなって逃げ、捕まえると 200・400・800・1600 点。目玉だけになって巣へ帰る（連作 6 段階の 3 つ目） | `type` 文（PEP 695 の型エイリアス） / `functools.singledispatchmethod` / `typing.Final` / `str.maketrans` と `translate` / `assert_never` の回収 |
| g58 | [パックマン風（ステージと果物）](g58-pacman-stages/) | 全部食べると次の面へ。面が進むとおばけが速くなりイジケが短くなる。途中に出る果物はボーナス（連作 6 段階の 4 つ目） | `fractions.Fraction` / `collections.abc.Sequence` の継承 / `itertools.repeat` と `chain` / `singledispatchmethod` に register を足す |
| g59 | [パックマン風（演出とアトラクトモード）](g59-pacman-scenes/) | 放っておくとデモが流れ、キーを押すと始まる。READY! の間、捕まって消える動き、面クリアの点滅（連作 6 段階の 5 つ目） | `enum` の `_generate_next_value_` / `functools.partialmethod` / `math.atan2` で絵を作る / 3×5 の英字フォント |
| g60 | [パックマン風（記録と分析）](g60-pacman-records/) | 遊んだ結果を 1 行 1 件で残し、得点の散らばり・到達した面・どのおばけに捕まったかを振り返る（連作 6 段階の完成形） | `collections.abc.MutableMapping` の継承 / `statistics.quantiles` / `dataclasses.astuple` と `fields` / `operator.attrgetter` |
| g61 | [推理ゲーム風（現場と聞き込み）](g61-mystery-scene/) | コマンド選択式の推理もの。街を回って調べ、人に聞き、手がかりを集める。手がかりが揃うと聞ける話が増える（事件はオリジナル） | `collections.abc.Set` の継承 / `typing.NewType` / `dataclasses.KW_ONLY` / `string.Template` / 長方形の重ね合わせで絵を作る |
| g62 | [推理ゲーム風（推理ノートと手がかりの地図）](g62-mystery-notes/) | 一度見た選択肢は消えるので残りが一目で分かる。集めた手がかりは層に並べた図に。事件が詰まないかも機械で確かめる | `graphlib.TopologicalSorter`（`static_order` と `prepare`/`get_ready`）/ `graphlib.CycleError` / `itertools.filterfalse` |
| g63 | [推理ゲーム風（証言の矛盾と告発）](g63-mystery-verdict/) | 食い違う 2 つの証言を突きつけて言い直させ、最後に犯人・手口・動機を指名して採点（推理もの 3 段階の完成形） | `copy.replace()`（Python 3.13） / `dataclasses.field(metadata=)` と `fields()` / 証言を「誰・いつ・どこ」に分けて矛盾を 1 行で |

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
