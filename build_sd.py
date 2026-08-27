"""
build_sd.py — 一键构建完整 SD 卡镜像（字库 + 书籍 + 背单词词库）

合并原 build.py（字库 + 书籍）与 build_dict.py（ECDICT 词库）为一个工具，
路径全部写死，所有成品统一输出到 sdcard/：

  sdcard/
  ├── fonts/
  │   └── *.font          ← 字库（PC 预生成）
  ├── books/
  │   ├── book_0001.txt   ← ASCII 文件名
  │   ├── book_0001_32.idx
  │   ├── book_0001_18.idx
  │   └── ...
  ├── books.map           ← ASCII名|中文名 映射
  └── dict/               ← 背单词词库（ECDICT 预处理）
      ├── master.*        ← 主词库（空间换时间二进制索引）
      ├── decks/*.bin     ← 各牌组
      ├── progress/*.bin  ← 学习进度（仅在词库重建时重置）
      └── unknown.bin     ← 生词本（设备端累积，绝不被覆盖）

增量构建（默认开启，大幅提升重复构建速度）：
  - 字库：仅当源字体文件比成品 .font 更新时才重新渲染
  - 书籍：仅当源 .txt 比成品更新时才重新切页；并尽量复用原有 book_XXXX
          编号，使断电续读进度（book_XXXX.txt.prog）在加/删书后依然有效
  - 词库：仅当 ECDICT csv 比 master.* 更新时才重建；否则整段跳过
  - 生词本 unknown.bin / 学习进度默认保留，不被脚本清空

用法:
  python build_sd.py              # 字库 + 书籍 + 词库，全部增量（默认）
  python build_sd.py --force      # 强制全量重建（清空学习进度与词库）

路径均为硬编码（见文件顶部常量）：
  OUT_DIR=sdcard, BOOKS_IN=books, DEFAULT_CSV=ECDICT/ecdict.csv, FONTS 见顶部列表。
输出目录整个拷到 FAT32 SD 卡根目录即可。
"""

import os
import struct
import sys
import csv

# --------------------------------------------------------------------------
# 通用配置
# --------------------------------------------------------------------------
OUT_DIR = "sdcard"
BOOKS_IN = "books"
DICT_SUB = "dict"
PAGE_SIZES = [32, 18]            # 12x12→32 字/页, 16x16→18 字/页

# 源字体（换机器/换字体改这里；Linux/macOS 备选已注释）
FONTS = [
    ("simsun", "C:/Windows/Fonts/simsun.ttc", [12, 16]),
    ("simyou", r"C:/Windows/Fonts/simyou.ttf", [12, 16]),
    ("simhei", r"C:/Windows/Fonts/simhei.ttf", [12, 16]),
    # Linux
    # ('simsun', '/usr/share/fonts/truetype/wqy/wqy-microhei.ttc', [12, 16]),
    # macOS
    # ('simsun', '/System/Library/Fonts/PingFang.ttc', [12, 16]),
]


def _mtime(p):
    try:
        return os.path.getmtime(p)
    except OSError:
        return 0


def _font_covers_all_fingerprint(font_path):
    """校验既有 .font 的字符数与当前 gen_codepoints() 一致（即区间没有演进）。

    只读 header 的 num_chars（偏移 4 起 4 字节小端 u32），不需整读字库。
    字符数不同说明区间被增删过，返回 False 触发重建。
    """
    try:
        with open(font_path, 'rb') as f:
            f.read(4)                                   # magic 'FNxx'
            num_chars = struct.unpack('<I', f.read(4))[0]
    except OSError:
        return False
    return num_chars == len(gen_codepoints())


# ==========================================================================
# 字库（原 build.py）
# ==========================================================================
# 音标（IPA）所需附加区间，与 src/lib/reader.py 的 _RANGES 必须完全一致（线性寻址）。
# 覆盖 ECDICT 音标实际用到的字符：拉丁（æ ð ŋ…）、IPA 扩展（ə ʃ ʊ ʌ…）、
# 修饰符（ˈ ˌ ː…）、希腊（θ ε）、西里尔（ә є，ECDICT 常用）。
PHON_RANGES = (
    (0x00A0, 0x0180),  # 拉丁-1 补充 + 拉丁扩展-A
    (0x0250, 0x0300),  # IPA 扩展 + 修饰符字母
    (0x0370, 0x0400),  # 希腊
    (0x0400, 0x0500),  # 西里尔
)


