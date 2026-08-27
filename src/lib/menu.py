import os
import time
import framebuf

SCR_W = 96
SCR_H = 48

BOOKS_DIR = '/sd/books'
FONTS_DIR = '/sd/fonts'
SETTINGS_FILE = '/sd/.settings'
MAP_FILE = '/sd/books.map'

_FONT8_DATA = bytes([
    0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00, 0x18,0x18,0x18,0x18,0x18,0x00,0x18,0x00,
    0x6C,0x6C,0x24,0x00,0x00,0x00,0x00,0x00, 0x6C,0x6C,0xFE,0x6C,0xFE,0x6C,0x6C,0x00,
    0x18,0x7E,0xC0,0x7C,0x06,0xFC,0x18,0x00, 0xC6,0xCC,0x18,0x30,0x60,0xC6,0x86,0x00,
    0x78,0xCC,0xC8,0x76,0xDC,0xCC,0x76,0x00, 0x18,0x18,0x18,0x18,0x18,0x00,0x18,0x00,
    0x0C,0x18,0x30,0x30,0x30,0x18,0x0C,0x00, 0x30,0x18,0x0C,0x0C,0x0C,0x18,0x30,0x00,
    0x00,0x66,0x3C,0xFF,0x3C,0x66,0x00,0x00, 0x00,0x18,0x18,0x7E,0x18,0x18,0x00,0x00,
    0x00,0x00,0x00,0x00,0x00,0x18,0x18,0x30, 0x00,0x00,0x00,0x7E,0x00,0x00,0x00,0x00,
    0x00,0x00,0x00,0x00,0x00,0x18,0x18,0x00, 0x06,0x0C,0x18,0x30,0x60,0xC0,0x80,0x00,
    0x7C,0xC6,0xC6,0xC6,0xC6,0xC6,0x7C,0x00, 0x18,0x38,0x78,0x18,0x18,0x18,0x7E,0x00,
    0x7C,0xC6,0x06,0x0C,0x18,0x30,0xFE,0x00, 0x7C,0xC6,0x06,0x3C,0x06,0xC6,0x7C,0x00,
    0xCC,0xCC,0xCC,0xCC,0xFE,0x0C,0x0C,0x00, 0xFE,0xC0,0xC0,0xFC,0x06,0xC6,0x7C,0x00,
    0x3C,0x60,0xC0,0xFC,0xC6,0xC6,0x7C,0x00, 0xFE,0xC6,0x0C,0x18,0x30,0x30,0x30,0x00,
    0x7C,0xC6,0xC6,0x7C,0xC6,0xC6,0x7C,0x00, 0x7C,0xC6,0xC6,0x7E,0x06,0x0C,0x78,0x00,
    0x00,0x18,0x18,0x00,0x00,0x18,0x18,0x00, 0x00,0x18,0x18,0x00,0x00,0x18,0x18,0x30,
    0x06,0x0C,0x18,0x30,0x18,0x0C,0x06,0x00, 0x00,0x00,0x7E,0x00,0x7E,0x00,0x00,0x00,
    0x60,0x30,0x18,0x0C,0x18,0x30,0x60,0x00, 0x7C,0xC6,0x0C,0x18,0x18,0x00,0x18,0x00,
    0x7C,0xC6,0xC6,0xDE,0xDE,0xC0,0x7C,0x00, 0x38,0x6C,0xC6,0xC6,0xFE,0xC6,0xC6,0x00,
    0xFC,0xC6,0xC6,0xFC,0xC6,0xC6,0xFC,0x00, 0x7C,0xC6,0xC0,0xC0,0xC0,0xC6,0x7C,0x00,
    0xF8,0xCC,0xC6,0xC6,0xC6,0xCC,0xF8,0x00, 0xFE,0xC0,0xC0,0xFC,0xC0,0xC0,0xFE,0x00,
    0xFE,0xC0,0xC0,0xFC,0xC0,0xC0,0xC0,0x00, 0x7C,0xC6,0xC0,0xCE,0xC6,0xC6,0x7C,0x00,
    0xC6,0xC6,0xC6,0xFE,0xC6,0xC6,0xC6,0x00, 0x7E,0x18,0x18,0x18,0x18,0x18,0x7E,0x00,
    0x1E,0x06,0x06,0x06,0xC6,0xC6,0x7C,0x00, 0xC6,0xCC,0xD8,0xF0,0xD8,0xCC,0xC6,0x00,
    0xC0,0xC0,0xC0,0xC0,0xC0,0xC0,0xFE,0x00, 0xC6,0xEE,0xFE,0xD6,0xC6,0xC6,0xC6,0x00,
    0xC6,0xE6,0xF6,0xDE,0xCE,0xC6,0xC6,0x00, 0x7C,0xC6,0xC6,0xC6,0xC6,0xC6,0x7C,0x00,
    0xFC,0xC6,0xC6,0xFC,0xC0,0xC0,0xC0,0x00, 0x7C,0xC6,0xC6,0xC6,0xD6,0xCC,0x76,0x00,
    0xFC,0xC6,0xC6,0xFC,0xD8,0xCC,0xC6,0x00, 0x7C,0xC6,0xC0,0x7C,0x06,0xC6,0x7C,0x00,
    0xFE,0x18,0x18,0x18,0x18,0x18,0x18,0x00, 0xC6,0xC6,0xC6,0xC6,0xC6,0xC6,0x7C,0x00,
    0xC6,0xC6,0xC6,0xC6,0xC6,0x6C,0x38,0x00, 0xC6,0xC6,0xC6,0xD6,0xD6,0xFE,0x6C,0x00,
    0xC6,0xC6,0x6C,0x38,0x6C,0xC6,0xC6,0x00, 0xC6,0xC6,0xC6,0x6C,0x38,0x18,0x18,0x00,
    0xFE,0x06,0x0C,0x18,0x30,0x60,0xFE,0x00, 0x3C,0x30,0x30,0x30,0x30,0x30,0x3C,0x00,
    0xC0,0x60,0x30,0x18,0x0C,0x06,0x02,0x00, 0x3C,0x0C,0x0C,0x0C,0x0C,0x0C,0x3C,0x00,
    0x18,0x3C,0x66,0x00,0x00,0x00,0x00,0x00, 0x00,0x00,0x00,0x00,0x00,0x00,0xFF,0x00,
    0x38,0x18,0x0C,0x00,0x00,0x00,0x00,0x00, 0x00,0x00,0x7C,0x06,0x7E,0xC6,0x7E,0x00,
    0xC0,0xC0,0xFC,0xC6,0xC6,0xC6,0xFC,0x00, 0x00,0x00,0x7C,0xC6,0xC0,0xC6,0x7C,0x00,
    0x06,0x06,0x7E,0xC6,0xC6,0xC6,0x7E,0x00, 0x00,0x00,0x7C,0xC6,0xFC,0xC0,0x7C,0x00,
    0x3C,0x66,0x60,0xF0,0x60,0x60,0x60,0x00, 0x00,0x7E,0xC6,0xC6,0x7E,0x06,0x7C,0x00,
    0xC0,0xC0,0xFC,0xC6,0xC6,0xC6,0xC6,0x00, 0x18,0x00,0x38,0x18,0x18,0x18,0x3C,0x00,
    0x06,0x00,0x06,0x06,0x06,0xC6,0x7C,0x00, 0xC0,0xC0,0xC6,0xCC,0xF8,0xCC,0xC6,0x00,
    0x38,0x18,0x18,0x18,0x18,0x18,0x3C,0x00, 0x00,0x00,0xCC,0xFE,0xD6,0xC6,0xC6,0x00,
    0x00,0x00,0xFC,0xC6,0xC6,0xC6,0xC6,0x00, 0x00,0x00,0x7C,0xC6,0xC6,0xC6,0x7C,0x00,
    0x00,0x00,0xFC,0xC6,0xC6,0xFC,0xC0,0xC0, 0x00,0x00,0x7E,0xC6,0xC6,0x7E,0x06,0x06,
    0x00,0x00,0xFC,0xC6,0xC0,0xC0,0xC0,0x00, 0x00,0x00,0x7E,0xC0,0x7C,0x06,0xFC,0x00,
    0x30,0x30,0xFC,0x30,0x30,0x36,0x1C,0x00, 0x00,0x00,0xC6,0xC6,0xC6,0xC6,0x7E,0x00,
    0x00,0x00,0xC6,0xC6,0xC6,0x6C,0x38,0x00, 0x00,0x00,0xC6,0xC6,0xD6,0xD6,0x6C,0x00,
    0x00,0x00,0xC6,0x6C,0x38,0x6C,0xC6,0x00, 0x00,0x00,0xC6,0xC6,0x7E,0x06,0x7C,0x00,
    0x00,0x00,0xFE,0x0C,0x38,0x60,0xFE,0x00, 0x0C,0x18,0x18,0x70,0x18,0x18,0x0C,0x00,
    0x18,0x18,0x18,0x00,0x18,0x18,0x18,0x00, 0x30,0x18,0x18,0x0E,0x18,0x18,0x30,0x00,
    0x00,0x00,0x70,0x9C,0x0E,0x00,0x00,0x00,
])


