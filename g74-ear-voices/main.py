"""耳コピ2（楽器を選ぶ）

g73 と同じ遊び。違うのは**楽器を選べる**こと——ピアノ・エレクトーン・ギター・ベース・木琴。
お題も鍵盤も、選んだ楽器で鳴る。

今回の主題は「同じ高さの音でも、波の作り方で楽器が変わる」こと。
  ピアノ    倍音を重ねて、打った瞬間から減衰させる
  エレクトーン 倍音を足し合わせて持続させる（ドローバー）
  ギター・ベース 雑音を弦の長さぶん遅らせて平均する（弦をはじく音になる）
  木琴      少ない倍音を短く
どれも「音の番号と長さを受けて標本の列を返す」同じ形（Voice）なので、差し替えるだけで済む。

    python3 main.py            遊ぶ
    python3 main.py --check    決まりを確かめる
    python3 main.py --wav 0    1 曲目の wav を書き出す（耳で確かめる用）
"""

import io
import math
import os
import random
import shutil
import subprocess
import sys
import tempfile
import wave
from array import array
from collections import deque
from dataclasses import dataclass, field
from functools import reduce
from typing import Callable, TypeAlias

RATE = 22050                                        # 1 秒あたりの標本の数
NOTE = 0.34                                         # お題の 1 音の長さ（秒）
TAP = 0.5                                           # 鍵盤を押したときの長さ（秒）
VOLUME = 0.34                                       # 0〜1。16 bit の最大値にかける割合

WIDTH = 128                                         # 画面の横（ドット）。端末では 1 ドット = 1 桁
HEIGHT = 80                                         # 縦。端末では 2 ドット = 1 行 → 40 行

OFFSET = 6                                          # 曲を鍵盤のどこに置くか（真ん中あたり）
SPAN = 12                                           # ロールに映す音の幅（半音）
ALMOST = 2                                          # 残りがこれ以下なら ALMOST
ROLL_TOP = 4                                        # ロールの上端
SEMI = 3                                            # 半音 1 つぶんの高さ（ドット）
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
HINT = (44, 80, 100)                                # 1 音目の高さの下書き（黒鍵）
HINT_W = (186, 200, 206)                            # 同じ（白鍵）
TRY = (206, 138, 74)                                # 打ち込み中の音
MISS = (198, 82, 70)                                # 答え合わせで違っていた音
BAND = (30, 40, 46)                                 # いま打ち込む列の帯
SURE_W = (150, 186, 208)                            # 決まった音の白鍵
SURE_B = (38, 72, 94)                               # 決まった音の黒鍵
FAINT = (74, 86, 80)                                # 1 音目の高さの目盛り
GRID = (38, 46, 42)                                 # 半音ごとの目盛り
BACK = (18, 22, 20)                                 # 背景
LINE = (44, 52, 48)                                 # 仕切り


# ── 音を作る ────────────────────────────────────────────────────────────

def pitch_hz(note: int) -> float:
    """半音の番号を周波数にする。ド = 0、ラ = 9 がちょうど 440 Hz。

    半音 1 つで 2 の 12 乗根倍。12 個かければ 2 倍＝ちょうど 1 オクターブ上になる。
    """
    return 440.0 * 2.0 ** ((note - 9) / 12)


Voice: TypeAlias = Callable[[int, float], array]    # 音の番号と長さを受けて、標本の列を返すもの


def shape(i: int, count: int, attack: float = RATE / 30, release: float = RATE / 10) -> float:
    """音の立ち上がりと消え方。0 から 1 のあいだの倍率を返す。

    これが無いと、音の出始めと終わりで波が急に切れて「プツッ」と鳴る。
    楽器で長さが違う。ピアノは打った瞬間に立ち上がり、エレクトーンはふわっと入る。
    """
    return min(1.0, i / attack, (count - i) / release)


def pack(count: int, gain: float, wave_at: Callable[[int], float]) -> array:
    """標本の数だけ wave_at(i) を呼んで、16 bit の列に詰める。どの楽器もここを通る。"""
    samples = array("h")
    for i in range(count):
        samples.append(int(32767 * VOLUME * gain * wave_at(i)))
    return samples


PIANO = ((1, 1.0), (2, 0.6), (3, 0.3), (4, 0.15), (5, 0.08))     # 倍音とその強さ


def piano(note: int, seconds: float) -> array:
    """ピアノ。倍音を重ねて、打った瞬間から減衰させる。

    高い倍音ほど早く消える（exp(-k t)）。これが「打った直後は明るく、すぐ丸くなる」
    ピアノらしさになる。
    """
    count, hz = int(RATE * seconds), pitch_hz(note)

    def wave_at(i: int) -> float:
        t = i / RATE
        value = sum(s * math.sin(math.tau * hz * k * t) * math.exp(-k * t) for k, s in PIANO)
        return shape(i, count, attack=RATE / 200) * math.exp(-3.5 * t) * value

    return pack(count, 0.55, wave_at)


