"""タイピング1（キーボードと指）

ブラインドタッチの練習。画面に JIS 配列のキーボードを描き、次に押すキーと
「どの指で押すか」を出す。ホームポジション → 上の段 → 下の段 → 数字、と段階を踏む。
正確さ 95% 以上で次の段階へ。

今回の主題は「絵を、まずデータにする」こと。キーボードは (文字, 指, 段) の表で持ち、
「いまどのキーが光るか」も表として組み立てる（keyboard_view）。端末はその表を
色つきの字に、ブラウザは同じ表を <div> に変える。**絵の中身は 1 か所で決まる。**

    python3 main.py            練習する
    python3 main.py --check    決まりを確かめる
    python3 main.py --drill 2  段階 3 の練習文を見る
"""

import random
import string
import sys
from dataclasses import dataclass, field
from enum import Enum
from statistics import fmean

PASS = 0.95                                         # 次の段階へ行ける正確さ
GROUPS = 8                                          # 1 回の練習に出す「かたまり」の数
GROUP_LEN = 4                                       # かたまり 1 つのキーの数
FRESH = 0.6                                         # 新しいキーを出す割合（残りは復習）


# ── キーボード ──────────────────────────────────────────────────────────

class Finger(Enum):
    """どの指か。値は画面に出す名前。"""

    L_PINKY = "左手 小指"
    L_RING = "左手 薬指"
    L_MIDDLE = "左手 中指"
    L_INDEX = "左手 人さし指"
    R_INDEX = "右手 人さし指"
    R_MIDDLE = "右手 中指"
    R_RING = "右手 薬指"
    R_PINKY = "右手 小指"
    THUMB = "親指"


# 列の番号 → 指。人さし指は 2 列、小指は右端まで全部
COLUMN_FINGER = (Finger.L_PINKY, Finger.L_RING, Finger.L_MIDDLE, Finger.L_INDEX, Finger.L_INDEX,
                 Finger.R_INDEX, Finger.R_INDEX, Finger.R_MIDDLE, Finger.R_RING)

# JIS 配列。段ごとの文字と、左端をどれだけずらすか（キー 1 つ = 1.0）
ROWS = (
    ("1234567890-^¥", 0.0),
    ("qwertyuiop@[", 1.5),
    ("asdfghjkl;:]", 2.0),
    ("zxcvbnm,./_", 2.5),
)
HOME = "asdfjkl;"                                   # ホームポジション。f と j に突起がある


@dataclass(frozen=True)
class Key:
    """キー 1 つ。文字・指・段・段の中の位置。"""

    char: str
    finger: Finger
    row: int
    column: int


def finger_of(column: int) -> Finger:
    """段の中の位置から指を決める。右へはみ出したぶんは全部右手の小指。"""
    return COLUMN_FINGER[column] if column < len(COLUMN_FINGER) else Finger.R_PINKY


KEYS: dict[str, Key] = {
    char: Key(char, finger_of(column), row, column)
    for row, (chars, _) in enumerate(ROWS)
    for column, char in enumerate(chars)
} | {" ": Key(" ", Finger.THUMB, 4, 0)}              # 空白は親指。表の外に 1 つだけ足す


# ── 段階 ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Stage:
    """段階。新しく覚えるキーと、名前。"""

    name: str
    fresh: str                                      # この段階で新しく出るキー

    def learned(self, index: int) -> str:
        """この段階までに出たキーぜんぶ。"""
        return "".join(stage.fresh for stage in STAGES[:index + 1])


STAGES = (
    Stage("ホームポジション", "asdfghjkl;"),
    Stage("上の段", "qwertyuiop"),
    Stage("下の段", "zxcvbnm,./"),
    Stage("数字", string.digits),
)


def drill(index: int, seed: int = 0) -> str:
    """段階 index の練習文。新しいキーを多めに、覚えたキーを混ぜる。

    乱数の種を固定してあるので、同じ段階・同じ回なら端末でもブラウザでも同じ文になる。
    かたまりの間の空白も打つ（親指の練習）。
    """
    luck = random.Random(seed * 100 + index)
    fresh, old = STAGES[index].fresh, STAGES[index].learned(index - 1) if index else ""
    groups = []
    for _ in range(GROUPS):
        keys = (luck.choice(fresh) if not old or luck.random() < FRESH else luck.choice(old)
                for _ in range(GROUP_LEN))
        groups.append("".join(keys))
    return " ".join(groups)


