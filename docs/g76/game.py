"""タイピング2（ローマ字で日本語）ブラウザ版

CLI 版（g76-type-kana/main.py）と中身はまったく同じ。ローマ字の表（ROMAJI）も、かなの切り方
（units_of・spellings）も、綴りのゆれを受ける判定（Game・obey）も 1 文字も変えていない。

違うのは入口と出口だけ。
  入口: 端末はキー 1 文字、ブラウザは keydown。どちらも obey() に入る
  出口: 端末は keyboard_view() を色つきの字に、ブラウザは同じ表を <div> にする。
        時計は端末が time.perf_counter()、ブラウザが performance.now()。
        どちらも obey() に「いま」を渡すだけで、中では時計を読まない。

音（beep_bytes）も同じ。端末は wav をファイルにして afplay へ、ブラウザは data URI にして Audio へ。
持ってこなかったのは端末の描画（paint / show / run）と Speaker と検査だけ。
"""

import asyncio
import base64
import io
import math
import random
import re
import string
import wave
from array import array
from dataclasses import dataclass, field
from enum import Enum
from itertools import product
from statistics import fmean

from pyodide.ffi import create_proxy, to_js
from pyscript import document, when, window
PASS = 0.95                                         # 次の段階へ行ける正確さ


WORDS_PER_DRILL = 5                                 # 1 回の練習に出すことばの数（文は 2 つ）


RATE = 22050                                        # 音の標本の数（1 秒あたり）


VOLUME = 0.12                                       # 小さく。0〜1


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
# --- 3D のキーボードと手（g75〜g77 で共有。2026-09-19）---------------------------------------
#   keyboard_view() の表（文字・指・状態）を Three.js のキーに写す。判定は 1 文字も変えていない。
#   キーは押すと沈み（GSAP のばね）、次に押すキーが光り、その指の「手」がキーの上へ動く。
#   音は Tone.js：指ごとに音の高さが違う（左小指が低く、右小指が高い）。間違えると濁る。

THREE = window.THREE
GSAP = getattr(window, "gsap", None)
TONE = getattr(window, "Tone", None)
KB_W, KB_H = 640, 360


def js(**kw):
    return to_js(kw, dict_converter=window.Object.fromEntries)


FINGER_COLOR = {                                    # CSS の指の色と同じ
    Finger.L_PINKY: 0xf2a7b3, Finger.L_RING: 0xf6c98b, Finger.L_MIDDLE: 0xc7e08c, Finger.L_INDEX: 0x8fd0e8,
    Finger.R_INDEX: 0xa9c4f5, Finger.R_MIDDLE: 0xb9e2a0, Finger.R_RING: 0xf8d59a, Finger.R_PINKY: 0xf5b2c4, Finger.THUMB: 0xcfcfcf,
}
FINGER_NOTE = {                                     # 指ごとの音（五音音階。左から右へ上がる）
    Finger.L_PINKY: "C4", Finger.L_RING: "D4", Finger.L_MIDDLE: "E4", Finger.L_INDEX: "G4",
    Finger.R_INDEX: "A4", Finger.R_MIDDLE: "C5", Finger.R_RING: "D5", Finger.R_PINKY: "E5", Finger.THUMB: "G3",
}
HOME_OF = {                                         # 指 → ホームポジションのキー
    Finger.L_PINKY: "a", Finger.L_RING: "s", Finger.L_MIDDLE: "d", Finger.L_INDEX: "f",
    Finger.R_INDEX: "j", Finger.R_MIDDLE: "k", Finger.R_RING: "l", Finger.R_PINKY: ";", Finger.THUMB: "space",
}
KEY_STEP = 1.0                                      # キーの間隔（世界の単位）
KEY_SIZE = 0.86
KEY_HEIGHT = 0.4

