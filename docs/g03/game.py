"""タイピングゲーム（ブラウザ版）

CLI 版（g03-typing/main.py）と出題も集計も同じ。
summarize() は 1 文字も変えずにそのまま持ってきている。
違うのは入口と出口だけで、input() の代わりに入力欄、print() の代わりに HTML を使う。
"""

import random
import time

from pyscript import document, when

texts = [  # CLI 版と同じ出題
    "hello world",
    "python is fun",
    "keep it simple",
    "practice makes perfect",
    "the quick brown fox",
]


def summarize(results):
    """結果のリストを集計して辞書で返す。CLI 版と同じ関数。"""
    correct = 0
    chars = 0
    seconds = 0.0

    for r in results:
        if r["ok"]:
            correct += 1
            chars += len(r["text"])
            seconds += r["seconds"]

    return {"total": len(results), "correct": correct, "chars": chars, "seconds": seconds}


# --- 画面の部品 ---
target_area = document.querySelector("#target")
answer_box = document.querySelector("#answer")
log_area = document.querySelector("#log")
progress_label = document.querySelector("#progress")
start_button = document.querySelector("#start-btn")

# CLI 版では for が持っていた「今どこまで進んだか」を、辞書で持つ。
# ボタンやキー入力から呼ばれるたびに中断・再開するため、ループにはできない。
state = {"queue": [], "results": [], "start": 0.0}


def show(message, kind="info"):
    """ログに1行足す。kind で色が変わる。CLI 版の print にあたる。"""
    line = document.createElement("p")
    line.className = f"line {kind}"
    line.textContent = message
    log_area.appendChild(line)
    log_area.scrollTop = log_area.scrollHeight


def update_progress():
    done = len(state["results"])
    progress_label.textContent = f"{done} / {len(texts)} 問"


def ask():
    """次の問題を出す。CLI 版の for が1周する瞬間にあたる。"""
    if not state["queue"]:
        finish()
        return

    text = state["queue"].pop(0)  # 先頭から1つ取り出す
    target_area.textContent = text
    target_area.classList.remove("waiting")
    answer_box.value = ""
    answer_box.disabled = False
    answer_box.focus()
    state["start"] = time.time()  # ← 問題を出した瞬間から測り始める


def answer(typed):
    """1問ぶんの判定。CLI 版の for の中身と同じことをしている。"""
    seconds = time.time() - state["start"]
    text = target_area.textContent
    ok = typed == text

    state["results"].append({"text": text, "ok": ok, "seconds": seconds})
    update_progress()

    if ok:
        show(f"OK （{seconds:.1f}秒） {text}", "ok")
    else:
        show(f"ミス（{text} でした）", "miss")

    ask()


def finish():
    """全問終わったあとの成績表示。CLI 版の最後の print にあたる。"""
    score = summarize(state["results"])

    target_area.textContent = "おつかれさまでした"
    target_area.classList.add("waiting")
    answer_box.value = ""
    answer_box.disabled = True

    show(f"{score['total']}問中 {score['correct']}問 正解", "result")
    if score["correct"] == 0:
        show("次は速さより正確さを狙ってみましょう")
    else:
        show(f"速さ: {score['chars'] / score['seconds']:.1f} 文字/秒", "result")

    start_button.textContent = "もう一度"
    start_button.disabled = False


def start():
    state["queue"] = list(texts)  # コピーを並べ替える（texts 自体は元の順のまま）
    random.shuffle(state["queue"])
    state["results"] = []

    log_area.innerHTML = ""
    show("表示された文章をそのまま打って Enter")
    update_progress()

    start_button.disabled = True
    ask()


@when("click", "#start-btn")
def on_start_click(event):
    start()


@when("keydown", "#answer")
def on_answer_key(event):
    """Enter が CLI 版の input() の Enter にあたる。"""
    if event.key == "Enter":
        answer(answer_box.value.strip())  # CLI 版と同じく前後の空白は落とす


# Pyodide の読み込みが終わってから実行される＝ここが準備完了の合図
document.querySelector("#loading").hidden = True
start_button.disabled = False
update_progress()
show("スタートを押すと始まります")
