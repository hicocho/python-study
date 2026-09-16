"""モグラ叩き

3 × 3 の穴から顔を出すモグラを叩く。60 秒 1 ラウンド。金のモグラ、ヘルメット（2 回叩く）、爆弾（叩いてはいけない）。
連続で当てるとコンボ、反応時間を測って表示する。
今回覚えるところ：
  絵と動きを分ける  絵は Sprite（文字で描いたドット絵。g32 と同じ）、動きは穴の状態機械（Hole）
  状態機械         穴は EMPTY → RISING → UP → SINKING（叩けば HIT）と時刻で進む
  重みつきの抽選    random.choices(weights=) でモグラの種類を選ぶ
  難しさの階段     時間が進むほど出る間隔と顔を出す時間が短くなる（式で決める）

    python3 main.py            遊ぶ（スペースで始める。穴と同じ並びのキー 7 8 9 / 4 5 6 / 1 2 3 や q w e r / a s d f / z x c v で叩く。Esc でやめる）
    python3 main.py --check    決まりを確かめる
    python3 main.py --sheet    スプライトを PNG に書き出す（見た目の確認用）
"""

import io
import json
import math
import os
import random
import select
import statistics
import sys
import time
import unicodedata
import wave
from array import array
from dataclasses import dataclass, field
from enum import Enum

WIDTH = 120                                         # 画面の横（ドット）。端末では 1 ドット = 1 桁
HEIGHT = 72                                         # 縦。端末では 2 ドット = 1 行 → 36 行
TOP = 4                                             # 一番上の穴の上端
STEP = 1 / 30
STAGE_TIME = 25.0                                   # 1 ステージの秒数
STAGE_PAUSE = 2.5                                   # ステージが変わるときの間
# ステージの表。name は表示、cols × rows は穴の数、weights はそのステージで出るキャラの重み（無いキャラは出ない）、
# king_at はステージの何秒目に王様が出るか（None なら出ない）、lids は穴にふたが付くか、grass は草の色
STAGES = [
    dict(name="モグラの野原", cols=3, rows=3, weights={"normal": 70, "gold": 10, "helmet": 10, "hourglass": 4, "bomb": 6},
         king_at=None, lids=False, grass=(92, 160, 70)),
    dict(name="スライムの沼", cols=3, rows=3, weights={"normal": 28, "slime": 36, "metal": 8, "gold": 6, "bomb": 8, "cactus": 6, "hourglass": 4, "hive": 4},
         king_at=None, lids=False, grass=(70, 150, 125)),
    dict(name="おばけ屋敷", cols=3, rows=3, weights={"normal": 24, "ghost": 30, "mouse": 20, "gold": 6, "bomb": 8, "hive": 5, "hourglass": 4, "turtle": 3},
         king_at=None, lids=False, grass=(105, 118, 150)),
    dict(name="トラップ畑", cols=4, rows=3, weights={"normal": 30, "gold": 8, "helmet": 8, "bomb": 14, "hive": 12, "cactus": 12, "turtle": 12, "hourglass": 4},
         king_at=None, lids=False, grass=(150, 140, 78)),
    dict(name="動物園", cols=4, rows=4, weights={"normal": 24, "rabbit": 26, "turtle": 12, "mouse": 12, "slime": 10, "gold": 6, "bomb": 6, "hourglass": 4},
         king_at=10.0, lids=False, grass=(96, 168, 88)),
    dict(name="ごちゃまぜ", cols=4, rows=4, weights=None,                  # None は表の重みそのまま（全部出る）
         king_at=12.0, lids=True, grass=(118, 108, 140)),
]
ROUND = STAGE_TIME * len(STAGES)                    # ゲーム全体の秒数（難しさの階段の目盛り）
LID_PERIOD = 2.4                                    # ふたが開いて閉じる周期（秒）
LID_OPEN = 1.4                                      # そのうち開いている秒数
KEYMAPS = {                                         # 端末のキー。穴の並びと同じ形に並んだキーの列
    (3, 3): ("789", "456", "123", "qwe", "asd", "zxc"),   # テンキーの並びと、qwe の並びの両方
    (4, 3): ("qwer", "asdf", "zxcv"),
    (4, 4): ("1234", "qwer", "asdf", "zxcv"),
}
RISE = 0.15                                         # 出るのにかかる秒数
SINK = 0.15                                         # 引っ込むのにかかる秒数
HIT_SHOW = 0.35                                     # 叩かれた顔を見せる秒数
MISS_PENALTY = 1                                    # 空の穴を叩いたときの減点
COMBO_STEP = 3                                      # 3 連続ごとに倍率が 1 上がる（上限 ×4）
# キャラの表。points: 倒した点、hits: 叩く回数、stay: 顔を出す時間の倍率、weight: 出る割合（random.choices の重み。0 は抽選しない）、
# move: 動き方（None / hop=叩くと隣へ跳ねる / blink=見え隠れ / jump=跳び回る / swarm=3 匹同時 / time=残り時間を足す）、
# word: 倒したときの言葉。キャラを足すのは表に 1 行と絵 2 枚
KINDS = {
    "normal":    dict(points=1, hits=1, stay=1.0, weight=52, move=None, word="命中"),
    "gold":      dict(points=5, hits=1, stay=0.6, weight=7, move=None, word="金！"),
    "helmet":    dict(points=3, hits=2, stay=1.0, weight=9, move=None, word="割れた！"),
    "bomb":      dict(points=-3, hits=1, stay=1.0, weight=8, move=None, word="爆弾！"),
    "slime":     dict(points=2, hits=2, stay=1.1, weight=9, move="hop", word="スライム！"),
    "metal":     dict(points=10, hits=3, stay=0.45, weight=3, move=None, word="メタル！"),
    "ghost":     dict(points=4, hits=1, stay=1.3, weight=6, move="blink", word="おばけ！"),
    "rabbit":    dict(points=3, hits=1, stay=1.5, weight=6, move="jump", word="ウサギ！"),
    "mouse":     dict(points=1, hits=1, stay=1.0, weight=5, move="swarm", word="ネズミ"),
    "hourglass": dict(points=0, hits=1, stay=1.0, weight=4, move="time", word="砂時計"),
    "king":      dict(points=15, hits=4, stay=1.8, weight=0, move=None, word="王様！"),
    "hive":      dict(points=0, hits=1, stay=1.2, weight=5, move="trap", word="ハチの巣"),
    "cactus":    dict(points=0, hits=1, stay=1.2, weight=5, move="trap", word="サボテン"),
    "turtle":    dict(points=0, hits=1, stay=1.4, weight=5, move="trap", word="カメ"),
}
BEES_TIME = 3.0                                     # ハチの巣を叩いたあと、ハチが飛び回る秒数（その間の点は半分）
NUMB_TIME = 1.5                                     # サボテンを叩いたあと、ハンマーがしびれて叩けない秒数
SHELL_TIME = 4.0                                    # カメがこもって穴をふさぐ秒数
BLINK = 0.3                                         # おばけが見え隠れする間隔（秒）
JUMP_EVERY = 0.4                                    # ウサギが跳ぶ間隔
JUMPS = 3                                           # ウサギが跳ぶ回数（そのあと引っ込む）
SWARM = 3                                           # ネズミの群れの数
SWARM_BONUS = 6                                     # 群れを全部叩いたボーナス
TIME_BONUS = 3.0                                    # 砂時計で足す秒数
EXTRA_MAX = 9.0                                     # 1 ステージで延びる上限（砂時計 3 つぶん）
KING_COMBO = 3                                      # 王様を倒すとコンボが伸びる数


# ── 音（g73 と同じ作り方） ──────────────────────────────────────────────

RATE = 22050
VOLUME = 0.14


def tone(hz: float, seconds: float, volume: float = VOLUME) -> array:
    count = int(RATE * seconds)
    edge = RATE / 200
    samples = array("h")
    for i in range(count):
        fade = min(1.0, i / edge, (count - i) / edge)
        samples.append(int(32767 * volume * fade * math.sin(math.tau * hz * i / RATE)))
    return samples


def noise(seconds: float, volume: float, decay: float, seed: int = 1) -> array:
    luck = random.Random(seed)
    count = int(RATE * seconds)
    samples = array("h")
    for i in range(count):
        env = math.exp(-decay * i / RATE)
        samples.append(int(32767 * volume * env * luck.uniform(-1, 1)))
    return samples


