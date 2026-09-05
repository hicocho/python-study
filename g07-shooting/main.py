"""シューティング — ステップ5: 全部落としたらクリア。"""

import os
import select
import sys
import termios
import time
import tty

WIDTH = 21
HEIGHT = 12
TICK_SECONDS = 0.08
MAX_BULLETS = 3       # ← 追加。画面に同時に出せる弾の数

ARROWS = {
    "\x1b[A": "up",
    "\x1b[B": "down",
    "\x1b[C": "right",
    "\x1b[D": "left",
}


class Ship:
    """自機。位置と見た目を自分で持つ。"""

    def __init__(self, x, y):
        self.x = x
        self.y = y
        self.mark = "A"

    def move(self, dx):
        """左右に動く。画面の外へは出ない。"""
        new_x = self.x + dx
        if 0 <= new_x < WIDTH:
            self.x = new_x

    def shoot(self):                 # ← 追加。自機が弾を作る
        """自分の1つ上に弾を1発つくって返す。"""
        return Bullet(self.x, self.y - 1)


class Bullet:
    """自機が撃った弾。まっすぐ上へ飛ぶ。"""

    def __init__(self, x, y):
        self.x = x
        self.y = y
        self.mark = "|"

    def update(self):
        """1段ぶん上へ進む。"""
        self.y -= 1

    def alive(self):
        """まだ画面の中にいるなら True。"""
        return 0 <= self.y < HEIGHT

    def hits(self, other):
        """相手と同じマスにいるなら True。"""
        return self.x == other.x and self.y == other.y


class Target:
    """撃ち落とす的。その場から動かない。"""

    def __init__(self, x, y):
        self.x = x
        self.y = y
        self.mark = "*"


def make_targets():
    """的を2列ぶん並べて、リストにして返す。"""
    return [Target(x, y) for y in (1, 3) for x in range(2, WIDTH - 1, 2)]


def collide(bullets, targets):
    """当たった弾と的を取り除いて、新しい2つのリストと命中数を返す。"""
    live_bullets = []
    live_targets = list(targets)

    for bullet in bullets:
        hit = None

        for target in live_targets:
            if bullet.hits(target):
                hit = target
                break

        if hit is None:
            live_bullets.append(bullet)
        else:
            live_targets.remove(hit)

    return live_bullets, live_targets, len(targets) - len(live_targets)   # ← 減った数＝命中数


def render(ship, bullets, targets):
    """盤面を1つの文字列にして返す。print はしない。"""
    rows = [["."] * WIDTH for _ in range(HEIGHT)]

    for target in targets:
        rows[target.y][target.x] = target.mark

    for bullet in bullets:
        rows[bullet.y][bullet.x] = bullet.mark

    rows[ship.y][ship.x] = ship.mark

    lines = ["+" + "-" * WIDTH + "+"]
    for row in rows:
        lines.append("|" + "".join(row) + "|")
    lines.append("+" + "-" * WIDTH + "+")
    return "\n".join(lines)


def draw(ship, bullets, targets, elapsed):    # ← 経過時間が増えた
    """カーソルを左上に戻して、画面ぜんぶを一度に書く。"""
    frame = render(ship, bullets, targets)
    frame += f"\n残り {len(targets):2d} 個   弾 {len(bullets)}/{MAX_BULLETS}   {elapsed:5.1f} 秒"
    frame += "\n← → 移動 / スペース 発射 / q やめる"

    sys.stdout.write("\x1b[H" + frame)
    sys.stdout.flush()


def read_key(timeout):
    """timeout 秒だけキーを待つ。何も押されなければ None を返す。"""
    fd = sys.stdin.fileno()

    ready, _, _ = select.select([fd], [], [], timeout)
    if not ready:
        return None

    key = os.read(fd, 3).decode(errors="ignore")
    return ARROWS.get(key, key)


ship = Ship(WIDTH // 2, HEIGHT - 1)
bullets = []
targets = make_targets()
shots = 0             # ← 追加。撃った弾の数
hits = 0              # ← 追加。当てた弾の数
cleared = False       # ← 追加

fd = sys.stdin.fileno()
saved = termios.tcgetattr(fd)

try:
    tty.setcbreak(fd)
    print("\x1b[2J", end="")
    start_time = time.time()                  # ← 追加
    next_tick = start_time + TICK_SECONDS

    while True:
        draw(ship, bullets, targets, time.time() - start_time)

        key = read_key(max(next_tick - time.time(), 0))

        if key == "q":
            break
        elif key == "left":
            ship.move(-1)
        elif key == "right":
            ship.move(1)
        elif key == " ":
            if len(bullets) < MAX_BULLETS:    # ← 撃てるのは3発まで
                bullets.append(ship.shoot())  # ← 弾の作り方は自機が知っている
                shots += 1

        if time.time() >= next_tick:
            for bullet in bullets:
                bullet.update()

            bullets = [b for b in bullets if b.alive()]
            bullets, targets, hit_count = collide(bullets, targets)
            hits += hit_count                 # ← 命中を数える

            if not targets:                   # ← 全部落としたら終わり
                cleared = True
                break

            next_tick = time.time() + TICK_SECONDS
finally:
    termios.tcsetattr(fd, termios.TCSADRAIN, saved)

elapsed = time.time() - start_time
accuracy = hits / shots * 100 if shots else 0.0   # ← 1発も撃たなければ 0%

print("\x1b[2J\x1b[H", end="")
print(render(ship, bullets, targets))

if cleared:
    print(f"クリア！  {elapsed:.1f} 秒")
else:
    print(f"中断。  残り {len(targets)} 個")

print(f"撃った弾 {shots} 発 / 命中 {hits} 発 / 命中率 {accuracy:.1f}%")
