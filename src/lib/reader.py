import os
import time
import struct
import re
import framebuf

_FONT_CACHE = {}
_FONT_CACHE_LIMIT = 200

# 自动阅读固定滚动速度（每滚一行的时间间隔，毫秒）
AUTO_SCROLL_MS = 3000

# 按键去抖/长按判定时长（与 menu.py 一致）
DEBOUNCE = 30
HOLD_MS = 400

# 注意：区间与 build_sd.py 的 gen_codepoints() 必须完全一致（字库按区间线性寻址）。
# 0x00A0-0x02FF/0x0370-0x04FF 为音标（IPA/希腊/西里尔）区间，与 PHON_RANGES 对应；
# 0x2000-0x2070 为通用标点（—–…“”‘’ 等非全角标点），缺失会显示成空块。
_RANGES = (
    (0x20, 0x7F),
    (0x00A0, 0x0180),
    (0x0250, 0x0300),
    (0x0370, 0x0400),
    (0x0400, 0x0500),
    (0x2000, 0x2070),
    (0x3000, 0x3040),
    (0x3400, 0x4DC0),
    (0x4E00, 0xA000),
    (0xFF00, 0xFFF0),
)


def _read_exact(f, n):
    data = bytearray(f.read(n))
    while len(data) < n:
        c = f.read(n - len(data))
        if not c:
            break
        data += c
    return data


def _decode_utf8(raw):
    """宽松 UTF-8 解码（忽略非法/截断的多字节序列）。

    不能用 raw.decode('utf-8', 'ignore')：MicroPython 的 decode-ignore 对「末尾
    被截断的多字节字符」（如 .idx 用 start+256 估算边界切断的中文）仍会抛
    UnicodeError，翻页即崩。这里手工按字节解码，截断部分直接丢弃，稳定跨平台。
    """
    out = []
    n = len(raw)
    i = 0
    while i < n:
        b0 = raw[i]
        if b0 < 0x80:                      # ASCII
            out.append(chr(b0))
            i += 1
            continue
        if 0xC2 <= b0 <= 0xDF:
            ln, cp = 2, b0 & 0x1F
        elif 0xE0 <= b0 <= 0xEF:
            ln, cp = 3, b0 & 0x0F
        elif 0xF0 <= b0 <= 0xF4:
            ln, cp = 4, b0 & 0x07
        else:
            i += 1                          # 非法引导字节，丢弃
            continue
        if i + ln > n:
            break                           # 末尾截断，丢弃剩余
        ok = True
        for k in range(1, ln):
            b = raw[i + k]
            if not 0x80 <= b <= 0xBF:
                ok = False
                break
            cp = (cp << 6) | (b & 0x3F)
        if ok and not 0xD800 <= cp <= 0xDFFF:
            out.append(chr(cp))
            i += ln
        else:
            i += 1                          # 非法续接字节，丢弃当期
    return ''.join(out)


def _get_font_index(cp, num_chars):
    total = 0
    for start, end in _RANGES:
        if start <= cp < end:
            idx = total + (cp - start)
            return idx if idx < num_chars else -1
        total += end - start
    return -1


def _load_font(font_path):
    if font_path in _FONT_CACHE and 'meta' in _FONT_CACHE[font_path]:
        return _FONT_CACHE[font_path]['meta']
    with open(font_path, 'rb') as f:
        magic = _read_exact(f, 4)
        if magic[:2] != b'FN':
            raise ValueError('非字体文件: %s' % font_path)
        num_chars = struct.unpack('<I', _read_exact(f, 4))[0]
        char_bytes = struct.unpack('<H', _read_exact(f, 2))[0]
        _read_exact(f, 2)
        index_offset = struct.unpack('<I', _read_exact(f, 4))[0]
        bitmap_offset = struct.unpack('<I', _read_exact(f, 4))[0]
        _read_exact(f, 4)
        meta = {
            'magic': magic,
            'num_chars': num_chars,
            'char_bytes': char_bytes,
            'index_offset': index_offset,
            'bitmap_offset': bitmap_offset,
        }
        _FONT_CACHE.setdefault(font_path, {})['meta'] = meta
    return meta


def _get_glyph(font_path, ch, FB):
    cache = _FONT_CACHE.get(font_path)
    if cache is None:
        _load_font(font_path)
        cache = _FONT_CACHE[font_path]
    cp = ord(ch)
    glyph_cache = cache.get('glyph_cache')
    if glyph_cache is None:
        glyph_cache = {}
        cache['glyph_cache'] = glyph_cache
    if cp in glyph_cache:
        bm = glyph_cache.pop(cp)
        glyph_cache[cp] = bm
        return bm
    meta = cache['meta']
    idx = _get_font_index(cp, meta['num_chars'])
    if idx < 0:
        bm = bytes(FB)
    else:
        f = cache.get('file')
        if f is None:
            f = open(font_path, 'rb')
            cache['file'] = f
        f.seek(meta['bitmap_offset'] + idx * FB)
        bm = _read_exact(f, FB)
    glyph_cache[cp] = bm
    if len(glyph_cache) > _FONT_CACHE_LIMIT:
        oldest = next(iter(glyph_cache))
        del glyph_cache[oldest]
    return bm


