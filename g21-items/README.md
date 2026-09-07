# g21 アイテムとセーブ

g20 のダンジョンに、床に落ちているアイテムを足しました。拾って持ち歩き、番号キーで使います。
薬草で回復、解毒薬で毒消し、剣で攻撃力、鎧で最大体力が上がる。`s` でセーブして中断すると、次に起動したとき続きから始まります。
遊んだ記録は `dungeon.log` に全部残ります。

g19 → g20 → g21 の 3 段階の連作の最終段。ダンジョン・敵・戦闘は g20 と同じです。

今回の主題は 3 つです。

- **`typing.Protocol`** — アイテムの「形」だけを決めて、継承なしで 4 種類を作る。`@runtime_checkable` で `isinstance` も
- **`pickle`** — `Game` をまるごとファイルに書き、読み戻す。乱数の状態も一緒に
- **`logging`** — `print` ではなく記録係に渡す。画面は直近 3 行、ファイルには全部、`--debug` で敵の動きまで

## ブラウザ版

インストールせずに遊べます → **https://hicocho.github.io/python-study/g21/**

ソースは [`docs/g21/game.py`](../docs/g21/game.py)。定数 18 個と `Trait` / `Kind` / `Monster` / `Item` / 4 つのアイテム / `Rect`、
`make_rooms()` 〜 `next_step_toward()`、そして `class Game` を **1 文字も変えずに**持ってきています（`ast` で切り出して文字列比較で確認済み）。

持ってこなかったのは `dungeon_text()` と端末まわり、`Game.render()`、それに `Game.save()` / `Game.load()` だけ。
ブラウザ版のセーブは `pickle.dumps()` した bytes を base64 にして `localStorage` に入れます。**同じ `pickle`** で、ファイルの代わりにブラウザの保存領域を使うだけです。

## 遊び方（ターミナル）

```bash
python3 main.py            # save.pkl があれば続きから
python3 main.py --new      # セーブを無視して最初から
python3 main.py --debug    # dungeon.log に敵の動きまで残す
```

- 矢印キーで移動。敵のいるマスへ動くと攻撃。アイテムのマスに乗ると拾う
- `1`〜`6` 持ち物を使う（1 ターン使う）
- `s` セーブして中断 ／ `q` やめる

```
                                                
               ######      ########             
             ###····#      #······#             
             ·······########······########      
             ###·························#      
           ·······················######·#      
              ##····########······#    #.#      
               ##··##      #······#    #.#      
                #··#       ########    #.#      
              ###··#                   #.#      
           ········#      #######      #.#      
              ###·##      #·····#      #.#      
                #·#########·····#    #..@..#    
             #··················#    #.....#    
             #······#######·····#    #..>.!#    
             #······#     #·····#    #.....#    
             #······#     #######    #######    
             #······#                           
              #######                           
                                                
地下 1 階   体力 15/20   攻撃 4   倒した  1     54 歩
持ち物  1:解毒薬   矢印で移動 / 番号で使う / s セーブして中断 / q
トロルに 2 のダメージ（残り 2）。
トロルに 3 のダメージを受けた。
トロルを倒した！
```

- `!` 薬草 ／ `+` 解毒薬 ／ `)` 剣 ／ `[` 鎧。一度見た場所のアイテムは覚えている

## 仕様

| アイテム | 記号 | 効果 | 出やすさ |
|---|---|---|---|
| 薬草 | `!` | 体力 +8（最大まで） | 5 |
| 解毒薬 | `+` | 毒を消す。毒でなければ何も起きない | 2 |
| 剣 | `)` | 攻撃 +2（ずっと） | 1 |
| 鎧 | `[` | 最大体力 +5（体力も +5） | 1 |

- 1 階に 2〜3 個。敵のいないマス、階段でないマスに落ちている。持てるのは 6 個まで（いっぱいなら置いたまま）
- 使うと 1 ターン経つ（敵が動く）
- セーブは `save.pkl`（`--save` で変更可）。読み込んだら消える（続きは 1 回きり。ローグライクの流儀）
- 記録は `dungeon.log`（`--log` で変更可）。INFO は階の移動・戦闘・拾う・使う、DEBUG は敵の 1 歩ごと

