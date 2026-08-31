"""じゃんけん（ブラウザ版）

CLI 版（g02-janken/main.py）とルールも判定も同じ。
judge() は 1 文字も変えずにそのまま持ってきている。
違うのは入口と出口だけで、input() の代わりにボタン、print() の代わりに HTML を使う。
"""

import random

from pyscript import document, when

keys = {"g": "グー", "c": "チョキ", "p": "パー"}  # 入力キー → 手 の変換表
hands = list(keys.values())
beats = {"グー": "チョキ", "チョキ": "パー", "パー": "グー"}  # その手が倒せる相手
emoji = {"グー": "✊", "チョキ": "✌️", "パー": "🖐"}  # 表示用（CLI 版にはない）


def judge(you, cpu):
    """勝敗を "win" / "lose" / "draw" のどれかで返す。CLI 版と同じ関数。"""
    if you == cpu:
        return "draw"
    elif beats[you] == cpu:
        return "win"
    else:
        return "lose"


score = {"win": 0, "lose": 0, "draw": 0}

# --- 画面の部品 ---
log_area = document.querySelector("#log")
score_label = document.querySelector("#score")


def show(message, kind="info"):
    """ログに1行足す。kind で色が変わる。CLI 版の print にあたる。"""
    line = document.createElement("p")
    line.className = f"line {kind}"
    line.textContent = message
    log_area.appendChild(line)
    log_area.scrollTop = log_area.scrollHeight


def update_score():
    total = score["win"] + score["lose"] + score["draw"]
    if total == 0:
        score_label.textContent = "まだ 0 回"
    else:
        score_label.textContent = (
            f"{total}回 — {score['win']}勝 {score['lose']}敗 {score['draw']}分"
        )


def play(you):
    """CLI 版の while ループ1周ぶんに相当する。"""
    cpu = random.choice(hands)
    result = judge(you, cpu)

    score[result] += 1
    update_score()

    match = f"{emoji[you]} {you}　vs　{emoji[cpu]} {cpu} → "
    if result == "win":
        show(match + "勝ち！", "win")
    elif result == "lose":
        show(match + "負け…", "lose")
    else:
        show(match + "あいこ", "draw")


def reset():
    for k in score:
        score[k] = 0
    update_score()
    log_area.innerHTML = ""
    show("戦績をリセットしました。もう一度どうぞ")


@when("click", ".hand")
def on_hand_click(event):
    button = event.target.closest(".hand")
    play(keys[button.dataset.key])  # data-key="g" → "グー"


@when("keydown", "html")
def on_key(event):
    """CLI 版と同じく g / c / p でも遊べる。"""
    key = event.key.lower()
    if key in keys:
        play(keys[key])


@when("click", "#reset-btn")
def on_reset_click(event):
    reset()


# Pyodide の読み込みが終わってから実行される＝ここが準備完了の合図
document.querySelector("#loading").hidden = True
for hand_button in document.querySelectorAll(".hand"):
    hand_button.disabled = False
document.querySelector("#reset-btn").disabled = False
update_score()
show("ボタンを押すか、キーボードの g / c / p で手を出してください")
