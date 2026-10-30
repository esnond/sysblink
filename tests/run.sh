#!/bin/sh
# headless checks for sysblink
# live checks run every patch on the real system, fixture checks expect
# exact values, runtime checks cover write failures and pinned sources

set -eu
cd "$(dirname "$0")/.."

CC=${CC:-cc}
# fortify mirrors the runner hardening, it marks write and ftruncate results
# as unused and keeps the strict gate honest about ignoring them
CFLAGS="-std=c99 -pedantic -Wall -Wextra -Werror -Wshadow -Wstrict-prototypes -O2 -D_FORTIFY_SOURCE=2"
FIXTURES=$PWD/tests/fixtures
MAX_VAL=255
UNIT_MAX_VAL=100
VERSION=$(cat VERSION 2>/dev/null || echo 1.0.0)

insert_patch() {
    awk -v patchfile="$1" '
    /\/\* PATCH_INSERT \*\// {
        while ((getline line < patchfile) > 0)
            print line
        close(patchfile)
        next
    }
    { print }'
}

# render, brightness file, max, ticks, patch file, proc root, sys root, disk, iface
# an absolute brightness path is taken as is, see the /dev/full check below
render() {
    rpath=$1
    case "$1" in
        /*) ;;
        *) rpath="$PWD/$1" ;;
    esac
    sed -e "s|{{LED_COUNT}}|1|" \
        -e "s|{{LED_PATHS}}|\"$rpath\"|" \
        -e "s|{{LED_MAXS}}|$2|" \
        -e "s|{{SLEEP_US}}|10000|" \
        -e "s|{{BLINK_HZ}}|100|" \
        -e "s|{{BLINK_TICKS}}|$3|" \
        -e "s|{{PROC_ROOT}}|$5|" \
        -e "s|{{SYS_ROOT}}|$6|" \
        -e "s|{{VERSION}}|$VERSION|" \
        -e "s|{{DISK_DEVICE}}|${7:-}|" \
        -e "s|{{NET_IFACE}}|${8:-}|" \
        engine.c | insert_patch "$4"
}

numeric_value() {
    case "$1" in
        ''|*[!0-9]*) echo 0 ;;
        *) echo "$1" ;;
    esac
}

# run a finite binary to the end and report the highest value it writes
peak_of() {
    "$1" &
    pid=$!
    peak=0
    while kill -0 "$pid" 2>/dev/null; do
        v=$(numeric_value "$(cat "$2")")
        if [ "$v" -gt "$peak" ]; then
            peak=$v
        fi
        sleep 0.05
    done
    wait "$pid"
    echo "$peak"
}

# sets PEAK and ZERO: starts an endless binary, runs the bump command in
# the background so the source keeps growing, samples for a bounded time,
# then kills both
watch_peak() {
    "$1" &
    _pid=$!
    _peak=0
    _zero=0
    sleep 0.2
    eval "$3" &
    _bump=$!
    _i=0
    while [ "$_i" -lt 16 ] && kill -0 "$_pid" 2>/dev/null; do
        _v=$(numeric_value "$(cat "$2")")
        if [ "$_v" -gt "$_peak" ]; then
            _peak=$_v
        fi
        if [ "$_v" -eq 0 ]; then
            _zero=1
        fi
        sleep 0.05
        _i=$((_i + 1))
    done
    kill "$_pid" "$_bump" 2>/dev/null || true
    wait "$_pid" 2>/dev/null || true
    PEAK=$_peak
    ZERO=$_zero
}

mkdir -p build
status=0

echo "live checks"
for patch in patches/*.c; do
    name=$(basename "$patch" .c)
    led="build/led_$name.txt"
    : > "$led"
    if ! render "$led" "$MAX_VAL" 25 "$patch" /proc /sys > "build/test_$name.c"; then
        echo "fail: $name render failed"
        status=1
        continue
    fi
    if ! $CC $CFLAGS -Ipatches "build/test_$name.c" -o "build/test_$name"; then
        echo "fail: $name does not compile"
        status=1
        continue
    fi

    case "$name" in
    breathe|heartbeat)
        # time based patches guarantee a bright phase, sample the peak
        render "$led" "$MAX_VAL" 200 "$patch" /proc /sys > "build/test_${name}_long.c"
        $CC $CFLAGS -Ipatches "build/test_${name}_long.c" -o "build/test_${name}_long"
        peak=$(peak_of "build/test_${name}_long" "$led")
        if [ "$peak" -eq 0 ]; then
            echo "fail: $name never left zero"
            status=1
        else
            echo "ok: $name peak $peak"
        fi
        ;;
    *)
        "build/test_$name"
        value=$(numeric_value "$(cat "$led")")
        if [ "$value" -gt "$MAX_VAL" ]; then
            echo "fail: $name wrote $value"
            status=1
        else
            echo "ok: $name wrote $value"
        fi
        ;;
    esac
done

echo "fixture checks"
for pair in "mem 75" "swap 75" "thermal 40" "battery 42"; do
    set -- $pair
    name=$1
    want=$2
    led="build/fled_$name.txt"
    : > "$led"
    render "$led" "$UNIT_MAX_VAL" 25 "patches/$name.c" "$FIXTURES/proc" "$FIXTURES/sys" > "build/unit_$name.c"
    $CC $CFLAGS -Ipatches "build/unit_$name.c" -o "build/unit_$name"
    "build/unit_$name"
    value=$(numeric_value "$(cat "$led")")
    if [ "$value" -eq "$want" ]; then
        echo "ok: $name wrote $value"
    else
        echo "fail: $name wrote $value, want $want"
        status=1
    fi
done

cores=$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 1)
want=$(awk -v l="2.50" -v c="$cores" 'BEGIN{v=l*100/c; if(v>100)v=100; printf "%d", v}')
led="build/fled_loadavg.txt"
: > "$led"
render "$led" "$UNIT_MAX_VAL" 25 "patches/loadavg.c" "$FIXTURES/proc" "$FIXTURES/sys" > "build/unit_loadavg.c"
$CC $CFLAGS -Ipatches "build/unit_loadavg.c" -o "build/unit_loadavg"
"build/unit_loadavg"
value=$(numeric_value "$(cat "$led")")
if [ "$value" -eq "$want" ]; then
    echo "ok: loadavg wrote $value"
else
    echo "fail: loadavg wrote $value, want $want"
    status=1
fi

for pair in "disk 0" "net 0"; do
    set -- $pair
    name=$1
    want=$2
    led="build/fled_$name.txt"
    : > "$led"
    render "$led" "$UNIT_MAX_VAL" 200 "patches/$name.c" "$FIXTURES/proc" "$FIXTURES/sys" > "build/unit_$name.c"
    $CC $CFLAGS -Ipatches "build/unit_$name.c" -o "build/unit_$name"
    peak=$(peak_of "build/unit_$name" "$led")
    value=$(numeric_value "$(cat "$led")")
    if [ "$peak" -eq "$want" ] && [ "$value" -eq 0 ]; then
        echo "ok: $name peak $peak, settled at 0"
    else
        echo "fail: $name peak $peak (want $want), final $value"
        status=1
    fi
done

# the cpu fixture check grows the counters while the daemon runs, every
# bump adds 15 user and 35 idle ticks so busy time stays at exactly 30
# percent, a sustained value cannot be missed by a slow sampler, the old
# single tick spike of 20 was invisible to the ci runner half of the time
rm -rf build/fixproc
cp -r "$FIXTURES/proc" build/fixproc
led="build/fled_cpu.txt"
: > "$led"
render "$led" "$UNIT_MAX_VAL" 0 "patches/cpu.c" "$PWD/build/fixproc" "$FIXTURES/sys" > "build/unit_cpu.c"
$CC $CFLAGS -Ipatches "build/unit_cpu.c" -o "build/unit_cpu"
CPU_BUMP="i=0; while :; do i=\$((i + 1)); printf 'cpu  %d 0 100 %d 100 0 0 0 0 0\n' \$((100 + 15 * i)) \$((700 + 35 * i)) > build/fixproc/stat; sleep 0.005; done"
watch_peak "build/unit_cpu" "$led" "$CPU_BUMP"
if [ "$PEAK" -eq 30 ] && [ "$ZERO" -eq 1 ]; then
    echo "ok: cpu holds 30 under growth, dark before it"
else
    echo "fail: cpu peak $PEAK (want 30), zero seen $ZERO"
    status=1
fi

echo "runtime checks"
# a led that refuses writes must end the daemon with exit code 1
# /dev/full opens fine and fails every write with ENOSPC, rights are only
# checked at open time so a plain chmod would not do here
render "/dev/full" "$UNIT_MAX_VAL" 0 "patches/loadavg.c" /proc /sys > "build/unit_fail.c"
$CC $CFLAGS -Ipatches "build/unit_fail.c" -o "build/unit_fail"
rc=0
"build/unit_fail" || rc=$?
if [ "$rc" -eq 1 ]; then
    echo "ok: write failure exits with 1"
else
    echo "fail: write failure exit code $rc"
    status=1
fi

echo "selection checks"
# the bump rewrites the fixture copy so the watched source grows forever,
# a one shot bump would last a single 10 ms tick and be easy to miss
DISK_BUMP="i=0; while :; do i=\$((i + 5000)); printf '8       0 sda 100 0 1000 100 0 0 1000 100 0 0 0 0 0 0\n8       16 sdb 0 0 %d 100 0 0 0 0 0 0 0 0 0 0\n' \"\$i\" > build/fixproc/diskstats; sleep 0.02; done"
NET_BUMP="i=0; while :; do i=\$((i + 5000)); printf 'Inter-|   Receive                                                |  Transmit\n face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed\n    lo:  1000      10    0    0    0     0          0         0 1000      10    0    0    0     0       0          0\n  eth0: 50000     100    0    0    0     0          0         0 50000     100    0    0    0     0       0          0\n  wlan1: %d 100 0 0 0 0 0 0 %d 100 0 0 0 0 0 0\n' \"\$i\" \"\$i\" > build/fixproc/net/dev; sleep 0.02; done"

# every case gets its own led file so a late writer cannot pollute the next
# case, and stale binaries are cleared before anything starts
pkill -f "build/sel[0-9]" 2>/dev/null || true

# disk pinned to sdb reacts when sdb starts moving
rm -rf build/fixproc
cp -r "$FIXTURES/proc" build/fixproc
led="build/sled1.txt"
: > "$led"
render "$led" "$UNIT_MAX_VAL" 0 "patches/disk.c" "$PWD/build/fixproc" "$FIXTURES/sys" sdb "" > "build/sel1.c"
$CC $CFLAGS -Ipatches "build/sel1.c" -o "build/sel1"
watch_peak "build/sel1" "$led" "$DISK_BUMP"
if [ "$PEAK" -gt 0 ]; then
    echo "ok: disk pinned to sdb saw the bump"
else
    echo "fail: disk pinned to sdb stayed at 0"
    status=1
fi

# disk pinned to sda ignores the sdb growth
rm -rf build/fixproc
cp -r "$FIXTURES/proc" build/fixproc
led="build/sled2.txt"
: > "$led"
render "$led" "$UNIT_MAX_VAL" 0 "patches/disk.c" "$PWD/build/fixproc" "$FIXTURES/sys" sda "" > "build/sel2.c"
$CC $CFLAGS -Ipatches "build/sel2.c" -o "build/sel2"
watch_peak "build/sel2" "$led" "$DISK_BUMP"
if [ "$PEAK" -eq 0 ]; then
    echo "ok: disk pinned to sda ignored the sdb growth"
else
    echo "fail: disk pinned to sda saw $PEAK"
    status=1
fi

# net pinned to wlan1 reacts when wlan1 starts moving
rm -rf build/fixproc
cp -r "$FIXTURES/proc" build/fixproc
led="build/sled3.txt"
: > "$led"
render "$led" "$UNIT_MAX_VAL" 0 "patches/net.c" "$PWD/build/fixproc" "$FIXTURES/sys" "" wlan1 > "build/sel3.c"
$CC $CFLAGS -Ipatches "build/sel3.c" -o "build/sel3"
watch_peak "build/sel3" "$led" "$NET_BUMP"
if [ "$PEAK" -gt 0 ]; then
    echo "ok: net pinned to wlan1 saw the bump"
else
    echo "fail: net pinned to wlan1 stayed at 0"
    status=1
fi

# net pinned to eth0 ignores the wlan1 growth
rm -rf build/fixproc
cp -r "$FIXTURES/proc" build/fixproc
led="build/sled4.txt"
: > "$led"
render "$led" "$UNIT_MAX_VAL" 0 "patches/net.c" "$PWD/build/fixproc" "$FIXTURES/sys" "" eth0 > "build/sel4.c"
$CC $CFLAGS -Ipatches "build/sel4.c" -o "build/sel4"
watch_peak "build/sel4" "$led" "$NET_BUMP"
if [ "$PEAK" -eq 0 ]; then
    echo "ok: net pinned to eth0 ignored the wlan1 growth"
else
    echo "fail: net pinned to eth0 saw $PEAK"
    status=1
fi

# a charging battery blinks between the charge level and dark
rm -rf build/fixsys
cp -r "$FIXTURES/sys" build/fixsys
printf 'Charging\n' > build/fixsys/class/power_supply/BAT0/status
led="build/sled5.txt"
: > "$led"
render "$led" "$UNIT_MAX_VAL" 0 "patches/battery.c" "$FIXTURES/proc" "$PWD/build/fixsys" > "build/sel5.c"
$CC $CFLAGS -Ipatches "build/sel5.c" -o "build/sel5"
watch_peak "build/sel5" "$led" "true"
if [ "$PEAK" -eq 42 ] && [ "$ZERO" -eq 1 ]; then
    echo "ok: charging battery blinks 0 and 42"
else
    echo "fail: charging battery peak $PEAK, zero seen $ZERO"
    status=1
fi

echo "python checks"
python3 tests/test_python.py > build/python_tests.log 2>&1 && echo "ok: python tests" || {
    echo "fail: python tests"
    cat build/python_tests.log
    status=1
}

exit $status
