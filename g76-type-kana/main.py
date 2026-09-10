"""タイピング2（ローマ字で日本語）

g75 の続き。打つものが「キーの並び」から「ことば」になる。「さくら」を sakura と打つ。
みじかい ことば → ながい ことば（ん・っ・きゃ・ー）→ ぶん、と段階を踏む。

今回の主題は「綴りのゆれを受ける」こと。し は shi でも si でもよく、ん は nn でも
（次が子音なら）n でもよい。これを**「いま居られる状態」の集合**で追う。n を打った時点では
「ん が終わった」と「nn の途中」の両方を残し、次のキーで決まる。
画面にはおすすめの綴りを出すが、打ったゆれに合わせて残りが変わる。

    python3 main.py            練習する
    python3 main.py --check    決まりを確かめる
    python3 main.py --drill 1  段階 2 の練習文を見る
    python3 main.py --romaji さくら   受け付ける綴りを全部見る
"""

import io
import math
import random
import re
import string
import sys
import wave
from array import array
from dataclasses import dataclass, field
from enum import Enum
from itertools import product
from statistics import fmean

PASS = 0.95                                         # 次の段階へ行ける正確さ
WORDS_PER_DRILL = 5                                 # 1 回の練習に出すことばの数（文は 2 つ）
RATE = 22050                                        # 音の標本の数（1 秒あたり）
VOLUME = 0.12                                       # 小さく。0〜1


# ── 音 ──────────────────────────────────────────────────────────────────

def tone(hz: float, seconds: float, volume: float = VOLUME) -> array:
    """正弦波 1 つ。出だしと終わりを短く絞って「プツッ」を消す（g73 と同じ）。"""
    count = int(RATE * seconds)
    edge = RATE / 200                               # 200 分の 1 秒でなめらかに
    samples = array("h")
    for i in range(count):
        fade = min(1.0, i / edge, (count - i) / edge)
        samples.append(int(32767 * volume * fade * math.sin(math.tau * hz * i / RATE)))
    return samples


def beep_bytes(kind: str) -> bytes:
    """キーを押したときの音を wav の bytes にする。

    hit   合った。高く、ごく短く（0.04 秒）
    miss  違った。低く、少し長く（0.12 秒）——目を上げなくても分かる
    done  打ち終わった。2 つの音を上がる向きに
    """
    if kind == "hit":
        samples = tone(1320, 0.04)
    elif kind == "miss":
        samples = tone(196, 0.12, VOLUME * 1.4)
    else:
        samples = tone(880, 0.08) + tone(1320, 0.14)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(samples.tobytes())
    return buffer.getvalue()


BEEPS = ("hit", "miss", "done")


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


# ── ローマ字 ────────────────────────────────────────────────────────────

