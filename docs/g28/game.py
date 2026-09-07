"""コマンド解析（ブラウザ版）

CLI 版（g28-parser/main.py）と部屋・言葉の解釈はまったく同じ。
定数と同義語の表、Direction / Command / Room、parse() / suggest() / wrap_japanese() / connect() / make_world() / draw_map()、そして class Game を、
ステップの目印コメント（# ←）を外しただけで 1 文字も変えずに持ってきている。

持ってこなかったのは Game.render() と main() だけ。
入口の <input> の文字列を parse() に渡し、Game.execute() の返事をログに足す。CLI 版の main() のループ 1 回ぶんと同じ。
"""

import difflib
import shlex
import textwrap
from dataclasses import dataclass, field
from enum import StrEnum
from typing import NamedTuple

from pyscript import document, when


# --- ここから class Game まで、CLI 版（g28-parser/main.py）からそのまま ---


WIDTH = 30                                  # 文章を折り返す幅（文字数。日本語は 1 文字が全角）
START = "entrance"
GOAL = "outside"


RESULT_TEXT = {
    "clear": "外に出た。夜明けの空気が冷たい。",
    "quit": "やめました。",
}


VERBS = {
    "go": {"walk", "move", "run", "行く", "進む", "移動"},
    "look": {"l", "examine", "x", "inspect", "見る", "調べる", "観察"},
    "map": {"m", "地図"},
    "help": {"h", "?", "commands", "ヘルプ", "助けて"},
    "quit": {"q", "exit", "bye", "やめる", "終わり"},
}


ALIASES = {alias: verb for verb, names in VERBS.items() for alias in names | {verb}}   # 逆引き: 言い換え → 動詞
STOP_WORDS = {"at", "the", "a", "an", "to", "on", "in", "を", "に", "へ", "の"}          # 読み飛ばす飾りの語
HELP_TEXT = "\n".join(f"  {verb:<5} {' / '.join(sorted(names))}" for verb, names in VERBS.items())


class Command(NamedTuple):
    """分解したコマンド。動詞と、その残り。"""

    verb: str
    args: tuple[str, ...] = ()


def parse(text: str) -> Command | None:
    """文を Command に。方角だけなら go に、動詞が分からなければ verb="unknown" に。空なら None。"""
    try:
        words = [w.lower() for w in shlex.split(text)]
    except ValueError:                                      # 引用符が閉じていない
        words = text.lower().split()
    words = [w[:-1] if len(w) > 1 and w[-1] in "へにをの" else w for w in words]   # 「北へ」「扉を」の助詞を落とす
    words = [w for w in words if w not in STOP_WORDS]
    if not words:
        return None
    if Direction.parse(words[0]) is not None:               # "n" や "北" だけで歩ける
        return Command("go", (words[0],))
    verb = ALIASES.get(words[0])
    if verb is None:
        return Command("unknown", tuple(words))
    return Command(verb, tuple(words[1:]))


def suggest(word: str, choices) -> str | None:
    """似た言葉を 1 つ。無ければ None。"""
    found = difflib.get_close_matches(word, list(choices), n=1, cutoff=0.5)
    return found[0] if found else None


class Direction(StrEnum):
    """方角。値は文字列そのものなので、表示にも辞書のキーにもそのまま使える。"""

    NORTH = "north"
    SOUTH = "south"
    EAST = "east"
    WEST = "west"
    UP = "up"
    DOWN = "down"

    @property
    def label(self) -> str:
        return {"north": "北", "south": "南", "east": "東", "west": "西", "up": "上", "down": "下"}[self]

    @property
    def opposite(self) -> "Direction":
        pairs = {"north": "south", "south": "north", "east": "west", "west": "east", "up": "down", "down": "up"}
        return Direction(pairs[self])

    @classmethod
    def parse(cls, text: str) -> "Direction | None":
        """n / north / 北 のどれでも。方角でなければ None。"""
        aliases = {"n": "north", "s": "south", "e": "east", "w": "west", "u": "up", "d": "down",
                   "北": "north", "南": "south", "東": "east", "西": "west", "上": "up", "下": "down"}
        text = aliases.get(text.lower(), text.lower())
        try:
            return cls(text)
        except ValueError:
            return None


