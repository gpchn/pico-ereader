"""
vocab.py — Pico 背单词子系统（查词 / 单词卡 / 生词本）

数据来自 PC 端 build_sd.py 生成的 /sd/dict/：
  master.entryoff / master.index / master.troff / master.data / master.dir  主词库（二分查找）
  decks/<name>.bin    u32[M] 牌组单词在 master 中的下标（按学习顺序）
  progress/<name>.bin 4 字节 counter + 每词 1 字节 box + 4 字节 due（Leitner 间隔重复）
  unknown.bin         生词本（设备端追加）

翻译文本在 PC 端按 MAX_TRANS=512 字节截断（UTF-8 字符边界），设备端翻页器
只按字符数折行，超长释义会切出大量行撑爆 RAM；本模块读取时直接 decode。

交互（只有 3 个按键，无键盘）：
主页即背单词界面：牌组列表，末尾挂「电子书」「切换字体」「按键说明」子菜单
二级菜单（牌组内）：顺序背 / 乱序背 / 查看进度（生词本另有清空）；长按「上」统一返回上级
单词卡正背面按键一致：上短=不认识，下短=认识，OK短=切换正背面，OK长=加删生词本，上长按=返回
长按「上」返回：单词卡/进度页/二级菜单均适用

输入统一使用 app.py 创建的全局 Input 实例：本模块任何地方都不得再新建 Input，
否则 pin.irq() 会覆盖全局 Input 的 IRQ，导致返回主页后按键失效。
"""
import os
import struct
import time
import random

import reader
import menu

DICT_BASE = "/sd/dict"
DEBOUNCE = 30
HOLD_MS = 400

# 进度文件分块读取的条目数（内存上界 = _PROG_CHUNK*5 字节，避免大牌组 MemoryError）
_PROG_CHUNK = 1024

FORM_LABEL = {
    "p": "过去式", "d": "过去分词", "i": "现在分词",
    "3": "三单", "r": "比较级", "t": "最高级",
    "s": "复数", "0": "原型",
}

INTERVALS = [1, 1, 3, 7, 15, 31]  # 按 box 等级决定再过多少"次复习"到期

# 牌组显示名（菜单用中文，避免英文缩写 + 全角渲染）
DECK_LABELS = {
    "gk": "高考",
    "cet4": "四级",
    "cet6": "六级",
    "kaoyan": "考研",
    "ielts": "雅思",
    "toefl": "托福",
    "gre": "GRE(研)",
    "freq": "高频词",
    "unknown": "生词本",
}

# 主菜单固定显示的分级（其余分级收进「更多分级」二级菜单）
_PRIMARY_DECKS = ("gk", "cet4", "unknown")


# --------------------------------------------------------------------------
# 渲染辅助
# --------------------------------------------------------------------------
def _make_blitter(display, FW, FH, FB):
    import framebuf
    buf = bytearray(FB)
    fb = framebuf.FrameBuffer(buf, FW, FH, framebuf.MONO_VLSB)

    def blit(glyph, x, y):
        if x + FW > 96 or y + FH > 48:
            return
        buf[:] = glyph
        display.blit(fb, x, y, -1)

    return blit


def _draw_char8(display, ch, x, y, color):
    # 8px 点阵（与 menu._FONT8_DATA 同源），用于 ASCII，避免 CJK 字体把英文渲染成全角
    o = (ord(ch) - 0x20) * 8
    data = menu._FONT8_DATA
    if o < 0 or o + 8 > len(data):
        return
    for row in range(8):
        b = data[o + row]
        if b == 0:
            continue
        for col in range(8):
            if b & (0x80 >> col):
                display.pixel(x + col, y + row, color)


# 8x8 对号位图（✓ U+2713 不在字库覆盖范围，自绘）
_CHECK_BITS = bytes([
    0x00, 0x02, 0x06, 0x0C, 0x18, 0xF8, 0xE0, 0x00,
])


def _draw_check(display, x, y, color=1):
    for row in range(8):
        b = _CHECK_BITS[row]
        if b == 0:
            continue
        for col in range(8):
            if b & (0x80 >> col):
                display.pixel(x + col, y + row, color)


def _str_w(s, FW):
    # 按渲染规则计算字符串像素宽（ASCII 8px，中文 FW）
    w = 0
    for ch in s:
        cp = ord(ch)
        w += 8 if 0x20 <= cp <= 0x7E else FW
    return w


# 复用缓冲：draw_str 每帧调用多次，避免重复分配 bytearray/FrameBuffer/临时 bytes
_str_buf = None
_str_fb = None
_str_FW = _str_FH = _str_FB = -1


