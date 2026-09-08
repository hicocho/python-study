"""推理ゲーム風（証言の矛盾と告発）ブラウザ版

CLI 版（g63-mystery-verdict/main.py）と、場所・人・手がかり・条件の判定はまったく同じ。
Sprite / Screen、家具の組み立て、Clues（Set の継承）、世界のデータ、手がかりのグラフ（graphlib）、
推理ノートの絵、証言と突きつけ、告発の採点、そして class Game を、
ステップの目印コメント（# ←）を外しただけで 1 文字も変えずに持ってきている。

持ってこなかったのは端末に描く Screen.render() と、それを使う play() / main() だけ。
入口は番号のボタン、出口は canvas と HTML の文章窓。日本語はブラウザのフォントで出す
（ドット絵のフォントでは漢字を出せないので、絵と文章を上下に分けている）。
"""

import base64
import struct
import zlib
from collections import deque
from collections.abc import Set
from graphlib import CycleError, TopologicalSorter
from itertools import batched, combinations, filterfalse
from copy import replace
from dataclasses import KW_ONLY, dataclass, field, fields
from functools import cache
from string import Template
from typing import NewType

from js import localStorage
from pyscript import document, when

WIDTH = 126                                         # 絵の横幅（ドット）。端末では 1 ドット = 1 桁
HEIGHT = 72                                         # 絵の高さ。端末では 2 ドット = 1 行 → 36 行
FLOOR_Y = 56                                        # 床の高さ。ここから下が床で、上が壁や空


PALETTE = {
    "K": (16, 16, 24), "W": (240, 240, 235), "G": (120, 120, 130), "D": (70, 70, 80),
    "N": (110, 78, 48), "M": (78, 54, 34), "R": (190, 60, 60), "B": (60, 100, 190),
    "Y": (230, 200, 90), "C": (120, 200, 220), "L": (250, 240, 180), "S": (150, 190, 150),
    "P": (200, 150, 170), "O": (220, 140, 70),
}


PlaceId = NewType("PlaceId", str)                   # 場所の名札。ただの str だが、型は別物として扱われる
PersonId = NewType("PersonId", str)                 # 人の名札
ClueId = NewType("ClueId", str)                     # 手がかりの名札


@dataclass(frozen=True)
class Sprite:
    """ドット絵 1 枚。rows は 1 行 1 文字列で、文字がパレットの色、. が透明。"""

    name: str
    rows: tuple[str, ...]
    palette: dict[str, tuple[int, int, int]] = field(default_factory=lambda: PALETTE, hash=False, compare=False)

    @property
    def width(self) -> int:
        return len(self.rows[0])

    @property
    def height(self) -> int:
        return len(self.rows)

    @property
    def pixels(self) -> list[tuple[int, int, tuple[int, int, int]]]:
        """(x, y, 色) の一覧。透明は含まない。"""
        return [(x, y, self.palette[ch]) for y, row in enumerate(self.rows) for x, ch in enumerate(row) if ch != "."]

    def __str__(self) -> str:
        return "\n".join(self.rows)


def sprite(name: str, art: str) -> Sprite:
    """三重引用符のドット絵から Sprite を作る。空行は無視、幅は最長の行にそろえる。"""
    rows = [line for line in art.splitlines() if line.strip()]
    width = max(len(r) for r in rows)
    return Sprite(name, tuple(r.ljust(width, ".") for r in rows))


DIGIT_FLAT = {
    "0": "WWWW.WW.WW.WWWW", "1": ".W.WW..W..W.WWW", "2": "WWW..WWWWW..WWW", "3": "WWW..WWWW..WWWW",
    "4": "W.WW.WWWW..W..W", "5": "WWWW..WWW..WWWW", "6": "WWWW..WWWW.WWWW", "7": "WWW..W..W..W..W",
    "8": "WWWW.WWWWW.WWWW", "9": "WWWW.WWWW..WWWW",
}


DIGITS = {ch: Sprite(f"digit-{ch}", tuple("".join(row) for row in batched(flat, 3)))   # 15 文字を 3 文字ずつ 5 行に
          for ch, flat in DIGIT_FLAT.items()}


class Screen:
    """WIDTH × HEIGHT のドットのキャンバス。1 ドットは RGB か None（黒）。"""

    def __init__(self):
        self.pixels: list[list[tuple[int, int, int] | None]] = [[None] * WIDTH for _ in range(HEIGHT)]

    def clear(self) -> None:
        for row in self.pixels:
            row[:] = [None] * WIDTH

    def plot(self, x: int, y: int, color: tuple[int, int, int]) -> None:
        if 0 <= x < WIDTH and 0 <= y < HEIGHT:
            self.pixels[y][x] = color

    def blit(self, spr: Sprite, x: float, y: float) -> None:
        """スプライトを (x, y) を左上にして置く。透明は上書きしない。"""
        ox, oy = round(x), round(y)
        for px, py, color in spr.pixels:
            self.plot(ox + px, oy + py, color)

    def text(self, s: str, x: int, y: int) -> None:
        """3×5 の数字で文字列を描く。数字以外は空ける。"""
        for i, ch in enumerate(s):
            if ch in DIGITS:
                self.blit(DIGITS[ch], x + i * 4, y)

    def render(self) -> str:
        """端末用の文字列。1 行に 2 ドット分の行を詰める（上が前景 ▀、下が背景）。色が変わるときだけエスケープを出す。"""
        out = []
        last = None
        for top, bottom in zip(self.pixels[0::2], self.pixels[1::2]):
            for a, b in zip(top, bottom):
                if a is None and b is None:
                    code, ch = "\x1b[0m", " "
                elif b is None:
                    code, ch = f"\x1b[0m\x1b[38;2;{a[0]};{a[1]};{a[2]}m", "▀"
                elif a is None:
                    code, ch = f"\x1b[0m\x1b[38;2;{b[0]};{b[1]};{b[2]}m", "▄"
                else:
                    code, ch = f"\x1b[38;2;{a[0]};{a[1]};{a[2]}m\x1b[48;2;{b[0]};{b[1]};{b[2]}m", "▀"
                if code != last:
                    out.append(code)
                    last = code
                out.append(ch)
            out.append("\x1b[0m\n")
            last = None
        return "".join(out)


