"""ブラックジャック（ブラウザ版）

CLI 版（g11-blackjack/main.py）とルールはまったく同じ。
定数 4 つと Suit / RANKS / FACES / RESULT_TEXT / RECORD_LABEL、
Card / Hand の 2 クラス、make_deck() / cards_text() / dealer_play() / judge() / payout()、
そして class Game を、ステップの目印コメント（# ←）を外しただけで 1 文字も変えずに持ってきている。

持ってこなかったのは hidden_text() と ask_bet() と ask_action() と main()、それに Game.render() だけ。
つまり違うのは入口と出口で、入口は h / s / d の文字入力ではなくボタン、
出口は [♠A] の文字列ではなく <div> のカード。
チップの置き場も、CLI 版は 1 回きりだが、ここでは localStorage に持ち越す。
"""

import random
from collections import Counter
from dataclasses import dataclass
from enum import Enum

from js import localStorage
from pyscript import document, when


# --- ここから class Game まで、CLI 版（g11-blackjack/main.py）からそのまま ---


TARGET = 21
DEALER_STOP = 17
START_CHIPS = 100
RESHUFFLE_AT = 15


class Suit(Enum):
    """トランプのマーク。値は表示に使う記号。"""

    SPADE = "♠"
    HEART = "♥"
    DIAMOND = "♦"
    CLUB = "♣"


RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
FACES = {"J", "Q", "K"}


RESULT_TEXT = {
    "blackjack": "ブラックジャック！ あなたの勝ち",
    "win": "あなたの勝ち",
    "push": "引き分け",
    "lose": "ディーラーの勝ち",
    "bust": "バースト… ディーラーの勝ち",
}


RECORD_LABEL = {
    "blackjack": "BJ",
    "win": "勝ち",
    "push": "引き分け",
    "lose": "負け",
    "bust": "バースト",
}


@dataclass(frozen=True)
class Card:
    """1 枚のカード。作ったあとは変えられない。"""

    suit: Suit
    rank: str

    def __str__(self) -> str:
        return f"{self.suit.value}{self.rank}"

    @property
    def point(self) -> int:
        """このカードの点数。絵札は 10、A はいったん 1 として数える。"""
        if self.rank in FACES:
            return 10
        if self.rank == "A":
            return 1
        return int(self.rank)


class Hand:
    """手札。点数の数え方を知っている。"""

    def __init__(self):
        self.cards: list[Card] = []

    def add(self, card: Card) -> None:
        self.cards.append(card)

    @property
    def hard_total(self) -> int:
        """A を全部 1 として数えた合計。"""
        return sum(card.point for card in self.cards)

    @property
    def is_soft(self) -> bool:
        """A を 11 として数えている状態なら True。"""
        has_ace = any(card.rank == "A" for card in self.cards)
        return has_ace and self.hard_total + 10 <= TARGET

    @property
    def total(self) -> int:
        """合計点。A を 11 にしても 21 を超えないなら、1 枚だけ 11 として数える。"""
        return self.hard_total + 10 if self.is_soft else self.hard_total

    @property
    def is_bust(self) -> bool:
        return self.total > TARGET

    @property
    def is_blackjack(self) -> bool:
        """最初の 2 枚で 21。ただの 21 より強い。"""
        return len(self.cards) == 2 and self.total == TARGET

    def __str__(self) -> str:
        soft = " (soft)" if self.is_soft else ""
        return f"{cards_text(self.cards)}  = {self.total}{soft}"


def make_deck() -> list[Card]:
    """52 枚のデッキを作って返す。順番はまだそろったまま。"""
    return [Card(suit, rank) for suit in Suit for rank in RANKS]


def cards_text(cards: list[Card]) -> str:
    """カードの並びを [♠A] [♥10] のような文字列にして返す。"""
    return " ".join(f"[{card}]" for card in cards)


def dealer_play(hand: Hand, draw) -> None:
    """ディーラーは 17 になるまで引く。それ以上は止まる。draw は 1 枚引く関数。"""
    while hand.total < DEALER_STOP:
        hand.add(draw())


def judge(player: Hand, dealer: Hand) -> str:
    """勝敗を "blackjack" / "win" / "push" / "lose" / "bust" のどれかで返す。"""
    if player.is_bust:
        return "bust"
    if player.is_blackjack:
        return "push" if dealer.is_blackjack else "blackjack"
    if dealer.is_blackjack:
        return "lose"
    if dealer.is_bust:
        return "win"
    if player.total > dealer.total:
        return "win"
    if player.total < dealer.total:
        return "lose"
    return "push"


