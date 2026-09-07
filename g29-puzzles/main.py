"""アイテムと仕掛け — 完成: 拾って、使って、開ける。仕掛けはクロージャ・partial・__call__ で、動詞は自作デコレータで登録する。"""

import argparse
import difflib
import shlex
import textwrap
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from functools import partial
from typing import NamedTuple

WIDTH = 30                                  # 文章を折り返す幅（文字数。日本語は 1 文字が全角）
START = "entrance"
GOAL = "outside"

RESULT_TEXT = {
    "clear": "外に出た。夜明けの空気が冷たい。",
    "quit": "やめました。",
}

# 動詞の表。@command(...) が Game のメソッドを登録するときに埋める
ALIASES: dict[str, str] = {}                # 言い換え → 動詞
HANDLERS: dict[str, tuple[str, str, str]] = {}   # 動詞 → (メソッド名, 言い換えの一覧, 説明)
STOP_WORDS = {"at", "the", "a", "an", "to", "on", "in", "を", "に", "へ", "の", "で"}     # 読み飛ばす飾りの語

ITEM_TEXT = {                               # 持ち物を調べたときの文
    "鉄の棒": "温室の支柱だったもの。てこに使えそうだ。",
    "鍵": "鍋の底から剥がした小さな鍵。歯が 3 つ。",
}


def command(*names: str, doc: str = ""):
    """動詞を登録するデコレータ。@command("take", "get", "拾う") のように言い換えも一緒に。"""
    def register(method):
        for name in names:
            ALIASES[name] = names[0]
        HANDLERS[names[0]] = (method.__name__, " / ".join(names[1:]), doc)
        return method                                       # メソッド自体は変えない
    return register


def help_text() -> str:
    return "\n".join(f"  {verb:<6} {doc:<22} {aliases}" for verb, (_, aliases, doc) in HANDLERS.items())


class Command(NamedTuple):
    """分解したコマンド。動詞と、その残り。"""

    verb: str
    args: tuple[str, ...] = ()

    @property
    def target(self) -> str:
        """引数をつなげた 1 語（「鉄の棒」を「鉄の」「棒」と分けられても戻せるように）。"""
        return "".join(self.args)


def parse(text: str) -> Command | None:
    """文を Command に。方角だけなら go に、動詞が分からなければ verb="unknown" に。空なら None。"""
    try:
        words = [w.lower() for w in shlex.split(text)]
    except ValueError:                                      # 引用符が閉じていない
        words = text.lower().split()
    words = [w[:-1] if len(w) > 1 and w[-1] in "へにを" else w for w in words]   # 「北へ」「扉を」の助詞を落とす（「の」は「鉄の棒」に入るので残す）
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
    items: list[str] = field(default_factory=list)          # 落ちているもの（拾える）
    blocked: dict[Direction, str] = field(default_factory=dict)   # 塞がっている方角 → その理由
    actions: dict[tuple[str, str], Callable[["Game"], str]] = field(default_factory=dict)   # (動詞, 対象) → 仕掛け

    def __str__(self) -> str:
        """プレイヤーに見せる文章。名前、折り返した説明、目につくもの、出口。"""
        text = "".join(line.strip() for line in textwrap.dedent(self.description).splitlines())   # 元の改行と字下げは捨てる
        body = wrap_japanese(text)
        things = f"\n目につくもの: {'、'.join(self.things)}" if self.things else ""
        items = f"\n落ちているもの: {'、'.join(self.items)}" if self.items else ""
        exits = "、".join(d.label for d in self.exits) or "なし"
        return f"【{self.name}】\n{body}{things}{items}\n出口: {exits}"

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


def lock(rooms: dict[str, Room], a: str, direction: Direction, reason: str) -> None:
    """a の direction を塞ぐ。出口を外して、理由を覚えておく。"""
    rooms[a].blocked[direction] = reason
    del rooms[a].exits[direction]


def unlock(game: "Game", direction: Direction, key: str, message: str) -> str:
    """鍵で塞ぎを解く共通の処理。部屋ごとの違い（方角・鍵・文）は partial で埋める。"""
    room = game.room
    if direction not in room.blocked:
        return "もう開いている。"
    if key not in game.inventory:
        return f"{room.blocked[direction]}"
    target = next(r.id for r in game.rooms.values() if (r.x, r.y) == step_from(room, direction))
    room.exits[direction] = target
    game.rooms[target].exits[direction.opposite] = room.id
    del room.blocked[direction]
    game.solved += 1
    return message


def step_from(room: Room, direction: Direction) -> tuple[int, int]:
    """room から direction へ 1 つ進んだ座標。"""
    dx, dy = {"north": (0, 1), "south": (0, -1), "east": (1, 0), "west": (-1, 0), "up": (0, 1), "down": (0, -1)}[direction]
    return room.x + dx, room.y + dy


