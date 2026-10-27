/*
 * sysblink patch: thermal
 * reads the first thermal zone and maps the celsius range from
 * patches/config.h onto 0 to 100, cold is dark and hot is full brightness
 */

#include <inttypes.h>
#include <stdio.h>

#include "config.h"

#define THERMAL_PATH BLINK_SYS_ROOT "/class/thermal/thermal_zone0/temp"

int get_led_value(void)
{
    int64_t milli = 0;
    int64_t cold = (int64_t)THERMAL_COLD_C * THERMAL_MILLI_C;
    int64_t hot = (int64_t)THERMAL_HOT_C * THERMAL_MILLI_C;
    int64_t span, level;
    FILE *fp;

    fp = fopen(THERMAL_PATH, "r");
    if (fp == NULL)
        return 0;
    if (fscanf(fp, "%" SCNd64, &milli) != 1) {
        fclose(fp);
        return 0;
    }
    fclose(fp);

    span = hot - cold;
    if (span <= 0)
        return 0;
    level = (milli - cold) * 100 / span;
    if (level < 0)
        return 0;
    if (level > 100)
        return 100;
    return (int)level;
}