def gen_codepoints():
    cps = set()
    for cp in range(0x20, 0x7F):
        cps.add(cp)
    for start, end in PHON_RANGES:
        for cp in range(start, end):
            cps.add(cp)
    # 通用标点区：中文排版常用的一半标点其实是非全角的，如 —(2014) –(2013)
    # …(2026) “”(201c/201d) ‘’(2018/2019)。不加的话这些字符查不到字形，
    # 设备端会显示成空块。与 reader._RANGES 必须同步。
    for cp in range(0x2000, 0x2070):
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
    from PIL import ImageFont
    return ImageFont.truetype(path, size)


def render_to_vlsb(font, ch, FW, FH):
    """单个字符 -> MONO_VLSB 字节数组（与 reader.py 约定一致）。"""
    from PIL import Image, ImageDraw
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


def build_one(name, font_path, size, out_dir, force):
    FW = FH = size
    FB = (FW + 7) // 8 * FH
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{name}{size}.font")
    # 增量：源字体未变化，且字库覆盖的码点区间也一致时跳过。
    # 只看 mtime 不够：若在 PHON_RANGES/gen_codepoints 里新增了区间（如补 IPA 音标），
    # 而源字体文件时间戳没变，会静默沿用旧的 .font，导致新字符在设备端渲染空白。
    # 故把当前区间的字符数指纹也纳入判断——指纹不同则强制重建。
    if not force and os.path.exists(out_path) and _mtime(font_path) <= _mtime(out_path):
        if _font_covers_all_fingerprint(out_path):
            print(f"  [跳过] {os.path.basename(out_path)} (字体未变，区间一致)")
            return

    from PIL import ImageFont
    font = ImageFont.truetype(font_path, size)
    codepoints = gen_codepoints()
    print(f"\n[{os.path.basename(out_path)}] 字体={font_path}  尺寸={FW}x{FH}")

    blank = bytes(FB)

    # 回退字体链：中文主字体（simsun/simhei/msyh 等）普遍缺 IPA/希腊扩展字形，
    # 且 PIL 对缺失字符渲染 .notdef「豆腐框」——textbbox 非空、位图非全零，
    # 用「位图==空白」根本检测不到缺失，豆腐框会被当有效字形写进字库（历史 bug）。
    # 故先用两个 PUA 哨兵字符取各字体的 .notdef 样本位图，渲染结果与样本一致即视为缺失；
    # 西文字体（Arial/Segoe UI 等）才有真 IPA 字形，逐个回退直到拿到真字形。
    FALLBACK_PATHS = (
        r"C:/Windows/Fonts/arial.ttf",
        r"C:/Windows/Fonts/segoeui.ttf",
        r"C:/Windows/Fonts/tahoma.ttf",
        r"C:/Windows/Fonts/times.ttf",
        r"C:/Windows/Fonts/DejaVuSans.ttf",
    )

    def notdef_sample(f):
        # 两个不同 PUA 字符渲染一致 → 即该字体对缺失字符的固定渲染（豆腐框或空白）
        a = render_to_vlsb(f, "\ue123", FW, FH)
        b = render_to_vlsb(f, "\uf8ab", FW, FH)
        return a if a == b else None

    main_nd = notdef_sample(font)
    fb_chain = []
    for p in FALLBACK_PATHS:
        if os.path.exists(p):
            try:
                fb_chain.append((ImageFont.truetype(p, size), notdef_sample(ImageFont.truetype(p, size))))
            except Exception:
                pass

    bitmaps = bytearray()
    rendered = 0
    fell_back = 0
    skipped = 0
    for cp in codepoints:
        ch = chr(cp)
        try:
            bm = render_to_vlsb(font, ch, FW, FH)
            if bm == blank or (main_nd is not None and bm == main_nd):
                # 主字体缺失（空白或豆腐框）→ 沿回退链找真字形
                for f, nd in fb_chain:
                    bm2 = render_to_vlsb(f, ch, FW, FH)
                    if bm2 != blank and (nd is None or bm2 != nd):
                        bm = bm2
                        fell_back += 1
                        break
                else:
                    bm = blank
                    skipped += 1
            bitmaps += bm
            rendered += 1
        except Exception:
            skipped += 1
            bitmaps += blank
    print(f"  渲染: 成功={rendered}（回退补字={fell_back}） 缺字形留空={skipped}")

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
    print("  写入:", out_path, f"({os.path.getsize(out_path)} 字节)")