def draw_str(display, s, font_path, FW, FH, FB, x, y, invert=False):
    import framebuf
    global _str_buf, _str_fb, _str_FW, _str_FH, _str_FB
    if invert:
        display.fill_rect(x, y, 96 - x, FH, 1)
    cx = x
    y8 = y + (FH - 8) // 2
    if _str_FB != FB or _str_FW != FW or _str_FH != FH:
        _str_buf = bytearray(FB)
        _str_fb = framebuf.FrameBuffer(_str_buf, FW, FH, framebuf.MONO_VLSB)
        _str_FW, _str_FH, _str_FB = FW, FH, FB
    buf = _str_buf
    fb = _str_fb
    for ch in s:
        cp = ord(ch)
        if 0x20 <= cp <= 0x7E:
            # ASCII 走 8px 点阵
            _draw_char8(display, ch, cx, y8, 0 if invert else 1)
            cx += 8
        else:
            # 中文走当前字库
            glyph = reader._get_glyph(font_path, ch, FB)
            if invert:
                for j in range(FB):
                    buf[j] = glyph[j] ^ 0xFF
            else:
                buf[:] = glyph
            if cx + FW <= 96:
                display.blit(fb, cx, y, -1)
            cx += FW


class Pager:
    """把长文本按字符宽度折行、分页，在 96x48 上显示。
    英文/数字等 ASCII 走内置 8px 点阵（半角），中文走当前字库（全角），
    这样单词卡/释义/提示里的英文不会撑成「全角」。
    set_text 支持显式 '\n' 换行：段内按像素宽度折行，段之间强制换行。"""

    def __init__(self, display, font_path):
        self.display = display
        self.set_font(font_path)
        self.pad = 0  # 底部预留像素（单词卡角落操作提示区）
        self.pages = []
        self.pi = 0

    def set_font(self, font_path):
        meta = reader._load_font(font_path)
        self.font_path = font_path
        self.FW = self.FH = 12 if meta['char_bytes'] == 24 else 16
        self.FB = meta['char_bytes']
        self.COLS = 96 // self.FW
        self.ROWS = 48 // self.FH
        self._blit = _make_blitter(self.display, self.FW, self.FH, self.FB)

    def _cw(self, ch):
        # ASCII 半角 8px，其余（CJK/全角）占 FW
        return 8 if 0x20 <= ord(ch) <= 0x7E else self.FW

    def fit_line(self, s):
        """返回能在 96px 宽内完整显示的最长前缀（供 draw_str 截断超长行）。"""
        w = 0
        for i, ch in enumerate(s):
            w += self._cw(ch)
            if w > 96:
                return s[:i]
        return s

    def set_text(self, text):
        lines = []
        for para in text.split('\n'):
            if not para:
                lines.append('')
                continue
            line = ''
            w = 0
            for ch in para:
                cw = self._cw(ch)
                if line and w + cw > 96:
                    lines.append(line)
                    line = ''
                    w = 0
                line += ch
                w += cw
            lines.append(line)
        if not lines:
            lines = ['']
        rows = self.ROWS - (self.pad + self.FH - 1) // self.FH
        if rows < 1:
            rows = 1
        self.pages = [lines[i:i + rows] for i in range(0, len(lines), rows)]
        if not self.pages:
            self.pages = [['']]
        self.pi = 0

    def show(self):
        self.display.fill(0)
        y8 = (self.FH - 8) // 2
        for r, line in enumerate(self.pages[self.pi]):
            y = r * self.FH
            x = 0
            for ch in line:
                if 0x20 <= ord(ch) <= 0x7E:
                    _draw_char8(self.display, ch, x, y + y8, 1)
                    x += 8
                else:
                    self._blit(reader._get_glyph(self.font_path, ch, self.FB), x, y)
                    x += self.FW
        self.display.show()

    def prev(self):
        if self.pi > 0:
            self.pi -= 1
            self.show()

    def next(self):
        if self.pi < len(self.pages) - 1:
            self.pi += 1
            self.show()


