"""
Pico 小说阅读器 v3 — SD 卡 + 动态字库

架构：
  /main.py
  /UC1701x.py
  /lib/sdcard.py
  /lib/menu.py
  /lib/reader.py

  /sd/books/*.txt      原文（任意编码）
  /sd/fonts/*.font     字库（PC 端 build_font.py 生成）
  /sd/.settings        字体偏好（运行时写入）
  /sd/books/*.txt.prog 阅读进度

按键：
  GP20 上 / GP16 下 / GP26 OK
"""
import sys
import time
import machine

sys.path.insert(0, '/')
sys.path.insert(0, '/lib')

from uc1701x import UC1701x
from menu import Menu
from reader import Reader


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
        import os
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
        try:
            os.stat('/sd/books')
        except OSError:
            try:
                os.mkdir('/sd/books')
            except:
                pass
        try:
            os.stat('/sd/fonts')
        except OSError:
            try:
                os.mkdir('/sd/fonts')
            except:
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
btn_up = machine.Pin(20, machine.Pin.IN, machine.Pin.PULL_UP)
btn_dn = machine.Pin(16, machine.Pin.IN, machine.Pin.PULL_UP)
btn_ok = machine.Pin(26, machine.Pin.IN, machine.Pin.PULL_UP)


# ---------- 主循环 ----------
def main():
    show_splash('Mounting SD...')
    sd = mount_sd()
    if sd is None:
        # 长时间错误显示（96 列宽，居中）
        display.fill(0)
        display.text('SD MOUNT', 16, 6, 1)   # 64px, x=16
        display.text('FAILED', 24, 22, 1)     # 48px, x=24
        display.text('CHECK SD', 16, 38, 1)   # 64px, x=16
        display.show()
        while True:
            if btn_ok.value() == 0:
                break
            time.sleep_ms(50)
    # 主循环
    while True:
        try:
            menu = Menu(display, btn_up, btn_dn, btn_ok)
            result = menu.run()
            if result == 'quit' or not result:
                # 进入低功耗：关闭 LCD
                display.poweroff()
                time.sleep_ms(100)
                # 关升压（节省更多电）
                display.writeCMD(0x28 | 0x00)
                while True:
                    if btn_up.value() == 0 or btn_dn.value() == 0 or btn_ok.value() == 0:
                        break
                    time.sleep_ms(50)
                # 恢复升压 + 显示
                display.writeCMD(0x28 | 0x07)
                display.poweron()
                time.sleep_ms(50)
                continue
            txt_path, font_path = result
            # 字体不存在时回退
            try:
                import os
                os.stat(font_path)
            except OSError:
                # 找任意 .font
                try:
                    fonts = [f for f in os.listdir('/sd/fonts') if f.endswith('.font')]
                    if fonts:
                        font_path = '/sd/fonts/' + fonts[0]
                    else:
                        show_splash('NO FONT')
                        time.sleep(2)
                        continue
                except:
                    show_splash('FONT ERR')
                    time.sleep(2)
                    continue
            # 进入阅读
            reader = Reader(display, txt_path, font_path, btn_up, btn_dn, btn_ok)
            reader.run()
        except Exception as e:
            # 把 traceback 输出到 Thonny Shell
            sys.print_exception(e)
            print('=== CAUGHT ===', type(e).__name__, repr(e))
            # LCD 显示错误类型 + 错误信息
            show_splash('E:' + type(e).__name__[:5] + str(e)[:6])
            time.sleep(3)
            # 继续循环
        except KeyboardInterrupt:
            break


main()
