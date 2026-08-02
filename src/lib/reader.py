import os
import time
import struct
import re
import machine
import framebuf


def _idle(ms):
    try:
        machine.lightsleep(ms)
    except Exception:
        time.sleep_ms(ms)

_FONT_CACHE = {}
_FONT_CACHE_LIMIT = 200

_RANGES = (
    (0x20, 0x7F),
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
    def __init__(self, display, txt_path, font_path, btn_up, btn_down, btn_ok):
        self.display = display
        self.txt_path = txt_path
        self.font_path = font_path
        self.btn_up = btn_up
        self.btn_down = btn_down
        self.btn_ok = btn_ok

        meta = _load_font(font_path)
        self.FW = self.FH = 12 if meta['char_bytes'] == 24 else 16
        self.FB = meta['char_bytes']
        self.COLS = 96 // self.FW
        self.ROWS = 48 // self.FH
        self.PER_PAGE = self.COLS * self.ROWS
        self._fb_buf = bytearray(self.FB)
        self._fb = framebuf.FrameBuffer(self._fb_buf, self.FW, self.FH, framebuf.MONO_VLSB)

        self._build_index()
        self._txt_f = None
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

    def _close_txt(self):
        if self._txt_f is not None:
            self._txt_f.close()
            self._txt_f = None

    def _progress_path(self):
        return self.txt_path + '.prog'

    def _load_progress(self):
        try:
            with open(self._progress_path(), 'r') as f:
                p = int(f.read().strip())
                if 0 <= p < self.total_pages:
                    return p
        except:
            pass
        return 0

    def _save_progress(self):
        try:
            with open(self._progress_path(), 'w') as f:
                f.write(str(self.page))
        except:
            pass

    def _show(self):
        d = self.display
        d.fill(0)
        page_idx = self.page
        if page_idx >= self.total_pages:
            return
        n_chars = self.PER_PAGE
        start, end = self._get_page_bounds(page_idx)
        if self._txt_f is None:
            self._txt_f = open(self.txt_path, 'rb')
        f = self._txt_f
        f.seek(start)
        raw = _read_exact(f, end - start)
        text = raw.decode('utf-8', 'ignore')
        text = re.sub(r'[\s\u3000]+', ' ', text)
        chars = text[:n_chars] if len(text) >= n_chars else text
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

    def _poweroff(self):
        d = self.display
        d.writeCMD(0x28 | 0x00)
        d.poweroff()

    def _poweron(self):
        d = self.display
        d.writeCMD(0x28 | 0x07)
        d.poweron()
        time.sleep_ms(20)
        self._show()

    def run(self):
        DEBOUNCE = 30
        HOLD_MS = 600
        IDLE_POWEROFF_MS = 120000
        last_active = time.ticks_ms()
        sleeping = False
        while True:
            up_pressed = self.btn_up.value() == 0
            dn_pressed = self.btn_down.value() == 0
            ok_pressed = self.btn_ok.value() == 0
            now = time.ticks_ms()
            if up_pressed or dn_pressed or ok_pressed:
                last_active = now
                sleeping = False
            if not sleeping and time.ticks_diff(now, last_active) > IDLE_POWEROFF_MS:
                self._poweroff()
                sleeping = True
            if sleeping:
                if up_pressed or dn_pressed or ok_pressed:
                    self._poweron()
                    sleeping = False
                _idle(50)
                continue
            if up_pressed:
                time.sleep_ms(DEBOUNCE)
                if self.btn_up.value() == 0:
                    self.turn_prev()
                    self._save_progress()
                    last_active = time.ticks_ms()
                    while self.btn_up.value() == 0:
                        time.sleep_ms(10)
            if dn_pressed:
                time.sleep_ms(DEBOUNCE)
                if self.btn_down.value() == 0:
                    self.turn_next()
                    self._save_progress()
                    last_active = time.ticks_ms()
                    while self.btn_down.value() == 0:
                        time.sleep_ms(10)
            if ok_pressed:
                time.sleep_ms(DEBOUNCE)
                if self.btn_ok.value() == 0:
                    start = time.ticks_ms()
                    while self.btn_ok.value() == 0:
                        if time.ticks_diff(time.ticks_ms(), start) >= HOLD_MS:
                            self._jump_dialog()
                            while self.btn_ok.value() == 0:
                                time.sleep_ms(10)
                            break
                        time.sleep_ms(10)
                    else:
                        self._save_progress()
                        self._close_idx()
                        self._close_txt()
                        return 'menu'
            _idle(15)

    def _jump_dialog(self):
        DEBOUNCE = 30
        t_start = time.ticks_ms()
        while True:
            if self.btn_up.value() == 0:
                time.sleep_ms(DEBOUNCE)
                if self.btn_up.value() == 0:
                    self.turn_prev()
                    while self.btn_up.value() == 0:
                        time.sleep_ms(10)
            if self.btn_down.value() == 0:
                time.sleep_ms(DEBOUNCE)
                if self.btn_down.value() == 0:
                    self.turn_next()
                    while self.btn_down.value() == 0:
                        time.sleep_ms(10)
            if self.btn_ok.value() == 0:
                time.sleep_ms(DEBOUNCE)
                if self.btn_ok.value() == 0:
                    hold_start = time.ticks_ms()
                    while self.btn_ok.value() == 0:
                        if time.ticks_diff(time.ticks_ms(), hold_start) >= 400:
                            while self.btn_ok.value() == 0:
                                time.sleep_ms(10)
                            self._save_progress()
                            return
                        time.sleep_ms(10)
                    self._save_progress()
                    return
            if time.ticks_diff(time.ticks_ms(), t_start) > 5000:
                return
            _idle(15)
