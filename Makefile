SHELL = cmd.exe
MPY_CROSS = mpy-cross
MPY_FLAGS = -O2

SOURCES = \
    src/app.py \
    src/lib/uc1701x.py \
    src/lib/sdcard.py \
    src/lib/menu.py \
    src/lib/reader.py \
    src/lib/vocab.py

TARGETS = \
    dist/app.mpy \
    dist/lib/uc1701x.mpy \
    dist/lib/sdcard.mpy \
    dist/lib/menu.mpy \
    dist/lib/reader.mpy \
    dist/lib/vocab.mpy

.PHONY: all clean

all: $(TARGETS)

dist/lib:
	if not exist dist\lib mkdir dist\lib

$(TARGETS): dist/%.mpy: src/%.py | dist/lib
	$(MPY_CROSS) $(MPY_FLAGS) -o $@ $<

clean:
	if exist dist\lib\*.mpy del /Q dist\lib\*.mpy
	if exist dist\*.mpy del /Q dist\*.mpy