def _draw_char8(display, ch, x, y, color=1):
    o = (ord(ch) - 0x20) * 8
    if o < 0 or o + 8 > len(_FONT8_DATA):
        return
    for row in range(8):
        b = _FONT8_DATA[o + row]
        if b == 0:
            continue
        for col in range(8):
            if b & (0x80 >> col):
                display.pixel(x + col, y + row, color)


def _draw_text8(display, s, x, y, color=1):
    for ch in s:
        if x + 8 > SCR_W:
            break
        _draw_char8(display, ch, x, y, color)
        x += 8


_menu_font = None

def _init_menu_font(font_path):
    global _menu_font
    if _menu_font is not None and _menu_font.get('path') == font_path:
        return _menu_font['FW'], _menu_font['FH'], _menu_font['FB']
    try:
        from reader import _load_font, _read_exact
        meta = _load_font(font_path)
        FB = meta['char_bytes']
        FW = FH = 12 if FB == 24 else 16
        fb_buf = bytearray(FB)
        fb = framebuf.FrameBuffer(fb_buf, FW, FH, framebuf.MONO_VLSB)
        inv_buf = bytearray(FB)
        inv_fb = framebuf.FrameBuffer(inv_buf, FW, FH, framebuf.MONO_VLSB)
        _menu_font = {
            'path': font_path,
            'FW': FW, 'FH': FH, 'FB': FB,
            'fb_buf': fb_buf, 'fb': fb,
            'inv_buf': inv_buf, 'inv_fb': inv_fb,
        }
        return FW, FH, FB
    except Exception:
        _menu_font = None
        return None


