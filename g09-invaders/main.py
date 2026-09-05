"""シューティング3 — 完成: ハイスコアをファイルに残す。"""

import json                                # ←
import os
import random
import select
import sys
import termios
import time
import tty

WIDTH = 21
HEIGHT = 14
TICK_SECONDS = 0.08
MAX_BULLETS = 3
ENEMY_MOVE_TICKS = 6
ENEMY_MIN_TICKS = 2
ENEMY_SHOT_CHANCE = 0.06
SHIP_LIVES = 3
BARRIER_HP = 3
CLEAR_BONUS = 100
HIGHSCORE_FILE = os.path.join(os.path.dirname(__file__), "highscore.json")   # ←

ARROWS = {
    "\x1b[A": "up",
    "\x1b[B": "down",
    "\x1b[C": "right",
    "\x1b[D": "left",
}


class Entity:
    """位置と見た目を持つもの。自機・弾・敵の共通部分。"""

    def __init__(self, x, y, mark):
        self.x = x
        self.y = y
        self.mark = mark

    def hits(self, other):
        """相手と同じマスにいるなら True。"""
        return self.x == other.x and self.y == other.y


class Ship(Entity):
    """自機。敵弾に当たると残機が減る。"""

    def __init__(self, x, y):
        super().__init__(x, y, "A")
        self.lives = SHIP_LIVES

    def move(self, dx):
        """左右に動く。画面の外へは出ない。"""
        new_x = self.x + dx
        if 0 <= new_x < WIDTH:
            self.x = new_x

    def shoot(self):
        """自分の1つ上に弾を1発つくって返す。"""
        return Bullet(self.x, self.y - 1)

    def take_hit(self):
        """敵弾を1発受ける。残機が尽きたなら True。"""
        self.lives -= 1
        return self.lives <= 0


class Bullet(Entity):
    """自機が撃った弾。まっすぐ上へ飛ぶ。"""

    def __init__(self, x, y, mark="|"):
        super().__init__(x, y, mark)

    def update(self):
        """1段ぶん上へ進む。"""
        self.y -= 1

    def alive(self):
        """まだ画面の中にいるなら True。"""
        return 0 <= self.y < HEIGHT


class EnemyBullet(Bullet):
    """敵が撃った弾。上下が逆なだけで、あとは自機の弾と同じ。"""

    def __init__(self, x, y):
        super().__init__(x, y, "!")

    def update(self):
        """1段ぶん下へ進む。"""
        self.y += 1


class Enemy(Entity):
    """敵。編隊でそろって横に動く。1発で落ちる。"""

    POINTS = 10

    def __init__(self, x, y, mark="*"):
        super().__init__(x, y, mark)

    def update(self, dx, dy):
        """横に dx、下に dy だけ動く。"""
        self.x += dx
        self.y += dy

    def shoot(self):
        """自分の1つ下に弾を1発つくって返す。"""
        return EnemyBullet(self.x, self.y + 1)

    def take_hit(self):
        """弾を1発受ける。落ちたなら True。"""
        return True


class ToughEnemy(Enemy):
    """固い敵。2発当てないと落ちない。"""

    POINTS = 30

    def __init__(self, x, y):
        super().__init__(x, y, "W")
        self.hp = 2

    def take_hit(self):
        """弾を1発受ける。体力が尽きたなら True。"""
        self.hp -= 1

        if self.hp > 0:
            self.mark = "w"
            return False

        return True


class Barrier(Entity):
    """自機を守る壁。弾を受けるたびに削れ、3発でなくなる。"""

    MARKS = ["-", "=", "#"]

    def __init__(self, x, y):
        super().__init__(x, y, "#")
        self.hp = BARRIER_HP

    def take_hit(self):
        """弾を1発受ける。なくなったなら True。"""
        self.hp -= 1

        if self.hp > 0:
            self.mark = self.MARKS[self.hp - 1]
            return False

        return True


def make_enemies():
    """敵を3行ぶん並べる。いちばん上の行だけ固い敵。"""
    enemies = [ToughEnemy(x, 1) for x in range(4, 17, 2)]
    enemies += [Enemy(x, y) for y in (3, 5) for x in range(4, 17, 2)]
    return enemies


