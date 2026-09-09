"""耳コピ3（面と記録と合言葉）ブラウザ版

CLI 版（g75-ear-course/main.py）と中身はまったく同じ。合言葉の作り方（to_word）も
読み方（from_word）も、面の分け方も、遊びの判断（Game・obey）も 1 文字も変えていない。

違うのは入口と出口だけ。
  入口: 端末はキー 1 文字、ブラウザは鍵盤のクリックとキーとボタンと入力欄
  出口: 絵は端末が ▀ の並び、ブラウザは canvas。音は端末が afplay、ブラウザは Audio。
        記録は端末が records.json、ブラウザは localStorage。**ただし中身は同じ形**。

持ってこなかったのは Screen.render() と、それを使う run() / show() / Speaker、
記録の読み書き（load_records / save_records）と検査だけ。
"""

import base64
import hashlib
import io
import json
import math
import wave
from array import array
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from functools import reduce
from itertools import accumulate, chain
from typing import Callable, TypeAlias
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pyscript import document, when, window
RATE = 22050                                        # 1 秒あたりの標本の数


BEAT = 0.19                                         # 八分音符 1 つぶんの長さ（秒）


VOLUME = 0.34                                       # 0〜1。16 bit の最大値にかける割合


LENGTHS = (1, 2, 3, 4, 6, 8)                        # 使う長さ（八分音符いくつぶんか）


MARKS = {1: "♪", 2: "♩", 3: "♩.", 4: "♩♩", 6: "♩♩♩", 8: "♩♩♩♩"}


MAKE_MAX = 12                                       # 自分で作れる旋律の音の数


def japan() -> timezone | ZoneInfo:
    """日本時間を返す。

    zoneinfo は「地域の名前」で時刻を扱う道具だが、**地域の時刻表そのものは
    動かす場所が持っている**。ブラウザの Python（Pyodide）には入っていないので、
    そこでは +9 時間で代用する。日本には夏時間が無いので、出る時刻は同じになる。
    """
    try:
        return ZoneInfo("Asia/Tokyo")
    except ZoneInfoNotFoundError:
        return timezone(timedelta(hours=9), "JST")


HERE = japan()


KEEP = 8                                            # 合言葉を覚えておく数


WIDTH = 128                                         # 画面の横（ドット）。端末では 1 ドット = 1 桁


HEIGHT = 80                                         # 縦。端末では 2 ドット = 1 行 → 40 行


OFFSET = 6                                          # 曲を鍵盤のどこに置くか（真ん中あたり）


SPAN = 12                                           # ロールに映す音の幅（半音）


MARK_TOP = 0                                        # 「いま打ち込む場所」の印


ROLL_TOP = 3                                        # ロールの上端


SEMI = 3                                            # 半音 1 つぶんの高さ（ドット）


STRIP_TOP = 43                                      # リズムの帯の上端


BOARD_TOP = 48                                      # 鍵盤の上端


WHITE_W = 8                                         # 白鍵の幅


WHITE_H = 32                                        # 白鍵の高さ


BLACK_W = 6                                         # 黒鍵の幅


BLACK_H = 20                                        # 黒鍵の高さ


LEFT = 4                                            # 鍵盤の左端


INK = (232, 234, 226)                               # 白鍵


SHADE = (176, 180, 170)                             # 白鍵の押されたところ


EBONY = (26, 30, 28)                                # 黒鍵


LIT = (232, 176, 84)                                # 押している鍵


SURE = (60, 122, 158)                               # 確定した音


TRY = (206, 138, 74)                                # 打ち込み中の音


FAINT = (74, 86, 80)                                # 1 音目の高さの目盛り


GRID = (38, 46, 42)                                 # 半音ごとの目盛り


BACK = (18, 22, 20)                                 # 背景


LINE = (44, 52, 48)                                 # 仕切り


Shape: TypeAlias = Callable[[float], float]         # 位相（0〜1）を受けて −1〜1 を返すもの


HARMONICS = ((1, 1.0), (2, 0.5), (3, 0.25), (4, 0.125))     # 倍音とその強さ


LOUDEST = 1.3953                                    # 重ねたときの実際の山の高さ（測った値）


def sine(phase: float) -> float:
    """いちばん素直な波。倍音がまったく無いので、澄んで細い音になる。"""
    return math.sin(math.tau * phase)


def triangle(phase: float) -> float:
    """三角の波。奇数の倍音がうっすら乗って、笛のような音になる。"""
    return 4 * abs((phase + 0.75) % 1 - 0.5) - 1


def sawtooth(phase: float) -> float:
    """のこぎりの波。倍音が全部そろうので、ざらついた厚い音になる。"""
    return 2 * ((phase + 0.5) % 1) - 1


def organ(phase: float) -> float:
    """正弦波を倍音のぶんだけ重ねた音。

    reduce は「たたみ込む」道具。倍音の表を順に見ながら合計に足していく。
    for で書いても同じだが、**「表を 1 つの値に畳む」ことがそのまま形に出る**。
    """
    return reduce(lambda total, part: total + part[1] * math.sin(math.tau * part[0] * phase),
                  HARMONICS, 0.0) / LOUDEST


SHAPES: tuple[tuple[str, Shape], ...] = (
    ("サイン", sine), ("三角", triangle), ("オルガン", organ), ("のこぎり", sawtooth),
)


def pitch_hz(note: int) -> float:
    """半音の番号を周波数にする。ド = 0、ラ = 9 がちょうど 440 Hz。

    半音 1 つで 2 の 12 乗根倍。12 個かければ 2 倍＝ちょうど 1 オクターブ上になる。
    """
    return 440.0 * 2.0 ** ((note - 9) / 12)


