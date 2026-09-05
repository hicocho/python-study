# g09 スペースインベーダー

撃ち返してくる敵の編隊 21 体を、バリアに隠れながら全部落とす CLI ゲームです。
自機は 3 機。敵弾に 3 回当たっても、編隊に攻め込まれても負けです。

g07 でシューティングの土台（`class`）、g08 で編隊（継承）を作りました。
この g09 で**スペースインベーダーへの 3 段階が完成**します。

今回の主題は 3 つです。

- **クラス変数** — 得点 `POINTS` を、インスタンスではなくクラスに持たせる
- **関数の一般化** — `collide()` を敵にもバリアにも使い回す
- **ファイル入出力** — `with open` と `json` でハイスコアを次の起動に残す

## ブラウザ版

インストールせずに遊べます → **https://hicocho.github.io/python-study/g09/**

ソースは [`docs/g09/game.py`](../docs/g09/game.py)。7 つのクラス（`Entity` / `Ship` / `Bullet` /
`EnemyBullet` / `Enemy` / `ToughEnemy` / `Barrier`）と 7 つの関数（`make_enemies()` /
`make_barriers()` / `move_interval()` / `can_move()` / `move_enemies()` / `front_enemies()` /
`collide()`）、そして `class Game` の**計 288 行を 1 文字も変えずに**持ってきています
（ステップの目印コメント `# ←` を除いて差分を取り、完全一致を確認済み）。

外したのは `Game` の `render()` と `draw()` だけ。違うのは**入口と出口**で、

- 入口：キーボードの生読み取り → キーイベント
- 出口：文字の盤面 → 294 個の `<div>`
- 記録の置き場：`highscore.json` → `localStorage`

3 つ目が g09 で増えたところです。**ファイルが無い環境でも、外側だけ差し替えれば動きます**。

そしてブラウザ版だけ、CLI 版に無いものがあります——**ドット絵のインベーダー**。
下の「メモ」に書きました。

## 遊び方（ターミナル）

```bash
python3 main.py
```

- `←` `→` 自機を左右に動かす
- `スペース` 弾を撃つ（画面に 3 発まで）
- `q` やめる

```
+---------------------+
|.....................|
|....W.W.W.W.w.W.W....|
|.....................|
|......*.*.*.*.*.*....|
|.....................|
|..........*.*.*.*....|
|.............!.......|
|.....................|
|..........|..........|
|.....!...............|
|.....................|
|...###...#=#...#-#...|
|.....................|
|..........A..........|
+---------------------+
残り 17 体   自機 2   得点   40   最高  340     8.4 秒
← → 移動 / スペース 発射 / q やめる
```

- `A` 自機（残り 3 機）
- `|` 自分の撃った弾 ／ `!` 敵の撃った弾
- `*` 敵（1 発で落ちる・10 点）
- `W` 固い敵（2 発必要・30 点）／`w` 1 発受けて傷ついた状態
- `#` バリア ／ `=` 1 発受けた ／ `-` 2 発受けた（3 発で消える）

## 仕様

- 画面は 21 × 14。敵は 3 行 × 7 列の計 21 体。いちばん上の行は `ToughEnemy`
- 編隊は全体でそろって横に動く。壁に着いた回は 1 段下がって向きを変える
- 編隊が動く間隔は残り数で変わる。21 体なら 6 ティック（0.48 秒）、最短 2 ティック（0.16 秒）
- **敵の反撃**：1 ティックにつき 6% の確率で、**最前列の敵 1 体**が下向きの弾を撃つ。
  上の敵は前の敵に隠れて撃てない（列ごとにいちばん下の敵だけが撃つ）
- **自機は 3 機**。敵弾に当たると 1 機減り、0 で「撃ち落とされた」
- 敵が 1 体でも自機の行まで降りたら「攻め込まれた」。何もしないと 33 秒ほどで到達する
- **バリア**は自機の 2 段上に 3 つ（1 つは横 3 マス）。弾を受けるたびに削れ、3 発で消える。
  自機の弾も止まる。敵が重なると削れる間もなく壊れる
