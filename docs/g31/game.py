"""セーブと自動テスト（ブラウザ版）

CLI 版（g31-save/main.py）と世界・セーブの中身・指紋の取り方はまったく同じ。
@command デコレータ、Direction / Command / Room / Reveal / ScenarioError / SaveError / Scenario、fingerprint() 〜 make_world() の関数、そして class Game を、
ステップの目印コメント（# ←）を外しただけで 1 文字も変えずに持ってきている。

持ってこなかったのは Game.render() と、zip を読み書きする Game.save() / load()、攻略ファイルの関数と main() だけ。
セーブは save_data() の辞書を JSON にして localStorage へ、つづきからは from_save() で。指紋の検証も同じ関数。
"""

import difflib
import hashlib
import json
import shlex
import textwrap
import tomllib
from collections.abc import Callable
from pathlib import Path
from dataclasses import dataclass, field
from enum import StrEnum
from functools import partial
from typing import NamedTuple

from js import window
from pyscript import document, when

SCENARIO_DIR = Path("scenarios")            # config の files で置いた TOML
DEFAULT_SCENARIO = "mansion"
SAVE_VERSION = 1
SAVE_KEY = "g31-save"                                       # localStorage のキー


# --- ここから class Game まで、CLI 版（g31-save/main.py）からそのまま ---


WIDTH = 30                                  # 文章を折り返す幅（文字数。日本語は 1 文字が全角）


RESULT_TEXT = {
    "quit": "やめました。",
}


ALIASES: dict[str, str] = {}                # 言い換え → 動詞
HANDLERS: dict[str, tuple[str, str, str]] = {}   # 動詞 → (メソッド名, 言い換えの一覧, 説明)
STOP_WORDS = {"at", "the", "a", "an", "to", "on", "in", "を", "に", "へ", "の", "で"}     # 読み飛ばす飾りの語


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
    """文を Command に。方角だけなら go に、動詞が分からなければ verb="unknown" に。空なら None。

    >>> parse("look at the 扉")
    Command(verb='look', args=('扉',))
    >>> parse("北へ")
    Command(verb='go', args=('北',))
    >>> parse("拾う 鉄の棒").target
    '鉄の棒'
    >>> parse("lok")
    Command(verb='unknown', args=('lok',))
    >>> parse("   ") is None
    True
    """
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
        """n / north / 北 のどれでも。方角でなければ None。

        >>> Direction.parse("n")
        <Direction.NORTH: 'north'>
        >>> Direction.parse("上") is Direction.UP
        True
        >>> Direction.parse("xyz") is None
        True
        """
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
    sealed: dict[Direction, str] = field(default_factory=dict)    # 塞がっている方角 → 開いたときの行き先
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
    """WIDTH 文字で折り返す。行頭に来た句読点は前の行の末尾へ（禁則処理）。

    >>> print(wrap_japanese("あ" * 29 + "。" + "い" * 3))
    あああああああああああああああああああああああああああああ。
    いいい
    """
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
    """a の direction を塞ぐ。出口を外して、理由と行き先を覚えておく。"""
    rooms[a].blocked[direction] = reason
    rooms[a].sealed[direction] = rooms[a].exits.pop(direction)


def open_way(game: "Game", direction: Direction) -> None:
    """塞ぎを解いて、覚えておいた行き先へ出口を戻す。"""
    room = game.room
    room.exits[direction] = room.sealed.pop(direction)
    del room.blocked[direction]
    game.solved += 1


def unlock(game: "Game", direction: Direction, key: str, message: str) -> str:
    """鍵で塞ぎを解く共通の処理。部屋ごとの違い（方角・鍵・文）は partial で埋める。"""
    room = game.room
    if direction not in room.blocked:
        return "もう開いている。"
    if key not in game.inventory:
        return f"{room.blocked[direction]}"
    open_way(game, direction)
    return message


