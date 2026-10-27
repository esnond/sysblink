# sysblink: headless checks for every patch
# the compile gate lives in tests/run.sh: c99, pedantic, warnings as errors

.PHONY: all test clean

all: test

test:
	sh tests/run.sh

clean:
	rm -rf build