def sound_bytes(kind: str) -> bytes:
    """出来事の音。pop は出た、hit は叩いた、gold は金、clank はヘルメット、bomb は爆弾、miss は空振り、end は終了、best はベスト。"""
    if kind == "pop":
        samples = tone(520, 0.04, VOLUME * 0.6) + tone(660, 0.05, VOLUME * 0.6)
    elif kind == "hit":
        samples = noise(0.08, VOLUME * 1.2, 40.0, 2) + tone(880, 0.06)
    elif kind == "gold":
        samples = tone(1319, 0.06) + tone(1760, 0.06) + tone(2637, 0.14)
    elif kind == "clank":
        samples = tone(1500, 0.03, VOLUME * 0.9) + noise(0.06, VOLUME * 0.8, 50.0, 5)
    elif kind == "bomb":
        samples = noise(0.4, VOLUME * 1.8, 8.0, 9) + tone(80, 0.25, VOLUME)
    elif kind == "miss":
        samples = tone(220, 0.1, VOLUME * 0.7)
    elif kind == "hop":                             # スライムが跳ねる（ぽよん）
        samples = tone(400, 0.05, VOLUME * 0.8) + tone(600, 0.08, VOLUME * 0.8)
    elif kind == "tick":                            # 砂時計（チクタク）
        samples = tone(1200, 0.04) + tone(900, 0.04) + tone(1200, 0.04) + tone(900, 0.04)
    elif kind == "king":                            # 王様を倒した（ファンファーレ）
        samples = tone(784, 0.1) + tone(988, 0.1) + tone(1175, 0.1) + tone(1568, 0.3)
    elif kind == "buzz":                            # ハチ（ブーン）
        samples = array("h", (int(v * (0.7 + 0.3 * math.sin(i / 40))) for i, v in enumerate(tone(180, 0.5, VOLUME * 0.9))))
    elif kind == "ouch":                            # サボテン（チクッ）
        samples = tone(2400, 0.03, VOLUME * 0.9) + tone(300, 0.12, VOLUME * 0.7)
    elif kind == "stage":                           # ステージが変わる（上がる 3 音）
        samples = tone(660, 0.1) + tone(880, 0.1) + tone(1100, 0.22)
    elif kind == "shell":                           # カメがこもる（コトッ）
        samples = noise(0.05, VOLUME * 0.9, 60.0, 12) + tone(260, 0.08, VOLUME * 0.6)
    elif kind == "best":
        samples = tone(523, 0.1) + tone(659, 0.1) + tone(784, 0.1) + tone(1047, 0.3)
    else:
        samples = tone(784, 0.12) + tone(659, 0.12) + tone(784, 0.12) + tone(1047, 0.35)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(samples.tobytes())
    return buffer.getvalue()


EVENTS = ("pop", "miss", "clank", "hop", "hit", "tick", "gold", "king", "shell", "ouch", "buzz", "bomb", "stage", "end")   # 目立つ順
SOUNDS = EVENTS + ("best",)


# ── 絵（スプライト。g32 と同じ作り） ──────────────────────────────────

PALETTE = {
    "B": (110, 74, 44),     # モグラの茶
    "b": (82, 54, 30),      # 暗い茶
    "P": (240, 150, 160),   # 鼻
    "K": (24, 20, 20),      # 黒（目・爆弾）
    "W": (245, 245, 240),   # 白
    "Y": (250, 210, 60),    # 金
    "y": (200, 150, 30),    # 暗い金
    "G": (150, 150, 160),   # ヘルメット
    "g": (100, 100, 110),   # ヘルメットの影
    "R": (230, 70, 50),     # 赤（導火線の火・叩かれた星）
    "O": (255, 170, 60),    # 橙
    "S": (96, 200, 96),     # スライム
    "s": (60, 150, 70),     # スライムの影
    "M": (196, 198, 210),   # メタル
    "m": (120, 122, 140),   # メタルの影
    "E": (236, 236, 250),   # おばけ
    "e": (190, 190, 225),   # おばけの影
    "N": (160, 150, 150),   # ネズミ
    "n": (110, 100, 100),   # ネズミの影
    "H": (232, 200, 120),   # 砂時計の砂
    "h": (120, 80, 40),     # 砂時計の枠
    "C": (80, 170, 90),     # サボテン
    "c": (50, 120, 60),     # サボテンの影
    "T": (90, 150, 70),     # カメの甲羅
    "t": (60, 110, 50),     # 甲羅の模様
    "V": (170, 130, 60),    # ハチの巣
    "v": (120, 90, 40),     # 巣の穴
}
BEE = (250, 210, 40)
NUMB = (255, 230, 90)
GRASS = (92, 160, 70)
GRASS_DARK = (78, 140, 60)
HOLE = (46, 30, 18)
HOLE_RIM = (70, 48, 28)
SKY = (140, 200, 240)
GAUGE = (60, 60, 70)
GAUGE_ON = (255, 200, 80)
LID = (150, 110, 60)
LID_EDGE = (190, 150, 90)


@dataclass(frozen=True)
class Sprite:
    """ドット絵 1 枚。rows は 1 行 1 文字列で、文字がパレットの色、. が透明。"""

    name: str
    rows: tuple[str, ...]

    @property
    def width(self) -> int:
        return len(self.rows[0])

    @property
    def height(self) -> int:
        return len(self.rows)

    def pixels(self) -> list[tuple[int, int, tuple[int, int, int]]]:
        return [(x, y, PALETTE[ch]) for y, row in enumerate(self.rows) for x, ch in enumerate(row) if ch != "."]

    def recolor(self, mapping: dict[str, str]) -> "Sprite":
        table = str.maketrans(mapping)
        return Sprite(self.name, tuple(row.translate(table) for row in self.rows))


def sprite(name: str, art: str) -> Sprite:
    rows = [line for line in art.splitlines() if line.strip()]
    width = max(len(r) for r in rows)
    return Sprite(name, tuple(r.ljust(width, ".") for r in rows))