def png_bytes(spr: Sprite, scale: int = 1, background: tuple[int, int, int] | None = None) -> bytes:
    """スプライトを PNG に。ライブラリなしで、チャンクを struct と zlib で組み立てる。background が無ければ透明。"""
    w, h = spr.width * scale, spr.height * scale
    colors = {(x, y): c for x, y, c in spr.pixels}
    blank = bytes(background) + b"\xff" if background else b"\x00\x00\x00\x00"
    raw = bytearray()
    for y in range(h):
        raw.append(0)                                       # フィルタ 0（そのまま）
        for x in range(w):
            c = colors.get((x // scale, y // scale))
            raw += bytes(c) + b"\xff" if c else blank

    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

    header = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)   # 8 ビット、RGBA
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b"")


@cache
def data_uri(spr: Sprite, scale: int = 1) -> str:
    """ブラウザで <img src=...> に入れる文字列。同じスプライトは一度だけ作る。"""
    return "data:image/png;base64," + base64.b64encode(png_bytes(spr, scale)).decode()


class Clues(Set):
    """集めた手がかり。集合として振る舞う。

    collections.abc.Set を継承すると、__contains__ と __iter__ と __len__ の
    3 つを書くだけで、& | - ^ と <= （部分集合）が付いてくる。
    「この話を聞くのに必要な手がかりが揃っているか」が required <= clues の 1 行で書ける。
    """

    def __init__(self, ids=()):
        self.ids: set[ClueId] = set(ids)

    def __contains__(self, clue: object) -> bool:
        return clue in self.ids

    def __iter__(self):
        return iter(self.ids)

    def __len__(self) -> int:
        return len(self.ids)

    def _from_iterable(self, it):
        """& や | が新しい Clues を作れるようにする（Set が使う入口）。"""
        return Clues(it)

    def add(self, clue: ClueId) -> bool:
        """新しければ足して True。もう持っていれば False。"""
        if clue in self.ids:
            return False
        self.ids.add(clue)
        return True


@dataclass(frozen=True)
class Clue:
    """手がかり 1 つ。"""

    id: ClueId
    _: KW_ONLY                                      # ここから下はキーワードでしか渡せない
    name: str                                       # 手がかり帳に出る名前
    text: str                                       # 見つけたときの文


@dataclass(frozen=True)
class Spot:
    """場所の中の「調べられるもの」。"""

    name: str
    _: KW_ONLY
    text: str                                       # 調べたときの文（$ で人の名前を埋められる）
    gives: ClueId | None = None                     # 見つかる手がかり
    needs: frozenset[ClueId] = frozenset()          # これが揃うまでは別の文になる
    locked: str = ""                                # 揃っていないときの文


@dataclass(frozen=True)
class Topic:
    """人に聞ける話 1 つ。"""

    name: str
    _: KW_ONLY
    text: str
    gives: ClueId | None = None
    needs: frozenset[ClueId] = frozenset()


@dataclass(frozen=True)
class Person:
    """その場にいる人。"""

    id: PersonId
    _: KW_ONLY
    name: str
    face: str                                       # 絵に置く人影の色の文字
    topics: tuple[Topic, ...] = ()


@dataclass(frozen=True)
class Place:
    """場所 1 つ。絵は「何をどこに置くか」の並びで作る。"""

    id: PlaceId
    _: KW_ONLY
    name: str
    text: str                                       # 着いたときの文
    sky: tuple[int, int, int]                       # 上半分の色
    floor: tuple[int, int, int]                     # 床の色
    scene: tuple[tuple[str, int, int], ...] = ()    # (家具の名前, x, y)
    stand: tuple[int, ...] = (16, 46, 76)           # 人が立つ x。家具と重ならない所を選ぶ
    spots: tuple[Spot, ...] = ()
    people: tuple[PersonId, ...] = ()
    exits: tuple[PlaceId, ...] = ()


def boxes_sprite(name: str, width: int, height: int,
                 boxes: tuple[tuple[int, int, int, int, str], ...]) -> Sprite:
    """長方形をいくつか重ねて 1 枚の絵にする。

    机や窓やビルはドット絵で 1 ドットずつ描くより、長方形の重ね合わせの方が短く、
    寸法も変えやすい。後ろに書いた長方形が上に重なる。
    """
    rows = [["."] * width for _ in range(height)]
    for bx, by, bw, bh, ch in boxes:
        for y in range(by, min(by + bh, height)):
            for x in range(bx, min(bx + bw, width)):
                rows[y][x] = ch
    return Sprite(name, tuple("".join(row) for row in rows))


FURNITURE: dict[str, tuple[int, int, tuple[tuple[int, int, int, int, str], ...]]] = {
    "desk": (30, 16, ((0, 0, 30, 4, "N"), (2, 4, 26, 3, "M"), (3, 7, 3, 9, "M"), (24, 7, 3, 9, "M"))),
    "chair": (12, 20, ((1, 0, 3, 13, "M"), (1, 11, 10, 3, "N"), (2, 14, 2, 6, "M"), (8, 14, 2, 6, "M"))),
    "fallen": (20, 10, ((0, 0, 3, 10, "M"), (2, 3, 13, 3, "N"), (14, 0, 2, 5, "M"), (14, 6, 2, 4, "M"))),
    "window": (30, 24, ((0, 0, 30, 24, "D"), (2, 2, 12, 20, "C"), (16, 2, 12, 20, "C"))),
    "door": (18, 34, ((0, 0, 18, 34, "M"), (2, 2, 14, 30, "N"), (13, 16, 2, 3, "Y"))),
    "safe": (18, 18, ((0, 0, 18, 18, "G"), (2, 2, 14, 14, "D"), (11, 8, 4, 3, "Y"))),
    "shelf": (24, 30, ((0, 0, 24, 30, "M"), (2, 2, 20, 6, "N"), (2, 11, 20, 6, "N"), (2, 20, 20, 6, "N"))),
    "counter": (44, 14, ((0, 0, 44, 4, "N"), (1, 4, 42, 10, "M"))),
    "plant": (14, 24, ((5, 0, 4, 14, "S"), (1, 4, 12, 4, "S"), (3, 14, 8, 10, "O"))),
    "sofa": (34, 16, ((0, 0, 34, 6, "P"), (0, 5, 34, 11, "R"), (0, 4, 4, 12, "P"), (30, 4, 4, 12, "P"))),
    "bottles": (30, 20, ((0, 16, 30, 4, "M"), (2, 4, 3, 12, "S"), (8, 2, 3, 14, "Y"), (14, 5, 3, 11, "R"),
                         (20, 3, 3, 13, "C"), (26, 6, 3, 10, "O"))),
    "building": (28, 46, ((0, 0, 28, 46, "D"), (4, 4, 6, 6, "L"), (16, 4, 6, 6, "L"),
                          (4, 14, 6, 6, "L"), (16, 14, 6, 6, "K"), (4, 24, 6, 6, "K"), (16, 24, 6, 6, "L"))),
    "lamp": (8, 40, ((3, 6, 2, 34, "G"), (0, 0, 8, 6, "L"))),
    "car": (38, 14, ((0, 6, 38, 8, "B"), (6, 0, 24, 7, "C"), (4, 11, 6, 3, "K"), (28, 11, 6, 3, "K"))),
    "body": (34, 12, ((0, 0, 34, 2, "W"), (0, 10, 34, 2, "W"), (0, 0, 2, 12, "W"), (32, 0, 2, 12, "W"),
                       (4, 4, 6, 6, "S"), (11, 3, 16, 7, "D"))),
    "board": (26, 18, ((0, 0, 26, 18, "M"), (2, 2, 22, 14, "W"))),
}
PIECES = {name: boxes_sprite(name, w, h, boxes) for name, (w, h, boxes) in FURNITURE.items()}


