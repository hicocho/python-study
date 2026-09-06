---
name: gnn
description: python-study の新しい課題（gNN）を、ゲーム名を渡すだけで最後まで自動で作る。フォルダ作成 → 覚える文法の設計 → 4〜5 ステップの CLI 版 → ブラウザ版（PyScript）→ 検証 → README → push → Notion に学習記録を保存、までを止まらずに実行する。「g11 を作って」「次の課題は◯◯」「gNN を作成」と言われたら使う。
---

# gNN — 1 課題をまるごと作る

`/gnn <ゲーム名>` で、課題フォルダから公開・Notion 記録までを **一度も止まらずに**やり切る。

ゲーム名だけが引数。番号・日付・覚える文法・ステップの割り方はこちらで決める。
**途中で確認を取らない。** 報告は最後に 1 回。

ゲーム名が渡されなかったときだけ、「今回覚える文法」で候補を 3〜4 個出して選んでもらう
（ゲーム名ではなく文法で並べる。例: 「再帰と集合＝マインスイーパ／BFS＝迷路／class＝15パズル」）。
選ばれたらそのまま最後まで走る。

## このリポジトリの決まりごと

- 1 課題 = 1 フォルダ。`gNN-<英小文字スラグ>/main.py` と `README.md`
- **標準ライブラリのみ**。CLI 版に外部パッケージを入れない（検証用の playwright は scratchpad に置く）
- 判定ロジックは `print` せず値を返す関数にする。CLI 版とブラウザ版で同じ関数を使い回すため
- 状態は `class Game` にまとめる。`input` と `print` は `Game` の外に置く
- 公開 URL は `https://hicocho.github.io/python-study/gNN/`
- コミットは 2 本。`gNN: 〜を追加`（課題フォルダ＋ルート README）と
  `docs: ブラウザ版の〜を追加（/gNN/）`（docs 一式）

## 手順

### 1. 下ごしらえ

```bash
ls -d g??-* | sort | tail -1          # 次の番号を決める
date +%Y%m%d                          # Notion ページ名に使う
```

`mkdir gNN-<slug>` と空の `main.py`。スラグは英小文字（`gomoku`、`invaders`）。
Notion のページ名も `YYYYMMDD-gNN-<slug>` とこのスラグで揃える。

### 2. 今回覚える文法を設計して 4〜5 ステップに割る

**題材ではなく文法で切る。** g01〜の「扱った文法」列（ルート `README.md`）を読み、
**まだ出ていない文法**を 3 つほど選んでから、それが自然に要る形にステップを並べる。
5 ステップが収まりがいい。ステップ 1 は既習の復習＋新顔 1 つ、最後のステップで `class Game` に畳む。

大きい題材は 1 課題に詰め込まず、連作にしてもよい（g07→g08→g09 がスペースインベーダーの 3 段階）。

### 3. CLI 版を 5 ステップぶん書く

各ステップで:

1. scratchpad に `stepN.py` として書き、**そこで検証する**（構文・総当たり・シナリオ入力）
2. 通ったら `main.py` へ反映する（`cp` でよい）
3. そのステップで変わった行に `# ←` を付ける。**前のステップの印は消す**

`stepN.py` は Notion に載せるので消さない。ステップごとに「読みどころ」も書き溜めておく
（文法の要点と、なぜその行がその位置なのかという設計判断。1 ステップ 4〜6 個）。

リアルタイム系（毎秒 10 回以上描き替える）は `\x1b[H` でカーソルを戻して上書きし、
`sys.stdout.write` を 1 回だけ呼ぶ。表示は `{x:5.1f}` と桁を固定する（`\x1b[2J` はちらつく）。

### 4. 盤面プレビューで見た目を決める

実装前に静的な HTML を書き、案を 3〜4 個並べて `scripts/shot.js` で撮り、自分で選ぶ。
ライトとダークの両方を撮る。ゲームを動かさずに決められるものは、ここで決めておく。

### 5. ブラウザ版 `docs/gNN/`

`index.html` の CSS・レイアウトは g01/g02 から続く形に揃える
（配色変数、カード、`← 課題一覧`、`#loading`、フッターの 3 リンク）。

`game.py` の共有部分は**手で写さず切り出す**:

```bash
python3 .claude/skills/gnn/scripts/extract_shared.py gNN-<slug>/main.py \
    --names 'SIZE+GOAL,EMPTY+BLACK+WHITE,DIRECTIONS,make_board,...,Game' \
    --drop-methods render,draw > $SCRATCH/shared.py
```

