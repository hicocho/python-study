# g08 敵の編隊

左右に動きながら 1 段ずつ降りてくる敵の編隊 21 体を、全部落とす CLI ゲームです。
いちばん上の行は 2 発当てないと落ちない固い敵。自機の高さまで降りられたら負けです。

g07 で `Ship` / `Bullet` / `Target` の 3 クラスを書いたとき、3 つとも
`self.x` `self.y` `self.mark` という同じ 3 行を持っていました。この重複を親クラスにまとめる、
つまり**継承**が今回の主題です。後半では、`Enemy` を継承した `ToughEnemy` で
**メソッドの上書き（オーバーライド）**も扱います。

最後に、g07 の README で予告していた `class Game` へ状態をまとめて CLI 版を締めます。

この課題はスペースインベーダーへの 3 段階の 2 段目です（g07 でシューティングの土台、g09 で反撃とバリア）。

## ブラウザ版

インストールせずに遊べます → **https://hicocho.github.io/python-study/g08/**

ソースは [`docs/g08/game.py`](../docs/g08/game.py)。5 つのクラス（`Entity` / `Ship` / `Bullet` /
`Enemy` / `ToughEnemy`）と 5 つの関数（`make_enemies()` / `move_interval()` / `can_move()` /
`move_enemies()` / `collide()`）、そして `class Game` を、ステップの目印コメント（`# ←`）を除いて
**1 文字も変えずに**持ってきています（差分を取って確認済み）。

外したのは `Game` の `render()` と `draw()` だけ。つまり違うのは**入口と出口**で、
キーボードの生読み取りがキーイベントに、文字の盤面が 294 個の `<div>` に入れ替わっています。

g07 のブラウザ版は状態を `state` という辞書に持たせていましたが、今回はその必要がありません。
`Game` がすでに状態を全部持っているので、**ブラウザ版が自分で持つのは「遊んでいる最中か」と時刻だけ**です。
「もう一度」で `Game()` を作り直せば、それが初期化になります。

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
|.....................|
|.....................|
|...W.w.W.w.W.w.W.....|
|.....................|
|...*.*.........*.....|
|.....................|
|.............*.*.....|
|.....................|
|.............|.......|
|.....................|
|..............|......|
|.....................|
|..............A......|
+---------------------+
残り 12 体   弾 2/3     6.4 秒
← → 移動 / スペース 発射 / q やめる
```

- `A` 自機
- `|` 自分の撃った弾
- `*` 敵（1 発で落ちる）
- `W` 固い敵（2 発必要）／`w` 1 発受けて傷ついた状態

## 仕様

- 画面は 21 × 14。敵は 3 行 × 7 列の計 21 体で、中央に並ぶ
- いちばん上の行（7 体）は `ToughEnemy`。2 発当てないと落ちない
- 編隊は全体でそろって横に動く。壁に着いた回は横に進まず、1 段下がって向きを変える
- 編隊が動く間隔は残り数で変わる。21 体なら 6 ティック（0.48 秒）、減るほど短くなり、最短 2 ティック（0.16 秒）
- 弾は 0.08 秒ごとに 1 段上がる。当たるか画面の外に出ると消える。同時に 3 発まで
- 弾 1 発が当たる敵は 1 体まで。固い敵に当たっても弾は消える
- 21 体すべて落とすとクリア。タイム・撃った数・命中率が出る
- 敵が 1 体でも自機の行（下から 1 行目）まで降りたら負け。何もしないと 33 秒ほどで到達する
- `q` で中断すると、残り数と命中率が出る

## メモ

### 同じ 3 行を 3 回書いていた

g07 の 3 つのクラスは、`__init__` の中身がほとんど同じでした。

```python
class Ship:
    def __init__(self, x, y):
        self.x = x
        self.y = y
        self.mark = "A"
```

違うのは `mark` の中身だけ。そこで、同じ部分を持つ親クラスを 1 つ作ります。

```python
class Entity:
    """位置と見た目を持つもの。自機・弾・敵の共通部分。"""

    def __init__(self, x, y, mark):
        self.x = x
        self.y = y
        self.mark = mark

    def hits(self, other):
        """相手と同じマスにいるなら True。"""
        return self.x == other.x and self.y == other.y


class Ship(Entity):
    def __init__(self, x, y):
        super().__init__(x, y, "A")
```

`class Ship(Entity):` のカッコが継承で、「`Ship` は `Entity` の一種」という意味です。
これだけで `Ship` は `Entity` に書いたものを全部持ちます。`Bullet` に `hits()` を
書いていないのに `bullet.hits(enemy)` が動くのはそのためです（g07 では `Bullet` の中に書いていました）。

**共通化のこつは「何が同じで何が違うか」を先に分けること。** ここでは `mark` だけが違ったので、
`mark` を `__init__` の引数にしました。**違うところを引数にすると、同じところをまとめられます。**

### `super()` は 1 段上を指す

```python
class ToughEnemy(Enemy):
    def __init__(self, x, y):
        super().__init__(x, y, "W")
        self.hp = 2