def make_barriers():
    """バリアを3つ、自機の少し上に置く。1つは横3マス。"""
    return [Barrier(x + dx, HEIGHT - 3) for x in (3, 9, 15) for dx in range(3)]


def move_interval(enemies, total):
    """残り数に応じた、敵が動く間隔。減るほど短く（速く）なる。"""
    ratio = len(enemies) / total
    return max(ENEMY_MIN_TICKS, round(ENEMY_MOVE_TICKS * ratio))


def can_move(enemies, dx):
    """編隊ぜんぶが dx の向きへ、あと1マス動けるなら True。"""
    if dx < 0:
        return min(enemy.x for enemy in enemies) + dx >= 0
    return max(enemy.x for enemy in enemies) + dx < WIDTH


def move_enemies(enemies, direction):
    """編隊を動かす。壁に着いていたら横へは進まず、1段下げて向きを変える。"""
    if can_move(enemies, direction):
        for enemy in enemies:
            enemy.update(direction, 0)
    else:
        direction = -direction
        for enemy in enemies:
            enemy.update(0, 1)

    return direction


def front_enemies(enemies):
    """列ごとに、いちばん下にいる敵だけを返す。撃てるのはこの敵だけ。"""
    front = {}

    for enemy in enemies:
        if enemy.x not in front or enemy.y > front[enemy.x].y:
            front[enemy.x] = enemy

    return list(front.values())


def collide(bullets, targets):
    """当たった弾を消し、壊れた的を取り除いて、残った弾・残った的・壊れた的を返す。"""
    live_bullets = []
    live_targets = list(targets)
    broken = []

    for bullet in bullets:
        hit = None

        for target in live_targets:
            if bullet.hits(target):
                hit = target
                break

        if hit is None:
            live_bullets.append(bullet)
        elif hit.take_hit():
            live_targets.remove(hit)
            broken.append(hit)

    return live_bullets, live_targets, broken


def load_highscore():                      # ← 追加
    """保存してあるハイスコアを読む。まだファイルが無ければ 0。"""
    try:
        with open(HIGHSCORE_FILE, encoding="utf-8") as f:
            return json.load(f)["score"]
    except (OSError, ValueError, KeyError):
        return 0


def save_highscore(score):                 # ← 追加
    """ハイスコアをファイルに書き出す。"""
    with open(HIGHSCORE_FILE, "w", encoding="utf-8") as f:
        json.dump({"score": score}, f)


