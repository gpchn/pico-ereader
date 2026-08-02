# AGENTS.md

Pico 小说阅读器：MicroPython 电子书阅读器（Raspberry Pi Pico + LCD9648 96×48 + SD 卡）。README.md 是面向用户的完整硬件教程（接线、烧录、使用），改动设备端逻辑前先读它。

## 布局

- `src/`：Pico 端源码。`main.py` 仅一行 `__import__('app')`（为兼容 mpy-cross 编译）；`app.py` 启动入口（LCD/SD/按键/主循环）；`lib/`：`uc1701x.py`（LCD 驱动）、`sdcard.py`（SD 驱动）、`menu.py`（菜单 + 字体选择）、`reader.py`（阅读器 + 字库/索引解析）。
- `build.py`：PC 端唯一构建工具（字库 + 书籍索引）→ 输出 `sd_card/`。旧 `build_font.py`/`build_books.py` 已合并删除（见 `3eb5558`），勿再引用。
- `books/`：原始中文名 `.txt`（gitignore）；`fonts/`：成品字库，`--copy-fonts` 的复制源（gitignore）。
- `Makefile`/`dist/`：可选 mpy-cross 编译。仅 `-O2`、Windows cmd 专用、**不含 `main.py`**。

## PC 端命令

- `python build.py` → 重建 `sd_card/fonts/*.font` + `sd_card/books/*.txt`/`.idx` + `books.map`。需 `pip install Pillow`。
- 字体路径硬编码在 `build.py` 顶部 `FONTS`（作者本机 Windows 路径，Linux/macOS 备选被注释）——换机器/换字体改这里。
- 常用参数：`--copy-fonts`（复制 `fonts/` 成品、跳过字库生成）、`--no-books`、`--no-fonts`。
- 每次运行都先清空再重建 `sd_card/books`、`fonts`、`books.map`；书籍按文件名排序编号 `book_0001.txt`…，**换书后编号会变**（进度按文件名绑定，编号变了续读失效）。
- `make` → `dist/*.mpy`（需 `mpy-cross` 在 PATH；部署时 `main.py` 仍以 .py 存在，`import` 会自动优先 `.mpy`）。

## 文件格式（改解析逻辑必看）

- `.font`：magic `'FN'`（只校验前 2 字节）；`<I` 字符数；`<H` char_bytes（**24=12px，32=16px**，其余按 16px 处理）；`<H` reserved；`<I` index_offset；`<I` bitmap_offset；`<I` reserved。字形按 `reader.py` `_RANGES` 的 codepoint 区间线性寻址；**index 表是恒等映射且设备端从不读**（直接 `bitmap_offset + idx*char_bytes` seek）。
- `.idx`：小端 uint32 数组（每页起始字节偏移），文件名 `<书名>_<每页字数>.idx`（12px→32、16px→18，由 `reader.py` 按 `COLS*ROWS` 推导）。最后一页边界用 `start+256` 估算（`reader.py` `_get_page_bounds`）。
- `books.map`：每行 `<ASCII名.txt>|<中文名>`（key 带 `.txt` 后缀，与 `os.listdir` 返回名一致）。
- `/sd/.settings`：`字体名,尺寸`（如 `simsun,12`）；进度文件 `/sd/books/<书名>.txt.prog`（页码整数，每次翻页写）。

## 设备端要点

- 纯 MicroPython（`machine`/`framebuf`），PC 上无法运行或测试；无测试/CI/lint，验证靠真机 + Thonny Shell（`app.py` 主循环 catch 异常并 `sys.print_exception` 到 shell）。`build.py` 是标准 CPython，可单独调试。
- LCD9648 可视区 96×48，但 **UC1701x buffer 必须保持默认 128×64，不要传 width/height**（README 13.7）；方向由 `app.py` 的 `invX/invY` 控制，显示裁剪靠屏物理实现。
- **UC1701x `show()` 每页必须写满 132 字节（128 buffer + 4 字节 0），`init()` 末尾整块清 9 页 × 132 列**：控制器 RAM 是 132×65，只写 128×8 会留下从未覆写的脏列/行，屏顶会显示一条固定内容（历史上因此出过 bug，见 commit `df8573e`）。勿精简成 `pages*128`。
- 按键：GP20 上 / GP16 下 / GP26 OK，均 `PULL_UP`、低电平有效；30ms 消抖在各模块 `DEBOUNCE` 常量（menu.py、reader.py 各有一份）。SD=SPI0（GP2-5），LCD=SPI1（GP8-12）。
- SD 挂载带 `encoding='gbk'` 回退（`app.py` `mount_sd()`，SD 驱动 ImportError 时回退 `machine.SDCard`）。**SD 文件名必须 ASCII**：非 ASCII 文件名会让 `os.listdir` 抛 UnicodeError 导致菜单为空；中文名只存在于 `books.map`。书文本必须 UTF-8（build.py 剥 BOM）。
- 菜单里 ASCII 文本用内置 8px 点阵（`menu.py` `_FONT8_DATA`），中文走当前字库；字体名从 `*.font` 文件名解析（首个连续数字处截断），只认 12/16 两档尺寸。
- 阅读模式：短按 OK 返回菜单，长按（>600ms）进跳页模式；跳页内长按 OK 取消、5 秒无操作自动退出（`reader.py` `run`/`_jump_dialog`）。
- 功耗：菜单/阅读循环空闲时用 `machine.lightsleep`（`_idle()`，异常回退 `time.sleep_ms`）；菜单与阅读器 120s 无操作自动熄屏（LCD 升压 `0x28|0x00` + `poweroff`），任意键唤醒重绘——升压关断是最大续航来源。