def fade(i: int, count: int) -> float:
    """音の立ち上がりと消え方。0 から 1 のあいだの倍率を返す。

    これが無いと、音の出始めと終わりで波が急に切れて「プツッ」と鳴る。
    立ち上がりは短く（30 分の 1 秒）、消え方は長く（10 分の 1 秒）。
    """
    return min(1.0, i / (RATE / 30), (count - i) / (RATE / 10))


def tone(note: int, seconds: float, wave_shape: Shape = sine) -> array:
    """1 つの音を、16 bit の標本の列にする。

    波の形は外から渡す。sin を直に書かず「位相を渡して高さをもらう」形にしたので、
    音色を変えるのに tone() を書き直さなくてよい。
    """
    count = int(RATE * seconds)
    turn = pitch_hz(note) / RATE                    # 1 標本ぶんで進む位相
    samples = array("h")
    for i in range(count):
        samples.append(int(32767 * VOLUME * fade(i, count) * wave_shape(turn * i)))
    return samples


def wav_bytes(samples: array) -> bytes:
    """標本の列を wav の bytes にする。ファイルにはしない。

    io.BytesIO は「メモリの上のファイル」。wave はファイルのように書き込むので、
    これを渡せば、書き出す先を選ばずに済む（端末はファイル、ブラウザは Audio）。
    """
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)                         # 1 本（モノラル）
        out.setsampwidth(2)                         # 1 標本 2 バイト = 16 bit
        out.setframerate(RATE)
        out.writeframes(samples.tobytes())
    return buffer.getvalue()


def melody(notes: list[tuple[int, int]], wave_shape: Shape = sine) -> array:
    """音を並べて 1 本の列にする。長さは音ごとに違う。

    先に全部ぶんの入れ物を作り、memoryview で「どこからどこまで」を切り出して書き込む。
    memoryview は**中身を写さずに一部を指す**ので、つなぐたびに配列を作り直さずに済む。
    始まる場所は accumulate（長さを順に足したもの）でそのまま出る。
    """
    counts = [int(RATE * length * BEAT) for _, length in notes]
    line = array("h", bytes(2 * sum(counts)))       # 2 バイト × 標本の数ぶんの空き地
    view = memoryview(line)
    for start, (note, length), count in zip(accumulate(counts, initial=0), notes, counts):
        view[start:start + count] = tone(note, length * BEAT, wave_shape)
    return line


@dataclass(frozen=True)
class Song:
    """1 曲。notes は (いちばん低い音を 0 とした半音の番号, 長さ) の並び。

    長さは八分音符いくつぶんか。どの高さで鳴らすかは OFFSET で決める。
    """

    name: str
    who: str
    notes: list[tuple[int, int]]

    def on_board(self) -> list[tuple[int, int]]:
        """鍵盤の上に置いた音にする。"""
        return [(note + OFFSET, length) for note, length in self.notes]

    def lengths(self) -> tuple[int, ...]:
        """この曲に出てくる長さだけ。打ち込みの選び先をここに絞る。

        47 曲のうち 37 曲は長さが 2 種類しかない。全部から選ばせると、
        耳ではなく総当たりの作業になってしまう。
        """
        return tuple(sorted({length for _, length in self.notes}))


