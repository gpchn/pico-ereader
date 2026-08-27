# Pico 小说阅读器 + 背单词 — 从零开始完整使用教程

> 屏幕：LCD9648（UC1701x 控制器，**实际分辨率 96×48**）
> 主控：Raspberry Pi Pico
> 文本：SD 卡内任意 `.txt`（**仅 UTF-8**）
> 字库：PC 端 `build_sd.py` 预生成，运行时按需查表
> 索引：PC 端 `build_sd.py` 预生成页偏移表 + 文件名映射，开书无需等待
> 词库：PC 端 `build_sd.py` 从 **ECDICT** 预生成，背单词 / 查词用

每页字数：

| 字号    | 列 | 行 | 每页字数   |
| ----- | - | - | ------ |
| 12×12 | 8 | 4 | **32** |
| 16×16 | 6 | 3 | **18** |

***

## 目录

1. [项目简介](#1-项目简介)
2. [物料清单](#2-物料清单)
3. [硬件接线](#3-硬件接线)
4. [PC 端准备](#4-pc-端准备)
5. [生成字库与书籍索引](#5-生成字库与书籍索引)
6. [生成背单词词库（ECDICT）](#6-生成背单词词库ecdict)
7. [生成 SD 卡文件](#7-生成-sd-卡文件)
8. [SD 卡准备](#8-sd-卡准备)
9. [烧录 MicroPython 固件](#9-烧录-micropython-固件)
10. [上传代码到 Pico](#10-上传代码到-pico)
11. [首次开机](#11-首次开机)
12. [日常使用](#12-日常使用)
13. [换书 / 换字体 / 换词库](#13-换书--换字体--换词库)
14. [常见问题](#14-常见问题)
15. [文件结构总览](#15-文件结构总览)
16. [附录](#16-附录)

***

## 1. 项目简介

### 1.1 它能做什么

把 SD 卡里任意多本中文 txt 小说装进 Raspberry Pi Pico，LCD9648（96×48）屏幕阅读，并附带一个**离线背单词 / 查词系统**（基于 ECDICT 开源词典）：

- **主页即背单词界面**：列出主牌组（高考 / 四级 / 生词本，括号为到期数），末尾挂 `更多分级` / `电子书` / `切换字体` / `按键说明` 子菜单入口
- **3 个按键**：上 / 下 / OK（短按与长按功能不同）
- **电子书**：翻页阅读、断电续读、自动阅读（长按「下」逐行滚动）、书签；长按「上」退出阅读回书架
- **背单词**：词卡记忆 + 间隔重复（Leitner）——顺序背 / 乱序背，正背面统一按键，生词本
- **断电续读 / 续背**：每本书、每个牌组的进度独立保存
- **ASCII 文件名**：避开 MicroPython 的 FAT32 中文编码 bug，中文名通过 `books.map` 元数据文件显示
- **音标正常显示**：字库覆盖 IPA / 希腊 / 西里尔，构建时自动从西文字体补字形

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
┌──── PC ────────────────────────────┐
│  build_sd.py（字库+书籍+词库一键） │  → sdcard/fonts/*.font
│                                    │  → sdcard/books/*.txt + *.idx + books.map
│                                    │  → sdcard/dict/（master.* + decks/ + progress/）
└────────────────────────────────────┘
          ↓
┌──── SD 卡 ─────────────────────────┐
│  /fonts/simsun12.font              │  ← 字库（PC 预生成）
│  /books/book_0001.txt              │  ← ASCII 文件名（无编码问题）
│  /books/book_0001_32.idx           │  ← 页偏移索引
│  /books.map                        │  ← book_0001.txt|三国演义
│  /books/book_0001.txt.prog         │  ← 阅读进度
│  /dict/master.entryoff             │  ← 词库偏移表（O(1) 定位）
│  /dict/master.index                │  ← 词库索引（[len][word][dataoff]）
│  /dict/master.dir                  │  ← 首字母窗口目录
│  /dict/master.data                 │  ← 词条记录
│  /dict/decks/cet4.bin              │  ← 牌组词表
│  /dict/progress/cet4.bin           │  ← 牌组进度
│  /.settings                        │  ← 当前字体偏好
└────────────────────────────────────┘
          ↑ 读
     ┌────┴────┐
     │   Pico  │  开书直接读 .idx（无需等待）
     │         │  → 每次翻页只读 32~64 字节
     │         │  → 查词经 master.dir 窗口 + 二分（不载入整表）
     │         │  → 字模 LRU 缓存（200 字）
     └────┬────┘
          ↓ 写
     ┌────┴────┐
     │  LCD    │  96×48
     └─────────┘
```

> 推荐顺序：把 `books/` 放好小说、`ECDICT/` 放好 `ecdict.csv` 后，只需运行 `python build_sd.py` 一次即可生成全部内容。

***

## 2. 物料清单

| 物料                  | 数量 | 备注                     |
| ------------------- | -- | ---------------------- |
| Raspberry Pi Pico   | 1  | 任何版本（Pico / Pico W 均可） |
| LCD9648 屏幕          | 1  | UC1701x 驱动，**96×48**   |
| Micro SD 卡模块        | 1  | SPI 接口，**3.3V**（不是 5V） |
| Micro SD 卡          | 1  | 4-32GB，**FAT32**       |
| 轻触按键                | 3  | 6mm 微型两脚按键             |
| 杜邦线                 | 若干 | 母对母 + 母对公              |
| 面包板                 | 1  | 400 孔或 830 孔           |
| Micro-USB / USB-C 线 | 1  | 给 Pico 供电 + 烧录         |

> 屏幕和 SD 模块必须是 **3.3V** 电平。Pico 的 GPIO 是 3.3V，所以直接连没问题。

***

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
    上 键 ──┤ GP16           GP20 ├── 下 键
            │                GP26 ├── OK 键
            │ 3V3             GND │
            └─────────────────────┘
```

### 3.2 LCD9648 接线（SPI1）

| LCD 引脚     | Pico 引脚  | 说明        |
| ---------- | -------- | --------- |
| VCC        | **3V3**  | 3.3V 供电   |
| GND        | **GND**  | 地         |
| SCK (SCL)  | **GP10** | SPI1 SCK  |
| SDA (MOSI) | **GP11** | SPI1 MOSI |
| CS         | **GP9**  | 片选        |
| DC (A0)    | **GP8**  | 数据/命令选择   |
| RST        | **GP12** | 复位        |
| BL (LED)   | 3V3 或悬空  | 背光（可选）    |

### 3.3 SD 卡模块接线（SPI0）

| SD 引脚 | Pico 引脚 | 说明              |
| ----- | ------- | --------------- |
| VCC   | **3V3** | 3.3V 供电（不要接 5V） |
| GND   | **GND** | 地               |
| SCK   | **GP2** | SPI0 SCK        |
| MOSI  | **GP3** | SPI0 MOSI       |
| MISO  | **GP4** | SPI0 MISO       |
| CS    | **GP5** | 片选              |

### 3.4 按键接线

每个按键**一脚接 GPxx，另一脚接 GND**。MicroPython 内部上拉，无需外接电阻。

| 按键   | Pico 引脚  | 菜单功能    | 阅读功能              |
| ---- | -------- | ------- | ----------------- |
| 上键   | **GP16** | 上移      | 上一页 / 长按退出阅读回书架   |
| 下键   | **GP20** | 下移      | 下一页 / 长按切换自动阅读    |
| OK 键 | **GP26** | 确认 / 打开 | 短按书签界面 / 长按添加删除书签 |

> 注意：上键是 **GP16**、下键是 **GP20**（不要接反，否则翻页方向会反）。

### 3.5 接线注意事项

> - **共地**：所有 GND 必须连到一起（Pico、LCD、SD、按键）
> - **SD 卡必须 3.3V**——5V 会烧 SD 卡
> - **杜邦线 < 20cm**：SPI 容易受干扰
> - **不要在 Pico 通电时插拔 SD 卡**

***

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

| 系统      | 字体路径                                  |
| ------- | ------------------------------------- |
| Windows | `C:\Windows\Fonts\simsun.ttc`（宋体）     |
| Windows | `C:\Windows\Fonts\simhei.ttf`（黑体）     |
| Windows | `C:\Windows\Fonts\SIMLI.TTF`（隶书）      |
| Linux   | `sudo apt install fonts-wqy-microhei` |
| macOS   | `/System/Library/Fonts/PingFang.ttc`  |

### 4.5 准备 ECDICT 词库源数据

背单词 / 查词功能需要 **ECDICT**（开源英汉词典，约 65MB CSV）：

- 下载 `ecdict.csv`（仓库 <https://github.com/skywind3000/ECDICT>，或 `stardict.csv` 改名）
- 放到项目下的 `ECDICT/` 目录：

```
pico-ebook/
└── ECDICT/
    └── ecdict.csv
```

> 单词统一 lower() 且只保留纯 ASCII 文本（设备端查词输入都是英文）。
> 中文释义与**音标都正常显示**：字库覆盖了 IPA / 希腊 / 西里尔区间，构建字库时对中文
> 字体缺失的 IPA 字形会自动从西文字体（Arial 等）补齐，无需额外处理。

***

## 5. 生成字库与书籍索引

> 现在字库、书籍、词库都由同一个工具 `build_sd.py` 一键完成（见第 6 节）。
> 本节只说明其中字库与书籍部分。

### 5.1 打开命令行，进入项目目录

```bash
cd pico-ebook
```

### 5.2 一键构建（字库 + 书籍索引）

```bash
python build_sd.py
```

一次完成三件事：

1. 生成全部字库（需先 `pip install Pillow`，见 4.2）
2. 把 `books/` 里的小说重命名为 ASCII 文件名（`book_0001.txt`、`book_0002.txt`…），并为每种字号（12×12 和 16×16）生成 `.idx` 页偏移索引
3. 生成 `books.map` 元数据文件（记录 ASCII 名←→中文名映射）

会输出类似：

```
[simsun12.font] 字体=C:/Windows/Fonts/simsun.ttc  尺寸=12x12
  渲染: 成功=28895（回退补字=612） 缺字形留空=215
  写入: sdcard\fonts\simsun12.font (809084 字节)
...
生成完成。共 6 个字体文件，目录：sdcard/fonts/
```

> 「回退补字」= 主字体缺失、从西文字体（Arial 等）补齐的字形数（主要是 IPA 音标 / 希腊 / 西里尔）。

生成文件：

```
sdcard/fonts/
├── simsun12.font   宋体 12×12 (~790KB)
├── simsun16.font   宋体 16×16 (~1MB)
├── simyou12.font   幼圆 12×12
├── simyou16.font   幼圆 16×16
├── simhei12.font   黑体 12×12
├── simhei16.font   黑体 16×16
└── ...             其余取决于本机已安装的字体（见 build_sd.py 顶部 FONTS）
```

### 5.3 增量构建

`build_sd.py` 默认**增量构建**，只重建有变化的部分，学习 / 阅读进度不受影响：

- **字库**：仅当源字体文件比成品新、且字符集区间有变化时才重新渲染
- **书籍**：仅当源 `.txt` 比成品新时才重新切页，并尽量复用原有 `book_XXXX` 编号（断电续读进度按文件名绑定，编号不变进度就还在）
- **词库**：仅当 `ECDICT/ecdict.csv` 变化时才重建

唯一参数 `--force` 强制全量重建（会重置除生词本外的学习进度）。

### 5.4 字符集说明

字体文件覆盖的字符范围（与 `reader.py` 的 `_RANGES` 严格一致，改任一侧都要同步）：

- ASCII 可打印（0x20-0x7E）
- **IPA / 拉丁扩展 / 希腊 / 西里尔**（音标，0x00A0-0x0500）
- 通用标点（0x2000-0x206F，含 — – … “” ‘’ 等非全角标点）
- CJK 标点（0x3000-0x303F）
- CJK 扩展 A（0x3400-0x4DBF）
- **CJK 基本**（0x4E00-0x9FFF，20902 字）
- 全角 ASCII（0xFF00-0xFFEF）

> 几乎所有标准中文小说和音标符号都在此范围内。极少数生僻字/异体字会显示为空白。

***

## 6. 生成背单词词库（ECDICT）

> 这一步只用于背单词 / 查词功能。不生成也能正常读小说，只是主页「背单词」会无词可用。
> 词库由同一个 `build_sd.py` 生成（见第 5 节），无需单独跑脚本。

### 6.1 一键构建（词库）

先把 `ecdict.csv` 放到 `ECDICT/`（见 4.5），然后直接：

```bash
python build_sd.py
```

会读取 `ECDICT/ecdict.csv`，输出到 `sdcard/dict/`：

- `master.entryoff` / `master.index` / `master.dir` / `master.troff` / `master.data`：主词库（空间换时间的紧凑二进制布局，O(1) 定点查找，不占 Pico 内存）
- `decks/*.bin`：各牌组的单词下标表，按学习顺序
- `progress/*.bin`：各牌组的学习进度（Leitner 间隔重复）
- `unknown.bin`：空生词本，设备端累积

生成时会打印每个牌组的词数（`ecdict.csv` 未变化时词库整段跳过）：

```
[3/3] 背单词词库...
词库无需更新（ecdict.csv 未变化），跳过
```

### 6.2 牌组说明

牌组来自 ECDICT 的 `tag` 字段（真实 tag：`zk` 中考 / `gk` 高考 / `cet4` / `cet6` / `ky` 考研 / `ielts` / `toefl` / `gre`）与词频：

| 牌组名       | 来源               | 主页位置    |
| --------- | ---------------- | ------- |
| `gk`      | 高考词汇（tag 含 `gk`） | 主牌组     |
| `cet4`    | 四级词汇（tag 含 cet4） | 主牌组     |
| `unknown` | 生词本（空，设备端累积）     | 主牌组     |
| `cet6`    | 六级词汇             | 「更多分级」里 |
| `kaoyan`  | 考研词汇（tag 含 `ky`） | 「更多分级」里 |
| `ielts`   | 雅思               | 「更多分级」里 |
| `toefl`   | 托福               | 「更多分级」里 |
| `gre`     | GRE              | 「更多分级」里 |
| `freq`    | 当代词频 Top 5000    | 「更多分级」里 |

### 6.3 重新生成 / 增量更新

- 词库默认增量：`ECDICT/ecdict.csv` 未变化时跳过；变化时才重建主词库与牌组。
- 牌组进度（`progress/*.bin`）在设备端生成，PC 端不写；增量重建不会动它，但若单词下标变化，旧进度可能错位——此时删掉对应的 `progress/<name>.bin` 让其重建即可。
- 要强制重建（同时重置除生词本外的学习进度）：`python build_sd.py --force`。

***

## 7. 生成 SD 卡文件

### 7.1 准备小说

把 `.txt` 文件放到项目下的 `books/` 目录：

```
pico-ebook/
└── books/
    ├── 三国演义.txt
    └── 红楼梦.txt
```

### 7.2 输出结构

运行一次 `python build_sd.py` 后，`sdcard/` 目录结构如下：

```
sdcard/
├── fonts/
│   ├── simsun12.font          ← 字库（simsun/simyou/simhei 各 12/16）
│   └── ...
├── books/
│   ├── book_0001.txt          ← ASCII 文件名，Pico 无编码问题
│   ├── book_0001_32.idx       ← 页偏移索引（12×12 字体用）
│   ├── book_0001_18.idx       ← 页偏移索引（16×16 字体用）
│   ├── book_0002.txt
│   ├── book_0002_32.idx
│   ├── book_0002_18.idx
│   └── ...
├── dict/
│   ├── master.entryoff        ← 词库偏移表
│   ├── master.index           ← 词库索引
│   ├── master.dir             ← 首字母窗口目录
│   ├── master.troff           ← 翻译偏移表（O(1) 直取）
│   ├── master.data            ← 词条记录
│   ├── decks/
│   │   ├── gk.bin              ← 各牌组词表
│   │   ├── cet4.bin
│   │   ├── cet6.bin
│   │   ├── kaoyan.bin
│   │   ├── ielts.bin
│   │   ├── toefl.bin
│   │   ├── gre.bin
│   │   ├── freq.bin
│   │   └── unknown.bin
│   └── progress/               ← 设备端运行时生成
└── books.map                  ← book_0001.txt|三国演义
```

***

## 8. SD 卡准备

### 8.1 格式化（重要！）

> **必须 FAT32**。如果是新卡或 exFAT，Pico 读不到。

1. 下载 **SD Card Formatter**：<https://www.sdcard.org/downloads/formatter/>
2. 插 SD 卡到电脑
3. 选 SD 卡 → **Format**
4. **Format Type = Quick**
5. **Format Size Adjustment = ON**
6. 开始

### 8.2 复制文件

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
├── dict/
│   ├── master.entryoff
│   ├── master.index
│   ├── master.dir
│   ├── master.data
│   ├── decks/
│   └── unknown.bin
└── books.map
```

> 目录名 `books/`、`fonts/`、`dict/` 必须小写。

***

## 9. 烧录 MicroPython 固件

### 9.1 下载固件

- 地址：<https://micropython.org/download/RPI_PICO/>
- 推荐：**`RPI_PICO-20240602-v1.23.0.uf2`**（或更新稳定版）
- Pico W 用户：选 `RPI_PICO_W-...uf2`

### 9.2 进入 BOOT 模式

1. **按住 Pico 板上的白色 BOOTSEL 按钮**
2. **不松开**，用 USB 线把 Pico 接到电脑
3. 松开按钮
4. 电脑会弹出一个名为 `RPI-RP2` 的 U 盘

### 9.3 复制固件

把下载的 `.uf2` 文件直接拖到 `RPI-RP2` U 盘。

***

## 10. 上传代码到 Pico

### 10.1 打开 Thonny

- 右上角选 **MicroPython (Raspberry Pi Pico)**
- View → Files，打开文件面板

### 10.2 创建 /lib 目录

在 Pico 文件树根目录右键 → **New directory** → 命名为 `lib`

### 10.3 复制文件

| PC 端路径               | 拖到 Pico 路径        |
| -------------------- | ----------------- |
| `src\app.py`         | `/app.py`         |
| `src\main.py`        | `/main.py`        |
| `src\lib\uc1701x.py` | `/lib/uc1701x.py` |
| `src\lib\sdcard.py`  | `/lib/sdcard.py`  |
| `src\lib\menu.py`    | `/lib/menu.py`    |
| `src\lib\reader.py`  | `/lib/reader.py`  |
| `src\lib\vocab.py`   | `/lib/vocab.py`   |

> `main.py` 只有一行 `__import__('app')`，这是为了兼容 mpy-cross 编译。如果不想用编译，可以直接把 `app.py` 改名为 `main.py`。

### 10.4 Pico 文件结构

```
Pico:/
├── main.py          ← 入口（__import__('app')）
├── app.py           ← 主程序
└── lib/
    ├── uc1701x.py
    ├── sdcard.py
    ├── menu.py
    ├── reader.py
    └── vocab.py
```

### 10.5 重启 Pico

- Thonny 中按 `Ctrl+D` 软重启，或
- 拔 USB 再插

***

## 11. 首次开机

### 11.1 启动流程

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
挂载成功 → 进入主页菜单
```

### 11.2 主页菜单（背单词界面，12×12 字体，4 行）

开机即进入「背单词」界面：先列出三个主牌组（高考 / 四级 / 生词本），末尾挂四个子菜单入口。

```
┌──────────────────────────────┐
│  ▸高考(12)                   │  ← 牌组名，括号内是到期数
│   四级(80)                   │
│   生词本(5)                  │
│   更多分级                   │  ← 子菜单：六级/考研/雅思/托福/GRE/高频词
│   电子书                     │  ← 子菜单：进入书籍列表
│   切换字体                   │  ← 子菜单：字体选择器
│   按键说明                   │  ← 子菜单：按键用法帮助
└──────────────────────────────┘
```

- 上/下键：在牌组 / 子菜单项之间移动
- OK 短按：进入选中牌组 → 动作菜单（顺序背 / 乱序背 / 查看进度，生词本另有「清空生词本」）；选中「更多分级 / 电子书 / 切换字体 / 按键说明」进入对应子菜单

> 想看小说：在主页选「电子书」即可，它是背单词界面的一个子菜单项。

### 11.3 电子书子菜单

选中「电子书」按 OK，进入书籍列表：

```
┌──────────────────────────────┐
│  ▸三国演义                   │
│   红楼梦                     │
│   西游记                     │
└──────────────────────────────┘
```

- 上/下键：滚动选择
- OK：选中书籍 → 进入阅读
- 上键长按：返回背单词主页（阅读中长按「上」先退回本书架）

***

## 12. 日常使用

### 12.1 背单词主页操作

| 操作    | 行为                                   |
| ----- | ------------------------------------ |
| 上键    | 选中上一行（牌组 / 更多分级 / 电子书 / 切换字体 / 按键说明） |
| 下键    | 选中下一行                                |
| OK 短按 | 进入选中牌组 / 子菜单                         |

### 12.2 字体选择器

主菜单选中 `切换字体` 按 OK：

```
┌──────────────────────────────┐
│  simsun12                    │  ← 选中行反色
│  simhei16                    │
│  simli12                     │
└──────────────────────────────┘
```

- 上/下键：滚动选择
- OK：确认并保存

### 12.3 阅读界面（12×12 字体示例）

```
┌──────────────────────────────┐
│ 滚滚长江东逝水               │
│ 浪花淘尽英雄                 │
│ 白发渔樵江渚上               │
│ 惯看秋月春风                 │
└──────────────────────────────┘
```

16×16 字体时每屏 3 行。

### 12.4 阅读操作

| 按键   | 短按     | 长按（约 0.4 秒）     |
| ---- | ------ | --------------- |
| 上键   | 上一页    | **退出阅读，返回书架**   |
| 下键   | 下一页    | **开启 / 关闭自动阅读** |
| OK 键 | 打开书签界面 | 给当前页添加 / 删除书签   |

### 12.5 自动阅读

阅读时长按「下」开启（再长按一次关闭，屏幕会提示「自动阅读 / 手动翻页」）：

- 屏幕按**固定速度自动逐行向上滚动**（每行约 3 秒，速度写死在 `reader.py` 的 `AUTO_SCROLL_MS`）
- 阅读进度会随滚动自动保存；短按上/下可临时手动翻页，滚动从新页顶部继续
- 滚动到书末自动关闭

### 12.6 书签

阅读时 OK 长按给**当前页**添加书签（再长按一次则删除），屏幕提示「已加书签 / 已删书签」。

OK 短按打开**书签界面**，列出所有书签页：

| 按键     | 作用         |
| ------ | ---------- |
| 上 / 下键 | 选择书签       |
| OK 短按  | 跳到该书签页继续阅读 |
| 上键长按   | 返回阅读       |

书签保存在 `/sd/books/<书名>.txt.bmk`（每行一个页码），换书后各自独立。

### 12.7 背单词

主页选一个牌组按 OK → 动作菜单（**顺序背 / 乱序背 / 查看进度**；生词本另有「清空生词本」）→ 选「顺序背」或「乱序背」进入单词卡学习。

- **顺序背**：按牌组顺序逐个学习（跳过未到期的词）
- **乱序背**：对整副牌组打乱顺序随机学，同样跳过未到期的词（随机范围覆盖全牌组，而非仅到期词）

每张**单词卡**分正背面：

```
┌──────────────────────────────┐
│  perceive                    │  ← 正面：单词 + 音标（若有）
│  [pə'siːv]                   │
│  ?                        ✓  │  ← 左下 ? = 不认识，右下 ✓ = 认识
├──────────────────────────────┤
│  perceive                    │  ← 翻面后：释义 + 词形
│  v. 察觉；理解               │
└──────────────────────────────┘
```

**正背面按键一致**：

| 按键    | 作用                        |
| ----- | ------------------------- |
| 上（短）  | **不认识** → 评分（降级 box）并进下一张 |
| 下（短）  | **认识** → 评分（升级 box）并进下一张  |
| OK 短按 | 切换正背面（正面单词 ↔ 背面释义）        |
| OK 长按 | 加入 / 删除生词本（不评分不翻面，留在当前词）  |
| 上（长）  | 退出学习，返回动作菜单               |

**生词本（unknown）**：与普通牌组一样支持顺序背 / 乱序背 / 查看进度，另有「清空生词本」；学习时随时 OK 长按把当前词加进 / 移出生词本，从生词本删词会立即从学习队列移除。

> 间隔重复用 **Leitner** 法：`box 0` 始终到期（每次都出现），`box` 越高，再次出现间隔越长（约 1 / 1 / 3 / 7 / 15 / 31 次复习）。无 RTC 时用相对计数。

### 12.8 断电续读 / 续背

- 书籍进度：`/sd/books/book_XXXX.txt.prog`（当前页码整数）
- 书签：`/sd/books/book_XXXX.txt.bmk`（每行一个页码，阅读时 OK 长按增删）
- 牌组进度：`/sd/dict/progress/<name>.bin`（counter + 每词 box + due）
- 生词本：`/sd/dict/unknown.bin`（设备端累积）

重启 Pico 自动恢复，无需重新设置。

***

## 13. 换书 / 换字体 / 换词库

### 13.1 加新书

1. 把 `.txt` 放到 `books/` 目录
2. 运行 `python build_sd.py`
3. 把 `sd_card/` 下的内容拷到 SD 卡
4. 重启 Pico

### 13.2 删书

从 SD 卡 `/books/` 删除对应 `book_XXXX.txt` + `book_XXXX_*.idx` 即可。

### 13.3 换字体

从主页选中 **`切换字体`** → 按 OK → 选字体 → OK 确认。
新字体自动保存到 `/sd/.settings`。

### 13.4 换尺寸

字体名后缀 `12` 或 `16` 决定尺寸：

- `simsun12.font` → 宋 12×12（每页 32 字，菜单 4 行）
- `simsun16.font` → 宋 16×16（每页 18 字，菜单 3 行）

### 13.5 重建 / 更新词库

1. 更新 `ECDICT/ecdict.csv`（如需）
2. 运行 `python build_sd.py`（词库在 csv 未变时自动跳过）
3. 把 `sd_card/dict/` 下的内容拷到 SD 卡 `/dict/`
4. 重启 Pico

> 重建词库不影响已有的 `progress/*.bin` 与 `unknown.bin`（设备端生成）。若发现某牌组进度错乱，删掉对应的 `progress/<name>.bin` 让其重建。

***

## 14. 常见问题

### 14.1 屏幕全黑 / 无显示

- 检查 LCD VCC、GND 是否接好
- 检查 SCK、MOSI、CS、DC、RST 接线
- 在 Thonny Shell 看启动时是否有报错
- 屏幕对比度可以调 `app.py` 里的 `roughContrast` 和 `fineContrast`

### 14.2 启动显示 "SD MOUNT FAILED"

- **SD 卡必须 FAT32**
- 检查 VCC 接的是 3V3（不是 5V）
- 检查接线
- 换一张 SD 卡

### 14.3 菜单显示 "NO BOOKS"

- 运行 `python build_sd.py` 生成文件名映射
- 检查 SD 卡 `/sd/books/` 里是否有 `book_XXXX.txt`
- 检查 `/sd/books.map` 是否存在

### 14.4 开书显示 "NO.IDX"

- 运行 `python build_sd.py` 重新生成索引
- 确认 `.idx` 文件和书名匹配（`book_0001.txt` ↔ `book_0001_32.idx`）

### 14.5 背单词里某牌组是空的 / 查词无结果

- 运行 `python build_sd.py` 生成词库，并把 `sd_card/dict/` 拷到 SD 卡 `/dict/`
- 确认 `ECDICT/ecdict.csv` 存在（默认位置 `ECDICT/` 下）

### 14.6 查词时音标显示为空白 / 豆腐块

- 正常安装后音标（IPA / 希腊 / 西里尔）应能显示。若仍是空白/方块：
  1. 确认 SD 卡字库是**重新生成**的（旧字库不含 IPA 区间）
  2. 重新生成字库并覆盖 SD 卡 `/fonts/`：`python build_sd.py`
  3. 构建时主字体（simsun/simhei 等）缺 IPA 字形会自动从西文字体（Arial 等）补齐，无需手动处理

### 14.7 进入阅读后字显示为空白 / 方块

- 字库没有该字（生僻字/异体字）
- 重新生成字库：`python build_sd.py`

### 14.8 翻页卡顿

- 第一次访问新字会查字库（约 5-10ms），之后 LRU 缓存
- 推荐 Class 10 SD 卡

### 14.9 显示屏只有一部分

- **不要传** **`width=96, height=48`** **给** **`UC1701x()`**
- 保持默认 `UC1701x(spi, a0=..., cs=..., rst=...)`（默认 buffer 128×64）
- 屏会自动显示前 96 列 48 行

### 14.10 按键没反应 / 方向反了

- 按键一脚接 GPxx，另一脚必须接 GND
- 内部上拉已启用，不要外接上拉电阻
- **上键 = GP16、下键 = GP20**：接反会导致翻页方向反

***

## 15. 文件结构总览

### 15.1 PC 端项目

```
pico-ebook/                 # 项目根目录
├── build_sd.py              # PC 端一键构建（字库 + 书籍索引 + 词库）
├── ECDICT/
│   └── ecdict.csv           # 词典源数据（需自行下载）
├── src/                     # Pico 端源码（用 Thonny 上传）
│   ├── main.py              # 启动入口（__import__('app')）
│   ├── app.py               # 主程序（主页菜单 + 主循环）
│   └── lib/                 # MicroPython 模块
│       ├── uc1701x.py       # LCD 驱动（96×48）
│       ├── sdcard.py        # SD 卡驱动
│       ├── menu.py          # 菜单模块（含字体选择）
│       ├── reader.py        # 阅读器模块（翻页 / 自动阅读 / 书签）
│       └── vocab.py         # 背单词 / 查词模块
├── Makefile                 # mpy-cross 编译（可选）
├── books/                   # 放原始 .txt（中文名）
├── sd_card/                 # 构建输出（拷到 SD 卡）
│   ├── fonts/               # 字库
│   ├── books/               # book_XXXX.txt + .idx
│   ├── dict/                # 词库（master.* + decks/ + progress/ + unknown.bin）
│   └── books.map
├── README.md                # 本文档
└── AGENTS.md                # 开发者说明
```

### 15.2 Pico 端（烧录后）

```
Pico:/
├── main.py
├── app.py
└── lib/
    ├── uc1701x.py
    ├── sdcard.py
    ├── menu.py
    ├── reader.py
    └── vocab.py
```

### 15.3 SD 卡

```
SD:/
├── books/
│   ├── book_0001.txt
│   ├── book_0001_32.idx
│   ├── book_0001_18.idx
│   ├── book_0001.txt.prog   ← 进度
│   └── ...
├── fonts/
│   ├── simsun12.font
│   ├── simsun16.font
│   ├── simhei12.font
│   ├── simhei16.font
│   ├── simli12.font
│   └── simli16.font
├── dict/
│   ├── master.entryoff      ← 词库偏移表
│   ├── master.index         ← 词库索引
│   ├── master.dir           ← 首字母窗口
│   ├── master.troff         ← 翻译偏移表
│   ├── master.data          ← 词条记录
│   ├── decks/               ← 各牌组词表
│   ├── progress/            ← 学习进度（设备端生成）
│   └── unknown.bin          ← 生词本
├── books.map                ← ASCII文件名|中文名
└── .settings                ← 当前字体偏好
```

***

## 16. 附录

### 附录 A：引脚速查

| Pico 引脚 | 用途               | 备注       |
| ------- | ---------------- | -------- |
| GP2     | SD SCK           | SPI0     |
| GP3     | SD MOSI          | SPI0     |
| GP4     | SD MISO          | SPI0     |
| GP5     | SD CS            | SPI0     |
| GP8     | LCD A0 (DC)      | SPI1     |
| GP9     | LCD CS           | SPI1     |
| GP10    | LCD SCK          | SPI1     |
| GP11    | LCD MOSI         | SPI1     |
| GP12    | LCD RST          | —        |
| GP16    | 上键/上一页           | PULL\_UP |
| GP20    | 下键/下一页           | PULL\_UP |
| GP26    | OK 键             | PULL\_UP |
| 3V3     | LCD VCC + SD VCC | 3.3V 供电  |
| GND     | 共地               | —        |

### 附录 B：每页字数对照

| 字号    | 列 | 行 | 每页 | 菜单行数 |
| ----- | - | - | -- | ---- |
| 12×12 | 8 | 4 | 32 | 4    |
| 16×16 | 6 | 3 | 18 | 3    |

### 附录 C：性能参考

实测（Raspberry Pi Pico + Class 10 SD 卡）：

| 操作             | 时间       |
| -------------- | -------- |
| 启动（挂 SD + 进菜单） | 1-2 秒    |
| 打开书            | < 1 秒    |
| 翻页（缓存命中）       | < 50ms   |
| 翻页（缓存未命中）      | 50-150ms |
| 切换字体           | < 100ms  |
| 打开书签界面         | < 100ms  |
| 查词（定点 seek）    | < 30ms   |

### 附录 D：术语表

| 术语           | 含义                             | <br /> |
| ------------ | ------------------------------ | :----- |
| LRU          | Least Recently Used，最近最少使用缓存淘汰 | <br /> |
| 页偏移表         | 记录每页起始字节位置的数组，存为 .idx 文件       | <br /> |
| 字库           | 字符 → 字模的映射集合                   | <br /> |
| .font        | 字库文件（PC 端 build\_sd.py 生成）     | <br /> |
| .idx         | 页偏移索引文件（PC 端 build\_sd.py 生成）  | <br /> |
| books.map    | 文件名映射表（ASCII名                  | 中文名）   |
| MONO\_VLSB   | Vertical LSB，UC1701x 的位图存储格式   | <br /> |
| ECDICT       | 开源英汉词典（ecdict.csv），背单词词源       | <br /> |
| Leitner      | 间隔重复记忆法，box 越高复习间隔越长           | <br /> |
| master.\*    | 词库主文件（PC 端 build\_sd.py 生成）    | <br /> |
| decks/\*.bin | 牌组词表（单词在 master 中的下标）          | <br /> |