# かな → 受け付ける綴り。先頭が「おすすめ」（画面に出す）
ROMAJI: dict[str, tuple[str, ...]] = {
    "あ": ("a",), "い": ("i",), "う": ("u",), "え": ("e",), "お": ("o",),
    "か": ("ka",), "き": ("ki",), "く": ("ku",), "け": ("ke",), "こ": ("ko",),
    "さ": ("sa",), "し": ("shi", "si"), "す": ("su",), "せ": ("se",), "そ": ("so",),
    "た": ("ta",), "ち": ("chi", "ti"), "つ": ("tsu", "tu"), "て": ("te",), "と": ("to",),
    "な": ("na",), "に": ("ni",), "ぬ": ("nu",), "ね": ("ne",), "の": ("no",),
    "は": ("ha",), "ひ": ("hi",), "ふ": ("fu", "hu"), "へ": ("he",), "ほ": ("ho",),
    "ま": ("ma",), "み": ("mi",), "む": ("mu",), "め": ("me",), "も": ("mo",),
    "や": ("ya",), "ゆ": ("yu",), "よ": ("yo",),
    "ら": ("ra",), "り": ("ri",), "る": ("ru",), "れ": ("re",), "ろ": ("ro",),
    "わ": ("wa",), "を": ("wo",),
    "が": ("ga",), "ぎ": ("gi",), "ぐ": ("gu",), "げ": ("ge",), "ご": ("go",),
    "ざ": ("za",), "じ": ("ji", "zi"), "ず": ("zu",), "ぜ": ("ze",), "ぞ": ("zo",),
    "だ": ("da",), "ぢ": ("di",), "づ": ("du",), "で": ("de",), "ど": ("do",),
    "ば": ("ba",), "び": ("bi",), "ぶ": ("bu",), "べ": ("be",), "ぼ": ("bo",),
    "ぱ": ("pa",), "ぴ": ("pi",), "ぷ": ("pu",), "ぺ": ("pe",), "ぽ": ("po",),
    "きゃ": ("kya",), "きゅ": ("kyu",), "きょ": ("kyo",),
    "しゃ": ("sha", "sya"), "しゅ": ("shu", "syu"), "しょ": ("sho", "syo"),
    "ちゃ": ("cha", "tya", "cya"), "ちゅ": ("chu", "tyu", "cyu"), "ちょ": ("cho", "tyo", "cyo"),
    "にゃ": ("nya",), "にゅ": ("nyu",), "にょ": ("nyo",),
    "ひゃ": ("hya",), "ひゅ": ("hyu",), "ひょ": ("hyo",),
    "みゃ": ("mya",), "みゅ": ("myu",), "みょ": ("myo",),
    "りゃ": ("rya",), "りゅ": ("ryu",), "りょ": ("ryo",),
    "ぎゃ": ("gya",), "ぎゅ": ("gyu",), "ぎょ": ("gyo",),
    "じゃ": ("ja", "zya", "jya"), "じゅ": ("ju", "zyu", "jyu"), "じょ": ("jo", "zyo", "jyo"),
    "びゃ": ("bya",), "びゅ": ("byu",), "びょ": ("byo",),
    "ぴゃ": ("pya",), "ぴゅ": ("pyu",), "ぴょ": ("pyo",),
    "ふぁ": ("fa",), "ふぃ": ("fi",), "ふぇ": ("fe",), "ふぉ": ("fo",),
    "てぃ": ("thi",), "でぃ": ("dhi",), "うぃ": ("wi",), "うぇ": ("we",),
    "ぁ": ("xa", "la"), "ぃ": ("xi", "li"), "ぅ": ("xu", "lu"), "ぇ": ("xe", "le"), "ぉ": ("xo", "lo"),
    "ゃ": ("xya", "lya"), "ゅ": ("xyu", "lyu"), "ょ": ("xyo", "lyo"),
    "ー": ("-",), "、": (",",), "。": (".",), " ": (" ",),
}
SMALL_TSU = ("xtu", "ltu", "xtsu", "ltsu")            # っ をそれだけで打つとき
VOWELS = "aiueo"


def hiragana(text: str) -> str:
    """カタカナをひらがなにする。表はひらがなで持っているので、先に寄せる。

    re.sub に関数を渡すと、見つかった字ごとに「どう置き換えるか」を計算できる。
    カタカナはひらがなの 0x60 あと（ア = あ + 0x60）なので、引き算で戻る。
    """
    return re.sub(r"[ァ-ヶ]", lambda m: chr(ord(m.group()) - 0x60), text)


def units_of(kana: str) -> list[str]:
    """かなを、ローマ字 1 つぶんの単位に切る。「きゃ」は 2 字で 1 単位。"""
    kana = hiragana(kana)
    out, i = [], 0
    while i < len(kana):
        pair = kana[i:i + 2]
        if len(pair) == 2 and pair in ROMAJI:
            out.append(pair)
            i += 2
        else:
            out.append(kana[i])
            i += 1
    return out


def spellings(units: list[str], i: int) -> tuple[str, ...]:
    """単位 i の受け付ける綴り。っ と ん は次の単位を見て決まる。"""
    unit = units[i]
    following = spellings(units, i + 1) if i + 1 < len(units) and units[i + 1] not in ("っ", "ん") \
        else ()
    if unit == "っ":
        # 次の綴りの最初の子音を 1 つ重ねる（きって = kitte）。母音と n は重ねられない
        doubled = tuple(dict.fromkeys(s[0] for s in following if s[0] not in VOWELS + "n"))
        return doubled + SMALL_TSU
    if unit == "ん":
        # 次が子音（な行・や行を除く）なら n 1 つでよい。母音や な・や の前、最後、空白や記号の前は nn
        lone = following and all(s[0].isalpha() and s[0] not in VOWELS + "ny" for s in following)
        return (("n",) if lone else ()) + ("nn", "xn")
    if unit not in ROMAJI:
        raise ValueError(f"ローマ字にできない字: {unit!r}")
    return ROMAJI[unit]


