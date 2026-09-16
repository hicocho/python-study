# g67 モグラ叩き

3 × 3 の穴から顔を出すモグラを 60 秒で叩く。金のモグラ（+5、すぐ引っ込む）、ヘルメット（2 回叩いて +3）、爆弾（叩くと −3）。
連続で当てるとコンボ（3 回ごとに倍率 +1、×4 まで）。反応時間（顔を出してから叩くまで）を測って平均と最速を出す。

**ブラウザ版**: https://hicocho.github.io/python-study/g67/

```bash
python3 main.py            # 遊ぶ（スペースで始める。テンキーの並び 7 8 9 / 4 5 6 / 1 2 3 で叩く。q でやめる）
python3 main.py --check    # 決まりを確かめる
python3 main.py --sheet    # モグラの絵と場面を PNG に
```

ベスト（点・最長コンボ・最速の反応）は `records.json`（git には入れない）に残る。ブラウザ版は localStorage。

## 主題：絵と動きを分ける

前に話した「スプライット（絵）」と「ゲームオブジェクト（動き）」の違いを、そのまま課題にした。

- **絵**は `Sprite`（g32 と同じ。文字で描いたドット絵、`.` が透明）。モグラ・金・ヘルメット・爆弾 × ふつうの顔と叩かれた顔、ハンマー。
  金はふつうのモグラの**色を置き換えただけ**（`recolor`）
- **動き**は `Hole`（穴の状態機械）。`EMPTY → RISING（0.15 秒）→ UP（顔を出す）→ SINKING（0.15 秒）→ EMPTY`、叩けば `HIT`。
  状態と「その状態に入った時刻」だけを持ち、`lift()` が今の高さ（0〜1）を返す
- `draw()` は穴の状態を見て絵を選び、`lift` のぶん上にずらして置く。穴の縁より下は `clip_bottom` で隠す

```python
class State(Enum):
    EMPTY = "empty"; RISING = "rising"; UP = "up"; SINKING = "sinking"; HIT = "hit"

@dataclass
class Hole:
    state: State = State.EMPTY
    kind: str = "normal"
    since: float = 0.0          # いまの状態に入った時刻

    def lift(self, now):        # 0（穴の中）〜1（全部出ている）
        if self.state == State.RISING:  return min(1.0, (now - self.since) / RISE)
        if self.state == State.SINKING: return max(0.0, 1 - (now - self.since) / SINK)
        return 1.0 if self.state in (State.UP, State.HIT) else 0.0
```

## 仕様

- 60 秒。出る間隔は `1.3 → 0.45 秒`、顔を出す時間は `1.5 → 0.7 秒`（時間の式。難しさの階段）。金は 0.6 倍の時間
- 種類は `random.choices(weights=)`：ふつう 70、金 8、ヘルメット 12、爆弾 10
- 空の穴を叩くと −1、爆弾は −3、どちらもコンボが 0 に。ヘルメットは 1 回目「クランク」、2 回目で割れる
- 点 = 種類の点 × 倍率（`min(4, 1 + 連続 // 3)`）
- 音：出た・叩いた・金・クランク・爆弾・空振り・終了・ベスト

## 検証

- `--check`：絵（4 種 × 2、金は色替え）、状態機械の遷移、叩く（空振り／ふつう／金／爆弾／ヘルメット 2 回、反応時間）、コンボ（7 連続で 14 点、空振りで 0）、
  難しさの階段、自動で叩いて 1 ラウンド（72 匹、命中 64、357 点、反応の平均 0.27 秒）、板の大きさ、記録、音
- 端末：pty で 28 コマ/秒。数字キーで叩ける
- ブラウザ：Playwright で 29 コマ/秒。叩ける穴を見てタップとキーで 30 秒叩き、命中 29・空振り 0

## メモ

- 端末の状態行は 120 桁に収める（最初 137 桁あった）
- コンボの倍率は「叩いた直後の連続数」で決まる。検査で 1 つずれていた
