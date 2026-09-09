# g75 耳コピ3（面と記録と合言葉）

耳コピ 3 段階の**完成形**（[g73](../g73-ear-piano/) → [g74](../g74-ear-rhythm/) → g75）。
47 曲が **4 つの面**に分かれ、遊んだ結果が**日時つきの記録**に残る。そして
**自分で作った旋律を「合言葉」にして持ち帰れる**——短い文字列を渡せば、
相手の画面にも同じ旋律が出題される。

**ブラウザ版**: https://hicocho.github.io/python-study/g75/

```bash
python3 main.py                        # 遊ぶ
python3 main.py --check                # 決まりを確かめる
python3 main.py --word AEIS-CKJ2-TI    # 合言葉から旋律を読む
```

## 今回の主題

**1. 中身を、人が打てる短い字にする — `base64.b32encode` と `hashlib.blake2s`**

```python
def to_word(notes: list[tuple[int, int]]) -> str:
    data = bytes((note << 3) | LENGTHS.index(length) for note, length in notes)
    body = base64.b32encode(data + check_byte(data)).decode().rstrip("=")
    return "-".join(body[i:i + 4] for i in range(0, len(body), 4))


def check_byte(data: bytes) -> bytes:
    """打ち間違いを見つけるための 1 バイト。中身が 1 bit 違えば必ず変わる。"""
    return hashlib.blake2s(data, digest_size=1).digest()
```

1 音を 1 バイトに詰める（高さ 0〜24 が上 5 bit、長さの番号が下 3 bit）。
**base32 は 0/O や 1/I を使わない**ので、書き写しても間違えにくい。
うしろに 1 バイト足しておくと、打ち間違いをその場で見つけられる——**測ったら 99.6%**。

読むときは、もう 1 つ決まりを足す。

```python
    if base64.b32encode(raw).decode().rstrip("=") != body:
        raise BadWord("打ち間違いがあります")        # 書き直したら別の字になる＝どこか違う
```

base32 は末尾に余りビットが出るので、そこを変えられても復号は通ってしまう。
**「読み戻して書き直したら同じ字になるはず」**を足したら、見つける割合が 95.4% → 99.6% になった。

**2. 動かす場所によって使えるものが違う — `zoneinfo`**

```python
def japan() -> timezone | ZoneInfo:
    """zoneinfo は「地域の名前」で時刻を扱う道具だが、地域の時刻表そのものは
    動かす場所が持っている。ブラウザの Python（Pyodide）には入っていない。"""
    try:
        return ZoneInfo("Asia/Tokyo")
    except ZoneInfoNotFoundError:
        return timezone(timedelta(hours=9), "JST")
```

`datetime.now()` だけだと、動かした機械の設定しだいで別の時刻が残る。
場所を決めておけば、端末でもブラウザでも同じ時刻になる。

**3. 最近の N 件 — `OrderedDict.move_to_end`**

```python
        if word in self.kept:
            self.kept.move_to_end(word)
        else:
            self.kept[word] = notes
            while len(self.kept) > KEEP:
                self.kept.popitem(last=False)
```

「入れた順を覚えている辞書」に、末尾へ送る `move_to_end` と、先頭を捨てる
`popitem(last=False)` を足すだけで「最近の N 件」になる。

**4. 入れ子をほどく — `itertools.chain.from_iterable`**

```python
ORDER = tuple(chain.from_iterable(stage.songs for stage in STAGES))
```

面をつなげると、もとの曲の並びにそのまま戻る。`--check` が
`ORDER == tuple(range(47))` を見ているので、**面の切り方に穴（抜けや重なり）が無いことが
1 行で確かめられる**。

## 遊び方

```
 白鍵  z x c v b n m   q w e r t y u i     ← 本物のピアノと同じ並び
 黒鍵   s d   g h j     2 3   5 6 7

 スペース  お題を聞く（クリアしたら次の曲へ）
 リターン  答え合わせ／つくるモードでは合言葉にする
 BS        1 つ消す
 , .       いま打ち込んだ音の長さを短く／長く
 1         つくるモードに入る／出る
 0         合言葉を打ち込む
 Esc       やめる
```

**つくるモード**は鍵盤 25 鍵ぜんぶが見える（どこに置いたか分からないと作れない）。
3 音以上でリターンを押すと合言葉が出る。

## 面

| 面 | 曲 | 音色 |
|---|---|---|
| すきとおる音 | 1〜12 | サイン |
| 笛のような音 | 13〜24 | 三角 |
| オルガンの音 | 25〜36 | 倍音を重ねた音 |
| ざらついた音 | 37〜47 | のこぎり |

曲は音の幅がせまい順に並んでいるので、**「音の幅」と「音色」の 2 つが同時に進む**。

## 仕様

- 合言葉は 16〜32 字。4 字ごとに `-` を入れる。小文字・空白でも読める
- 記録は「いつ・どの曲・どの面・星いくつ」。端末は `main.py` の隣の `records.json`、
  ブラウザは `localStorage`。**中身の形は同じ**
- 覚えておく合言葉は 8 件まで。入れ直すといちばん新しい扱いになる
- `--check` が見るもの: 面をほどくともとの並びに戻るか／47 曲すべて合言葉を往復できるか／
  **1 字の書き間違いを見つける割合**／空・使えない字・短すぎるものを断るか／
  古い合言葉から消えるか／記録の時刻／**つくって合言葉にして別の Game で遊ぶまで**

## メモ

- **`obey()` が 3 つに分かれた。** あそぶ・つくる・合言葉を打つ、で見るキーがまるで違う。
  1 つの関数に `if` を積むより、**まずモードで振り分けて、そのあとで鍵の話をする**方が読める
- **チェックの 1 バイトだけでは足りなかった。** base32 の末尾には余りビットがあるので、
  そこを変えられても復号が通る。**「書き直したら同じ字になるはず」**を足して 99.6% に
- **同じ標準ライブラリでも、動く場所によって使える範囲が違う。** `zoneinfo` は
  ブラウザの Python では地域の時刻表が無くて落ちる。**外部パッケージを足さず、
  無いときの代わりを自分で書いた**（日本には夏時間が無いので、出る時刻は同じ）
- **`.pad two` のボタンが効いていなかった。** `@when("click", "#pad button")` は
  `#pad` の中しか見ない。g74 の「短く／長く」も動いていなかったので、
  `.pad button` に直して両方を修理した。**2 つ目の入れ物を足したら、選び方も見直す**
- **つくるモードは鍵盤 25 鍵ぶんを映す。** あそぶときの窓（13 半音）だと、
  作った音が窓の外に出て見えなくなる
