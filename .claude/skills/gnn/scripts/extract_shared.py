"""CLI 版 main.py から、ブラウザ版と共有する部分を ast で切り出す。

手で写すと写し間違いが混ざるので、名前で指定して原文の行をそのまま連結する。
ステップの目印（# ←）はここで落とす。

    python3 extract_shared.py main.py --names SIZE,EMPTY,make_board,Game \
        --drop-methods render,draw > shared.py

--names は出力したい順に並べる。連続する定数をくっつけたいときは + でつなぐ
（例: SIZE+GOAL+NEAR）。クラスからメソッドを外すときは --drop-methods。
"""

import argparse
import ast
import re
import sys

MARKER = re.compile(r"[ \t]*# ←$")


def strip_markers(text):
    return "\n".join(MARKER.sub("", line) for line in text.split("\n"))


def blocks(path, drop_methods):
    """{名前: その定義の行そのもの} を返す。"""
    source = open(path, encoding="utf-8").read()
    lines = source.split("\n")
    tree = ast.parse(source)
    out = {}

    def text_of(node, drop=()):
        keep = list(range(node.lineno - 1, node.end_lineno))
        for method in drop:
            for i in range(method.lineno - 1, method.end_lineno):
                keep.remove(i)
        taken = [lines[i] for i in keep]
        while taken and not taken[-1].strip():          # 落とした跡の空行を詰める
            taken.pop()
        return strip_markers("\n".join(taken))

    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            out[node.targets[0].id] = text_of(node)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out[node.name] = text_of(node)
        elif isinstance(node, ast.ClassDef):
            drop = [b for b in node.body
                    if isinstance(b, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and b.name in drop_methods]
            out[node.name] = text_of(node, drop)

    return out


def shared_text(path, names, drop_methods):
    b = blocks(path, drop_methods)
    missing = [n for group in names for n in group.split("+") if n not in b]
    if missing:
        sys.exit(f"main.py に見つからない名前: {', '.join(missing)}")

    parts = ["\n".join(b[n] for n in group.split("+")) for group in names]
    return "\n\n\n".join(parts) + "\n"


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("source")
    p.add_argument("--names", required=True,
                   help="出力する定数・関数・クラスをカンマ区切りで。+ でつなぐと間を1行空けにする")
    p.add_argument("--drop-methods", default="",
                   help="クラスから外すメソッド（カンマ区切り）")
    a = p.parse_args()

    sys.stdout.write(shared_text(a.source,
                                 [n.strip() for n in a.names.split(",") if n.strip()],
                                 {m.strip() for m in a.drop_methods.split(",") if m.strip()}))
