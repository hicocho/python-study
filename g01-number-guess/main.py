"""数当てゲーム — 1〜100 のランダムな数字を 7 回以内に当てる。"""

import random

limit = 7  # 1ゲームで挑戦できる回数

while True:
    answer = random.randint(1, 100)
    count = 0

    while count < limit:
        remaining = limit - count
        try:
            guess = int(input(f"1〜100の数字を入力（残り{remaining}回）: "))
        except ValueError:
            print("数字を入力してください")
            continue

        if guess < 1 or guess > 100:
            print("1〜100の数字にしてください")
            continue

        count += 1

        if guess < answer:
            print("もっと大きい")
        elif guess > answer:
            print("もっと小さい")
        else:
            print(f"正解！ {count}回でした")
            break
    else:
        # while が break されずに終わった＝回数を使い切った
        print(f"残念！ 答えは {answer} でした")

    again = input("もう一度？ (y/n): ").strip().lower()
    if again != "y":
        print("またね！")
        break