def make_window() -> Callable[["Game"], str]:
    """屋根裏の窓。押した回数を閉じ込めたクロージャ。3 回押すか、鉄の棒があれば 1 回で外れる。"""
    pushes = 0

    def push(game: "Game") -> str:
        nonlocal pushes                                     # 外側の pushes を書き換える
        room = game.room
        if Direction.EAST not in room.blocked:
            return "窓はもう外れている。"
        pushes += 1
        if "鉄の棒" in game.inventory:
            reason = "鉄の棒をこじ入れると、枠ごと外れた。"
        elif pushes < 3:
            return f"押した。少し動いた（{pushes} 回目）。"
        else:
            reason = "3 度目でやっと枠が外れた。"
        room.exits[Direction.EAST] = "outside"
        del room.blocked[Direction.EAST]
        game.solved += 1
        return f"{reason} 東に、屋根の上へ出られる。"

    return push


class Reveal:
    """調べると 1 回だけ物が出てくる仕掛け。関数のように呼べるオブジェクト。"""

    def __init__(self, item: str, text: str, again: str):
        self.item = item
        self.text = text
        self.again = again
        self.done = False

    def __call__(self, game: "Game") -> str:
        if self.done:
            return self.again
        self.done = True
        game.room.items.append(self.item)
        return self.text


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
             things={"竈": "灰は冷え切っている。", "鍋": "空だ。底に何か固まっている。"},
             actions={("look", "鍋"): Reveal("鍵", "鍋の底の塊を剥がすと、小さな鍵が出てきた。", "鍋はもう空だ。")}),
        Room("hall", "広間", """
            シャンデリアの下、大きな階段が二階へ伸びている。
            床の埃に、自分以外の足跡はない。""", 1, 1,
             things={"シャンデリア": "蝋燭は 1 本も残っていない。", "階段": "手すりが一部欠けている。北へ上がれる。"}),
        Room("greenhouse", "温室", """
            ガラス越しに月が見える。
            枯れた植物の間に、細い通路が続く。""", 2, 1,
             things={"植物": "どれも枯れている。鉢の土だけがなぜか湿っている。"},
             items=["鉄の棒"]),
        Room("pantry", "貯蔵庫", """
            棚に並んだ瓶。ラベルはどれも読めない。
            ここは行き止まりのようだ。""", 0, 2,
             things={"瓶": "中身は黒い液体。開ける気にはなれない。"}),
        Room("stairs", "階段の踊り場", """
            二階への階段はここで折れ曲がる。
            上には小さな扉、横には手すりの向こうにバルコニー。""", 1, 2,
             things={"扉": "天井の扉。梯子がかかっているが、扉には鍵穴がある。"}),
        Room("balcony", "バルコニー", """
            夜風が強い。庭の向こうに門が見えるが、飛び降りるには高すぎる。""", 2, 2,
             things={"門": "鉄の門。閉まっているが、庭に降りられれば越えられそうだ。"}),
        Room("attic", "屋根裏", """
            梁の間を、風が抜けていく。
            東の壁の窓が、外れかけている。""", 1, 3,
             things={"窓": "枠ごと外れかけている。押せば外へ出られそうだ。"}),
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

    # 仕掛け。塞いでおいて、対応する動詞で開ける
    lock(rooms, "stairs", Direction.UP, "天井の扉には鍵がかかっている。")
    open_door = partial(unlock, direction=Direction.UP, key="鍵", message="鍵が回った。扉が開き、梯子を上がれる。")
    rooms["stairs"].actions[("open", "扉")] = open_door
    rooms["stairs"].actions[("use", "鍵")] = open_door
    lock(rooms, "attic", Direction.EAST, "窓は枠が歪んで開かない。押せば動くかもしれない。")
    window = make_window()
    for key in [("push", "窓"), ("open", "窓"), ("use", "鉄の棒")]:
        rooms["attic"].actions[key] = window
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
        self.inventory: list[str] = []
        self.steps = 0
        self.solved = 0                                     # 解いた仕掛けの数
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
            return self.room.blocked.get(direction, f"{direction.label}には行けない。")
        self.here = target
        self.visited.add(target)
        self.steps += 1
        if target == GOAL:
            self.result = "clear"
            return f"{self.room}\n\n{RESULT_TEXT['clear']}  {self.steps} 歩"
        return str(self.room)

    def trigger(self, verb: str, target: str) -> str | None:
        """この部屋に (動詞, 対象) の仕掛けがあれば動かす。無ければ None。"""
        action = self.room.actions.get((verb, target))
        return action(self) if action else None

    @command("go", "walk", "move", "run", "行く", "進む", "移動", doc="歩く")
    def do_go(self, *args: str) -> str:
        if not args:
            return "どちらへ？（n s e w u d）"
        direction = Direction.parse(args[0])
        return self.go(direction) if direction else f"「{args[0]}」は方角じゃない。"

    @command("look", "l", "examine", "x", "inspect", "見る", "調べる", "観察", doc="見回す・調べる")
    def do_look(self, *args: str) -> str:
        if not args:
            return str(self.room)
        name = "".join(args)
        if (reply := self.trigger("look", name)) is not None:
            return reply
        if name in self.room.things:
            return self.room.things[name]
        if name in self.inventory or name in self.room.items:
            return ITEM_TEXT.get(name, f"{name}。特に変わったところはない。")
        near = suggest(name, list(self.room.things) + self.room.items + self.inventory)
        return f"「{name}」は見当たらない。もしかして「{near}」？" if near else f"ここに「{name}」は見当たらない。"

    @command("take", "get", "pick", "拾う", "取る", doc="拾う")
    def do_take(self, *args: str) -> str:
        name = "".join(args)
        if not name:
            return "何を？"
        if name not in self.room.items:
            return f"ここに「{name}」は落ちていない。"
        self.room.items.remove(name)
        self.inventory.append(name)
        return f"{name}を拾った。"

    @command("drop", "put", "置く", "捨てる", doc="置く")
    def do_drop(self, *args: str) -> str:
        name = "".join(args)
        if name not in self.inventory:
            return f"「{name}」は持っていない。"
        self.inventory.remove(name)
        self.room.items.append(name)
        return f"{name}を置いた。"

    @command("inventory", "i", "inv", "持ち物", "所持品", doc="持ち物")
    def do_inventory(self, *args: str) -> str:
        return f"持ち物: {'、'.join(self.inventory)}" if self.inventory else "何も持っていない。"

    @command("use", "使う", doc="持ち物を使う")
    def do_use(self, *args: str) -> str:
        name = "".join(args)
        if name not in self.inventory:
            return f"「{name}」は持っていない。"
        return self.trigger("use", name) or f"ここで{name}を使っても何も起きない。"

    @command("open", "unlock", "開ける", doc="開ける")
    def do_open(self, *args: str) -> str:
        name = "".join(args)
        return self.trigger("open", name) or f"「{name}」は開けられない。"

    @command("push", "press", "押す", doc="押す")
    def do_push(self, *args: str) -> str:
        name = "".join(args)
        return self.trigger("push", name) or f"「{name}」を押しても何も起きない。"

    @command("map", "m", "地図", doc="地図")
    def do_map(self, *args: str) -> str:
        return draw_map(self.rooms, self.visited, self.here)

    @command("help", "h", "?", "commands", "ヘルプ", doc="この一覧")
    def do_help(self, *args: str) -> str:
        return f"使える言葉:\n{help_text()}\n  方角   n s e w u d / north … / 北 南 東 西 上 下"

    @command("quit", "q", "exit", "bye", "やめる", doc="やめる")
    def do_quit(self, *args: str) -> str:
        self.result = "quit"
        return RESULT_TEXT["quit"]

    def look(self) -> str:
        return str(self.room)

    def map(self) -> str:
        return draw_map(self.rooms, self.visited, self.here)

    def execute(self, command: Command) -> str:
        """1 つのコマンドを実行して、返事の文を返す。動詞の表からメソッドを引く。"""
        if command.verb == "unknown":
            near = suggest(command.args[0], ALIASES)
            hint = f"もしかして「{near}」？" if near else "help で使える言葉が出る。"
            return f"「{command.args[0]}」は分からない。{hint}"
        method_name, _, _ = HANDLERS[command.verb]
        return getattr(self, method_name)(*command.args)

    def render(self) -> str:
        bag = "、".join(self.inventory) or "なし"
        return f"{self.room}\n\n{self.steps} 歩  行った部屋 {len(self.visited)}/{len(self.rooms)}  仕掛け {self.solved}/2  持ち物: {bag}\n"


def main():
    global WIDTH                                            # --width で折り返し幅を変えるため
    parser = argparse.ArgumentParser(description="冒険（部屋と移動）")
    parser.add_argument("--width", type=int, default=WIDTH, help="文章を折り返す幅")
    args = parser.parse_args()
    WIDTH = args.width

    game = Game()
    print("take 鍵 / use 鍵 / open 扉 / push 窓 / inventory。look で調べ、方角で歩く。help で使える言葉、q でやめる。\n")
    print(game.look())

    while game.result is None:
        command = parse(input("\n> "))
        if command is None:
            continue
        print(game.execute(command))

    print(f"\n{game.steps} 歩  行った部屋 {len(game.visited)}/{len(game.rooms)}  解いた仕掛け {game.solved}/2")


if __name__ == "__main__":
    main()
