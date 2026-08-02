# Pico 小说阅读器 — 从零开始完整使用教程

> 屏幕：LCD9648（UC1701x 控制器，**实际分辨率 96×48**）
> 主控：Raspberry Pi Pico
> 文本：SD 卡内任意 `.txt`（**仅 UTF-8**）
> 字库：PC 端 `build.py` 预生成，运行时按需查表
> 索引：PC 端 `build.py` 预生成页偏移表 + 文件名映射，开书无需等待

每页字数：

| 字号  | 列  | 行  | 每页字数 |
| ----- | --- | --- | -------- |
| 12×12 | 8   | 4   | **32**   |
| 16×16 | 6   | 3   | **18**   |

---

## 目录

1. [项目简介](#1-项目简介)
2. [物料清单](#2-物料清单)
3. [硬件接线](#3-硬件接线)
4. [PC 端准备](#4-pc-端准备)
5. [生成字库与书籍索引](#5-生成字库与书籍索引)
6. [生成 SD 卡文件](#6-生成-sd-卡文件)
7. [SD 卡准备](#7-sd-卡准备)
8. [烧录 MicroPython 固件](#8-烧录-micropython-固件)
9. [上传代码到 Pico](#9-上传代码到-pico)
10. [首次开机](#10-首次开机)
11. [日常使用](#11-日常使用)
12. [换书 / 换字体 / 换尺寸](#12-换书--换字体--换尺寸)
13. [常见问题](#13-常见问题)
14. [文件结构总览](#14-文件结构总览)
15. [附录](#15-附录)

---

## 1. 项目简介

### 1.1 它能做什么

把 SD 卡里任意多本中文 txt 小说装进 Raspberry Pi Pico，LCD9648（96×48）屏幕阅读：

- **主菜单**：列出 SD 卡上所有 `.txt` + **`>切换字体`** 选项
- **3 个按键**：翻页 + 确认 + 返回
- **菜单切换字体**：选中 `>切换字体` 按 OK 进入字体选择器
- **断电续读**：每本书独立保存进度
- **ASCII 文件名**：避开 MicroPython 的 FAT32 中文编码 bug，中文名通过 `books.map` 元数据文件显示

### 1.2 屏幕参数

> **重要**：LCD9648 实际可视区域是 **96×48 像素**（不是 128×64）。
> 控制器（UC1701x）内置 RAM 132×65，**buffer 保持默认 128×64**（1024 字节），
> 屏只显示前 96 列 48 行（被物理裁剪）。

每行字数 = 96 / 字号宽：

- 12px 字号 → 8 字/行
- 16px 字号 → 6 字/行

每屏行数 = 48 / 字号高：

- 12px 字号 → 4 行/屏
- 16px 字号 → 3 行/屏

每页字数：

- **12×12** = 8 × 4 = **32 字/页**
- **16×16** = 6 × 3 = **18 字/页**

### 1.3 系统原理

```
┌──── PC ────────────────────┐
│  build.py（字库+索引一键）  │  → sd_card/fonts/*.font
│                            │  → sd_card/books/*.txt + *.idx + books.map
└────────────────────────────┘
         ↓
┌──── SD 卡 ─────────────────┐
│  /fonts/simsun12.font      │  ← 字库（PC 预生成）
│  /books/book_0001.txt      │  ← ASCII 文件名（无编码问题）
│  /books/book_0001_32.idx   │  ← 页偏移索引
│  /books/book_0001_18.idx   │  ← 页偏移索引（16×16 字体用）
│  /books.map                │  ← book_0001.txt|三国演义
│  /books/book_0001.txt.prog │  ← 阅读进度
│  /.settings                │  ← 当前字体偏好
└────────────────────────────┘
         ↑ 读
    ┌────┴────┐
    │   Pico  │  开书直接读 .idx（无需等待）
    │         │  → 每次翻页只读 32~64 字节
    │         │  → through 范围查找 codepoint（无内存分配）
    │         │  → 字模 LRU 缓存（200 字）
    └────┬────┘
         ↓ 写
    ┌────┴────┐
    │  LCD    │  96×48
    └─────────┘
```

---

## 2. 物料清单

| 物料                 | 数量 | 备注                           |
| -------------------- | ---- | ------------------------------ |
| Raspberry Pi Pico    | 1    | 任何版本（Pico / Pico W 均可） |
| LCD9648 屏幕         | 1    | UC1701x 驱动，**96×48**        |
| Micro SD 卡模块      | 1    | SPI 接口，**3.3V**（不是 5V）  |
| Micro SD 卡          | 1    | 4-32GB，**FAT32**              |
| 轻触按键             | 3    | 6mm 微型两脚按键               |
| 杜邦线               | 若干 | 母对母 + 母对公                |
| 面包板               | 1    | 400 孔或 830 孔                |
| Micro-USB / USB-C 线 | 1    | 给 Pico 供电 + 烧录            |

> 屏幕和 SD 模块必须是 **3.3V** 电平。Pico 的 GPIO 是 3.3V，所以直接连没问题。

---

## 3. 硬件接线

### 3.1 引脚总览

```
              Raspberry Pi Pico
            ┌─────────────────────┐
            │                  USB│
   LCD SCK ─┤ GP10            GP2 ├─ SD SCK
   LCD MOSI─┤ GP11            GP3 ├─ SD MOSI
   LCD CS  ─┤ GP9             GP4 ├─ SD MISO
   LCD A0  ─┤ GP8             GP5 ├─ SD CS
   LCD RST ─┤ GP12                │
    上 键 ──┤ GP20           GP16 ├── 下 键
            │                GP26 ├── OK 键
            │ 3V3             GND │
            └─────────────────────┘
```

### 3.2 LCD9648 接线（SPI1）

| LCD 引脚   | Pico 引脚  | 说明          |
| ---------- | ---------- | ------------- |
| VCC        | **3V3**    | 3.3V 供电     |
| GND        | **GND**    | 地            |
| SCK (SCL)  | **GP10**   | SPI1 SCK      |
| SDA (MOSI) | **GP11**   | SPI1 MOSI     |
| CS         | **GP9**    | 片选          |
| DC (A0)    | **GP8**    | 数据/命令选择 |
| RST        | **GP12**   | 复位          |
| BL (LED)   | 3V3 或悬空 | 背光（可选）  |

### 3.3 SD 卡模块接线（SPI0）

| SD 引脚 | Pico 引脚 | 说明                   |
| ------- | --------- | ---------------------- |
| VCC     | **3V3**   | 3.3V 供电（不要接 5V） |
| GND     | **GND**   | 地                     |
| SCK     | **GP2**   | SPI0 SCK               |
| MOSI    | **GP3**   | SPI0 MOSI              |
| MISO    | **GP4**   | SPI0 MISO              |
| CS      | **GP5**   | 片选                   |

### 3.4 按键接线

每个按键**一脚接 GPxx，另一脚接 GND**。MicroPython 内部上拉，无需外接电阻。

| 按键  | Pico 引脚 | 菜单功能    | 阅读功能            |
| ----- | --------- | ----------- | ------------------- |
| 上键  | **GP20**  | 上移        | **上一页**          |
| 下键  | **GP16**  | 下移        | **下一页**          |
| OK 键 | **GP26**  | 确认 / 打开 | 返回菜单 / 长按跳页 |

### 3.5 接线注意事项

> - **共地**：所有 GND 必须连到一起（Pico、LCD、SD、按键）
> - **SD 卡必须 3.3V**——5V 会烧 SD 卡
> - **杜邦线 < 20cm**：SPI 容易受干扰
> - **不要在 Pico 通电时插拔 SD 卡**

---

## 4. PC 端准备

### 4.1 安装 Python

- 推荐 **Python 3.9+**
- <https://www.python.org/downloads/>
- 安装时勾选 "Add Python to PATH"

### 4.2 安装 Pillow（生成字库用）

```bash
pip install Pillow
```

### 4.3 安装 Thonny（给 Pico 传文件）

- 下载：<https://thonny.org/>
- 安装后首次打开会自动检测 Pico

### 4.4 准备中文字体

确认 PC 上有中文字体：

| 系统    | 字体路径                              |
| ------- | ------------------------------------- |
| Windows | `C:\Windows\Fonts\simsun.ttc`（宋体） |
| Windows | `C:\Windows\Fonts\simhei.ttf`（黑体） |
| Windows | `C:\Windows\Fonts\SIMLI.TTF`（隶书）  |
| Linux   | `sudo apt install fonts-wqy-microhei` |
| macOS   | `/System/Library/Fonts/PingFang.ttc`  |

---

## 5. 生成字库与书籍索引

### 5.1 打开命令行，进入项目目录

```bash
cd 三国演义
```

### 5.2 一键构建（字库 + 书籍索引）

```bash
python build.py
```

一次完成三件事：

1. 生成全部字库（需先 `pip install Pillow`，见 4.2）
2. 把 `books/` 里的小说重命名为 ASCII 文件名（`book_0001.txt`、`book_0002.txt`…），并为每种字号（12×12 和 16×16）生成 `.idx` 页偏移索引
3. 生成 `books.map` 元数据文件（记录 ASCII 名←→中文名映射）

会输出类似：

```
[simsun12.font] 字体=C:/Windows/Fonts/simsun.ttc  尺寸=12x12
  字符数: 27983
  渲染: 成功=27983 失败/空白=0
  写入: sd_card\fonts\simsun12.font (783548 字节, 765.2 KB)
...
生成完成。共 4 个字体文件，目录：sd_card/fonts/
```

生成文件：

```
sd_card/fonts/
├── simsun12.font   宋体 12×12 (~765KB)
├── simsun16.font   宋体 16×16 (~984KB)
└── ...             其余取决于本机已安装的字体（文泉驿等）
```

### 5.3 常用参数

| 参数           | 作用                                             |
| -------------- | ------------------------------------------------ |
| `--copy-fonts` | 不重新生成字库，直接复制 `fonts/` 目录下已有成品 |
| `--no-books`   | 只处理字库，跳过书籍                             |
| `--no-fonts`   | 只处理书籍，跳过字库                             |

### 5.4 字符集说明

字体文件覆盖的字符范围：

- ASCII 可打印（0x20-0x7E）
- CJK 标点（0x3000-0x303F）
- CJK 扩展 A（0x3400-0x4DBF）
- **CJK 基本**（0x4E00-0x9FFF，20902 字）
- 全角 ASCII（0xFF00-0xFFEF）

> 几乎所有标准中文小说的字符都在此范围内。极少数生僻字/异体字会显示为空白。

---

## 6. 生成 SD 卡文件

### 6.1 准备小说

把 `.txt` 文件放到项目下的 `books/` 目录：

```
三国演义/
└── books/
    ├── 三国演义.txt
    └── 红楼梦.txt
```

### 6.2 输出结构

`python build.py` 全部完成后（见第 5 章），`sd_card/` 目录结构如下：

```
sd_card/
├── fonts/
│   ├── simsun12.font          ← 字库
│   └── simsun16.font
├── books/
│   ├── book_0001.txt          ← ASCII 文件名，Pico 无编码问题
│   ├── book_0001_32.idx       ← 页偏移索引（12×12 字体用）
│   ├── book_0001_18.idx       ← 页偏移索引（16×16 字体用）
│   ├── book_0002.txt
│   ├── book_0002_32.idx
│   ├── book_0002_18.idx
│   └── ...
└── books.map                  ← book_0001.txt|三国演义
```

---

## 7. SD 卡准备

### 7.1 格式化（重要！）

> **必须 FAT32**。如果是新卡或 exFAT，Pico 读不到。

1. 下载 **SD Card Formatter**：<https://www.sdcard.org/downloads/formatter/>
2. 插 SD 卡到电脑
3. 选 SD 卡 → **Format**
4. **Format Type = Quick**
5. **Format Size Adjustment = ON**
6. 开始

### 7.2 复制文件

把 `sd_card/` 下的内容复制到 SD 卡根目录：

```
SD:/
├── books/
│   ├── book_0001.txt
│   ├── book_0001_32.idx
│   ├── book_0001_18.idx
│   └── ...
├── fonts/
│   ├── simsun12.font
│   ├── simsun16.font
│   ├── simhei12.font
│   ├── simhei16.font
│   ├── simli12.font
│   └── simli16.font
└── books.map
```

> 目录名 `books/` 和 `fonts/` 必须小写。

---

## 8. 烧录 MicroPython 固件

### 8.1 下载固件

- 地址：<https://micropython.org/download/RPI_PICO/>
- 推荐：**`RPI_PICO-20240602-v1.23.0.uf2`**（或更新稳定版）
- Pico W 用户：选 `RPI_PICO_W-...uf2`

### 8.2 进入 BOOT 模式

1. **按住 Pico 板上的白色 BOOTSEL 按钮**
2. **不松开**，用 USB 线把 Pico 接到电脑
3. 松开按钮
4. 电脑会弹出一个名为 `RPI-RP2` 的 U 盘

### 8.3 复制固件

把下载的 `.uf2` 文件直接拖到 `RPI-RP2` U 盘。

---

## 9. 上传代码到 Pico

### 9.1 打开 Thonny

- 右上角选 **MicroPython (Raspberry Pi Pico)**
- View → Files，打开文件面板

### 9.2 创建 /lib 目录

在 Pico 文件树根目录右键 → **New directory** → 命名为 `lib`

### 9.3 复制文件

| PC 端路径            | 拖到 Pico 路径    |
| -------------------- | ----------------- |
| `src\app.py`         | `/app.py`         |
| `src\main.py`        | `/main.py`        |
| `src\lib\uc1701x.py` | `/lib/uc1701x.py` |
| `src\lib\sdcard.py`  | `/lib/sdcard.py`  |
| `src\lib\menu.py`    | `/lib/menu.py`    |
| `src\lib\reader.py`  | `/lib/reader.py`  |

> `main.py` 只有一行 `__import__('app')`，这是为了兼容 mpy-cross 编译。如果不想用编译，可以直接把 `app.py` 改名为 `main.py`。

### 9.4 Pico 文件结构

```
Pico:/
├── main.py          ← 入口（__import__('app')）
├── app.py           ← 主程序
└── lib/
    ├── uc1701x.py
    ├── sdcard.py
    ├── menu.py
    └── reader.py
```

### 9.5 重启 Pico

- Thonny 中按 `Ctrl+D` 软重启，或
- 拔 USB 再插

---

## 10. 首次开机

### 10.1 启动流程

```
USB 上电
   ↓
Pico 启动 main.py → app.py
   ↓
屏幕显示 "PicoReader" + "Mounting SD..."
   ↓
SD 卡挂载（1-2 秒）
   ↓
如果 SD 没准备好 → 显示 "SD MOUNT FAILED"
   ↓
挂载成功 → 进入主菜单
```

### 10.2 主菜单（12×12 字体，4 行）

```
┌──────────────────────────────┐
│  1.三国演义                  │  ← 选中行反色
│  2.红楼梦                    │
│  3.西游记                    │
│  >切换字体                   │
└──────────────────────────────┘
```

16×16 字体时显示 3 行。

- 上/下键：滚动选择
- OK：选中书籍 → 进入阅读，选中 `>切换字体` → 打开字体选择器

---

## 11. 日常使用

### 11.1 主菜单操作

| 操作 | 行为                                              |
| ---- | ------------------------------------------------- |
| 上键 | 选中上一行                                        |
| 下键 | 选中下一行                                        |
| OK   | 打开选中项（书籍 → 阅读，`>切换字体` → 字体选择） |

### 11.2 字体选择器

主菜单选中 `>切换字体` 按 OK：

```
┌──────────────────────────────┐
│  simsun12                    │  ← 选中行反色
│  simhei16                    │
│  simli12                     │
└──────────────────────────────┘
```

- 上/下键：滚动选择
- OK：确认并保存

### 11.3 阅读界面（12×12 字体示例）

```
┌──────────────────────────────┐
│ 滚滚长江东逝水                │
│ 浪花淘尽英雄                  │
│ 白发渔樵江渚上                │
│ 惯看秋月春风                  │
└──────────────────────────────┘
```

16×16 字体时每屏 3 行。

### 11.4 阅读操作

| 按键  | 短按       | 长按（>0.5 秒） |
| ----- | ---------- | --------------- |
| 上键  | 上一页     | —               |
| 下键  | 下一页     | —               |
| OK 键 | 返回主菜单 | 进入跳页模式    |

### 11.5 跳页模式

阅读时长按 OK 进入：

| 按键        | 作用               |
| ----------- | ------------------ |
| 上键        | 上一页             |
| 下键        | 下一页             |
| OK 短按     | 确认当前位置并退出 |
| OK 长按     | 取消跳页           |
| 无操作 5 秒 | 自动退出           |

### 11.6 断电续读

每本书的进度保存在：

```
/sd/books/book_0001.txt.prog
/sd/books/book_0002.txt.prog
```

文件内容就是当前页码（整数）。重启 Pico 时自动恢复。

---

## 12. 换书 / 换字体 / 换尺寸

### 12.1 加新书

1. 把 `.txt` 放到 `books/` 目录
2. 运行 `python build.py`
3. 把 `sd_card/` 下的内容拷到 SD 卡
4. 重启 Pico

### 12.2 删书

从 SD 卡 `/books/` 删除对应 `book_XXXX.txt` + `book_XXXX_*.idx` 即可。

### 12.3 换字体

从主菜单选中 **`>切换字体`** → 按 OK → 选字体 → OK 确认。
新字体自动保存到 `/sd/.settings`。

### 12.4 换尺寸

字体名后缀 `12` 或 `16` 决定尺寸：

- `simsun12.font` → 宋 12×12（每页 32 字，菜单 4 行）
- `simsun16.font` → 宋 16×16（每页 18 字，菜单 3 行）

---

## 13. 常见问题

### 13.1 屏幕全黑 / 无显示

- 检查 LCD VCC、GND 是否接好
- 检查 SCK、MOSI、CS、DC、RST 接线
- 在 Thonny Shell 看启动时是否有报错
- 屏幕对比度可以调 `app.py` 里的 `roughContrast` 和 `fineContrast`

### 13.2 启动显示 "SD MOUNT FAILED"

- **SD 卡必须 FAT32**
- 检查 VCC 接的是 3V3（不是 5V）
- 检查接线
- 换一张 SD 卡

### 13.3 菜单显示 "NO BOOKS"

- 运行 `python build.py` 生成文件名映射
- 检查 SD 卡 `/sd/books/` 里是否有 `book_XXXX.txt`
- 检查 `/sd/books.map` 是否存在

### 13.4 开书显示 "NO.IDX"

- 运行 `python build.py` 重新生成索引
- 确认 `.idx` 文件和书名匹配（`book_0001.txt` ↔ `book_0001_32.idx`）

### 13.5 进入阅读后字显示为空白 / 方块

- 字库没有该字（生僻字/异体字）
- 重新生成字库：`python build.py`

### 13.6 翻页卡顿

- 第一次访问新字会查字库（约 5-10ms），之后 LRU 缓存
- 推荐 Class 10 SD 卡

### 13.7 显示屏只有一部分

- **不要传 `width=96, height=48` 给 `UC1701x()`**
- 保持默认 `UC1701x(spi, a0=..., cs=..., rst=...)`（默认 buffer 128×64）
- 屏会自动显示前 96 列 48 行

### 13.8 按键没反应

- 按键一脚接 GPxx，另一脚必须接 GND
- 内部上拉已启用，不要外接上拉电阻

---

## 14. 文件结构总览

### 14.1 PC 端项目

```
电子书/                      # 项目根目录
├── build.py                 # PC 端一键构建（字库 + 书籍索引）
├── src/                     # Pico 端源码（用 Thonny 上传）
│   ├── main.py              # 启动入口（__import__('app')）
│   ├── app.py               # 主程序
│   └── lib/                 # MicroPython 模块
│       ├── uc1701x.py       # LCD 驱动（96×48）
│       ├── sdcard.py        # SD 卡驱动
│       ├── menu.py          # 菜单模块
│       └── reader.py        # 阅读器模块
├── Makefile                 # mpy-cross 编译（可选）
├── books/                   # 放原始 .txt（中文名）
├── sd_card/                 # build.py 输出（拷到 SD 卡）
│   ├── fonts/               # 字库
│   ├── books/               # book_XXXX.txt + .idx
│   └── books.map
├── README.md                # 本文档
└── AGENTS.md                # 开发者说明
```

### 14.2 Pico 端（烧录后）

```
Pico:/
├── main.py
├── app.py
└── lib/
    ├── uc1701x.py
    ├── sdcard.py
    ├── menu.py
    └── reader.py
```

### 14.3 SD 卡

```
SD:/
├── books/
│   ├── book_0001.txt
│   ├── book_0001_32.idx
│   ├── book_0001_18.idx
│   ├── book_0002.txt
│   ├── book_0002_32.idx
│   ├── book_0002_18.idx
│   ├── book_0001.txt.prog   ← 进度
│   └── ...
├── fonts/
│   ├── simsun12.font
│   ├── simsun16.font
│   ├── simhei12.font
│   ├── simhei16.font
│   ├── simli12.font
│   └── simli16.font
├── books.map                ← ASCII文件名|中文名
└── .settings                ← 当前字体偏好
```

---

## 15. 附录

### 附录 A：引脚速查

| Pico 引脚 | 用途             | 备注      |
| --------- | ---------------- | --------- |
| GP2       | SD SCK           | SPI0      |
| GP3       | SD MOSI          | SPI0      |
| GP4       | SD MISO          | SPI0      |
| GP5       | SD CS            | SPI0      |
| GP8       | LCD A0 (DC)      | SPI1      |
| GP9       | LCD CS           | SPI1      |
| GP10      | LCD SCK          | SPI1      |
| GP11      | LCD MOSI         | SPI1      |
| GP12      | LCD RST          | —         |
| GP16      | 下键/上一页      | PULL_UP   |
| GP20      | 上键/下一页      | PULL_UP   |
| GP26      | OK 键            | PULL_UP   |
| 3V3       | LCD VCC + SD VCC | 3.3V 供电 |
| GND       | 共地             | —         |

### 附录 B：每页字数对照

| 字号  | 列  | 行  | 每页 | 菜单行数 |
| ----- | --- | --- | ---- | -------- |
| 12×12 | 8   | 4   | 32   | 4        |
| 16×16 | 6   | 3   | 18   | 3        |

### 附录 C：性能参考

实测（Raspberry Pi Pico + Class 10 SD 卡）：

| 操作                   | 时间     |
| ---------------------- | -------- |
| 启动（挂 SD + 进菜单） | 1-2 秒   |
| 打开书                 | < 1 秒   |
| 翻页（缓存命中）       | < 50ms   |
| 翻页（缓存未命中）     | 50-150ms |
| 切换字体               | < 100ms  |
| 跳页                   | 50ms     |

### 附录 D：术语表

| 术语      | 含义                                       |
| --------- | ------------------------------------------ |
| LRU       | Least Recently Used，最近最少使用缓存淘汰  |
| 页偏移表  | 记录每页起始字节位置的数组，存为 .idx 文件 |
| 字库      | 字符 → 字模的映射集合                      |
| .font     | 字库文件（PC 端 build.py 生成）            |
| .idx      | 页偏移索引文件（PC 端 build.py 生成）      |
| books.map | 文件名映射表（ASCII名                      | 中文名） |
| MONO_VLSB | Vertical LSB，UC1701x 的位图存储格式       |