- **得点**：`*` 10 点、`W` 30 点。クリアすると残機 1 つにつき 100 点のボーナス。満点は 650 点
- **ハイスコア**は `highscore.json` に保存され、次の起動で読み込まれる（`.gitignore` 済み）

## メモ

### 上下が逆なだけの弾

g08 の README の最後で、`Bullet.alive()` をこう書いた理由を予告していました。

```python
    def alive(self):
        """まだ画面の中にいるなら True。"""
        return 0 <= self.y < HEIGHT
```

上へ飛ぶ弾しか無かった時点では `self.y >= 0` で足ります。それでも**上下どちらもはみ出しで判定**
しておいたので、下へ飛ぶ弾はこの行をそのまま受け継げました。

```python
class EnemyBullet(Bullet):
    """敵が撃った弾。上下が逆なだけで、あとは自機の弾と同じ。"""

    def __init__(self, x, y):
        super().__init__(x, y, "!")

    def update(self):
        """1段ぶん下へ進む。"""
        self.y += 1
```

書き足したのは `-=` を `+=` にした 1 行と、見た目だけです。

親の `Bullet` 側も 1 か所だけ直しました。

```python
    def __init__(self, x, y, mark="|"):
        super().__init__(x, y, mark)
```

デフォルト引数にしてあるので、**既存の `Bullet(self.x, self.y - 1)` は 1 文字も直っていません**。
g08 で `Entity.__init__` に `mark` を渡したのと同じ手です。
**後から選択肢を増やすときは、いままでの呼び出しが黙って動く形にする。**

### `Ship.shoot()` と `Enemy.shoot()` は双子

```python
    def shoot(self):                        # Ship
        return Bullet(self.x, self.y - 1)

    def shoot(self):                        # Enemy
        return EnemyBullet(self.x, self.y + 1)
```

どちらも「弾を作って**返すだけ**」で、リストに入れるのは呼んだ側（`Game`）の仕事です。
`self.bullets.append(...)` を `Ship` の中に書くと、`Ship` が `Game` のリストを知る必要が出ます。
**作る人と、しまう人を分ける。**

### 辞書は「キーごとの代表」を選ぶのに使える

上の敵は前の敵に隠れて撃てない、という本家の挙動です。

```python
def front_enemies(enemies):
    """列ごとに、いちばん下にいる敵だけを返す。撃てるのはこの敵だけ。"""
    front = {}

    for enemy in enemies:
        if enemy.x not in front or enemy.y > front[enemy.x].y:
            front[enemy.x] = enemy

    return list(front.values())
```

`x`（列）をキーにして、より下にいる敵で上書きしていきます。`or` の左が真なら右は評価されない
（g05 の短絡評価）ので、**まだ登録が無い列で `front[enemy.x]` を読んで `KeyError` になりません**。
この 2 条件は順番を入れ替えると落ちます。

そして g08 の `min` / `max` と同じで、**覚えずに数え直しています**。最前列の敵を落とせば、
次のティックからは自動的に 1 つ上の敵が撃ってくるようになります。

### 確率とタイマーを使い分ける

編隊の移動はカウントダウン（`cooldown`）、敵の発射は確率です。

```python
        if self.enemies and random.random() < ENEMY_SHOT_CHANCE:
            shooter = random.choice(front_enemies(self.enemies))
```

- **決まった間隔で起きてほしい**ものはカウントダウン
- **読まれたくない**ものは確率

編隊の動きが確率だとガタつき、発射がタイマーだと「次はいつ来るか」が丸わかりになります。
`0.06` は 1 ティック（0.08 秒）あたりの確率なので、平均 1.3 秒に 1 発です。

### `and` の右に「副作用のある呼び出し」を置くとき

```python
        if hits and self.ship.take_hit():
            self.result = "over"
```

`take_hit()` は**呼ぶと残機が減ります**。`hits` が空リストなら Python は `and` の右を評価しない
ので、**当たっていなければ残機も減りません**。順番を逆にすると毎ティック減って即ゲームオーバーです。

