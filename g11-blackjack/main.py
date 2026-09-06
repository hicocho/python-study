"""ブラックジャック — 完成: 1 卓ぶんの状態を class Game にまとめ、戦績を数える。"""

import random
from collections import Counter             # ←
from dataclasses import dataclass
from enum import Enum

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

RECORD_LABEL = {                            # ←
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


def hidden_text(hand: Hand) -> str:
    """ディーラーの手札を、2 枚目を伏せた状態で返す。"""
    return f"[{hand.cards[0]}] [??]"


def dealer_play(hand: Hand, draw) -> None:  # ←
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


class Game:                                 # ←
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

    def render(self) -> str:
        """卓の様子を端末に出す文字列にして返す。勝負中はディーラーの 2 枚目を伏せる。"""
        dealer = hidden_text(self.dealer) if self.phase == "player" else str(self.dealer)
        return (f"ディーラー: {dealer}\n"
                f"あなた:     {self.player}\n"
                f"賭け金 {self.bet} 枚 / 山 {len(self.deck)} 枚")


def ask_bet(chips: int) -> int:
    """賭ける枚数を聞いて返す。0 なら「やめる」。"""
    while True:
        answer = input(f"\nチップ {chips} 枚。いくら賭けますか？（0 でやめる）> ").strip()

        if not answer.isdigit():
            print("数字で入れてください。")
            continue

        bet = int(answer)
        if bet > chips:
            print(f"手持ちは {chips} 枚です。")
            continue

        return bet


def ask_action(can_double: bool) -> str:
    """h / s / d を聞いて "hit" / "stand" / "double" で返す。"""
    choices = "h: もう 1 枚 / s: 止める"
    if can_double:
        choices += " / d: ダブルダウン"

    while True:
        answer = input(f"{choices} > ").strip().lower()

        match answer:
            case "h" | "hit":
                return "hit"
            case "s" | "stand":
                return "stand"
            case "d" | "double" if can_double:
                return "double"
            case _:
                print("h か s で答えてください。")


def main():                                 # ←
    game = Game()

    print(f"チップ {game.chips} 枚からスタート。ブラックジャックは 1.5 倍。")

    while game.chips > 0:
        bet = ask_bet(game.chips)
        if bet == 0:
            break

        game.start_round(bet)

        while game.phase == "player":
            print()
            print(game.render())

            match ask_action(game.can_double):
                case "hit":
                    game.hit()
                case "stand":
                    game.stand()
                case "double":
                    game.double()

        print()
        print(game.render())
        print(f"\n{RESULT_TEXT[game.result]}  {payout(game.result, game.bet) - game.bet:+d} 枚")
        game.next_round()

    print(f"\n終了。チップは {game.chips} 枚（{game.chips - START_CHIPS:+d}）。")
    if game.record:
        print("戦績: " + " / ".join(f"{RECORD_LABEL[k]} {n}" for k, n in game.record.most_common()))


if __name__ == "__main__":
    main()
