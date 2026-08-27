# AGENTS.md

Pico 小说阅读器：MicroPython 电子书阅读器（Raspberry Pi Pico + LCD9648 96×48 + SD 卡）。README.md 是面向用户的完整硬件教程（接线、烧录、使用），改动设备端逻辑前先读它。

## 布局

- `src/`：Pico 端源码。`main.py` 仅一行 `__import__('app')`（为兼容 mpy-cross 编译）；`app.py` 启动入口（LCD/SD/按键/主循环）；`lib/`：`uc1701x.py`（LCD 驱动）、`sdcard.py`（SD 驱动）、`menu.py`（菜单 + 字体选择）、`reader.py`（阅读器 + 字库/索引解析）。
- `build_sd.py`：PC 端**一键构建**工具（合并了原 `build.py` 字库/书籍 + `build_dict.py` 词库）→ 输出 `sd_card/`（字库 + 书籍 + 索引 + `books.map` + `dict/`）。默认增量构建：字库按「源字体 mtime + 码点区间指纹」跳过、书籍复用旧编号保留进度、词库在 `ecdict.csv` 未变时整段跳过。唯一参数 `--force`（全量重建，重置除 `unknown.bin` 外的学习进度）。ECDICT 真实 tag 是 `zk/gk/cet4/cet6/ky(考研)/ielts/toefl/gre`，考研对应 `ky` 而非 `kaoyan`。
- `books/`：原始中文名 `.txt`（gitignore）；`fonts/`：成品字库（gitignore）。
- `Makefile`/`dist/`：可选 mpy-cross 编译。仅 `-O2`、Windows cmd 专用、**不含 `main.py`**。
- `src/lib/vocab.py`：背单词子系统（主页菜单 + 牌组列表 + 单词卡 + 生词本 + 查词）；`src/lib/reader.py` 长按「上」退出阅读、长按「下」切换自动阅读、OK 短按书签/长按加删书签。
- `server/`：当前**无 `server.py`/`wifi_sync.py` 源码**（仅 `__pycache__` 残留 + `books/` 样本），勿据此假设存在 WiFi/网络同步功能。

## PC 端命令

- `python build_sd.py` → 重建 `sd_card/fonts/*.font` + `sd_card/books/*.txt`/`.idx` + `books.map` + `dict/`（词库在 csv 未变时跳过）。需 `pip install Pillow`。
- 字体路径硬编码在 `build_sd.py` 顶部 `FONTS`（作者本机 Windows 路径，Linux/macOS 备选被注释）——换机器/换字体改这里。
- 常用参数：仅 `--force`（强制全量重建；会重置除 `unknown.bin` 外的学习进度）。
- 增量构建默认开启：字库按源字体 mtime + 码点指纹跳过；书籍复用旧编号（**进度按文件名绑定**，编号尽量不变使续读有效）；词库在 `ECDICT/ecdict.csv` 未变时整段跳过。
- `make` → `dist/*.mpy`（需 `mpy-cross` 在 PATH；部署时 `main.py` 仍以 .py 存在，`import` 会自动优先 `.mpy`）。

## 文件格式（改解析逻辑必看）

