# g81 軽飛行機で輪をくぐる（3D フライト）

山と谷の上に浮かぶ 12 個の輪を、順にくぐってタイムを競う。コックピット視点。**3D は g78〜g80 と同じく自分で書く。**
g79（yaw）・g80（yaw + pitch）に続いて、今回で**3 軸の回転**がそろう。

**ブラウザ版**: https://hicocho.github.io/python-study/g81/

```bash
python3 main.py            # 遊ぶ（スペースで始める。← → ロール、↑ ↓ 機首、w / s スロットル。q でやめる）
python3 main.py --check    # 決まりを確かめる
python3 main.py --shot     # 場面を PNG に書き出す
python3 main.py --map      # 地形と輪を真上から PNG に
```

ベスト（12 個くぐったタイム）は `records.json`（この階層。git には入れない）に残る。ブラウザ版は localStorage。

## 遊び方

- 3・2・1・GO で出発。**← → で翼を傾けると曲がる**（傾き 1 ラジアンで 0.9 rad/s。離すと水平に戻る）、**↑ ↓ で機首**（±55°）、スロットル 3 段階（40 / 65 / 90 m/s）。上昇で減速、降下で加速
- **橙の輪**が次。菱形の印が輪の場所、画面の外なら縁の矢印。輪の面をまたいだとき中心から 14 m 以内なら「くぐった」
- 山や地面にぶつかると跳ね返って減速（窓の縁が赤く）。タイムのロスが罰

## 3D で新しく覚えるところ

### 3 軸の回転——向きを 3 本のベクトルで持つ

```python
def spin(v: V, axis: V, angle: float) -> V:
    """v を axis（単位ベクトル）のまわりに angle だけ回す（ロドリゲスの回転公式）。"""
    c, s = math.cos(angle), math.sin(angle)
    return v.scale(c) + axis.cross(v).scale(s) + axis.scale(axis.dot(v) * (1 - c))


class Frame(NamedTuple):
    forward: V; up: V; right: V                   # 互いに直角の単位ベクトル

    def roll(self, angle):   return Frame(self.forward, spin(self.up, self.forward, -angle), spin(self.right, self.forward, -angle))
    def pitch(self, angle):  return Frame(spin(self.forward, self.right, -angle), spin(self.up, self.right, -angle), self.right)
    def yaw(self, angle):    return Frame(spin(self.forward, self.up, angle), self.up, spin(self.right, self.up, angle))
```

g78 の `rotate()` は x・y・z 軸まわりだけ。飛行機は「機体の軸」まわりに回るので、**どの向きの軸でも回せる式**（ロドリゲス）が要る。
向きを角度 3 つでなく**前・上・右の 3 本**で持てば、ロールは前を固定して上と右を回すだけ。混ぜても順番の悩みが無い。
毎コマ少しずつ回すと直角と長さがずれるので `tidy()` で直す（前を正規化 → 右から前の成分を引く → 上 = 前 × 右）。

### 基底で見るカメラ

```python
def view(p: V, cam: Camera) -> V:
    q = p - cam.pos
    return V(q.dot(cam.frame.right), q.dot(cam.frame.up), q.dot(cam.frame.forward))
```

g79・g80 は角度で世界を逆に回した。向きを 3 本で持てば、**「その軸にどれだけ沿っているか」＝内積**がそのままカメラ座標。式は 3 行。

### ハイトマップから地形

`relief(x, z)`（sin の重ね合わせ＋川の谷）を 32 × 32 マス（80 m）で表にし、`ground_at()` は 4 隅から双一次補間。
描くときは飛行機の近く 6 マスは 1 マスずつ、12 マスまでは 2 × 2、20 マスまでは 4 × 4 をまとめて（遠くは細かくても 1 ドットにならない）。
四角の 2 本の対角線の外積で法線 → 陰影、高さと傾きで色（水・砂・草・森・岩・雪）。奥から順に塗る（画家のアルゴリズム）。

### 傾く地平線

地平線は「水平で無限に遠い向き」を 2 つ投影した**直線**。傾けば傾く。空はその線より上の半平面を大きな多角形で塗る。
どちら側が空かは、カメラの「上」を画面に投影して決める（画面の上は y の負——ここで 1 回間違えた）。

### 輪をくぐる判定

```python
now = self.side(ring)                          # 輪の面のどちら側か（符号つき距離）
if self.side_before < 0 <= now:                # 面をまたいだ
    t = self.side_before / (self.side_before - now)
    at = self.pos_before + (self.pos - self.pos_before).scale(t)   # またいだ瞬間の位置
    if (at - ring.pos).length() <= RING_R:
        ring.done = True
```

1 コマで 2〜3 m 進むので、「今の位置」でなく**またいだ瞬間の位置**（前と今の間を補間）で比べる。

## 検証

- `--check`：3 軸の回転（1 本固定・直角と長さ）、基底で見るカメラ、地形（補間・外は海）、コース（地面から 60〜140 m）、
  飛行機の動き（傾き 70°・水平に戻る・上昇で減速）、地面との当たり、輪の判定（中と外）、自動操縦で 12 個（1:30、ぶつかり 0）、板の大きさ、記録、音
- 端末：pty で 30 コマ/秒。→ で方位が変わり、w で加速
- ブラウザ：Playwright で 29〜30 コマ/秒（4 倍の板）。→ で方位 0 → 75、スロットル▲で 83 m/s、↑ で高度 120 → 187

## メモ

- **回転の符号は必ず具体的な点で確かめる。** ロールもピッチも最初は逆だった（`spin` の右ねじの向き）。「30° 傾けたら bank() が 30°」の検査で発覚
- 「上 = 右 × 前」と書いて上下が逆になった。**上 = 前 × 右**
- 輪の向きは「前の輪から来て次の輪へ行く向きの平均」。「次の輪へ行く向き」だけだと、最初の輪を横から通ることになった
- 自動操縦は機体座標の上下でなく**世界の上げ角**で機首を決める。傾いた機体の「上」は横を向いている
