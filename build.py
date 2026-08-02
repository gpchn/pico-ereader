"""
build_sd.py — 一键构建完整 SD 卡镜像（字库 + 书籍）

整合 build_font.py 与 build_books.py，所有成品统一输出到 sd_card/：

  sd_card/
  ├── fonts/
  │   └── *.font          ← 字库（PC 预生成）
  ├── books/
  │   ├── book_0001.txt   ← ASCII 文件名
  │   ├── book_0001_32.idx
  │   ├── book_0001_18.idx
  │   └── ...
  └── books.map           ← ASCII名|中文名 映射

用法:
  python build_sd.py                # 重新生成字库 + 处理书籍
  python build_sd.py --copy-fonts   # 字库不重新生成，直接复制 fonts/ 下已有成品
  python build_sd.py --no-books     # 只处理字库
  python build_sd.py --no-fonts     # 只处理书籍

输出目录整个拷到 FAT32 SD 卡根目录即可。
"""

import os
import shutil
import sys

import build_books
import build_font

OUT_DIR = "sd_card"


def clean():
    targets = [
        os.path.join(OUT_DIR, "books"),
        os.path.join(OUT_DIR, "fonts"),
        os.path.join(OUT_DIR, "books.map"),
    ]
    for path in targets:
        if os.path.isdir(path):
            shutil.rmtree(path)
        elif os.path.exists(path):
            os.remove(path)


def copy_fonts():
    src = build_font.OUTPUT_DIR
    if not os.path.isdir(src):
        print("错误: %s/ 目录不存在，先运行 python build_font.py" % src)
        return False
    dst = os.path.join(OUT_DIR, "fonts")
    os.makedirs(dst, exist_ok=True)
    n = 0
    for f in sorted(os.listdir(src)):
        if f.endswith(".font"):
            shutil.copy2(os.path.join(src, f), dst)
            n += 1
    print(f"已复制 {n} 个字库文件 → {dst}/")
    return n > 0


def main():
    args = sys.argv[1:]
    copy_fonts_mode = "--copy-fonts" in args
    no_books = "--no-books" in args
    no_fonts = "--no-fonts" in args
    if copy_fonts_mode:
        no_fonts = True

    print("=" * 52)
    print("构建 SD 卡镜像 → %s/" % OUT_DIR)
    print("=" * 52)

    clean()

    if not no_fonts:
        print("\n[1/2] 生成字库...")
        build_font.main(os.path.join(OUT_DIR, "fonts"))
    else:
        print("\n[1/2] 字库...")
        if copy_fonts_mode:
            copy_fonts()
        else:
            print("已跳过（--no-fonts）")

    if not no_books:
        print("\n[2/2] 处理书籍...")
        build_books.main(OUT_DIR)
    else:
        print("\n[2/2] 书籍...")
        print("已跳过（--no-books）")

    print("\n" + "=" * 52)
    print("构建完成! 输出目录: %s/" % OUT_DIR)
    print("把该目录下的内容复制到 FAT32 SD 卡根目录即可：")
    print("  /fonts/  ← 字库")
    print("  /books/  ← 书籍 + 页索引")
    print("  /books.map ← 文件名映射")


if __name__ == "__main__":
    main()