DRAWBARS = ((0.5, 0.8), (1, 1.0), (2, 0.7), (3, 0.4), (4, 0.3), (6, 0.15), (8, 0.1))
LOUD_ORGAN = 2.1                                    # 重ねたときの山の高さ（測った値）


def organ(note: int, seconds: float) -> array:
    """エレクトーン。倍音を足し合わせて持続させる。

    本物のオルガンは「ドローバー」を引いて倍音の量を決める。それを表にしたのが DRAWBARS。
    reduce で表を 1 つの波に畳む。減衰しないかわりに、ゆれ（トレモロ）を少し乗せる。
    """
    count, hz = int(RATE * seconds), pitch_hz(note)

    def wave_at(i: int) -> float:
        phase = hz * i / RATE
        value = reduce(lambda total, bar: total + bar[1] * math.sin(math.tau * bar[0] * phase),
                       DRAWBARS, 0.0) / LOUD_ORGAN
        wobble = 1 + 0.06 * math.sin(math.tau * 6 * i / RATE)
        return shape(i, count, attack=RATE / 60) * wobble * value

    return pack(count, 1.0, wave_at)


def pluck(note: int, seconds: float, damp: float, blend: float) -> array:
    """弦をはじく（Karplus-Strong）。

    弦の長さぶんの雑音を用意し、先頭を取り出しては「となりと平均して」末尾に戻す。
    これだけで、雑音が一周ごとに丸くなって弦の音になる。deque(maxlen=) が弦そのもの。
    平均するたびに高い成分から消えるので、はじいた直後は明るく、あとは太く残る。
    """
    count = int(RATE * seconds)
    length = max(2, int(RATE / pitch_hz(note)))     # 一周が音の高さになる
    luck = random.Random(1)                         # 種を固定。端末とブラウザで同じ雑音にする
    string = deque((luck.uniform(-1, 1) for _ in range(length)), maxlen=length)
    last = 0.0

    def wave_at(i: int) -> float:
        nonlocal last
        first = string[0]
        value = damp * (blend * first + (1 - blend) * last)
        string.append(value)
        last = first
        return shape(i, count, attack=1, release=RATE / 20) * value

    return pack(count, 1.0, wave_at)


def guitar(note: int, seconds: float) -> array:
    """ギター。弦をはじく。"""
    return pluck(note, seconds, damp=0.995, blend=0.5)


def bass(note: int, seconds: float) -> array:
    """ベース。1 オクターブ下の弦を、平均を強めにして太く。"""
    return pluck(note - 12, seconds, damp=0.998, blend=0.7)


def xylophone(note: int, seconds: float) -> array:
    """木琴。基音と、4 倍近くの高い倍音を 1 つだけ、短く減衰させる。"""
    count, hz = int(RATE * seconds), pitch_hz(note)

    def wave_at(i: int) -> float:
        t = i / RATE
        value = (math.sin(math.tau * hz * t) * math.exp(-9 * t)
                 + 0.35 * math.sin(math.tau * hz * 3.98 * t) * math.exp(-22 * t))
        return shape(i, count, attack=1, release=RATE / 50) * value

    return pack(count, 0.8, wave_at)


VOICES: tuple[tuple[str, Voice], ...] = (
    ("ピアノ", piano), ("エレクトーン", organ), ("ギター", guitar), ("ベース", bass), ("木琴", xylophone),
)


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


def melody(notes: list[int], seconds: float = NOTE, voice: Voice = piano) -> array:
    """音を並べて 1 本の列にする。楽器は外から渡す。"""
    line = array("h")
    for note in notes:
        line.extend(voice(note, seconds))
    return line


# ── 曲集 ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Song:
    """1 曲。notes は「いちばん低い音を 0 とした半音の番号」。

    どの高さで鳴らすかは OFFSET で決めるので、曲の側は形だけを持つ。
    """

    name: str
    who: str
    notes: list[int]

    def on_board(self) -> list[int]:
        """鍵盤の上に置いた音の番号にする。"""
        return [note + OFFSET for note in self.notes]