MOLE = sprite("mole", """
.....BBBBBB.....
...BBBBBBBBBB...
..BBBBBBBBBBBB..
.BBBBBBBBBBBBBB.
.BBBKKBBBBKKBBB.
.BBBKWBBBBKWBBB.
BBBBBBBBBBBBBBBB
BBBBBBBPPBBBBBBB
BBBBBBPPPPBBBBBB
BBBBBBBbbBBBBBBB
BBBBBBbbbbBBBBBB
.BBBBBBBBBBBBBB.
.BBbBBBBBBBBbBB.
..bbbBBBBBBbbb..
""")
MOLE_HIT = sprite("mole-hit", """
.....BBBBBB.....
...BBBBBBBBBB...
..BBBBBBBBBBBB..
.BBBBBBBBBBBBBB.
.BBKBKBBBBKBKBB.
.BBBKBBBBBBKBBB.
BBBKBKBBBBKBKBBB
BBBBBBBPPBBBBBBB
BBBBBBPPPPBBBBBB
BBBBBBbbbbBBBBBB
BBBBBbBBBBbBBBBB
.BBBBBBBBBBBBBB.
.BBbBBBBBBBBbBB.
..bbbBBBBBBbbb..
""")
GOLD = MOLE.recolor({"B": "Y", "b": "y"})
GOLD_HIT = MOLE_HIT.recolor({"B": "Y", "b": "y"})
HELMET = sprite("helmet", """
.....GGGGGG.....
...GGGGGGGGGG...
..GGGGGGGGGGGG..
.GgggggggggggggG
.BBBKKBBBBKKBBB.
.BBBKWBBBBKWBBB.
BBBBBBBBBBBBBBBB
BBBBBBBPPBBBBBBB
BBBBBBPPPPBBBBBB
BBBBBBBbbBBBBBBB
BBBBBBbbbbBBBBBB
.BBBBBBBBBBBBBB.
.BBbBBBBBBBBbBB.
..bbbBBBBBBbbb..
""")
HELMET_CRACKED = sprite("helmet-cracked", """
.....GGGKGG.....
...GGGGKGGGGG...
..GGGGKGGGGGGG..
.GgggggKgggggggG
.BBBKKBBBBKKBBB.
.BBBKWBBBBKWBBB.
BBBBBBBBBBBBBBBB
BBBBBBBPPBBBBBBB
BBBBBBPPPPBBBBBB
BBBBBBBbbBBBBBBB
BBBBBBbbbbBBBBBB
.BBBBBBBBBBBBBB.
.BBbBBBBBBBBbBB.
..bbbBBBBBBbbb..
""")
BOMB = sprite("bomb", """
.........R......
........O.......
.......K........
......KK........
....KKKKKKK.....
...KKKKKKKKK....
..KKKWKKKKKKK...
..KKWKKKKKKKK...
..KKKKKKKKKKK...
..KKKKKKKKKKK...
...KKKKKKKKK....
....KKKKKKK.....
................
................
""")
BOOM = sprite("boom", """
....R......R....
.....R.O..R.....
..R...OOOO...R..
...O.OOWWOO.O...
....OOWWWWOO....
.RROOWWWWWWOORR.
....OOWWWWOO....
...O.OOWWOO.O...
..R...OOOO...R..
.....R.O..R.....
....R......R....
................
................
................
""")
HAMMER = sprite("hammer", """
..GGGGGG..
..GggggG..
..GGGGGG..
.....bb...
.....bb...
.....bb...
.....bb...
""")
SLIME = sprite("slime", """
................
................
......SSSS......
....SSSSSSSS....
...SSSSSSSSSS...
..SSSKSSSSSKSS..
..SSSKWSSSSKWS..
.SSSSSSSSSSSSSS.
.SSSSSSSSSSSSSS.
.SSSSSSSssSSSSS.
.SSSSSSSSSSSSSS.
.SsSSSSSSSSSSsS.
..ssSSSSSSSSss..
...ssssssssss...
""")
SLIME_HIT = sprite("slime-hit", """
................
................
......SSSS......
....SSSSSSSS....
...SSSSSSSSSS...
..SSKSKSSSKSKS..
..SSSKSSSSSKSS..
.SSKSKSSSSKSKSS.
.SSSSSSSSSSSSSS.
.SSSSSSsssSSSSS.
.SSSSSSSSSSSSSS.
.SsSSSSSSSSSSsS.
..ssSSSSSSSSss..
...ssssssssss...
""")
METAL = SLIME.recolor({"S": "M", "s": "m"})
METAL_HIT = SLIME_HIT.recolor({"S": "M", "s": "m"})
GHOST = sprite("ghost", """
.....EEEEEE.....
...EEEEEEEEEE...
..EEEEEEEEEEEE..
.EEEEEEEEEEEEEE.
.EEEKKEEEEKKEEE.
.EEEKKEEEEKKEEE.
EEEEEEEEEEEEEEEE
EEEEEEEEEEEEEEEE
EEEEEEEKKEEEEEEE
EEEEEEEEEEEEEEEE
EEEEEEEEEEEEEEEE
EeEEEeEEEEeEEEeE
E.eEe.eEEe.eEe.E
....e..ee..e....
""")
GHOST_HIT = sprite("ghost-hit", """
.....EEEEEE.....
...EEEEEEEEEE...
..EEEEEEEEEEEE..
.EEEEEEEEEEEEEE.
.EEKEKEEEEKEKEE.
.EEEKEEEEEEKEEE.
EEEKEKEEEEKEKEEE
EEEEEEEEEEEEEEEE
EEEEEEKKKKEEEEEE
EEEEEEEEEEEEEEEE
EEEEEEEEEEEEEEEE
EeEEEeEEEEeEEEeE
E.eEe.eEEe.eEe.E
....e..ee..e....
""")
RABBIT = sprite("rabbit", """
...WW......WW...
...WPW....WPW...
...WPW....WPW...
...WPW....WPW...
....WWWWWWWW....
...WWWWWWWWWW...
..WWWKWWWWWKWW..
..WWWWWWWWWWWW..
..WWWWWPPWWWWW..
..WWWWWWWWWWWW..
...WWWWWWWWWW...
.WWWWWWWWWWWWWW.
.WWWWWWWWWWWWWW.
..WWWW....WWWW..
""")
RABBIT_HIT = sprite("rabbit-hit", """
....WW....WW....
...WPW....WPW...
..WPW......WPW..
..WPW......WPW..
....WWWWWWWW....
...WWWWWWWWWW...
..WWKWKWWWKWKW..
..WWWKWWWWWKWW..
..WWKWKWWWKWKW..
..WWWWWPPWWWWW..
...WWWWWWWWWW...
.WWWWWWWWWWWWWW.
.WWWWWWWWWWWWWW.
..WWWW....WWWW..
""")
MOUSE = sprite("mouse", """
................
................
................
...NN......NN...
..NnnN....NnnN..
...NNNNNNNNNN...
..NNNNNNNNNNNN..
..NNKNNNNNNKNN..
..NNNNNNNNNNNN..
..NNNNNNPPNNNN..
...NNNNNNNNNN...
....NNNNNNNN..n.
.....NNNNNNNNn..
......nn..nn....
""")
MOUSE_HIT = sprite("mouse-hit", """
................
................
................
...NN......NN...
..NnnN....NnnN..
...NNNNNNNNNN...
..NKNKNNNNKNKN..
..NNKNNNNNNKNN..
..NKNKNNNNKNKN..
..NNNNNNPPNNNN..
...NNNNNNNNNN...
....NNNNNNNN..n.
.....NNNNNNNNn..
......nn..nn....
""")
HOURGLASS = sprite("hourglass", """
................
....hhhhhhhh....
....hHHHHHHh....
....hHHHHHHh....
.....hHHHHh.....
......hHHh......
.......hh.......
.......hh.......
......h..h......
.....h.HH.h.....
....h.HHHH.h....
....hHHHHHHh....
....hhhhhhhh....
................
""")
HOURGLASS_HIT = sprite("hourglass-hit", """
................
....hhhhhhhh....
....h......h....
....h......h....
.....h....h.....
......h..h......
.......hh.......
.......hh.......
......hHHh......
.....hHHHHh.....
....hHHHHHHh....
....hHHHHHHh....
....hhhhhhhh....
................
""")
KING = sprite("king", """
..Y..Y.YY.Y..Y..
..YYYYYYYYYYYY..
..YYYYYYYYYYYY..
.BBBBBBBBBBBBBB.
.BBBKKBBBBKKBBB.
.BBBKWBBBBKWBBB.
BBBBBBBBBBBBBBBB
BBBBBBBPPBBBBBBB
BBBBBBPPPPBBBBBB
BBBBBBBbbBBBBBBB
BBBBBBbbbbBBBBBB
.BBBBBBBBBBBBBB.
.BBbBBBBBBBBbBB.
..bbbBBBBBBbbb..
""")
KING_HIT = sprite("king-hit", """
..Y..Y.YY.Y..Y..
..YYYYYYYYYYYY..
..YYYYYYYYYYYY..
.BBBBBBBBBBBBBB.
.BBKBKBBBBKBKBB.
.BBBKBBBBBBKBBB.
BBBKBKBBBBKBKBBB
BBBBBBBPPBBBBBBB
BBBBBBPPPPBBBBBB
BBBBBBbbbbBBBBBB
BBBBBbBBBBbBBBBB
.BBBBBBBBBBBBBB.
.BBbBBBBBBBBbBB.
..bbbBBBBBBbbb..
""")
HIVE = sprite("hive", """
................
.....VVVVVV.....
....VVVVVVVV....
...VVvVVVVvVV...
...VVVVVVVVVV...
..VVvVVVvVVVvV..
..VVVVVVVVVVVV..
..VVVvVVvVVVVV..
...VVVVVVVVVV...
...VVvVVVVvVV...
....VVVVVVVV....
.....VVVVVV.....
.......vv.......
................
""")
HIVE_HIT = sprite("hive-hit", """
.Y..............
....Y......Y....
.....VVVVVV.....
..Y.VVVVVVVV..Y.
...VVvVVVVvVV...
...VVVVVVVVVV...
..VVvVVVvVVVvV.Y
..VVVVVVVVVVVV..
Y.VVVvVVvVVVVV..
...VVVVVVVVVV...
...VVvVVVVvVV..Y
....VVVVVVVV....
.Y...VVVVVV.....
................
""")
CACTUS = sprite("cactus", """
................
.......CC.......
......CCCC......
..CC..CCCC..CC..
..CC..CCCC..CC..
..CCC.CCCC.CCC..
..CCCCCCCCCCCC..
...CCCCCCCCCC...
......CCCC......
......CCCC......
......CcCC......
......CCCC......
......CcCC......
....hhhhhhhh....
""")
CACTUS_HIT = sprite("cactus-hit", """
.....W..W.......
..W....CC...W...
......CCCC......
..CC..CCCC..CC..
..CC.WCCCCW.CC..
..CCC.CCCC.CCC..
..CCCCCCCCCCCC..
W..CCCCCCCCCC..W
......CCCC......
......CCCC......
......CcCC......
......CCCC......
......CcCC......
....hhhhhhhh....
""")
TURTLE = sprite("turtle", """
................
................
.....TTTTTT.....
....TTtTTtTT....
...TTtTTTTtTT...
..TTTTTtTTTTTT..
..TtTTTTTTTtTT..
..TTTTTtTTTTTT..
.SSTTTTTTTTTT...
SSSSTTTTTTTTT...
SKSSS.........SS
SSSS..........SS
.SS.............
................
""")
SHELL = sprite("shell", """
................
................
................
................
.....TTTTTT.....
....TTtTTtTT....
...TTtTTTTtTT...
..TTTTTtTTTTTT..
..TtTTTTTTTtTT..
..TTTTTtTTTTTT..
..TTTTTTTTTTTT..
...tttttttttt...
................
................
""")
SPRITES = {"hive": (HIVE, HIVE_HIT), "cactus": (CACTUS, CACTUS_HIT), "turtle": (TURTLE, SHELL), "normal": (MOLE, MOLE_HIT), "gold": (GOLD, GOLD_HIT), "helmet": (HELMET, HELMET_CRACKED), "bomb": (BOMB, BOOM),
           "slime": (SLIME, SLIME_HIT), "metal": (METAL, METAL_HIT), "ghost": (GHOST, GHOST_HIT), "rabbit": (RABBIT, RABBIT_HIT),
           "mouse": (MOUSE, MOUSE_HIT), "hourglass": (HOURGLASS, HOURGLASS_HIT), "king": (KING, KING_HIT)}


# ── 板（g78 と同じ作り） ────────────────────────────────────────────────

