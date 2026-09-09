"""耳コピ3（面と記録と合言葉）

耳コピ 3 段階の完成形。47 曲が 4 つの面に分かれ、遊んだ結果が日時つきで記録に残る。
そして**自分で作った旋律を「合言葉」にして持ち帰れる**——短い文字列を渡せば、
相手の画面にも同じ旋律が出題される。

今回の主題は「中身を、人が打てる短い字にする」こと。1 音を 1 バイトに詰め、
base32 で書き、うしろに blake2s の 1 バイトを足して打ち間違いを見つける。

    python3 main.py            遊ぶ
    python3 main.py --check    決まりを確かめる
    python3 main.py --wav 0    1 曲目の wav を書き出す（耳で確かめる用）
    python3 main.py --word ... 合言葉から旋律を読む
"""

import base64
import hashlib
import io
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import wave
from array import array
from collections import OrderedDict
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from functools import reduce
from itertools import accumulate, chain
from pathlib import Path
from typing import Callable, TypeAlias
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

RATE = 22050                                        # 1 秒あたりの標本の数
BEAT = 0.19                                         # 八分音符 1 つぶんの長さ（秒）
LENGTHS = (1, 2, 3, 4, 6, 8)                        # 使う長さ（八分音符いくつぶんか）
MARKS = {1: "♪", 2: "♩", 3: "♩.", 4: "♩♩", 6: "♩♩♩", 8: "♩♩♩♩"}
MAKE_MAX = 12                                       # 自分で作れる旋律の音の数
HERE = None                                         # 記録に残す時刻の場所（下で決める）
KEEP = 8                                            # 合言葉を覚えておく数
VOLUME = 0.34                                       # 0〜1。16 bit の最大値にかける割合

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


# ── 音を作る ────────────────────────────────────────────────────────────

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


def fade(i: int, count: int) -> float:
    """音の立ち上がりと消え方。0 から 1 のあいだの倍率を返す。

    これが無いと、音の出始めと終わりで波が急に切れて「プツッ」と鳴る。
    立ち上がりは短く（30 分の 1 秒）、消え方は長く（10 分の 1 秒）。
    """
    return min(1.0, i / (RATE / 30), (count - i) / (RATE / 10))


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


# ── 曲集 ────────────────────────────────────────────────────────────────

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


# ── 合言葉 ──────────────────────────────────────────────────────────────

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


# ── 記録 ────────────────────────────────────────────────────────────────

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


RECORDS = Path(__file__).with_name("records.json")


def load_records() -> list[Record]:
    rows: list[Record] = []
    with suppress(FileNotFoundError, json.JSONDecodeError, TypeError):
        rows = [Record(**row) for row in json.loads(RECORDS.read_text("utf-8"))]
    return rows


def save_records(rows: list[Record]) -> None:
    RECORDS.write_text(json.dumps([vars(row) for row in rows], ensure_ascii=False,
                                  indent=1), "utf-8")


# ── 鍵盤 ────────────────────────────────────────────────────────────────

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

# 面をつなげると、もとの曲の並びにそのまま戻る。chain.from_iterable は
# 「入れ子になった並びを 1 本にほどく」道具。ほどいた結果を確かめれば、
# 面の切り方に穴（抜けや重なり）が無いことがそのまま分かる。
ORDER = tuple(chain.from_iterable(stage.songs for stage in STAGES))


def shape_of(index: int) -> tuple[str, Shape]:
    """何曲目かで音色が変わる。倍音が多い音ほど、高さが取りにくい。"""
    return SHAPES[stage_of(index)]


def stage_of(index: int) -> int:
    """その曲が何面目か。"""
    return next(n for n, stage in enumerate(STAGES) if index <= stage.last)


WHITE = [0, 2, 4, 5, 7, 9, 11, 12, 14, 16, 17, 19, 21, 23, 24]      # 白鍵の音
BLACK_AFTER = [0, 1, 3, 4, 5, 7, 8, 10, 11, 12]                     # この白鍵の右上に黒鍵
BLACK = [WHITE[w] + 1 for w in BLACK_AFTER]                         # 黒鍵の音
WHITE_CHARS = "zxcvbnmqwertyui"                                     # 白鍵のキー
BLACK_CHARS = "sd" "ghj" "23" "567"                                 # 黒鍵のキー