class Reader:
    def __init__(self, display, txt_path, font_path, btn_up, btn_down, btn_ok, inp):
        self.display = display
        self.txt_path = txt_path
        self.font_path = font_path
        self.btn_up = btn_up
        self.btn_down = btn_down
        self.btn_ok = btn_ok
        # 复用 app.py 的全局 Input（书签界面导航用），不要在这里新建 Input 实例，
        # 否则会覆盖全局 Input 的 IRQ，导致返回主页后按键失效。
        self.inp = inp

        meta = _load_font(font_path)
        self.FW = self.FH = 12 if meta['char_bytes'] == 24 else 16
        self.FB = meta['char_bytes']
        self.COLS = 96 // self.FW
        self.ROWS = 48 // self.FH
        self.PER_PAGE = self.COLS * self.ROWS
        self._fb_buf = bytearray(self.FB)
        self._fb = framebuf.FrameBuffer(self._fb_buf, self.FW, self.FH, framebuf.MONO_VLSB)

        self._build_index()
        self.page = self._load_progress()
        if self.page >= self.total_pages:
            self.page = 0
        self._show()

    def _build_index(self):
        base = self.txt_path
        if base.lower().endswith('.txt'):
            base = base[:-4]
        self._idx_path = f'{base}_{self.PER_PAGE}.idx'
        try:
            idx_size = os.stat(self._idx_path)[6]
        except OSError:
            raise RuntimeError('NO.IDX')
        self.total_pages = idx_size // 4
        self._idx_f = None

    def _get_page_bounds(self, p):
        if self._idx_f is None:
            self._idx_f = open(self._idx_path, 'rb')
        self._idx_f.seek(p * 4)
        start = struct.unpack('<I', _read_exact(self._idx_f, 4))[0]
        if p + 1 < self.total_pages:
            end = struct.unpack('<I', _read_exact(self._idx_f, 4))[0]
        else:
            end = start + 256
        return start, end

    def _close_idx(self):
        if self._idx_f is not None:
            self._idx_f.close()
            self._idx_f = None

    def _progress_path(self):
        return self.txt_path + '.prog'

    def _load_progress(self):
        try:
            with open(self._progress_path(), 'r') as f:
                p = int(f.read().strip())
                if 0 <= p < self.total_pages:
                    return p
        except Exception:
            pass
        return 0

    def _save_progress(self):
        try:
            with open(self._progress_path(), 'w') as f:
                f.write(str(self.page))
        except Exception:
            pass

    def _show(self):
        d = self.display
        d.fill(0)
        if self.page >= self.total_pages:
            d.show()  # 越界页也推一次空屏，避免残留上一帧内容
            return
        chars = self._page_chars(self.page)
        for i, ch in enumerate(chars):
            g = _get_glyph(self.font_path, ch, self.FB)
            col = i % self.COLS
            row = i // self.COLS
            self._blit_glyph(d, g, col * self.FW, row * self.FH)
        d.show()

    def _blit_glyph(self, d, glyph_bytes, x, y):
        if x + self.FW > 96 or y + self.FH > 48:
            return
        self._fb_buf[:] = glyph_bytes
        d.blit(self._fb, x, y, -1)

    def turn_next(self):
        if self.page < self.total_pages - 1:
            self.page += 1
            self._show()

    def turn_prev(self):
        if self.page > 0:
            self.page -= 1
            self._show()

    def jump_to(self, p):
        if 0 <= p < self.total_pages:
            self.page = p
            self._show()

    def run(self):
        auto = False                      # 自动阅读开关
        self._auto_win = 0                # 自动滚动窗口的全局行号（页*ROWS + 行）
        self._auto_cache = {'page': -1, 'lines': []}  # 当前页行缓存
        auto_last = time.ticks_ms()
        self._drain_all()
        while True:
            if self.btn_up.value() == 0:
                p = self._press(self.btn_up)
                if p is None:
                    pass  # 去抖后无有效按键，忽略
                elif p == 'long':
                    # 长按「上」：立即退出阅读回书架（不等松开，避免“松开才刷新”）
                    self._save_progress()
                    self._close_idx()
                    return 'menu'
                else:
                    self.turn_prev()
                    self._save_progress()
                    if auto:
                        self._auto_win = self.page * self.ROWS
                        self._auto_cache = {'page': -1, 'lines': []}
                        auto_last = time.ticks_ms()
            if self.btn_down.value() == 0:
                p = self._press(self.btn_down)
                if p is None:
                    pass
                elif p == 'long':
                    # 长按「下」：切换自动阅读（达到阈值立即生效；随后等松开防重复触发）
                    auto = not auto
                    self._auto_win = self.page * self.ROWS
                    self._auto_cache = {'page': -1, 'lines': []}
                    self._drain(self.btn_down)
                    self._show_msg('自动阅读' if auto else '手动翻页')
                    time.sleep_ms(800)
                    self._show()
                    auto_last = time.ticks_ms()
                else:
                    self.turn_next()
                    self._save_progress()
                    if auto:
                        self._auto_win = self.page * self.ROWS
                        self._auto_cache = {'page': -1, 'lines': []}
                        auto_last = time.ticks_ms()
            if self.btn_ok.value() == 0:
                p = self._press(self.btn_ok)
                if p is None:
                    pass
                elif p == 'long':
                    # 长按 OK：添加/删除书签（先等松开，保持“一次长按只开关一次”）
                    self._drain(self.btn_ok)
                    self._toggle_bookmark()
                    auto_last = time.ticks_ms()
                else:
                    # 短按 OK：书签界面
                    self._bookmark_menu()
                    # 书签界面长按「上」返回时键仍按住且屏幕停在书签列表：
                    # 先恢复当前页，再等松开，否则残键会被判成阅读中的长按「上」
                    # → 一次长按连跳两级（先退阅读再退书架）
                    self._show()
                    self._drain_all()
                    if auto:
                        self._auto_win = self.page * self.ROWS
                        self._auto_cache = {'page': -1, 'lines': []}
                    auto_last = time.ticks_ms()
            if auto and time.ticks_diff(time.ticks_ms(), auto_last) >= AUTO_SCROLL_MS:
                self._auto_win += 1
                if not self._auto_render(self._auto_win):
                    # 滚到末页：自动关闭
                    auto = False
                    self._show()
                    self._show_msg('已到末页')
                    time.sleep_ms(800)
                    self._show()
                else:
                    # 进度同步到底行所在页
                    last_idx = self._auto_win + self.ROWS - 1
                    p = last_idx // self.ROWS
                    if p != self.page:
                        self.page = min(p, self.total_pages - 1)
                        self._save_progress()
                auto_last = time.ticks_ms()
            time.sleep_ms(15)

    def _press(self, pin, hold_ms=HOLD_MS, debounce=DEBOUNCE):
        """阻塞式判定单键：达到长按时长立即返回 'long'（键仍按住，不等松开）；
        短按则等待松开后返回 'short'；去抖后无有效按键返回 None。
        统一上/下/OK 三处的长按判定（消除重复实现）。"""
        time.sleep_ms(debounce)
        if pin.value() != 0:
            return None
        start = time.ticks_ms()
        while pin.value() == 0:
            if time.ticks_diff(time.ticks_ms(), start) >= hold_ms:
                return 'long'
            time.sleep_ms(10)
        return 'short'

    def _drain(self, pin):
        """等待指定按键松开（用于切换类动作后防止循环重复触发）。"""
        while pin.value() == 0:
            time.sleep_ms(10)

    def _drain_all(self, timeout_ms=5000):
        """进入阅读/返回阅读前等所有按键松开（带超时兜底）。
        两个用途：书架短按 OK 选书后键往往还没松开，若不排空，run() 会把这次
        持键误判成阅读中的短按 → 直接弹出书签界面；书签界面长按「上」返回阅读
        时键也仍按住，不排空会被误判成阅读中的长按「上」→ 连锁退出阅读。"""
        start = time.ticks_ms()
        while (self.btn_up.value() == 0 or self.btn_down.value() == 0
               or self.btn_ok.value() == 0):
            if time.ticks_diff(time.ticks_ms(), start) >= timeout_ms:
                break
            time.sleep_ms(10)

    def _show_msg(self, text):
        """居中显示一行提示文字（走当前字库）。"""
        d = self.display
        d.fill(0)
        chars = list(text)[:self.COLS]
        n = len(chars)
        x0 = (96 - n * self.FW) // 2
        y0 = (48 - self.FH) // 2
        for i, ch in enumerate(chars):
            self._blit_glyph(d, _get_glyph(self.font_path, ch, self.FB), x0 + i * self.FW, y0)
        d.show()

    def _page_chars(self, p):
        """读取第 p 页文本（归一化空白），返回至多 PER_PAGE 个字符。"""
        if p >= self.total_pages:
            return ''
        start, end = self._get_page_bounds(p)
        with open(self.txt_path, 'rb') as f:
            f.seek(start)
            raw = _read_exact(f, end - start)
        text = _decode_utf8(raw)
        # 注意：MicroPython 的 ure 不识别字符类里的多字节字面量「　」(U+3000)。
        # 它会把 [　] 按字节拆成 {0xE3,0x80}，re.sub 于是把正文里所有含续接字节
        # 0x80 的汉字（如 一/开/简，编码均以 80 结尾）也当“空白”替换成空格 →
        # 这些字乱码成“空格+黑框/两个空格”。所以全角空格改用 str.replace
        # （对 str 安全），正则里只保留 ASCII 空白。
        text = text.replace('\u3000', ' ')
        try:
            text = re.sub('[ \t\r\n]+', ' ', text)
        except Exception:
            pass  # 极端情况（如部分 MicroPython 构建对特定字符的 re 异常）下原样显示，不崩溃
        try:
            return text[:self.PER_PAGE]
        except Exception:
            return text  # 渲染层极端兜底，绝不让本页读取外抛

    def _render_line(self, d, line, row):
        y = row * self.FH
        for i, ch in enumerate(line):
            if i >= self.COLS:
                break
            self._blit_glyph(d, _get_glyph(self.font_path, ch, self.FB), i * self.FW, y)

    def _auto_page_lines(self, p):
        """把第 p 页字符拆成 ROWS 行（每行至多 COLS 字符，不足补空）。"""
        chars = self._page_chars(p)
        return [chars[r * self.COLS:(r + 1) * self.COLS] for r in range(self.ROWS)]

    def _auto_line_at(self, idx):
        """返回全局行流（页*ROWS+行）中第 idx 行的字符串；越界或空行返回 None。"""
        p = idx // self.ROWS
        r = idx % self.ROWS
        if p >= self.total_pages:
            return None
        if self._auto_cache['page'] != p:
            self._auto_cache = {'page': p, 'lines': self._auto_page_lines(p)}
        line = self._auto_cache['lines'][r]
        return line or None

    def _auto_render(self, win):
        """渲染自动阅读窗口：全局行 win 起的 ROWS 行。返回 False 表示已到末页。"""
        d = self.display
        d.fill(0)
        any_line = False
        for r in range(self.ROWS):
            line = self._auto_line_at(win + r)
            if line is None:
                break
            any_line = True
            self._render_line(d, line, r)
        d.show()
        return any_line

    # ---- 书签 ----
    def _bmk_path(self):
        return self.txt_path + '.bmk'

    def _load_bookmarks(self):
        try:
            with open(self._bmk_path(), 'r') as f:
                vals = [int(x) for x in f.read().split() if x.strip().isdigit()]
            return sorted(set(vals))
        except Exception:
            return []

    def _save_bookmarks(self, marks):
        try:
            with open(self._bmk_path(), 'w') as f:
                for p in marks:
                    f.write('%d\n' % p)
        except Exception:
            pass

    def _toggle_bookmark(self):
        marks = self._load_bookmarks()
        if self.page in marks:
            marks.remove(self.page)
            msg = '已删书签'
        else:
            marks.append(self.page)
            marks.sort()
            msg = '已加书签'
        self._save_bookmarks(marks)
        self._show_msg(msg)
        time.sleep_ms(800)
        self._show()

    def _bookmark_menu(self):
        from menu import _draw_text8
        marks = self._load_bookmarks()
        if not marks:
            self._show_msg('无书签')
            time.sleep_ms(800)
            self._show()
            return
        sel = 0
        vis = self.ROWS
        # app.py 始终传入全局 Input，书签导航统一走 IRQ 事件（一种功能仅此一种实现）。
        inp = self.inp
        inp.clear()  # 进书签界面先清残键，避免上一动作的持键被误判
        while True:
            d = self.display
            d.fill(0)
            top = (sel // vis) * vis
            for i, p in enumerate(marks[top:top + vis]):
                y = i * self.FH
                if top + i == sel:
                    d.fill_rect(0, y, 96, self.FH, 1)
                    _draw_text8(d, 'P%d' % p, 2, y + (self.FH - 8) // 2, 0)
                else:
                    _draw_text8(d, 'P%d' % p, 2, y + (self.FH - 8) // 2, 1)
            d.show()
            a = inp.wait()
            if a[0] == 'up' and a[1] == 'short':
                sel = (sel - 1) % len(marks)
            elif a[0] == 'down' and a[1] == 'short':
                sel = (sel + 1) % len(marks)
            elif a[0] == 'ok' and a[1] == 'short':
                self.jump_to(marks[sel])
                self._save_progress()
                return
            elif a[0] == 'up' and a[1] == 'long':
                # 长按「上」：返回阅读
                return
