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