def make_pusher(direction: Direction, times: int, tool: str, texts: dict) -> Callable[["Game"], str]:
    """押して開ける仕掛け。押した回数を閉じ込めたクロージャ。times 回押すか、tool があれば 1 回で開く。"""
    pushes = 0

    def push(game: "Game") -> str:
        nonlocal pushes                                     # 外側の pushes を書き換える
        if direction not in game.room.blocked:
            return texts["already"]
        pushes += 1
        if tool in game.inventory:
            reason = texts["with_tool"]
        elif pushes < times:
            return texts["partial"].format(n=pushes)
        else:
            reason = texts["done"]
        open_way(game, direction)
        return f"{reason} {texts['after']}"

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
        game.solved += 1
        return self.text


class ScenarioError(Exception):
    """シナリオのファイルがおかしい。どこが悪いかを文で持つ。"""


class SaveError(Exception):
    """セーブが読めない、または書き換えられている。"""


def fingerprint(text: str) -> str:
    """文字列の指紋（SHA-256 の 16 進）。1 文字でも違えばまったく別の値になる。

    >>> fingerprint("abc")[:12]
    'ba7816bf8f01'
    >>> fingerprint("abd") == fingerprint("abc")
    False
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Scenario:
    """TOML の中身。scenario.title のように属性で読める。"""

    def __init__(self, data: dict, path: Path | None = None, source: str = ""):
        self._data = data
        self.path = path
        self.source = source                                # 元の TOML の文字列。指紋はこれから取る

    def __getattr__(self, name: str):
        """普通の属性に無い名前が来たときだけ呼ばれる。TOML のキーを引く。"""
        try:
            return self._data[name]
        except KeyError:
            raise AttributeError(f"シナリオに {name!r} という項目は無い") from None

    def get(self, name: str, default=None):
        return self._data.get(name, default)


def load_scenario(path: Path) -> Scenario:
    """TOML を読んで検証する。読めない・足りないときは ScenarioError。"""
    try:
        source = path.read_text(encoding="utf-8")
        data = tomllib.loads(source)
    except OSError as error:
        raise ScenarioError(f"{path} が開けない: {error}") from error
    except tomllib.TOMLDecodeError as error:
        raise ScenarioError(f"{path} は TOML として読めない: {error}") from error
    validate(data, path)
    return Scenario(data, path, source)


def validate(data: dict, path: Path) -> None:
    """足りないキー、無い部屋への通路、知らない仕掛けを、遊ぶ前に見つける。"""
    for key in ("title", "start", "goal", "rooms", "exits"):
        if key not in data:
            raise ScenarioError(f"{path}: {key} が無い")
    ids = set()
    for room in data["rooms"]:
        for key in ("id", "name", "description", "x", "y"):
            if key not in room:
                raise ScenarioError(f"{path}: 部屋 {room.get('id', '?')} に {key} が無い")
        ids.add(room["id"])
    for key in ("start", "goal"):
        if data[key] not in ids:
            raise ScenarioError(f"{path}: {key} の {data[key]!r} という部屋は無い")
    for exit_ in data["exits"]:
        for end in ("from", "to"):
            if exit_.get(end) not in ids:
                raise ScenarioError(f"{path}: 通路 {exit_} の {end} が部屋にない")
        if Direction.parse(str(exit_.get("direction"))) is None:
            raise ScenarioError(f"{path}: 通路 {exit_} の direction が方角でない")
    for puzzle in data.get("puzzles", []):
        if puzzle.get("room") not in ids:
            raise ScenarioError(f"{path}: 仕掛け {puzzle} の room が部屋にない")
        if puzzle.get("type") not in BUILDERS:
            raise ScenarioError(f"{path}: 仕掛けの type {puzzle.get('type')!r} は知らない（{' / '.join(BUILDERS)}）")


def build_lock(rooms: dict[str, Room], p: dict) -> None:
    direction = Direction(p["direction"])
    lock(rooms, p["room"], direction, p["reason"])
    action = partial(unlock, direction=direction, key=p["key"], message=p["message"])
    for verb, target in p["verbs"]:
        rooms[p["room"]].actions[(verb, target)] = action


def build_reveal(rooms: dict[str, Room], p: dict) -> None:
    rooms[p["room"]].actions[("look", p["thing"])] = Reveal(p["item"], p["text"], p["again"])


def build_push(rooms: dict[str, Room], p: dict) -> None:
    direction = Direction(p["direction"])
    lock(rooms, p["room"], direction, p["reason"])
    action = make_pusher(direction, p["times"], p["tool"], p)
    for verb, target in p["verbs"]:
        rooms[p["room"]].actions[(verb, target)] = action


BUILDERS = {"lock": build_lock, "reveal": build_reveal, "push": build_push}   # type → 作り方


def make_world(scenario: Scenario) -> dict[str, Room]:
    """シナリオのデータから部屋・通路・仕掛けを組み立てる。"""
    rooms = {r["id"]: Room(r["id"], r["name"], r["description"], r["x"], r["y"],
                           things=dict(r.get("things", {})), items=list(r.get("items", [])))
             for r in scenario.rooms}
    for exit_ in scenario.exits:
        connect(rooms, exit_["from"], Direction.parse(exit_["direction"]), exit_["to"])
    for puzzle in scenario.get("puzzles", []):
        BUILDERS[puzzle["type"]](rooms, puzzle)
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

    def __init__(self, scenario: Scenario):
        self.scenario = scenario
        self.rooms = make_world(scenario)
        self.here = scenario.start
        self.visited = {scenario.start}
        self.inventory: list[str] = []
        self.item_text: dict[str, str] = scenario.get("items", {})
        self.puzzles = len(scenario.get("puzzles", []))
        self.steps = 0
        self.solved = 0                                     # 解いた仕掛けの数
        self.result: str | None = None
        self.record: list[str] = []                         # 実行したコマンドの記録。セーブはこれ

    @property
    def room(self) -> Room:
        return self.rooms[self.here]

    def go(self, direction: Direction) -> str:
        """歩く。行けなければその旨。着いた部屋の説明を返す。"""
        if self.result is not None:
            return self.ending if self.result == "clear" else RESULT_TEXT[self.result]
        target = self.room.exits.get(direction)
        if target is None:
            return self.room.blocked.get(direction, f"{direction.label}には行けない。")
        self.here = target
        self.visited.add(target)
        self.steps += 1
        if target == self.scenario.goal:
            self.result = "clear"
            return f"{self.room}\n\n{self.ending}  {self.steps} 歩"
        return str(self.room)

    @property
    def ending(self) -> str:
        return self.scenario.get("ending", "出口に着いた。")

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
            return self.item_text.get(name, f"{name}。特に変わったところはない。")
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
        """1 つのコマンドを実行して、返事の文を返す。動詞の表からメソッドを引く。世界を変える動詞は記録する。"""
        if command.verb == "unknown":
            near = suggest(command.args[0], ALIASES)
            hint = f"もしかして「{near}」？" if near else "help で使える言葉が出る。"
            return f"「{command.args[0]}」は分からない。{hint}"
        method_name, _, _ = HANDLERS[command.verb]
        if command.verb not in ("map", "help", "quit", "inventory"):
            self.record.append(" ".join((command.verb,) + command.args))
        return getattr(self, method_name)(*command.args)

    def save_data(self) -> dict:
        """セーブの中身。シナリオの名前と指紋、コマンドの記録。状態そのものは入れない（読む＝指し直す）。"""
        return {
            "version": SAVE_VERSION,
            "scenario": self.scenario.path.stem if self.scenario.path else "?",
            "scenario_sha256": fingerprint(self.scenario.source),
            "record": self.record,
            "record_sha256": fingerprint("\n".join(self.record)),
        }

    @classmethod
    def from_save(cls, data: dict, scenario: Scenario) -> "Game":
        """セーブから Game を作り直す。指紋が合わなければ SaveError。"""
        if data.get("version") != SAVE_VERSION:
            raise SaveError(f"セーブの形式が違う（version {data.get('version')}）")
        if fingerprint("\n".join(data["record"])) != data["record_sha256"]:
            raise SaveError("コマンドの記録が書き換えられている")
        if fingerprint(scenario.source) != data["scenario_sha256"]:
            raise SaveError(f"シナリオ {scenario.title} がセーブしたときと変わっている")
        game = cls(scenario)
        for text in data["record"]:
            game.execute(parse(text))
        return game


# --- ここから下はブラウザ版だけ。CLI 版の input() と print() と main() にあたる ---

log = document.querySelector("#log")
map_el = document.querySelector("#map")
turn_label = document.querySelector("#turn")
moves_label = document.querySelector("#moves")
rooms_label = document.querySelector("#rooms")
solved_label = document.querySelector("#solved")
bag_label = document.querySelector("#bag")
total_label = document.querySelector("#total")
message = document.querySelector("#message")
command = document.querySelector("#cmd")
send_button = document.querySelector("#send")
start_button = document.querySelector("#start-btn")
scenario_select = document.querySelector("#scenario")
save_button = document.querySelector("#save-btn")
resume_button = document.querySelector("#resume-btn")
compass = document.querySelectorAll(".compass button")

scenarios = {}                                              # 名前 → Scenario。glob で集める
for path in sorted(SCENARIO_DIR.glob("*.toml")):
    try:
        scenarios[path.stem] = load_scenario(path)
    except ScenarioError as error:
        print(f"{path}: {error}")                           # コンソールへ
for name, scenario in scenarios.items():
    option = document.createElement("option")
    option.value = name
    option.textContent = f"{scenario.title}（部屋 {len(scenario.rooms)}、仕掛け {len(scenario.get('puzzles', []))}）"
    scenario_select.appendChild(option)
scenario_select.value = DEFAULT_SCENARIO

game = Game(scenarios[DEFAULT_SCENARIO])


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
    solved_label.textContent = str(game.solved)
    bag_label.textContent = "持ち物: " + ("、".join(game.inventory) or "なし")
    map_el.textContent = game.map()
    for button in compass:
        direction = button.getAttribute("data-dir")
        if direction:
            button.disabled = game.result is not None or Direction(direction) not in game.room.exits
        else:
            button.disabled = game.result is not None
    command.disabled = send_button.disabled = game.result is not None
    save_button.disabled = game.result is not None or not game.record
    resume_button.disabled = window.localStorage.getItem(SAVE_KEY) is None
    if game.result is not None:
        text = game.ending if game.result == "clear" else RESULT_TEXT[game.result]
        message.textContent = f"{text}　{game.steps} 歩"


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
    say(reply, "warn" if command.verb == "unknown" or "見当たらない" in reply or "持っていない" in reply else "")
    draw()


def start():
    global game
    scenario = scenarios[scenario_select.value]
    game = Game(scenario)                                   # 選んだシナリオから世界を組み立て直す
    log.replaceChildren()
    message.textContent = ""
    say(f"【{scenario.title}】 {scenario.get('intro', '')}")
    say("look / take / use / open / push / inventory / map。help で使える言葉。")
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


@when("change", "#scenario")
def on_scenario(event):
    start()


@when("click", "#save-btn")
def on_save(event):
    """CLI 版の Game.save() にあたる。zip ではなく localStorage に JSON で。"""
    window.localStorage.setItem(SAVE_KEY, json.dumps(game.save_data(), ensure_ascii=False))
    say(f"セーブした（コマンド {len(game.record)} 個、シナリオ {game.scenario.title}）。", "cmd")
    draw()


@when("click", "#resume-btn")
def on_resume(event):
    """CLI 版の Game.load() にあたる。記録を指し直して同じところへ。"""
    global game
    text = window.localStorage.getItem(SAVE_KEY)
    if text is None:
        return
    data = json.loads(text)
    try:
        game = Game.from_save(data, scenarios[data["scenario"]])
    except (SaveError, KeyError) as error:
        say(f"つづきからにできない: {error}", "warn")
        return
    scenario_select.value = data["scenario"]
    log.replaceChildren()
    message.textContent = ""
    say(f"つづきから（コマンド {len(game.record)} 個を指し直した）。", "cmd")
    say(game.look())
    draw()


# Pyodide の読み込みが終わってから実行される＝ここが準備完了の合図
document.querySelector("#loading").hidden = True
start_button.disabled = False
scenario_select.disabled = False
start()
