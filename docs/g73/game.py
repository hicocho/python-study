"""耳コピ1（音を作る）ブラウザ版

CLI 版（g73-ear-piano/main.py）と中身はまったく同じ。音の作り方（pitch_hz・tone・
wav_bytes・melody）も、絵の描き方（Screen・roll・board・draw）も、遊びの判断（Game・obey）も
1 文字も変えずに持ってきている。

違うのは入口と出口だけ。
  入口: 端末はキー 1 文字、ブラウザは鍵盤のクリックとキー。どちらも obey() に入る
  出口: 絵は端末が ▀ の並び、ブラウザは canvas。音は端末が afplay、ブラウザは Audio。
        ただし **鳴らしている wav の bytes は同じもの**。wav_bytes() が作った bytes を、
        端末はファイルへ、ブラウザは data URI へ渡しているだけ。

持ってこなかったのは Screen.render() と、それを使う run() / show() / Speaker と検査だけ。
"""

import base64
import io
import math
import wave
from array import array
from dataclasses import dataclass, field

from pyscript import document, when, window
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


def pitch_hz(note: int) -> float:
    """半音の番号を周波数にする。ド = 0、ラ = 9 がちょうど 440 Hz。

    半音 1 つで 2 の 12 乗根倍。12 個かければ 2 倍＝ちょうど 1 オクターブ上になる。
    """
    return 440.0 * 2.0 ** ((note - 9) / 12)


def tone(note: int, seconds: float) -> array:
    """1 つの音を、16 bit の標本の列にする。

    array("h") は「短い整数がぎっしり並んだ入れ物」。list より小さく、
    tobytes() でそのまま wav の中身になる。
    """
    count = int(RATE * seconds)
    step = 2 * math.pi * pitch_hz(note) / RATE
    samples = array("h")
    for i in range(count):
        samples.append(int(32767 * VOLUME * shape(i, count) * math.sin(step * i)))
    return samples


def shape(i: int, count: int) -> float:
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


def melody(notes: list[int], seconds: float = NOTE) -> array:
    """音を並べて 1 本の列にする。つないだ先も array のまま。"""
    line = array("h")
    for note in notes:
        line.extend(tone(note, seconds))
    return line


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


SONGS = [                                           # ← 3 曲 → 47 曲に
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
    call: str = ""                                  # GOOD / ALMOST / BAD
    stars: list[int] = field(default_factory=list)  # ← 曲ごとの星
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
        self.message = "スペースでお題を聞く"

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
            self.message = f"★ {self.score()}{how}　スペースで次の曲へ"
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


def obey(game: Game, key: str) -> tuple[list[int], float] | None:
    """キーを 1 つ受け取ってゲームを進め、鳴らすものがあれば (音, 長さ) で返す。

    端末もブラウザもここを通る。鳴らし方は違っても、判断はここ 1 か所。
    """
    if key == "space":
        if game.cleared:
            return None if not game.advance() else (game.answer, NOTE)
        game.heard += 1
        game.message = game.left()
        return game.answer, NOTE
    if key == "enter":
        if game.cleared:
            game.advance()
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
    return [note], TAP


# --- ここから下はブラウザ版だけ。CLI 版の run() / Screen.render() / Speaker にあたる ---

canvas = document.querySelector("#screen")
ctx = canvas.getContext("2d")
ctx.imageSmoothingEnabled = False
image = ctx.createImageData(WIDTH, HEIGHT)
title_label = document.querySelector("#title")
count_label = document.querySelector("#count")
heard_label = document.querySelector("#heard")
tries_label = document.querySelector("#tries")
stars_label = document.querySelector("#stars")
message = document.querySelector("#message")
verdict = document.querySelector("#verdict")
who_label = document.querySelector("#who")


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
    """ブラウザで音を出す係。CLI 版の Speaker と役目は同じ。

    wav_bytes() が返した **同じ bytes** を data URI にして Audio に渡すだけ。
    作るのに少し時間がかかるので、一度作った音は取っておく。
    """

    def __init__(self):
        self.made: dict[tuple, object] = {}

    def say(self, notes: list[int], seconds: float) -> None:
        want = (tuple(notes), seconds)
        if want not in self.made:
            data = wav_bytes(melody(notes, seconds))
            uri = "data:audio/wav;base64," + base64.b64encode(data).decode()
            self.made[want] = window.Audio.new(uri)
        sound = self.made[want]
        sound.pause()
        sound.currentTime = 0
        sound.play()


screen = CanvasScreen()
game = Game()
speaker = Speaker()


def refresh() -> None:
    """CLI 版の show() にあたる。draw() を canvas へ、様子を HTML へ。"""
    draw(screen, game)
    screen.flush()
    title_label.textContent = game.song.name        # 曲名は最初から出す（曲そのものを覚えるため）
    title_label.className = "song done" if game.cleared else "song"
    who_label.textContent = game.song.who
    count_label.textContent = f"{game.index + 1} / {len(SONGS)}"
    heard_label.textContent = f"{game.heard} 回"
    tries_label.textContent = f"{game.tries} 回"
    stars_label.textContent = "".join("★" * n + "・" for n in game.stars[-14:]) or "—"
    verdict.textContent = game.call
    verdict.hidden = not game.call
    verdict.className = "verdict " + {"GOOD！": "good", "ALMOST！": "almost"}.get(game.call, "bad")
    message.textContent = game.message


def act(key: str) -> None:
    """キー 1 つぶん進める。判断は CLI と同じ obey()。"""
    want = obey(game, key)
    if want is not None:
        speaker.say(*want)
    refresh()


@when("click", "#screen")
def tap(event) -> None:
    """canvas の上を押したら、その場所の鍵を鳴らす。"""
    box = canvas.getBoundingClientRect()
    x = int((event.clientX - box.left) / box.width * WIDTH)
    y = int((event.clientY - box.top) / box.height * HEIGHT)
    note = key_at(x, y)
    if note is not None:
        act(WHITE_CHARS[WHITE.index(note)] if note in WHITE else BLACK_CHARS[BLACK.index(note)])


@when("click", ".pad button")                        # 2 つ目以降の pad も拾う
def button(event) -> None:
    act(event.target.getAttribute("data-key"))


@when("keydown", "body")
def typed(event) -> None:
    name = {" ": "space", "Enter": "enter", "Backspace": "back"}.get(event.key, event.key.lower())
    if name in CHARS or name in ("space", "enter", "back"):
        event.preventDefault()
        act(name)


document.querySelector("#loading").hidden = True
refresh()