**短絡評価は「速さの話」ではなく「呼ぶ／呼ばない」の話**で、右側に副作用があるときは
順番が仕様そのものになります。同じ理由で、同時に 2 発当たっても `if` は 1 回なので残機は 1 しか減りません。

### ループの途中でリストをいじらない

```python
        hits = [b for b in self.enemy_bullets if b.hits(self.ship)]
        self.enemy_bullets = [b for b in self.enemy_bullets if not b.hits(self.ship)]
```

`for` で回しながら `remove()` すると要素が詰められ、**次の 1 個を飛ばします**。
`collide()` が新しいリストを組み立てているのも同じ理由です。
条件が `if` と `if not` で対になっていて、取りこぼしが起きません。

### 書こうとした関数が、もうあった

最初は `hit_barriers()` という新しい関数を書きかけました。「弾を回して、当たった相手を探して、
当たった弾は消して、壊れたら取り除く」——書いているうちに `collide()` と同じだと気づきます。

変えたのは**名前だけ**です。

```python
def collide(bullets, targets):     # 前は collide(bullets, enemies)
```

これで 3 通りの当たり判定が同じ関数で書けます。

```python
        self.bullets, self.barriers, _ = collide(self.bullets, self.barriers)
        self.enemy_bullets, self.barriers, _ = collide(self.enemy_bullets, self.barriers)
        self.bullets, self.enemies, downed = collide(self.bullets, self.enemies)
```

動く理由は、`collide()` が相手に求めるのが **`hits()` と `take_hit()` の 2 つだけ**だから。
`Barrier` は `Entity` を継承して `hits()` を持ち、`take_hit()` を自分で書いた。それだけで的になれます。

g08 の「型を聞かずに、呼ぶ」がここまで届きます。**関数が相手に求める約束を小さく保っておくと、
後から出てきた別物がそのまま乗る。** 名前が `enemies` のままだと敵専用に見えるので、
**使える範囲が広がったら名前も広げます**（g08 の `hits` → `downed` と同じ手当て）。

### クラス変数 — インスタンスごとに持たなくていい値

```python
class Enemy(Entity):
    POINTS = 10

class ToughEnemy(Enemy):
    POINTS = 30
```

`self.x` は 1 体ごとに別ですが、`POINTS` は `class` の直下なので**クラスに 1 つ**しかありません。

```python
>>> e = Enemy(1, 1)
>>> e.POINTS
10
>>> "POINTS" in e.__dict__     # インスタンス自身は持っていない
False
```

読むときは `enemy.POINTS` で構いません。**まずインスタンスを探し、無ければクラスを見にいく**からです。
`Barrier.MARKS`（削れたときの見た目）も同じ仕組みです。

`self.POINTS = 10` と `__init__` に書いても動きます。違うのは 21 体ぶんの `10` を作るかどうかと、
**「これは 1 体ごとの状態ではなく、その種類の性質だ」が読んで分かるかどうか**。書く場所そのものが説明になります。

そしてメソッドと同じで**子が書けば子が勝つ**ので、呼ぶ側は種類を聞きません。

```python
        self.score += sum(enemy.POINTS for enemy in downed)
```

**敵の種類を増やす手続きが「クラスを 1 つ足す」に揃いました。** 強さ（`take_hit`）も
見た目（`mark`）も点数（`POINTS`）も、そのクラスの中に書けば済みます。
もし `Game` が `{"*": 10, "W": 30}` のような辞書で持っていたら、敵を足すたびに離れた 2 か所を直すことになります。

### 数を返すと、後から欲しくなったときに壊れる

`collide()` の 3 つ目の返り値を、**数から「壊れたものそのもの」に変えました**。

```python
    return live_bullets, live_targets, broken     # 前は len(targets) - len(live_targets)
```

数のままだと点数が出せません。`10 点の敵が 2 体`と`30 点の敵が 2 体`は、どちらも「2」だからです。

```python
        self.downed += len(downed)
        self.score += sum(enemy.POINTS for enemy in downed)
```

**要約した値を返すと、要約に含まれなかった情報は永久に取り出せません。** 元のものを返しておけば、
呼ぶ側が欲しい形にできます。返り値の数は 3 つのままです。