SONGS = [
    Song("うれしいひなまつり", "河村光陽（1946 没）", [0, 0, 0, 2, 3, 2, 0]),
    Song("雀の学校", "弘田龍太郎（1952 没）", [0, 3, 3, 3, 0, 3, 3, 3]),
    Song("かごめかごめ", "わらべうた", [0, 0, 2, 0, 2, 3, 2, 0, 0, 2, 0]),
    Song("アルプス一万尺", "アメリカ民謡", [0, 0, 2, 4, 0, 4, 2]),
    Song("メリーさんのひつじ", "アメリカ民謡", [4, 2, 0, 2, 4, 4, 4]),
    Song("あんたがたどこさ", "わらべうた", [0, 0, 2, 4, 4, 2, 0, 2, 4, 0]),
    Song("あめふり", "中山晋平（1952 没）", [3, 3, 0, 3, 5, 5, 3]),
    Song("かえるの合唱", "ドイツ民謡", [0, 2, 4, 5, 4, 2, 0]),
    Song("かなりや", "成田為三（1945 没）", [0, 0, 1, 3, 5, 3, 0]),
    Song("こいのぼり", "作曲者不詳（1931）", [0, 3, 3, 5, 3, 0, 3]),
    Song("月の沙漠", "佐々木すぐる（1966 没）", [2, 2, 4, 5, 4, 2, 0]),
    Song("浦島太郎", "文部省唱歌", [3, 3, 0, 3, 5, 3, 0]),
    Song("茶摘み", "文部省唱歌", [0, 0, 3, 3, 5, 3, 0]),
    Song("草競馬", "S.フォスター", [3, 3, 0, 3, 5, 3, 0]),
    Song("夕焼小焼", "草川信（1948 没）", [3, 3, 5, 3, 0, 3, 5, 3]),
    Song("春が来た", "岡野貞一（1941 没）", [3, 0, 3, 5, 3, 0, 3, 5, 3, 0]),
    Song("桃太郎", "岡野貞一（1941 没）", [3, 3, 0, 3, 5, 3, 3, 3, 0, 3, 5, 3]),
    Song("かもめの水兵さん", "河村光陽（1946 没）", [0, 4, 7, 4, 0, 4, 7]),
    Song("富士山", "文部省唱歌", [0, 4, 7, 4, 0, 4, 2]),
    Song("春よ来い", "弘田龍太郎（1952 没）", [5, 2, 5, 7, 5, 2, 0]),
    Song("証城寺の狸囃子", "中山晋平（1952 没）", [5, 5, 5, 7, 5, 2, 0]),
    Song("金太郎", "田村虎蔵（1943 没）", [4, 4, 2, 0, 4, 7, 7]),
    Song("てるてる坊主", "中山晋平（1952 没）", [0, 2, 4, 5, 7, 7, 4, 0]),
    Song("聖者の行進", "アメリカ賛美歌", [0, 4, 5, 7, 0, 4, 5, 7]),
    Song("荒城の月", "滝廉太郎（1903 没）", [0, 2, 3, 2, 0, 3, 7, 5, 3]),
    Song("ロンドン橋", "イギリス伝承", [5, 7, 5, 3, 2, 3, 5, 0, 2, 3]),
    Song("ぶんぶんぶん", "ボヘミア民謡", [7, 4, 4, 5, 2, 2, 0, 2, 4, 5, 7]),
    Song("ジングルベル", "J.ピアポント", [4, 4, 4, 4, 4, 4, 4, 7, 0, 2, 4]),
    Song("山の音楽家", "ドイツ民謡", [0, 0, 4, 4, 7, 7, 4, 5, 5, 4, 4, 2]),
    Song("ちょうちょう", "ドイツ民謡", [7, 4, 4, 5, 2, 2, 0, 2, 4, 5, 7, 7, 7]),
    Song("さくらさくら", "日本古謡", [4, 4, 6, 4, 4, 6, 4, 6, 7, 6, 4, 6, 4, 0]),
    Song("うさぎとかめ", "納所弁次郎（1936 没）", [3, 3, 0, 3, 8, 5, 3]),
    Song("七つの子", "本居長世（1945 没）", [5, 3, 0, 3, 5, 8, 5, 3]),
    Song("春の小川", "岡野貞一（1941 没）", [3, 3, 5, 3, 0, 3, 5, 8]),
    Song("きらきら星", "フランス民謡", [0, 0, 7, 7, 9, 9, 7]),
    Song("シャボン玉", "中山晋平（1952 没）", [4, 7, 9, 7, 4, 2, 0]),
    Song("赤い靴", "本居長世（1945 没）", [4, 7, 9, 7, 4, 2, 0]),
    Song("この道", "山田耕筰（1965 没）", [0, 4, 7, 9, 7, 4, 2, 0]),
    Song("もみじ", "岡野貞一（1941 没）", [4, 7, 7, 9, 7, 4, 2, 0]),
    Song("峠の我が家", "アメリカ民謡", [0, 5, 5, 7, 9, 5, 4, 2]),
    Song("浜辺の歌", "成田為三（1945 没）", [0, 2, 4, 7, 9, 7, 4, 2]),
    Song("蛍の光", "スコットランド民謡", [0, 5, 5, 9, 7, 5, 7, 9]),
    Song("靴が鳴る", "弘田龍太郎（1952 没）", [0, 4, 7, 7, 9, 7, 5, 4, 2]),
    Song("朧月夜", "岡野貞一（1941 没）", [0, 4, 7, 9, 7, 4, 2, 4, 2, 0]),
    Song("どんぐりころころ", "梁田貞（1959 没）", [4, 4, 7, 7, 9, 9, 7, 4, 4, 2, 2, 0]),
    Song("おおスザンナ", "S.フォスター", [0, 2, 4, 7, 7, 9, 7, 4, 0, 2, 4, 4, 2, 0, 2]),
    Song("赤とんぼ", "山田耕筰（1965 没）", [4, 7, 9, 12, 9, 7, 4, 2, 0]),
]