@dataclass
class Room:
    """部屋。名前と説明と、方角ごとの行き先（部屋の id）。x, y は地図用。"""

    id: str
    name: str
    description: str
    x: int
    y: int
    exits: dict[Direction, str] = field(default_factory=dict)
    things: dict[str, str] = field(default_factory=dict)    # 目につくもの。名前 → 調べたときの文

    def __str__(self) -> str:
        """プレイヤーに見せる文章。名前、折り返した説明、目につくもの、出口。"""
        text = "".join(line.strip() for line in textwrap.dedent(self.description).splitlines())   # 元の改行と字下げは捨てる
        body = wrap_japanese(text)
        things = f"\n目につくもの: {'、'.join(self.things)}" if self.things else ""
        exits = "、".join(d.label for d in self.exits) or "なし"
        return f"【{self.name}】\n{body}{things}\n出口: {exits}"

    def __repr__(self) -> str:
        """デバッグ用。中身が分かる短い形。"""
        return f"Room({self.id!r}, exits={[str(d) for d in self.exits]})"


def wrap_japanese(text: str) -> str:
    """WIDTH 文字で折り返す。行頭に来た句読点は前の行の末尾へ（禁則処理）。"""
    lines = textwrap.fill(text, width=WIDTH).splitlines()   # 日本語は空白が無いので、文字数でそのまま折れる
    for i in range(1, len(lines)):
        while lines[i] and lines[i][0] in "。、」）":
            lines[i - 1] += lines[i][0]
            lines[i] = lines[i][1:]
    return "\n".join(line for line in lines if line)


def connect(rooms: dict[str, Room], a: str, direction: Direction, b: str) -> None:
    """a から direction へ行くと b。b からは逆向きで a に戻れる。"""
    rooms[a].exits[direction] = b
    rooms[b].exits[direction.opposite] = a


