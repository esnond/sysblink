# writing patches for sysblink

a patch is one c file in the patches directory. the installer inserts it
into engine.c and compiles the result, so a patch is a piece of a bigger
program, not a standalone one. this guide shows the contract, the helpers
and one worked out example.

## the contract

* the patch defines exactly one public entry point: int get_led_value(void)
* the engine calls it once per tick and expects a level from 0 to 100
* 0 means dark, 100 means full brightness, scaling to the led maximum is
  the engine job, do not do it twice
* the function must return fast, sleeping inside stalls the whole daemon
* keep state in static variables, the function runs again and again
* every symbol besides the entry point must be static

## what a patch can use

the engine defines these before the patch code:

* BLINK_HZ: the tick frequency in hertz, turn per second budgets into per
  tick budgets by division
* BLINK_PROC_ROOT and BLINK_SYS_ROOT: the roots of /proc and /sys as strings,
  glue your file paths onto them, the test suite points them at fixtures
* BLINK_DISK_DEVICE and BLINK_NET_IFACE: selection hints from sysblink.conf
  as strings, empty means the patch default, check them when your patch
  watches one device or interface out of many
* LED_COUNT, LED_PATHS, LED_MAXS: the led setup, a patch does not need
  them, one patch serves every led the daemon drives
* SLEEP_US: engine internals, usually left alone

shared thresholds live in patches/config.h, include it where needed:

    #include "config.h"

include the headers you use, the engine includes nothing on your behalf
beyond its own needs.

## measuring rates

a rate patch needs two samples and a guard against the very first call,
which has no previous sample to diff against:

    static uint64_t prev_total;
    static int primed;

    total = ...;
    if (!primed) {
        primed = 1;
        prev_total = total;
        return 0;
    }
    diff = total > prev_total ? total - prev_total : 0;
    prev_total = total;

two more rules keep the numbers honest:

* counters can go backwards after suspend, treat a negative difference
  as zero
* turn a budget from config.h into a per tick budget with BLINK_HZ, for
  example budget = NET_BYTES_PER_SEC / BLINK_HZ, then compare the diff

## the compile gate

the project builds with:

    cc -std=c99 -pedantic -Wall -Wextra -Werror -O2

so a patch must be clean iso c99 plus the small posix subset the engine
already enables: no gnu extensions, no new libraries, fixed width types
from stdint.h for counters, inttypes.h format macros for scanf and
printf, an explicit void in the parameter list of the entry point.

## a full example

patches/swap.c is a complete small patch, it shows opening a proc file,
parsing two fields with sscanf and the static state pattern:

    /*
     * sysblink patch: swap usage
     * example patch from docs/patches.md, reads SwapTotal and SwapFree
     * from /proc/meminfo and returns the share of swap in use
     */

    #include <inttypes.h>
    #include <stdio.h>
    #include <string.h>

    #define SWAP_LINE_SIZE     256
    #define SWAP_LABEL_SIZE    32
    #define SWAP_FIELDS_NEEDED 2

    int get_led_value(void)
    {
        uint64_t total = 0, free_pages = 0, value;
        char label[SWAP_LABEL_SIZE];
        char line[SWAP_LINE_SIZE];
        int found = 0;
        FILE *fp;

        fp = fopen("/proc/meminfo", "r");
        if (fp == NULL)
            return 0;
        while (found < SWAP_FIELDS_NEEDED && fgets(line, sizeof(line), fp) != NULL) {
            if (sscanf(line, "%31s %" SCNu64, label, &value) != 2)
                continue;
            if (strcmp(label, "SwapTotal:") == 0) {
                total = value;
                found++;
            } else if (strcmp(label, "SwapFree:") == 0) {
                free_pages = value;
                found++;
            }
        }
        fclose(fp);

        if (found < SWAP_FIELDS_NEEDED || total == 0)
            return 0;
        return (int)(100 * (total - free_pages) / total);
    }

to ship it, save the listing as patches/swap.c, it is already there, then
run make test. no swap on the machine means a dark led, the patch answers
zero.

## testing a patch

    make test

builds your patch into the engine with strict flags and runs two kinds of
headless sessions. the live ones use the real /proc and /sys and only
check that the numbers stay sane. the fixture ones point the engine at
tests/fixtures and expect exact values, so if your patch reads a source
that already has a fixture, its number is pinned. time based patches are
sampled for a bright phase instead. to watch a shipped patch live without
installing anything:

    python3 preview.py breathe --hz 60
    watch cat build/led_breathe.txt

## checklist

* the file defines get_led_value and nothing public besides it
* helpers and state are static, includes are minimal and present
* thresholds that mean something live in patches/config.h or as named
  macros at the top of the patch, with the unit in the comment
* comments say why, lowercase, without dashes
* make test passes with your patch in place
