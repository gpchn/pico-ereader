import framebuf

_SET_COLADD_L = const(0x00)
_SET_COLADD_H = const(0x10)
_SET_PWR_CTRL = const(0x28)
_SET_SCROLL_LINE = const(0x40)
_SET_PAGE_ADD = const(0xB0)
_VLCD_R_RATIO = const(0x20)
_CONTRAST_SET = const(0x81)
_ALL_PIX_ON = const(0xA4)
_SET_INV_DISP = const(0xA6)
_SET_ENA_DISP = const(0xAE)
_SET_SEG_DIR = const(0xA0)
_SET_COM_DIR = const(0xC0)
_SYS_SOFT_RST = const(0xE2)
_BIAS_RATIO = const(0xA2)


class UC1701x:
    def __init__(self, spi, a0, rst=None, cs=None, width=128, height=64,
                 roughContrast=0x03, fineContrast=0x28,
                 invX=False, invY=False, invDISP=False):
        self.width = width
        self.height = height
        self.spi = spi
        self.a0 = a0
        a0.init(a0.OUT, value=0)
        self.existCS = False
        if cs is not None:
            self.existCS = True
            cs.init(cs.OUT, value=0)
            self.cs = cs
        if rst is not None:
            rst.init(rst.OUT, value=0)
            self.rst = rst
            rst(1)
            import time
            time.sleep_ms(10)
            rst(0)
            time.sleep_ms(100)
            rst(1)
            time.sleep_ms(100)
        self.buffer = bytearray(width * height // 8)
        self.fb = framebuf.FrameBuffer(self.buffer, width, height, framebuf.MONO_VLSB)
        self.init(roughContrast, fineContrast, invX, invY, invDISP)

    def _cmd(self, cmd):
        self.a0(0)
        if self.existCS:
            self.cs(0)
        self.spi.write(bytearray([cmd]))
        if self.existCS:
            self.cs(1)

    def _data(self, data):
        self.a0(1)
        if self.existCS:
            self.cs(0)
        self.spi.write(data)
        if self.existCS:
            self.cs(1)

    def init(self, roughContrast=0x03, fineContrast=0x28,
             invX=False, invY=False, invDISP=False):
        import time
        self._cmd(_SYS_SOFT_RST)
        time.sleep_ms(10)
        self._cmd(_BIAS_RATIO)
        self._cmd(_SET_SEG_DIR | (1 if invX else 0))
        self._cmd(_SET_COM_DIR | (8 if invY else 0))
        self._cmd(_SET_INV_DISP | (1 if invDISP else 0))
        self._cmd(_ALL_PIX_ON)
        self._cmd(_VLCD_R_RATIO | 0x07)
        self._cmd(_CONTRAST_SET)
        self._cmd(roughContrast)
        self._cmd(fineContrast)
        self._cmd(_SET_PWR_CTRL | 0x07)
        self._cmd(_SET_ENA_DISP | 1)
        time.sleep_ms(100)
        self.fill(0)
        self.show()

    def _set_pos(self, col=0, page=0):
        self._cmd(_SET_COLADD_L | (col & 0x0F))
        self._cmd(_SET_COLADD_H | ((col >> 4) & 0x0F))
        self._cmd(_SET_PAGE_ADD | page)

    def fill(self, c):
        self.fb.fill(c)

    def fill_rect(self, x, y, w, h, c):
        self.fb.fill_rect(x, y, w, h, c)

    def hline(self, x, y, w, c):
        self.fb.hline(x, y, w, c)

    def text(self, s, x, y, c=1):
        self.fb.text(s, x, y, c)

    def pixel(self, x, y, c=1):
        self.fb.pixel(x, y, c)

    def blit(self, source, x, y, key=-1):
        self.fb.blit(source, x, y, key)

    def show(self):
        pages = self.height // 8
        col_start = (128 - self.width) // 2
        for p in range(pages):
            self._set_pos(col_start, p)
            self._data(self.buffer[p * self.width:(p + 1) * self.width])

    def poweroff(self):
        self._cmd(_SET_ENA_DISP | 0)

    def poweron(self):
        self._cmd(_SET_ENA_DISP | 1)

    def writeCMD(self, cmd):
        self._cmd(cmd)