SONGS = [
    Song("うれしいひなまつり", "河村光陽（1946 没）", [(0, 2), (0, 2), (0, 2), (2, 2), (3, 2), (2, 2), (0, 4)]),
    Song("雀の学校", "弘田龍太郎（1952 没）", [(0, 2), (3, 2), (3, 2), (3, 2), (0, 2), (3, 2), (3, 2), (3, 4)]),
    Song("かごめかごめ", "わらべうた", [(0, 2), (0, 2), (2, 2), (0, 2), (2, 2), (3, 2), (2, 4), (0, 2), (0, 2), (2, 2), (0, 4)]),
    Song("アルプス一万尺", "アメリカ民謡", [(0, 1), (0, 1), (2, 1), (4, 1), (0, 1), (4, 1), (2, 4)]),
    Song("メリーさんのひつじ", "アメリカ民謡", [(4, 2), (2, 2), (0, 2), (2, 2), (4, 2), (4, 2), (4, 4)]),
    Song("あんたがたどこさ", "わらべうた", [(0, 1), (0, 1), (2, 1), (4, 1), (4, 2), (2, 2), (0, 2), (2, 2), (4, 2), (0, 4)]),
    Song("あめふり", "中山晋平（1952 没）", [(3, 2), (3, 2), (0, 2), (3, 2), (5, 2), (5, 2), (3, 4)]),
    Song("かえるの合唱", "ドイツ民謡", [(0, 2), (2, 2), (4, 2), (5, 2), (4, 2), (2, 2), (0, 4)]),
    Song("かなりや", "成田為三（1945 没）", [(0, 2), (0, 2), (1, 2), (3, 2), (5, 2), (3, 2), (0, 4)]),
    Song("こいのぼり", "作曲者不詳（1931）", [(0, 2), (3, 2), (3, 2), (5, 2), (3, 2), (0, 2), (3, 4)]),
    Song("月の沙漠", "佐々木すぐる（1966 没）", [(2, 2), (2, 2), (4, 2), (5, 2), (4, 2), (2, 2), (0, 4)]),
    Song("浦島太郎", "文部省唱歌", [(3, 2), (3, 2), (0, 2), (3, 2), (5, 2), (3, 2), (0, 4)]),
    Song("茶摘み", "文部省唱歌", [(0, 2), (0, 2), (3, 2), (3, 2), (5, 2), (3, 2), (0, 4)]),
    Song("草競馬", "S.フォスター", [(3, 2), (3, 1), (0, 1), (3, 2), (5, 2), (3, 2), (0, 4)]),
    Song("夕焼小焼", "草川信（1948 没）", [(3, 2), (3, 2), (5, 2), (3, 2), (0, 2), (3, 2), (5, 2), (3, 4)]),
    Song("春が来た", "岡野貞一（1941 没）", [(3, 2), (0, 2), (3, 2), (5, 2), (3, 4), (0, 2), (3, 2), (5, 2), (3, 2), (0, 4)]),
    Song("桃太郎", "岡野貞一（1941 没）", [(3, 2), (3, 2), (0, 2), (3, 2), (5, 2), (3, 4), (3, 2), (3, 2), (0, 2), (3, 2), (5, 2), (3, 4)]),
    Song("かもめの水兵さん", "河村光陽（1946 没）", [(0, 2), (4, 2), (7, 2), (4, 2), (0, 2), (4, 2), (7, 4)]),
    Song("富士山", "文部省唱歌", [(0, 2), (4, 2), (7, 2), (4, 2), (0, 2), (4, 2), (2, 4)]),
    Song("春よ来い", "弘田龍太郎（1952 没）", [(5, 2), (2, 2), (5, 2), (7, 2), (5, 2), (2, 2), (0, 4)]),
    Song("証城寺の狸囃子", "中山晋平（1952 没）", [(5, 2), (5, 2), (5, 2), (7, 2), (5, 2), (2, 2), (0, 4)]),
    Song("金太郎", "田村虎蔵（1943 没）", [(4, 2), (4, 2), (2, 2), (0, 2), (4, 2), (7, 2), (7, 4)]),
    Song("てるてる坊主", "中山晋平（1952 没）", [(0, 2), (2, 2), (4, 2), (5, 2), (7, 4), (7, 2), (4, 2), (0, 4)]),
    Song("聖者の行進", "アメリカ賛美歌", [(0, 1), (4, 1), (5, 1), (7, 6), (0, 1), (4, 1), (5, 1), (7, 6)]),
    Song("荒城の月", "滝廉太郎（1903 没）", [(0, 2), (2, 2), (3, 4), (2, 2), (0, 2), (3, 4), (7, 2), (5, 2), (3, 4)]),
    Song("ロンドン橋", "イギリス伝承", [(5, 2), (7, 1), (5, 1), (3, 2), (2, 2), (3, 2), (5, 2), (0, 2), (2, 2), (3, 4)]),
    Song("ぶんぶんぶん", "ボヘミア民謡", [(7, 2), (4, 2), (4, 4), (5, 2), (2, 2), (2, 4), (0, 2), (2, 2), (4, 2), (5, 2), (7, 4)]),
    Song("ジングルベル", "J.ピアポント", [(4, 2), (4, 2), (4, 4), (4, 2), (4, 2), (4, 4), (4, 2), (7, 2), (0, 3), (2, 1), (4, 8)]),
    Song("山の音楽家", "ドイツ民謡", [(0, 1), (0, 1), (4, 1), (4, 1), (7, 1), (7, 1), (4, 2), (5, 1), (5, 1), (4, 1), (4, 1), (2, 4)]),
    Song("ちょうちょう", "ドイツ民謡", [(7, 2), (4, 2), (4, 4), (5, 2), (2, 2), (2, 4), (0, 2), (2, 2), (4, 2), (5, 2), (7, 2), (7, 2), (7, 4)]),
    Song("さくらさくら", "日本古謡", [(4, 4), (4, 4), (6, 8), (4, 4), (4, 4), (6, 8), (4, 4), (6, 4), (7, 2), (6, 2), (4, 4), (6, 2), (4, 2), (0, 8)]),
    Song("うさぎとかめ", "納所弁次郎（1936 没）", [(3, 2), (3, 2), (0, 2), (3, 2), (8, 2), (5, 2), (3, 4)]),
    Song("七つの子", "本居長世（1945 没）", [(5, 2), (3, 2), (0, 4), (3, 2), (5, 2), (8, 2), (5, 2), (3, 4)]),
    Song("春の小川", "岡野貞一（1941 没）", [(3, 2), (3, 2), (5, 2), (3, 2), (0, 2), (3, 2), (5, 2), (8, 4)]),
    Song("きらきら星", "フランス民謡", [(0, 2), (0, 2), (7, 2), (7, 2), (9, 2), (9, 2), (7, 4)]),
    Song("シャボン玉", "中山晋平（1952 没）", [(4, 2), (7, 2), (9, 2), (7, 2), (4, 2), (2, 2), (0, 4)]),
    Song("赤い靴", "本居長世（1945 没）", [(4, 2), (7, 2), (9, 2), (7, 2), (4, 2), (2, 2), (0, 4)]),
    Song("この道", "山田耕筰（1965 没）", [(0, 2), (4, 2), (7, 2), (9, 2), (7, 4), (4, 2), (2, 2), (0, 4)]),
    Song("もみじ", "岡野貞一（1941 没）", [(4, 2), (7, 2), (7, 2), (9, 2), (7, 2), (4, 2), (2, 2), (0, 4)]),
    Song("峠の我が家", "アメリカ民謡", [(0, 2), (5, 2), (5, 1), (7, 1), (9, 2), (5, 2), (4, 2), (2, 4)]),
    Song("浜辺の歌", "成田為三（1945 没）", [(0, 3), (2, 1), (4, 2), (7, 2), (9, 4), (7, 2), (4, 2), (2, 4)]),
    Song("蛍の光", "スコットランド民謡", [(0, 1), (5, 3), (5, 1), (9, 2), (7, 2), (5, 2), (7, 2), (9, 4)]),
    Song("靴が鳴る", "弘田龍太郎（1952 没）", [(0, 2), (4, 2), (7, 2), (7, 2), (9, 2), (7, 4), (5, 2), (4, 2), (2, 4)]),
    Song("朧月夜", "岡野貞一（1941 没）", [(0, 2), (4, 2), (7, 4), (9, 2), (7, 2), (4, 4), (2, 2), (4, 2), (2, 2), (0, 4)]),
    Song("どんぐりころころ", "梁田貞（1959 没）", [(4, 2), (4, 2), (7, 2), (7, 2), (9, 2), (9, 2), (7, 4), (4, 2), (4, 2), (2, 2), (2, 2), (0, 4)]),
    Song("おおスザンナ", "S.フォスター", [(0, 1), (2, 1), (4, 2), (7, 2), (7, 2), (9, 2), (7, 2), (4, 2), (0, 2), (2, 2), (4, 2), (4, 2), (2, 2), (0, 2), (2, 4)]),
    Song("赤とんぼ", "山田耕筰（1965 没）", [(4, 2), (7, 2), (9, 4), (12, 2), (9, 2), (7, 4), (4, 2), (2, 2), (0, 4)]),
]