- `.font`：magic `'FN'`（只校验前 2 字节）；`<I` 字符数；`<H` char_bytes（**24=12px，32=16px**，其余按 16px 处理）；`<H` reserved；`<I` index_offset；`<I` bitmap_offset；`<I` reserved。字形按 `reader.py` `_RANGES` 的 codepoint 区间线性寻址；**index 表是恒等映射且设备端从不读**（直接 `bitmap_offset + idx*char_bytes` seek）。
- `.idx`：小端 uint32 数组（每页起始字节偏移），文件名 `<书名>_<每页字数>.idx`（12px→32、16px→18，由 `reader.py` 按 `COLS*ROWS` 推导）。最后一页边界用 `start+256` 估算（`reader.py` `_get_page_bounds`）。
- `books.map`：每行 `<ASCII名.txt>|<中文名>`（key 带 `.txt` 后缀，与 `os.listdir` 返回名一致）。
- `/sd/.settings`：`字体名,尺寸`（如 `simsun,12`）；进度文件 `/sd/books/<书名>.txt.prog`（页码整数，每次翻页写）；书签文件 `/sd/books/<书名>.txt.bmk`（每行一个页码整数，设备端 OK 长按增删）。
- `/sd/dict/`（背单词词库，`build_sd.py` 生成，全部小端；单词统一 lower() 且只保留 ASCII）：
  - `master.entryoff`：`u32[N]` 每条目在 `master.index` 的字节偏移（**空间换时间**：O(1) 定点 seek，无需把整张词表载入 RAM）。`master.index`：变长条目 `[u16 len][word ascii][u32 dataoff]`，**按单词升序**。`master.dir`：`u32[27]`，`dir[k]`=首字母 `chr(97+k)` 的起始条目下标、`dir[26]=N`，把二分范围缩到同首字母（约 1/26 窗口）。`master.troff`：`u32[N]` 每条目**翻译**在 `master.data` 中的偏移（**空间换时间**：O(1) 直取翻译，绕开音标/词性/词形，热路径如词卡正面零整记录解析）。`master.data`：连续记录，每条 = `[u8 phon_len][phon][u8 tag_len][tag][u8 nforms]` + 每 form `[u8 type][u8 wlen][word]` + `[u16 trans_len][translation utf-8]`（翻译上限 `MAX_TRANS=512`，过长在 PC 端截断以防设备端翻页器切分出行列表撑爆 RAM）。
  - 设备端查询：`Dictionary._index_of` 先用 `master.dir` 定首字母窗口，再在窗口内二分（`_word_at` 经 `master.entryoff` 直接 seek 到条目读 word），命中后 `_rec_at` 用条目内联的 `dataoff` 直接读 `master.data`。全程定点小读，不载入整表。
  - `decks/<name>.bin`：`u32[M]` 该牌组单词在 master 中的下标，按学习顺序（`name` ∈ gk/cet4/cet6/kaoyan/ielts/toefl/gre/freq/unknown）。
  - `progress/<name>.bin`：`u32 counter` + 每词 `[u8 box][u32 due]`（Leitner 间隔重复：box 0 始终到期；counter 无 RTC 时用作相对计数）。`unknown.bin` 生词本由设备端 `vocab.add_unknown` 追加。
  - **音标（IPA/希腊/西里尔）已在字库覆盖区间内（`build_sd.py` `PHON_RANGES` 与 `reader._RANGES` 0x00A0-0x0180 / 0x0250-0x0300 / 0x0370-0x0400 / 0x0400-0x0500），设备端可正常渲染**。注意：中文主字体（simsun/simhei/msyh）普遍没有 IPA 字形，`build_sd.py` 构建字库时对缺失字形用两个 PUA 哨兵字符检测「豆腐框」并回退到西文字体（Arial 等）补字形，勿删该逻辑。ECDICT 个别音标用 PUA 字符（如 U+E143 表示 /ɪ/），构建时已映射回真实码点。改显示前先确认 `vocab.FORM_LABEL` 与 `reader._RANGES` 的覆盖范围。

## 设备端要点