@cache
def figure(color: str) -> Sprite:
    """人影 1 人。色の文字だけを変えて使い回す。"""
    return boxes_sprite(f"figure-{color}", 14, 30,
                        ((5, 0, 5, 5, "S"), (3, 5, 9, 13, color), (4, 18, 3, 12, "D"), (8, 18, 3, 12, "D")))


CAST = {"detective": "あなた", "assistant": "三沢", "victim": "北浦"}


CLUES: dict[ClueId, Clue] = {c.id: c for c in (
    Clue(ClueId("watch"), name="止まった腕時計", text="$victim さんの腕時計。9 時 40 分で止まっている。"),
    Clue(ClueId("safe"), name="開いた金庫", text="金庫の扉が開いている。中は空だ。"),
    Clue(ClueId("latch"), name="外れた窓の掛け金", text="窓の掛け金が外れている。内側からしか外せない。"),
    Clue(ClueId("bill"), name="借金の督促状", text="$victim さん宛ての督促状。会社ではなく個人あての借金だ。"),
    Clue(ClueId("log"), name="日曜の入館記録", text="日曜の夜、$victim さんのほかに 2 人が入館している。"),
    Clue(ClueId("fired"), name="三国の解雇", text="三国 徹は先月クビになっている。"),
    Clue(ClueId("quarrel"), name="社長と専務の口論", text="堂島専務と $victim さんが、金のことで言い争っていた。"),
    Clue(ClueId("alibi"), name="堂島のアリバイ", text="堂島専務は 9 時半に会社を出たと言う。"),
    Clue(ClueId("money"), name="使い込み", text="会社の金が 3 年かけて抜かれている。$victim さん自身の手で。"),
    Clue(ClueId("met"), name="三国が会っていた相手", text="三国はあの夜、酒場で誰かと会っていた。相手は顔を隠していた。"),
    Clue(ClueId("camera"), name="防犯カメラ", text="街角のカメラ。会社の裏口が写る向きだ。"),
    Clue(ClueId("dojima_true"), name="堂島の言い直し", text="堂島は 10 時まで社内にいた。金庫を見に戻ったという。"),
    Clue(ClueId("hayase_admits"), name="早瀬の告白", text="早瀬はあの晩、社長室にいたと認めた。"),
)}


WordId = NewType("WordId", str)                     # 証言の名札


@dataclass(frozen=True)
class Word:
    """証言 1 つ。「誰について・いつ・どこにいたか」を主張する。

    この 3 つを揃えて持つから、2 つ並べて食い違いを見つけられる。
    """

    id: WordId
    _: KW_ONLY
    speaker: str                                    # 言った人
    about: str                                      # 誰について
    when: str                                       # いつ
    where: str                                      # どこに
    text: str                                       # 証言帳に出る文


@dataclass(frozen=True)
class Fix:
    """食い違いを突きつけたときに起きること。"""

    _: KW_ONLY
    text: str                                       # 突きつけたときの台詞
    revise: WordId                                  # 言い直させる証言
    where: str                                      # 言い直したあとの場所
    said: str                                       # 言い直したあとの文
    adds: tuple[WordId, ...] = ()                   # 新しく出てくる証言
    gives: ClueId | None = None                     # 手に入る手がかり
    needs: frozenset[ClueId] = frozenset()          # そこへ辿り着くのに要る手がかり


WORDS: dict[WordId, Word] = {w.id: w for w in (
    Word(WordId("dojima_out"), speaker="堂島", about="堂島", when="9 時半すぎ", where="会社の外",
         text="堂島「9 時半には会社を出た」"),
    Word(WordId("camera"), speaker="防犯カメラ", about="堂島", when="9 時半すぎ", where="会社の裏口",
         text="カメラの記録「9 時 50 分、堂島が裏口に立っている」"),
    Word(WordId("hayase_seen"), speaker="堂島", about="早瀬", when="9 時半すぎ", where="社長室の前",
         text="堂島「そのとき、経理の早瀬さんが社長室から出てきた」"),
    Word(WordId("hayase_home"), speaker="早瀬", about="早瀬", when="9 時半すぎ", where="自宅",
         text="早瀬「その時間は家にいました」"),
    Word(WordId("mikuni_bar"), speaker="三国", about="三国", when="9 時半すぎ", where="酒場",
         text="三国「ここで飲んでました。中には入ってない」"),
    Word(WordId("akiba_morning"), speaker="秋葉", about="北浦", when="翌朝", where="社長室",
         text="秋葉「朝、鍵を開けたら社長が倒れていて……」"),
)}


CLUE_WORD: dict[ClueId, WordId] = {
    ClueId("alibi"): WordId("dojima_out"),
    ClueId("camera"): WordId("camera"),
    ClueId("money"): WordId("hayase_home"),
    ClueId("met"): WordId("mikuni_bar"),
    ClueId("watch"): WordId("akiba_morning"),
}