### 判定の順番が仕様を決める（3 回目）

```python
        self.hit_ship()

        if self.over():
            return

        if not self.enemies:
```

最後の 1 体を落とした**同じこま**に自分も撃ち落とされることがあります。この `return` が無いと、
`result` が `"over"` から `"clear"` に**上書き**されます。

g08 では「`max()` に空リストを渡さないため」にクリア判定を先に置きました。今回は
**先に決まった結果を守るため**の早期リターン。理由は違いますが、どちらも並び順が仕様です。

### 状態は増やさず、あるものから導く

負け方が 2 通りになりましたが、`result` に `"shot"` と `"invaded"` は増やしていません。

```python
elif game.result == "over" and game.ship.lives <= 0:
    print(f"撃ち落とされた。  残り {len(game.enemies)} 体")
elif game.result == "over":
    print(f"攻め込まれた。  残り {len(game.enemies)} 体")
```

`ship.lives` を見れば理由は分かるからです。g08 で真偽値 2 つを `result` 1 つに畳んだのと同じ判断で、
**同じ事実を 2 か所に持つと、片方の更新を忘れた瞬間に嘘になる**。
状態を増やすのは「既にある値から導けないとき」だけです。

### `with` は「閉じ忘れない」ための書き方

```python
        with open(HIGHSCORE_FILE, encoding="utf-8") as f:
            return json.load(f)["score"]
```

`with` を使うと、**ブロックを抜けるときに必ず閉じられます**——`return` で抜けても、例外が出ても。
上の例はまさに `with` の中から `return` していますが、それでも閉じられます。

これは端末の設定を戻している `try` / `finally` と同じ仕組みで、
`with` はそれを**呼ぶ側が書かなくて済むようにまとめたもの**です。

### 「ファイルが無い」は異常ではない

```python
    except (OSError, ValueError, KeyError):
        return 0
```

| 例外 | いつ起きるか |
|---|---|
| `OSError` | ファイルが無い、読む権限が無い |
| `ValueError` | 中身が JSON として壊れている |
| `KeyError` | JSON だが `"score"` が入っていない |

**どれが起きても答えは同じ「まだ記録は無い（0）」**なので 1 つの `except` にまとめました。
g01 の `except ValueError`（数字でない入力）と同じ考え方で、
**起きうると分かっている事態は、例外で受けて既定値に倒す**。
ここで落ちると、記録ファイルを 1 度壊しただけで二度と遊べなくなります。

逆に `except:` と裸で書いて全部飲み込むのは避けます。想定外のバグまで隠れるからです。

### `__file__` — どこから起動しても同じ場所

```python
HIGHSCORE_FILE = os.path.join(os.path.dirname(__file__), "highscore.json")
```

`"highscore.json"` とだけ書くと**いま居るディレクトリ**に作られるので、
`cd g09-invaders` してから起動した場合とリポジトリのルートから起動した場合で、
**同じゲームなのに記録が 2 つに分かれます**。

`__file__` は「このソースファイル自身の場所」。その `dirname` と繋げば、
起動場所によらず `main.py` の隣に決まります。

### `Game` にファイルを触らせない

`load_highscore()` を `Game.__init__` の中で呼ぶこともできました。そうしなかったのは、
**`Game` をファイル無しで試せる状態に保つ**ためです。

```python
    def __init__(self, high=0):
        ...
        self.high = high                   # 表示に使うだけ。読み書きはしない
```

```python
game = Game(load_highscore())
...
if game.score > game.high:
    save_highscore(game.score)
```

おかげで `Game(250)` と直接渡してクリア時の得点を確かめられます——ファイルを作らずに、です。
`Game` が中で読みに行っていたら、テストのたびに本物の記録を書き換えてしまいます。

**外の世界（ファイル・端末・ブラウザ）に触る処理は、ルールを持つ部分の外に出す。**
g07 から一貫してやってきたこと（`Ship.shoot()` は弾を作るだけ、`render()` は文字列を返すだけ）の
締めくくりで、これがそのままブラウザ版への移植しやすさになっています。
ブラウザに `open()` はありませんが、`Game` が触っていないので**差し替えるのは外側だけ**でした。