ヘッダ（docstring と import 群）とブラウザ層（DOM 描画・イベント）だけを手で書き、
`cat header.py shared.py footer.py > docs/gNN/game.py` で組み立てる。
**組み立て直したら必ず、同じコマンドの出力が `game.py` に部分文字列として含まれるか確かめる。**

`docs/index.html` の課題一覧にカードを 1 枚足す（既存カードと同じ形。タグは覚えた文法 4 つ）。

### 6. 検証は 3 つに分ける

ブラウザで新しく確かめるべきなのは**結線だけ**。順に潰す。

| 対象 | やり方 |
|---|---|
| ルール | 判定関数を独立実装（総当たり）と数百局突き合わせる |
| 状態 | `undo` などは、操作前後の全フィールドを `deepcopy` と比較して完全一致を見る |
| 強さ・テンポ | CPU 同士を数十局。決着するか、平均手数、1 局あたりの秒数 |
| 移植 | **同じ乱数の種**で CLI 版と `docs/gNN/game.py` を自動対局させ、棋譜が一致するか |
| import 漏れ | `python3 .claude/skills/gnn/scripts/check_names.py docs/gNN/game.py` |
| 結線 | `python3 -m http.server` + Playwright でクリック・キー・終局・再開・携帯幅 |

ロジックだけ動かしたいときは、`game.py` をブラウザ層の手前で切って `exec()` する
（`pyscript` は `sys.modules` にダミーを入れれば import が通る）。

Playwright は scratchpad に置いて既存の Chrome を使う:

```bash
cd $SCRATCH && PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm install --no-save playwright
node .claude/skills/gnn/scripts/shot.js http://localhost:8910/gNN/ $SCRATCH/web.png light 480
```

確認できたらサーバーとブラウザは閉じる。

### 7. README は最後

動くものが全部揃ってから文章にする（先に書くと、実機で直したときに書き直しになる）。

- `gNN-<slug>/README.md` — 概要 / 今回の主題 3 つ / ブラウザ版 / 遊び方（端末の画面例つき）/ 仕様 / メモ
  - 「メモ」は**設計判断の記録**。文法の説明だけでなく「なぜその形にしたか」を書く
  - CLI とブラウザで変わる部分は「違うのは入口と出口だけ」の形で明示する
- ルート `README.md` の課題一覧テーブルに 1 行（「扱った文法」列がその課題の学習記録）

### 8. commit 2 本と push、公開の確認

push したら 45 秒ほど待って `https://hicocho.github.io/python-study/gNN/` を実機で開き、
1 手動かしてエラーが無いことまで見る。

### 9. Notion に学習記録を保存（最後に一括で 1 回）

親は「🎗️ Python」ページ = `3ccecd59-0c9a-8003-b914-d8c98da32c3b`。
その配下に **`YYYYMMDD-gNN-<slug>`** という子ページを作る（`notion-create-pages` の `parent.page_id`）。

**書く前に `notion-fetch` で `notion://docs/enhanced-markdown-spec` を読む。**
手貼りだとコードブロックが `<br>` に崩れる（g10 のステップ2 が実例）。崩さないために、
コードは必ず ```python のフェンスに入れ、生成した文字列をそのまま渡す。

ページの構成:

1. **今回覚える文法**の表（ステップ / 作るもの / 覚える文法）と目次
2. ステップごとに `## ステップN：…` → コード全文（```python）→ `### 読みどころ`
3. **検証結果**の表（何をどう確かめて、どうだったか）
4. 端末の画面例（```text）とブラウザ版のスクショ、公開 URL と GitHub リンク

スクショは `notion-create-file-upload` → `curl` で multipart POST → 返ってきた
`markdown_source` をページ本文に埋める。

1 回の `create-pages` で通らない大きさなら、ページを作ってから
`notion-update-page` の `insert_content`（`position: end`）でステップごとに足す。
**分割は API の都合。Hicoさんへの確認は挟まない。**

## 最後の報告

- 公開 URL と Notion ページの URL
- 覚えた文法（表）
- 検証結果（何を何回、どうだったか）
- 途中で見つけて直した問題

## やらないこと

- 途中でゲームの仕様や見た目を相談しない（自分で決めて、決めた理由を報告に書く）
- CLI 版に外部パッケージを足さない
- `docs/` に手書きの重複コードを置かない（共有部分は必ず切り出す）
