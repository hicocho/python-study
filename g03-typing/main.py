"""タイピングゲーム — 表示された文章をそのまま打つ。ステップ3: 成績を出して締める。"""

import random
import time

texts = [
    "hello world",
    "python is fun",
    "keep it simple",
    "practice makes perfect",
    "the quick brown fox",
]

def summarize(results):  # ← 追加。集計だけして、表示はしない
    """結果のリストを集計して辞書で返す。"""
    correct = 0
    chars = 0
    seconds = 0.0

    for r in results:
        if r["ok"]:               # ← 正解した問題だけを数える
            correct += 1
            chars += len(r["text"])
            seconds += r["seconds"]

    return {"total": len(results), "correct": correct, "chars": chars, "seconds": seconds}

print("タイピングゲーム！")
print("表示された文章をそのまま打って Enter。")

random.shuffle(texts)

results = []

for text in texts:
    print(f"\n{text}")

    start = time.time()
    typed = input("> ").strip()
    seconds = time.time() - start

    ok = typed == text
    results.append({"text": text, "ok": ok, "seconds": seconds})

    if ok:
        print(f"OK ({seconds:.1f}秒)")
    else:
        print(f"ミス（{text} でした）")

score = summarize(results)  # ← ためた記録を渡して、成績を受け取る

print("\n--- 成績 ---")  # ←
print(f"{score['total']}問中 {score['correct']}問 正解")  # ←

if score["correct"] == 0:  # ← 1問も正解がないと割り算ができない
    print("次は速さより正確さを狙ってみましょう")
else:
    print(f"速さ: {score['chars'] / score['seconds']:.1f} 文字/秒")