# ── 段階 ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Stage:
    """段階。名前と、出すことば。"""

    name: str
    words: tuple[str, ...]
    count: int                                      # 1 回に出す数


STAGES = (
    Stage("みじかい ことば", (
        "さくら", "うみ", "やま", "そら", "はな", "ねこ", "いぬ", "ほし", "つき", "かわ",
        "みず", "ひかり", "くも", "あめ", "ゆき", "かぜ", "もり", "いし", "さかな", "とり",
        "うた", "ふね", "みち", "まち", "むら", "はし", "かさ", "くつ", "ふく", "つくえ",
    ), WORDS_PER_DRILL),
    Stage("ながい ことば", (
        "しんかんせん", "きっぷ", "きょうと", "とうきょう", "おちゃ", "じゅぎょう", "がっこう",
        "せんせい", "でんしゃ", "きって", "ざっし", "しゃしん", "りょこう", "にっき", "びょういん",
        "コンピュータ", "テレビ", "パン", "ラーメン", "コーヒー", "スーパー", "サッカー", "ノート",
        "ぎんこう", "にんじん", "しんぶん", "おんがく", "けんこう", "ちゃわん", "ほんや",
    ), WORDS_PER_DRILL),
    Stage("ぶん", (
        "きょうは いい てんきです。",
        "ねこが にわで ねている。",
        "あしたは がっこうに いきます。",
        "でんしゃで とうきょうへ いった。",
        "おちゃを のみながら ほんを よむ。",
        "しんかんせんは とても はやい。",
        "まいあさ パンと コーヒーを たべる。",
        "きって、 はがき、 ふうとうを かった。",
        "せんせいが しゃしんを とった。",
        "にちようびに サッカーを した。",
    ), 2),
)


def drill(index: int, seed: int = 0) -> str:
    """段階 index の練習文。ことばを空白でつなぐ。

    乱数の種を固定してあるので、同じ段階・同じ回なら端末でもブラウザでも同じ文になる。
    """
    luck = random.Random(seed * 100 + index)
    stage = STAGES[index]
    return " ".join(luck.sample(stage.words, stage.count))


# ── 練習 ────────────────────────────────────────────────────────────────

@dataclass
class Game:
    """練習の状態。端末もブラウザもこれ 1 つを進める。"""

    stage: int = 0
    round: int = 0                                  # その段階で何回目か
    kana: str = ""                                  # 打つことば（かな）
    units: list[str] = field(default_factory=list)  # ローマ字 1 つぶんの単位に切ったもの（ひらがな）
    shown: list[str] = field(default_factory=list)  # 画面に出す単位（カタカナはそのまま）
    states: set[tuple[int, str]] = field(default_factory=set)   # いま居られる (単位, 打ちかけ)
    typed: str = ""                                 # 合ったキーの列
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
        if not self.kana:
            self.start()

    def start(self) -> None:
        """その段階の練習文を出し、数え直す。"""
        self.kana = drill(self.stage, self.round)
        self.units = units_of(self.kana)
        self.shown, at = [], 0                      # 判定はひらがな、表示は元の字で
        for unit in self.units:
            self.shown.append(self.kana[at:at + len(unit)])
            at += len(unit)
        self.states = {(0, "")}
        self.typed = ""
        self.hits = self.misses = 0
        self.wrong = ""
        self.started = self.last = None
        self.gaps = []
        self.miss_by = {}
        self.done = self.passed = False
        self.message = f"{STAGES[self.stage].name}。打ち始めると時計が動きます"

    def best(self) -> tuple[int, str]:
        """いちばん進んでいる状態。画面に出すのはこれ。"""
        return max(self.states, key=lambda state: (state[0], len(state[1])))

    def favorite(self, i: int, partial: str) -> str:
        """単位 i の綴りのうち、打ちかけ partial に合う「おすすめ」。"""
        for spelling in spellings(self.units, i):
            if spelling.startswith(partial):
                return spelling
        return ""

    @property
    def target(self) -> str | None:
        """次に押すキー（おすすめの綴りで）。終わっていれば None。"""
        if self.done:
            return None
        i, partial = self.best()
        return self.favorite(i, partial)[len(partial)]

    def hint(self) -> str:
        """まだ打っていないぶんのローマ字（おすすめの綴り）。打ったゆれに合わせて変わる。"""
        if self.done:
            return ""
        i, partial = self.best()
        rest = self.favorite(i, partial).removeprefix(partial)
        return rest + "".join(spellings(self.units, j)[0] for j in range(i + 1, len(self.units)))

    def done_units(self) -> int:
        """かなの何単位まで打ち終わったか。"""
        return self.best()[0]

    def press(self, char: str, now: float) -> bool:
        """キーを 1 つ受ける。居られる状態が 1 つでも残れば進む。残らなければミス。

        状態は (単位の番号, その単位の打ちかけ)。1 つのキーで、ある状態は次の単位へ進み、
        別の状態は打ちかけが伸びる。両方を持っておけば「ん を n 1 つで済ませたのか、
        nn の途中なのか」を次のキーまで決めなくてよい。
        """
        if self.done:
            return False
        if self.started is None:
            self.started = now
        elif self.last is not None:
            self.gaps.append(now - self.last)
        self.last = now
        moved: set[tuple[int, str]] = set()
        for i, partial in self.states:
            if i >= len(self.units):
                continue
            trying = partial + char
            for spelling in spellings(self.units, i):
                if spelling == trying:
                    moved.add((i + 1, ""))
                elif spelling.startswith(trying):
                    moved.add((i, trying))
        if moved:
            self.states = moved
            self.typed += char
            self.hits += 1
            self.wrong = ""
            if any(i == len(self.units) for i, _ in moved):
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