@dataclass(frozen=True)
class Stage:
    """面。曲の番号の並びと、その面で使う音色。"""

    name: str
    first: int
    last: int                                       # ここも含む

    @property
    def songs(self) -> tuple[int, ...]:
        return tuple(range(self.first, self.last + 1))


STAGES = (
    Stage("すきとおる音", 0, 11),                     # サイン
    Stage("笛のような音", 12, 23),                    # 三角
    Stage("オルガンの音", 24, 35),                    # 倍音を重ねた音
    Stage("ざらついた音", 36, 46),                    # のこぎり
)


ORDER = tuple(chain.from_iterable(stage.songs for stage in STAGES))


def shape_of(index: int) -> tuple[str, Shape]:
    """何曲目かで音色が変わる。倍音が多い音ほど、高さが取りにくい。"""
    return SHAPES[stage_of(index)]


def stage_of(index: int) -> int:
    """その曲が何面目か。"""
    return next(n for n, stage in enumerate(STAGES) if index <= stage.last)


class BadWord(Exception):
    """合言葉が読めないときに投げる。理由を自分で持つ。"""

    def __init__(self, why: str):
        super().__init__(why)
        self.why = why


def to_word(notes: list[tuple[int, int]]) -> str:
    """旋律を、人が打てる短い字にする。

    1 音を 1 バイトに詰める（高さ 0〜24 が上 5 bit、長さの番号が下 3 bit）。
    うしろに blake2s の 1 バイトを足しておくと、打ち間違いをその場で見つけられる。
    base32 は 0/O や 1/I を使わないので、書き写しても間違えにくい。
    """
    data = bytes((note << 3) | LENGTHS.index(length) for note, length in notes)
    body = base64.b32encode(data + check_byte(data)).decode().rstrip("=")
    return "-".join(body[i:i + 4] for i in range(0, len(body), 4))


def from_word(word: str) -> list[tuple[int, int]]:
    """合言葉を旋律に戻す。読めなければ BadWord。"""
    body = "".join(word.upper().split()).replace("-", "")
    if not body:
        raise BadWord("合言葉が空です")
    if set(body) - set("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"):
        raise BadWord("使えない字が入っています（A〜Z と 2〜7 だけ）")
    padded = body + "=" * (-len(body) % 8)
    try:
        raw = base64.b32decode(padded)
    except Exception:
        raise BadWord("長さが足りません") from None
    if base64.b32encode(raw).decode().rstrip("=") != body:
        raise BadWord("打ち間違いがあります")        # 書き直したら別の字になる＝どこか違う
    data, tail = raw[:-1], raw[-1:]
    if not data:
        raise BadWord("音が入っていません")
    if tail != check_byte(data):
        raise BadWord("打ち間違いがあります")
    if any((byte & 7) >= len(LENGTHS) or (byte >> 3) > 24 for byte in data):
        raise BadWord("鍵盤の外の音が入っています")   # 先に見る。読んでからでは落ちる
    return [(byte >> 3, LENGTHS[byte & 7]) for byte in data]


def check_byte(data: bytes) -> bytes:
    """打ち間違いを見つけるための 1 バイト。中身が 1 bit 違えば必ず変わる。"""
    return hashlib.blake2s(data, digest_size=1).digest()


@dataclass
class Record:
    """1 曲ぶんの記録。いつ・どの曲を・星いくつで。"""

    when: str
    song: str
    stage: str
    stars: int

    @staticmethod
    def now(song: "Song", stage: str, stars: int) -> "Record":
        """いまの時刻は「日本時間」で残す。

        datetime.now() だけだと、動かした機械の設定しだいで別の時刻になる。
        ZoneInfo で場所を決めておけば、端末でもブラウザでも同じ時刻が残る。
        """
        return Record(datetime.now(HERE).strftime("%Y-%m-%d %H:%M"), song.name, stage, stars)


WHITE = [0, 2, 4, 5, 7, 9, 11, 12, 14, 16, 17, 19, 21, 23, 24]      # 白鍵の音