def make_world() -> dict[str, Room]:
    """洋館。3×3 の部屋と屋根裏、そして外。"""
    rooms = {room.id: room for room in [
        Room("entrance", "玄関", """
            重い扉は背後で閉まってしまった。
            天井の高いホールに、埃っぽい絨毯が続いている。""", 1, 0,
             things={"扉": "押しても引いても動かない。外から閂がかかっているようだ。",
                     "絨毯": "赤かったのだろう。踏むと埃が舞う。"}),
        Room("dining", "食堂", """
            長いテーブルに、燭台が一つ。
            蝋はとうに燃え尽きている。""", 0, 0,
             things={"燭台": "銀の燭台。蝋の跡に、指で書いたような「屋根裏」の文字。",
                     "テーブル": "椅子は 12 脚。どれも埃をかぶっている。"}),
        Room("study", "書斎", """
            壁一面の本棚。机の上の地図には、この館の見取り図が描かれている。""", 2, 0,
             things={"地図": "見取り図。屋根裏の東の壁に、小さく「窓」と書き込みがある。",
                     "本棚": "背表紙の文字はかすれて読めない。1 冊だけ、逆さに差してある。"}),
        Room("kitchen", "台所", """
            冷えた竈と、鍋がいくつか。
            奥の扉の向こうから、かすかに風の音がする。""", 0, 1,
             things={"竈": "灰は冷え切っている。", "鍋": "空だ。底に何か固まっている。"}),
        Room("hall", "広間", """
            シャンデリアの下、大きな階段が二階へ伸びている。
            床の埃に、自分以外の足跡はない。""", 1, 1,
             things={"シャンデリア": "蝋燭は 1 本も残っていない。", "階段": "手すりが一部欠けている。北へ上がれる。"}),
        Room("greenhouse", "温室", """
            ガラス越しに月が見える。
            枯れた植物の間に、細い通路が続く。""", 2, 1,
             things={"植物": "どれも枯れている。鉢の土だけがなぜか湿っている。"}),
        Room("pantry", "貯蔵庫", """
            棚に並んだ瓶。ラベルはどれも読めない。
            ここは行き止まりのようだ。""", 0, 2,
             things={"瓶": "中身は黒い液体。開ける気にはなれない。"}),
        Room("stairs", "階段の踊り場", """
            二階への階段はここで折れ曲がる。
            上には小さな扉、横には手すりの向こうにバルコニー。""", 1, 2,
             things={"扉": "天井の扉。梯子がかかっていて、上へ行ける。"}),
        Room("balcony", "バルコニー", """
            夜風が強い。庭の向こうに門が見えるが、飛び降りるには高すぎる。""", 2, 2,
             things={"門": "鉄の門。閉まっているが、庭に降りられれば越えられそうだ。"}),
        Room("attic", "屋根裏", """
            梁の間を、風が抜けていく。
            東の壁の窓が、外れかけている。""", 1, 3,
             things={"窓": "枠ごと外れかけている。押せば外へ出られる。"}),
        Room("outside", "外", """
            屋根伝いに降りて、庭に立った。""", 2, 3),
    ]}
    connect(rooms, "entrance", Direction.NORTH, "hall")
    connect(rooms, "entrance", Direction.EAST, "study")
    connect(rooms, "entrance", Direction.WEST, "dining")
    connect(rooms, "dining", Direction.NORTH, "kitchen")
    connect(rooms, "study", Direction.NORTH, "greenhouse")
    connect(rooms, "kitchen", Direction.EAST, "hall")
    connect(rooms, "kitchen", Direction.NORTH, "pantry")
    connect(rooms, "hall", Direction.EAST, "greenhouse")
    connect(rooms, "hall", Direction.NORTH, "stairs")
    connect(rooms, "greenhouse", Direction.NORTH, "balcony")
    connect(rooms, "stairs", Direction.EAST, "balcony")
    connect(rooms, "stairs", Direction.UP, "attic")
    connect(rooms, "attic", Direction.EAST, "outside")
    return rooms


def draw_map(rooms: dict[str, Room], visited: set[str], here: str) -> str:
    """行った部屋だけの地図。自分のいる部屋は [ ] で囲む。北が上。"""
    cell = 8
    xs = [room.x for room in rooms.values()]
    ys = [room.y for room in rooms.values()]
    lines = []
    for y in range(max(ys), min(ys) - 1, -1):
        row = ""
        for x in range(min(xs), max(xs) + 1):
            room = next((r for r in rooms.values() if (r.x, r.y) == (x, y) and r.id in visited), None)
            if room is None:
                row += " " * cell
            elif room.id == here:
                row += f"[{room.name}]".center(cell)
            else:
                row += room.name.center(cell)
        lines.append(row.rstrip())
    return "\n".join(lines)