kb_canvas = document.querySelector("#board3d")
kb_renderer = THREE.WebGLRenderer.new(js(canvas=kb_canvas, antialias=True, alpha=True))
kb_renderer.setPixelRatio(min(2.0, window.devicePixelRatio))
kb_renderer.setSize(KB_W, KB_H, False)
kb_renderer.shadowMap.enabled = True
kb_renderer.shadowMap.type = THREE.PCFSoftShadowMap
kb_scene = THREE.Scene.new()
kb_camera = THREE.PerspectiveCamera.new(38, KB_W / KB_H, 0.5, 100)
KB_CAM = (0.0, 9.5, 8.8)
KB_LOOK = (0.0, 0.0, 1.4)
kb_camera.position.set(*KB_CAM)
kb_camera.lookAt(*KB_LOOK)
kb_key = THREE.DirectionalLight.new(0xffffff, 2.2)
kb_key.position.set(-4, 10, 6)
kb_key.castShadow = True
kb_key.shadow.mapSize.set(1024, 1024)
for _name, _value in (("left", -9), ("right", 9), ("top", 6), ("bottom", -6), ("near", 1), ("far", 40)):
    setattr(kb_key.shadow.camera, _name, _value)
kb_scene.add(kb_key)
kb_scene.add(THREE.HemisphereLight.new(0xe8f0ff, 0x8a7a6a, 0.9))


def key_label(text: str, finger: Finger) -> object:
    """キーの上面の絵：指の色の地に字。"""
    cv = document.createElement("canvas")
    cv.width = cv.height = 64
    ctx = cv.getContext("2d")
    c = FINGER_COLOR[finger]
    ctx.fillStyle = f"rgb({(c >> 16) & 255},{(c >> 8) & 255},{c & 255})"
    ctx.fillRect(0, 0, 64, 64)
    ctx.fillStyle = "#1f2328"
    ctx.textAlign = "center"
    ctx.textBaseline = "middle"
    ctx.font = "bold 30px sans-serif" if len(text) == 1 else "bold 20px sans-serif"
    ctx.fillText(text, 32, 34)
    tex = THREE.CanvasTexture.new(cv)
    tex.colorSpace = THREE.SRGBColorSpace
    return tex


kb_keys: dict[str, dict] = {}                       # 文字 → {mesh, x, z, finger, base_y, top}。g77 は lift（苦手の高さ）を足す
kb_side_mats: dict[Finger, object] = {finger: THREE.MeshStandardMaterial.new(js(color=color, roughness=0.6)) for finger, color in FINGER_COLOR.items()}
plate = THREE.Mesh.new(THREE.BoxGeometry.new(15.0, 0.5, 6.4), THREE.MeshStandardMaterial.new(js(color=0x5c6270, roughness=0.7, metalness=0.2)))
plate.position.set(0.3, -0.45, 1.5)
plate.receiveShadow = True
kb_scene.add(plate)
KB_LEFT = -6.2
for row, (chars, offset) in enumerate(ROWS):
    for column, char in enumerate(chars):
        finger = KEYS[char].finger
        x = KB_LEFT + (column + offset) * KEY_STEP
        z = row * KEY_STEP
        top = THREE.MeshStandardMaterial.new(js(map=key_label(char, finger), roughness=0.55, emissive=0x000000))
        side = kb_side_mats[finger]
        mesh = THREE.Mesh.new(THREE.BoxGeometry.new(KEY_SIZE, KEY_HEIGHT, KEY_SIZE), to_js([side, side, top, side, side, side]))
        mesh.position.set(x, 0.0, z)
        mesh.castShadow = True
        mesh.receiveShadow = True
        kb_scene.add(mesh)
        kb_keys[char] = dict(mesh=mesh, x=x, z=z, finger=finger, base_y=0.0, top=top)
        if char in "fj":                            # 突起
            bump = THREE.Mesh.new(THREE.BoxGeometry.new(0.3, 0.05, 0.06), THREE.MeshStandardMaterial.new(js(color=0x333333)))
            bump.position.set(0, KEY_HEIGHT / 2 + 0.02, 0.3)
            mesh.add(bump)