# ── 鍵盤 ────────────────────────────────────────────────────────────────

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
    """お題の音を横に並べる。

    1 列が 1 音。色でその音がどうなっているかを出す。
      青  決まった（もう動かない）
      橙  いま打ち込んでいる
      赤  さっきの答え合わせで違っていた（次に何か押すと消える）
    いま打ち込む列は縦の帯で示す。**どこに入るのかが見えないと、耳より先に迷う。**

    縦は半音 1 つが SEMI ドット。窓の高さは曲によらず SPAN 半音で固定してある——
    曲に合わせて伸び縮みさせると、目盛りの間隔が「その曲の音の幅」を教えてしまう。
    位置だけは曲の真ん中に合わせる（せまい曲が鍵盤に張りつかないように）。
    """
    count = len(game.answer)
    step = (WIDTH - LEFT * 2) // count
    goal = game.goal
    high = OFFSET + game.shift + SPAN - (SPAN - max(game.song.notes)) // 2
    tall = SPAN * SEMI + SEMI
    base = ROLL_TOP + tall            # 印を置く行。鍵盤とぶつからない高さ
    here = game.at()
    if here is not None:                            # いま打ち込む列を先に塗る（目盛りの下）
        screen.box(LEFT + here * step, ROLL_TOP, step - 2, tall, BAND)
    for line in range(SPAN + 1):                    # 半音ごとの目盛り。空いた所も「音の高さ」だと分かる
        y = ROLL_TOP + line * SEMI + SEMI - 1
        color = FAINT if (high - line) == goal[0] else GRID
        for x in range(LEFT, LEFT + count * step - 2):
            screen.plot(x, y, color)
    for i in range(count):
        x = LEFT + i * step
        if game.fixed[i]:
            note, color, mark = goal[i], SURE, SURE
        elif game.missed[i] is not None:
            note, color, mark = game.missed[i], MISS, MISS
        elif game.typed[i] is not None:
            note, color, mark = game.typed[i], TRY, TRY
        elif i == 0:
            note, color, mark = goal[0], HINT, TRY if i == here else GRID
        else:
            note, color, mark = None, None, TRY if i == here else GRID
        screen.box(x + step // 2 - 1, base + 2, 2, 2, mark)
        if note is None:
            continue
        if high - SPAN <= note <= high:
            screen.box(x, ROLL_TOP + (high - note) * SEMI, step - 2, SEMI, color)
        else:                                       # 窓の外の音。端に細く出して「外にある」と示す
            edge = ROLL_TOP if note > high else ROLL_TOP + tall - 1
            screen.box(x, edge, step - 2, 1, color)
    for x in range(LEFT, LEFT + count * step - 2):
        screen.plot(x, base, LINE)


def board(screen: "Screen", game: "Game") -> None:
    """25 鍵の鍵盤。黒鍵をあとに描いて白鍵の上に載せる。

    **決まった音の鍵は青く塗る。** 上のバーと鍵盤がこれでつながる——
    「青いバーはこの鍵のこと」が一目で分かるようにするため。
    もう分かっている音なので、これで教えすぎになることもない。
    """
    goal = game.goal
    done = {goal[i] for i in range(len(goal)) if game.fixed[i]}
    start = goal[0] if game.at() == 0 else None     # おすすめの始まりの鍵
    for index, note in enumerate(WHITE):
        x, y, w, h = white_box(index)
        screen.box(x, y, w, h, LIT if note == game.lit else SURE_W if note in done
                   else HINT_W if note == start else INK)
        screen.frame(x, y, w, h, SHADE)
    for index, note in enumerate(BLACK):
        x, y, w, h = black_box(index)
        screen.box(x, y, w, h, LIT if note == game.lit else SURE_B if note in done
                   else HINT if note == start else EBONY)


def draw(screen: "Screen", game: "Game") -> None:
    screen.clear()
    screen.box(0, 0, WIDTH, HEIGHT, BACK)
    roll(screen, game)
    board(screen, game)


# ── ゲーム ──────────────────────────────────────────────────────────────

@dataclass
class Game:
    """遊びの状態。端末もブラウザもこれ 1 つを進める。"""

    index: int = 0                                  # 何曲目
    typed: list[int | None] = field(default_factory=list)
    fixed: list[bool] = field(default_factory=list)
    missed: list[int | None] = field(default_factory=list)  # 答え合わせで違っていた音
    heard: int = 0                                  # お題を聞いた回数
    tries: int = 0                                  # 答え合わせをした回数
    lit: int | None = None                          # いま光っている鍵
    shift: int = 0                                  # 弾いている高さのずれ（半音）
    voice: int = 0                                  # 楽器（VOICES の番号）
    call: str = ""                                  # GOOD / ALMOST / BAD
    stars: list[int] = field(default_factory=list)
    cleared: bool = False
    message: str = ""

    def __post_init__(self):
        if not self.typed:
            self.start()

    @property
    def song(self) -> Song:
        return SONGS[self.index]

    @property
    def answer(self) -> list[int]:
        """お題として鳴らす音。ここは動かさない。"""
        return self.song.on_board()

    @property
    def goal(self) -> list[int]:
        """答え合わせの相手。弾いている高さに合わせてずらしたもの。

        耳コピは「音の形」を写す遊びなので、**どの高さから弾いても正解**にする。
        絶対音感がないと出だしの高さは決められないし、決められないと全部はずれる。
        """
        return [note + self.shift for note in self.answer]

    @property
    def sound(self) -> Voice:
        """いま選んでいる楽器。お題も鍵盤もこれで鳴る。"""
        return VOICES[self.voice][1]

    def switch(self) -> str:
        """次の楽器へ。最後まで行ったら最初へ戻る。曲や打ち込みには触らない。"""
        self.voice = (self.voice + 1) % len(VOICES)
        return VOICES[self.voice][0]

    def shifts(self) -> range:
        """25 鍵に収まる範囲で、曲を置ける高さのずれ。"""
        return range(-OFFSET, 25 - OFFSET - max(self.song.notes) + 1)

    def start(self) -> None:
        """新しい曲を出す。1 音目の高さは**下書きとして見せるだけ**にする。

        見せないと、絶対音感が無いかぎり出だしの高さを当てられない。
        かといって埋めてしまうと、**聞いたとおりに全部打つと 1 つずれる**。
        だから見せるが埋めない。打ち込むのは 1 音目から。
        """
        answer = self.answer
        self.typed = [None] * len(answer)
        self.fixed = [False] * len(answer)
        self.missed = [None] * len(answer)
        self.shift = 0
        self.call = ""
        self.heard = 0
        self.tries = 0
        self.lit = None
        self.cleared = False
        self.message = "まずお題を聞いてください"

    def at(self) -> int | None:
        """次に打ち込む場所。確定していなくて、まだ空いているところの左から。"""
        for i, (note, done) in enumerate(zip(self.typed, self.fixed)):
            if not done and note is None:
                return i
        return None

    def press(self, note: int) -> bool:
        """鍵を押す。打ち込む場所があれば入れる。"""
        self.lit = note
        self.forget()
        spot = self.at()
        if spot is None or self.cleared:
            return False
        self.typed[spot] = note
        self.message = self.left()
        return True

    def left(self) -> str:
        """あと何音そろえればいいか。**押すべきときが分かるように、いつも出す。**"""
        rest = sum(1 for i, note in enumerate(self.typed) if not self.fixed[i] and note is None)
        if rest == 0:
            return "そろった。リターンで答え合わせ"
        return f"{len(self.typed)} 音の曲。あと {rest} 音"

    def forget(self) -> None:
        """さっきの答え合わせの跡（赤い印と GOOD/BAD）を消す。何か打ったら消える。"""
        if self.call or any(note is not None for note in self.missed):
            self.missed = [None] * len(self.typed)
            self.call = ""

    def erase(self) -> None:
        """最後に打ち込んだ音を消す。確定した音は消せない。"""
        self.forget()
        for i in reversed(range(len(self.typed))):
            if not self.fixed[i] and self.typed[i] is not None:
                self.typed[i] = None
                self.message = self.left()
                return

    def judge(self) -> bool:
        """答え合わせ。合っていた音だけを確定させ、違った音は消す。

        位置も高さも教えない。合っていたかどうかだけ。
        耳で確かめれば分かることを字で教えると、耳を使わずに解けてしまう。

        違っていた音は**赤のまま残す**。黙って消すと、何が起きたのか分からない。
        次に鍵を押したときに消える。
        """
        if self.at() is not None or self.cleared:
            self.message = "まだ全部そろっていない"
            return False
        self.tries += 1
        if not any(self.fixed):                     # まだ何も決まっていないうちは高さを選び直す
            answer = self.answer
            self.shift = max(self.shifts(), key=lambda d: (
                sum(1 for i, note in enumerate(self.typed) if note == answer[i] + d), -abs(d)))
        goal = self.goal
        self.missed = [None] * len(goal)
        for i in range(len(goal)):
            if self.typed[i] == goal[i]:
                self.fixed[i] = True
            else:
                self.missed[i] = self.typed[i]      # 何を押したかを赤で残す
                self.typed[i] = None
        wrong = sum(1 for note in self.missed if note is not None)
        if all(self.fixed):
            self.cleared = True
            self.call = "GOOD！"
            self.stars.append(self.score())
            how = f"（{self.shift:+d} 半音の高さで弾きましたが、形が同じなので正解）" if self.shift else ""
            self.message = f"★ {self.score()}{how}"
        else:
            self.call = "ALMOST！" if wrong <= ALMOST else "BAD！"
            self.message = (f"青が {sum(self.fixed)} 音そろった。"
                            f"赤い {wrong} 音をもう一度")
        return self.cleared

    def score(self) -> int:
        """星の数。聞いた回数と答え合わせの回数が少ないほど多い。"""
        if self.heard <= 3 and self.tries <= 2:
            return 3
        if self.heard <= 6 and self.tries <= 4:
            return 2
        return 1

    def advance(self) -> bool:
        """次の曲へ。最後まで行ったら False。"""
        if self.index + 1 >= len(SONGS):
            return False
        self.index += 1
        self.start()
        return True


def obey(game: Game, key: str) -> tuple[list[int], float, Voice] | None:
    """キーを 1 つ受け取ってゲームを進め、鳴らすものがあれば (音, 長さ, 楽器) で返す。

    端末もブラウザもここを通る。鳴らし方は違っても、判断はここ 1 か所。
    """
    if key == "voice":                                  # 楽器を変える。遊びには触らない
        game.message = f"楽器: {game.switch()}"
        return [game.goal[0]], TAP, game.sound          # 変わった音をひとつ鳴らして聞かせる
    if key == "space":                                  # いつでも「お題を聞く」だけ
        if game.cleared:
            return game.answer, NOTE, game.sound        # クリア後は聞き直すだけ。進まない
        game.heard += 1
        game.message = game.left()
        return game.answer, NOTE, game.sound
    if key == "enter":                                  # 「答え合わせ」、クリア後は「次の曲へ」
        if game.cleared:
            if not game.advance():
                game.message = "最後の曲です"
            return None
        game.judge()
        return None
    if key == "back":
        game.erase()
        return None
    note = CHARS.get(key)
    if note is None:
        return None
    game.press(note)
    return [note], TAP, game.sound


# ── 端末 ────────────────────────────────────────────────────────────────

class Speaker:
    """端末で音を出す係。wav をいったんファイルにして afplay に渡す。

    同じ音は作り直さない（1 音つくるのに 7500 回の sin がいる）。
    """

    def __init__(self):
        self.player = shutil.which("afplay") or shutil.which("aplay")
        self.folder = tempfile.mkdtemp(prefix="ear-piano-")
        self.made: dict[tuple, str] = {}
        self.now: subprocess.Popen | None = None

    def say(self, notes: list[int], seconds: float, voice: Voice) -> None:
        if self.player is None:
            return
        want = (tuple(notes), seconds, voice.__name__)
        if want not in self.made:
            path = os.path.join(self.folder, f"{len(self.made)}.wav")
            with open(path, "wb") as out:
                out.write(wav_bytes(melody(notes, seconds, voice)))
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
         "\t": "voice"}