CONFRONTS: dict[frozenset[WordId], Fix] = {
    frozenset({WordId("dojima_out"), WordId("camera")}): Fix(
        text="堂島「……分かった。9 時半に出たというのは嘘だ。金庫が気になって戻った」",
        revise=WordId("dojima_out"), where="社長室のあたり",
        said="堂島「10 時までいた。金庫が気になって戻ったんだ」",
        adds=(WordId("hayase_seen"),), gives=ClueId("dojima_true"),
        needs=frozenset({ClueId("alibi"), ClueId("camera")})),
    frozenset({WordId("hayase_seen"), WordId("hayase_home")}): Fix(
        text="早瀬「……見られていたんですね」",
        revise=WordId("hayase_home"), where="社長室",
        said="早瀬「あの晩、社長室にいました」",
        gives=ClueId("hayase_admits"),
        needs=frozenset({ClueId("dojima_true"), ClueId("money")})),
}


def clash(a: Word, b: Word) -> bool:
    """2 つの証言が両立しないか。同じ人の同じ時刻について、違う場所を言っている。"""
    return a.about == b.about and a.when == b.when and a.where != b.where


@dataclass(frozen=True)
class Verdict:
    """告発の中身。metadata に見出し・配点・選択肢を持たせ、fields() から画面も採点表も作る。"""

    culprit: str = field(metadata={
        "label": "犯人は誰か", "points": 40,
        "options": ("秋葉 涼子", "堂島 健", "早瀬 睦", "三国 徹")})
    entry: str = field(metadata={
        "label": "どうやって社長室に入ったか", "points": 20,
        "options": ("合鍵でドアから", "窓から", "裏口から", "もともと中にいた")})
    escape: str = field(metadata={
        "label": "どうやって出たか", "points": 20,
        "options": ("窓から", "ドアから", "裏口から", "出ていない")})
    motive: str = field(metadata={
        "label": "動機は何か", "points": 20,
        "options": ("金庫の金", "使い込みの口封じ", "解雇の恨み", "会社の乗っ取り")})


TRUTH = Verdict("早瀬 睦", "合鍵でドアから", "窓から", "使い込みの口封じ")


ENDINGS = (
    (100, "真相", "早瀬は認めた。社長の使い込みを 3 年ぶん帳簿で隠し続け、いつか自分が罪を"
                  "被ると知っていた。あの晩、合鍵で入って詰め寄り、突き飛ばした社長は机の角に頭を打った。"
                  "内側から鍵を掛けて、窓から出た——掛け金を戻し忘れて。"),
    (60, "半分", "指し示した先は当たっていたが、筋が通らなかった。証拠が足りない。"),
    (0, "誤認", "見当違いだった。真犯人は今も街のどこかにいる。"),
)


def judge(answer: Verdict) -> tuple[int, list[str], str, str]:
    """告発を採点する。fields() の metadata から配点を読むので、項目を増やしても直すのはここではない。"""
    total = 0
    marks = []
    for f in fields(Verdict):
        mine, right = getattr(answer, f.name), getattr(TRUTH, f.name)
        ok = mine == right
        total += f.metadata["points"] if ok else 0
        marks.append(f"{f.metadata['label']}: {mine} … {'○' if ok else '× （' + right + '）'}")
    for need, name, text in ENDINGS:
        if total >= need:
            return total, marks, name, text
    return total, marks, "誤認", ENDINGS[-1][2]


PEOPLE: dict[PersonId, Person] = {p.id: p for p in (
    Person(PersonId("misawa"), name="三沢", face="B", topics=(
        Topic("事件のこと", text="$assistant「日曜の夜、みなと商事の社長室で $victim さんが亡くなりました。ドアは内側から鍵がかかっていたそうです」"),
        Topic("これから", text="$assistant「まずは社長室ですね。それから会社の人たちに話を聞きましょう」"),
    )),
    Person(PersonId("akiba"), name="秋葉 涼子", face="P", topics=(
        Topic("第一発見者として", text="秋葉「朝、鍵を開けたら社長が倒れていて……ドアはたしかに内側から掛かっていました」"),
        Topic("日曜の夜のこと", needs=frozenset({ClueId("log")}),
              text="秋葉「入館記録……ええ、堂島専務が来ていました。もうひとりは、たぶん三国さんです」",
              gives=ClueId("fired")),
        Topic("社長と専務", needs=frozenset({ClueId("fired")}),
              text="秋葉「先週、社長室から怒鳴り声が。お金のことだったと思います」",
              gives=ClueId("quarrel")),
    )),
    Person(PersonId("dojima"), name="堂島 健", face="R", topics=(
        Topic("日曜の夜", text="堂島「9 時半には会社を出た。守衛に聞いてくれてかまわん」", gives=ClueId("alibi")),
        Topic("口論のこと", needs=frozenset({ClueId("quarrel")}),
              text="堂島「……金の話だ。会社の金が減っていた。わたしは問いただしただけだ」"),
        Topic("腕時計のこと", needs=frozenset({ClueId("watch"), ClueId("alibi")}),
              text="堂島「9 時 40 分？ わたしはもう電車の中だ。……疑うのか」"),
    )),
    Person(PersonId("hayase"), name="早瀬 睦", face="C", topics=(
        Topic("経理として", text="早瀬「わたしは数字を合わせるだけです。合わない数字も、ありましたけど」"),
        Topic("会社の金", needs=frozenset({ClueId("safe"), ClueId("bill")}),
              text="早瀬「3 年です。少しずつ、社長ご自身が。金庫の中身も、たぶんもう」",
              gives=ClueId("money")),
    )),
    Person(PersonId("mikuni"), name="三国 徹", face="Y", topics=(
        Topic("解雇のこと", needs=frozenset({ClueId("fired")}),
              text="三国「クビですよ。10 年働いて。……恨んでないと言えば嘘になる」"),
        Topic("日曜の夜", needs=frozenset({ClueId("log")}),
              text="三国「会社？ 行きましたよ。でも中には入ってない。ここで飲んでました」"),
    )),
)}


