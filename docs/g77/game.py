"""タイピング3（記録と苦手キー）ブラウザ版

CLI 版（g77-type-record/main.py）と中身はまったく同じ。記録（Record・History）も、苦手キーで
重みづけする出題（drill）も、綴りのゆれを受ける判定（Game・obey）も 1 文字も変えていない。
記録の置き場だけ違う：端末は records.json、ブラウザは localStorage。**中身の形（History.dump）は同じ**。

違うのは入口と出口だけ。
  入口: 端末はキー 1 文字、ブラウザは keydown。どちらも obey() に入る
  出口: 端末は keyboard_view() を色つきの字に、ブラウザは同じ表を <div> にする。
        時計は端末が time.perf_counter()、ブラウザが performance.now()。
        どちらも obey() に「いま」を渡すだけで、中では時計を読まない。

音（beep_bytes）も同じ。端末は wav をファイルにして afplay へ、ブラウザは data URI にして Audio へ。
持ってこなかったのは端末の描画（paint / show / run）と Speaker と検査だけ。
"""

import base64
import io
import json
import math
import random
import re
import string
import wave
from array import array
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from heapq import nlargest
from itertools import product
from statistics import fmean, median

from pyscript import document, when, window
PASS = 0.95                                         # 次の段階へ行ける正確さ


WORDS_PER_DRILL = 5                                 # 1 回の練習に出すことばの数（文は 2 つ）


WEAK_TOP = 5                                        # 「苦手」として扱うキーの数


WEAK_WEIGHT = 3                                     # 苦手キー 1 つにつき、ことばの重みをこれだけ足す


KEEP_RECORDS = 200                                  # 記録を残す数


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
    Stage("にがてなキー", (), WORDS_PER_DRILL),      # ことばは全段階から。苦手キーで重みづけ
)


def romaji_of(kana: str) -> str:
    """ことばのおすすめの綴り（重みづけに使う）。"""
    units = units_of(kana)
    return "".join(spellings(units, i)[0] for i in range(len(units)))


def drill(index: int, seed: int = 0, weak: str = "") -> str:
    """段階 index の練習文。ことばを空白でつなぐ。

    乱数の種を固定してあるので、同じ段階・同じ回・同じ苦手キーなら端末でもブラウザでも同じ文。
    「にがてなキー」の段階だけは、苦手キーを多く含むことばほど出やすくする。
    """
    luck = random.Random(seed * 100 + index)
    stage = STAGES[index]
    if stage.words:
        return " ".join(luck.sample(stage.words, stage.count))
    pool = [word for other in STAGES[:2] for word in other.words]     # ことばだけ（文は除く）
    weights = [1 + WEAK_WEIGHT * sum(romaji_of(word).count(key) for key in weak) for word in pool]
    picked: list[str] = []
    while len(picked) < stage.count:                # 同じことばは 2 度出さない
        word = luck.choices(pool, weights)[0]
        if word not in picked:
            picked.append(word)
    return " ".join(picked)


@dataclass
class Record:
    """1 回の練習の記録。when は「2026-09-10T14:30」の形（ISO）。"""

    when: str
    stage: str
    hits: int
    misses: int
    accuracy: float
    per_minute: float

    def day(self) -> str:
        """日付だけ。fromisoformat で読み戻してから整える。"""
        return datetime.fromisoformat(self.when).strftime("%m/%d")


@dataclass
class History:
    """これまでの記録と、キーごとのミス。端末はファイル、ブラウザは localStorage に置く。"""

    records: list[Record] = field(default_factory=list)
    weak: Counter = field(default_factory=Counter)  # 押すべきだったキー → ミスの数

    def weak_keys(self) -> str:
        """苦手なキー、多い順に WEAK_TOP 個。"""
        return "".join(key for key, _ in self.weak.most_common(WEAK_TOP))

    def best(self) -> float:
        """自己ベスト（1 分あたり）。"""
        return max((row.per_minute for row in self.records), default=0.0)

    def usual(self) -> float:
        """いつもの速さ。平均だと 1 回の大当たりに引きずられるので中央値。"""
        return median(row.per_minute for row in self.records) if self.records else 0.0

    def top(self, n: int = 3) -> list[Record]:
        """速かった順に n 件。nlargest は「全部並べ替えずに上位だけ取る」道具。"""
        return nlargest(n, self.records, key=lambda row: row.per_minute)

    def add(self, row: Record) -> None:
        self.records.append(row)
        del self.records[:-KEEP_RECORDS]

    def dump(self) -> str:
        """字にする。端末もブラウザも同じ形で残す。"""
        return json.dumps({"records": [asdict(row) for row in self.records],
                           "weak": dict(self.weak)}, ensure_ascii=False, indent=1)

    @staticmethod
    def parse(text: str) -> "History":
        """字から戻す。壊れていたら空から始める。"""
        try:
            data = json.loads(text)
            return History([Record(**row) for row in data["records"]], Counter(data["weak"]))
        except (ValueError, KeyError, TypeError):
            return History()