class Game:
    """自機・弾・敵と、勝敗や記録をまとめて持つ。時間を1こまずつ進める。"""

    def __init__(self, high=0):            # ← 最高得点を外から受け取る
        self.ship = Ship(WIDTH // 2, HEIGHT - 1)
        self.bullets = []
        self.enemy_bullets = []
        self.enemies = make_enemies()
        self.barriers = make_barriers()
        self.total = len(self.enemies)
        self.direction = 1
        self.cooldown = ENEMY_MOVE_TICKS
        self.shots = 0
        self.downed = 0
        self.score = 0
        self.high = high                   # ← 表示に使うだけ。読み書きはしない
        self.result = None

    def over(self):
        """勝負がついているなら True。"""
        return self.result is not None

    def quit(self):
        """やめる。"""
        self.result = "quit"

    def move_ship(self, dx):
        """自機を左右に動かす。"""
        self.ship.move(dx)

    def shoot(self):
        """撃てる残りがあれば1発撃つ。"""
        if len(self.bullets) < MAX_BULLETS:
            self.bullets.append(self.ship.shoot())
            self.shots += 1

    def enemy_shoot(self):
        """ときどき、最前列の敵が1体だけ撃ってくる。"""
        if self.enemies and random.random() < ENEMY_SHOT_CHANCE:
            shooter = random.choice(front_enemies(self.enemies))
            self.enemy_bullets.append(shooter.shoot())

    def hit_ship(self):
        """自機に当たった敵弾を消し、当たっていたら残機を1つ減らす。"""
        hits = [b for b in self.enemy_bullets if b.hits(self.ship)]
        self.enemy_bullets = [b for b in self.enemy_bullets if not b.hits(self.ship)]

        if hits and self.ship.take_hit():
            self.result = "over"

    def crush_barriers(self):
        """敵が重なったバリアは、削れる間もなく壊れる。"""
        self.barriers = [
            barrier
            for barrier in self.barriers
            if not any(enemy.hits(barrier) for enemy in self.enemies)
        ]

    def update(self):
        """時間を1こま進める。"""
        for bullet in self.bullets + self.enemy_bullets:
            bullet.update()

        self.enemy_shoot()

        self.cooldown -= 1
        if self.cooldown <= 0:
            self.direction = move_enemies(self.enemies, self.direction)
            self.cooldown = move_interval(self.enemies, self.total)
            self.crush_barriers()

        self.bullets = [b for b in self.bullets if b.alive()]
        self.enemy_bullets = [b for b in self.enemy_bullets if b.alive()]

        self.bullets, self.barriers, _ = collide(self.bullets, self.barriers)
        self.enemy_bullets, self.barriers, _ = collide(self.enemy_bullets, self.barriers)
        self.bullets, self.enemies, downed = collide(self.bullets, self.enemies)

        self.downed += len(downed)
        self.score += sum(enemy.POINTS for enemy in downed)

        self.hit_ship()

        if self.over():
            return

        if not self.enemies:
            self.score += self.ship.lives * CLEAR_BONUS
            self.result = "clear"
        elif max(enemy.y for enemy in self.enemies) >= self.ship.y:
            self.result = "over"

    def accuracy(self):
        """撃った弾に対する撃破の割合。1発も撃っていなければ 0。"""
        return self.downed / self.shots * 100 if self.shots else 0.0

    def render(self):
        """盤面を1つの文字列にして返す。print はしない。"""
        rows = [["."] * WIDTH for _ in range(HEIGHT)]

        for entity in self.enemies + self.barriers + self.bullets + self.enemy_bullets + [self.ship]:
            rows[entity.y][entity.x] = entity.mark

        lines = ["+" + "-" * WIDTH + "+"]
        for row in rows:
            lines.append("|" + "".join(row) + "|")
        lines.append("+" + "-" * WIDTH + "+")
        return "\n".join(lines)

    def draw(self, elapsed):
        """カーソルを左上に戻して、画面ぜんぶを一度に書く。"""
        frame = self.render()
        frame += f"\n残り {len(self.enemies):2d} 体   自機 {self.ship.lives}   得点 {self.score:4d}   最高 {self.high:4d}   {elapsed:5.1f} 秒"   # ←
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


game = Game(load_highscore())              # ←

fd = sys.stdin.fileno()
saved = termios.tcgetattr(fd)

try:
    tty.setcbreak(fd)
    print("\x1b[2J", end="")
    start_time = time.time()
    next_tick = start_time + TICK_SECONDS

    while not game.over():
        game.draw(time.time() - start_time)

        key = read_key(max(next_tick - time.time(), 0))

        if key == "q":
            game.quit()
        elif key == "left":
            game.move_ship(-1)
        elif key == "right":
            game.move_ship(1)
        elif key == " ":
            game.shoot()

        if time.time() >= next_tick:
            game.update()
            next_tick = time.time() + TICK_SECONDS
finally:
    termios.tcsetattr(fd, termios.TCSADRAIN, saved)

elapsed = time.time() - start_time

print("\x1b[2J\x1b[H", end="")
print(game.render())

if game.result == "clear":
    print(f"クリア！  {elapsed:.1f} 秒   ボーナス {game.ship.lives * CLEAR_BONUS} 点")
elif game.result == "over" and game.ship.lives <= 0:
    print(f"撃ち落とされた。  残り {len(game.enemies)} 体")
elif game.result == "over":
    print(f"攻め込まれた。  残り {len(game.enemies)} 体")
else:
    print(f"中断。  残り {len(game.enemies)} 体")

print(f"得点 {game.score} 点")
print(f"撃った弾 {game.shots} 発 / 撃破 {game.downed} 体 / 命中率 {game.accuracy():.1f}%")

if game.score > game.high:                 # ←
    save_highscore(game.score)
    print(f"ハイスコア更新！  {game.high} → {game.score} 点")
else:                                      # ←
    print(f"ハイスコアは {game.high} 点")