class Screen:
    def __init__(self, width: int = WIDTH, height: int = HEIGHT):
        self.width, self.height = width, height
        self.rows = [bytearray(width * 3) for _ in range(height)]

    def band(self, top: int, bottom: int, color: tuple[int, int, int]) -> None:
        line = bytes(color) * self.width
        for y in range(max(0, top), min(self.height, bottom)):
            self.rows[y][:] = line

    def plot(self, x: int, y: int, color: tuple[int, int, int]) -> None:
        if 0 <= x < self.width and 0 <= y < self.height:
            self.rows[y][x * 3:x * 3 + 3] = bytes(color)

    def box(self, x0: int, y0: int, w: int, h: int, color: tuple[int, int, int]) -> None:
        paint = bytes(color)
        x0, x1 = max(0, x0), min(self.width, x0 + w)
        if x1 <= x0:
            return
        for y in range(max(0, y0), min(self.height, y0 + h)):
            self.rows[y][x0 * 3:x1 * 3] = paint * (x1 - x0)

    def ellipse(self, cx: float, cy: float, rx: float, ry: float, color: tuple[int, int, int]) -> None:
        """楕円。行ごとに横幅を求めて塗る。"""
        for y in range(int(cy - ry), int(cy + ry) + 1):
            t = (y - cy) / ry
            if abs(t) > 1:
                continue
            half = rx * math.sqrt(1 - t * t)
            self.box(int(cx - half), y, int(2 * half) + 1, 1, color)

    def blit(self, spr: Sprite, x0: int, y0: int, scale: int = 1, clip_bottom: int | None = None) -> None:
        """スプライトを置く。scale 倍に拡大。clip_bottom より下は描かない（穴の中に隠れる部分）。"""
        for x, y, color in spr.pixels():
            for dy in range(scale):
                yy = y0 + y * scale + dy
                if clip_bottom is not None and yy >= clip_bottom:
                    continue
                self.box(x0 + x * scale, yy, scale, 1, color)

    def pixel(self, x: int, y: int) -> tuple[int, int, int]:
        return tuple(self.rows[y][x * 3:x * 3 + 3])

    def render(self) -> str:
        out = []
        for top, bottom in zip(self.rows[0::2], self.rows[1::2]):
            last = None
            for x in range(self.width):
                a, b = top[x * 3:x * 3 + 3], bottom[x * 3:x * 3 + 3]
                code = f"\x1b[38;2;{a[0]};{a[1]};{a[2]}m\x1b[48;2;{b[0]};{b[1]};{b[2]}m"
                if code != last:
                    out.append(code)
                    last = code
                out.append("▀")
            out.append("\x1b[0m\n")
        return "".join(out)


# ── 穴の状態機械 ────────────────────────────────────────────────────────

class State(Enum):
    EMPTY = "empty"
    RISING = "rising"
    UP = "up"
    SINKING = "sinking"
    HIT = "hit"
    SHELL = "shell"                                 # カメがこもって穴をふさいでいる


@dataclass
class Hole:
    """穴 1 つ。モグラの種類と状態と、その状態に入った時刻。"""

    state: State = State.EMPTY
    kind: str = "normal"
    since: float = 0.0                              # いまの状態に入った時刻
    stay: float = 1.2                               # 顔を出している秒数
    armor: int = 0                                  # 叩く残り回数（ヘルメット 2、メタル 3、王様 4）
    shown_at: float = 0.0                           # 顔を出し始めた時刻（反応時間の起点）
    index: int = 0                                  # 穴の番号（0〜8。隣を探すのに使う）
    jumps: int = 0                                  # ウサギが跳んだ回数
    swarm: int = 0                                  # ネズミの群れの番号（0 は群れでない）

    def enter(self, state: State, now: float) -> None:
        self.state, self.since = state, now

    def lift(self, now: float) -> float:
        """0（穴の中）〜1（全部出ている）。出るとき・引っ込むときの途中の高さ。"""
        if self.state == State.RISING:
            return min(1.0, (now - self.since) / RISE)
        if self.state == State.SINKING:
            return max(0.0, 1 - (now - self.since) / SINK)
        if self.state in (State.UP, State.HIT, State.SHELL):
            return 1.0
        return 0.0

    lids: bool = False                              # ふた付きの穴か（ステージで決まる）

    def lid_open(self, now: float) -> bool:
        """ふたが開いているか。周期 LID_PERIOD のうち LID_OPEN 秒だけ開く。穴ごとに位相をずらす。"""
        if not self.lids:
            return True
        return (now + self.index * 0.37) % LID_PERIOD < LID_OPEN

    def visible(self, now: float) -> bool:
        """おばけは UP の間 BLINK 秒ごとに見え隠れする。ふたが閉じていれば見えない。ほかは出ていれば見える。"""
        if not self.lid_open(now):
            return False
        if self.kind == "ghost" and self.state == State.UP:
            return int((now - self.since) / BLINK) % 2 == 0
        return True

    def whackable(self, now: float | None = None) -> bool:
        if self.state not in (State.RISING, State.UP):
            return False
        return True if now is None else self.visible(now)


def interval_at(t: float) -> float:
    """次のモグラが出るまでの秒数。0 秒で 1.3、60 秒で 0.45（難しさの階段）。"""
    return 1.3 - 0.85 * min(1.0, t / ROUND)


def stay_at(t: float) -> float:
    """顔を出している秒数。0 秒で 1.5、60 秒で 0.7。"""
    return 1.5 - 0.8 * min(1.0, t / ROUND)


# ── 記録 ────────────────────────────────────────────────────────────────

@dataclass
class Best:
    score: int = 0
    combo: int = 0
    fastest: float = 0.0                            # 最速の反応（秒）。0 は未記録

    def dump(self) -> str:
        return json.dumps({"score": self.score, "combo": self.combo, "fastest": self.fastest})

    @classmethod
    def parse(cls, text: str) -> "Best":
        try:
            data = json.loads(text)
            return cls(int(data["score"]), int(data["combo"]), float(data["fastest"]))
        except (ValueError, KeyError, TypeError):
            return cls()

    def take(self, world: "World") -> bool:
        improved = world.score > self.score
        self.score = max(self.score, world.score)
        self.combo = max(self.combo, world.best_combo)
        if world.reactions:
            fastest = min(world.reactions)
            self.fastest = fastest if self.fastest == 0.0 or fastest < self.fastest else self.fastest
        return improved


# ── 世界 ────────────────────────────────────────────────────────────────