space_top = THREE.MeshStandardMaterial.new(js(map=key_label("空白", Finger.THUMB), roughness=0.55, emissive=0x000000))
space_mesh = THREE.Mesh.new(THREE.BoxGeometry.new(6.0, KEY_HEIGHT, KEY_SIZE), to_js([kb_side_mats[Finger.THUMB]] * 2 + [space_top] + [kb_side_mats[Finger.THUMB]] * 3))
space_mesh.position.set(KB_LEFT + 6.2, 0.0, 4 * KEY_STEP)
space_mesh.castShadow = True
kb_scene.add(space_mesh)
kb_keys["space"] = dict(mesh=space_mesh, x=KB_LEFT + 6.2, z=4 * KEY_STEP, finger=Finger.THUMB, base_y=0.0, top=space_top)

# 手：指先の球 10 個と、手のひらの板。ホームポジションに置き、次に押す指だけキーの上へ
SKIN = THREE.MeshStandardMaterial.new(js(color=0xf1c9a5, roughness=0.75))
SKIN_NEXT = THREE.MeshStandardMaterial.new(js(color=0xffe0b0, roughness=0.5, emissive=0xffb040, emissiveIntensity=0.6))
kb_tips: dict[Finger, dict] = {}
for finger, home in HOME_OF.items():
    if finger == Finger.THUMB:
        continue
    k = kb_keys[home]
    tip = THREE.Mesh.new(THREE.SphereGeometry.new(0.3, 16, 12), SKIN)
    tip.castShadow = True
    tip.position.set(k["x"], 0.55, k["z"] + 0.15)
    kb_scene.add(tip)
    kb_tips[finger] = dict(mesh=tip, home=(k["x"], 0.55, k["z"] + 0.15), want=[k["x"], 0.55, k["z"] + 0.15])
for side, x in (("L", kb_keys["space"]["x"] - 1.2), ("R", kb_keys["space"]["x"] + 1.2)):   # 親指は 2 本
    tip = THREE.Mesh.new(THREE.SphereGeometry.new(0.3, 16, 12), SKIN)
    tip.castShadow = True
    tip.position.set(x, 0.55, kb_keys["space"]["z"] + 0.1)
    kb_scene.add(tip)
    kb_tips[("thumb", side)] = dict(mesh=tip, home=(x, 0.55, kb_keys["space"]["z"] + 0.1), want=[x, 0.55, kb_keys["space"]["z"] + 0.1])
kb_palms = []
for fingers in ((Finger.L_PINKY, Finger.L_RING, Finger.L_MIDDLE, Finger.L_INDEX), (Finger.R_INDEX, Finger.R_MIDDLE, Finger.R_RING, Finger.R_PINKY)):
    xs = [kb_tips[f]["home"][0] for f in fingers]
    palm = THREE.Mesh.new(THREE.SphereGeometry.new(1.0, 20, 14), SKIN)
    palm.scale.set(1.9, 0.45, 1.3)
    palm.position.set(sum(xs) / 4, 0.75, kb_keys["f"]["z"] + 2.2)
    palm.castShadow = True
    kb_scene.add(palm)
    kb_palms.append(palm)
kb_glow = THREE.Mesh.new(THREE.RingGeometry.new(0.6, 0.78, 32), THREE.MeshBasicMaterial.new(js(color=0xffe37a, transparent=True, opacity=0.9, side=THREE.DoubleSide)))
kb_glow.rotation.x = -math.pi / 2
kb_glow.visible = False
kb_scene.add(kb_glow)

kb_state = {"next": None, "miss": None, "time": 0.0, "shake": 0.0, "streak": 0, "zoom": 0.0}


def kb_note_start() -> None:
    """Tone.js の楽器。人が触った処理（keydown）の中で 1 回だけ作る。"""
    if TONE is None or kb_state.get("synth") is not None:
        return
    try:
        TONE.start()
        synth = TONE.PolySynth.new(TONE.Synth, js(oscillator=js(type="triangle"), envelope=js(attack=0.005, decay=0.12, sustain=0.1, release=0.25))).toDestination()
        synth.volume.value = -12
        kb_state["synth"] = synth
    except Exception:
        kb_state["synth"] = False


