"""game.py の中身から版を作り、index.html の読み込みに付ける。

中身が変われば版も変わるので、ブラウザは必ず新しいものを取りに行く。
古いままの画面を見続ける、が起きなくなる。
"""
import hashlib
import re
import sys

folder = sys.argv[1]
code = open(f"{folder}/game.py", "rb").read()
version = hashlib.sha256(code).hexdigest()[:8]
page = open(f"{folder}/index.html").read()
page, count = re.subn(r'src="\./game\.py(\?v=[0-9a-f]+)?"', f'src="./game.py?v={version}"', page)
assert count == 1, f"読み込みが {count} か所"
open(f"{folder}/index.html", "w").write(page)
print(f"{folder}/game.py の版: {version}")
