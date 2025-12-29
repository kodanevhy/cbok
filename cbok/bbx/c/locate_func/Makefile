CC				:= gcc
BUILD_VERSION   := 1.0.0

TARGET_PATH 	:= bin

CPU_ARCH 		:= $(shell uname -m)
TARGET_API 		:= locate-func-${CPU_ARCH}

build: clean
	mkdir -p ${TARGET_PATH}
	${CC} main.c -o ${TARGET_PATH}/${TARGET_API}

clean:
	rm -rf ${TARGET_PATH}