def kb_sound(char: str, ok: bool) -> bool:
    """打鍵の音。合えばその指の音、違えば濁った低い 2 音。鳴らせたら True。"""
    synth = kb_state.get("synth")
    if not synth:
        return False
    try:
        now = TONE.now()
        if ok:
            finger = kb_keys[char]["finger"] if char in kb_keys else Finger.THUMB
            synth.triggerAttackRelease(FINGER_NOTE[finger], "16n", now)
        else:
            synth.triggerAttackRelease(to_js(["E2", "F2"]), "8n", now)
        return True
    except Exception:
        return False


def kb_pressed(char: str, ok: bool) -> None:
    """キーが押された：沈んで戻る（ばね）。間違いは赤く光り、カメラが少し揺れる。"""
    name = "space" if char == " " else char
    k = kb_keys.get(name)
    if k is None:
        return
    mesh = k["mesh"]
    if GSAP is not None:
        GSAP.fromTo(mesh.position, js(y=k["base_y"] - 0.18), js(y=k["base_y"], duration=0.32, ease="elastic.out(1, 0.35)"))
    if ok:
        kb_state["streak"] += 1
    else:
        kb_state["streak"] = 0
        kb_state["shake"] = 0.25


def kb_refresh(game) -> None:
    """keyboard_view() の表を読んで、光るキー・赤いキー・手の位置を決める。"""
    kb_state["next"] = kb_state["miss"] = None
    for row in keyboard_view(game):
        for char, finger, state in row:
            k = kb_keys[char]
            top = k["top"]
            if state == "next":
                kb_state["next"] = char
                top.emissive.setHex(0xffe37a)
                top.emissiveIntensity = 0.8
            elif state == "miss":
                kb_state["miss"] = char
                top.emissive.setHex(0xd9463b)
                top.emissiveIntensity = 0.9
            else:
                top.emissiveIntensity = 0.0
    for finger, tip in kb_tips.items():             # 手：みんなホームへ。次に押す指だけキーの上へ
        tip["want"] = list(tip["home"])
        tip["mesh"].material = SKIN
    nxt = kb_state["next"]
    if nxt is not None:
        k = kb_keys[nxt]
        if k["finger"] == Finger.THUMB:
            tip = kb_tips[("thumb", "R")]
        else:
            tip = kb_tips[k["finger"]]
        tip["want"] = [k["x"], 0.85 + k.get("lift", 0.0), k["z"] + 0.1]
        tip["mesh"].material = SKIN_NEXT
        kb_glow.visible = True
        kb_glow.position.set(k["x"], KEY_HEIGHT / 2 + 0.02 + k.get("lift", 0.0), k["z"])
    else:
        kb_glow.visible = False


