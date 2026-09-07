"""main.py の検証。python3 -m unittest -v で実行する。"""

import unittest

from main import BLACK, START_FEN, WHITE, Board, Game, Move, count_moves, insufficient_material, legal_moves, result_of

# 世界中のチェスプログラムが使う既知の値（perft）
PERFT_CASES = {
    "初期局面": (START_FEN, [(1, 20), (2, 400), (3, 8902)]),
    "Kiwipete": ("r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq -", [(1, 48), (2, 2039), (3, 97862)]),
    "局面 3": ("8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - -", [(1, 14), (2, 191), (3, 2812)]),
    "局面 4": ("r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq -", [(1, 6), (2, 264), (3, 9467)]),
    "局面 5": ("rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ -", [(1, 44), (2, 1486)]),
}


class PerftTest(unittest.TestCase):
    """合法手の数が既知の値と一致するか。キャスリング・アンパッサン・成りを含む。"""

    def test_perft(self):
        for name, (fen, table) in PERFT_CASES.items():
            for depth, expected in table:
                with self.subTest(name=name, depth=depth):
                    self.assertEqual(count_moves(Board.from_fen(fen), depth), expected)


class FenTest(unittest.TestCase):
    def test_roundtrip(self):
        for fen, _ in PERFT_CASES.values():
            with self.subTest(fen=fen):
                full = fen if len(fen.split()) == 6 else fen + " 0 1"
                self.assertEqual(Board.from_fen(fen).fen, full)

    def test_counters(self):
        board = Board.from_fen(START_FEN)
        self.assertEqual((board.halfmove, board.fullmove), (0, 1))
        board = Game().board
        game = Game()
        game.play(Move.parse("g1f3"))
        self.assertEqual((game.board.halfmove, game.board.fullmove), (1, 1))     # ナイトの手は数える。黒が指すまで手数は同じ
        game.play(Move.parse("g8f6"))
        self.assertEqual((game.board.halfmove, game.board.fullmove), (2, 2))
        game.play(Move.parse("e2e4"))
        self.assertEqual(game.board.halfmove, 0)                                  # ポーンの手で振り出し

    def test_same_position_ignores_counters(self):
        a = Board.from_fen("4k3/8/8/8/8/8/8/4K3 w - - 0 1")
        b = Board.from_fen("4k3/8/8/8/8/8/8/4K3 w - - 37 60")
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))


class DrawTest(unittest.TestCase):
    def setUp(self):
        self.game = Game()

    def play(self, *moves):
        for text in moves:
            self.assertTrue(self.game.play(Move.parse(text)), text)

    def test_repetition(self):
        shuffle = ["g1f3", "g8f6", "f3g1", "f6g8"]
        self.play(*shuffle)
        self.assertEqual(self.game.repetitions, 2)
        self.assertIsNone(self.game.result)
        self.play(*shuffle)
        self.assertEqual(self.game.repetitions, 3)
        self.assertEqual(self.game.result, "repetition")

    def test_undo_restores_repetitions(self):
        self.play("g1f3", "g8f6", "f3g1", "f6g8")
        self.game.undo()
        self.game.undo()
        self.game.undo()
        self.game.undo()
        self.assertEqual(self.game.repetitions, 1)

    def test_fifty_moves(self):
        game = Game(fen="4k3/8/8/8/8/8/8/R3K3 w - - 99 80")
        game.play(Move.parse("a1a2"))
        self.assertEqual(game.result, "fifty")
        game = Game(fen="4k3/8/8/8/8/8/P7/4K3 w - - 99 80")
        game.play(Move.parse("a2a3"))                                             # ポーンの手なら振り出し
        self.assertIsNone(game.result)

    def test_insufficient_material(self):
        for fen, expected in [("4k3/8/8/8/8/8/8/4K3 w - -", True),
                              ("4k3/8/8/8/8/8/8/4KB2 w - -", True),
                              ("4k3/8/8/8/8/8/8/4KN2 w - -", True),
                              ("4kb2/8/8/8/8/8/8/4KB2 w - -", False),              # f8 と f1 は色が違う
                              ("4k1b1/8/8/8/8/8/8/4KB2 w - -", True),              # g8 と f1 は同じ色
                              ("4k3/8/8/8/8/8/8/4KR2 w - -", False),
                              ("4k3/8/8/8/8/8/8/4KNN1 w - -", False)]:
            with self.subTest(fen=fen):
                self.assertEqual(insufficient_material(Board.from_fen(fen)), expected)
                self.assertEqual(result_of(Board.from_fen(fen)) == "material", expected)


class RuleTest(unittest.TestCase):
    def test_checkmate_and_stalemate(self):
        self.assertEqual(result_of(Board.from_fen("rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq -")), BLACK)
        self.assertEqual(result_of(Board.from_fen("7k/5Q2/6K1/8/8/8/8/8 b - -")), "stalemate")

    def test_castling(self):
        board = Board.from_fen("4k3/8/8/8/8/8/8/R3K2R w KQ -")
        self.assertIn(Move.parse("e1g1"), legal_moves(board))
        self.assertIn(Move.parse("e1c1"), legal_moves(board))
        board = Board.from_fen("4k3/8/8/8/8/8/5r2/R3K2R w KQ -")                 # f1 が利きに入っている
        self.assertNotIn(Move.parse("e1g1"), legal_moves(board))
        self.assertIn(Move.parse("e1c1"), legal_moves(board))

    def test_en_passant(self):
        game = Game(fen="4k3/8/8/8/3p4/8/4P3/4K3 w - -")
        game.play(Move.parse("e2e4"))
        self.assertIn(Move.parse("d4e3"), game.legal_moves)
        game.play(Move.parse("d4e3"))
        self.assertIsNone(game.board["e4"])


if __name__ == "__main__":
    unittest.main()
