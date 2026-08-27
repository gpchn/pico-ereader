"""
Pico 小说阅读器 + 背单词 — SD 卡 + 动态字库

架构：
  /main.py   （一行 __import__('app')）
  /app.py    启动入口（LCD/SD/按键/主循环）
  /lib/uc1701x.py        LCD 驱动
  /lib/sdcard.py         SD 驱动
  /lib/menu.py           书架菜单 + 字体选择
  /lib/reader.py         阅读器 + 字库/索引解析
  /lib/vocab.py          背单词子系统（主页菜单 / 单词卡 / 生词本）

  /sd/books/*.txt          原文（UTF-8）
  /sd/fonts/*.font         字库（PC 端 build_sd.py 生成）
  /sd/dict/*               词库（PC 端 build_sd.py 生成）
  /sd/.settings            字体偏好（运行时写入）
  /sd/books/*.txt.prog     阅读进度

主页即背单词界面（牌组列表 + 电子书 / 切换字体子菜单）。
电子书作为子菜单项；阅读中长按「上」退出回书架（再长按「上」回主页）。

按键：
  GP16 上 / GP20 下 / GP26 OK
"""
import os
import sys
import time
import machine

sys.path.insert(0, '/')
sys.path.insert(0, '/lib')

from uc1701x import UC1701x
from menu import Menu, pick_font, list_fonts, _preferred_font, font_path as build_font_path
from reader import Reader
import vocab
from vocab import Input



# ---------- LCD ----------
# LCD9648 实际分辨率 96 x 48（UC1701x 控制器 buffer 128x64，前 96 列 48 行是屏可见区域）
# 方向调整（根据屏实际方向修改 invX / invY 组合）：
#   正常（默认）   ：invX=False, invY=True
spi_lcd = machine.SPI(1, baudrate=4_000_000, polarity=0, phase=0,
                     sck=machine.Pin(10), mosi=machine.Pin(11))
display = UC1701x(spi_lcd,
                  a0=machine.Pin(8),
                  cs=machine.Pin(9),
                  rst=machine.Pin(12),
                  roughContrast=0x04,
                  fineContrast=0x28,
                  invX=False,
                  invY=True)


# ---------- SD ----------
def mount_sd():
    try:
        spi_sd = machine.SPI(0, baudrate=1_000_000, polarity=0, phase=0,
                            sck=machine.Pin(2), mosi=machine.Pin(3), miso=machine.Pin(4))
        cs = machine.Pin(5, machine.Pin.OUT, value=1)
        try:
            from sdcard import SDCard
            sd = SDCard(spi_sd, cs, baudrate=4_000_000)
        except ImportError:
            sd = machine.SDCard(spi_sd, cs)
        try:
            os.mount(sd, '/sd', encoding='gbk')
        except TypeError:
            os.mount(sd, '/sd')
        for sub in ('books', 'fonts'):
            try:
                os.stat('/sd/' + sub)
            except OSError:
                try:
                    os.mkdir('/sd/' + sub)
                except Exception:
                    pass
        return sd
    except Exception as e:
        print('SD 挂载失败:', e)
        return None


def show_splash(msg, line2=''):
    display.fill(0)
    display.text('PicoReader', 8, 8, 1)
    display.text(msg, 0, 30, 1)
    if line2:
        display.text(line2, 0, 40, 1)
    display.show()


# ---------- 按键 ----------
btn_up = machine.Pin(16, machine.Pin.IN, machine.Pin.PULL_UP)
btn_dn = machine.Pin(20, machine.Pin.IN, machine.Pin.PULL_UP)
btn_ok = machine.Pin(26, machine.Pin.IN, machine.Pin.PULL_UP)


# ---------- 主循环 ----------
def main():
    show_splash('Mounting SD...')
    sd = mount_sd()
    if sd is None:
        # 无 SD 卡什么都做不了：提示后按 OK 复位重试（否则主循环会无限闪「无词库」）
        display.fill(0)
        display.text('SD MOUNT', 16, 6, 1)   # 64px, x=16
        display.text('FAILED', 24, 22, 1)     # 48px, x=24
        display.text('OK=RETRY', 12, 38, 1)   # 72px, x=12
        display.show()
        while True:
            if btn_ok.value() == 0:
                machine.reset()
            time.sleep_ms(50)
    # 电子书子菜单：书架选书 -> 阅读；阅读退出后回到书架继续选书（长按「上」退出阅读不再回主页）
    def run_books():
        while True:
            menu = Menu(display, btn_up, btn_dn, btn_ok)
            result = menu.run()
            if not result:
                return  # 书架长按「上」返回主页
            txt_path, font_path = result
            # 所选字库文件若已消失（防御性兜底）：复用 menu 的单一回退规则重选一个
            try:
                os.stat(font_path)
            except OSError:
                pick = _preferred_font(list_fonts())
                if pick is None:
                    show_splash('NO FONT')
                    time.sleep(2)
                    return
                font_path = build_font_path(pick[0], pick[1])
            Reader(display, txt_path, font_path, btn_up, btn_dn, btn_ok, inp).run()
            # 阅读返回（含长按「上」退出）→ 回到本层书架，不会直接回主页

    # 主循环：背单词界面为顶层，电子书/切换字体为子菜单
    inp = Input(btn_up, btn_dn, btn_ok)
    while True:
        try:
            choice = vocab.run_vocab(display, inp)
            if choice == 'books':
                run_books()
            elif choice == 'font':
                pick_font(display, btn_up, btn_dn, btn_ok)
            # None：无词库等情况，重新进入背单词界面
        except Exception as e:
            # 把 traceback 输出到 Thonny Shell
            sys.print_exception(e)
            print('=== CAUGHT ===', type(e).__name__, repr(e))
            show_splash('E:' + type(e).__name__[:5] + str(e)[:6])
            time.sleep(3)
        except KeyboardInterrupt:
            break

main()