def kb_tick(dt: float) -> None:
    """毎コマ：指を目標へ、光を脈打たせ、揺れを減らす。"""
    kb_state["time"] += dt
    t = kb_state["time"]
    for tip in kb_tips.values():
        m = tip["mesh"]
        wx, wy, wz = tip["want"]
        m.position.x += (wx - m.position.x) * 0.22
        m.position.y += (wy + (0.08 * math.sin(t * 7) if tip["mesh"].material is SKIN_NEXT else 0.0) - m.position.y) * 0.22
        m.position.z += (wz - m.position.z) * 0.22
    for side, palm in zip(("L", "R"), kb_palms):    # 手のひらは指先の平均に付いていく
        fingers = [f for f in kb_tips if not isinstance(f, tuple) and f.name.startswith(side)]
        xs = [kb_tips[f]["mesh"].position.x for f in fingers]
        zs = [kb_tips[f]["mesh"].position.z for f in fingers]
        palm.position.x += (sum(xs) / len(xs) - palm.position.x) * 0.15
        palm.position.z += (sum(zs) / len(zs) + 2.0 - palm.position.z) * 0.15
    nxt = kb_state["next"]
    if nxt is not None:
        kb_keys[nxt]["top"].emissiveIntensity = 0.55 + 0.4 * math.sin(t * 6)
        kb_glow.material.opacity = 0.55 + 0.4 * math.sin(t * 6)
        kb_glow.rotation.z = t * 1.5
    kb_state["shake"] = max(0.0, kb_state["shake"] - dt)
    sx = 0.12 * math.sin(t * 80) * (kb_state["shake"] / 0.25) if kb_state["shake"] > 0 else 0.0
    zoom = 0.0 if kb_state["streak"] > 0 or kb_state["miss"] is None else 1.0   # 間違えた直後は少し寄る
    kb_state["zoom"] += (zoom - kb_state["zoom"]) * 0.08
    z = kb_state["zoom"]
    kb_camera.position.set(KB_CAM[0] + sx, KB_CAM[1] - 1.6 * z, KB_CAM[2] - 1.5 * z)
    kb_camera.lookAt(KB_LOOK[0] + sx, KB_LOOK[1], KB_LOOK[2])


kb_extra = []                                       # 各課題が足す毎コマの処理（g76 の言葉の板、g77 の苦手の高さ）


async def kb_loop():
    last = window.performance.now() / 1000
    while True:
        now = window.performance.now() / 1000
        dt = min(0.1, now - last)
        last = now
        kb_tick(dt)
        for fn in kb_extra:
            fn(dt)
        kb_renderer.render(kb_scene, kb_camera)
        await asyncio.sleep(1 / 30)


# --- ここから下はブラウザ版だけ。CLI 版の paint() / show() / run() にあたる ---

stage_label = document.querySelector("#stage")
name_label = document.querySelector("#name")
hits_label = document.querySelector("#hits")
misses_label = document.querySelector("#misses")
acc_label = document.querySelector("#acc")
kana_box = document.querySelector("#kana")
text_box = document.querySelector("#text")
next_box = document.querySelector("#next")
report_box = document.querySelector("#report")
message = document.querySelector("#message")
next_button = document.querySelector("#go")
ime_warning = document.querySelector("#ime")

FINGER_CLASS = {finger: f"f{n}" for n, finger in enumerate(Finger)}
sound_switch = document.querySelector("#sound")


class Speaker:
    """ブラウザで音を出す係。3 つの wav を data URI にして Audio に持たせておく。"""

    def __init__(self):
        self.made = {}
        for kind in BEEPS:
            uri = "data:audio/wav;base64," + base64.b64encode(beep_bytes(kind)).decode()
            self.made[kind] = window.Audio.new(uri)

    def say(self, kind: str | None) -> None:
        if kind is None or not sound_switch.checked:
            return
        sound = self.made[kind]
        sound.currentTime = 0
        sound.play()


game = Game()
speaker = Speaker()



def refresh() -> None:
    """CLI 版の show() にあたる。keyboard_view() の表をクラス名に写す。"""
    stage_label.textContent = f"{game.stage + 1} / {len(STAGES)}"
    name_label.textContent = STAGES[game.stage].name
    hits_label.textContent = str(game.hits)
    misses_label.textContent = str(game.misses)
    acc_label.textContent = f"{game.accuracy():.0%}"
    done = game.done_units()
    kana_box.innerHTML = ""
    for i, unit in enumerate(game.shown):
        span = document.createElement("span")
        span.className = "done" if i < done else ""
        span.textContent = "　" if unit == " " else unit
        kana_box.appendChild(span)
    hint = game.hint()
    text_box.innerHTML = ""
    for piece, cls in ((game.typed, "done"), (hint[:1], "cur"), (hint[1:], "")):
        for char in piece:
            span = document.createElement("span")
            span.className = cls
            span.textContent = "␣" if char == " " else char
            text_box.appendChild(span)
    if game.target is not None:
        key = KEYS[game.target]
        next_box.innerHTML = (f"次は <b>{'空白' if game.target == ' ' else game.target}</b> → "
                              f"<span class='{FINGER_CLASS[key.finger]} tag'>{key.finger.value}</span>")
    else:
        next_box.textContent = ""
    kb_refresh(game)                                # 3D のキーボードと手に写す
    report_box.textContent = "\n".join(report(game)) if game.done else ""
    message.textContent = game.message
    next_button.hidden = not game.done
    next_button.textContent = "つぎの段階へ →" if game.passed else "もう一度（別の文で）"