def _draw_text_mixed(display, s, x, y_row, row_h, color, font_path):
    from reader import _get_glyph
    info = _init_menu_font(font_path)
    if info is None:
        _draw_text8(display, s, x, y_row + (row_h - 8) // 2, color)
        return
    FW, FH, FB = info
    fb_buf = _menu_font['fb_buf']
    fb = _menu_font['fb']
    inv_buf = _menu_font['inv_buf']
    inv_fb = _menu_font['inv_fb']
    y_as = y_row + (row_h - 8) // 2
    y_cn = y_row + (row_h - FH) // 2
    cx = x
    for ch in s:
        cp = ord(ch)
        if 0x20 <= cp <= 0x7E:
            if cx + 8 > SCR_W:
                break
            _draw_char8(display, ch, cx, y_as, color)
            cx += 8
        else:
            if cx + FW > SCR_W:
                break
            glyph = _get_glyph(font_path, ch, FB)
            if color == 0:
                for j in range(FB):
                    inv_buf[j] = glyph[j] ^ 0xFF
                display.blit(inv_fb, cx, y_cn, 1)
            else:
                fb_buf[:] = glyph
                display.blit(fb, cx, y_cn, 0)
            cx += FW


def _load_book_map():
    mapping = {}
    try:
        with open(MAP_FILE, 'r') as f:
            for line in f:
                line = line.strip()
                if '|' in line:
                    k, v = line.split('|', 1)
                    mapping[k] = v
    except Exception:
        pass
    return mapping


def list_books():
    try:
        files = os.listdir(BOOKS_DIR)
    except (OSError, UnicodeError):
        return []
    book_map = _load_book_map()
    books = []
    for f in files:
        if not isinstance(f, str) or f.startswith('.'):
            continue
        if not f.lower().endswith('.txt'):
            continue
        display = book_map.get(f, f[:-4])
        books.append(('%s/%s' % (BOOKS_DIR, f), display))
    books.sort(key=lambda x: x[0])
    return books


def list_fonts():
    fonts = []
    try:
        files = os.listdir(FONTS_DIR)
    except (OSError, UnicodeError):
        return []
    for f in files:
        try:
            if not isinstance(f, str):
                continue
            if f.endswith('.font') or f.endswith('.FONT'):
                base = f[:-5]
                for sep in range(len(base)):
                    if base[sep:].isdigit():
                        size = int(base[sep:])
                        fname = base[:sep]
                        if size in (12, 16):
                            fonts.append((fname, size))
                        break
        except Exception:
            continue
    fonts.sort()
    return fonts


def _load_settings():
    try:
        with open(SETTINGS_FILE, 'r') as f:
            line = f.read().strip()
            if line:
                parts = line.split(',')
                if len(parts) == 2:
                    return (parts[0], int(parts[1]))
    except Exception:
        pass
    return None


def _save_settings(name, size):
    try:
        with open(SETTINGS_FILE, 'w') as f:
            f.write('%s,%d' % (name, size))
    except Exception:
        pass


def font_path(name, size):
    return '%s/%s%d.font' % (FONTS_DIR, name, size)


def _preferred_font(fonts):
    """给出一组可用字体 (name,size) 时的默认选择：
    优先 simsun / simyou 的 12、16 档（与电子书回退优先级一致），
    都没有才回退到列表首项；空列表返回 None。"""
    if not fonts:
        return None
    for f in (('simsun', 12), ('simsun', 16), ('simyou', 12), ('simyou', 16)):
        if f in fonts:
            return f
    return fonts[0]


def current_font_path():
    """返回当前字体对应的 .font 路径（无设置或默认 simsun,12 缺失时，回退到任一可用字体，
    绝不返回一个不存在的文件，避免 vocab 初始化字库时报错卡死）。"""
    fonts = list_fonts()
    s = _load_settings()
    if s and s in fonts:
        name, size = s
    else:
        pick = _preferred_font(fonts)
        if pick is None:
            # 没有任何字库：返回 None，由调用方决定降级（如仅显示 8px 点阵）
            return None
        name, size = pick
    return font_path(name, size)


def pick_font(display, btn_up, btn_down, btn_ok):
    """弹出字体选择器，选定后写入 .settings，返回 (name, size)。"""
    fonts = list_fonts()
    if not fonts:
        return None
    idx = -1
    cur = _load_settings()
    for i, f in enumerate(fonts):
        if cur and cur == f:
            idx = i
            break
    if idx < 0:
        # 无有效设置时默认停在 simsun（与 Menu/current_font_path 默认一致），
        # 不取 fonts[0]，否则首次打开选择器会把 simhei 高亮成「默认」。
        idx = 0
        for i, f in enumerate(fonts):
            if f[0] == 'simsun':
                idx = i
                break
    d = display
    while btn_ok.value() == 0:
        time.sleep_ms(10)
    time.sleep_ms(50)
    row_h = 14
    rows = 3
    y0 = 2
    while True:
        d.fill(0)
        for i in range(rows):
            fi = (idx // rows) * rows + i
            if fi >= len(fonts):
                break
            y = y0 + i * row_h
            if fi == idx:
                d.fill_rect(0, y, SCR_W, row_h, 1)
                color = 0
            else:
                color = 1
            _draw_text8(d, '%s%d' % fonts[fi], 8, y + (row_h - 8) // 2, color)
        d.show()
        while True:
            if btn_up.value() == 0:
                time.sleep_ms(30)
                if btn_up.value() == 0:
                    idx = (idx - 1) % len(fonts)
                    while btn_up.value() == 0:
                        time.sleep_ms(10)
                    break
            if btn_down.value() == 0:
                time.sleep_ms(30)
                if btn_down.value() == 0:
                    idx = (idx + 1) % len(fonts)
                    while btn_down.value() == 0:
                        time.sleep_ms(10)
                    break
            if btn_ok.value() == 0:
                time.sleep_ms(30)
                if btn_ok.value() == 0:
                    while btn_ok.value() == 0:
                        time.sleep_ms(10)
                    _save_settings(fonts[idx][0], fonts[idx][1])
                    return fonts[idx]
            time.sleep_ms(15)


class Menu:
    def __init__(self, display, btn_up, btn_down, btn_ok):
        self.display = display
        self.btn_up = btn_up
        self.btn_down = btn_down
        self.btn_ok = btn_ok
        self.books = list_books()
        self.fonts = list_fonts()
        s = _load_settings()
        if s and s in self.fonts:
            self.font_name, self.font_size = s
        else:
            # 与 current_font_path() 保持一致：无有效设置时固定回退 simsun,12（缺失则回退
            # 任一可用字体），不取 fonts[0]，否则 os.listdir/排序把残留的 simhei 排到最前
            # 会导致电子书被强制成黑体。
            pick = _preferred_font(self.fonts)
            if pick is None:
                self.font_name, self.font_size = 'simsun', 12
            else:
                self.font_name, self.font_size = pick
        self._items = []
        for path, display in self.books:
            self._items.append({'type': 'book', 'path': path, 'name': display})
        self.sel = 0
        self._show()

    def _font_path(self):
        return '%s/%s%d.font' % (FONTS_DIR, self.font_name, self.font_size)

    def _drain_input(self, timeout_ms=5000):
        """进入菜单前等待所有按键松开，避免把来自上一层（如阅读长按退出）的残键
        误判为本菜单操作。__init__ 已绘制首帧，等待期间书架保持可见且不响应。
        超时必须给足：阅读长按「上」退出时键仍被按住，用户往往要再过一两秒、
        看到书架后才松手，超时过短会让书架把这句还没松开的「上」判成新长按，
        一次长按直接穿两级退回主页。5s 兜底按键卡死的情况。"""
        start = time.ticks_ms()
        while (self.btn_up.value() == 0 or self.btn_down.value() == 0
               or self.btn_ok.value() == 0):
            if time.ticks_diff(time.ticks_ms(), start) >= timeout_ms:
                break  # 超时兜底（按键卡死时不再阻塞，交给后续逻辑）
            time.sleep_ms(10)

    def _show(self):
        d = self.display
        d.fill(0)
        font_path = self._font_path()
        row_h = 12 if self.font_size == 12 else 16
        rows = 48 // row_h
        for i in range(rows):
            idx = (self.sel // rows) * rows + i
            if idx >= len(self._items):
                break
            y = i * row_h
            item = self._items[idx]
            if idx == self.sel:
                d.fill_rect(0, y, SCR_W, row_h, 1)
                color = 0
            else:
                color = 1
            if item['type'] == 'book':
                _draw_text_mixed(d, item['name'], 0, y, row_h, color, font_path)
        if not self._items:
            _draw_text8(d, 'NO BOOKS', (SCR_W - 8 * 8) // 2, 20, 1)
        d.show()

    def run(self):
        DEBOUNCE = 30
        HOLD_MS = 400
        # 进入书架时可能残留上一步的持键（如刚长按「上」退出阅读、或点选子菜单后未松手）：
        # 先等按键松开再处理，避免把上一步的持键误判成本菜单操作（否则刚进书架就被
        # 那句还没松开的「上」判成长按而立刻返回主页）。带超时兜底，防按键卡死。
        self._drain_input()
        while True:
            if self.btn_up.value() == 0:
                time.sleep_ms(DEBOUNCE)
                if self.btn_up.value() == 0:
                    start = time.ticks_ms()
                    long = False
                    while self.btn_up.value() == 0:
                        if time.ticks_diff(time.ticks_ms(), start) >= HOLD_MS:
                            long = True
                            break  # 达到长按时长立即退出，不等松开（与 Input IRQ 行为一致）
                        time.sleep_ms(10)
                    if long:
                        # 长按「上」：返回上一级（主页）
                        return None
                    if self.sel > 0:
                        self.sel -= 1
                        self._show()
            if self.btn_down.value() == 0:
                time.sleep_ms(DEBOUNCE)
                if self.btn_down.value() == 0:
                    if self.sel < len(self._items) - 1:
                        self.sel += 1
                        self._show()
                    while self.btn_down.value() == 0:
                        time.sleep_ms(10)
            if self.btn_ok.value() == 0:
                time.sleep_ms(DEBOUNCE)
                if self.btn_ok.value() == 0:
                    if self.books:
                        return (
                            self._items[self.sel]['path'],
                            '%s/%s%d.font' % (FONTS_DIR, self.font_name, self.font_size),
                        )
            time.sleep_ms(15)