BLACK_AFTER = [0, 1, 3, 4, 5, 7, 8, 10, 11, 12]                     # この白鍵の右上に黒鍵


BLACK = [WHITE[w] + 1 for w in BLACK_AFTER]                         # 黒鍵の音


WHITE_CHARS = "zxcvbnmqwertyui"                                     # 白鍵のキー


BLACK_CHARS = "sd" "ghj" "23" "567"                                 # 黒鍵のキー


CHARS = dict(zip(WHITE_CHARS, WHITE)) | dict(zip(BLACK_CHARS, BLACK))


def white_box(index: int) -> tuple[int, int, int, int]:
    """白鍵の左上と大きさ。"""
    return LEFT + index * WHITE_W, BOARD_TOP, WHITE_W, WHITE_H


def black_box(index: int) -> tuple[int, int, int, int]:
    """黒鍵の左上と大きさ。白鍵の境目にまたがって載る。"""
    left = LEFT + (BLACK_AFTER[index] + 1) * WHITE_W - BLACK_W // 2
    return left, BOARD_TOP, BLACK_W, BLACK_H


def key_at(x: int, y: int) -> int | None:
    """画面の点を鍵盤の音にする。黒鍵が上に載っているので、黒を先に見る。"""
    for index, note in enumerate(BLACK):
        left, top, w, h = black_box(index)
        if left <= x < left + w and top <= y < top + h:
            return note
    for index, note in enumerate(WHITE):
        left, top, w, h = white_box(index)
        if left <= x < left + w and top <= y < top + h:
            return note
    return None


class Screen:
    """WIDTH × HEIGHT のドットの板。1 ドットは RGB か None（黒）。"""

    def __init__(self):
        self.pixels: list[list[tuple[int, int, int] | None]] = [[None] * WIDTH for _ in range(HEIGHT)]

    def clear(self) -> None:
        for row in self.pixels:
            row[:] = [None] * WIDTH

    def plot(self, x: int, y: int, color: tuple[int, int, int]) -> None:
        if 0 <= x < WIDTH and 0 <= y < HEIGHT:
            self.pixels[y][x] = color

    def box(self, x: int, y: int, w: int, h: int, color: tuple[int, int, int]) -> None:
        for row in range(y, y + h):
            for col in range(x, x + w):
                self.plot(col, row, color)

    def frame(self, x: int, y: int, w: int, h: int, color: tuple[int, int, int]) -> None:
        for i in range(w):
            self.plot(x + i, y, color)
            self.plot(x + i, y + h - 1, color)
        for i in range(h):
            self.plot(x, y + i, color)
            self.plot(x + w - 1, y + i, color)