def payout(result: str, bet: int) -> int:
    """結果に応じて手元に戻るチップを返す。賭け金も含めた額。"""
    match result:
        case "blackjack":
            return bet + bet * 3 // 2                       # 1.5 倍の配当
        case "win":
            return bet * 2
        case "push":
            return bet
        case "lose" | "bust":
            return 0
    raise ValueError(f"知らない結果: {result}")


class Game:
    """1 卓ぶんの状態。山・手札・賭け金・チップ・ラウンドの段階をまとめて持つ。"""

    def __init__(self, chips: int = START_CHIPS):
        self.chips = chips
        self.deck: list[Card] = []
        self.player = Hand()
        self.dealer = Hand()
        self.bet = 0
        self.phase = "bet"                                  # "bet" → "player" → "done"
        self.result: str | None = None
        self.record = Counter()                             # 結果ごとの回数

    def draw(self) -> Card:
        """山から 1 枚引く。山が尽きていたら新しい山を切る。"""
        if not self.deck:
            self.deck = make_deck()
            random.shuffle(self.deck)
        return self.deck.pop()

    def start_round(self, bet: int) -> bool:
        """賭けてカードを配る。賭けられない額や、段階が違えば False。"""
        if self.phase != "bet" or not 0 < bet <= self.chips:
            return False

        if len(self.deck) < RESHUFFLE_AT:                   # 残りが少なければ切り直す
            self.deck = []

        self.bet = bet
        self.chips -= bet                                   # 賭け金は先に卓へ出す
        self.player = Hand()
        self.dealer = Hand()
        self.result = None
        for _ in range(2):                                  # 交互に 2 枚ずつ
            self.player.add(self.draw())
            self.dealer.add(self.draw())

        self.phase = "player"
        if self.player.is_blackjack or self.dealer.is_blackjack:
            self.settle()                                   # どちらかが最初から 21 なら即決着

        return True

    @property
    def can_double(self) -> bool:
        """ダブルダウンは最初の 2 枚のとき、同額をもう一度出せるなら。"""
        return self.phase == "player" and len(self.player.cards) == 2 and self.chips >= self.bet

    def hit(self) -> bool:
        if self.phase != "player":
            return False
        self.player.add(self.draw())
        if self.player.is_bust:
            self.settle()
        return True

    def stand(self) -> bool:
        if self.phase != "player":
            return False
        self.settle()
        return True

    def double(self) -> bool:
        """賭け金を倍にして 1 枚だけ引き、そのまま勝負。"""
        if not self.can_double:
            return False
        self.chips -= self.bet
        self.bet *= 2
        self.player.add(self.draw())
        self.settle()
        return True

    def settle(self) -> None:
        """ディーラーが引き、勝敗を決めて、チップを精算する。"""
        if not self.player.is_bust and not self.player.is_blackjack:
            dealer_play(self.dealer, self.draw)             # 引く必要があるときだけ
        self.result = judge(self.player, self.dealer)
        self.chips += payout(self.result, self.bet)
        self.record[self.result] += 1
        self.phase = "done"

    def next_round(self) -> None:
        if self.phase == "done":
            self.phase = "bet"


# --- ここから下はブラウザ版だけ。CLI 版の ask_bet() / ask_action() / main() にあたる ---

CHIPS_KEY = "python-study-g11-chips"       # CLI 版には無い。チップを次回に持ち越す
BETS = [5, 10, 25, 50]
RED_SUITS = {Suit.HEART, Suit.DIAMOND}

dealer_box = document.querySelector("#dealer")
player_box = document.querySelector("#player")
dealer_total = document.querySelector("#dealer-total")
player_total = document.querySelector("#player-total")
chips_label = document.querySelector("#chips")
bet_label = document.querySelector("#bet")
deck_label = document.querySelector("#deck")
message = document.querySelector("#message")
record_label = document.querySelector("#record")
bet_buttons = document.querySelectorAll(".bet")
deal_button = document.querySelector("#deal-btn")
hit_button = document.querySelector("#hit-btn")
stand_button = document.querySelector("#stand-btn")
double_button = document.querySelector("#double-btn")
next_button = document.querySelector("#next-btn")


def load_chips() -> int:
    """前回のチップを読む。無ければ最初の枚数。"""
    try:
        return int(localStorage.getItem(CHIPS_KEY) or START_CHIPS)
    except (TypeError, ValueError):
        return START_CHIPS


def save_chips(chips: int) -> None:
    localStorage.setItem(CHIPS_KEY, str(chips))


