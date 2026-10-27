/*
 * sysblink patch: cpu load
 * reads the aggregate cpu line from /proc/stat and returns the busy share
 * of the time since the previous tick as a percent
 */

#include <inttypes.h>
#include <stdio.h>
#include <string.h>

#define CPU_COUNTERS 8   /* user nice system idle iowait irq softirq steal */
#define CPU_IDLE     3
#define CPU_IOWAIT   4
#define CPU_TAG_SIZE 8

int get_led_value(void)
{
    static uint64_t prev_total;
    static uint64_t prev_idle;
    uint64_t counters[CPU_COUNTERS];
    uint64_t total, idle, dtotal, didle;
    char tag[CPU_TAG_SIZE];
    int i;
    FILE *fp;

    fp = fopen(BLINK_PROC_ROOT "/stat", "r");
    if (fp == NULL)
        return 0;
    if (fscanf(fp, "%7s", tag) != 1 || strcmp(tag, "cpu") != 0) {
        fclose(fp);
        return 0;
    }
    for (i = 0; i < CPU_COUNTERS; i++) {
        if (fscanf(fp, "%" SCNu64, &counters[i]) != 1) {
            fclose(fp);
            return 0;
        }
    }
    fclose(fp);

    total = 0;
    for (i = 0; i < CPU_COUNTERS; i++)
        total += counters[i];
    idle = counters[CPU_IDLE] + counters[CPU_IOWAIT];

    dtotal = total - prev_total;
    didle = idle - prev_idle;
    prev_total = total;
    prev_idle = idle;

    /* backwards counters after suspend and the first call both land here */
    if (dtotal == 0 || didle > dtotal)
        return 0;
    return (int)(100 * (dtotal - didle) / dtotal);
}
