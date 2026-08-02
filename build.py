"""
build.py — 一键构建完整 SD 卡镜像（字库 + 书籍）

整合原 build_font.py 与 build_books.py，所有成品统一输出到 sd_card/：

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
  python build.py                # 重新生成字库 + 处理书籍
  python build.py --copy-fonts   # 字库不重新生成，直接复制 fonts/ 下已有成品
  python build.py --no-books     # 只处理字库
  python build.py --no-fonts     # 只处理书籍

输出目录整个拷到 FAT32 SD 卡根目录即可。
"""

import os
import shutil
import struct
import sys

from PIL import Image, ImageDraw, ImageFont

OUT_DIR = "sd_card"
FONTS_OUT_DIR = "fonts"
BOOKS_IN = "books"
PAGE_SIZES = [32, 18]  # 12x12→32 字/页, 16x16→18 字/页

FONTS = [
    # (名称, 字体路径, 尺寸列表)
    ("simsun", "C:/Windows/Fonts/simsun.ttc", [12, 16]),
    (
        "wq",
        r"C:\Users\gpchn\AppData\Local\Microsoft\Windows\Fonts\WenQuanYi Bitmap Song 16px.ttf",
        [16],
    ),
    (
        "wq",
        r"C:\Users\gpchn\AppData\Local\Microsoft\Windows\Fonts\WenQuanYi Bitmap Song 12px.ttf",
        [12],
    ),
    # Linux 备选
    # ('simsun', '/usr/share/fonts/truetype/wqy/wqy-microhei.ttc', [12, 16]),
    # ('simsun', '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc', [12, 16]),
    # macOS
    # ('simsun', '/System/Library/Fonts/PingFang.ttc', [12, 16]),
]

# 字体文件格式（与 reader.py 约定）：
#   [0..3]    magic 'FN12'/'FN16'  (4 字节，只校验前 2 字节 'FN')
#   [4..7]    num_chars u32 LE
#   [8..9]    char_bytes u16 LE    (每字字节数：12x12=24, 16x16=32)
#   [10..11]  reserved u16 LE
#   [12..15]  index_offset u32 LE
#   [16..19]  bitmap_offset u32 LE
#   [20..23]  reserved u32 LE
#   [24...]   index 表 (按 codepoint 升序，每个 u32 LE 给出 bitmap 区内序号)
#   [...]     bitmap 区 (num_chars * char_bytes 字节 MONO_VLSB)

# 字符集（覆盖中文小说用到的所有字符，须与 reader.py 的 _RANGES 一致）
#   - 0x0020-0x007E  ASCII 可打印
#   - 0x3000-0x303F  CJK 标点
#   - 0x3400-0x4DBF  CJK 扩展 A
#   - 0x4E00-0x9FFF  CJK 基本
#   - 0xFF00-0xFFEF  全角 ASCII


def gen_codepoints():
    cps = set()
    for cp in range(0x20, 0x7F):
        cps.add(cp)
    for cp in range(0x3000, 0x3040):
        cps.add(cp)
    for cp in range(0x3400, 0x4DC0):
        cps.add(cp)
    for cp in range(0x4E00, 0xA000):
        cps.add(cp)
    for cp in range(0xFF00, 0xFFF0):
        cps.add(cp)
    return sorted(cps)


def load_font(path, size):
    return ImageFont.truetype(path, size)