def obey(game: Game, key: str, now: float) -> str | None:
    """キーを 1 つ受け取って練習を進め、鳴らす音（hit / miss / done）があれば返す。

    端末もブラウザもここを通る。now は外から渡す。中で時計を読まないので、
    同じキー列と同じ時刻を与えれば端末でもブラウザでも同じ結果になる（検証で使う）。
    """
    if key == "enter":
        if game.done:
            game.advance()
        return None
    if key == "escape" or game.done or key not in KEYS:
        return None
    if game.press(key, now):
        return "done" if game.done else "hit"
    return "miss"


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


def show(game: Game, sound: bool = True) -> str:
    """画面ぜんぶ。"""
    stage = STAGES[game.stage]
    done = game.done_units()
    kana_done = "".join(game.shown[:done])
    kana_rest = "".join(game.shown[done:])
    hint = game.hint()
    lines = [
        f" 段階 {game.stage + 1}/{len(STAGES)}  {stage.name}   "
        f"打った {game.hits}  ミス {game.misses}  正確さ {game.accuracy():.0%}",
        "",
        f"   \x1b[38;5;245m{kana_done}\x1b[0m\x1b[1m{kana_rest}\x1b[0m",
        f"   \x1b[38;5;245m{game.typed}\x1b[0m\x1b[1;4m{hint[:1]}\x1b[0m{hint[1:]}",
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
    lines.append(f" リターン=つぎへ（終わったら）　Tab=音 {'オン' if sound else 'オフ'}　Esc=やめる　※ 日本語入力はオフに")
    return "\n".join(lines)


class Speaker:
    """端末で音を出す係。3 つの wav を先に書いておき、押されたら afplay に渡す。"""

    def __init__(self):
        import os
        import shutil
        import tempfile

        self.player = shutil.which("afplay") or shutil.which("aplay")
        self.folder = tempfile.mkdtemp(prefix="type-keys-")
        self.paths = {}
        for kind in BEEPS:
            path = os.path.join(self.folder, f"{kind}.wav")
            with open(path, "wb") as out:
                out.write(beep_bytes(kind))
            self.paths[kind] = path
        self.on = True

    def say(self, kind: str | None) -> None:
        import subprocess

        if kind is None or not self.on or self.player is None:
            return
        subprocess.Popen([self.player, self.paths[kind]],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def close(self) -> None:
        import shutil

        shutil.rmtree(self.folder, ignore_errors=True)


def run() -> None:
    """端末で練習する。1 キーずつ読む。"""
    import termios
    import time
    import tty

    game = Game()
    speaker = Speaker()
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        sys.stdout.write("\x1b[2J\x1b[?25l")
        while True:
            sys.stdout.write("\x1b[H\x1b[J" + show(game, speaker.on))
            sys.stdout.flush()
            ch = sys.stdin.read(1)
            if ch in ("\x1b", "\x03", "\x04"):
                break
            if ch == "\t":                             # 音の on/off
                speaker.on = not speaker.on
                continue
            key = {"\r": "enter", "\n": "enter"}.get(ch, ch)
            speaker.say(obey(game, key, time.perf_counter()))
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
        sys.stdout.write("\x1b[?25h\x1b[2J\x1b[H")
        speaker.close()


# ── 確かめる ────────────────────────────────────────────────────────────

def all_spellings(kana: str) -> list[str]:
    """ことば全体の、受け付ける綴りぜんぶ。検査で「どれで打っても通る」を見るために使う。

    単位ごとの綴りの直積（product）をつないで作る。ことばが長いと数が増えるので検査だけ。
    """
    units = units_of(kana)
    choices = [spellings(units, i) for i in range(len(units))]
    return ["".join(parts) for parts in product(*choices)]


def typed_through(kana: str, keys: str) -> Game:
    """ことば kana に keys を打ち込んだあとの Game（検査用）。"""
    game = Game()
    game.kana, game.units, game.states, game.typed = kana, units_of(kana), {(0, "")}, ""
    game.hits = game.misses = 0
    game.done = False
    for char in keys:
        game.press(char, 1.0)
    return game


def check() -> None:
    """決まりを機械に確かめさせる。"""
    print("● ローマ字の表")
    plain = "あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわを"
    assert all(char in ROMAJI for char in plain)
    for chars in ROMAJI.values():
        assert all(c in KEYS for s in chars for c in s), chars
    assert hiragana("コンピュータ") == "こんぴゅーた" and hiragana("さくら") == "さくら"
    print(f"  {len(ROMAJI)} 項目。五十音は全部あり、綴りの字は全部 JIS の表にある。カタカナはひらがなに寄せる")

    print("● かなの切り方")
    assert units_of("きょうと") == ["きょ", "う", "と"]
    assert units_of("しんかんせん") == ["し", "ん", "か", "ん", "せ", "ん"]
    assert units_of("コンピュータ") == ["こ", "ん", "ぴゅ", "ー", "た"]
    for stage in STAGES:
        for word in stage.words:
            units = units_of(word)
            for i in range(len(units)):
                assert spellings(units, i), (word, units[i])
    print(f"  段階の {sum(len(s.words) for s in STAGES)} 語すべて、ローマ字にできる")

    print("● 綴りのゆれ")
    cases = {
        "しんかんせん": ("shinkansenn", "sinnkannsenn", "shinnkannsenn"),
        "きって": ("kitte", "kixtute", "kiltute"),
        "がっこう": ("gakkou", "gaxtukou"),
        "にんじん": ("ninjinn", "ninnzinn"),
        "コンピュータ": ("konpyu-ta", "konnpyu-ta"),
        "ちゃわん": ("chawann", "tyawann", "cyawann"),
    }
    for kana, keys_list in cases.items():
        for keys in keys_list:
            game = typed_through(kana, keys)
            assert game.done and game.misses == 0, (kana, keys, game.misses)
        every = all_spellings(kana)
        for keys in every:
            assert typed_through(kana, keys).done, (kana, keys)
        print(f"  {kana:8s} {len(every):3d} 通りの綴りをすべて受ける（例 {' / '.join(keys_list)}）")
    assert not typed_through("パン", "pan").done, "最後の ん は n 1 つでは終わらないはず"
    assert typed_through("パン ぱん", "pan ").misses == 1, "空白の前の ん も nn が要るはず"
    assert typed_through("パン ぱん", "pann pann").done
    assert typed_through("パン", "pann").done
    game = typed_through("んあ", "na")
    assert game.misses == 1 and not game.done, "母音の前の ん は nn が要るはず"
    assert typed_through("んあ", "nna").done
    print("  最後の ん・母音の前の ん・空白の前の ん は nn が要る（na を んあ と読まない）")
    game = Game(stage=1)
    game.kana = "ラーメン"; game.units = units_of("ラーメン"); game.states = {(0, "")}
    game.shown = ["ラ", "ー", "メ", "ン"]
    assert "".join(game.shown) == "ラーメン" and game.units == ["ら", "ー", "め", "ん"]
    print("  判定はひらがなに寄せ、表示はカタカナのまま")

    print("● おすすめの綴りが、打ったゆれに合わせて変わるか")
    game = typed_through("しんぶん", "")
    assert game.hint() == "shinbunn", game.hint()
    game.press("s", 1.0); game.press("i", 1.0)
    assert game.typed == "si" and game.hint() == "nbunn", game.hint()
    game.press("n", 1.0)
    assert game.hint() == "bunn" or game.hint() == "nbunn", game.hint()
    print(f"  「しんぶん」を si と打ったら、残りは {game.hint()!r}（sh に戻さない）")

    print("● 練習文")
    for index in range(len(STAGES)):
        for seed in range(3):
            text = drill(index, seed)
            assert text == drill(index, seed), "同じ回なのに違う文が出た"
            assert all(word in STAGES[index].words for word in text.split(" ") if word) or index == 2
        print(f"  段階 {index + 1} {STAGES[index].name:9s} 例「{drill(index)}」")
    assert drill(0, 0) != drill(0, 1), "回が変わっても同じ文"

    print("● 練習の決まり")
    game = Game()
    clock = 0.0
    for char in all_spellings(game.kana)[0]:        # おすすめの綴りで、0.2 秒間隔で
        clock += 0.2
        obey(game, char, clock)
    assert game.done and game.passed and game.accuracy() == 1.0
    assert abs(game.per_minute() - 300) < 1, game.per_minute()
    print(f"  全部正しく打つと合格。0.2 秒間隔なら 1 分あたり {game.per_minute():.0f} 打")

    game = Game()
    first = game.target
    assert obey(game, "z" if first != "z" else "x", 1.0) == "miss" and game.typed == ""
    assert game.misses == 1 and game.wrong and game.target == first
    assert game.miss_by == {KEYS[first].finger.value: 1}
    assert obey(game, first, 1.2) == "hit" and game.wrong == ""
    print("  間違えたら進まず、ミスを数え、正しいキーを押すまで待つ。指ごとに数える")

    game = Game()
    for i, char in enumerate(all_spellings(game.kana)[0]):
        if i % 10 == 0:
            obey(game, "z" if char != "z" else "x", i * 0.2)
        obey(game, char, i * 0.2 + 0.1)
    assert game.done and not game.passed
    obey(game, "enter", 99.0)
    assert game.stage == 0 and game.round == 1, "不合格なら同じ段階のはず"
    print(f"  正確さ {PASS:.0%} 未満なら同じ段階を別の文でもう一度")

    game = Game()
    for char in all_spellings(game.kana)[0]:
        obey(game, char, 1.0)
    assert obey(game, "enter", 2.0) is None and game.stage == 1
    print("  合格ならリターンで次の段階へ")

    print("● 音")
    for kind in BEEPS:
        data = beep_bytes(kind)
        assert data[:4] == b"RIFF"
    assert beep_bytes("hit") != beep_bytes("miss")
    game = Game()
    keys = all_spellings(game.kana)[0]
    for char in keys[:-1]:
        obey(game, char, 1.0)
    assert obey(game, keys[-1], 2.0) == "done"
    print("  合えば hit、違えば miss、打ち終われば done")

    print("● キーボードの見た目（データ）")
    game = Game()
    view = keyboard_view(game)
    assert [len(row) for row in view] == [13, 12, 12, 11, 1]
    nexts = [c for row in view for c, _, s in row if s == "next"]
    assert nexts == [game.target], nexts
    print(f"  次のキーはちょうど 1 つ（{game.target}）")

    print("\nぜんぶ通った。")


def main() -> None:
    if "--check" in sys.argv:
        check()
    elif "--drill" in sys.argv:
        index = int(sys.argv[sys.argv.index("--drill") + 1])
        for seed in range(3):
            print(f"段階 {index + 1} {STAGES[index].name} 回 {seed + 1}: {drill(index, seed)}")
    elif "--romaji" in sys.argv:
        kana = sys.argv[sys.argv.index("--romaji") + 1]
        every = all_spellings(kana)
        print(f"{kana} → {units_of(kana)}")
        print(f"{len(every)} 通り: " + "  ".join(every[:24]) + ("  …" if len(every) > 24 else ""))
    else:
        run()


if __name__ == "__main__":
    main()