PLACES: dict[PlaceId, Place] = {p.id: p for p in (
    Place(PlaceId("office"), name="探偵事務所", text="$assistant が窓ぎわで待っている。",
          sky=(60, 60, 80), floor=(90, 70, 55),
          scene=(("window", 12, 14), ("desk", 60, 40), ("chair", 96, 36)), stand=(46,),
          people=(PersonId("misawa"),), exits=(PlaceId("company"), PlaceId("street"))),
    Place(PlaceId("company"), name="みなと商事 受付", text="受付。奥に社長室の扉が見える。",
          sky=(70, 75, 95), floor=(120, 115, 105),
          scene=(("counter", 6, 42), ("plant", 60, 32), ("board", 82, 12), ("door", 104, 22)), stand=(20,),
          spots=(
              Spot("受付の記録", text="日曜の入館記録が残っていた。", gives=ClueId("log")),
              Spot("掲示板", text="社員旅行の写真。$victim さんが真ん中で笑っている。"),
          ),
          people=(PersonId("akiba"),), exits=(PlaceId("office"), PlaceId("room"), PlaceId("meeting"), PlaceId("street"))),
    Place(PlaceId("room"), name="社長室（現場）", text="ここで $victim さんが見つかった。",
          sky=(55, 50, 60), floor=(100, 80, 60),
          scene=(("window", 8, 10), ("desk", 60, 38), ("safe", 100, 38), ("fallen", 30, 46), ("body", 8, 58)),
          spots=(
              Spot("倒れていた場所", text="床に白い線。そばに腕時計が落ちていた。", gives=ClueId("watch")),
              Spot("金庫", text="金庫が開いている。中は空だ。", gives=ClueId("safe")),
              Spot("窓", text="掛け金が外れている。だが窓は閉まっていた。", gives=ClueId("latch")),
              Spot("机の引き出し", text="督促状が一枚。$victim さん個人あての借金だ。", gives=ClueId("bill")),
              Spot("ドア", needs=frozenset({ClueId("latch")}),
                   locked="頑丈なドアだ。内側から鍵が掛かっていたという。",
                   text="鍵穴に傷。合鍵を差した跡かもしれない。"),
          ),
          exits=(PlaceId("company"),)),
    Place(PlaceId("meeting"), name="会議室", text="専務と経理が向かい合っている。",
          sky=(80, 80, 90), floor=(115, 110, 100),
          scene=(("window", 94, 12), ("desk", 30, 42), ("chair", 8, 38)), stand=(62, 78),
          people=(PersonId("dojima"), PersonId("hayase")),
          exits=(PlaceId("company"),)),
    Place(PlaceId("bar"), name="酒場 ひまわり", text="昼から灯りがついている。",
          sky=(45, 35, 45), floor=(85, 60, 45),
          scene=(("bottles", 10, 18), ("counter", 4, 44), ("plant", 100, 32)), stand=(78,),
          spots=(
              Spot("カウンター", needs=frozenset({ClueId("fired")}),
                   locked="マスターは黙ってグラスを拭いている。",
                   text="マスター「三国さん？ 日曜も来てましたよ。連れがいましてね、帽子で顔を隠して」",
                   gives=ClueId("met")),
          ),
          people=(PersonId("mikuni"),), exits=(PlaceId("street"),)),
    Place(PlaceId("street"), name="街角", text="みなと商事の裏手に出た。",
          sky=(90, 110, 150), floor=(105, 105, 110),
          scene=(("building", 4, 12), ("building", 40, 6), ("lamp", 78, 18), ("car", 88, 46)),
          spots=(
              Spot("街灯の上", text="防犯カメラがある。会社の裏口が写る向きだ。", gives=ClueId("camera")),
              Spot("裏口", needs=frozenset({ClueId("camera")}),
                   locked="会社の裏口。鍵が掛かっている。",
                   text="裏口の鍵。ここからなら受付を通らずに入れる。"),
          ),
          exits=(PlaceId("office"), PlaceId("company"), PlaceId("bar"))),
)}


def scene_sprites(place: Place) -> list[tuple[Sprite, int, int]]:
    """その場所に置くもの。家具の並びと、そこにいる人。"""
    put = [(PIECES[name], x, y) for name, x, y in place.scene]
    for i, pid in enumerate(place.people):
        x = place.stand[i % len(place.stand)]
        put.append((figure(PEOPLE[pid].face), x, FLOOR_Y - 28))
    return put


def draw(screen: Screen, game: "Game") -> None:
    """場面の一枚絵。ノートを開いていれば手がかりの地図を描く。"""
    if game.note:
        return draw_note(screen, game)
    place = game.here
    screen.clear()
    for y in range(HEIGHT):
        color = place.sky if y < FLOOR_Y else place.floor
        for x in range(WIDTH):
            screen.plot(x, y, color)
    edge = tuple(max(0, v - 30) for v in place.floor)       # 床と壁の見切り。1 本入るだけで奥行きが出る
    for x in range(WIDTH):
        screen.plot(x, FLOOR_Y, edge)
        screen.plot(x, FLOOR_Y + 1, edge)
    for spr, x, y in scene_sprites(place):
        screen.blit(spr, x, y)


def clue_graph() -> dict[ClueId, set[ClueId]]:
    """手がかりの依存。「この手がかりを得るには、どの手がかりが要るか」。

    世界のデータ（調べどころと話）から組み立てる。表を別に持つと、
    データを直したときに必ずどちらかを直し忘れる。
    """
    graph: dict[ClueId, set[ClueId]] = {c: set() for c in CLUES}
    for place in PLACES.values():
        for spot in place.spots:
            if spot.gives:
                graph[spot.gives] |= set(spot.needs)
    for person in PEOPLE.values():
        for topic in person.topics:
            if topic.gives:
                graph[topic.gives] |= set(topic.needs)
    for fix in CONFRONTS.values():                  # 突きつけて手に入る手がかりも同じ地図に乗せる
        if fix.gives:
            graph[fix.gives] |= set(fix.needs)
    return graph


def clue_sources() -> dict[ClueId, list[str]]:
    """手がかりごとの入手先。1 つも無い／2 つ以上ある、を見つけるために使う。"""
    found: dict[ClueId, list[str]] = {c: [] for c in CLUES}
    for place in PLACES.values():
        for spot in place.spots:
            if spot.gives:
                found[spot.gives].append(f"{place.name} / {spot.name}")
    for person in PEOPLE.values():
        for topic in person.topics:
            if topic.gives:
                found[topic.gives].append(f"{person.name} / {topic.name}")
    for pair, fix in CONFRONTS.items():
        if fix.gives:
            found[fix.gives].append("突きつけ: " + " × ".join(WORDS[w].speaker for w in pair))
    return found