# 卓の状態は Game が全部持っている。ブラウザ側が覚えるのは「次に賭ける額」だけ
game = Game(load_chips())
bet = BETS[1]


def card_element(card: Card, hidden: bool = False):
    """カード 1 枚ぶんの <div> を作る。CLI 版の f"[{card}]" にあたる。"""
    element = document.createElement("div")

    if hidden:
        element.className = "c back"
        return element

    element.className = "c red" if card.suit in RED_SUITS else "c"

    rank = document.createElement("span")
    rank.className = "r"
    rank.textContent = card.rank

    suit = document.createElement("span")
    suit.className = "s"
    suit.textContent = card.suit.value

    element.appendChild(rank)
    element.appendChild(suit)
    return element


def show_hand(box, hand: Hand, hide_second: bool = False) -> None:
    """手札を並べ直す。hide_second なら 2 枚目を裏向きにする。"""
    box.replaceChildren()
    for index, card in enumerate(hand.cards):
        box.appendChild(card_element(card, hidden=hide_second and index == 1))


def total_text(hand: Hand) -> str:
    """CLI 版の Hand.__str__ の末尾と同じ。"""
    if not hand.cards:
        return ""
    return f"{hand.total} (soft)" if hand.is_soft else str(hand.total)


def draw():
    """CLI 版の render() にあたる。手札・チップ・ボタンの見せ方を段階に合わせる。"""
    playing = game.phase == "player"
    betting = game.phase == "bet"

    show_hand(dealer_box, game.dealer, hide_second=playing)
    show_hand(player_box, game.player)
    dealer_total.textContent = "?" if playing else total_text(game.dealer)
    player_total.textContent = total_text(game.player)

    chips_label.textContent = str(game.chips)
    bet_label.textContent = str(bet if betting else game.bet)
    deck_label.textContent = str(len(game.deck))

    for button in bet_buttons:
        amount = int(button.getAttribute("data-bet"))
        button.disabled = not betting or amount > game.chips
        button.className = "bet is-on" if amount == bet else "bet"

    deal_button.hidden = not betting
    deal_button.disabled = not betting or bet > game.chips
    hit_button.hidden = stand_button.hidden = double_button.hidden = not playing
    double_button.disabled = not game.can_double
    next_button.hidden = game.phase != "done"

    if game.record:
        record_label.textContent = "戦績: " + " / ".join(
            f"{RECORD_LABEL[key]} {n}" for key, n in game.record.most_common())
    else:
        record_label.textContent = ""


def after_action():
    """1 手のあと。決着していたら精算の表示まで。"""
    draw()

    if game.phase == "done":
        net = payout(game.result, game.bet) - game.bet
        message.textContent = f"{RESULT_TEXT[game.result]}  {net:+d} 枚"
        save_chips(game.chips)


def deal():
    if game.start_round(bet):
        message.textContent = ""
        after_action()


def next_round():
    global bet

    game.next_round()
    if game.chips <= 0:
        message.textContent = "チップがなくなりました。下のリンクで 100 枚に戻せます。"
    else:
        message.textContent = ""
        while bet > game.chips:                              # 手持ちより大きい賭けは下げる
            bet = BETS[BETS.index(bet) - 1]
    draw()


@when("click", ".bet")
def on_bet(event):
    global bet
    bet = int(event.target.getAttribute("data-bet"))
    draw()


@when("click", "#deal-btn")
def on_deal(event):
    deal()


@when("click", "#hit-btn")
def on_hit(event):
    if game.hit():
        after_action()


@when("click", "#stand-btn")
def on_stand(event):
    if game.stand():
        after_action()


@when("click", "#double-btn")
def on_double(event):
    if game.double():
        after_action()


@when("click", "#next-btn")
def on_next(event):
    next_round()


@when("click", "#reset-btn")
def on_reset(event):
    global game, bet

    game = Game(START_CHIPS)                                 # 作り直すだけで初期化になる
    bet = BETS[1]
    save_chips(game.chips)
    message.textContent = ""
    draw()


@when("keydown", "body")
def on_key(event):
    """CLI 版の h / s / d と同じ文字で動く。"""
    key = event.key.lower()

    if game.phase == "player":
        if key == "h" and game.hit():
            after_action()
        elif key == "s" and game.stand():
            after_action()
        elif key == "d" and game.double():
            after_action()
    elif key == "enter":
        if game.phase == "bet":
            deal()
        elif game.phase == "done":
            next_round()


# Pyodide の読み込みが終わってから実行される＝ここが準備完了の合図
document.querySelector("#loading").hidden = True
draw()