# --------------------------------------------------------------------------
# 按键输入
# --------------------------------------------------------------------------
class Input:
    """边沿锁存的按键输入：用 IRQ 捕捉下降沿，任何长度的短按都不会被轮询间隔漏掉。
    poll() 每次最多返回一个事件 ('up'|'down'|'ok', 'short'|'long')，无事件返回 None。

    旧实现 _poll 只在调用瞬间采样按键电平，若一次短按在两次轮询之间完成就会被漏掉，
    表现为「有时不灵敏」。这里改为中断锁存：按下即记录时间戳，poll() 据此判定
    short/long 并在松开时补发 short，因此再短的点击也不会丢失。

    注意：全局只应存在一个 Input 实例（app.py 创建），本模块复用，绝不再新建。"""

    def __init__(self, up, down, ok, hold_ms=HOLD_MS):
        self.hold_ms = hold_ms
        self.b = {'up': up, 'down': down, 'ok': ok}
        self.down_since = {}
        self.long_emitted = set()
        self.last_irq = {}
        for name, pin in self.b.items():
            pin.irq(self._irq(name), pin.IRQ_FALLING)

    def _irq(self, name):
        def h(_):
            now = time.ticks_ms()
            last = self.last_irq.get(name)
            if last is not None and time.ticks_diff(now, last) < DEBOUNCE:
                return  # 去抖：忽略 30ms 内的重复下降沿
            self.last_irq[name] = now
            self.down_since[name] = now
        return h

    def poll(self):
        now = time.ticks_ms()
        ev = None
        for name, pin in self.b.items():
            s = self.down_since.get(name)
            if s is None:
                continue
            if pin.value() == 0:
                if name not in self.long_emitted and time.ticks_diff(now, s) >= self.hold_ms:
                    self.long_emitted.add(name)
                    ev = (name, 'long')
            else:
                if name not in self.long_emitted:
                    ev = (name, 'short')
                del self.down_since[name]
                self.long_emitted.discard(name)
        return ev

    def wait(self):
        """阻塞到拿到一个事件（带极短让出，避免空转）。"""
        while True:
            a = self.poll()
            if a is not None:
                return a
            time.sleep_ms(8)

    def clear(self):
        """清空尚未消费的事件（菜单切换 / 进入查词模式时调用）。
        保留 last_irq 去抖时间戳，避免清空后紧接着的按键绕过去抖。"""
        self.down_since.clear()
        self.long_emitted.clear()


# --------------------------------------------------------------------------
# 主词库
# --------------------------------------------------------------------------
class Dictionary:
    def __init__(self, base=DICT_BASE):
        self.base = base
        self._off_f = open(base + "/master.entryoff", "rb")
        self._idx_f = open(base + "/master.index", "rb")
        self._dat_f = open(base + "/master.data", "rb")
        self._tr_f = open(base + "/master.troff", "rb")
        self.N = os.stat(base + "/master.entryoff")[6] // 4
        d = open(base + "/master.dir", "rb").read(27 * 4)
        self._dir = list(struct.unpack("<27I", d))

    def close(self):
        for f in (self._off_f, self._idx_f, self._dat_f, self._tr_f):
            try:
                f.close()
            except Exception:
                pass

    def _trans_off(self, m):
        self._tr_f.seek(m * 4)
        return struct.unpack("<I", self._tr_f.read(4))[0]

    def _trans_at(self, m):
        # O(1) 直取翻译：跳过音标/词性/词形，省一次整记录解析
        off = self._trans_off(m)
        self._dat_f.seek(off)
        tl = struct.unpack("<H", self._dat_f.read(2))[0]
        return self._dat_f.read(tl).decode('utf-8', 'replace')

    def _rec_full(self, m):
        # 翻译走 troff；词形变化走 dataoff（跳过音标/词性），仅 reveal 时才需要
        trans = self._trans_at(m)
        off = self._entry_off(m)
        self._idx_f.seek(off)
        ln = struct.unpack("<H", self._idx_f.read(2))[0]
        self._idx_f.read(ln)
        dataoff = struct.unpack("<I", self._idx_f.read(4))[0]
        self._dat_f.seek(dataoff)
        pl = struct.unpack("<B", self._dat_f.read(1))[0]
        self._dat_f.read(pl)
        tl = struct.unpack("<B", self._dat_f.read(1))[0]
        self._dat_f.read(tl)
        nf = struct.unpack("<B", self._dat_f.read(1))[0]
        forms = []
        for _ in range(nf):
            k = struct.unpack("<B", self._dat_f.read(1))[0]
            l = struct.unpack("<B", self._dat_f.read(1))[0]
            w = self._dat_f.read(l).decode('ascii', 'replace')
            forms.append((chr(k), w))
        return {'word': '', 'phonetic': '', 'tag': '',
                'forms': forms, 'translation': trans}

    def _entry_off(self, m):
        self._off_f.seek(m * 4)
        return struct.unpack("<I", self._off_f.read(4))[0]

    def _word_at(self, m):
        off = self._entry_off(m)
        self._idx_f.seek(off)
        ln = struct.unpack("<H", self._idx_f.read(2))[0]
        return self._idx_f.read(ln).decode('ascii')

    def _phon_at(self, m):
        # 只读音标字段（UTF-8，含 IPA 符号），不解析整条记录
        off = self._entry_off(m)
        self._idx_f.seek(off)
        ln = struct.unpack("<H", self._idx_f.read(2))[0]
        self._idx_f.read(ln)  # 跳过 word
        dataoff = struct.unpack("<I", self._idx_f.read(4))[0]
        self._dat_f.seek(dataoff)
        pl = struct.unpack("<B", self._dat_f.read(1))[0]
        return self._dat_f.read(pl).decode('utf-8', 'replace')

    def _index_of(self, word):
        w = word.strip().lower()
        try:
            w.encode('ascii')
        except UnicodeEncodeError:
            return -1
        if not w:
            return -1
        fl = ord(w[0]) - 97
        if 0 <= fl < 26:
            lo = self._dir[fl]
            hi = self._dir[fl + 1] - 1
        else:
            lo, hi = 0, self.N - 1
        while lo <= hi:
            m = (lo + hi) // 2
            ww = self._word_at(m)
            if ww == w:
                return m
            elif ww < w:
                lo = m + 1
            else:
                hi = m - 1
        return -1