def build_fonts(out_dir, force):
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
                build_one(name, font_path, size, out_dir, force)
            except Exception as e:
                print("  错误:", e)
                import traceback
                traceback.print_exc()
    print(f"\n生成完成。共 {len(generated)} 个字体文件，目录：{out_dir}/")


# ==========================================================================
# 书籍（原 build.py，增量 + 稳定编号）
# ==========================================================================
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

    if data[:3] == b"\xef\xbb\xbf":
        data = data[3:]

    with open(out_txt, "wb") as f:
        f.write(data)

    for pp in PAGE_SIZES:
        build_index(data, out_dir, ascii_name, pp)

    print("  %s ← %s" % (out_txt, base))
    return ascii_name, orig_name


def _idx_ok(out_dir, ascii_name):
    for pp in PAGE_SIZES:
        if not os.path.exists("%s/%s_%d.idx" % (out_dir, ascii_name, pp)):
            return False
    return True


def build_books(out_dir, force):
    """books/*.txt → out_dir/books/（ASCII 名 + .idx）+ out_dir/books.map

    增量：源 .txt 未更新则复用旧成品；编号按原书名复用，使阅读进度文件
    （book_XXXX.txt.prog）在加/删书后依然指向同一本书。
    """
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

    # 载入旧映射：原书名 -> ascii 名（去掉 .txt）
    existing = {}
    map_path = os.path.join(out_dir, "books.map")
    if os.path.exists(map_path):
        with open(map_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if "|" in line:
                    k, v = line.split("|", 1)
                    existing[v] = k[:-4] if k.endswith(".txt") else k

    used_ids = set()
    for v in existing.values():
        try:
            used_ids.add(int(v.split("_")[1]))
        except (IndexError, ValueError):
            pass
    next_id = (max(used_ids) if used_ids else 0) + 1

    mapping = []
    for fname in files:
        txt_path = os.path.join(BOOKS_IN, fname)
        orig = fname[:-4] if fname.lower().endswith(".txt") else fname

        # 原书名已见过（含 --force）→ 复用原编号：编号是进度文件（.prog/.bmk）
        # 的锚点，换号会导致续读失效，且旧成品残留会在书架里重复出现
        if orig in existing:
            ascii_name = existing[orig]
            out_txt = os.path.join(books_out, ascii_name + ".txt")
            unchanged = (not force and os.path.exists(out_txt)
                         and _mtime(txt_path) <= _mtime(out_txt)
                         and _idx_ok(books_out, ascii_name))
            if unchanged:
                mapping.append((ascii_name, orig))
                continue
            # 源已更新或 --force：复用同一编号（保留进度），重新切页
            book_id = int(ascii_name.split("_")[1])
        else:
            book_id = next_id
            next_id += 1
            ascii_name = "book_%04d" % book_id

        process_one(txt_path, book_id, books_out)
        mapping.append((ascii_name, orig))

    # 清理孤儿成品：books/ 里已删掉的书不再出现在映射中，旧 .txt/.idx 若留着
    # 会在书架上显示为幽灵书。只删脚本自己生成的 book_XXXX(.txt/.idx)，
    # 不动设备端写的 .prog/.bmk 进度文件。
    keep = {a for a, _ in mapping}
    for f in os.listdir(books_out):
        if not f.endswith((".txt", ".idx")) or not f.startswith("book_"):
            continue
        parts = f.rsplit(".", 1)[0].split("_")  # ['book','0001'] / ['book','0001','32']
        if len(parts) >= 2 and parts[0] == "book" and parts[1].isdigit():
            if "book_%s" % parts[1] not in keep:
                os.remove(os.path.join(books_out, f))
                print("  清理孤儿: %s" % f)

    with open(map_path, "w", encoding="utf-8") as f:
        for ascii_name, orig_name in mapping:
            f.write("%s.txt|%s\n" % (ascii_name, orig_name))

    print("\n完成! 共处理 %d 本书（复用 %d 个旧编号）" % (
        len(mapping), sum(1 for a, o in mapping if o in existing)))
    print("输出目录: %s/" % books_out)
    print("元数据:   %s" % map_path)


# ==========================================================================
# 背单词词库（原 build_dict.py，增量 + 保留生词本/进度）
# ==========================================================================
DEFAULT_CSV = "ECDICT/ecdict.csv"

# 牌组：文件名 -> 匹配条件（tag 字段中含该子串即归入）
# ECDICT 真实 tag：zk 中考 / gk 高考 / cet4 / cet6 / ky 考研 / ielts / toefl / gre
DECK_TAGS = {
    "gk": "gk",
    "cet4": "cet4",
    "cet6": "cet6",
    "kaoyan": "ky",
    "ielts": "ielts",
    "toefl": "toefl",
    "gre": "gre",
}
FREQ_DECK = "freq"
FREQ_TOP = 5000

FORM_KEYS = ["p", "d", "i", "3", "r", "t", "s", "0"]
FORM_LABEL = {
    "p": "过去式", "d": "过去分词", "i": "现在分词",
    "3": "第三人称", "r": "比较级", "t": "最高级",
    "s": "复数", "0": "原型",
}

# 设备端翻译显示上限：过长释义既显示不下也会让翻页器切分出行列表撑爆 RAM
MAX_TRANS = 512

# ECDICT 源数据把个别 IPA 音素误编码成私有使用区(PUA, U+E000 区)字符，例如把
# /ɪ/ 写成 U+E143（常见于 amphitheatres/aperitifs/awning 等）。字库覆盖区间
# （PHON_RANGES）只有真实 IPA codepoint，不含 PUA，设备端会渲染成空白。
# 构建时映射回字库已覆盖的真实字符即可，无需重建字库。
PUA_PHON_FIX = {
    "\ue143": "\u026a",  # U+E143 -> /ɪ/
}


def fix_pua_phonetic(s):
    if not s:
        return s
    for k, v in PUA_PHON_FIX.items():
        s = s.replace(k, v)
    return s


def clean_text(s):
    if not s:
        return ""
    s = s.replace("\\n", "\n").replace("\r", " ").replace("\n", " ")
    return s.strip()


def parse_exchange(ex):
    forms = {}
    if not ex:
        return forms
    for seg in ex.split("/"):
        if ":" not in seg:
            continue
        t, w = seg.split(":", 1)
        t = t.strip()
        w = w.strip()
        if t and w:
            forms[t] = w
    return forms


def collect(csv_path, use_freq):
    records = {}
    deck_words = {n: [] for n in DECK_TAGS}
    freq_pairs = []
    tag_of = {}

    print("读取 %s ..." % csv_path)
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        n = 0
        kept = 0
        for row in reader:
            n += 1
            word = (row.get("word") or "").strip()
            if not word:
                continue
            wl = word.lower()
            try:
                wl.encode("ascii")
            except UnicodeEncodeError:
                continue
            tag = (row.get("tag") or "")
            frq = 0
            try:
                frq = int(row.get("frq") or 0)
            except ValueError:
                frq = 0
            keep = False
            for name, subtag in DECK_TAGS.items():
                if subtag in tag:
                    deck_words[name].append(wl)
                    keep = True
            if use_freq and 0 < frq <= FREQ_TOP:
                freq_pairs.append((frq, wl))
                keep = True
            if not keep:
                continue
            kept += 1
            tag_of[wl] = tag.strip()
            if wl in records:
                continue
            records[wl] = {
                "phonetic": fix_pua_phonetic(clean_text(row.get("phonetic"))),
                "translation": clean_text(row.get("translation")),
                "forms": parse_exchange(row.get("exchange")),
                "frq": frq,
            }
    print("  扫描 %d 行，收录 %d 词" % (n, kept))
    return records, deck_words, freq_pairs, tag_of


def _utf8_clip(data, n):
    """把 UTF-8 字节串截到至多 n 字节且不切在多字节字符中间。
    data 必须是合法 UTF-8；截断点若刚好落在一个字符中间，decode 会失败，
    从 n 开始逐字节回退直到能严格解码（最多回退一个编码 ≤3/4 字节的字符）。"""
    if len(data) <= n:
        return data
    cut = n
    while cut > 0:
        try:
            data[:cut].decode("utf-8")
            break
        except UnicodeDecodeError:
            cut -= 1
    return data[:cut]


def _pack_record(rec, tag):
    # 音标含 IPA/希腊/西里尔字符，必须按 UTF-8 存（ASCII replace 会把符号变成 '?'）；
    # 设备端按 UTF-8 解码，字库已覆盖对应区间（见 PHON_RANGES）。
    phon = _utf8_clip(rec["phonetic"].encode("utf-8"), 255)
    tagb = tag.encode("ascii", "replace")[:255]
    form_items = [(k, rec["forms"][k]) for k in FORM_KEYS if k in rec["forms"]]
    trans = _utf8_clip(rec["translation"].encode("utf-8"), MAX_TRANS)

    out = bytearray()
    out += bytes([len(phon)])
    out += phon
    out += bytes([len(tagb)])
    out += tagb
    out += bytes([len(form_items)])
    for k, w in form_items:
        wb = w.lower().encode("ascii", "replace")[:63]
        out += bytes([ord(k)])
        out += bytes([len(wb)])
        out += wb
    trans_off = len(out)
    out += struct.pack("<H", len(trans))
    out += trans
    return bytes(out), trans_off


def _ensure_unknown(out_dir):
    """生词本由设备端累积，脚本只负责在缺失时建空文件，绝不覆盖已有内容。"""
    decks_dir = os.path.join(out_dir, "decks")
    prog_dir = os.path.join(out_dir, "progress")
    os.makedirs(decks_dir, exist_ok=True)
    os.makedirs(prog_dir, exist_ok=True)
    up_deck = os.path.join(decks_dir, "unknown.bin")
    up_prog = os.path.join(prog_dir, "unknown.bin")
    if not os.path.exists(up_deck):
        with open(up_deck, "wb") as f:
            f.write(b"")
    if not os.path.exists(up_prog):
        with open(up_prog, "wb") as f:
            f.write(bytes(4))


def build_dict(out_dir, csv_path, use_freq, force):
    masters = ["master.entryoff", "master.index", "master.data",
               "master.troff", "master.dir"]
    master_paths = [os.path.join(out_dir, m) for m in masters]

    if not os.path.exists(csv_path):
        # 不检查的话 _mtime 返回 0，增量分支会把词库静默跳过、构建看似成功
        print("错误: 找不到词库源 %s" % csv_path)
        print("请把 ECDICT 的 ecdict.csv 放到该路径（或修改 build_sd.py 顶部 DEFAULT_CSV）")
        sys.exit(1)

    # 增量：csv 未变化且 master 齐全 → 整段跳过
    if not force and all(os.path.exists(p) for p in master_paths):
        csv_mt = _mtime(csv_path)
        if csv_mt <= max(_mtime(p) for p in master_paths):
            _ensure_unknown(out_dir)
            print("词库无需更新（%s 未变化），跳过" % os.path.basename(csv_path))
            return

    records, deck_words, freq_pairs, tag_of = collect(csv_path, use_freq)
    if not records:
        print("错误：没有收录任何词条，检查 CSV 路径")
        sys.exit(1)

    words = sorted(records.keys())
    N = len(words)
    index_of = {w: i for i, w in enumerate(words)}
    print("  总词条 %d" % N)

    index_block = bytearray()
    entry_off = bytearray()
    data_block = bytearray()
    troff_arr = bytearray()
    first_letter = [-1] * 26
    for i, w in enumerate(words):
        fl = ord(w[0]) - 97
        if 0 <= fl < 26 and first_letter[fl] < 0:
            first_letter[fl] = i
    last = N
    for k in range(25, -1, -1):
        if first_letter[k] < 0:
            first_letter[k] = last
        else:
            last = first_letter[k]

    for w in words:
        wb = w.encode("ascii")
        entry_off += struct.pack("<I", len(index_block))
        index_block += struct.pack("<H", len(wb))
        index_block += wb
        dataoff = len(data_block)
        index_block += struct.pack("<I", dataoff)
        rec_bytes, toff = _pack_record(records[w], tag_of.get(w, ""))
        data_block += rec_bytes
        troff_arr += struct.pack("<I", dataoff + toff)
    dir_arr = bytearray()
    for k in range(26):
        dir_arr += struct.pack("<I", first_letter[k])
    dir_arr += struct.pack("<I", N)

    os.makedirs(out_dir, exist_ok=True)
    for name, blob in (("master.entryoff", entry_off),
                       ("master.index", index_block),
                       ("master.data", data_block),
                       ("master.troff", troff_arr),
                       ("master.dir", dir_arr)):
        with open(os.path.join(out_dir, name), "wb") as f:
            f.write(blob)
    print("  写出 master.* (words=%d)" % N)

    decks_dir = os.path.join(out_dir, "decks")
    prog_dir = os.path.join(out_dir, "progress")
    os.makedirs(decks_dir, exist_ok=True)
    os.makedirs(prog_dir, exist_ok=True)

    def write_deck(name, wordlist, preserve=False):
        # preserve=True（仅 unknown）：设备端会追加，脚本不覆盖已有内容
        deck_path = os.path.join(decks_dir, "%s.bin" % name)
        prog_path = os.path.join(prog_dir, "%s.bin" % name)
        if preserve and os.path.exists(deck_path) and os.path.getsize(deck_path) > 0:
            return
        uniq = []
        seen = set()
        for w in wordlist:
            if w not in seen and w in index_of:
                seen.add(w)
                uniq.append(w)
        uniq.sort(key=lambda w: records[w]["frq"])
        idxs = [index_of[w] for w in uniq]
        with open(deck_path, "wb") as f:
            f.write(struct.pack("<%dI" % len(idxs), *idxs))
        with open(prog_path, "wb") as f:
            f.write(bytes(4 + len(idxs) * 5))
        print("  牌组 %-8s %d 词" % (name, len(idxs)))

    for name, wl in deck_words.items():
        write_deck(name, wl)
    if freq_pairs:
        fp = [w for _, w in sorted(freq_pairs, key=lambda x: x[0])]
        write_deck(FREQ_DECK, fp)

    _ensure_unknown(out_dir)
    print("  牌组 unknown  (空/保留，生词本)")


# ==========================================================================
# 主流程
# ==========================================================================
def main():
    force = "--force" in sys.argv[1:]
    out_dir = OUT_DIR
    os.makedirs(out_dir, exist_ok=True)

    print("=" * 52)
    print("构建 SD 卡镜像 → %s/" % out_dir)
    print("=" * 52)

    print("\n[1/3] 字库...")
    build_fonts(os.path.join(out_dir, "fonts"), force)

    print("\n[2/3] 书籍...")
    build_books(out_dir, force)

    print("\n[3/3] 背单词词库...")
    build_dict(os.path.join(out_dir, DICT_SUB), DEFAULT_CSV, True, force)

    print("\n" + "=" * 52)
    print("构建完成! 输出目录: %s/" % out_dir)
    print("把该目录下的内容复制到 FAT32 SD 卡根目录即可：")
    print("  /fonts/  ← 字库")
    print("  /books/  ← 书籍 + 页索引")
    print("  /books.map ← 文件名映射")
    print("  /dict/   ← 背单词词库")


if __name__ == "__main__":
    main()
