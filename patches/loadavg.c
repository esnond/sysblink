/*
 * sysblink patch: load average
 * turns the one minute load average into a percent of the cores online
 * one core fully busy reads as 100 percent
 */

#include <stdio.h>
#include <unistd.h>

#include "config.h"

#define LOADAVG_PATH BLINK_PROC_ROOT "/loadavg"

int get_led_value(void)
{
    long cores;
    double load = 0.0;
    double level;
    FILE *fp;

    fp = fopen(LOADAVG_PATH, "r");
    if (fp == NULL)
        return 0;
    if (fscanf(fp, "%lf", &load) != 1) {
        fclose(fp);
        return 0;
    }
    fclose(fp);

    cores = sysconf(_SC_NPROCESSORS_ONLN);
    if (cores < 1)
        cores = 1;
    level = load * 100.0 / ((double)cores * LOAD_FULL_PER_CORE);
    if (level < 0.0)
        return 0;
    if (level > 100.0)
        return 100;
    return (int)level;
}
