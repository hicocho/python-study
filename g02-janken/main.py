"""じゃんけん — g / c / p のキーで手を出し、最後に戦績を出す。"""

import random

keys = {"g": "グー", "c": "チョキ", "p": "パー"}  # 入力キー → 手 の変換表
hands = list(keys.values())
beats = {"グー": "チョキ", "チョキ": "パー", "パー": "グー"}  # その手が倒せる相手


def judge(you, cpu):
    """勝敗を "win" / "lose" / "draw" のどれかで返す。"""
    if you == cpu:
        return "draw"
    elif beats[you] == cpu:
        return "win"
    else:
        return "lose"


score = {"win": 0, "lose": 0, "draw": 0}

print("じゃんけん！")
print("  g … グー")
print("  c … チョキ")
print("  p … パー")
print("  q … やめる")

while True:
    key = input("\nどれにする? (g/c/p/q): ").strip().lower()

    if key == "q":
        break

    # キーさえ正しければ、変換後の手は必ず正しい
    if key not in keys:
        print("g / c / p のどれかを入力してください")
        continue

    you = keys[key]
    cpu = random.choice(hands)
    print(f"あなた: {you}　コンピュータ: {cpu}")

    result = judge(you, cpu)
    score[result] += 1

    if result == "win":
        print("あなたの勝ち！")
    elif result == "lose":
        print("あなたの負け…")
    else:
        print("あいこ")

total = score["win"] + score["lose"] + score["draw"]

if total == 0:
    print("\n一度も勝負しませんでした。またどうぞ")
else:
    print(f"\n{total}回勝負 — {score['win']}勝 {score['lose']}敗 {score['draw']}分")
