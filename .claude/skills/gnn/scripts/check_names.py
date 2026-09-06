"""読まれているのに import も定義もされていない名前を洗う。

ブラウザ版 docs/gNN/game.py は共有部分を機械的に写すが、ヘッダ（import 群）は
手で書くので必ず漏れる。g09 は import random の抜けを実機の NameError で見つけた。
ブラウザを開く前にこれで捕まえる。

    python3 check_names.py docs/g10/game.py

見つからなければ「未定義の名前: なし」と出て終了コード 0。
"""

import ast
import sys

EXTRA = {"__file__", "__name__", "self"}


def undefined(path):
    tree = ast.parse(open(path, encoding="utf-8").read())
    defined = set(dir(__builtins__)) | EXTRA

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                defined.add((a.asname or a.name).split(".")[0])
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            defined.add(node.id)
        elif isinstance(node, ast.arg):
            defined.add(node.arg)

    used = {n.id for n in ast.walk(tree)
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
    return sorted(used - defined)


if __name__ == "__main__":
    missing = []
    for path in sys.argv[1:]:
        found = undefined(path)
        print(f"{path} の未定義の名前:", found or "なし")
        missing += found
    sys.exit(1 if missing else 0)