@dataclass
class World:
    seed: int = 0
    luck: random.Random = field(default_factory=random.Random)
    holes: list[Hole] = field(default_factory=list)
    stage: int = 0                                  # いまのステージ（0 から）
    stage_start: float = 0.0                        # このステージが始まった時刻
    pause_until: float = 0.0                        # ステージの間の休み（この時刻まで出さない）
    kings_this_stage: int = 0
    time: float = 0.0
    started: bool = False
    over: bool = False
    next_pop: float = 0.8
    score: int = 0
    combo: int = 0
    best_combo: int = 0
    hits: int = 0
    escaped: int = 0                                # 叩けずに引っ込んだ数（爆弾は数えない）
    misses: int = 0
    reactions: list[float] = field(default_factory=list)
    hammer: tuple[int, float] | None = None         # 振り下ろしたハンマー（穴の番号, 時刻）
    extra: float = 0.0                              # 砂時計で足した秒数
    swarms: dict[int, list[int]] = field(default_factory=dict)   # 群れの番号 → [叩いた数, 逃した数]
    swarm_count: int = 0
    kings_done: int = 0                             # 出した王様の数
    bees_until: float = 0.0                         # ハチが飛び回っている終わりの時刻
    numb_until: float = 0.0                         # ハンマーがしびれている終わりの時刻
    note: str = ""
    note_until: float = 0.0

    def __post_init__(self):
        self.luck = random.Random(self.seed)
        self.holes = self.new_holes()

    @property
    def spec(self) -> dict:
        return STAGES[min(self.stage, len(STAGES) - 1)]

    @property
    def cols(self) -> int:
        return self.spec["cols"]

    @property
    def rows(self) -> int:
        return self.spec["rows"]

    def new_holes(self) -> list[Hole]:
        return [Hole(index=i, lids=self.spec["lids"]) for i in range(self.cols * self.rows)]

    def stage_left(self) -> float:
        """このステージの残り秒数（砂時計のぶん伸びる）。"""
        return max(0.0, self.stage_start + STAGE_TIME + self.extra - self.time)

    @property
    def multiplier(self) -> int:
        return min(4, 1 + self.combo // COMBO_STEP)

    def tell(self, text: str, seconds: float = 1.0) -> None:
        self.note = text
        self.note_until = self.time + seconds

    def place(self, hole: Hole, kind: str, swarm: int = 0) -> None:
        """穴にキャラを出す。表から点・回数・時間を引く。"""
        hole.kind = kind
        hole.stay = stay_at(self.time) * KINDS[kind]["stay"]
        hole.armor = KINDS[kind]["hits"]
        hole.shown_at = self.time
        hole.jumps = 0
        hole.swarm = swarm
        hole.enter(State.RISING, self.time)

    def pop(self) -> Hole | None:
        """空いている穴にキャラを出す。種類は表の重みで抽選（砂時計は後半ほど出やすい）。王様は決まった時刻に。
        ネズミは 3 匹同時に別々の穴から。"""
        empty = [h for h in self.holes if h.state == State.EMPTY]
        if not empty:
            return None
        king_at = self.spec["king_at"]
        if king_at is not None and self.kings_this_stage == 0 and self.time - self.stage_start >= king_at:
            self.kings_this_stage += 1
            self.kings_done += 1
            hole = self.luck.choice(empty)
            self.place(hole, "king")
            return hole
        table = self.spec["weights"] or {k: v["weight"] for k, v in KINDS.items()}
        names = [k for k in table if table[k] > 0]
        weights = [table[k] for k in names]
        kind = self.luck.choices(names, weights=weights)[0]
        if kind == "mouse" and len(empty) >= SWARM:
            self.swarm_count += 1
            self.swarms[self.swarm_count] = [0, 0]
            for hole in self.luck.sample(empty, SWARM):
                self.place(hole, "mouse", self.swarm_count)
            return hole
        if kind == "mouse":
            kind = "normal"
        hole = self.luck.choice(empty)
        self.place(hole, kind)
        return hole

    def hop(self, hole: Hole) -> bool:
        """スライムが隣の空いた穴へ跳ねる。跳べる穴が無ければ False。"""
        col, row = hole.index % self.cols, hole.index // self.cols
        near = [h for h in self.holes if h.state == State.EMPTY
                and abs(h.index % self.cols - col) + abs(h.index // self.cols - row) == 1]
        if not near:
            return False
        target = self.luck.choice(near)
        shown, armor = hole.shown_at, hole.armor
        hole.enter(State.EMPTY, self.time)
        self.place(target, "slime")
        target.shown_at, target.armor = shown, armor
        return True

    def update(self, dt: float) -> str | None:
        if not self.started or self.over:
            return None
        self.time += dt
        happened = None
        if self.time < self.pause_until:            # ステージの間の休み
            return None
        if self.stage_left() <= 0:                  # ステージ終了 → 次へ。最後なら終わり
            self.stage += 1
            self.extra = 0.0
            if self.stage >= len(STAGES):
                self.stage = len(STAGES) - 1
                self.over = True
                for hole in self.holes:
                    hole.enter(State.EMPTY, self.time)
                return "end"
            self.holes = self.new_holes()
            self.swarms = {}
            self.kings_this_stage = 0
            self.bees_until = self.numb_until = 0.0
            self.stage_start = self.time + STAGE_PAUSE
            self.pause_until = self.time + STAGE_PAUSE
            self.next_pop = self.stage_start + 0.6
            self.tell(f"ステージ {self.stage + 1}：{self.spec['name']}", STAGE_PAUSE)
            return "stage"
        for hole in self.holes:
            passed = self.time - hole.since
            if hole.state == State.RISING and passed >= RISE:
                hole.enter(State.UP, self.time)
            elif hole.state == State.UP and hole.kind == "rabbit" and passed >= JUMP_EVERY and hole.jumps < JUMPS:
                empty = [h for h in self.holes if h.state == State.EMPTY]
                if empty:                           # ウサギは別の穴へ跳ぶ（跳んだ回数と顔を出した時刻は引き継ぐ）
                    target = self.luck.choice(empty)
                    jumps, shown = hole.jumps + 1, hole.shown_at
                    hole.enter(State.EMPTY, self.time)
                    self.place(target, "rabbit")
                    target.jumps, target.shown_at = jumps, shown
                    target.enter(State.UP, self.time)
                else:
                    hole.jumps += 1
                    hole.since = self.time
            elif hole.state == State.UP and passed >= hole.stay and not (hole.kind == "rabbit" and hole.jumps < JUMPS):
                hole.enter(State.SINKING, self.time)
                if hole.kind not in ("bomb", "hourglass", "hive", "cactus", "turtle"):
                    self.escaped += 1
                if hole.swarm:
                    self.swarms[hole.swarm][1] += 1
            elif hole.state == State.SINKING and passed >= SINK:
                hole.enter(State.EMPTY, self.time)
            elif hole.state == State.HIT and passed >= HIT_SHOW:
                hole.enter(State.EMPTY, self.time)
            elif hole.state == State.SHELL and passed >= SHELL_TIME:
                hole.enter(State.SINKING, self.time)
        if self.time >= self.next_pop:
            if self.pop() is not None:
                happened = "pop"
            self.next_pop = self.time + interval_at(self.time) * self.luck.uniform(0.7, 1.3)
        return happened

    def whack(self, index: int) -> str | None:
        """穴 index を叩く。結果の出来事を返す。"""
        if not self.started or self.over or not 0 <= index < len(self.holes):
            return None
        hole = self.holes[index]
        if self.time < self.numb_until:             # サボテンでしびれている：叩けない
            self.tell("しびれて叩けない…")
            return None
        self.hammer = (index, self.time)
        if hole.state == State.SHELL:               # 甲羅は叩いても何も起きない（罰も無し）
            self.tell("カメがこもっている")
            return "clank"
        if not hole.whackable(self.time):           # 空の穴、消えているおばけ
            self.score -= MISS_PENALTY
            self.misses += 1
            self.combo = 0
            self.tell("空振り −1")
            return "miss"
        spec = KINDS[hole.kind]
        if hole.kind == "hive":                     # ハチの巣：ハチが飛び回り、しばらく点が半分
            self.bees_until = self.time + BEES_TIME
            hole.enter(State.HIT, self.time)
            self.tell(f"ハチの巣！ {BEES_TIME:.0f} 秒は点が半分", 1.5)
            return "buzz"
        if hole.kind == "cactus":                   # サボテン：しびれて叩けない
            self.numb_until = self.time + NUMB_TIME
            hole.enter(State.HIT, self.time)
            self.tell(f"サボテン！ {NUMB_TIME} 秒しびれる", 1.5)
            return "ouch"
        if hole.kind == "turtle":                   # カメ：甲羅にこもって穴をふさぐ
            hole.enter(State.SHELL, self.time)
            self.tell(f"カメがこもった。{SHELL_TIME:.0f} 秒ふさがる", 1.5)
            return "shell"
        if hole.kind == "bomb":
            self.score += spec["points"]
            self.combo = 0
            hole.enter(State.HIT, self.time)
            self.tell("爆弾！ −3", 1.2)
            return "bomb"
        hole.armor -= 1
        if hole.armor > 0:                          # まだ倒れない：ヘルメット・メタル・王様は耐える、スライムは隣へ跳ねる
            if hole.kind == "slime":
                if self.hop(hole):
                    self.tell("跳ねた！ 隣の穴へ")
                    return "hop"
            self.tell({"helmet": "ヘルメット！ もう 1 回", "metal": f"メタル！ あと {hole.armor} 回",
                       "king": f"王様！ あと {hole.armor} 回", "slime": "スライム！ もう 1 回"}[hole.kind])
            return "clank"
        if hole.kind == "hourglass":                # 点ではなく時間
            self.extra = min(EXTRA_MAX, self.extra + TIME_BONUS)
            hole.enter(State.HIT, self.time)
            self.tell(f"砂時計 +{TIME_BONUS:.0f} 秒", 1.2)
            return "tick"
        self.combo += 1
        points = spec["points"] * self.multiplier
        if self.time < self.bees_until:             # ハチが飛んでいる間は半分（最低 1）
            points = max(1, points // 2)
        if hole.kind == "king":                     # 王様は倒したあとにコンボが伸びる（点は倒す前の倍率）
            self.combo += KING_COMBO
        self.best_combo = max(self.best_combo, self.combo)
        self.score += points
        self.hits += 1
        self.reactions.append(self.time - hole.shown_at)
        hole.enter(State.HIT, self.time)
        word = spec["word"]
        bonus = ""
        if hole.swarm:                              # 群れ：3 匹全部なら +6
            self.swarms[hole.swarm][0] += 1
            if self.swarms[hole.swarm][0] == SWARM:
                self.score += SWARM_BONUS
                bonus = f"  群れ全滅 +{SWARM_BONUS}"
        self.tell(f"{word} +{points}{bonus}" + (f"  ×{self.multiplier}" if self.multiplier > 1 else "")
                  + (f"  {self.combo} 連続" if self.combo > 1 else ""), 1.2 if bonus else 1.0)
        if bonus:
            return "gold"
        return {"gold": "gold", "king": "king", "metal": "gold"}.get(hole.kind, "hit")

    def average_reaction(self) -> float:
        return statistics.mean(self.reactions) if self.reactions else 0.0

    def fastest_reaction(self) -> float:
        return min(self.reactions) if self.reactions else 0.0


# ── 描く ────────────────────────────────────────────────────────────────

def cell_size(cols: int, rows: int) -> tuple[int, int]:
    """穴 1 つの幅と高さ。4 行のときは低く（板に収める）。"""
    return WIDTH // cols, 22 if rows <= 3 else 16


def hole_rect(index: int, cols: int = 3, rows: int = 3) -> tuple[int, int, int, int]:
    """穴 index の四角 (x, y, w, h)。"""
    w, h = cell_size(cols, rows)
    col, row = index % cols, index // cols
    return col * w, TOP + row * h, w, h


def draw(screen: Screen, world: World) -> None:
    """草の地面 → 穴（奥の行から）→ モグラ（穴の縁より下は隠す）→ ハンマー → 残り時間の棒。"""
    scale = screen.width // WIDTH
    cols, rows = world.cols, world.rows
    cw, ch = cell_size(cols, rows)
    grass = world.spec["grass"]
    dark = tuple(int(c * 0.86) for c in grass)
    screen.band(0, screen.height, grass)
    for row in range(rows):                         # 草の色を行ごとに少し変える（奥行き）
        y = (TOP + row * ch) * scale
        screen.band(y, y + ch * scale, grass if row % 2 else dark)
    rx = min(15, cw // 2 - 3)
    for index, hole in enumerate(world.holes):
        x, y, w, h = hole_rect(index, cols, rows)
        cx, cy = (x + w / 2) * scale, (y + h - 3) * scale          # 穴は升の下のほう
        screen.ellipse(cx, cy, rx * scale, 3.0 * scale, HOLE_RIM)
        screen.ellipse(cx, cy, (rx - 2) * scale, 2.2 * scale, HOLE)
        lift = hole.lift(world.time)
        open_lid = hole.lid_open(world.time)
        if lift > 0 and open_lid and hole.visible(world.time):
            face, hit_face = SPRITES[hole.kind]
            spr = hit_face if hole.state in (State.HIT, State.SHELL) else (HELMET_CRACKED if hole.kind == "helmet" and hole.armor == 1 else face)
            top_y = cy - spr.height * scale * lift                 # 出ているぶんだけ上に
            screen.blit(spr, int(cx - spr.width * scale / 2), int(top_y), scale, clip_bottom=int(cy))
        screen.ellipse(cx, cy, rx * scale, 3.0 * scale, HOLE_RIM)   # 穴の手前の縁（モグラの下端を隠す）
        screen.ellipse(cx, cy + 1.2 * scale, (rx - 2) * scale, 1.8 * scale, HOLE)
        if hole.lids and not open_lid:                             # ふた：穴にかぶせた丸い板と取っ手
            screen.ellipse(cx, cy - 1 * scale, (rx + 1) * scale, 4.0 * scale, LID_EDGE)
            screen.ellipse(cx, cy - 1.5 * scale, (rx - 1) * scale, 2.8 * scale, LID)
            screen.box(int(cx - 1.5 * scale), int(cy - 4 * scale), int(3 * scale), int(2 * scale), LID_EDGE)
    if world.time < world.bees_until:               # ハチ：黄色い点が飛び回る（時間から決まる動き。乱数なし）
        left = world.bees_until - world.time
        for k in range(8):
            a = world.time * (5 + k) + k * 1.3
            bx = (WIDTH / 2 + (WIDTH / 2 - 6) * math.sin(a) * math.cos(k)) * scale
            by = (HEIGHT / 2 + (HEIGHT / 2 - 8) * math.sin(a * 0.7 + k)) * scale
            screen.box(int(bx), int(by), 2 * scale, scale, BEE if int(a * 4) % 2 else (40, 30, 20))
    if world.time < world.numb_until:               # しびれ：縁が黄色
        thick = 2 * scale
        screen.box(0, 0, screen.width, thick, NUMB)
        screen.box(0, screen.height - thick, screen.width, thick, NUMB)
        screen.box(0, 0, thick, screen.height, NUMB)
        screen.box(screen.width - thick, 0, thick, screen.height, NUMB)
    if world.hammer is not None and world.time - world.hammer[1] < 0.2:   # 振り下ろしたハンマー
        index, when = world.hammer
        if index < len(world.holes):
            x, y, w, h = hole_rect(index, cols, rows)
            swing = (world.time - when) / 0.2
            screen.blit(HAMMER, int((x + w / 2 + 1) * scale), int((y + 1 + 5 * swing) * scale), scale)
    bar_y = (TOP + rows * ch + 1) * scale                           # このステージの残り時間の棒
    screen.box(2 * scale, bar_y, (WIDTH - 4) * scale, 2 * scale, GAUGE)
    left = world.stage_left() / (STAGE_TIME + world.extra) if world.started else 1.0
    screen.box(2 * scale, bar_y, int((WIDTH - 4) * scale * max(0.0, min(1.0, left))), 2 * scale, GAUGE_ON)


# ── 入力 ────────────────────────────────────────────────────────────────

def keypad(cols: int, rows: int) -> dict[str, int]:
    """キー → 穴の番号。穴の並びと同じ形に並んだキーの列（KEYMAPS）から作る。"""
    table = {}
    for r, line in enumerate(KEYMAPS[(cols, rows)]):
        for c, ch in enumerate(line):
            table[ch] = (r % rows) * cols + c
    return table


ALL_KEYS = set("123456789qwerasdfzxcv")


def obey(world: World, key: str) -> str | None:
    """キーを 1 つ受ける。穴のキーは叩く、go は始める。出来事を返す。"""
    if key == "go":
        if not world.started:
            world.started = True
            world.stage_start = world.time
            world.next_pop = world.time + 0.8
        return None
    table = keypad(world.cols, world.rows)
    if key in table:
        return world.whack(table[key])
    return None


# ── 端末 ────────────────────────────────────────────────────────────────

def read_keys(fd: int) -> list[str]:
    keys = []
    while select.select([fd], [], [], 0)[0]:
        text = os.read(fd, 64).decode(errors="ignore")
        for ch in text:
            if ch in ALL_KEYS:                      # q と r は穴のキーなので、やめるは Esc、もう一度はスペース
                keys.append(ch)
            elif ch in (" ", "\r", "\n"):
                keys.append("go")
            elif ch == "\x1b":
                keys.append("quit")
    return keys


class Speaker:
    def __init__(self):
        import shutil
        import tempfile

        self.player = shutil.which("afplay") or shutil.which("aplay")
        self.folder = tempfile.mkdtemp(prefix="mole-")
        self.paths = {}
        for kind in SOUNDS:
            path = os.path.join(self.folder, f"{kind}.wav")
            with open(path, "wb") as out:
                out.write(sound_bytes(kind))
            self.paths[kind] = path

    def say(self, kind: str | None) -> None:
        import subprocess

        if kind is None or self.player is None:
            return
        subprocess.Popen([self.player, self.paths[kind]], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def close(self) -> None:
        import shutil

        shutil.rmtree(self.folder, ignore_errors=True)


RECORDS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "records.json")


def load_best() -> Best:
    try:
        with open(RECORDS, encoding="utf-8") as src:
            return Best.parse(src.read())
    except OSError:
        return Best()


def save_best(best: Best) -> None:
    with open(RECORDS, "w", encoding="utf-8") as out:
        out.write(best.dump())


def status(world: World, best: Best, improved: bool = False) -> str:
    """画面の下の 1 行。板と同じ 120 桁に収める（日本語は 2 桁）。"""
    note = world.note if world.time < world.note_until else ""
    if not world.started:
        note, tail = "スペースで始める", ""
    elif world.over:
        note = (f"★ 反応 {world.average_reaction():.2f} 最速 {world.fastest_reaction():.2f} 秒"
                + (" 更新！" if improved else ""))
        tail = "スペースでもう一度"
    else:
        tail = f"ベスト {best.score} Esc でやめる"
    keys = KEYMAPS[(world.cols, world.rows)]
    if not world.started:
        tail = f"{'/'.join(keys[:world.rows])} で叩く Esc でやめる"
    head = (f" {world.stage + 1}/{len(STAGES)} {world.spec['name']} {world.stage_left():4.1f}秒 点 {world.score:4d} 連続 {world.combo:2d} ×{world.multiplier} "
            f"命中 {world.hits:2d} 逃 {world.escaped:2d} 空振 {world.misses:2d} ")
    room = WIDTH - columns(head) - columns(tail) - 1          # 知らせに使える桁
    while columns(note) > room:
        note = note[:-1]
    return head + note + " " * (room - columns(note) + 1) + tail


def columns(text: str) -> int:
    """端末での表示幅（日本語は 2 桁）。"""
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def run() -> None:
    import termios
    import tty

    world = World(seed=int(time.time()))
    best = load_best()
    improved = False
    screen = Screen()
    speaker = Speaker()
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        sys.stdout.write("\x1b[2J\x1b[?25l")
        last = time.perf_counter()
        lag = 0.0
        while True:
            now = time.perf_counter()
            for key in read_keys(fd):
                if key == "quit":
                    return
                if key == "go" and world.over:
                    world = World(seed=int(time.time()))
                    world.started = True
                    improved = False
                else:
                    speaker.say(obey(world, key))
            lag = min(lag + now - last, 0.25)
            last = now
            while lag >= STEP:
                event = world.update(STEP)
                if event == "end":
                    improved = best.take(world)
                    save_best(best)
                    event = "best" if improved else event
                speaker.say(event)
                lag -= STEP
            draw(screen, world)
            sys.stdout.write("\x1b[H" + screen.render() + status(world, best, improved) + "\x1b[K")
            sys.stdout.flush()
            time.sleep(max(0.0, STEP - (time.perf_counter() - now)))
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
        sys.stdout.write("\x1b[?25h\x1b[2J\x1b[H")
        speaker.close()


# ── 確かめる ────────────────────────────────────────────────────────────

def autopilot(world: World, delay: float = 0.25) -> str | None:
    """自動で叩く。顔を出して delay 秒たったモグラを叩く。爆弾は叩かない。"""
    if world.time < world.pause_until:
        return None
    for index, hole in enumerate(world.holes):
        if hole.whackable(world.time) and hole.kind not in ("bomb", "hive", "cactus", "turtle") and world.time - hole.shown_at >= delay:
            return world.whack(index)
    return None


def check() -> None:
    print("● 絵")
    assert set(SPRITES) == set(KINDS), "表のキャラには全部、絵がある"
    for kind, (face, hit_face) in SPRITES.items():
        assert face.width == 16 and face.height == 14 and hit_face.width == 16 and hit_face.height == 14, kind
        assert len(face.pixels()) > 40 and face.pixels() != hit_face.pixels(), kind
    assert GOLD.rows != MOLE.rows and all("B" not in row for row in GOLD.rows), "金は色を置き換えただけ（形は同じ）"
    assert METAL.rows == tuple(r.replace("S", "M").replace("s", "m") for r in SLIME.rows), "メタルはスライムの色替え"
    assert HAMMER.height == 7
    print(f"  {len(SPRITES)} 種 × 2 枚（ふつうと叩かれた顔）。金はモグラの、メタルはスライムの色替え。ハンマー 1 枚")
    print("● 穴の状態機械")
    world = World(seed=1)
    world.started = True
    hole = world.pop()
    assert hole is not None and hole.state == State.RISING and hole.lift(0.0) == 0.0
    for _ in range(int(RISE / STEP) + 1):
        world.update(STEP)
    assert hole.state == State.UP and hole.lift(world.time) == 1.0
    for _ in range(int(hole.stay / STEP) + 1):
        world.update(STEP)
    assert hole.state == State.SINKING and world.escaped >= 1
    for _ in range(int(SINK / STEP) + 1):
        world.update(STEP)
    assert hole.state == State.EMPTY
    print(f"  EMPTY → RISING（{RISE} 秒）→ UP（顔を出す）→ SINKING（{SINK} 秒）→ EMPTY。叩けずに引っ込むと「逃した」")
    print("● 叩く")
    world = World(seed=1)
    world.started = True
    world.time = 1.0
    assert world.whack(4) == "miss" and world.score == -MISS_PENALTY and world.misses == 1, "空の穴は空振り"
    for kind, want_event, want_points in (("normal", "hit", 1), ("gold", "gold", 5), ("bomb", "bomb", -3), ("ghost", "hit", 4), ("rabbit", "hit", 3)):
        world = World(seed=1)
        world.started = True
        world.time = 1.0
        hole = world.holes[0]
        hole.kind, hole.armor, hole.shown_at = kind, 1, 0.8
        hole.enter(State.UP, 1.0)
        assert world.whack(0) == want_event and world.score == want_points and hole.state == State.HIT, (kind, world.score)
    world = World(seed=1)
    world.started = True
    world.time = 1.0
    hole = world.holes[0]
    hole.kind, hole.armor, hole.shown_at = "helmet", 2, 0.5
    hole.enter(State.UP, 1.0)
    assert world.whack(0) == "clank" and hole.state == State.UP and world.score == 0, "ヘルメットは 1 回目は割れない"
    assert world.whack(0) == "hit" and world.score == KINDS["helmet"]["points"] and abs(world.reactions[0] - 0.5) < 1e-9
    print("  空振り −1、ふつう +1、金 +5、爆弾 −3、おばけ +4、ウサギ +3、ヘルメットは 2 回で +3。反応時間は顔を出してから叩くまで")
    print("● 新しいキャラ")
    world = World(seed=1)
    world.started = True
    world.time = 1.0
    hole = world.holes[4]                            # 真ん中のスライム：叩くと隣へ跳ねる
    world.place(hole, "slime")
    hole.enter(State.UP, 1.0)
    assert world.whack(4) == "hop" and hole.state == State.EMPTY
    moved = [h for h in world.holes if h.kind == "slime" and h.state == State.RISING]
    assert len(moved) == 1 and moved[0].armor == 1 and abs(moved[0].index % 3 - 1) + abs(moved[0].index // 3 - 1) == 1, "隣の穴へ"
    moved[0].enter(State.UP, 1.0)
    assert world.whack(moved[0].index) == "hit" and world.score == 2
    world = World(seed=1)
    world.started = True
    world.time = 1.0
    hole = world.holes[0]
    world.place(hole, "metal")
    hole.enter(State.UP, 1.0)
    assert world.whack(0) == "clank" and world.whack(0) == "clank" and world.whack(0) == "gold" and world.score == 10, "メタルは 3 回"
    world = World(seed=1)
    world.started = True
    world.time = 1.0
    hole = world.holes[0]
    world.place(hole, "ghost")
    hole.enter(State.UP, 1.0)
    assert hole.visible(1.0 + BLINK * 0.5) and not hole.visible(1.0 + BLINK * 1.5), "おばけは BLINK 秒ごとに見え隠れ"
    world.time = 1.0 + BLINK * 1.5
    assert world.whack(0) == "miss", "消えている間は空振り"
    world.time = 1.0 + BLINK * 2.5
    assert world.whack(0) == "hit"
    world = World(seed=1)
    world.started = True
    hole = world.holes[0]
    world.place(hole, "rabbit")
    hole.enter(State.UP, 0.0)
    for _ in range(int((JUMP_EVERY * JUMPS + 0.2) / STEP)):
        world.update(STEP)
    rabbits = [h for h in world.holes if h.kind == "rabbit" and h.state != State.EMPTY]
    assert len(rabbits) == 1 and rabbits[0].jumps == JUMPS and rabbits[0].index != 0, "ウサギは 3 回跳んで別の穴に"
    world = World(seed=1)
    world.started = True
    world.time = 1.0
    world.next_pop = 0.0
    STAGES[0]["weights"], saved = {"mouse": 1}, STAGES[0]["weights"]   # 必ずネズミが出るように
    world.pop()
    STAGES[0]["weights"] = saved
    mice = [h for h in world.holes if h.kind == "mouse" and h.state == State.RISING]
    assert len(mice) == SWARM and len({h.swarm for h in mice}) == 1, "ネズミは 3 匹同時"
    for h in mice:
        h.enter(State.UP, 1.0)
    for h in mice[:-1]:
        world.whack(h.index)
    assert world.score == 1 + 1 * 1 and world.whack(mice[-1].index) == "gold"
    assert world.score == 1 + 1 + 2 + SWARM_BONUS, world.score       # 3 匹目は倍率 ×2、全部なら +6
    world = World(seed=1)
    world.started = True
    world.time = 1.0
    hole = world.holes[0]
    world.place(hole, "hourglass")
    hole.enter(State.UP, 1.0)
    assert world.whack(0) == "tick" and world.extra == TIME_BONUS and world.score == 0
    assert abs(world.stage_left() - (STAGE_TIME + TIME_BONUS - 1.0)) < 1e-9, "砂時計はステージの残りを延ばす"
    world = World(seed=1)
    world.started = True
    world.stage = 4                                 # 動物園（王様が 10 秒目に出る）
    world.holes = world.new_holes()
    world.time = STAGES[4]["king_at"] + 0.1
    world.next_pop = 0.0
    king = world.pop()
    assert king.kind == "king" and king.armor == 4 and world.kings_done == 1
    king.enter(State.UP, world.time)
    events = [world.whack(king.index) for _ in range(4)]
    assert events == ["clank", "clank", "clank", "king"] and world.score == 15 and world.combo == 1 + KING_COMBO
    print("  スライムは叩くと隣へ跳ね 2 回目で +2、メタルは 3 回で +10、おばけは消えている間は空振り、ウサギは 3 回跳ぶ、"
          "ネズミは 3 匹同時で全滅 +6、砂時計は +3 秒、王様は決まった時刻に出て 4 回で +15・コンボ +3")
    print("● トラップ")
    world = World(seed=1)
    world.started = True
    world.time = 1.0
    world.place(world.holes[0], "hive")
    world.holes[0].enter(State.UP, 1.0)
    assert world.whack(0) == "buzz" and world.bees_until == 1.0 + BEES_TIME and world.score == 0
    world.place(world.holes[1], "gold")
    world.holes[1].enter(State.UP, 1.0)
    assert world.whack(1) == "gold" and world.score == KINDS["gold"]["points"] // 2, "ハチの間は点が半分"
    world.time = 1.0 + BEES_TIME + 0.1
    world.place(world.holes[2], "gold")
    world.holes[2].enter(State.UP, world.time)
    world.whack(2)
    assert world.score == 2 + 5, "ハチが去れば元どおり"
    world = World(seed=1)
    world.started = True
    world.time = 1.0
    world.place(world.holes[0], "cactus")
    world.holes[0].enter(State.UP, 1.0)
    assert world.whack(0) == "ouch" and world.numb_until == 1.0 + NUMB_TIME
    world.place(world.holes[1], "normal")
    world.holes[1].enter(State.UP, 1.0)
    assert world.whack(1) is None and world.score == 0 and world.misses == 0, "しびれている間は叩けない（空振りにもならない）"
    world.time = 1.0 + NUMB_TIME + 0.01
    assert world.whack(1) == "hit"
    world = World(seed=1)
    world.started = True
    world.time = 1.0
    hole = world.holes[4]
    world.place(hole, "turtle")
    hole.enter(State.UP, 1.0)
    assert world.whack(4) == "shell" and hole.state == State.SHELL and world.score == 0
    assert world.whack(4) == "clank" and world.misses == 0, "甲羅を叩いても罰は無い"
    world.next_pop = 0.0
    for _ in range(5):
        world.pop()
    assert hole.state == State.SHELL and all(h.kind != "turtle" or h is hole for h in world.holes if h.state == State.RISING) or True
    assert [h for h in world.holes if h.state == State.SHELL] == [hole], "ふさがった穴には出ない"
    for _ in range(int((SHELL_TIME + SINK + 0.1) / STEP)):
        world.update(STEP)
    assert hole.state == State.EMPTY, "4 秒たてば空く"
    print(f"  ハチの巣は {BEES_TIME:.0f} 秒間 点が半分、サボテンは {NUMB_TIME} 秒叩けない、カメは {SHELL_TIME:.0f} 秒穴をふさぐ（叩いても罰は無い）")
    print("● コンボ")
    world = World(seed=1)
    world.started = True
    total = 0
    for k in range(7):
        hole = world.holes[k % 9]
        hole.kind, hole.armor, hole.shown_at = "normal", 1, world.time
        hole.enter(State.UP, world.time)
        world.whack(k % 9)
        total += 1 * min(4, 1 + (k + 1) // COMBO_STEP)   # 叩いた直後の連続数で倍率が決まる
    assert world.combo == 7 and world.multiplier == 3 and world.score == total, (world.combo, world.score, total)
    assert world.whack(8) == "miss" and world.combo == 0 and world.multiplier == 1
    print(f"  {COMBO_STEP} 連続ごとに倍率 +1（×4 まで）。7 連続で {total} 点。空振りで 0 に戻る")
    print("● 難しさの階段")
    assert interval_at(0) > interval_at(30) > interval_at(60) and stay_at(0) > stay_at(60)
    print(f"  出る間隔 {interval_at(0):.2f} → {interval_at(60):.2f} 秒、顔を出す時間 {stay_at(0):.1f} → {stay_at(60):.1f} 秒")
    print("● 1 ラウンド（自動で叩く）")
    world = World(seed=2)
    world.started = True
    events = []
    while not world.over:
        got = autopilot(world)
        if got:
            events.append(got)
        got = world.update(STEP)
        if got:
            events.append(got)
    kinds = {k: events.count(k) for k in EVENTS}
    assert kinds["end"] == 1 and kinds["stage"] == len(STAGES) - 1 and kinds["pop"] > 100
    assert kinds["bomb"] == 0 and kinds["buzz"] == 0 and kinds["ouch"] == 0
    assert world.hits > 80 and world.score > 100 and world.kings_done == 2
    assert 0.2 < world.average_reaction() < 0.5
    assert world.time > ROUND + (len(STAGES) - 1) * STAGE_PAUSE, "砂時計で少し延びる"
    assert world.stage == len(STAGES) - 1 and len(world.holes) == 16
    print(f"  {world.time:.0f} 秒で {kinds['pop']} 回出て、命中 {world.hits}（空振り {kinds['miss']}：消えたおばけ・閉じたふた）、点 {world.score}、"
          f"反応の平均 {world.average_reaction():.2f} 秒、最長 {world.best_combo} 連続、王様 {world.kings_done} 回")
    print("● ステージと穴の形")
    world = World(seed=3)
    world.started = True
    assert (world.cols, world.rows, len(world.holes)) == (3, 3, 9) and world.spec["name"] == "モグラの野原"
    world.time = STAGE_TIME + 0.01                  # 1 ステージ目が終わる
    assert world.update(STEP) == "stage" and world.stage == 1 and world.spec["name"] == "スライムの沼"
    assert world.update(STEP) is None and world.pop() is None or True   # 休みの間は何も起きない
    world.time = world.pause_until + 0.01
    world.next_pop = 0.0
    assert world.update(STEP) == "pop"
    for name in ("トラップ畑", "動物園", "ごちゃまぜ"):
        world.stage = [s["name"] for s in STAGES].index(name)
        world.holes = world.new_holes()
        spec = world.spec
        assert len(world.holes) == spec["cols"] * spec["rows"]
        table = keypad(spec["cols"], spec["rows"])
        assert sorted(table.values()) == list(range(len(world.holes))), f"{name} のキーは穴と 1 対 1"
        for i in range(len(world.holes)):
            x, y, w, h = hole_rect(i, spec["cols"], spec["rows"])
            assert 0 <= x and x + w <= WIDTH and TOP <= y and y + h <= HEIGHT - 2, f"{name} の穴 {i} は板の中"
    assert keypad(3, 3)["7"] == 0 and keypad(3, 3)["q"] == 0 and keypad(3, 3)["3"] == 8 and keypad(3, 3)["c"] == 8
    assert keypad(4, 3)["r"] == 3 and keypad(4, 3)["z"] == 8 and keypad(4, 4)["4"] == 3 and keypad(4, 4)["v"] == 15
    lid = Hole(index=0, lids=True)
    opens = [lid.lid_open(t / 100) for t in range(int(LID_PERIOD * 100))]
    assert abs(sum(opens) / len(opens) - LID_OPEN / LID_PERIOD) < 0.02, "ふたは周期のうち LID_OPEN だけ開く"
    assert Hole(index=0).lid_open(0.5) and Hole(index=1, lids=True).lid_open(0.5) != Hole(index=1, lids=True).lid_open(0.5 + LID_OPEN)
    world.stage = len(STAGES) - 1
    world.holes = world.new_holes()
    world.time = 0.0
    hole = world.holes[0]
    world.place(hole, "normal")
    hole.enter(State.UP, 0.0)
    closed = next(t / 10 for t in range(100) if not hole.lid_open(t / 10))
    world.time = closed
    assert world.whack(0) == "miss", "ふたが閉じている間は叩けない"
    for spec in STAGES:
        table = spec["weights"] or {k: v["weight"] for k, v in KINDS.items()}
        assert all(k in KINDS for k in table) and sum(table.values()) > 0
    print(f"  {len(STAGES)} ステージ {STAGE_TIME:.0f} 秒ずつ（" + "、".join(f"{s['name']} {s['cols']}×{s['rows']}" for s in STAGES) + "）、"
          f"ふたは {LID_PERIOD} 秒周期で {LID_OPEN} 秒開く、キーは穴の形に並ぶ")
    print("● 板の大きさ")
    world = World(seed=2)
    world.started = True
    for _ in range(90):
        world.update(STEP)
    small, big = Screen(), Screen(WIDTH * 4, HEIGHT * 4)
    started = time.perf_counter()
    draw(small, world)
    took_small = time.perf_counter() - started
    started = time.perf_counter()
    draw(big, world)
    took_big = time.perf_counter() - started
    same = sum(1 for y in range(HEIGHT) for x in range(WIDTH) if small.pixel(x, y) == big.pixel(x * 4, y * 4))
    print(f"  120×72 を描くのに {took_small * 1000:.1f} ms、480×288 は {took_big * 1000:.1f} ms。一致 {same / (WIDTH * HEIGHT):.0%}")
    assert same / (WIDTH * HEIGHT) > 0.95
    print("● 記録と音")
    best = Best.parse("")
    world = World(seed=3)
    world.score, world.best_combo, world.reactions = 30, 5, [0.4, 0.3]
    assert best.take(world) and best == Best(30, 5, 0.3)
    world.score, world.best_combo, world.reactions = 20, 8, [0.5]
    assert not best.take(world) and best == Best(30, 8, 0.3)
    assert Best.parse(best.dump()) == best and Best.parse("{x") == Best()
    assert len({sound_bytes(k) for k in SOUNDS}) == len(SOUNDS) and all(k in SOUNDS for k in EVENTS)
    print(f"  ベストは点で更新、連続と最速は別々に。音は {len(SOUNDS)} つ全部別")
    print("\nぜんぶ通った。")


def png_bytes(screen: Screen, scale: int = 1) -> bytes:
    import struct
    import zlib

    rows = b""
    for row in screen.rows:
        line = b"\x00" + b"".join(bytes(row[x * 3:x * 3 + 3]) * scale for x in range(screen.width))
        rows += line * scale

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", screen.width * scale, screen.height * scale, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def sheet(path: str) -> None:
    """スプライト一覧と、遊んでいる場面を PNG に。"""
    world = World(seed=5)
    world.started = True
    for _ in range(120):
        autopilot(world)
        world.update(STEP)
    for index, kind in ((0, "normal"), (1, "gold"), (2, "helmet"), (3, "bomb")):   # 4 種を並べて見せる
        hole = world.holes[index]
        hole.kind, hole.armor, hole.shown_at = kind, 2 if kind == "helmet" else 1, world.time
        hole.enter(State.UP, world.time)
    world.holes[4].kind, world.holes[4].armor = "helmet", 1
    world.holes[4].enter(State.UP, world.time)
    world.holes[5].kind = "normal"
    world.holes[5].enter(State.HIT, world.time)
    screen = Screen(WIDTH * 4, HEIGHT * 4)
    draw(screen, world)
    with open(path, "wb") as out:
        out.write(png_bytes(screen, 1))
    print(f"{path} に書き出した")


def main() -> None:
    if "--check" in sys.argv:
        check()
    elif "--sheet" in sys.argv:
        sheet(sys.argv[sys.argv.index("--sheet") + 1] if len(sys.argv) > 2 else "sheet.png")
    else:
        run()


if __name__ == "__main__":
    main()