def roll(screen: "Screen", game: "Game") -> None:
    """お題の音を横に並べる。確定した音は塗り、打ち込み中は色を変える。

    横は音の数で等分する。長さは**下の帯**で見せる（横幅で見せると、打ち込んだ長さが
    違うだけで全部の音が横にずれて、どこを直せばいいのか分からなくなる）。
    縦は半音 1 つが SEMI ドット。窓の高さは曲によらず SPAN 半音で固定。
    """
    answer = game.answer
    count = len(answer)
    step = (WIDTH - LEFT * 2) // count
    high = OFFSET + SPAN - (SPAN - max(note for note, _ in game.song.notes)) // 2
    base = ROLL_TOP + SPAN * SEMI + 1
    longest = max(game.song.lengths())
    for line in range(SPAN + 1):                    # 半音ごとの目盛り
        y = ROLL_TOP + line * SEMI + SEMI - 1
        color = FAINT if (high - line) == answer[0][0] else GRID
        for x in range(LEFT, LEFT + count * step - 2):
            screen.plot(x, y, color)
    for i in range(count):
        x = LEFT + i * step
        if game.fixed[i]:
            (note, length), color = answer[i], SURE
        elif game.typed[i] is not None:
            (note, length), color = game.typed[i], TRY
        else:
            screen.box(x, STRIP_TOP, step - 2, 1, GRID)
            continue
        screen.box(x, ROLL_TOP + (high - note) * SEMI, step - 2, SEMI, color)
        wide = max(2, (step - 2) * length // longest)
        screen.box(x, STRIP_TOP, wide, 3, color)    # 長さは下の帯の長さで見せる
    for x in range(LEFT, LEFT + count * step - 2):
        screen.plot(x, base, LINE)
    if game.at() is not None:                       # 印はロールの上に置く（帯と重ならないように）
        screen.box(LEFT + game.at() * step, MARK_TOP, step - 2, 2, TRY)


def sketch(screen: "Screen", game: "Game") -> None:
    """つくるモードの絵。作りかけの旋律を並べる。

    あそぶときの窓は 13 半音ぶんだが、ここは鍵盤 25 鍵ぜんぶが見えるようにする
    （どこに置いたか分からないと作れない）。半音 1 つが 1 ドット。
    """
    step = (WIDTH - LEFT * 2) // MAKE_MAX
    tall = STRIP_TOP - ROLL_TOP - 4                  # ロールに使える高さ
    for line in range(0, 25, 2):                    # 2 半音ごとの目盛り
        for x in range(LEFT, LEFT + MAKE_MAX * step - 2):
            screen.plot(x, ROLL_TOP + (24 - line) * tall // 24, GRID)
    longest = max((length for _, length in game.draft), default=1)
    for i, (note, length) in enumerate(game.draft):
        x = LEFT + i * step
        screen.box(x, ROLL_TOP + (24 - note) * tall // 24, step - 2, 2, TRY)
        screen.box(x, STRIP_TOP, max(2, (step - 2) * length // longest), 3, TRY)
    if len(game.draft) < MAKE_MAX:
        screen.box(LEFT + len(game.draft) * step, MARK_TOP, step - 2, 2, TRY)


def board(screen: "Screen", game: "Game") -> None:
    """25 鍵の鍵盤。黒鍵をあとに描いて白鍵の上に載せる。"""
    for index, note in enumerate(WHITE):
        x, y, w, h = white_box(index)
        screen.box(x, y, w, h, LIT if note == game.lit else INK)
        screen.frame(x, y, w, h, SHADE)
    for index, note in enumerate(BLACK):
        x, y, w, h = black_box(index)
        screen.box(x, y, w, h, LIT if note == game.lit else EBONY)


def draw(screen: "Screen", game: "Game") -> None:
    screen.clear()
    screen.box(0, 0, WIDTH, HEIGHT, BACK)
    if game.making:
        sketch(screen, game)
    else:
        roll(screen, game)
    board(screen, game)


@dataclass
class Game:
    """遊びの状態。端末もブラウザもこれ 1 つを進める。"""

    index: int = 0                                  # 何曲目
    typed: list[tuple[int, int] | None] = field(default_factory=list)
    length: int = 2                                 # いま打ち込もうとしている長さ
    fixed: list[bool] = field(default_factory=list)
    heard: int = 0                                  # お題を聞いた回数
    tries: int = 0                                  # 答え合わせをした回数
    lit: int | None = None                          # いま光っている鍵
    stars: list[int] = field(default_factory=list)  # 曲ごとの星
    cleared: bool = False
    message: str = ""
    making: bool = False                            # つくるモードか
    asking: bool = False                            # 合言葉を打ち込んでいるか
    draft: list[tuple[int, int]] = field(default_factory=list)
    word: str = ""                                  # 出したり打ち込んだりする合言葉
    custom: Song | None = None                      # 合言葉から読んだ曲
    kept: OrderedDict = field(default_factory=OrderedDict)
    records: list[Record] = field(default_factory=list)

    def __post_init__(self):
        if not self.typed:
            self.start()

    @property
    def song(self) -> Song:
        return self.custom or SONGS[self.index]

    @property
    def stage(self) -> Stage:
        return STAGES[stage_of(self.index)]

    @property
    def answer(self) -> list[tuple[int, int]]:
        return self.song.on_board()

    @property
    def wave_shape(self) -> Shape:
        return sine if self.custom else shape_of(self.index)[1]

    def start(self) -> None:
        """新しい曲を出す。1 音目だけは最初から見せておく。

        これが無いと、絶対音感が無いかぎり出だしの高さを当てられない。
        「そこからの上がり下がり」を当てる遊びにするための 3 行。
        """
        answer = self.answer
        self.typed = [None] * len(answer)
        self.fixed = [False] * len(answer)
        self.typed[0] = answer[0]
        self.fixed[0] = True
        self.length = answer[0][1]                  # 1 音目と同じ長さから始める
        self.heard = 0
        self.tries = 0
        self.lit = None
        self.cleared = False
        self.message = "スペースでお題を聞く"

    def at(self) -> int | None:
        """次に打ち込む場所。確定していなくて、まだ空いているところの左から。"""
        for i, (note, done) in enumerate(zip(self.typed, self.fixed)):
            if not done and note is None:
                return i
        return None

    def press(self, note: int) -> bool:
        """鍵を押す。打ち込む場所があれば、いま選んでいる長さで入れる。"""
        self.lit = note
        spot = self.at()
        if spot is None or self.cleared:
            return False
        self.typed[spot] = (note, self.length)
        self.message = "そろったらリターンで答え合わせ" if self.at() is None else ""
        return True

    def stretch(self, step: int) -> int:
        """長さを 1 つ伸ばす／縮める。選び先はこの曲に出てくる長さだけ。

        直前に打ち込んだ音があれば、その長さも一緒に変える。
        「置いてから長さを直す」ほうが、置く前に選ぶより手数が少ない。
        """
        choices = self.choices()
        here = choices.index(self.length) if self.length in choices else 0
        self.length = choices[min(max(here + step, 0), len(choices) - 1)]
        if self.making:
            if self.draft:
                self.draft[-1] = (self.draft[-1][0], self.length)
            return self.length
        for i in reversed(range(len(self.typed))):
            if not self.fixed[i] and self.typed[i] is not None:
                self.typed[i] = (self.typed[i][0], self.length)
                break
        return self.length

    def choices(self) -> tuple[int, ...]:
        """選べる長さ。つくるときは全部から、あそぶときはその曲に出てくるものだけ。"""
        return LENGTHS if self.making else self.song.lengths()

    def erase(self) -> None:
        """最後に打ち込んだ音を消す。確定した音は消せない。"""
        for i in reversed(range(len(self.typed))):
            if not self.fixed[i] and self.typed[i] is not None:
                self.typed[i] = None
                self.message = ""
                return

    def judge(self) -> bool:
        """答え合わせ。合っていた音だけを確定させ、違った音は消す。

        **高さと長さの両方**が合って初めて確定。片方だけ合っていても消える。
        「高さは合っている」と教えると、そこから先は耳を使わずに済んでしまう。
        """
        if self.at() is not None or self.cleared:
            self.message = "まだ全部そろっていない"
            return False
        self.tries += 1
        answer = self.answer
        for i in range(len(answer)):
            if self.typed[i] == answer[i]:
                self.fixed[i] = True
            else:
                self.typed[i] = None
        if all(self.fixed):
            self.cleared = True
            self.stars.append(self.score())
            self.remember(Record.now(self.song, self.stage.name, self.score()))
            self.message = f"{self.song.name}　★ {self.score()}"
        else:
            self.message = f"{sum(self.fixed)} / {len(answer)} 音が決まった"
        return self.cleared

    def score(self) -> int:
        """星の数。聞いた回数と答え合わせの回数が少ないほど多い。"""
        if self.heard <= 3 and self.tries <= 2:
            return 3
        if self.heard <= 6 and self.tries <= 4:
            return 2
        return 1

    def advance(self) -> bool:
        """次の曲へ。合言葉の曲を遊んでいたら、もとの曲へ戻る。"""
        if self.custom is not None:
            self.custom = None
            self.start()
            return True
        if self.index + 1 >= len(SONGS):
            return False
        self.index += 1
        self.start()
        return True

    def remember(self, row: Record) -> None:
        """記録を新しい順に並べて持つ。"""
        self.records.insert(0, row)

    # ── つくる ──────────────────────────────────────────────────────

    def make(self) -> None:
        """つくるモードに入る／出る。"""
        self.making = not self.making
        self.asking = False
        self.word = ""
        self.message = ("鍵盤で旋律を作る。リターンで合言葉になる"
                        if self.making else "スペースでお題を聞く")

    def coin(self) -> None:
        """作った旋律を合言葉にする。"""
        if len(self.draft) < 3:
            self.message = "3 音以上ないと合言葉にできない"
            return
        self.word = to_word(self.draft)
        self.keep(self.word, list(self.draft))
        self.message = f"合言葉  {self.word}"

    def keep(self, word: str, notes: list[tuple[int, int]]) -> None:
        """合言葉を覚えておく。同じものを入れ直したら、いちばん新しい扱いにする。

        OrderedDict は「入れた順を覚えている辞書」。move_to_end で末尾へ送り、
        あふれたら先頭（いちばん古いもの）を捨てる。これだけで「最近の N 件」になる。
        """
        if word in self.kept:
            self.kept.move_to_end(word)
        else:
            self.kept[word] = notes
            while len(self.kept) > KEEP:
                self.kept.popitem(last=False)

    # ── 合言葉を読む ────────────────────────────────────────────────

    def ask(self) -> None:
        """合言葉の打ち込みを始める／やめる。"""
        self.asking = not self.asking
        self.word = ""
        self.message = "合言葉を打ってリターン" if self.asking else ""

    def letter(self, key: str) -> None:
        """合言葉を 1 字ずつ受ける。"""
        if key == "back":
            self.word = self.word[:-1]
        elif len(self.word) < 40 and key.upper() in "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567-":
            self.word += key.upper()
        self.message = f"合言葉  {self.word}"

    def open_word(self) -> bool:
        """打ち込んだ合言葉の曲を出す。読めなければ理由を出す。"""
        try:
            notes = from_word(self.word)
        except BadWord as bad:
            self.message = bad.why
            return False
        low = min(note for note, _ in notes)
        self.keep(self.word, notes)
        self.custom = Song("合言葉のうた", "だれかの作った旋律",
                           [(note - low, length) for note, length in notes])
        self.asking = False
        self.making = False
        self.start()
        self.message = "合言葉のうた。スペースでお題を聞く"
        return True


def obey(game: Game, key: str) -> tuple[list[tuple[int, int]], Shape] | None:
    """キーを 1 つ受け取ってゲームを進め、鳴らすものがあれば (音の並び, 波の形) で返す。

    端末もブラウザもここを通る。**やっていることが 3 つに分かれた**ので、
    まず「いまどのモードか」で振り分け、そのあとで鍵の話をする。
    """
    if game.asking:
        return read_word(game, key)
    if game.making:
        return build(game, key)
    return guess(game, key)


def read_word(game: Game, key: str) -> tuple[list[tuple[int, int]], Shape] | None:
    """合言葉を打ち込んでいるあいだ。"""
    if key == "enter":
        if game.open_word():
            return game.answer, game.wave_shape
        return None
    if key in ("ask", "space"):
        game.ask()
        return None
    if key == "back" or len(key) == 1:
        game.letter(key)
    return None


def build(game: Game, key: str) -> tuple[list[tuple[int, int]], Shape] | None:
    """つくるモード。作りかけの旋律に音を足す。"""
    if key == "make":
        game.make()
        return None
    if key == "ask":
        game.ask()
        return None
    if key == "enter":
        game.coin()
        return None
    if key == "space":
        return (game.draft, sine) if game.draft else None
    if key == "back":
        if game.draft:
            game.draft.pop()
            game.message = ""
        return None
    if key in ("longer", "shorter"):
        game.stretch(1 if key == "longer" else -1)
        return ([game.draft[-1]], sine) if game.draft else None
    note = CHARS.get(key)
    if note is None or len(game.draft) >= MAKE_MAX:
        return None
    game.lit = note
    game.draft.append((note, game.length))
    game.message = f"{len(game.draft)} / {MAKE_MAX} 音"
    return [(note, game.length)], sine


def guess(game: Game, key: str) -> tuple[list[tuple[int, int]], Shape] | None:
    """あそぶモード。g74 までと同じ。"""
    if key == "make":
        game.make()
        return None
    if key == "ask":
        game.ask()
        return None
    if key == "space":
        if game.cleared:
            return None if not game.advance() else (game.answer, game.wave_shape)
        game.heard += 1
        game.message = ""
        return game.answer, game.wave_shape
    if key == "enter":
        if game.cleared:
            game.advance()
            return None
        game.judge()
        return None
    if key == "back":
        game.erase()
        return None
    if key in ("longer", "shorter"):
        game.stretch(1 if key == "longer" else -1)
        spot = game.at()
        last = (spot - 1) if spot is not None else (len(game.typed) - 1)
        here = game.typed[last]
        return ([(here[0], game.length)] if here else None), game.wave_shape
    note = CHARS.get(key)
    if note is None:
        return None
    game.press(note)
    return [(note, game.length)], game.wave_shape


# --- ここから下はブラウザ版だけ。CLI 版の run() / Screen.render() / Speaker にあたる ---

canvas = document.querySelector("#screen")
ctx = canvas.getContext("2d")
ctx.imageSmoothingEnabled = False
image = ctx.createImageData(WIDTH, HEIGHT)
title_label = document.querySelector("#title")
count_label = document.querySelector("#count")
stage_label = document.querySelector("#stage")
timbre_label = document.querySelector("#timbre")
heard_label = document.querySelector("#heard")
tries_label = document.querySelector("#tries")
length_label = document.querySelector("#length")
stars_label = document.querySelector("#stars")
word_box = document.querySelector("#word")
record_box = document.querySelector("#record")
message = document.querySelector("#message")

SAVED = "g75-records"


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


class Speaker:
    """ブラウザで音を出す係。wav_bytes() が返した同じ bytes を Audio に渡すだけ。"""

    def __init__(self):
        self.made: dict[tuple, object] = {}

    def say(self, notes: list[tuple[int, int]] | None, wave_shape: Shape) -> None:
        if not notes:
            return
        want = (tuple(notes), wave_shape.__name__)
        if want not in self.made:
            data = wav_bytes(melody(notes, wave_shape))
            uri = "data:audio/wav;base64," + base64.b64encode(data).decode()
            self.made[want] = window.Audio.new(uri)
        sound = self.made[want]
        sound.pause()
        sound.currentTime = 0
        sound.play()


def load_records() -> list[Record]:
    """CLI 版は records.json、こちらは localStorage。**中身の形は同じ**。"""
    try:
        return [Record(**row) for row in json.loads(window.localStorage.getItem(SAVED) or "[]")]
    except Exception:
        return []


def save_records(rows: list[Record]) -> None:
    window.localStorage.setItem(SAVED, json.dumps([vars(row) for row in rows],
                                                  ensure_ascii=False))


screen = CanvasScreen()
game = Game(records=load_records())
speaker = Speaker()


def refresh() -> None:
    """CLI 版の show() にあたる。draw() を canvas へ、様子を HTML へ。"""
    draw(screen, game)
    screen.flush()
    if game.custom is not None:
        title_label.textContent = game.song.name if game.cleared else "合言葉のうた"
        stage_label.textContent = "—"
        timbre_label.textContent = "サイン"
    else:
        title_label.textContent = game.song.name if game.cleared else "？"
        stage_label.textContent = game.stage.name
        timbre_label.textContent = shape_of(game.index)[0]
    count_label.textContent = f"{game.index + 1} / {len(SONGS)}"
    heard_label.textContent = f"{game.heard} 回"
    tries_label.textContent = f"{game.tries} 回"
    length_label.textContent = "  ".join(
        f"[{MARKS[n]}]" if n == game.length else MARKS[n] for n in game.choices())
    stars_label.textContent = "".join("★" * n + "・" for n in game.stars[-14:]) or "—"
    record_box.textContent = "\n".join(
        f"{row.when}  {row.song}  {row.stage}  {'★' * row.stars}" for row in game.records[:20]) or "—"
    message.textContent = game.message
    document.querySelector("#making").textContent = "あそぶに戻る" if game.making else "つくる"
    word_box.hidden = not game.making


def act(key: str) -> None:
    """キー 1 つぶん進める。判断は CLI と同じ obey()。"""
    want = obey(game, key)
    if want is not None:
        speaker.say(*want)
    refresh()
    save_records(game.records[:200])


@when("click", "#screen")
def tap(event) -> None:
    box = canvas.getBoundingClientRect()
    x = int((event.clientX - box.left) / box.width * WIDTH)
    y = int((event.clientY - box.top) / box.height * HEIGHT)
    note = key_at(x, y)
    if note is not None:
        act(WHITE_CHARS[WHITE.index(note)] if note in WHITE else BLACK_CHARS[BLACK.index(note)])


@when("click", ".pad button")                        # 2 つ目以降の pad も拾う
def button(event) -> None:
    act(event.target.getAttribute("data-key"))


@when("click", "#read")
def read(event) -> None:
    """入力欄の合言葉を読む。打ち込み方は違っても、読むのは CLI と同じ open_word()。"""
    game.word = document.querySelector("#phrase").value
    game.asking = True
    act("enter")
    document.querySelector("#phrase").value = ""


KEYS = {" ": "space", "Enter": "enter", "Backspace": "back",
        ",": "shorter", ".": "longer", "ArrowLeft": "shorter", "ArrowRight": "longer",
        "1": "make", "0": "ask"}


@when("keydown", "body")
def typed(event) -> None:
    if event.target.tagName == "INPUT":
        return                                      # 入力欄に打っているときは邪魔しない
    name = KEYS.get(event.key, event.key.lower())
    if name in CHARS or name in ("space", "enter", "back", "shorter", "longer", "make"):
        event.preventDefault()
        act(name)


document.querySelector("#loading").hidden = True
refresh()