def show(screen: Screen, game: Game) -> str:
    """画面と、その下に出す字。"""
    draw(screen, game)
    star = "".join("★" * n + "・" for n in game.stars[-12:])
    lines = [
        screen.render(),
        f" {game.index + 1:2d}/{len(SONGS)}曲目  {game.song.name}  楽器 {VOICES[game.voice][0]}  "
        f"聞いた {game.heard} 回  答え合わせ {game.tries} 回",
        f" {game.call}",
        f" {game.message}",
        f" {star}",
        (" スペース=もう一度聞く　リターン=次の曲へ　Tab=楽器　Esc=やめる" if game.cleared else
         " スペース=お題　リターン=答え合わせ　BS=1つ消す　Tab=楽器　Esc=やめる"),
        " 白鍵 z x c v b n m q w e r t y u i ／ 黒鍵 s d g h j 2 3 5 6 7",
    ]
    return "\n".join(lines)


def run() -> None:
    """端末で遊ぶ。耳コピはターン制なので、キーを 1 つずつ待てばよい。"""
    import termios
    import tty

    speaker = Speaker()
    screen, game = Screen(), Game()
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


# ── 確かめる ────────────────────────────────────────────────────────────

def check() -> None:
    """決まりを機械に確かめさせる。"""
    print("● 音の高さ")
    assert abs(pitch_hz(9) - 440.0) < 1e-9, pitch_hz(9)
    assert abs(pitch_hz(21) - 880.0) < 1e-9, pitch_hz(21)
    assert abs(pitch_hz(1) / pitch_hz(0) - 2 ** (1 / 12)) < 1e-12
    print(f"  ラ(9) = {pitch_hz(9):.2f} Hz / 1 オクターブ上 = {pitch_hz(21):.2f} Hz")
    print(f"  ド = {pitch_hz(0):.2f} Hz、25 鍵の上端 = {pitch_hz(24):.2f} Hz")

    print("● 楽器")
    import time
    peaks = {}
    for name, voice in VOICES:
        started = time.perf_counter()
        line = melody(SONGS[0].on_board(), NOTE, voice)
        took = (time.perf_counter() - started) * 1000
        assert len(line) == len(SONGS[0].notes) * int(RATE * NOTE), name
        peak = max(abs(v) for v in line)
        assert peak <= 32767 * VOLUME * 1.05, f"{name} が頭打ちしている（{peak}）"
        assert line == melody(SONGS[0].on_board(), NOTE, voice), f"{name} が毎回違う音になる"
        one = voice(9, 0.5)
        head = max(abs(v) for v in one[:len(one) // 10])
        tail = max(abs(v) for v in one[len(one) * 6 // 10:len(one) * 8 // 10])  # 消え始める前
        peaks[name] = line
        kind = "持続" if tail > head * 0.5 else "減衰"
        print(f"  {name:6s} 7 音 {took:5.0f} ms　いちばん大きい標本 {peak:5d}　"
              f"出だし {head:5d} → 終わり {tail:5d}（{kind}）")
    assert len({bytes(v) for v in peaks.values()}) == len(VOICES), "同じ音になっている楽器がある"
    def late(voice: Voice) -> int:
        one = voice(9, 0.5)
        return max(abs(v) for v in one[len(one) * 6 // 10:len(one) * 8 // 10])

    assert late(organ) > late(piano) * 3, "エレクトーンがピアノと同じように減衰している"
    print(f"  {len(VOICES)} 種とも別の音。同じ呼び方なら毎回同じ bytes（弦の雑音も種を固定）")

    print("● wav の中身")
    samples = piano(9, 0.2)
    data = wav_bytes(samples)
    assert data[:4] == b"RIFF" and data[8:12] == b"WAVE", data[:12]
    with wave.open(io.BytesIO(data)) as back:
        assert back.getnchannels() == 1 and back.getsampwidth() == 2
        assert back.getframerate() == RATE
        again = array("h")
        again.frombytes(back.readframes(back.getnframes()))
    assert again == samples, "書いて読み戻したら違うものになった"
    assert len(samples) == int(RATE * 0.2) == 4410
    print(f"  {len(data)} バイト / 標本 {len(samples)} 個 / 読み戻して一致")
    assert max(samples) <= 32767 and min(samples) >= -32768
    assert abs(samples[0]) < 100 and abs(samples[-1]) < 100, "端が切れている（プツッと鳴る）"
    print(f"  いちばん大きい標本 {max(samples)}（頭打ち {int(32767 * VOLUME)} 以内）")

    print("● 曲集")
    assert len(SONGS) == 47, len(SONGS)
    for song in SONGS:
        notes = song.on_board()
        assert min(song.notes) == 0, song.name
        assert all(0 <= note <= 24 for note in notes), song.name
        assert max(song.notes) <= SPAN, f"{song.name} は幅 {max(song.notes)} で入りきらない"
        assert 7 <= len(notes) <= 15, song.name
    widths = [max(s.notes) for s in SONGS]
    counts = [len(s.notes) for s in SONGS]
    assert widths == sorted(widths), "やさしい順に並んでいない"
    print(f"  {len(SONGS)} 曲 / 音の幅 {min(widths)}〜{max(widths)} / 音の数 {min(counts)}〜{max(counts)}")

    print("● 鍵盤")
    assert len(WHITE) == 15 and len(BLACK) == 10 and len(CHARS) == 25
    assert sorted(WHITE + BLACK) == list(range(25))
    for note in range(25):
        box = white_box(WHITE.index(note)) if note in WHITE else black_box(BLACK.index(note))
        x, y, w, h = box
        assert key_at(x + w // 2, y + h - 2) == note, note
    assert key_at(0, 0) is None
    print(f"  25 鍵すべて、真ん中を押すとその音が返る（左端 {LEFT} 〜 右端 {LEFT + 15 * WHITE_W}）")

    print("● 遊びの決まり")
    game = Game()
    assert not any(game.fixed) and not any(game.typed), "はじめは何も埋まっていないはず"
    assert game.at() == 0, "打ち込みは 1 音目から始まるはず"
    for note in game.answer:                        # 聞いたとおり、音の数だけ打つ
        game.press(note)
    assert game.at() is None, "音の数と打ち込む場所の数が合っていない"
    assert game.judge() and game.cleared, "正解を打ち込んだのにクリアにならない"
    assert game.stars == [3], game.stars
    print("  聞いた音の数だけ打てば、そのままそろう（ずれない）")

    game = Game()
    answer = game.answer
    for i in range(len(answer)):                    # わざと 1 音だけ間違える
        game.press(answer[i] if i != 2 else answer[2] + 1)
    assert not game.judge()
    assert sum(game.fixed) == len(answer) - 1
    assert game.typed[2] is None and game.missed[2] == answer[2] + 1, "違った音は赤で残るはず"
    kept = list(game.fixed)
    game.press(answer[2] + 5)                       # 確定した音は動かない
    assert all(note is None for note in game.missed), "何か押したら赤は消えるはず"
    game.judge()
    assert all(a or not b for a, b in zip(game.fixed, kept))
    print("  合った音だけ残り、違った音は赤で残り、確定した音は動かない")

    print("● どの高さから弾いても正解になるか")
    tries = ok = 0
    for index, song in enumerate(SONGS):
        for shift in Game(index=index).shifts():
            game = Game(index=index)
            for note in game.answer:                # 同じ形を、別の高さで弾く
                game.press(note + shift)
            game.judge()
            tries += 1
            ok += game.cleared
    assert ok == tries, f"{tries - ok} 通りが正解にならない"
    print(f"  47 曲 × 置ける高さぜんぶ = {tries} 通り、すべてクリアできる")
    game = Game(index=1)
    answer = game.answer
    for i, note in enumerate(answer):               # 形が違えば、ずらしても直らない
        game.press(note + 5 + (1 if i == 3 else 0))
    game.judge()
    assert not game.cleared and sum(game.fixed) == len(answer) - 1
    print(f"  形が 1 音違えば、どう置き直しても合わない（{sum(game.fixed)} / {len(answer)}）")

    print("● 鍵盤ぜんぶが画面に出るか")
    counts = []
    for index, song in enumerate(SONGS):
        high = OFFSET + SPAN - (SPAN - max(song.notes)) // 2
        counts.append(sum(1 for note in range(25) if not (high - SPAN <= note <= high)))
    print(f"  窓は 13 半音なので、25 鍵のうち {min(counts)}〜{max(counts)} 鍵は窓の外に来る。")
    print("  窓の外の音は端に細く出す（押しても何も起きない、にはしない）")


    print("● どの曲も必ず解ける（総当たりの上限）")
    worst = 0
    for index in range(len(SONGS)):
        game = Game(index=index)
        for guess in range(25):
            if game.cleared:
                break
            while (spot := game.at()) is not None:
                game.typed[spot] = guess             # 分からないところを全部その音で埋める
            game.judge()
        assert game.cleared, SONGS[index].name
        worst = max(worst, game.tries)
    print(f"  47 曲すべて、いちばんかかっても答え合わせ {worst} 回で解ける（鍵盤 25 鍵が上限）")

    print("● 端末とブラウザで同じ音が鳴るか")
    same = wav_bytes(melody(SONGS[0].on_board(), NOTE, guitar))
    assert same == wav_bytes(melody(SONGS[0].on_board(), NOTE, guitar)), "同じ曲から違う wav が出た"
    print(f"  1 曲目の wav は {len(same)} バイト。この bytes をそのまま両方へ渡す")

    print("\nぜんぶ通った。")


def write_wav(index: int) -> None:
    """耳で確かめる用に、1 曲を楽器ぜんぶで書き出す。"""
    song = SONGS[index]
    for name, voice in VOICES:
        path = f"{index:02d}-{song.name}-{name}.wav"
        with open(path, "wb") as out:
            out.write(wav_bytes(melody(song.on_board(), NOTE, voice)))
        print(f"{path} に書き出した")


def main() -> None:
    if "--check" in sys.argv:
        check()
    elif "--wav" in sys.argv:
        write_wav(int(sys.argv[sys.argv.index("--wav") + 1]))
    else:
        run()


if __name__ == "__main__":
    main()
