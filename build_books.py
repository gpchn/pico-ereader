"""
build_books.py — 批量处理小说，生成 SD 卡可用文件

用法:  python build_books.py

输入:  books/*.txt          (任意编码的原始小说，文件名可以是中文)
输出:  sd_card/books/       (ASCII 文件名 + .idx 索引)
       sd_card/books.map    (元数据: ASCII名|原始名)
"""

import struct
import os
import sys

BOOKS_IN = 'books'
BOOKS_OUT = 'sd_card/books'
MAP_FILE = 'sd_card/books.map'

PAGE_SIZES = [32, 18]


def process_one(txt_path, book_id):
    """处理单本小说，返回 (ascii_name, original_name)。"""
    base = os.path.basename(txt_path)
    orig_name = base
    if orig_name.lower().endswith('.txt'):
        orig_name = orig_name[:-4]

    ascii_name = 'book_%04d' % book_id
    out_txt = '%s/%s.txt' % (BOOKS_OUT, ascii_name)

    # 读取原文
    with open(txt_path, 'rb') as f:
        data = f.read()

    # 处理 BOM
    if data[:3] == b'\xef\xbb\xbf':
        data = data[3:]

    # 写出 ASCII 文件名
    with open(out_txt, 'wb') as f:
        f.write(data)

    # 为每种字号生成索引
    for pp in PAGE_SIZES:
        _build_index(data, BOOKS_OUT, ascii_name, pp)

    print('  %s ← %s' % (out_txt, base))
    return ascii_name, orig_name


def _build_index(data, out_dir, ascii_name, per_page):
    """在内存中扫描文本，生成 .idx 文件。"""
    idx_path = '%s/%s_%d.idx' % (out_dir, ascii_name, per_page)
    with open(idx_path, 'wb') as idx:
        idx.write(struct.pack('<I', 0))
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
            ch = data[i:i + ch_bytes_len].decode('utf-8', 'ignore')
            i += ch_bytes_len
            if not ch:
                continue
            if ch.isspace() or ch == '\u3000':
                if not last_was_space:
                    char_count += 1
                    last_was_space = True
            else:
                char_count += 1
                last_was_space = False
            if char_count == per_page:
                idx.write(struct.pack('<I', i))
                char_count = 0
                last_was_space = False


def main():
    os.makedirs(BOOKS_OUT, exist_ok=True)

    if not os.path.isdir(BOOKS_IN):
        print('错误: 找不到输入目录 %s/' % BOOKS_IN)
        print('请把 .txt 文件放到 %s/ 目录下' % BOOKS_IN)
        sys.exit(1)

    files = sorted([f for f in os.listdir(BOOKS_IN)
                    if f.endswith('.txt') and not f.startswith('.')])

    if not files:
        print('错误: %s/ 目录下没有 .txt 文件' % BOOKS_IN)
        sys.exit(1)

    mapping = []
    for idx, fname in enumerate(files, 1):
        txt_path = os.path.join(BOOKS_IN, fname)
        ascii_name, orig_name = process_one(txt_path, idx)
        mapping.append((ascii_name, orig_name))

    # 写出元数据
    with open(MAP_FILE, 'w', encoding='utf-8') as f:
        for ascii_name, orig_name in mapping:
            f.write('%s.txt|%s\n' % (ascii_name, orig_name))

    print('\n完成! 共处理 %d 本书' % len(mapping))
    print('输出目录: %s/' % BOOKS_OUT)
    print('元数据:   %s' % MAP_FILE)
    print('\n把 %s/ 目录和 %s 复制到 SD 卡即可。' % (os.path.dirname(BOOKS_OUT), MAP_FILE))
    print('SD 卡目录结构:')
    print('  /sd/books/      ← 所有 .txt + .idx')
    print('  /sd/books.map   ← 文件名映射')


if __name__ == '__main__':
    main()