def layers() -> list[list[ClueId]]:
    """手がかりを「同時に手が届くもの」の層に分ける。

    TopologicalSorter は static_order() で 1 列に並べてくれるが、
    prepare() / get_ready() / done() と回すと「今いっぺんに取れるもの」が層で出る。
    推理ノートの絵は、この層をそのまま左から右へ並べたもの。
    """
    sorter = TopologicalSorter(clue_graph())
    sorter.prepare()
    out = []
    while sorter.is_active():
        ready = sorter.get_ready()
        out.append(sorted(ready, key=list(CLUES).index))
        sorter.done(*ready)
    return out


def check_case() -> list[str]:
    """事件が壊れていないか調べる。返すのは見つかった問題の一覧（空なら健全）。"""
    problems = []
    sources = clue_sources()
    for cid, where in sources.items():
        if not where:
            problems.append(f"{CLUES[cid].name}: どこからも手に入らない")
        elif len(where) > 1:
            problems.append(f"{CLUES[cid].name}: 入手先が {len(where)} か所（{'、'.join(where)}）")
    graph = clue_graph()
    for cid, needs in graph.items():
        for need in needs:
            if need not in CLUES:
                problems.append(f"{CLUES[cid].name}: 知らない手がかり {need} を必要としている")
    try:
        order = list(TopologicalSorter(graph).static_order())
    except CycleError as e:
        problems.append(f"手がかりが輪になっている: {' → '.join(CLUES[c].name for c in e.args[1])}")
        return problems
    if len(order) != len(CLUES):
        problems.append("並べられなかった手がかりがある")
    reached = walkable_clues()
    for cid in CLUES:
        if cid not in reached:
            problems.append(f"{CLUES[cid].name}: 条件は満たせるが、その場所へ行けない")
    return problems


def walkable_clues() -> set[ClueId]:
    """実際に街を歩いて届く手がかり。場所のつながりも見るので、グラフだけでは分からない詰みを拾う。"""
    reachable = {PlaceId("office")}
    queue = deque([PlaceId("office")])
    while queue:
        here = queue.popleft()
        for nxt in PLACES[here].exits:
            if nxt not in reachable:
                reachable.add(nxt)
                queue.append(nxt)
    got: set[ClueId] = set()
    for _ in range(len(CLUES) + 1):
        before = len(got)
        for pid in reachable:
            for spot in PLACES[pid].spots:
                if spot.gives and set(spot.needs) <= got:
                    got.add(spot.gives)
            for person_id in PLACES[pid].people:
                for topic in PEOPLE[person_id].topics:
                    if topic.gives and set(topic.needs) <= got:
                        got.add(topic.gives)
        for fix in CONFRONTS.values():              # 突きつけは場所を選ばない
            if fix.gives and set(fix.needs) <= got:
                got.add(fix.gives)
        if len(got) == before:
            break
    return got


NOTE_COLS = 3                                       # ノートの絵に並べる層の数（横）
BOX_W = 22                                          # 手がかり 1 つの枠の横
BOX_H = 8                                           # 同じく縦
NOTE_BG = (28, 30, 40)
NOTE_HAVE = (90, 170, 110)                          # 持っている手がかり
NOTE_YET = (60, 62, 74)                             # まだの手がかり
NOTE_LINE = (110, 115, 130)


