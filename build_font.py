"""
build_font.py  -  PC 端预生成 12x12 / 16x16 全字符集字库

输出到 fonts/ 目录：
  simsun12.font, simsun16.font
  simhei12.font, simhei16.font
  simli12.font,  simli16.font

字体文件格式（与 reader.py 约定）：
  [0..3]    magic 'FN12' 或 'FN16'   (4 字节)
  [4..7]    num_chars u32 LE         (字符数)
  [8..9]    char_bytes u16 LE        (每字字节数：12x12=24, 16x16=32)
  [10..11]  reserved u16 LE
  [12..15]  index_offset u32 LE
  [16..19]  bitmap_offset u32 LE
  [20..23]  reserved u32 LE
  [24...]   index 表                 (按 codepoint 升序，每个 4 字节 u32 LE 给出 bitmap 区内序号)
  [...]     bitmap 区                (num_chars * char_bytes 字节 MONO_VLSB)

字符集（覆盖中文小说用到的所有字符）：
  - 0x0020-0x007E  ASCII 可打印
  - 0x3000-0x303F  CJK 标点
  - 0x3400-0x4DBF  CJK 扩展 A
  - 0x4E00-0x9FFF  CJK 基本
  - 0xFF00-0xFFEF  全角 ASCII
"""

import os
import struct
import sys

from PIL import Image, ImageDraw, ImageFont

OUTPUT_DIR = "fonts"

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


def gen_codepoints():
    """生成字符集（按 codepoint 升序）"""
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


def build_one(name, font_path, size):
    FW = FH = size
    FB = (FW + 7) // 8 * FH
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(OUTPUT_DIR, f"{name}{size}.font")
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


def load_font(path, size):
    return ImageFont.truetype(path, size)


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
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
                build_one(name, font_path, size)
            except Exception as e:
                print("  错误:", e)
                import traceback

                traceback.print_exc()
    print(f"\n生成完成。共 {len(generated)} 个字体文件，目录：{OUTPUT_DIR}/")
    print("复制整个 fonts/ 目录到 SD 卡的 /fonts/ 路径下即可。")


if __name__ == "__main__":
    main()