# キー → 音。本物のピアノと同じ並びにしてある（下の段が低いオクターブ）
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


# ── 画面 ────────────────────────────────────────────────────────────────

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

    def render(self) -> str:
        """端末用の文字列。1 行に 2 ドット分の行を詰める（上が前景 ▀、下が背景）。"""
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


# ── 絵を描く ────────────────────────────────────────────────────────────

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


def board(screen: "Screen", game: "Game") -> None:
    """25 鍵の鍵盤。黒鍵をあとに描いて白鍵の上に載せる。"""
    for index, note in enumerate(WHITE):
        x, y, w, h = white_box(index)
        screen.box(x, y, w, h, LIT if note == game.lit else INK)
        screen.frame(x, y, w, h, SHADE)
    for index, note in enumerate(BLACK):
        x, y, w, h = black_box(index)
        screen.box(x, y, w, h, LIT if note == game.lit else EBONY)


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


def draw(screen: "Screen", game: "Game") -> None:
    screen.clear()
    screen.box(0, 0, WIDTH, HEIGHT, BACK)
    if game.making:
        sketch(screen, game)
    else:
        roll(screen, game)
    board(screen, game)


# ── ゲーム ──────────────────────────────────────────────────────────────

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


# ── 端末 ──# ── 端末 ────────────────────────────────────────────────────────────────