def note_layout() -> dict[ClueId, tuple[int, int]]:
    """手がかりを層ごとに左から右へ並べ、枠の左上の座標を返す。"""
    spread = layers()
    places: dict[ClueId, tuple[int, int]] = {}
    for col, group in enumerate(spread[:NOTE_COLS]):
        x = 4 + col * ((WIDTH - 8 - BOX_W) // max(NOTE_COLS - 1, 1))
        step = (HEIGHT - 6) // max(len(group), 1)
        for row, cid in enumerate(group):
            places[cid] = (x, 3 + row * step)
    return places


def line(screen: Screen, x0: int, y0: int, x1: int, y1: int, color) -> None:
    """2 点を結ぶ線。ブレゼンハム（g20 の視線と同じ）。"""
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
    err = dx + dy
    while True:
        screen.plot(x0, y0, color)
        if (x0, y0) == (x1, y1):
            return
        step = 2 * err
        if step >= dy:
            err += dy
            x0 += sx
        if step <= dx:
            err += dx
            y0 += sy


def draw_note(screen: Screen, game: "Game") -> None:
    """推理ノート。手がかりを層で並べ、依存を線でつなぐ。番号は下の文章と対応する。"""
    screen.clear()
    for y in range(HEIGHT):
        for x in range(WIDTH):
            screen.plot(x, y, NOTE_BG)
    spot = note_layout()
    graph = clue_graph()
    for cid, needs in graph.items():                # 先に線。枠が上に来るように
        if cid not in spot:
            continue
        x1, y1 = spot[cid]
        for need in needs:
            if need in spot:
                x0, y0 = spot[need]
                line(screen, x0 + BOX_W, y0 + BOX_H // 2, x1, y1 + BOX_H // 2, NOTE_LINE)
    numbers = {cid: i + 1 for i, cid in enumerate(CLUES)}
    for cid, (x, y) in spot.items():
        color = NOTE_HAVE if cid in game.clues else NOTE_YET
        for dy in range(BOX_H):
            for dx in range(BOX_W):
                edge = dy in (0, BOX_H - 1) or dx in (0, BOX_W - 1)
                screen.plot(x + dx, y + dy, color if edge else NOTE_BG)
        screen.text(f"{numbers[cid]:02d}", x + 7, y + 2)


COMMANDS = ("しらべる", "きく", "つきつける", "いどう", "ノート", "こくはつ")
BACK = "もどる"
LOG_LINES = 6                                       # 下の文章窓に残す行数


@dataclass
class Game:
    """1 回ぶんの捜査。今いる場所と、集めた手がかりと、画面に出す文。"""

    place: PlaceId = PlaceId("office")
    mode: str = "top"                               # top / spot / person / topic / move
    who: PersonId | None = None                     # 「きく」で選んだ相手
    result: str | None = None

    def __post_init__(self) -> None:
        self.clues = Clues()
        self.seen: set[str] = set()                 # 一度「中身を見た」調べどころと話
        self.words: dict[WordId, Word] = {}         # 証言帳。言い直させると中身が入れ替わる
        self.pick: WordId | None = None             # 突きつけで先に選んだ証言
        self.pressed: set[frozenset[WordId]] = set()    # もう突きつけた組
        self.answers: list[str] = []                # 告発の答え
        self.note = False                           # ノートを開いているか
        self.lines: list[str] = []
        self.say(PLACES[self.place].text)

    @property
    def here(self) -> Place:
        return PLACES[self.place]

    def say(self, text: str) -> None:
        """文章窓に 1 行足す。$ の名前を差し替えてから。"""
        self.lines.append(Template(text).substitute(CAST))
        self.lines = self.lines[-LOG_LINES:]

    def can(self, needs: frozenset[ClueId]) -> bool:
        """必要な手がかりが揃っているか。Set を継承しているので <= が使える。"""
        return needs <= self.clues

    def found(self, clue: ClueId | None) -> None:
        """手がかりを 1 つ手に入れる。証言が付いていれば証言帳にも載せる。"""
        if clue is not None and self.clues.add(clue):
            self.say(f"【手がかり】{CLUES[clue].name} — {CLUES[clue].text}")
            if (wid := CLUE_WORD.get(clue)) is not None:
                self.hear(wid)

    def hear(self, wid: WordId) -> None:
        """証言帳に 1 つ載せる。"""
        if wid not in self.words:
            self.words[wid] = WORDS[wid]
            self.say(f"【証言】{self.words[wid].text}")

    def confront(self, a: WordId, b: WordId) -> None:
        """2 つの証言を突きつける。食い違っていて、しかも突きどころなら相手が言い直す。"""
        first, second = self.words[a], self.words[b]
        if not clash(first, second):
            self.say("この 2 つは食い違っていない。")
            return
        pair = frozenset({a, b})
        if pair in self.pressed:
            self.say("それはもう突きつけた。")
            return
        fix = CONFRONTS.get(pair)
        if fix is None:
            self.say("食い違ってはいる。だが、それだけでは何も出てこない。")
            return
        self.pressed.add(pair)
        self.say(fix.text)
        self.words[fix.revise] = replace(self.words[fix.revise], where=fix.where, text=fix.said)
        self.say(f"【言い直し】{self.words[fix.revise].text}")
        for wid in fix.adds:
            self.hear(wid)
        self.found(fix.gives)

    # --- 選択肢 ---
    def options(self) -> list[str]:
        """今の画面に出す選択肢。"""
        match self.mode:
            case "top":
                return [*COMMANDS, "そうさをおえる"]
            case "spot":
                return [s.name for s in self.spots()] + [BACK]
            case "person":
                return [PEOPLE[p].name for p in self.here.people] + [BACK]
            case "topic":
                return [t.name for t in self.topics()] + [BACK]
            case "move":
                return [PLACES[e].name for e in self.here.exits] + [BACK]
            case "word1" | "word2":
                return [self.words[w].text for w in self.pickable()] + [BACK]
            case "verdict":
                return list(fields(Verdict)[len(self.answers)].metadata["options"]) + [BACK]
        return [BACK]

    def key(self, kind: str, name: str) -> str:
        """「どこの何を見たか」の名札。場所や相手が違えば別ものとして数える。"""
        return f"{kind}/{self.place if kind == 'spot' else self.who}/{name}"

    def done(self, kind: str, name: str) -> bool:
        return self.key(kind, name) in self.seen

    def spots(self) -> list[Spot]:
        """まだ中身を見ていない調べどころ。条件が足りずに空振りしたものは残る。"""
        return list(filterfalse(lambda s: self.done("spot", s.name), self.here.spots))

    def topics(self) -> list[Topic]:
        """今の相手に聞ける話。手がかりが足りない話と、もう聞いた話は出てこない。"""
        return [t for t in PEOPLE[self.who].topics
                if self.can(t.needs) and not self.done("topic", t.name)]

    def choose(self, index: int) -> None:
        """選択肢を 1 つ選ぶ。"""
        choices = self.options()
        if not 0 <= index < len(choices):
            return
        if choices[index] == BACK:
            self.mode = "top"
            return
        match self.mode:
            case "top":
                self.top_command(index)
            case "spot":
                self.investigate(self.spots()[index])
            case "person":
                self.who = self.here.people[index]
                self.mode = "topic"
                self.say(f"{PEOPLE[self.who].name} に話を聞く。")
            case "topic":
                self.ask(self.topics()[index])
            case "move":
                self.go(self.here.exits[index])
            case "word1":
                self.pick = self.pickable()[index]
                self.mode = "word2"
            case "word2":
                other = self.pickable()[index]
                self.mode = "top"
                self.confront(self.pick, other)
                self.pick = None
            case "verdict":
                self.answers.append(self.options()[index])
                if len(self.answers) == len(fields(Verdict)):
                    self.accuse()
                else:
                    self.say(fields(Verdict)[len(self.answers)].metadata["label"] + "？")

    def top_command(self, index: int) -> None:
        match COMMANDS[index] if index < len(COMMANDS) else "おわる":
            case "しらべる":
                self.mode = "spot" if self.spots() else "top"
                if not self.spots():
                    self.say("ここはもう調べ尽くした。")
            case "きく":
                self.mode = "person" if self.here.people else "top"
                if not self.here.people:
                    self.say("ここには誰もいない。")
            case "いどう":
                self.mode = "move"
            case "つきつける":
                if len(self.words) < 2:
                    self.say("突きつけられるほど証言が集まっていない。")
                else:
                    self.mode = "word1"
                    self.say("どの証言と、どの証言を突き合わせる？")
            case "ノート":
                self.note = not self.note
                self.memo()
            case "こくはつ":
                self.answers = []
                self.mode = "verdict"
                self.note = False
                self.say("——ここまでで指し示す。")
                self.say(fields(Verdict)[0].metadata["label"] + "？")
            case _:
                self.result = "quit"

    def investigate(self, spot: Spot) -> None:
        """調べる。条件が足りなければ別の文を出し、選択肢からは消さない。

        「頑丈なドアだ」→（掛け金を見つけたあと）「鍵穴に傷」と中身が変わるので、
        空振りで消してしまうと二度と見られなくなる。
        """
        if not self.can(spot.needs):
            self.say(spot.locked or "とくに何もない。")
            return
        self.say(spot.text)
        self.found(spot.gives)
        self.seen.add(self.key("spot", spot.name))

    def ask_done(self, topic: Topic) -> None:
        self.seen.add(self.key("topic", topic.name))

    def ask(self, topic: Topic) -> None:
        self.say(topic.text)
        self.found(topic.gives)
        self.ask_done(topic)

    def go(self, place: PlaceId) -> None:
        self.place = place
        self.mode = "top"
        self.say(f"── {self.here.name} ──")
        self.say(self.here.text)

    def pickable(self) -> list[WordId]:
        """今えらべる証言。2 つ目は 1 つ目を除く。"""
        return [w for w in self.words if w != self.pick]

    def accuse(self) -> None:
        """告発を採点して終わる。"""
        total, marks, name, text = judge(Verdict(*self.answers))
        for mark in marks:
            self.say(mark)
        self.say(f"── {total} 点 ──")
        self.say(text)
        self.result = name

    def memo(self) -> None:
        """手がかりを番号つきで並べる。番号はノートの絵の枠と同じ。"""
        got = [f"{i + 1:2d} {CLUES[c].name}" for i, c in enumerate(CLUES) if c in self.clues]
        yet = [f"{i + 1:2d}" for i, c in enumerate(CLUES) if c not in self.clues]
        self.say(f"手がかり {len(self.clues)} / {len(CLUES)}   " + ("  ".join(got) or "まだ何も掴んでいない。"))
        if yet:
            self.say("まだの番号: " + " ".join(yet))
        if self.words:
            self.say(f"証言 {len(self.words)} 件: " + "／".join(w.speaker for w in self.words.values()))

    def status(self) -> str:
        left = sum(len(self.spots()) for _ in (0,)) + sum(
            1 for pid in self.here.people for t in PEOPLE[pid].topics
            if self.can(t.needs) and not self.done("topic", t.name))
        return (f"{self.here.name}   手がかり {len(self.clues)} / {len(CLUES)}"
                f"   証言 {len(self.words)}   ここで残り {left}")


def route(frm: PlaceId, to: PlaceId) -> list[PlaceId]:
    """frm から to までの道のり。場所のつながりを幅優先でたどる。"""
    if frm == to:
        return []
    first: dict[PlaceId, list[PlaceId]] = {frm: []}
    queue = deque([frm])
    while queue:
        here = queue.popleft()
        for nxt in PLACES[here].exits:
            if nxt not in first:
                first[nxt] = first[here] + [nxt]
                if nxt == to:
                    return first[nxt]
                queue.append(nxt)
    return []


def harvest(game: Game) -> None:
    """今いる場所で、まだ見ていないものを全部見る。そのあと証言を総当たりで突き合わせる。"""
    for spot in list(game.spots()):
        game.investigate(spot)
    for pid in game.here.people:
        game.who = pid
        for topic in list(game.topics()):
            game.ask(topic)
    for a, b in combinations(list(game.words), 2):   # 食い違う組は多くないので総当たりで足りる
        if frozenset({a, b}) in CONFRONTS:
            game.confront(a, b)


def autopilot(game: Game, rounds: int = 10) -> list[str]:
    """自動で捜査する。全部の場所を歩いて回り、新しい手がかりが出なくなるまで繰り返す。

    「その事件が詰まずに解けるか」を確かめるための道具。手がかりには
    「これを知らないと聞けない話」があるので、一周では足りない。
    """
    trail = []
    for turn in range(1, rounds + 1):
        before = len(game.clues)
        for target in PLACES:
            for step in route(game.place, target):
                game.go(step)
            harvest(game)
        gained = len(game.clues) - before
        trail.append(f"{turn} 周目: +{gained} 個（合計 {len(game.clues)}）")
        if gained == 0:
            break
    return trail
# --- ここから下はブラウザ版だけ。CLI 版の play() / Screen.render() にあたる ---

canvas = document.querySelector("#screen")
ctx = canvas.getContext("2d")
ctx.imageSmoothingEnabled = False
image = ctx.createImageData(WIDTH, HEIGHT)                  # 126 × 72 の画素の板
status_label = document.querySelector("#status")
log_box = document.querySelector("#log")
buttons_box = document.querySelector("#choices")


class CanvasScreen(Screen):
    """CLI 版の Screen をそのまま使い、描き終えた画素をまとめて canvas へ送る。"""

    def flush(self) -> None:
        buf = bytearray(WIDTH * HEIGHT * 4)
        i = 0
        for row in self.pixels:
            for color in row:
                if color is not None:
                    buf[i], buf[i + 1], buf[i + 2] = color
                buf[i + 3] = 255
                i += 4
        image.data.assign(bytes(buf))
        ctx.putImageData(image, 0, 0)


screen = CanvasScreen()
game = Game()


def refresh():
    """CLI 版の play() の 1 周ぶん。絵・文章・選択肢を描き直す。

    共有部分に module 直下の draw() があるので、ここで draw という名前は使えない。
    """
    draw(screen, game)
    screen.flush()
    status_label.textContent = game.status()
    log_box.textContent = "\n".join(game.lines)
    buttons_box.innerHTML = ""
    for i, name in enumerate(game.options()):
        button = document.createElement("button")
        button.textContent = f"{i + 1}  {name}"
        button.setAttribute("data-index", str(i))
        button.className = "choice"
        buttons_box.appendChild(button)


@when("click", "#choices")
def on_choice(event):
    """選択肢のボタンは毎回作り直すので、入れ物の側でクリックを受ける。

    @when は登録したときに在る要素に listener を付ける。あとから作った
    ボタンには付かないので、"#choices .choice" にすると 1 回も反応しない。
    """
    index = event.target.getAttribute("data-index")
    if index is None:
        return
    game.choose(int(index))
    refresh()


@when("click", "#restart")
def on_restart(event):
    global game
    game = Game()
    refresh()


# Pyodide の読み込みが終わってから実行される＝ここが準備完了の合図
document.querySelector("#loading").hidden = True
refresh()