# ── 練習 ────────────────────────────────────────────────────────────────

@dataclass
class Game:
    """練習の状態。端末もブラウザもこれ 1 つを進める。"""

    stage: int = 0
    round: int = 0                                  # その段階で何回目か
    text: str = ""
    at: int = 0                                     # 次に打つ位置
    hits: int = 0
    misses: int = 0
    wrong: str = ""                                 # さっき間違えて押したキー
    started: float | None = None                    # 最初のキーを押した時刻
    gaps: list[float] = field(default_factory=list) # キーとキーの間隔（秒）
    last: float | None = None
    miss_by: dict[str, int] = field(default_factory=dict)   # 指ごとのミス
    done: bool = False
    passed: bool = False
    message: str = ""

    def __post_init__(self):
        if not self.text:
            self.start()

    def start(self) -> None:
        """その段階の練習文を出し、数え直す。"""
        self.text = drill(self.stage, self.round)
        self.at = 0
        self.hits = self.misses = 0
        self.wrong = ""
        self.started = self.last = None
        self.gaps = []
        self.miss_by = {}
        self.done = self.passed = False
        self.message = f"{STAGES[self.stage].name}。打ち始めると時計が動きます"

    @property
    def target(self) -> str | None:
        """次に押すキー。終わっていれば None。"""
        return self.text[self.at] if self.at < len(self.text) else None

    def press(self, char: str, now: float) -> bool:
        """キーを 1 つ受ける。合っていれば進む。違えば数えて、その場にとどまる。"""
        if self.done or self.target is None:
            return False
        if self.started is None:
            self.started = now
        elif self.last is not None:
            self.gaps.append(now - self.last)
        self.last = now
        if char == self.target:
            self.hits += 1
            self.at += 1
            self.wrong = ""
            if self.target is None:
                self.finish(now)
            return True
        self.misses += 1
        self.wrong = char
        finger = KEYS[self.target].finger.value
        self.miss_by[finger] = self.miss_by.get(finger, 0) + 1
        return False

    def accuracy(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total else 1.0

    def seconds(self, now: float | None = None) -> float:
        if self.started is None:
            return 0.0
        return ((now if now is not None else self.last) or self.started) - self.started

    def per_minute(self) -> float:
        """1 分あたりの打鍵数。間隔の平均から出す（最初の 1 打は時計が動いていない）。"""
        return 60 / fmean(self.gaps) if self.gaps else 0.0

    def finish(self, now: float) -> None:
        self.done = True
        self.passed = self.accuracy() >= PASS
        self.message = (f"合格。正確さ {self.accuracy():.0%}" if self.passed else
                        f"正確さ {self.accuracy():.0%}。{PASS:.0%} 以上でつぎへ")

    def advance(self) -> None:
        """合格なら次の段階、そうでなければ同じ段階をもう一度（別の文で）。"""
        if self.passed and self.stage + 1 < len(STAGES):
            self.stage += 1
            self.round = 0
        else:
            self.round += 1
        self.start()


def obey(game: Game, key: str, now: float) -> None:
    """キーを 1 つ受け取って練習を進める。端末もブラウザもここを通る。

    now は外から渡す。中で時計を読まないので、同じキー列と同じ時刻を与えれば
    端末でもブラウザでも同じ結果になる（検証で使う）。
    """
    if key == "enter":
        if game.done:
            game.advance()
        return
    if key == "escape":
        return
    if key in KEYS:
        game.press(key, now)


# ── 絵をデータで組む ────────────────────────────────────────────────────

def keyboard_view(game: Game) -> list[list[tuple[str, Finger, str]]]:
    """キーボードの「いまの見た目」を表にする。端末もブラウザもこれを描く。

    各キーは (文字, 指, 状態)。状態は
      "next"  次に押すキー
      "miss"  さっき間違えて押したキー
      "home"  ホームポジション
      ""      それ以外
    """
    rows = []
    for row, (chars, _) in enumerate(ROWS):
        line = []
        for char in chars:
            state = ("next" if char == game.target else
                     "miss" if char == game.wrong else
                     "home" if char in HOME else "")
            line.append((char, KEYS[char].finger, state))
        rows.append(line)
    space = ("space", Finger.THUMB,
             "next" if game.target == " " else "miss" if game.wrong == " " else "")
    rows.append([space])
    return rows


def report(game: Game) -> list[str]:
    """終わったときの成績。"""
    lines = [
        f"打鍵 {game.hits}  ミス {game.misses}  正確さ {game.accuracy():.0%}  "
        f"{game.seconds():.1f} 秒  1 分あたり {game.per_minute():.0f} 打",
    ]
    if game.miss_by:
        worst = sorted(game.miss_by.items(), key=lambda kv: -kv[1])
        lines.append("ミスの多い指: " + "  ".join(f"{name} {n}" for name, n in worst[:3]))
    return lines


# ── 端末 ────────────────────────────────────────────────────────────────

PAINT = {                                           # 指ごとの色（端末の 256 色）
    Finger.L_PINKY: 168, Finger.L_RING: 178, Finger.L_MIDDLE: 114, Finger.L_INDEX: 75,
    Finger.R_INDEX: 81, Finger.R_MIDDLE: 150, Finger.R_RING: 216, Finger.R_PINKY: 211,
    Finger.THUMB: 245,
}


def paint(label: str, finger: Finger, state: str) -> str:
    """キー 1 つを色つきの字にする。"""
    color = PAINT[finger]
    if state == "next":
        return f"\x1b[1;30;48;5;{color}m {label} \x1b[0m"
    if state == "miss":
        return f"\x1b[1;97;48;5;196m {label} \x1b[0m"
    if state == "home":
        return f"\x1b[4;38;5;{color}m {label} \x1b[0m"
    return f"\x1b[38;5;{color}m {label} \x1b[0m"


def show(game: Game) -> str:
    """画面ぜんぶ。"""
    stage = STAGES[game.stage]
    done_part = game.text[:game.at]
    rest = game.text[game.at:]
    lines = [
        f" 段階 {game.stage + 1}/{len(STAGES)}  {stage.name}   "
        f"打った {game.hits}  ミス {game.misses}  正確さ {game.accuracy():.0%}",
        "",
        f"   \x1b[38;5;245m{done_part}\x1b[0m\x1b[1;4m{rest[:1]}\x1b[0m{rest[1:]}",
        "",
    ]
    if game.target is not None:
        key = KEYS[game.target]
        name = "空白" if game.target == " " else game.target
        lines.append(f"   次は  \x1b[1m{name}\x1b[0m  →  {key.finger.value}")
    else:
        lines.extend("   " + line for line in report(game))
    lines.append("")
    for row, line in enumerate(keyboard_view(game)):
        if row < len(ROWS):
            indent = " " * int(ROWS[row][1] * 3)
            lines.append("  " + indent + "".join(paint(c, f, s) for c, f, s in line))
        else:
            char, finger, state = line[0]
            lines.append("  " + " " * 15 + paint("   空白   ", finger, state))
    lines.append("")
    lines.append(f" {game.message}")
    lines.append(" リターン=つぎへ（終わったら）　Esc=やめる　※ 日本語入力はオフに")
    return "\n".join(lines)


def run() -> None:
    """端末で練習する。1 キーずつ読む。"""
    import termios
    import time
    import tty

    game = Game()
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        sys.stdout.write("\x1b[2J\x1b[?25l")
        while True:
            sys.stdout.write("\x1b[H\x1b[J" + show(game))
            sys.stdout.flush()
            ch = sys.stdin.read(1)
            if ch in ("\x1b", "\x03", "\x04"):
                break
            key = {"\r": "enter", "\n": "enter"}.get(ch, ch)
            obey(game, key, time.perf_counter())
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
        sys.stdout.write("\x1b[?25h\x1b[2J\x1b[H")


# ── 確かめる ────────────────────────────────────────────────────────────

def check() -> None:
    """決まりを機械に確かめさせる。"""
    print("● JIS 配列")
    counts = [len(chars) for chars, _ in ROWS]
    assert counts == [13, 12, 12, 11], counts
    assert all(char in KEYS for char in string.ascii_lowercase + string.digits)
    assert KEYS["f"].finger is Finger.L_INDEX and KEYS["j"].finger is Finger.R_INDEX
    assert KEYS["a"].finger is Finger.L_PINKY and KEYS[";"].finger is Finger.R_PINKY
    assert KEYS["¥"].finger is Finger.R_PINKY and KEYS["_"].finger is Finger.R_PINKY
    assert KEYS["5"].finger is Finger.L_INDEX and KEYS["6"].finger is Finger.R_INDEX
    used = {key.finger for key in KEYS.values()}
    assert used == set(Finger), set(Finger) - used
    print(f"  段のキー数 {counts}（13/12/12/11 = JIS）。a〜z と 0〜9 が全部あり、9 本の指が全部使われる")

    print("● 段階")
    seen = ""
    for index, stage in enumerate(STAGES):
        assert not set(stage.fresh) & set(seen), f"{stage.name} のキーが前と重なる"
        seen += stage.fresh
        assert all(char in KEYS for char in stage.fresh)
    assert set(seen) >= set(string.ascii_lowercase + string.digits)
    print(f"  {len(STAGES)} 段階で a〜z と 0〜9 を全部通る（重なりなし）")

    print("● 練習文")
    for index in range(len(STAGES)):
        for seed in range(3):
            text = drill(index, seed)
            assert text == drill(index, seed), "同じ回なのに違う文が出た"
            allowed = set(STAGES[index].learned(index)) | {" "}
            assert set(text) <= allowed, f"段階 {index + 1} に習っていないキーが出た"
            assert len(text.replace(" ", "")) == GROUPS * GROUP_LEN
        fresh = set(STAGES[index].fresh)
        share = sum(1 for c in drill(index) if c in fresh) / (GROUPS * GROUP_LEN)
        print(f"  段階 {index + 1} {STAGES[index].name:9s} 例「{drill(index)[:19]}…」 新しいキーの割合 {share:.0%}")
    assert drill(0, 0) != drill(0, 1), "回が変わっても同じ文"

    print("● 練習の決まり")
    game = Game()
    clock = 0.0
    for char in game.text:                          # 全部正しく、0.2 秒間隔で
        clock += 0.2
        obey(game, char, clock)
    assert game.done and game.passed and game.accuracy() == 1.0
    assert abs(game.per_minute() - 300) < 1, game.per_minute()
    print(f"  全部正しく打つと合格。0.2 秒間隔なら 1 分あたり {game.per_minute():.0f} 打")

    game = Game()
    first = game.target
    assert not obey(game, "z" if first != "z" else "x", 1.0) and game.at == 0
    assert game.misses == 1 and game.wrong and game.target == first
    assert game.miss_by == {KEYS[first].finger.value: 1}
    obey(game, first, 1.2)
    assert game.at == 1 and game.wrong == "", "正しく押したら赤は消えるはず"
    print("  間違えたら進まず、ミスを数え、正しいキーを押すまで待つ。指ごとに数える")

    game = Game()
    chars = list(game.text)
    for i, char in enumerate(chars):
        if i % 10 == 0:                             # 10 回に 1 回間違える → 91%
            obey(game, "z" if char != "z" else "x", i * 0.2)
        obey(game, char, i * 0.2 + 0.1)
    assert game.done and not game.passed, game.accuracy()
    stage_before = game.stage
    obey(game, "enter", 99.0)
    assert game.stage == stage_before and game.round == 1, "不合格なら同じ段階のはず"
    assert game.text != drill(stage_before, 0), "同じ段階でも別の文が出るはず"
    print(f"  正確さ {PASS:.0%} 未満なら同じ段階を別の文でもう一度")

    game = Game()
    for char in game.text:
        obey(game, char, 1.0)
    obey(game, "enter", 2.0)
    assert game.stage == 1 and game.round == 0, "合格なら次の段階のはず"
    print("  合格ならリターンで次の段階へ")

    print("● キーボードの見た目（データ）")
    game = Game()
    view = keyboard_view(game)
    assert [len(row) for row in view] == [13, 12, 12, 11, 1]
    nexts = [c for row in view for c, _, s in row if s == "next"]
    assert nexts == [game.target], nexts
    homes = [c for row in view for c, _, s in row if s == "home"]
    assert set(homes) | {game.target} >= set(HOME)
    print(f"  次のキーはちょうど 1 つ（{game.target}）、ホームポジションに印")

    print("\nぜんぶ通った。")


def main() -> None:
    if "--check" in sys.argv:
        check()
    elif "--drill" in sys.argv:
        index = int(sys.argv[sys.argv.index("--drill") + 1])
        for seed in range(3):
            print(f"段階 {index + 1} {STAGES[index].name} 回 {seed + 1}: {drill(index, seed)}")
    else:
        run()


if __name__ == "__main__":
    main()