class Speaker:
    """端末で音を出す係。wav をいったんファイルにして afplay に渡す。

    同じ音は作り直さない（1 音つくるのに 7500 回の sin がいる）。
    """

    def __init__(self):
        self.player = shutil.which("afplay") or shutil.which("aplay")
        self.folder = tempfile.mkdtemp(prefix="ear-piano-")
        self.made: dict[tuple, str] = {}
        self.now: subprocess.Popen | None = None

    def say(self, notes: list[tuple[int, int]] | None, wave_shape: Shape) -> None:
        if self.player is None or not notes:
            return
        want = (tuple(notes), wave_shape.__name__)
        if want not in self.made:
            path = os.path.join(self.folder, f"{len(self.made)}.wav")
            with open(path, "wb") as out:
                out.write(wav_bytes(melody(notes, wave_shape)))
            self.made[want] = path
        if self.now is not None and self.now.poll() is None:
            self.now.kill()                         # 前の音を止めてから鳴らす
        self.now = subprocess.Popen([self.player, self.made[want]],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def close(self) -> None:
        if self.now is not None and self.now.poll() is None:
            self.now.kill()
        shutil.rmtree(self.folder, ignore_errors=True)


NAMES = {" ": "space", "\r": "enter", "\n": "enter", "\x7f": "back", "\b": "back",
         ",": "shorter", ".": "longer", "<": "shorter", ">": "longer",
         "1": "make", "0": "ask"}


def show(screen: Screen, game: Game) -> str:
    """画面と、その下に出す字。モードで見出しが変わる。"""
    draw(screen, game)
    star = "".join("★" * n + "・" for n in game.stars[-12:])
    choices = "  ".join(("[" + MARKS[n] + "]") if n == game.length else (" " + MARKS[n] + " ")
                        for n in game.choices())
    if game.making:
        head = f" つくる　{len(game.draft)} / {MAKE_MAX} 音　リターンで合言葉に"
    elif game.asking:
        head = f" 合言葉を打つ　{game.word}▌"
    elif game.custom is not None:
        head = f" 合言葉のうた　{game.song.who}"
    else:
        head = (f" {game.index + 1:2d}/{len(SONGS)}曲目  {game.stage.name}  "
                f"音色 {shape_of(game.index)[0]}  "
                f"聞いた {game.heard} 回  答え合わせ {game.tries} 回")
    lines = [
        screen.render(),
        head,
        f" 長さ  {choices}",
        f" {game.message}",
        f" {star}",
        "  ".join(f"{row.when} {row.song} ★{row.stars}" for row in game.records[:2]),
        " スペース=お題　リターン=答え合わせ　BS=1つ消す　, . =長さ",
        " 1=つくる　0=合言葉　Esc=やめる",
        " 白鍵 z x c v b n m q w e r t y u i ／ 黒鍵 s d g h j 2 3 5 6 7",
    ]
    return "\n".join(lines)


def run() -> None:
    """端末で遊ぶ。耳コピはターン制なので、キーを 1 つずつ待てばよい。"""
    import termios
    import tty

    speaker = Speaker()
    screen, game = Screen(), Game(records=load_records())
    if speaker.player is None:
        print("音を鳴らす道具（afplay / aplay）が見つかりません。絵だけで動かします。")
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        sys.stdout.write("\x1b[2J\x1b[?25l")
        while True:
            sys.stdout.write("\x1b[H" + show(screen, game))
            sys.stdout.flush()
            ch = sys.stdin.read(1)
            if ch in ("\x1b", "\x03", "\x04"):
                break
            want = obey(game, NAMES.get(ch, ch.lower()))
            if want is not None:
                speaker.say(*want)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
        sys.stdout.write("\x1b[?25h\x1b[2J\x1b[H")
        speaker.close()
        save_records(game.records[:200])            # 遊んだ結果は main.py の隣に残す


# ── 確かめる ────────────────────────────────────────────────────────────

def check() -> None:
    """決まりを機械に確かめさせる。"""
    print("● 面のつなぎ目")
    assert ORDER == tuple(range(len(SONGS))), "面をほどいたら、もとの並びに戻らない"
    assert len(STAGES) == len(SHAPES)
    for n, stage in enumerate(STAGES):
        names = {shape_of(i)[0] for i in stage.songs}
        assert len(names) == 1, f"{stage.name} に音色が {len(names)} 種類ある"
        print(f"  {stage.name}　{stage.first + 1:2d}〜{stage.last + 1:2d} 曲目"
              f"（{len(stage.songs):2d} 曲・{names.pop()}）")

    print("● 合言葉")
    for song in SONGS:
        notes = song.on_board()
        word = to_word(notes)
        assert from_word(word) == notes, song.name
        assert from_word(word.lower().replace("-", " ")) == notes, "小文字や空白で読めない"
    words = [len(to_word(s.on_board())) for s in SONGS]
    print(f"  47 曲すべて往復できた。合言葉の長さ {min(words)}〜{max(words)} 字")

    import random
    luck = random.Random(1)
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
    found = missed = 0
    for song in SONGS:
        word = to_word(song.on_board())
        for _ in range(40):                         # 1 字だけ書き間違えてみる
            broken = list(word)
            where = luck.choice([i for i, c in enumerate(broken) if c != "-"])
            broken[where] = luck.choice(letters)
            if "".join(broken) == word:
                continue
            try:
                from_word("".join(broken))
                missed += 1
            except BadWord:
                found += 1
    share = found / (found + missed) * 100
    assert share > 99.0, share
    print(f"  1 字の書き間違い {found + missed} 件のうち {found} 件を見つけた（{share:.1f}%）")
    for bad, why in (("", "空"), ("AAA!", "使えない字"), ("A", "長さ")):
        try:
            from_word(bad)
            raise AssertionError(f"{why} を通してしまった")
        except BadWord:
            pass
    print("  空・使えない字・短すぎる合言葉は、理由つきで断る")

    print("● 覚えておく合言葉（OrderedDict）")
    game = Game()
    for n in range(KEEP + 3):
        game.keep(f"WORD{n}", [(6, 2)])
    assert len(game.kept) == KEEP, len(game.kept)
    assert "WORD0" not in game.kept and f"WORD{KEEP + 2}" in game.kept
    first = next(iter(game.kept))
    game.keep(first, [(6, 2)])                      # 入れ直すと新しい扱いになる
    assert next(iter(game.kept)) != first
    print(f"  古いものから消えて {KEEP} 件だけ残る。入れ直すと新しい扱いになる")

    print("● 記録の時刻")
    row = Record.now(SONGS[0], STAGES[0].name, 3)
    assert len(row.when) == 16 and row.when[4] == "-" and row.when[13] == ":", row.when
    here = datetime.now(HERE)
    print(f"  {row.when}（{HERE}）。機械の設定によらず日本時間で残る")
    assert here.utcoffset().total_seconds() == 9 * 3600

    print("● 音の高さ")
    assert abs(pitch_hz(9) - 440.0) < 1e-9, pitch_hz(9)
    print(f"  ラ(9) = {pitch_hz(9):.2f} Hz / 1 オクターブ上 = {pitch_hz(21):.2f} Hz")

    print("● memoryview で組んだ旋律")
    notes = [(6, 2), (9, 1), (13, 4)]
    made = melody(notes, triangle)
    one_by_one = array("h")
    for note, length in notes:
        one_by_one.extend(tone(note, length * BEAT, triangle))
    assert made == one_by_one, "場所を決めて書き込んだら中身が変わった"
    print(f"  標本 {len(made)} 個。素直につないだものと完全に一致")

    print("● 曲集")
    assert len(SONGS) == 47, len(SONGS)
    for song in SONGS:
        assert min(note for note, _ in song.notes) == 0, song.name
        assert all(0 <= note <= 24 for note, _ in song.on_board()), song.name
        assert all(length in LENGTHS for _, length in song.notes), song.name
    widths = [max(note for note, _ in s.notes) for s in SONGS]
    assert widths == sorted(widths), "やさしい順に並んでいない"
    print(f"  {len(SONGS)} 曲 / 音の幅 {min(widths)}〜{max(widths)}")

    print("● 遊びの決まり")
    game = Game()
    for note, length in game.answer[1:]:
        game.length = length
        game.press(note)
    assert game.judge() and game.cleared
    assert game.stars == [3] and len(game.records) == 1
    assert game.records[0].stage == STAGES[0].name
    print(f"  クリアすると記録が 1 行増える（{game.records[0].song} ★{game.records[0].stars}）")

    print("● つくって、合言葉にして、遊ぶ")
    game = Game()
    obey(game, "make")
    assert game.making
    for key in "zxcvb":
        obey(game, key)
    obey(game, "longer")
    assert len(game.draft) == 5 and game.draft[-1][1] != game.draft[0][1]
    obey(game, "enter")
    word = game.word
    assert word and word in game.kept
    print(f"  作った旋律 {game.draft} → {word}")

    other = Game()
    obey(other, "ask")
    for letter in word:
        obey(other, letter.lower())
    obey(other, "enter")
    assert other.custom is not None, other.message
    low = min(note for note, _ in game.draft)
    assert other.answer == [(note - low + OFFSET, length) for note, length in game.draft]
    print(f"  別の画面で合言葉を打つと、同じ旋律が出題される（{other.song.name}）")
    for note, length in other.answer[1:]:
        other.length = length
        other.press(note)
    assert other.judge(), "合言葉の曲がクリアできない"
    assert other.advance() and other.custom is None, "遊び終えたら曲集へ戻る"
    print("  遊び終えたら曲集へ戻る")

    print("● どの曲も必ず解ける（総当たりの上限）")
    worst, worst_name = 0, ""
    for index in range(len(SONGS)):
        game = Game(index=index)
        for length in game.song.lengths():
            for guess_note in range(OFFSET, OFFSET + SPAN + 1):
                if game.cleared:
                    break
                while (spot := game.at()) is not None:
                    game.typed[spot] = (guess_note, length)
                game.judge()
        assert game.cleared, SONGS[index].name
        if game.tries > worst:
            worst, worst_name = game.tries, SONGS[index].name
    print(f"  47 曲すべて解ける。いちばんかかったのは「{worst_name}」で答え合わせ {worst} 回")

    print("● 端末とブラウザで同じ音が鳴るか")
    same = wav_bytes(melody(SONGS[0].on_board(), shape_of(0)[1]))
    assert same == wav_bytes(melody(SONGS[0].on_board(), shape_of(0)[1]))
    print(f"  1 曲目の wav は {len(same)} バイト。この bytes をそのまま両方へ渡す")

    print("\nぜんぶ通った。")


def write_wav(index: int) -> None:
    """耳で確かめる用に wav を書き出す。"""
    song = SONGS[index]
    name, wave_shape = shape_of(index)
    path = f"{index:02d}-{song.name}.wav"
    with open(path, "wb") as out:
        out.write(wav_bytes(melody(song.on_board(), wave_shape)))
    print(f"{path} に書き出した（{song.who} / 音色 {name}）")


def main() -> None:
    if "--check" in sys.argv:
        check()
    elif "--wav" in sys.argv:
        write_wav(int(sys.argv[sys.argv.index("--wav") + 1]))
    elif "--word" in sys.argv:
        try:
            notes = from_word(sys.argv[sys.argv.index("--word") + 1])
        except BadWord as bad:
            print("読めません:", bad.why)
            return
        print(f"{len(notes)} 音:", " ".join(f"{note}{MARKS[length]}" for note, length in notes))
    else:
        run()


if __name__ == "__main__":
    main()