- 纯 MicroPython（`machine`/`framebuf`），PC 上无法运行或测试；无测试/CI/lint，验证靠真机 + Thonny Shell（`app.py` 主循环 catch 异常并 `sys.print_exception` 到 shell）。`build_sd.py` 是标准 CPython，可单独调试。
- LCD9648 可视区 96×48，但 **UC1701x buffer 必须保持默认 128×64，不要传 width/height**（README 13.7）；方向由 `app.py` 的 `invX/invY` 控制，显示裁剪靠屏物理实现。
- **UC1701x `show()` 每页必须写满 132 字节（128 buffer + 4 字节 0），`init()` 末尾整块清 9 页 × 132 列**：控制器 RAM 是 132×65，只写 128×8 会留下从未覆写的脏列/行，屏顶会显示一条固定内容（历史上因此出过 bug，见 commit `df8573e`）。勿精简成 `pages*128`。
- 按键：**GP16 上 / GP20 下 / GP26 OK**（`app.py` 实际接线，勿与代码注释里的旧写法混淆），均 `PULL_UP`、低电平有效；30ms 消抖在各模块 `DEBOUNCE` 常量（menu.py、reader.py 各有一份）。SD=SPI0（GP2-5），LCD=SPI1（GP8-12，其中 GP8=A0/DC、GP9=CS、GP10=SCK、GP11=MOSI、GP12=RST）。
- SD 挂载带 `encoding='gbk'` 回退（`app.py` `mount_sd()`，SD 驱动 ImportError 时回退 `machine.SDCard`）。**SD 文件名必须 ASCII**：非 ASCII 文件名会让 `os.listdir` 抛 UnicodeError 导致菜单为空；中文名只存在于 `books.map`。书文本必须 UTF-8（build_sd.py 剥 BOM）。
- 菜单里 ASCII 文本用内置 8px 点阵（`menu.py` `_FONT8_DATA`），中文走当前字库；字体名从 `*.font` 文件名解析（首个连续数字处截断），只认 12/16 两档尺寸。
- 主页菜单即「背单词界面」（`app.py` 主循环调 `vocab.run_vocab(display, inp)`，`inp` 为 IRQ 锁存的 `Input` 实例）：列出主牌组（高考/四级/生词本），末尾挂 `更多分级` / `电子书` / `切换字体` / `按键说明` 子菜单入口。选牌组 → 动作菜单（顺序背/乱序背/查看进度，生词本另含清空）；选「电子书」→ `run_books`（菜单+阅读），选「切换字体」→ `pick_font`，选「按键说明」→ `_show_help`。电子书内：短按 ↑/↓ 翻页；长按「上」退出阅读回书架（再长按「上」回主页）；长按「下」切换自动阅读（每 `AUTO_SCROLL_MS`（3000ms）窗口式逐行向上滚动，`reader.py` `_auto_render`，到末页自动关闭）；OK 短按打开书签界面（`_bookmark_menu`：↑↓ 选、OK 跳到该书签页、长按「上」返回）；OK 长按给当前页添加/删除书签（`_toggle_bookmark`，写入 `.bmk`）。
- 背单词交互（无键盘，纯 3 键固化流程）：单词卡**正背面按键一致**——上短=不认识、下短=认识（直接评分进下一张）、上长按=退出学习、OK短=切换正背面（正面单词/背面单词+释义）、OK长=加/删生词本（留在当前词）。二级菜单统一「上长按」返回上级（含「更多分级」菜单）。顺序背用 range 遍历、乱序背对整副牌组洗牌（`_build_order`），到期过滤统一在 `_study` 主循环按 `is_due` 跳过，故两模式都只学到期词（乱序背随机范围覆盖全牌组）。间隔重复用 Leitner（box 0 必现，box 越高越久才再出现）。已无测验功能。
- 按键输入统一走 `vocab.Input`（IRQ FALLING 锁存下降沿，`poll()` 每次最多返回一个 `(键, 'short'|'long')` 事件，`wait()` 阻塞取事件）。旧 `_poll` 仅在调用瞬间采样电平，短按在两轮询间完成会漏掉（表现为「有时不灵敏」），已弃用。`DEBOUNCE=30ms` 去抖、`HOLD_MS=400ms` 判定长按（阅读/菜单/词卡统一，长按达到阈值立即生效不等松开）。
- **注意：曾尝试用 `machine.lightsleep` 替代忙轮询并加 120s 自动熄屏省电（`f0e03f1`），因 RP2040 上 `lightsleep` 唤醒不可靠导致休眠后无法唤醒，已整体回退（`eca5d1a`）**。当前主线为最早的忙轮询演进版本（无 `lightsleep`/自动熄屏/低频优化），勿再引入；README 已更新为最新版（`7c97507`），设备端要点以回退后代码为准。
