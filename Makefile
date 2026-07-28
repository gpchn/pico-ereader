SHELL = cmd.exe
MPY_CROSS = mpy-cross
MPY_ARCH = armv6m
MPY_INT_BITS = 31
MPY_OPT = -O2

SOURCES = \
    app.py \
    lib/uc1701x.py \
    lib/sdcard.py \
    lib/menu.py \
    lib/reader.py

TARGETS = \
    dist/app.mpy \
    dist/lib/uc1701x.mpy \
    dist/lib/sdcard.mpy \
    dist/lib/menu.mpy \
    dist/lib/reader.mpy

MPY_FLAGS = -march=$(MPY_ARCH) -msmall-int-bits=$(MPY_INT_BITS) $(MPY_OPT)

.PHONY: all clean

all: $(TARGETS)

dist/lib:
	if not exist dist\lib mkdir dist\lib

dist/%.mpy: %.py | dist/lib
	$(MPY_CROSS) $(MPY_FLAGS) -o $@ $<

clean:
	if exist dist\lib\*.mpy del /Q dist\lib\*.mpy
	if exist dist\*.mpy del /Q dist\*.mpy
