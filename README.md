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