def render_to_vlsb(font, ch, FW, FH):
    """单个字符 -> MONO_VLSB 字节数组。
    framebuf.MONO_VLSB 布局：buffer[page*FW + x] 的 bit (y%8) 表示像素 (x, y)
    """
    img = Image.new("1", (FW, FH), 0)
    draw = ImageDraw.Draw(img)
    bbox = draw.textbbox((0, 0), ch, font=font)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    if w <= 0 or h <= 0:
        return bytes((FW + 7) // 8 * FH)
    x = (FW - w) // 2 - bbox[0]
    y = (FH - h) // 2 - bbox[1]
    draw.text((x, y), ch, fill=1, font=font)
    FB = (FW + 7) // 8 * FH
    out = bytearray(FB)
    for x in range(FW):
        for y in range(FH):
            page = y >> 3
            bit = y & 7
            if img.getpixel((x, y)):
                out[page * FW + x] |= 1 << bit
    return bytes(out)


def build_one(name, font_path, size, out_dir):
    FW = FH = size
    FB = (FW + 7) // 8 * FH
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{name}{size}.font")
    print(f"\n[{os.path.basename(out_path)}] 字体={font_path}  尺寸={FW}x{FH}")

    font = load_font(font_path, size)
    codepoints = gen_codepoints()
    print("  字符数:", len(codepoints))

    bitmaps = bytearray()
    rendered = 0
    skipped = 0
    for cp in codepoints:
        ch = chr(cp)
        try:
            bm = render_to_vlsb(font, ch, FW, FH)
            bitmaps += bm
            rendered += 1
        except Exception:
            skipped += 1
            bitmaps += bytes(FB)
    print(f"  渲染: 成功={rendered} 失败/空白={skipped}")

    num_chars = len(codepoints)
    index_size = num_chars * 4
    bitmap_size = num_chars * FB
    header_size = 24
    index_offset = header_size
    bitmap_offset = header_size + index_size
    magic = b"FN%d" % (size % 100)  # 'FN12' / 'FN16'

    with open(out_path, "wb") as f:
        f.write(magic)
        f.write(struct.pack("<I", num_chars))
        f.write(struct.pack("<H", FB))
        f.write(struct.pack("<H", 0))
        f.write(struct.pack("<I", index_offset))
        f.write(struct.pack("<I", bitmap_offset))
        f.write(struct.pack("<I", 0))
        for i in range(num_chars):
            f.write(struct.pack("<I", i))
        f.write(bitmaps)
    print(
        "  写入:",
        out_path,
        f"({os.path.getsize(out_path)} 字节, {os.path.getsize(out_path) / 1024:1f} KB)",
    )


def build_fonts(out_dir):
    """生成字库到 out_dir/（含名称去重，跳过不存在的字体文件）。"""
    os.makedirs(out_dir, exist_ok=True)
    generated = set()
    for name, font_path, sizes in FONTS:
        if not os.path.exists(font_path):
            continue
        for size in sizes:
            key = (name, size)
            if key in generated:
                continue
            generated.add(key)
            try:
                build_one(name, font_path, size, out_dir)
            except Exception as e:
                print("  错误:", e)
                import traceback

                traceback.print_exc()
    print(f"\n生成完成。共 {len(generated)} 个字体文件，目录：{out_dir}/")


def copy_fonts():
    src = FONTS_OUT_DIR
    if not os.path.isdir(src):
        print("错误: %s/ 目录不存在，先运行 python build.py" % src)
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


def build_index(data, out_dir, ascii_name, per_page):
    """在内存中扫描文本，生成 .idx 文件（每页起始字节偏移的 u32 LE 数组）。"""
    idx_path = "%s/%s_%d.idx" % (out_dir, ascii_name, per_page)
    with open(idx_path, "wb") as idx:
        idx.write(struct.pack("<I", 0))
        char_count = 0
        last_was_space = False
        i = 0
        L = len(data)
        while i < L:
            b = data[i]
            if b < 0x80:
                ch_bytes_len = 1
            elif b < 0xE0:
                ch_bytes_len = 2
            elif b < 0xF0:
                ch_bytes_len = 3
            else:
                ch_bytes_len = 4
            if i + ch_bytes_len > L:
                break
            ch = data[i:i + ch_bytes_len].decode("utf-8", "ignore")
            i += ch_bytes_len
            if not ch:
                continue
            if ch.isspace() or ch == "\u3000":
                if not last_was_space:
                    char_count += 1
                    last_was_space = True
            else:
                char_count += 1
                last_was_space = False
            if char_count == per_page:
                idx.write(struct.pack("<I", i))
                char_count = 0
                last_was_space = False


def process_one(txt_path, book_id, out_dir):
    """处理单本小说，返回 (ascii_name, original_name)。"""
    base = os.path.basename(txt_path)
    orig_name = base
    if orig_name.lower().endswith(".txt"):
        orig_name = orig_name[:-4]

    ascii_name = "book_%04d" % book_id
    out_txt = "%s/%s.txt" % (out_dir, ascii_name)

    with open(txt_path, "rb") as f:
        data = f.read()

    # 处理 BOM
    if data[:3] == b"\xef\xbb\xbf":
        data = data[3:]

    with open(out_txt, "wb") as f:
        f.write(data)

    for pp in PAGE_SIZES:
        build_index(data, out_dir, ascii_name, pp)

    print("  %s ← %s" % (out_txt, base))
    return ascii_name, orig_name


def build_books(out_dir):
    """books/*.txt → out_dir/books/（ASCII 名 + .idx）+ out_dir/books.map"""
    books_out = os.path.join(out_dir, "books")
    os.makedirs(books_out, exist_ok=True)

    if not os.path.isdir(BOOKS_IN):
        print("错误: 找不到输入目录 %s/" % BOOKS_IN)
        print("请把 .txt 文件放到 %s/ 目录下" % BOOKS_IN)
        sys.exit(1)

    files = sorted([f for f in os.listdir(BOOKS_IN)
                    if f.endswith(".txt") and not f.startswith(".")])

    if not files:
        print("错误: %s/ 目录下没有 .txt 文件" % BOOKS_IN)
        sys.exit(1)

    mapping = []
    for idx, fname in enumerate(files, 1):
        txt_path = os.path.join(BOOKS_IN, fname)
        ascii_name, orig_name = process_one(txt_path, idx, books_out)
        mapping.append((ascii_name, orig_name))

    map_file = os.path.join(out_dir, "books.map")
    with open(map_file, "w", encoding="utf-8") as f:
        for ascii_name, orig_name in mapping:
            f.write("%s.txt|%s\n" % (ascii_name, orig_name))

    print("\n完成! 共处理 %d 本书" % len(mapping))
    print("输出目录: %s/" % books_out)
    print("元数据:   %s" % map_file)


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
        build_fonts(os.path.join(OUT_DIR, "fonts"))
    else:
        print("\n[1/2] 字库...")
        if copy_fonts_mode:
            copy_fonts()
        else:
            print("已跳过（--no-fonts）")

    if not no_books:
        print("\n[2/2] 处理书籍...")
        build_books(OUT_DIR)
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