## メモ

### `Protocol` — 「この形をしていればアイテム」

```python
@runtime_checkable
class Item(Protocol):
    name: str
    char: str
    weight: int

    def use(self, game: "Game") -> str: ...


@dataclass(frozen=True)
class Herb:
    name: str = "薬草"
    ...
    def use(self, game: "Game") -> str:
```

g17 の `abc.ABC` は「これを継承して、`@abstractmethod` を埋めろ」でした。`Protocol` は**継承させない**。
`Herb` は `Item` のことを知らないただの `dataclass` で、`name` `char` `weight` と `use()` を持っているから `Item` として通る（構造的部分型）。
型ヒント `list[Item]` や `dict[pos, Item]` はこの「形」を指し、`@runtime_checkable` を付けると `isinstance(x, Item)` も効きます。
テストでは `use` の無いクラスが弾かれることを確認しました。
継承の木を作りたくないとき——たとえば「剣」を `Weapon` にも `Item` にもしたいとき——に効く道具です。

### `pickle` — オブジェクトをそのままファイルに

```python
    def save(self, path: Path) -> None:
        with open(path, "wb") as f:
            pickle.dump((self, random.getstate()), f)

    @classmethod
    def load(cls, path: Path) -> "Game":
        with open(path, "rb") as f:
            game, state = pickle.load(f)
        random.setstate(state)
        return game
```

g09 の `json` は文字列・数値・リスト・辞書しか書けず、`Game` を保存するなら自分で辞書に直す必要がありました。
`pickle` は **Python のオブジェクトをそのまま** bytes にします。盤（リストのリスト）、`Rect` や `Monster` の `dataclass`、`Trait` の `Flag`、
`set`、アイテムの辞書——`Game` が持っている全部が 1 回の `dump` で入ります（7 KB ほど）。
`random.getstate()` も一緒に保存するのは、再開後の展開を「セーブしなかった場合」と同じにするため。テストではセーブ前後で 40 手の展開が一致しました。
`load` は `@classmethod`——`Game` の**インスタンスを作る側**の関数なので、`self` ではなく `cls` で受けます。

`pickle` は信用できないファイルを読んではいけません（任意のコードが動く）。自分のセーブだけを読む、この用途に向いています。

### `logging` — `print` の代わりに記録係へ

```python
logger = logging.getLogger("dungeon")       # モジュールの先頭
        logger.info(text)                   # Game.say の中
        logger.debug("%s %s → %s", monster.kind.name, monster.pos, step)

    logging.basicConfig(filename=args.log, level=logging.DEBUG if args.debug else logging.INFO, ...)   # main()
```

`Game` は「どこに書くか」を知りません。`logger.info()` に渡すだけで、出力先と粒度は `main()` の `basicConfig` が決めます。
だから同じ `Game` が、CLI ではファイルに、ブラウザではコンソールに記録を残せます。
`debug` は普段は捨てられ、`--debug` のときだけ敵の 1 歩ごとが残る（300 手で 1600 行）。`%s` の書式は文字列を作る前に「出すかどうか」を判定するための形です。
`say()` が画面用の 3 行とファイル用の全行を同時に扱うので、「画面に出したのに記録に無い」が起きません。

### `argparse` の `type=Path`

`--save` `--log` は `type=Path` で受けると、そのまま `.exists()` `.unlink()` が呼べます（g18 の `pathlib`）。

### セーブは読んだら消す

`Game.load` のあと `args.save.unlink()`。「セーブして戻す」を繰り返して有利な展開を選べないようにする、ローグライクの流儀です。
`--new` でセーブを無視して始めることはできますが、その場合もセーブは残ったままです（消すのは読んだときだけ）。

### 自動プレイ 24/30

剣と鎧はすぐ使い、体力半分以下で薬草、毒なら解毒薬、見えたアイテムは取りに行く操縦で 30 回中 24 回クリア（g20 の 22 回とほぼ同じ）。
アイテムで有利になりすぎないよう、薬草の重み 5 に対して剣・鎧は 1 にしています。
