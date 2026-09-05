"""シューティング2 — 完成: 状態を class Game にまとめる。"""

import os
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
    """自機。位置と見た目は親から受け継ぐ。"""

    def __init__(self, x, y):
        super().__init__(x, y, "A")

    def move(self, dx):
        """左右に動く。画面の外へは出ない。"""
        new_x = self.x + dx
        if 0 <= new_x < WIDTH:
            self.x = new_x

    def shoot(self):
        """自分の1つ上に弾を1発つくって返す。"""
        return Bullet(self.x, self.y - 1)


class Bullet(Entity):
    """自機が撃った弾。まっすぐ上へ飛ぶ。"""

    def __init__(self, x, y):
        super().__init__(x, y, "|")

    def update(self):
        """1段ぶん上へ進む。"""
        self.y -= 1

    def alive(self):
        """まだ画面の中にいるなら True。"""
        return 0 <= self.y < HEIGHT


class Enemy(Entity):
    """敵。編隊でそろって横に動く。1発で落ちる。"""

    def __init__(self, x, y, mark="*"):
        super().__init__(x, y, mark)

    def update(self, dx, dy):
        """横に dx、下に dy だけ動く。"""
        self.x += dx
        self.y += dy

    def take_hit(self):
        """弾を1発受ける。落ちたなら True。"""
        return True


class ToughEnemy(Enemy):
    """固い敵。2発当てないと落ちない。"""

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


def make_enemies():
    """敵を3行ぶん並べる。いちばん上の行だけ固い敵。"""
    enemies = [ToughEnemy(x, 1) for x in range(4, 17, 2)]
    enemies += [Enemy(x, y) for y in (3, 5) for x in range(4, 17, 2)]
    return enemies


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


def collide(bullets, enemies):
    """当たった弾を消し、落ちた敵を取り除いて、新しい2つのリストと撃破数を返す。"""
    live_bullets = []
    live_enemies = list(enemies)

    for bullet in bullets:
        hit = None

        for enemy in live_enemies:
            if bullet.hits(enemy):
                hit = enemy
                break

        if hit is None:
            live_bullets.append(bullet)
        elif hit.take_hit():
            live_enemies.remove(hit)

    return live_bullets, live_enemies, len(enemies) - len(live_enemies)


class Game:                                # ← 追加。ゲームの状態ぜんぶ
    """自機・弾・敵と、勝敗や記録をまとめて持つ。時間を1こまずつ進める。"""

    def __init__(self):
        self.ship = Ship(WIDTH // 2, HEIGHT - 1)
        self.bullets = []
        self.enemies = make_enemies()
        self.total = len(self.enemies)
        self.direction = 1
        self.cooldown = ENEMY_MOVE_TICKS
        self.shots = 0
        self.downed = 0
        self.result = None                 # ← None のあいだは勝負がついていない

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

    def update(self):
        """時間を1こま進める。"""
        for bullet in self.bullets:
            bullet.update()

        self.cooldown -= 1
        if self.cooldown <= 0:
            self.direction = move_enemies(self.enemies, self.direction)
            self.cooldown = move_interval(self.enemies, self.total)

        self.bullets = [b for b in self.bullets if b.alive()]
        self.bullets, self.enemies, down_count = collide(self.bullets, self.enemies)
        self.downed += down_count

        if not self.enemies:
            self.result = "clear"
        elif max(enemy.y for enemy in self.enemies) >= self.ship.y:
            self.result = "over"

    def accuracy(self):
        """撃った弾に対する撃破の割合。1発も撃っていなければ 0。"""
        return self.downed / self.shots * 100 if self.shots else 0.0

    def render(self):
        """盤面を1つの文字列にして返す。print はしない。"""
        rows = [["."] * WIDTH for _ in range(HEIGHT)]

        for entity in self.enemies + self.bullets + [self.ship]:
            rows[entity.y][entity.x] = entity.mark

        lines = ["+" + "-" * WIDTH + "+"]
        for row in rows:
            lines.append("|" + "".join(row) + "|")
        lines.append("+" + "-" * WIDTH + "+")
        return "\n".join(lines)

    def draw(self, elapsed):               # ← 引数が4つから1つに減った
        """カーソルを左上に戻して、画面ぜんぶを一度に書く。"""
        frame = self.render()
        frame += f"\n残り {len(self.enemies):2d} 体   弾 {len(self.bullets)}/{MAX_BULLETS}   {elapsed:5.1f} 秒"
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


game = Game()                              # ← 変数8個が、これ1つになった

fd = sys.stdin.fileno()
saved = termios.tcgetattr(fd)

try:
    tty.setcbreak(fd)
    print("\x1b[2J", end="")
    start_time = time.time()
    next_tick = start_time + TICK_SECONDS

    while not game.over():                 # ← break を並べる代わりに、条件で回す
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
    print(f"クリア！  {elapsed:.1f} 秒")
elif game.result == "over":
    print(f"やられた。  残り {len(game.enemies)} 体")
else:
    print(f"中断。  残り {len(game.enemies)} 体")

print(f"撃った弾 {game.shots} 発 / 撃破 {game.downed} 体 / 命中率 {game.accuracy():.1f}%")
