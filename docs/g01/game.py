"""数当てゲーム（ブラウザ版）

CLI 版（g01-number-guess/main.py）と同じルールだが、while ループがない。
ブラウザでは「入力を待つ」ことができないので、
状態を変数に持ち、ボタンが押されるたびに1手だけ進める形にしている。
"""

import random

from pyscript import document, when

LIMIT = 7  # 1ゲームで挑戦できる回数

# --- ゲームの状態（CLI版ではローカル変数だったもの）---
answer = 0
count = 0
playing = False

# --- 画面の部品 ---
guess_input = document.querySelector("#guess")
guess_button = document.querySelector("#guess-btn")
again_button = document.querySelector("#again-btn")
log_area = document.querySelector("#log")
remaining_label = document.querySelector("#remaining")


def show(message, kind="info"):
    """ログに1行足す。kind で色が変わる。"""
    line = document.createElement("p")
    line.className = f"line {kind}"
    line.textContent = message
    log_area.appendChild(line)
    log_area.scrollTop = log_area.scrollHeight


def update_remaining():
    remaining_label.textContent = f"残り {LIMIT - count} 回"


def finish(message, kind):
    """1ゲーム終了。入力を閉じて「もう一度」を出す。"""
    global playing
    playing = False
    show(message, kind)
    guess_input.disabled = True
    guess_button.disabled = True
    again_button.hidden = False
    again_button.focus()


def start_game():
    """CLI版の外側 while ループ1周ぶんに相当する。"""
    global answer, count, playing
    answer = random.randint(1, 100)
    count = 0
    playing = True

    log_area.innerHTML = ""
    show("1〜100 の数字を当ててください。チャンスは 7 回です。")
    update_remaining()

    guess_input.disabled = False
    guess_button.disabled = False
    guess_input.value = ""
    again_button.hidden = True
    guess_input.focus()


def submit_guess():
    """CLI版の内側 while ループ1周ぶんに相当する。"""
    global count

    if not playing:
        return

    raw = guess_input.value.strip()
    guess_input.value = ""
    guess_input.focus()

    # CLI版の try / except ValueError と同じ役割
    try:
        guess = int(raw)
    except ValueError:
        show("数字を入力してください", "warn")
        return

    # CLI版の範囲チェックと同じ
    if guess < 1 or guess > 100:
        show("1〜100 の数字にしてください", "warn")
        return

    count += 1
    update_remaining()

    if guess < answer:
        show(f"{guess} → もっと大きい")
    elif guess > answer:
        show(f"{guess} → もっと小さい")
    else:
        finish(f"正解！ {count} 回でした 🎉", "win")
        return

    # CLI版では while の条件だったもの
    if count >= LIMIT:
        finish(f"残念！ 答えは {answer} でした", "lose")


@when("click", "#guess-btn")
def on_guess_click(event):
    submit_guess()


@when("keydown", "#guess")
def on_guess_key(event):
    if event.key == "Enter":
        submit_guess()


@when("click", "#again-btn")
def on_again_click(event):
    start_game()


# Pyodide の読み込みが終わってから実行される＝ここが準備完了の合図
document.querySelector("#loading").hidden = True
start_game()
