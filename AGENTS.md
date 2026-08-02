# AGENTS.md

Pico 小说阅读器：MicroPython 电子书阅读器（Raspberry Pi Pico + LCD9648 96×48 + SD 卡）。README.md 是面向用户的完整硬件教程（接线、烧录、使用），改动设备端逻辑前先读它。

## 目录结构（⚠️ 仓库处于半重构状态，见下）

- `src/`：Pico 端真实源码。`src/main.py` 仅一行 `__import__('app')`（为兼容 mpy-cross 编译）；`src/app.py` 是启动入口；`src/lib/`：`uc1701x.py`（LCD 驱动）、`sdcard.py`（SD 驱动）、`menu.py`（菜单）、`reader.py`（阅读器）。
- `build.py`：PC 端一键构建（字库 + 书籍索引）→ 输出 `sd_card/`
- `books/`：放原始中文名 `.txt`（已 gitignore）
- `Makefile` / `dist/`：mpy-cross 编译（`-march=armv6m -msmall-int-bits=31 -O2`）

## 当前状态

- 设备代码在 `src/`（`main.py`/`app.py`/`lib/*`），PC 构建工具是自包含的 `build.py`（原 `build_font.py`/`build_books.py` 已合并删除，仍可在 `3eb5558^` 的 git 历史中查到）。README、Makefile 均已与 `src/` 布局同步，以 build.py 为准。

## PC 端构建流程（顺序固定）

1. `python build.py` → 生成 `sd_card/fonts/*.font` + `sd_card/books/*.txt`/`.idx` + `sd_card/books.map`（字库需 `pip install Pillow`，Windows 直接读 `C:\Windows\Fonts\simsun.ttc` 等；`--copy-fonts` 跳过字库生成直接复制 `fonts/` 成品，`--no-books`/`--no-fonts` 可只跑一半）
2. 把 `sd_card/` 内容拷到 **FAT32** SD 卡根目录（目录名必须小写 `books/`、`fonts/`）
3. Pico 端用 Thonny 传 `main.py`、`app.py`、`lib/*.py`

生成产物（`sd_card/`、`*.font`、`*.idx`、`*.prog`、`.settings`、`dist/`）全在 .gitignore 里，不要提交。

## 文件格式（改解析逻辑必看）

- `.font`：magic `'FN'`；`<I` 字符数；`<H` char_bytes（**24=12px，32=16px**，其余按 16px 处理）；`<I` index_offset；`<I` bitmap_offset。字形按 `reader.py:10-16` `_RANGES` 的 codepoint 区间线性寻址。
- `.idx`：小端 uint32 数组（每页起始字节偏移），文件名 `<书名>_<每页字数>.idx`（12px→32、16px→18）。
- `books.map`：每行 `ASCII文件名|中文名`；`/sd/.settings`：`字体名,尺寸`（如 `simsun,12`）；进度文件 `/sd/<书名>.prog`（页码整数）。

## 设备端要点

- 纯 MicroPython（`machine`/`framebuf`），PC 上无法运行或测试；无测试/CI/lint，验证靠真机。PC 端脚本是标准 CPython，可单独调试。
- LCD9648 可视区 96×48，但 **UC1701x buffer 必须保持默认 128×64，不要传 width/height**（见 README 13.7）；方向由 `app.py` 的 `invX/invY` 控制，显示裁剪靠屏物理实现。
- 书文本必须 UTF-8；SD 文件名必须 ASCII（中文名只存在于 `books.map`）；挂载带 `encoding='gbk'` 回退（`app.py:60-62`）。
- 按键：GP20 上 / GP16 下 / GP26 OK，均 `PULL_UP`、低电平有效、30ms 消抖（`app.py:93-95`）；SD 走 SPI0（GP2-5），LCD 走 SPI1（GP8-12）。
