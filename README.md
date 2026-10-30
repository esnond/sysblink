# sysblink

[![ci](https://github.com/esnond/sysblink/actions/workflows/ci.yml/badge.svg)](https://github.com/esnond/sysblink/actions/workflows/ci.yml)

sysblink turns a spare led on your machine into a live system meter. you pick a
led and a patch, the installer renders a small c daemon from a template,
compiles it and hands it to your init system. after that the led shows cpu
load, memory, disk io, network traffic, temperature or whatever else a
patch watches, and it keeps doing it across reboots.

written with ai assistance.

project page: https://esnond.github.io/sysblink/

## requirements

* linux with sysfs leds in /sys/class/leds
* a c compiler: cc, gcc or clang
* python3 for the installer
* root only for installing or removing services

## quick start

    cd sysblink
    python3 sysblink.py

the installer asks the language, lists the leds it can write to, lists the
patches, asks for the update frequency and compiles the daemon into build/.
answering yes to the service question registers it with the detected init
system, that step needs sudo. if you hate menus, everything has a flag,
see below.

## a config file

answering the same three questions every time gets old, so the installer
reads defaults from sysblink.conf next to sysblink.py. the shipped file is called
sysblink.conf.example, copy it and trim:

    # sysblink.conf
    lang = ru
    hz = 20
    init = systemd
    led = input13::scrolllock
    patch = cpu

the interactive menu takes led, patch, hz and init from here when you
press enter, and the language question is skipped once lang is set. a flag
on the command line always beats the file. unknown keys are ignored, so
you can keep notes in there too.

two keys change what a daemon watches: `disk` pins the block device the
disk patch reads, `iface` pins the network interface the net patch counts,
empty means the patch default. both are baked into the binary at build
time, which is the sysblink way, so changing them means rebuilding.

    disk = nvme0n1
    iface = wlan0

## cli usage

every interactive step has a flag equivalent, so the tool works in
scripts:

    python3 sysblink.py --list_leds
    python3 sysblink.py --list_patches
    python3 sysblink.py --list_inits
    python3 sysblink.py --build 'input13::scrolllock' cpu --hz 20
    sudo python3 sysblink.py --build 'input13::scrolllock' cpu --install
    sudo python3 sysblink.py --build 'input13::scrolllock' cpu --init openrc --install
    sudo python3 sysblink.py --remove
    sudo python3 sysblink.py --remove_all
    python3 sysblink.py --version

notes that save time: the led name is the directory name under
/sys/class/leds, quote it because some names contain colons. the patch
name works with or without the .c suffix. building never needs root, the
daemon writes the led at runtime, sudo is only for the service part.
there is also a man page: `man sysblink` after installing the deb, or
`man -l docs/sysblink.1` straight from the tree.

## init systems

the installer picks the first backend that answers detect, override it
with --init. detection order: systemd, openrc, runit, s6, sysvinit.

* systemd: a unit in /etc/systemd/system, enabled and started with
  systemctl, the unit ships with basic hardening like ProtectSystem and
  NoNewPrivileges
* openrc: an openrc-run script in /etc/init.d, added to the default runlevel
* runit: a run directory in the service scandir, picked up by runsvdir
* s6: a run directory in the s6 scandir, plain supervision, experimental
* sysvinit: a classic init script in /etc/init.d with start, stop, restart
  and status, enabled with update-rc.d or chkconfig
* none: no init found, the binary is built and you run it by hand

removal lists every sysblink service known to any backend and undoes the files
it created, including the copy of the binary in /usr/local/bin.

## how it works

engine.c holds the whole daemon. once per tick it asks the patch for a
level from 0 to 100, scales the level to each led maximum and writes it
into the brightness file. the installer replaces the placeholders
{{LED_COUNT}}, {{LED_PATHS}}, {{LED_MAXS}}, {{SLEEP_US}}, {{BLINK_HZ}},
{{BLINK_TICKS}}, {{PROC_ROOT}} and {{SYS_ROOT}}, inserts the patch instead
of the /* PATCH_INSERT */ marker and compiles the result in c99 with O2.
the generated source stays in build/, so you can read exactly what runs
on your machine.

two details worth knowing. first, on startup the daemon writes none into
the trigger file of each led when one exists, because a kernel trigger
would fight the brightness writes, and the trigger stays off after the
daemon exits, put it back by hand if you ever need it. second, a daemon
exits on SIGINT or SIGTERM and writes 0 to every led on the way out, so a
stopped service leaves the leds dark. and if writes keep failing for ten
ticks in a row, for example because the led node vanished, the daemon
exits with code 1 and lets the init system restart it.

## several leds at once

one daemon can drive many leds with the same patch, which is nice when
your keyboard has a row of lock leds begging for a purpose. separate the
led names with a comma:

    sudo python3 sysblink.py --build 'input13::scrolllock,input13::capslock' cpu --install

the unit name is the led names glued together, and scaling happens per
led, so a binary lock led at max 1 just blinks while a backlight led at
max 255 shades smoothly. the interactive menu takes numbers separated by
spaces, or the word all.

## preview before installing

before committing to a service you can watch a patch run against a fake
led right in the terminal:

    python3 preview.py breathe --hz 60
    python3 preview.py cpu --hz 10 --once

the first command opens a curses bar fed by the real daemon writing into
a fake brightness file under build/, q quits. the second runs three ticks
and prints one bar, handy for scripts. this is a sanity tool, the
automated checks are the actual evidence.

## shipped patches

* cpu.c: processor load from /proc/stat
* mem.c: memory in use from /proc/meminfo
* swap.c: swap in use, also the worked out example in the patch guide
* disk.c: disk io rate from /proc/diskstats
* net.c: network traffic from /proc/net/dev, loopback skipped
* thermal.c: cpu temperature from the first thermal zone
* battery.c: battery charge from sysfs, blinks while the battery charges
* loadavg.c: one minute load average per core
* heartbeat.c: the classic double blink
* breathe.c: a smooth four second breathing wave

patches that measure a rate use the tick frequency BLINK_HZ to turn budgets
from patches/config.h into per tick thresholds, so the scale stays honest
at any frequency you pick.

## writing your own patch

the guide lives in docs/patches.md, the russian version in
docs/patches.ru.md. short version: a patch is one c file in patches/ that
defines int get_led_value(void) and returns 0 to 100 without sleeping.
start by copying swap.c, it is the smallest one that touches /proc.

## development

    make test

runs four kinds of checks. the live ones build every patch into the engine
with c99, pedantic and all warnings as errors, then run headless sessions
against fake led files in build/, watching that time based patches reach a
bright phase and the rest write sane numbers. the fixture ones point the
engine at copies of /proc and /sys under tests/fixtures and expect exact
values, for example memory writes 75 and the cpu patch peaks at exactly 20
on the fixture numbers. the runtime ones feed the daemon /dev/full to
prove that failing writes end it with exit code 1, and grow pinned fixture
sources to prove that the disk and iface selection really selects. the
python ones cover the installer logic itself, from config parsing to
service file generation for every backend. BLINK_TICKS bakes a tick limit
into a daemon, 0 means run until a signal, that is what makes the runs
headless. the same suite runs on every push through github actions.

## layout

    sysblink/
      sysblink.py          installer and builder
      preview.py           terminal preview of a patch
      engine.c             daemon template
      patches/             ten patches plus config.h with shared thresholds
      docs/                patch guide in english and russian, man page
      tests/               headless checks, fixtures and python unit tests
      makefile             runs the checks
      packaging/           deb build script and an aur pkgbuild
      site/                project page published to github pages
      .github/workflows/   ci on push, pages deploy, deb release on tags
      CHANGELOG.md         release history
      CONTRIBUTING.md      how to build, test and send a patch
      SECURITY.md          private reporting channel

## packaging

packaging/deb/build.sh assembles a deb with dpkg-deb, it was built and
inspected on debian during development. it installs the installer to
/usr/bin/sysblink and the tree to /usr/share/sysblink, sysblink.py finds the tree there
on its own. packaging/aur/PKGBUILD is provided for arch users but was not
validated here, this host has no makepkg.

## limitations

* battery.c probes BAT0, BAT1 and BATT only, listing sysfs would need
  dirent.h which sits outside the posix subset of the compile gate
* s6 support assumes a plain supervised scandir, s6 rc bundles are not wired
* disk and net normalization is a hand picked approximation, tune the
  budgets in patches/config.h for your hardware
* rate patches measure between ticks, a suspended machine can make counters
  jump backwards, the patches answer zero for such a tick
* the packaged installer builds into /var/lib/sysblink because the share
  dir is root owned, which fits its use anyway

## license

mit, the full text lives in the license file next to this readme.