# --------------------------------------------------------------------------
# 牌组 + 间隔重复
# --------------------------------------------------------------------------
class Deck:
    # 进度文件布局：u32 counter + 每词 [u8 box][u32 due]（共 5 字节）
    # 全部按 index 定点读写，绝不把整副牌组载入 RAM（大牌组如 gre 有 7500+ 词，
    # 整块读入会触发 MemoryError）。
    def __init__(self, dictionary, name):
        self.d = dictionary
        self.name = name
        base = getattr(dictionary, "base", DICT_BASE)
        self.idx_path = base + "/decks/" + name + ".bin"
        self.prog_path = base + "/progress/" + name + ".bin"
        self._idx_f = open(self.idx_path, "rb")
        self.M = os.stat(self.idx_path)[6] // 4
        need = 4 + self.M * 5
        try:
            sz = os.stat(self.prog_path)[6]
        except Exception:
            sz = 0
        if sz < need:
            with open(self.prog_path, "wb") as f:
                f.write(bytes(need))
        self._p_f = open(self.prog_path, "r+b")

    def close(self):
        try:
            self._idx_f.close()
        except Exception:
            pass
        try:
            self._p_f.close()
        except Exception:
            pass

    def index_at(self, i):
        self._idx_f.seek(i * 4)
        return struct.unpack("<I", self._idx_f.read(4))[0]

    def head(self, i):
        # 单词 + 音标（音标走定点小读 _phon_at，只读 phon 字段，不解析整条记录）——用于词卡正面
        mi = self.index_at(i)
        return {'word': self.d._word_at(mi), 'phonetic': self.d._phon_at(mi),
                'translation': '', 'forms': [], 'tag': ''}

    def full(self, i):
        # 单词 + 翻译 + 词形变化——仅 reveal 时调用
        mi = self.index_at(i)
        rec = self.d._rec_full(mi)
        rec['word'] = self.d._word_at(mi)
        return rec

    def _read_prog(self, i):
        self._p_f.seek(4 + i * 5)
        b = self._p_f.read(5)
        return b[0], struct.unpack("<I", b[1:5])[0]

    def _write_prog(self, i, box, due):
        self._p_f.seek(4 + i * 5)
        self._p_f.write(bytes([box]))
        self._p_f.write(struct.pack("<I", due))

    def _get_counter(self):
        self._p_f.seek(0)
        return struct.unpack("<I", self._p_f.read(4))[0]

    def _set_counter(self, c):
        self._p_f.seek(0)
        self._p_f.write(struct.pack("<I", c))

    def is_due(self, i):
        box, due = self._read_prog(i)
        return box == 0 or due <= self._get_counter()

    def _prog_stats(self):
        """分块读取进度文件，返回 (due_count, boxes 分布)。
        大牌组（如 gre 7500+ 词）整块读入会一次申请 ~37KB 内存触发 MemoryError，
        这里按 _PROG_CHUNK 条固定大小分块统计，内存占用有上界。"""
        c = self._get_counter()
        boxes = [0] * 6
        due = 0
        if self.M <= 0:
            return due, boxes
        chunk_bytes = _PROG_CHUNK * 5
        off = 4
        total = 4 + self.M * 5
        while off < total:
            self._p_f.seek(off)
            data = self._p_f.read(chunk_bytes)
            if not data:
                break
            n = len(data) // 5
            for k in range(n):
                base = k * 5
                b = data[base]
                if b >= len(boxes):
                    b = 0
                boxes[b] += 1
                if b == 0 or struct.unpack_from("<I", data, base + 1)[0] <= c:
                    due += 1
            off += n * 5
            if n < _PROG_CHUNK:
                break
        return due, boxes

    def due_count(self):
        due, _ = self._prog_stats()
        return due

    def rate(self, i, known):
        c = self._get_counter() + 1
        self._set_counter(c)
        box, _ = self._read_prog(i)
        box = min(box + 1, 5) if known else max(box - 1, 0)
        due = c + (INTERVALS[box] if box < len(INTERVALS) else 31)
        self._write_prog(i, box, due)
        _mark_dirty(self.name)


# --------------------------------------------------------------------------
# 主页到期数缓存（脏标记）：只有评分/生词本变更过的牌组才重算 due_count
# --------------------------------------------------------------------------
_due_cache = {}
_dirty = set()


def _mark_dirty(name):
    _dirty.add(name)


