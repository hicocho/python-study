"""タイピング1（キーボードと指）ブラウザ版

CLI 版（g75-type-keys/main.py）と中身はまったく同じ。JIS 配列の表（ROWS・KEYS）も、
段階と練習文（STAGES・drill）も、判定（Game・obey）も、見た目の表（keyboard_view）も
1 文字も変えていない。

違うのは入口と出口だけ。
  入口: 端末はキー 1 文字、ブラウザは keydown。どちらも obey() に入る
  出口: 端末は keyboard_view() を色つきの字に、ブラウザは同じ表を <div> にする。
        時計は端末が time.perf_counter()、ブラウザが performance.now()。
        どちらも obey() に「いま」を渡すだけで、中では時計を読まない。

持ってこなかったのは端末の描画（paint / show / run）と検査だけ。
"""

import random
import string
from dataclasses import dataclass, field
from enum import Enum
from statistics import fmean

from pyscript import document, when, window
PASS = 0.95                                         # 次の段階へ行ける正確さ


GROUPS = 8                                          # 1 回の練習に出す「かたまり」の数


GROUP_LEN = 4                                       # かたまり 1 つのキーの数


FRESH = 0.6                                         # 新しいキーを出す割合（残りは復習）


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


COLUMN_FINGER = (Finger.L_PINKY, Finger.L_RING, Finger.L_MIDDLE, Finger.L_INDEX, Finger.L_INDEX,
                 Finger.R_INDEX, Finger.R_INDEX, Finger.R_MIDDLE, Finger.R_RING)


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


# --- ここから下はブラウザ版だけ。CLI 版の paint() / show() / run() にあたる ---

stage_label = document.querySelector("#stage")
name_label = document.querySelector("#name")
hits_label = document.querySelector("#hits")
misses_label = document.querySelector("#misses")
acc_label = document.querySelector("#acc")
text_box = document.querySelector("#text")
next_box = document.querySelector("#next")
board = document.querySelector("#board")
report_box = document.querySelector("#report")
message = document.querySelector("#message")
next_button = document.querySelector("#go")
ime_warning = document.querySelector("#ime")

FINGER_CLASS = {finger: f"f{n}" for n, finger in enumerate(Finger)}

game = Game()


def build_board() -> None:
    """キーボードの <div> を、共有の ROWS から 1 回だけ組む。"""
    for row, (chars, offset) in enumerate(ROWS):
        line = document.createElement("div")
        line.className = "row"
        line.style.paddingLeft = f"{offset * 2.2}rem"
        for char in chars:
            cell = document.createElement("span")
            cell.className = "key " + FINGER_CLASS[KEYS[char].finger]
            cell.setAttribute("data-key", char)
            cell.textContent = char
            line.appendChild(cell)
        board.appendChild(line)
    line = document.createElement("div")
    line.className = "row"
    line.style.paddingLeft = "7rem"
    cell = document.createElement("span")
    cell.className = "key space " + FINGER_CLASS[Finger.THUMB]
    cell.setAttribute("data-key", "space")
    cell.textContent = "空白"
    line.appendChild(cell)
    board.appendChild(line)


def refresh() -> None:
    """CLI 版の show() にあたる。keyboard_view() の表をクラス名に写す。"""
    stage_label.textContent = f"{game.stage + 1} / {len(STAGES)}"
    name_label.textContent = STAGES[game.stage].name
    hits_label.textContent = str(game.hits)
    misses_label.textContent = str(game.misses)
    acc_label.textContent = f"{game.accuracy():.0%}"
    text_box.innerHTML = ""
    for i, char in enumerate(game.text):
        span = document.createElement("span")
        span.className = "done" if i < game.at else "cur" if i == game.at else ""
        span.textContent = "␣" if char == " " else char
        text_box.appendChild(span)
    if game.target is not None:
        key = KEYS[game.target]
        next_box.innerHTML = (f"次は <b>{'空白' if game.target == ' ' else game.target}</b> → "
                              f"<span class='{FINGER_CLASS[key.finger]} tag'>{key.finger.value}</span>")
    else:
        next_box.textContent = ""
    for row in keyboard_view(game):
        for char, finger, state in row:
            cell = board.querySelector(f'[data-key="{char}"]')
            cell.className = f"key {FINGER_CLASS[finger]} {state}" + (" space" if char == "space" else "")
    report_box.textContent = "\n".join(report(game)) if game.done else ""
    message.textContent = game.message
    next_button.hidden = not game.done
    next_button.textContent = "つぎの段階へ →" if game.passed else "もう一度（別の文で）"


@when("click", "#go")
def go(event) -> None:
    obey(game, "enter", window.performance.now() / 1000)
    refresh()


@when("keydown", "body")
def typed(event) -> None:
    if event.key == "Process" or event.isComposing:
        ime_warning.hidden = False                  # 日本語入力がオン。字が届かない
        return
    ime_warning.hidden = True
    key = {"Enter": "enter", "Escape": "escape"}.get(event.key, event.key)
    if key in KEYS or key in ("enter", "escape"):
        event.preventDefault()
        obey(game, key, window.performance.now() / 1000)
        refresh()


build_board()
document.querySelector("#loading").hidden = True
refresh()