```python
def load_highscore():
    """保存してあるハイスコアを読む。CLI 版はファイル、ここでは localStorage。"""
    try:
        return int(localStorage.getItem(HIGHSCORE_KEY) or 0)
    except (TypeError, ValueError):
        return 0
```

### ブラウザ版だけの追加：ドット絵のインベーダー

CLI 版は `*` や `W` の文字で足りますが、ブラウザ版はアーケードらしいドット絵にしました。
**ゲームのロジックには 1 行も触っていません。**

ドット絵は**文字列のリスト**として持ちます。

```python
CRAB_1 = [
    "..#.....#..",
    "...#...#...",
    "..#######..",
    ".##.###.##.",
    "###########",
    "#.#######.#",
    "#.#.....#.#",
    "...##.##...",
]
```

これを SVG に組み立てて、CSS にそのまま入る形にします。

```python
def sprite_url(rows, color):
    """ドット絵を SVG の data URI にする。CSS の background-image にそのまま入る。"""
    height = len(rows)
    width = len(rows[0])
    dots = "".join(
        f"<rect x='{x}' y='{y}' width='1' height='1'/>"
        for y, row in enumerate(rows)
        for x, dot in enumerate(row)
        if dot == "#"
    )
    svg = (f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 {width} {height}' "
           f"fill='{color}'>{dots}</svg>")
    return f'url("data:image/svg+xml,{quote(svg, safe="")}")'
```

起動時に一度だけ CSS 変数へ流し込めば、あとは今まで通りクラス名を付け替えるだけです。

```python
for name, (frame_a, frame_b, color) in SPRITES.items():
    document.documentElement.style.setProperty(f"--s-{name}", sprite_url(frame_a, color))
```

**置き方は `POINTS` と同じ考え方です。** 敵の種類ごとに「強さ・見た目・点数・ドット絵」が
1 か所にまとまっている状態を崩していません。

**大きさは 1.5 マス分。** 敵は `range(4, 17, 2)` と `y in (1, 3, 5)` で**縦も横も 1 マス空けて**
並ぶので、はみ出しても隣とぶつかりません。ただし `background-image` は
**マスの外へはみ出せない**（拡大すると切り取られる）ので、`::before` を広げてそこに描いています。

```css
  .cell::before { content: ""; position: absolute; inset: 0;
    background-repeat: no-repeat; background-position: center; background-size: contain; }
  .c-enemy::before { inset: -25%; }        /* 1.5 マス分に広げる */
  .c-ship::before { inset: -25% -25% 0; }  /* 自機は最下行。下だけは広げない */
  .c-enemy { z-index: 1; }                 /* 隣のマスの不透明な背景に隠れないように */
```

バリアだけは等倍で固定です。横に 3 つ連なるので、はみ出すと継ぎ目がずれて 1 枚の壁に見えません。

**パタパタ（2 コマの切り替え）も足しました。** これも `Game` には何も足していません。

```python
    # cooldown は毎ティック 1 減り、編隊が動いた回だけ入れ直される。
    # つまり「増えていたら動いた」。Game に何も足さずに動いた瞬間が分かる。
    if game.cooldown > prev_cooldown:
        frame = 1 - frame
```

`cooldown` は減り続けて 0 以下で動き、そのとき次の間隔（最短 2）が入ります。
**増えるのは動いた回だけ**なので、これが合図になります。

### 3 段階を振り返って

| | 覚えた文法 | 作ったもの |
|---|---|---|
| g07 | `class` / `__init__`・`self` / メソッド | 動かない的を撃つ |
| g08 | 継承 / `super()` / オーバーライド / `class Game` | 編隊が降りてくる |
| g09 | クラス変数 / 関数の一般化 / ファイル入出力 | 撃ち返す・バリア・スコア |

大きい題材を 1 課題に詰め込まず、**覚える文法で切って連作にする**とこうなります。
g09 で追加したクラスは `EnemyBullet` と `Barrier` の 2 つだけで、
残りは g08 のコードがそのまま動いています。