```

`ToughEnemy` → `Enemy` → `Entity` と 2 段重なっています。`super().__init__` が呼ぶのは
1 つ上の `Enemy.__init__` で、その中の `super().__init__` がさらに `Entity.__init__` を呼ぶ。
**1 段ずつ上へ渡っていく**のが `super()` です。

子と親に同じ名前のメソッドがあるときは**子が勝ちます**。`Ship(10, 13)` で呼ばれるのは `Ship.__init__`。
そこから親を呼び直したいときだけ `super()` を書きます。

### 型を聞かずに、呼ぶ

継承のもう半分がオーバーライド（上書き）です。`Enemy` と `ToughEnemy` は
同じ名前の `take_hit()` を持っていて、中身が違います。

```python
class Enemy(Entity):
    def take_hit(self):
        """弾を1発受ける。落ちたなら True。"""
        return True


class ToughEnemy(Enemy):
    def take_hit(self):
        """弾を1発受ける。体力が尽きたなら True。"""
        self.hp -= 1

        if self.hp > 0:
            self.mark = "w"
            return False

        return True
```

呼ぶ側は種類を聞きません。

```python
        elif hit.take_hit():
            live_enemies.remove(hit)
```

`isinstance()` で書き分けていないので、**敵の種類を増やしても `collide()` は 1 文字も直りません**。
g07 の「相手の型を決め打ちしない」の続きです。

**返すのは「落ちたか」であって「体力」ではない**のも大事なところ。`hp` を返して呼び出し側に
判断させると、`hp` を持たない `Enemy` で破綻します。**外から見て意味のあることだけを返し、
内側の作り（hp があるかどうか）は隠す。**`Enemy.take_hit()` が `return True` の 1 行なのは、
「1 発で落ちる」を素直に書いた結果です。

`self.hp = 2` を `ToughEnemy` にしか書いていないのも同じ考え方で、
親に空の `hp = 0` を用意する必要はありません（g07 で `Target` に `update()` を書かなかったのと同じ）。

### 判断する人と、動く人を分ける

敵 1 体は「言われた分だけ動く」しか知りません。

```python
class Enemy(Entity):
    def update(self, dx, dy):
        """横に dx、下に dy だけ動く。"""
        self.x += dx
        self.y += dy
```

端に着いたか、いま右か左か、を決めるのは編隊全体の話なので、外の関数が持ちます。

```python
def move_enemies(enemies, direction):
    """編隊を動かす。壁に着いていたら横へは進まず、1段下げて向きを変える。"""
    if can_move(enemies, direction):
        for enemy in enemies:
            enemy.update(direction, 0)
    else:
        direction = -direction
        for enemy in enemies:
            enemy.update(0, 1)

    return direction
```

**1 体で決められることだけを 1 体に持たせる。** `Bullet.update()` が引数なしで自分だけで
進めるのと対照的です。壁の回に横へ進まない（`update(0, 1)` の `0`）のは本家と同じ挙動で、
ここを `update(direction, 1)` にすると折り返しの瞬間に横へ 1 マス飛んで動きがガタつきます。

### 端は、覚えずに数え直す

編隊の左端・右端は変数に持っていません。そのつど残っている敵から計算します。

```python
def can_move(enemies, dx):
    if dx < 0:
        return min(enemy.x for enemy in enemies) + dx >= 0
    return max(enemy.x for enemy in enemies) + dx < WIDTH
```

`min` / `max` にジェネレータ式を渡す形は、g06 で `sum()` に渡したのと同じです。

そして、これが**特別なコードなしに本家と同じ挙動を生みます**。端の列を撃ち落とすと
`min` / `max` の値が変わり、編隊はその分だけ遠くまで行けるようになる。負け判定の
`max(enemy.y for enemy in enemies) >= ship.y`（いちばん下にいる敵の行）も同じで、
最前列を落とせば自動的に 1 つ上の行を見るようになります。
**覚えた値を持ち回ると、更新し忘れた瞬間に嘘になる。数え直せる値は数え直す。**

### 空のリストに `max()` は使えない

```python
        if not self.enemies:
            self.result = "clear"
        elif max(enemy.y for enemy in self.enemies) >= self.ship.y:
            self.result = "over"