@dataclass
class Game:
    """練習の状態。端末もブラウザもこれ 1 つを進める。"""

    stage: int = 0
    round: int = 0                                  # その段階で何回目か
    history: History = field(default_factory=History)
    recorded: bool = False                          # この回をもう記録したか
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
        self.kana = drill(self.stage, self.round, self.history.weak_keys())
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
        self.recorded = False
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
        self.history.weak[self.target] += 1         # 押すべきだったキーを苦手として数える
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

    def record(self, when: str) -> Record | None:
        """終わった回を記録に足す。when は外から渡す（中で時計を読まない）。1 回だけ。"""
        if not self.done or self.recorded:
            return None
        row = Record(when, STAGES[self.stage].name, self.hits, self.misses,
                     round(self.accuracy(), 3), round(self.per_minute(), 1))
        self.history.add(row)
        self.recorded = True
        return row

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
    """終わったときの成績。これまでの記録と比べる。"""
    story = game.history
    lines = [
        f"打鍵 {game.hits}  ミス {game.misses}  正確さ {game.accuracy():.0%}  "
        f"{game.seconds():.1f} 秒  1 分あたり {game.per_minute():.0f} 打",
    ]
    if len(story.records) > 1:
        note = "自己ベスト！" if game.per_minute() >= story.best() else ""
        lines.append(f"自己ベスト {story.best():.0f} 打  いつも {story.usual():.0f} 打  "
                     f"（{len(story.records)} 回め）{note}")
    if game.miss_by:
        worst = sorted(game.miss_by.items(), key=lambda kv: -kv[1])
        lines.append("ミスの多い指: " + "  ".join(f"{name} {n}" for name, n in worst[:3]))
    if story.weak:
        lines.append("苦手なキー: " + "  ".join(f"{key} {n}" for key, n in story.weak.most_common(WEAK_TOP)))
    return lines


# --- ここから下はブラウザ版だけ。CLI 版の paint() / show() / run() にあたる ---

stage_label = document.querySelector("#stage")
name_label = document.querySelector("#name")
hits_label = document.querySelector("#hits")
misses_label = document.querySelector("#misses")
acc_label = document.querySelector("#acc")
kana_box = document.querySelector("#kana")
text_box = document.querySelector("#text")
next_box = document.querySelector("#next")
board = document.querySelector("#board")
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


SAVED = "g77-history"


def load_history() -> History:
    """CLI 版は records.json、こちらは localStorage。中身の形は同じ。"""
    return History.parse(window.localStorage.getItem(SAVED) or "")


def now_text() -> str:
    """いまの時刻を「2026-09-10T14:30」の形で。ブラウザの時計（その土地の時刻）から組む。"""
    d = window.Date.new()
    return f"{d.getFullYear()}-{d.getMonth() + 1:02d}-{d.getDate():02d}T{d.getHours():02d}:{d.getMinutes():02d}"


game = Game(history=load_history())
speaker = Speaker()
record_list = document.querySelector("#records")


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
    for row in keyboard_view(game):
        for char, finger, state in row:
            cell = board.querySelector(f'[data-key="{char}"]')
            cell.className = f"key {FINGER_CLASS[finger]} {state}" + (" space" if char == "space" else "")
    report_box.textContent = "\n".join(report(game)) if game.done else ""
    rows = game.history.records[-8:][::-1]
    record_list.textContent = "\n".join(
        f"{row.when.replace('T', ' ')}  {row.stage:8s}  正確さ {row.accuracy:.0%}  {row.per_minute:4.0f} 打/分"
        for row in rows) or "—"
    message.textContent = game.message
    next_button.hidden = not game.done
    last = game.stage + 1 >= len(STAGES)
    next_button.textContent = ("もう一度（にがてなキー）" if last else
                               "つぎの段階へ →" if game.passed else "もう一度（別の文で）")


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
        speaker.say(obey(game, key, window.performance.now() / 1000))
        if game.done and not game.recorded:         # 時刻はここで読んで渡す
            game.record(now_text())
            window.localStorage.setItem(SAVED, game.history.dump())
        refresh()


build_board()
document.querySelector("#loading").hidden = True
refresh()
