/*
 * sysblink patch: breathe
 * a smooth triangle wave from dark to full and back, timing comes from the
 * monotonic clock so the period is the same at any tick frequency
 */

#include <time.h>

#define BREATHE_PERIOD_MS 4000

int get_led_value(void)
{
    struct timespec now;
    long phase, half;

    if (clock_gettime(CLOCK_MONOTONIC, &now) != 0)
        return 0;
    phase = (now.tv_sec * 1000L + now.tv_nsec / 1000000L) % BREATHE_PERIOD_MS;
    half = BREATHE_PERIOD_MS / 2;
    if (phase < half)
        return (int)(phase * 100 / half);
    return (int)((BREATHE_PERIOD_MS - phase) * 100 / half);
}