```

`max()` は空のリストを渡すと `ValueError` で落ちます。最後の 1 体を撃ち落とした直後は
`enemies` が空なので、**クリア判定を先に置いて** `max()` に空が渡らないようにしています。
逆順にすると「最後の敵を倒した瞬間だけ落ちる」という、たまにしか出ないバグになります。
`elif` にしてあるのも同じ理由です。

### 周期が変わるなら、割り算ではなくカウントダウン

敵は 6 ティックに 1 回だけ動きます。作っている途中は割り算で判定していました。

```python
if ticks % ENEMY_MOVE_TICKS == 0:      # 間隔が一定なら、これでいい
```

ところが「敵が減ると速くなる」を足すと、この形が壊れます。間隔が 6 → 4 → 2 と変わると、
`ticks` の絶対値に対する余りは意味を失い、動きが飛んだり詰まったりする。
そこで「あと何回で動くか」を持ち、1 ずつ減らして 0 で動かし、**次の間隔を入れ直します**。

```python
        self.cooldown -= 1
        if self.cooldown <= 0:
            self.direction = move_enemies(self.enemies, self.direction)
            self.cooldown = move_interval(self.enemies, self.total)
```

```python
def move_interval(enemies, total):
    """残り数に応じた、敵が動く間隔。減るほど短く（速く）なる。"""
    ratio = len(enemies) / total
    return max(ENEMY_MIN_TICKS, round(ENEMY_MOVE_TICKS * ratio))
```

`total`（開始時の 21）を別に取ってあるのは、割合の分母が要るからです。
`max(ENEMY_MIN_TICKS, ...)` は下限で、これが無いと残り 1 体で間隔が 0 になり、
毎ティック動く（＝止まって見えないほど速い）ことになります。

### 名前と中身がずれたら、名前を直す

固い敵ができたことで「弾が当たった数」と「敵が落ちた数」が別物になりました。
`collide()` が返しているのは後者なので、変数名を `hits` から `downed` に、
表示も「命中 N 発」から「撃破 N 体」に変えています。
**ずれた名前をそのままにすると、あとで自分が読み違えます。**

### `class Game` — 引数 4 つの答え

g07 の README の最後に「`draw()` の引数が 4 つに増えた」と書きました。その答えがこれです。
トップレベルに散らばっていた 10 個の変数を 1 つのオブジェクトにまとめます。

```python
class Game:
    def __init__(self):
        self.ship = Ship(WIDTH // 2, HEIGHT - 1)
        self.bullets = []
        self.enemies = make_enemies()
        self.total = len(self.enemies)
        self.direction = 1
        self.cooldown = ENEMY_MOVE_TICKS
        self.shots = 0
        self.downed = 0
        self.result = None
```

効果は 3 つあります。

**1. メインループからルールが消えた。** 残ったのは「キーを読む」「時間を待つ」
「端末の設定を戻す」だけで、ルールは全部 `Game` の中です。だからブラウザ版は
`Game` をそのまま使い、下半分だけ差し替えれば動きます。

**2. 引数の受け渡しが要らなくなった。** ループの中の素の変数は、関数に切り出そうとした途端
「引数で渡して返り値で受け取る」が必要になります（`direction = move_enemies(...)` がまさにそれ）。
`self.direction` なら `update()` の中で書き換えるだけです。
**`self.` を付けた瞬間、変数の寿命がオブジェクトと同じになる。**

**3. 終わり方が `break` から状態になった。**

```python
    def over(self):
        """勝負がついているなら True。"""
        return self.result is not None
```

`cleared` と `over` という 2 つの真偽値をやめて、`result` に `"clear"` / `"over"` / `"quit"`
のどれかを入れる形にしました。**同時に True にならない真偽値が 2 つ以上あるなら、
1 つの状態に畳める。**おかげでメインループは `while not game.over():` の 1 行で回り、
3 通りの終わり方が同じ仕組みに乗ります。初期値が `None` なのは「まだ決まっていない」を
表すためで、`is not None` で「決まったか？」が素直に書けます。

### `update()` という名前が 3 つある

`Bullet.update()`（1 段上へ）、`Enemy.update(dx, dy)`（言われた分だけ）、
`Game.update()`（時間を 1 こま）。名前が同じでもクラスが違えば別物です。
そのうえで役割は揃えてあります——**自分を 1 こま進める**。
呼ぶ側が `x.update()` と書ける形に名前を揃えておくと、中で何が起きるかを知らずに使えます。

### クラスに入れなかったもの

`collide()` `move_enemies()` `can_move()` `move_interval()` は関数のまま残しました。
どれも「渡されたものを見て答えを返す」だけで、状態を持たないからです。
**持たないものはクラスに入れない。**状態を持たない関数は単体で試せます。実際、
`collide()` に弾と敵のリストを渡して固い敵が 2 発で落ちるか、`move_interval()` が
21 → 6・10 → 3 を返すかは、ゲームを起動せずに確かめました。

### 次（g09）へ

敵は撃ち返してきません。`Ship.shoot()` と同じ形の `shoot()` を `Enemy` に持たせ、
下へ飛ぶ弾を足すのが g09 です。`Bullet.alive()` を
`return 0 <= self.y < HEIGHT` と**上下どちらもはみ出しで判定**してあるのは、そのときそのまま使うためです。
バリアもスコアも `Game` のインスタンス変数が増えるだけで、`draw()` の引数は 1 つのままで済みます。
