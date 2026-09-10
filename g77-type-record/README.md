# g77 タイピング3（記録と苦手キー）

タイピング 3 段階の**完成形**（[g75](../g75-type-keys/) → [g76](../g76-type-kana/) → g77）。
g76 に**記録**と**苦手キー**を足した。終わるたびに記録が残り、成績に**自己ベスト**と**いつもの速さ**が添えられる。
ミスは**押すべきだったキー**ごとに数え、段階 4「にがてなキー」では**苦手なキーを含むことばが多めに出る**。

**ブラウザ版**: https://hicocho.github.io/python-study/g77/

```bash
python3 main.py              # 練習する（日本語入力はオフに）
python3 main.py --check      # 決まりを確かめる
python3 main.py --records    # 記録を見る
```

## 今回の主題

**遊んだ結果を次の出題に返す。** 記録は読むためだけでなく、練習文を選ぶ重みになる。

**1. 記録の形は 1 つ — `History.dump()` / `parse()`**

```python
@dataclass
class History:
    records: list[Record] = field(default_factory=list)
    weak: Counter = field(default_factory=Counter)  # 押すべきだったキー → ミスの数

    def dump(self) -> str:
        return json.dumps({"records": [asdict(row) for row in self.records],
                           "weak": dict(self.weak)}, ensure_ascii=False, indent=1)

    @staticmethod
    def parse(text: str) -> "History":
        try:
            data = json.loads(text)
            return History([Record(**row) for row in data["records"]], Counter(data["weak"]))
        except (ValueError, KeyError, TypeError):
            return History()                        # 壊れていたら空から
```

端末は `records.json`、ブラウザは `localStorage`。**置き場が違うだけで中身の形は同じ**。
`dataclasses.asdict` で字にし、`Record(**row)` で戻す。

**2. 苦手キーで重みづけ — `random.choices(weights=)`**

```python
    pool = [word for other in STAGES[:2] for word in other.words]
    weights = [1 + WEAK_WEIGHT * sum(romaji_of(word).count(key) for key in weak) for word in pool]
    word = luck.choices(pool, weights)[0]
```

苦手キーを 1 つ含むごとに重みが 3 増える。測ると、苦手が `k` のとき `k` を含むことばの割合が **46% → 78%**。

**3. 上位だけ取る — `heapq.nlargest`／時刻を戻す — `datetime.fromisoformat`**

```python
    def top(self, n: int = 3) -> list[Record]:
        return nlargest(n, self.records, key=lambda row: row.per_minute)

    def day(self) -> str:
        return datetime.fromisoformat(self.when).strftime("%m/%d")
```

`nlargest` は全部並べ替えずに上位だけ取る。「いつもの速さ」は平均ではなく**中央値**（1 回の大当たりに引きずられない）。

**4. 時刻は外から渡す**（g75 と同じ）

```python
            if game.done and not game.recorded:     # 時刻はここで読んで渡す
                game.record(datetime.now().isoformat(timespec="minutes"))
```

`Game.record(when)` は時計を読まない。端末は `datetime.now()`、ブラウザは JS の `Date` から組んだ字を渡す。
だから検証で同じ時刻を与えて、端末とブラウザの記録を突き合わせられる。

## 遊び方

g76 と同じ。足したのは成績の 2 行と、段階 4。

```
 打鍵 31  ミス 0  正確さ 100%  0.5 秒  1 分あたり 250 打
 自己ベスト 260 打  いつも 230 打  （5 回め）
 苦手なキー: k 3  h 1
   09/10 ながい ことば  260 打  正確さ 100%
   09/10 みじかい ことば  245 打  正確さ 96%
```

## 仕様

- 段階 4 つ：みじかい ことば → ながい ことば → ぶん → **にがてなキー**（全段階のことばから、苦手キーで重みづけ）
- 記録は 1 回ごと（いつ・段階・打鍵・ミス・正確さ・1 分あたり）。200 件まで
- 苦手キーは「押すべきだったキー」のミスの数。多い順に 5 つを重みづけに使う
- `--check` が見るもの：苦手キーで出題の割合が上がるか（k / n / sh で測定）、同じ苦手・同じ回なら同じ文か、
  記録が 1 回に 1 行だけ増えるか、字にして戻しても同じか、壊れた字は空から始まるか、
  自己ベスト・中央値・上位 n 件、g76 の検査ぜんぶ

## メモ

- **記録は「読むもの」ではなく「次の出題を変えるもの」にした。** 苦手キーを数えるだけなら表示で終わるが、
  重みに使えば練習が変わる。「遊んだ結果を次に返す」のが完成形の条件
- **平均ではなく中央値。** 「いつもの速さ」に平均を使うと、1 回の大当たり（や大外れ）に引きずられる
- **記録するのは 1 回に 1 度。** `recorded` を持たないと、画面を描き直すたびに行が増える
- **壊れた記録は空から。** `parse()` が例外を握って `History()` を返す。記録が読めなくて遊べない、を作らない
- 最後の段階では「つぎの段階へ」ではなく「もう一度（にがてなキー）」と出す。行き先が無いのに「つぎ」と言わない