# --------------------------------------------------------------------------
# 生词本（unknown 牌组）维护
# --------------------------------------------------------------------------
def add_unknown(word, dic=None):
    own = dic is None
    if own:
        try:
            dic = Dictionary()
        except Exception:
            return False
    try:
        i = dic._index_of(word)
        if i < 0:
            return False
        path = DICT_BASE + "/decks/unknown.bin"
        data = open(path, "rb").read()
        existing = set(struct.unpack("<%dI" % (len(data) // 4), data)) if data else set()
        if i in existing:
            return True
        with open(path, "ab") as f:
            f.write(struct.pack("<I", i))
        ppath = DICT_BASE + "/progress/unknown.bin"
        p = bytearray(open(ppath, "rb").read())
        p += bytes([0])
        p += struct.pack("<I", 0)
        with open(ppath, "wb") as f:
            f.write(p)
        _mark_dirty("unknown")
        return True
    finally:
        if own and dic is not None:
            dic.close()


def is_in_unknown(word, dic=None):
    """单词是否已在生词本。"""
    own = dic is None
    if own:
        try:
            dic = Dictionary()
        except Exception:
            return False
    try:
        i = dic._index_of(word)
        if i < 0:
            return False
        path = DICT_BASE + "/decks/unknown.bin"
        data = open(path, "rb").read()
        if not data:
            return False
        return i in set(struct.unpack("<%dI" % (len(data) // 4), data))
    finally:
        if own and dic is not None:
            dic.close()


def remove_unknown(word, dic=None):
    """按单词从生词本删除（不存在则忽略）。"""
    own = dic is None
    if own:
        try:
            dic = Dictionary()
        except Exception:
            return
    try:
        i = dic._index_of(word)
        if i < 0:
            return
        path = DICT_BASE + "/decks/unknown.bin"
        data = open(path, "rb").read()
        if not data:
            return
        arr = list(struct.unpack("<%dI" % (len(data) // 4), data))
        if i not in arr:
            return
        _remove_unknown(arr.index(i))
    finally:
        if own and dic is not None:
            dic.close()


def _toggle_unknown(display, dic, word):
    """长按 OK：已在生词本就删除，否则添加。返回 'added' / 'removed'。"""
    if is_in_unknown(word, dic):
        remove_unknown(word, dic)
        _show_msg(display, "已删生词本")
        return "removed"
    add_unknown(word, dic)
    _show_msg(display, "已加生词本")
    return "added"


def _remove_unknown(idx):
    path = DICT_BASE + "/decks/unknown.bin"
    data = open(path, "rb").read()
    arr = list(struct.unpack("<%dI" % (len(data) // 4), data))
    if idx < 0 or idx >= len(arr):
        return
    arr.pop(idx)
    with open(path, "wb") as f:
        f.write(struct.pack("<%dI" % len(arr), *arr))
    ppath = DICT_BASE + "/progress/unknown.bin"
    p = bytearray(open(ppath, "rb").read())
    counter = struct.unpack("<I", p[:4])[0]
    new = bytearray(struct.pack("<I", counter))
    new += p[4:4 + idx * 5]
    new += p[4 + (idx + 1) * 5:]
    with open(ppath, "wb") as f:
        f.write(new)
    _mark_dirty("unknown")


def _clear_unknown():
    with open(DICT_BASE + "/decks/unknown.bin", "wb") as f:
        f.write(b"")
    with open(DICT_BASE + "/progress/unknown.bin", "wb") as f:
        f.write(bytes(4))
    _mark_dirty("unknown")


# --------------------------------------------------------------------------
# 通用提示 / 释义辅助
# --------------------------------------------------------------------------
def _show_msg(display, s):
    p = Pager(display, menu.current_font_path())
    p.set_text(s)
    p.show()


# --------------------------------------------------------------------------
# 主页菜单
# --------------------------------------------------------------------------
def _home(display, inp, dic):
    # 顶层菜单即「背单词界面」：主菜单固定保留 高考/四级/生词本，
    # 其余分级收进「更多分级」二级菜单，末尾挂「电子书」「切换字体」
    if dic is None:
        files = []  # 词库不可用：降级为仅电子书/字体/帮助
    else:
        try:
            files = sorted([f for f in os.listdir(DICT_BASE + "/decks") if f.endswith(".bin")])
        except OSError:
            files = []
    names = [f[:-4] for f in files]
    primary = [n for n in _PRIMARY_DECKS if n in names]
    secondary = [n for n in names if n not in primary]
    # 只重算进度发生变化的牌组（学习/生词本修改会标记 _dirty）
    for nm in names:
        if nm in _due_cache and nm not in _dirty:
            continue
        dk = None
        try:
            dk = Deck(dic, nm)
            _due_cache[nm] = dk.due_count()
        except Exception:
            _due_cache[nm] = 0
        finally:
            if dk is not None:
                dk.close()
    _dirty.clear()
    items = primary + (["更多分级"] if secondary else []) + ["电子书", "切换字体", "按键说明"]
    sub_entries = ("电子书", "切换字体", "更多分级", "按键说明")
    sel = 0
    pager = Pager(display, menu.current_font_path())
    while True:
        display.fill(0)
        start = (sel // pager.ROWS) * pager.ROWS
        for r in range(pager.ROWS):
            idx = start + r
            if idx >= len(items):
                break
            name = items[idx]
            y = r * pager.FH
            if name in sub_entries:
                label = name
            else:
                label = "%s(%d)" % (DECK_LABELS.get(name, name), _due_cache.get(name, 0))
            if idx == sel:
                display.fill_rect(0, y, 96, pager.FH, 1)
                draw_str(display, label, pager.font_path, pager.FW, pager.FH,
                          pager.FB, 0, y, invert=True)
            else:
                draw_str(display, label, pager.font_path, pager.FW, pager.FH,
                          pager.FB, 0, y)
        display.show()
        a = inp.poll()
        if a is None:
            time.sleep_ms(8)
            continue
        if a[0] == 'up' and a[1] == 'short':
            sel = (sel - 1) % len(items)
        elif a[0] == 'down' and a[1] == 'short':
            sel = (sel + 1) % len(items)
        elif a[0] == 'ok' and a[1] == 'short':
            name = items[sel]
            if name == "电子书":
                return "books"
            if name == "切换字体":
                return "font"
            if name == "更多分级":
                return "more"
            if name == "按键说明":
                return "help"
            return ("deck", name)


def _more_decks(display, inp, dic):
    """二级菜单：不常用的分级（六级/考研/雅思/托福/GRE/高频词）牌组列表，
    返回选中的牌组名；返回 None 表示返回上级。"""
    if dic is None:
        return None
    try:
        files = sorted([f for f in os.listdir(DICT_BASE + "/decks") if f.endswith(".bin")])
    except OSError:
        files = []
    names = [f[:-4] for f in files]
    secondary = [n for n in names if n not in _PRIMARY_DECKS]
    if not secondary:
        return None
    sel = 0
    pager = Pager(display, menu.current_font_path())
    while True:
        display.fill(0)
        start = (sel // pager.ROWS) * pager.ROWS
        for r in range(pager.ROWS):
            idx = start + r
            if idx >= len(secondary):
                break
            name = secondary[idx]
            y = r * pager.FH
            label = "%s(%d)" % (DECK_LABELS.get(name, name), _due_cache.get(name, 0))
            if idx == sel:
                display.fill_rect(0, y, 96, pager.FH, 1)
                draw_str(display, label, pager.font_path, pager.FW, pager.FH,
                          pager.FB, 0, y, invert=True)
            else:
                draw_str(display, label, pager.font_path, pager.FW, pager.FH,
                          pager.FB, 0, y)
        display.show()
        a = inp.poll()
        if a is None:
            time.sleep_ms(8)
            continue
        if a[0] == 'up' and a[1] == 'short':
            sel = (sel - 1) % len(secondary)
        elif a[0] == 'down' and a[1] == 'short':
            sel = (sel + 1) % len(secondary)
        elif a[0] == 'ok' and a[1] == 'short':
            return secondary[sel]
        elif a[0] == 'up' and a[1] == 'long':
            return None


def _show_help(display, inp, font_path):
    """按键说明：逐页列出各界面按键用法。上下翻页，OK短按/上长按返回。"""
    text = (
        "背单词主页\n"
        "上下 选择\n"
        "OK 进入\n"
        "\n"
        "二级菜单\n"
        "上下 选择\n"
        "OK 进入\n"
        "上长按 返回\n"
        "\n"
        "单词卡\n"
        "上下短 认不认识\n"
        "上长按 返回\n"
        "OK短 切换正背面\n"
        "OK长 加删生词\n"
        "\n"
        "查看进度\n"
        "上长按 返回\n"
        "\n"
        "电子书\n"
        "上下 翻页\n"
        "上长按 退出\n"
        "下长按 自动读\n"
        "OK短 书签\n"
        "OK长 加删书签\n"
        "\n"
        "书签界面\n"
        "上下 选择\n"
        "OK 跳页\n"
        "上长按 返回\n"
    )
    pager = Pager(display, font_path)
    pager.set_text(text)
    pager.show()
    while True:
        a = inp.wait()
        if a[0] == 'up' and a[1] == 'short':
            pager.prev()
        elif a[0] == 'down' and a[1] == 'short':
            pager.next()
        elif (a[0] == 'ok' and a[1] == 'short') or (a[0] == 'up' and a[1] == 'long'):
            return


# --------------------------------------------------------------------------
# 牌组列表 / 动作菜单
# --------------------------------------------------------------------------
def _action_menu(display, inp, name):
    # 二级菜单：顺序背 / 乱序背 / 查看进度（生词本另有清空）；长按「上」返回一级
    opts = [("顺序背", "study"), ("乱序背", "shuffle"), ("查看进度", "progress")]
    if name == "unknown":
        opts.append(("清空生词本", "clear"))
    n = len(opts)
    sel = 0
    pager = Pager(display, menu.current_font_path())
    rows = pager.ROWS
    while True:
        display.fill(0)
        # 窗口化渲染：条目多于一屏（生词本 4 项在 16px 屏只有 3 行）时也要可滚动
        start = (sel // rows) * rows
        for r in range(rows):
            i = start + r
            if i >= n:
                break
            label = opts[i][0]
            y = r * pager.FH
            if i == sel:
                display.fill_rect(0, y, 96, pager.FH, 1)
                draw_str(display, label, pager.font_path, pager.FW, pager.FH,
                          pager.FB, 0, y, invert=True)
            else:
                draw_str(display, label, pager.font_path, pager.FW, pager.FH,
                          pager.FB, 0, y)
        display.show()
        a = inp.poll()
        if a is None:
            time.sleep_ms(8)
            continue
        if a[0] == 'up' and a[1] == 'short':
            sel = (sel - 1) % n
        elif a[0] == 'down' and a[1] == 'short':
            sel = (sel + 1) % n
        elif a[0] == 'ok' and a[1] == 'short':
            return opts[sel][1]
        elif a[0] == 'up' and a[1] == 'long':
            # 长按「上」：返回一级菜单
            return None


def _show_progress(display, inp, dic, name, font_path):
    """查看进度：进度条 + 总词数/已学/待复习/掌握数。长按「上」返回。"""
    deck = Deck(dic, name)
    try:
        if deck.M == 0:
            _show_msg(display, "空牌组")
            time.sleep_ms(1200)
            return
        pager = Pager(display, font_path)
        FW, FH, FB = pager.FW, pager.FH, pager.FB
        M = deck.M
        due, boxes = deck._prog_stats()
        learned = M - boxes[0]  # 至少学过一次的词
        mastered = sum(boxes[3:])  # box>=3 视为已掌握
        d = display
        while True:
            d.fill(0)
            # 行0：标题 + 右对齐待复习数
            draw_str(d, DECK_LABELS.get(name, name), font_path, FW, FH, FB, 0, 0)
            srev = "复习%d" % due
            draw_str(d, srev, font_path, FW, FH, FB, 96 - _str_w(srev, FW), 0)
            # 行1：进度条（已学比例）
            by = FH
            bh = 8
            d.hline(0, by, 96, 1)          # 上边
            d.hline(0, by + bh - 1, 96, 1)  # 下边
            d.fill_rect(0, by, 1, bh, 1)    # 左边
            d.fill_rect(95, by, 1, bh, 1)   # 右边
            fw = int(96 * learned / M) if M else 0
            if fw > 2:
                d.fill_rect(1, by + 1, fw - 2, bh - 2, 1)
            # 行2：已学/总
            sy = by + bh + 2
            draw_str(d, "学%d/%d" % (learned, M), font_path, FW, FH, FB, 0, sy)
            # 行3（若放得下）：右对齐已掌握数
            ty = sy + FH
            if ty + FH <= 48:
                sm = "掌握%d" % mastered
                draw_str(d, sm, font_path, FW, FH, FB, 96 - _str_w(sm, FW), ty)
            d.show()
            a = inp.wait()
            if a[0] == 'up' and a[1] == 'long':
                return
    finally:
        deck.close()


def _deck_session(display, inp, dic, name, font_path):
    while True:
        act = _action_menu(display, inp, name)
        if act is None:
            return
        if act == "study":
            _study(display, inp, dic, name, font_path, shuffle=False)
        elif act == "shuffle":
            _study(display, inp, dic, name, font_path, shuffle=True)
        elif act == "progress":
            _show_progress(display, inp, dic, name, font_path)
        elif act == "clear":
            _clear_deck(name)


def run_vocab(display, inp):
    # 背单词主入口：顶层即牌组列表，电子书/切换字体作为子菜单返回给 app.py
    inp.clear()
    font_path = menu.current_font_path()
    if font_path is None:
        # 一个字库文件都没有：只能显示 8px 点阵，提示并返回（避免 Pager 报错卡死）
        display.fill(0)
        display.text('NO FONT', 24, 20, 1)
        display.show()
        time.sleep_ms(1500)
        return None
    # 词库缺失/损坏时降级运行（dic=None）：主页仍可用，只挂
    # 电子书/切换字体/按键说明，否则「无词库」会在主循环里无限闪屏
    try:
        dic = Dictionary()
    except Exception:
        dic = None
        _show_msg(display, "无词库")
        time.sleep_ms(1200)
    try:
        while True:
            choice = _home(display, inp, dic)
            if choice == "books":
                return "books"
            if choice == "font":
                return "font"
            if choice == "help":
                _show_help(display, inp, font_path)
                continue
            if choice == "more":
                more = _more_decks(display, inp, dic)
                if more:
                    _deck_session(display, inp, dic, more, font_path)
                continue
            if isinstance(choice, tuple) and choice[0] == "deck":
                _deck_session(display, inp, dic, choice[1], font_path)
    finally:
        if dic is not None:
            dic.close()


# --------------------------------------------------------------------------
# 学习（单词卡）
# --------------------------------------------------------------------------
def _flashcard_show(pager, rec, revealed):
    # 单词卡：上方显示单词/释义（自动折行），底部预留角落操作提示
    pager.pad = 8
    if not revealed:
        # 正面：单词 + 音标（若有），音标换行显示
        text = rec['word']
        if rec.get('phonetic'):
            text += "\n[" + rec['phonetic'] + "]"
        pager.set_text(text)
    else:
        forms = " ".join(FORM_LABEL.get(k, k) + ":" + w for k, w in rec.get('forms', []))
        txt = rec['word'] + "\n" + rec.get('translation', '')
        if forms:
            txt += "\n" + forms
        pager.set_text(txt)
    pager.show()
    # 左下角「?」= 不认识（上键）；右下角「✓」= 认识（下键）
    d = pager.display
    _draw_char8(d, '?', 0, 40, 1)
    _draw_check(d, 88, 40)
    # 图标在 pager.show() 推屏之后绘制，必须再刷新一次才会显示
    d.show()


def _fisher_yates(a):
    # MicroPython 的 random 模块没有 shuffle，手写 Fisher-Yates
    for k in range(len(a) - 1, 0, -1):
        j = random.randint(0, k)
        a[k], a[j] = a[j], a[k]


def _build_order(deck, shuffle):
    # 顺序背用 range（不占内存）；乱序背只取到期词并洗牌。
    # 到期下标用 array('i') 而非 list：MicroPython 的 list 里每个 int 都是独立
    # 堆对象，gre 等大牌组（7500+ 词）会一次吃掉 ~90KB 触发 MemoryError；
    # array 按 4 字节原生存储，同样数据只要 ~30KB。
    if shuffle:
        from array import array
        order = array('i')
        for i in range(deck.M):
            if deck.is_due(i):
                order.append(i)
        _fisher_yates(order)
        return order
    return range(deck.M)


def _study(display, inp, dic, name, font_path, shuffle=False):
    deck = Deck(dic, name)
    try:
        if deck.M == 0:
            _show_msg(display, "空牌组")
            time.sleep_ms(1200)
            return
        pager = Pager(display, font_path)
        order = _build_order(deck, shuffle)
        pos = 0
        exited = False  # 长按「上」退出/删空生词本时不显示「本组完成」
        revealed = False  # False=正面(单词)，True=背面(单词+释义)
        while pos < len(order):
            i = order[pos]
            if not deck.is_due(i):
                pos += 1
                continue
            # 单词卡正背面按键一致：
            #   上短=不认识  下短=认识  上长=返回
            #   OK短=切换正背面  OK长=加删生词本
            _flashcard_show(pager, deck.full(i) if revealed else deck.head(i), revealed)
            a = inp.wait()
            if a[0] == 'up' and a[1] == 'short':
                deck.rate(i, False)
                revealed = False
                pos += 1
            elif a[0] == 'down' and a[1] == 'short':
                deck.rate(i, True)
                revealed = False
                pos += 1
            elif a[0] == 'ok' and a[1] == 'short':
                # OK短：切换正背面
                revealed = not revealed
            elif a[0] == 'ok' and a[1] == 'long':
                # OK长：加/删生词本（不评分不翻面，留在当前词）
                w = deck.head(i)['word']
                res = _toggle_unknown(display, dic, w)
                time.sleep_ms(1000)
                if res == "removed" and name == "unknown":
                    # 从生词本删词：索引失效，重建遍历列表
                    deck.close()
                    deck = Deck(dic, name)
                    if deck.M == 0:
                        exited = True
                        break
                    order = _build_order(deck, shuffle)
                    pos = 0
                    continue
                revealed = False
            elif a[0] == 'up' and a[1] == 'long':
                # 上长按：退出学习
                exited = True
                break
        if not exited:
            _show_msg(display, "暂无到期词" if shuffle and len(order) == 0 else "本组完成")
            time.sleep_ms(1500)
    finally:
        deck.close()


# --------------------------------------------------------------------------
# 清空牌组（目前仅生词本）
# --------------------------------------------------------------------------
def _clear_deck(name):
    if name == "unknown":
        _clear_unknown()


# --------------------------------------------------------------------------
# 入口：app.py 调用 vocab.run_vocab(display, inp)
# --------------------------------------------------------------------------