class Game:
    """冒険 1 回ぶん。今いる部屋、行った部屋、歩数、結果。表示と入力は持たない。"""

    def __init__(self):
        self.rooms = make_world()
        self.here = START
        self.visited = {START}
        self.steps = 0
        self.result: str | None = None

    @property
    def room(self) -> Room:
        return self.rooms[self.here]

    def go(self, direction: Direction) -> str:
        """歩く。行けなければその旨。着いた部屋の説明を返す。"""
        if self.result is not None:
            return RESULT_TEXT[self.result]
        target = self.room.exits.get(direction)
        if target is None:
            return f"{direction.label}には行けない。"
        self.here = target
        self.visited.add(target)
        self.steps += 1
        if target == GOAL:
            self.result = "clear"
            return f"{self.room}\n\n{RESULT_TEXT['clear']}  {self.steps} 歩"
        return str(self.room)

    def look(self) -> str:
        return str(self.room)

    def examine(self, name: str) -> str:
        """目につくものを調べる。無ければ似た名前を提案する。"""
        if name in self.room.things:
            return self.room.things[name]
        near = suggest(name, self.room.things)
        if near is not None:
            return f"「{name}」は見当たらない。もしかして「{near}」？"
        return f"ここに「{name}」は見当たらない。"

    def map(self) -> str:
        return draw_map(self.rooms, self.visited, self.here)

    def execute(self, command: Command) -> str:
        """1 つのコマンドを実行して、返事の文を返す。"""
        match command:
            case Command("go", ()):
                return "どちらへ？（n s e w u d）"
            case Command("go", (word, *_)):
                direction = Direction.parse(word)
                return self.go(direction) if direction else f"「{word}」は方角じゃない。"
            case Command("look", ()):
                return self.look()
            case Command("look", (name, *_)):
                return self.examine(name)
            case Command("map", _):
                return self.map()
            case Command("help", _):
                return f"使える言葉:\n{HELP_TEXT}\n  方角  n s e w u d / north … / 北 南 東 西 上 下"
            case Command("quit", _):
                self.result = "quit"
                return RESULT_TEXT["quit"]
            case Command("unknown", (word, *_)):
                near = suggest(word, ALIASES)
                hint = f"もしかして「{near}」？" if near else "help で使える言葉が出る。"
                return f"「{word}」は分からない。{hint}"
        return "……"


# --- ここから下はブラウザ版だけ。CLI 版の input() と print() と main() にあたる ---

log = document.querySelector("#log")
map_el = document.querySelector("#map")
turn_label = document.querySelector("#turn")
moves_label = document.querySelector("#moves")
rooms_label = document.querySelector("#rooms")
total_label = document.querySelector("#total")
message = document.querySelector("#message")
command = document.querySelector("#cmd")
send_button = document.querySelector("#send")
start_button = document.querySelector("#start-btn")
compass = document.querySelectorAll(".compass button")

game = Game()


def say(text: str, kind: str = "") -> None:
    """ログに 1 段落足して、いちばん下までスクロールする。CLI 版の print()。"""
    block = document.createElement("div")
    if kind:
        block.className = kind
    block.textContent = text
    log.appendChild(block)
    log.scrollTop = log.scrollHeight


def draw():
    """CLI 版の render() にあたる。状態の行と、地図と、ボタンの有効・無効。"""
    turn_label.textContent = game.room.name
    moves_label.textContent = str(game.steps)
    rooms_label.textContent = str(len(game.visited))
    total_label.textContent = str(len(game.rooms))
    map_el.textContent = game.map()
    for button in compass:
        direction = button.getAttribute("data-dir")
        if direction:
            button.disabled = game.result is not None or Direction(direction) not in game.room.exits
        else:
            button.disabled = game.result is not None
    command.disabled = send_button.disabled = game.result is not None
    if game.result is not None:
        message.textContent = f"{RESULT_TEXT[game.result]}　{game.steps} 歩"


def run(text: str) -> None:
    """CLI 版の main() のループ 1 回ぶん。"""
    text = text.strip()
    if not text or game.result is not None:
        return
    say(f"> {text}", "cmd")
    command = parse(text)
    if command is None:
        return
    reply = game.execute(command)
    say(reply, "warn" if command.verb == "unknown" or "見当たらない" in reply else "")
    draw()


def start():
    global game
    game = Game()
    log.replaceChildren()
    message.textContent = ""
    say("「look at the 燭台」「examine 地図」「go north」「北へ」のように打つ。help で使える言葉。")
    say(game.look())
    draw()
    command.focus()


@when("click", ".compass button")
def on_compass(event):
    run(event.target.getAttribute("data-dir") or event.target.getAttribute("data-cmd"))


@when("submit", "#form")
def on_submit(event):
    event.preventDefault()
    run(command.value)
    command.value = ""


@when("click", "#start-btn")
def on_start(event):
    start()


# Pyodide の読み込みが終わってから実行される＝ここが準備完了の合図
document.querySelector("#loading").hidden = True
start_button.disabled = False
start()
