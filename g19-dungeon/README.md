# g19 ダンジョン

部屋と廊下をランダムに作り、霧の中を矢印キーで歩いて階段 `>` を探す CLI ゲームです。
地下 5 階の階段にたどり着いたらクリア。見えたところだけが地図に残ります。

g19 → g20 → g21 の 3 段階の連作（ローグライク）の 1 段階目で、この g19 が「ダンジョンと探索」、g20 が「敵と視界と戦闘」、g21 が「アイテムとセーブ」です。

今回の主題は 3 つです。

- **`__contains__`** — `pos in room` と書けるようにする。`in` も自分の型に教えられる演算子
- **`itertools.combinations`** — 部屋の全組み合わせで「重なっていないか」を確かめる
- **集合の和 `|=`** — 見えたマスを `seen` に足していく霧の表現

## ブラウザ版

インストールせずに遊べます → **https://hicocho.github.io/python-study/g19/**

ソースは [`docs/g19/game.py`](../docs/g19/game.py)。定数 11 個と `Rect`、`make_rooms()` / `rooms_apart()` / `carve_room()` /
`carve_line()` / `carve_corridor()` / `make_dungeon()` / `reachable()` / `visible_cells()`、そして `class Game` を **1 文字も変えずに**持ってきています
（`ast` で切り出して文字列比較で確認済み）。

持ってこなかったのは `dungeon_text()` と `raw_mode()` / `read_key()` / `main()`、それに `Game.render()` だけ。
違うのは**入口と出口**で、入口は `termios` の生キー入力 → キーイベントとパッド、出口は文字の盤 → 960 個の `<div>`（見えている／覚えている／未知で色を変える）。

## 遊び方（ターミナル）

```bash
python3 main.py
```

- 矢印キーで移動。`>` に乗ると次の階
- `q` やめる

```
                                                
                                                
                                                
                                                
                                                
                                                
                                                
                                                
                                                
                                                
                           ··##                 
                        ·····#####              
                       ####·########            
                       ········########         
                       ········#########        
                      #········####.....        
                       ········####.....        
                       ·······.....@..>..       
                       ############.....        
                        ################        
地下 1 階     10 歩   > で下へ   矢印で移動 / q でやめる
```

- `@` 自分 ／ `#` 壁 ／ `.` 見えている床 ／ `·` 覚えているだけの床 ／ `>` 階段 ／ 空白は未知

## 仕様

- ダンジョンは 48 × 20。部屋は横 4〜9・縦 4〜6 を最大 7 つ、壁 1 マスの隙間を空けて重ならないように置く（60 回試して置けたぶんだけ）
- 廊下は置いた順に隣の部屋の中心どうしを L 字でつなぐ。曲がり角は右上か左下をランダムに
- 階段は最後に置いた部屋の中心。自分は最初の部屋の中心から
- 見えるのは半径 5 マス（この階では壁で遮られない。g20 で光線にする）。一度見えたマスは `·` で残る
- 階段に乗ると次の階を作り直す。5 階の階段でクリア

## メモ

### `__contains__` — `in` を自分の型に

```python
    def __contains__(self, pos):
        px, py = pos
        return self.x <= px < self.x2 and self.y <= py < self.y2
```

`(3, 4) in room` と書くと `room.__contains__((3, 4))` が呼ばれます。g14 の `__add__`、g15 の `__matmul__` に続く
演算子オーバーロードで、`in` も例外ではありません。「部屋の中か」が英語のまま読めます。

### `combinations` — 全組み合わせを 1 回ずつ

```python
def rooms_apart(rooms):
    return all(not a.overlaps(b) for a, b in combinations(rooms, 2))
```

7 つの部屋から 2 つ選ぶ組み合わせは 21 通り。二重の `for` で書くと `(a, b)` と `(b, a)` を 2 回見たり、`(a, a)` を見たりして
`if i < j` が要ります。`combinations(rooms, 2)` は**重複も自分自身も無しで 1 回ずつ**出してくれます。g10 の `product` が「全部の組」、
こちらは「選び方」です。

### `overlaps` は「隙間 1 マス」込み

```python
        return (self.x - 1 < other.x2 and other.x - 1 < self.x2
                and self.y - 1 < other.y2 and other.y - 1 < self.y2)
```

ぴったり隣り合った部屋は壁がなくなって 1 つの大部屋になってしまう。`- 1` で 1 マス広げて判定すると、必ず壁 1 枚が残ります。
「重なっていない」は「左右か上下のどちらかで完全に離れている」の否定で、この 4 つの `and` になります。

### 置けるまで試す

```python
    for _ in range(ROOM_TRIES):
        room = Rect(...)
        if not any(room.overlaps(other) for other in rooms):
            rooms.append(room)
        if len(rooms) == MAX_ROOMS:
            break
```

「重ならない場所を計算で探す」より「ランダムに置いてみて、だめなら捨てる」が単純で、60 回も試せば 7 つ入ります
（300 回の生成で平均 7.0 個）。`any(...)` は g09 でやった「1 つでも当たれば」。

### L 字の廊下

```python
    corner = (bx, ay) if random.random() < 0.5 else (ax, by)
    carve_line(grid, a, corner)
    carve_line(grid, corner, b)
```

2 点を結ぶ廊下は「横に行ってから縦」か「縦に行ってから横」。曲がり角を先に決めれば、まっすぐ掘る関数を 2 回呼ぶだけ。
`carve_line` は縦横どちらでも同じコードで掘れるように、`x` と `y` の範囲をそれぞれ `min`〜`max` で回しています。

### つながっているかは BFS で確かめる

部屋を置いた順につないでいるので、理屈では全部つながっているはず。でも「はず」は検証しません。
g12 の `shortest_path` と同じ `deque` の BFS で「最初の部屋から歩いて行けるマス」を集め、**全部屋の中心と階段が入っているか**を
300 回の生成で確かめました。

### 霧は集合 2 つ

```python
        self.visible = visible_cells(self.player)
        self.seen |= self.visible
```

`visible` は「いま見えている」、`seen` は「一度でも見えた」。`|=` は集合の和で、見えるたびに足していきます。
表示は「`visible` ならそのまま、`seen` なら薄く、どちらでもなければ空白」の 3 段階。状態を増やさず、集合 2 つで済んでいます。

### `descend()` — 階を降りるたびに作り直す

```python
    def descend(self):
        self.floor += 1
        self.grid, self.rooms = make_dungeon()
        self.player = self.rooms[0].center
        self.seen = set()
```

最初の階も `__init__` から同じ `descend()` で作ります（g17 の `next_wave()` と同じ形）。
`seen` を空にするので、新しい階は何も知らないところから始まります。