# --- 言葉の板が奥から迫ってくる（g76 だけ。2026-09-19）--------------------------------------
#   いま打つことばを 1 枚の板に描き、キーボードの奥から手前へ流す。打ち終わると板は上へ飛び去り、
#   次のことばが奥から来る。板が手前まで来ても判定は変わらない（赤くなって揺れるだけ）。
#   Python が持つのは「何番目のことばか」「いつ出たか」「どこまで打てたか」。絵は Three.js に任せる。

WORD_FAR, WORD_NEAR = (0.3, 2.1, -3.0), (0.3, 1.25, -0.5)   # 板の (x, y, z)：出発点と到着点（キーの奥、上の帯）
WORD_SECONDS_BASE, WORD_SECONDS_PER_KEY = 1.2, 0.55   # 到着までの時間 = 基本 + 字数 × これ

word_canvas = document.createElement("canvas")
word_canvas.width, word_canvas.height = 512, 128
word_tex = THREE.CanvasTexture.new(word_canvas)
word_tex.colorSpace = THREE.SRGBColorSpace
word_mat = THREE.MeshBasicMaterial.new(js(map=word_tex, transparent=True, side=THREE.DoubleSide))
word_board = THREE.Mesh.new(THREE.PlaneGeometry.new(6.4, 1.6), word_mat)
word_board.position.set(*WORD_FAR)
word_board.rotation.x = -0.45
kb_scene.add(word_board)
word_state = {"ident": None, "index": -1, "born": 0.0, "seconds": 1.0, "drawn": None, "flying": False, "flew": 0.0}


def word_index(game) -> int:
    """いま打っている「ことば」が文の何番目か（空白の単位で区切る）。"""
    return sum(1 for unit in game.units[:game.done_units()] if unit == " ")


def word_span(game, index: int) -> tuple[int, int]:
    """index 番目のことばが単位のどこからどこまでか。"""
    start = 0
    for n in range(index):
        start = game.units.index(" ", start) + 1
    end = game.units.index(" ", start) if " " in game.units[start:] else len(game.units)
    return start, end


def word_keys_left(game, index: int) -> int:
    """そのことばで、まだ打っていないローマ字の数（時間の目安に使う）。"""
    start, end = word_span(game, index)
    i, partial = game.best()
    total = 0
    for j in range(max(i, start), end):
        total += len(spellings(game.units, j)[0])
    return max(1, total - len(partial))


