"""
dynhosts / make_icon.py
トレイアイコンと同じ描画ロジックから EXE 用の dynhosts.ico を生成する。
build.ps1 から PyInstaller 実行前に呼び出される。

使い方:
    python make_icon.py
"""

from pathlib import Path

from main import build_icon_image

ICO_PATH = Path(__file__).parent / "dynhosts.ico"

# 各サイズをネイティブ描画して 1 つの ICO にまとめる
# （単一画像の縮小だと 16px などの小サイズでにじむため）
SIZES = [16, 24, 32, 48, 64, 128, 256]


def main() -> None:
    images = [build_icon_image(s) for s in SIZES]
    largest = images[-1]
    largest.save(
        ICO_PATH,
        format="ICO",
        append_images=images[:-1],
        sizes=[(s, s) for s in SIZES],
    )
    print(f"生成しました: {ICO_PATH}")


if __name__ == "__main__":
    main()
