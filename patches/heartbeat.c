/*
 * sysblink patch: heartbeat
 * mimics the classic double blink of the linux heartbeat led, one pair of
 * pulses per period, timing comes from the monotonic clock so the pattern
 * keeps its shape at any tick frequency
 */

#include <time.h>

#define HEARTBEAT_PERIOD_MS 1200
#define HEARTBEAT_PULSE_MS  80
#define HEARTBEAT_GAP_MS    160

int get_led_value(void)
{
    struct timespec now;
    long phase;

    if (clock_gettime(CLOCK_MONOTONIC, &now) != 0)
        return 0;
    phase = (now.tv_sec * 1000L + now.tv_nsec / 1000000L) % HEARTBEAT_PERIOD_MS;
    if (phase < HEARTBEAT_PULSE_MS)
        return 100;
    if (phase >= HEARTBEAT_GAP_MS &&
        phase < HEARTBEAT_GAP_MS + HEARTBEAT_PULSE_MS)
        return 100;
    return 0;
}