def draw_word(game, index: int, arrived: bool) -> None:
    """板の絵：かな（打った分は緑）と、その下にローマ字のおすすめの綴り。"""
    start, end = word_span(game, index)
    done = game.done_units()
    i, partial = game.best()
    ctx = word_canvas.getContext("2d")
    ctx.clearRect(0, 0, 512, 128)
    ctx.fillStyle = "rgba(217,70,59,0.92)" if arrived else "rgba(28,32,44,0.88)"
    ctx.beginPath()
    ctx.roundRect(4, 4, 504, 120, 18)
    ctx.fill()
    ctx.strokeStyle = "#ffe37a" if not arrived else "#ffffff"
    ctx.lineWidth = 4
    ctx.stroke()
    ctx.textAlign = "center"
    ctx.textBaseline = "middle"
    kana = "".join(game.shown[start:end])
    ctx.font = "bold 44px sans-serif"
    width = ctx.measureText(kana).width
    x = 256 - width / 2
    for j in range(start, end):                     # 単位ごとに色を変えて描く
        piece = game.shown[j]
        w = ctx.measureText(piece).width
        ctx.fillStyle = "#8fe39b" if j < done else "#ffffff"
        ctx.textAlign = "left"
        ctx.fillText(piece, x, 48)
        x += w
    romaji = "".join(spellings(game.units, j)[0] for j in range(start, end))
    typed = "".join(spellings(game.units, j)[0] for j in range(start, min(i, end))) + (partial if start <= i < end else "")
    ctx.font = "bold 32px monospace"
    ctx.textAlign = "center"
    ctx.fillStyle = "#c9d0dd"
    ctx.fillText(romaji, 256, 98)
    if typed:
        full = ctx.measureText(romaji).width
        ctx.textAlign = "left"
        ctx.fillStyle = "#8fe39b"
        ctx.fillText(typed, 256 - full / 2, 98)
    word_tex.needsUpdate = True
    word_state["drawn"] = (index, done, i, partial, arrived)


def word_fly_away() -> None:
    """打ち終えたことばの板は上へ飛び去る。"""
    word_state["flying"] = True
    word_state["flew"] = window.performance.now() / 1000
    if GSAP is not None:
        GSAP.to(word_board.position, js(y=word_board.position.y + 3.0, duration=0.35, ease="power2.in"))
        GSAP.to(word_board.rotation, js(x=-1.4, duration=0.35))


def word_tick(dt: float) -> None:
    """毎コマ：出てからの時間で z を決める。着いたら赤く揺れる。ことばが変われば奥から出直す。"""
    now = window.performance.now() / 1000
    if word_state["flying"]:
        if now - word_state["flew"] < 0.36:
            return                                  # 飛び去る途中。前の絵のまま
        word_state["flying"] = False
    if game.done:
        word_board.visible = False
        word_state["ident"] = None
        return
    index = word_index(game)
    ident = (game.stage, game.round, index)
    if ident != word_state["ident"]:                # 新しいことば：奥から出直す
        word_state.update(ident=ident, index=index, born=now, drawn=None)
        word_state["seconds"] = WORD_SECONDS_BASE + WORD_SECONDS_PER_KEY * word_keys_left(game, index)
        word_board.position.set(*WORD_FAR)
        word_board.rotation.x = -0.45
        word_board.visible = True
    progress = min(1.0, (now - word_state["born"]) / word_state["seconds"])
    arrived = progress >= 1.0
    i, partial = game.best()
    key = (index, game.done_units(), i, partial, arrived)
    if word_state["drawn"] != key:
        draw_word(game, index, arrived)
    fx, fy, fz = WORD_FAR
    nx, ny, nz = WORD_NEAR
    word_board.position.z = fz + (nz - fz) * progress
    word_board.position.y = fy + (ny - fy) * progress + 0.08 * math.sin(now * 3)
    word_board.position.x = nx + (0.15 * math.sin(now * 40) if arrived else 0.0)
    scale = 0.55 + 0.45 * progress                  # 近づくほど大きく
    word_board.scale.set(scale, scale, 1)


kb_extra.append(word_tick)


@when("click", "#go")
def go(event) -> None:
    speaker.say(obey(game, "enter", window.performance.now() / 1000))
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
        kb_note_start()
        beep = obey(game, key, window.performance.now() / 1000)
        if key in KEYS:
            kb_pressed(key, beep != "miss")
            if not (sound_switch.checked and kb_sound(key, beep != "miss")):
                speaker.say(beep)
            if beep != "miss" and (game.done or word_index(game) != word_state["index"]):
                word_fly_away()                     # ことばを打ち終えた：板が飛び去る
        else:
            speaker.say(beep)
        refresh()


document.querySelector("#loading").hidden = True
refresh()
asyncio.ensure_future(kb_loop())
