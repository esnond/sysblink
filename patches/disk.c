/*
 * sysblink patch: disk io
 * watches sectors read plus written on the first real device in
 * BLINK_PROC_ROOT /diskstats and turns the rate into a share of the budget
 * from patches/config.h, a device pinned in sysblink.conf wins over the
 * first device rule
 */

#include <inttypes.h>
#include <stdio.h>
#include <string.h>

#include "config.h"

#define DISK_LINE_SIZE 256
#define DISK_NAME_FIELD "%63s"

int get_led_value(void)
{
    static uint64_t prev_total;
    static int primed;
    uint64_t read_sectors = 0, written_sectors = 0;
    uint64_t total, diff, budget;
    char name[64];
    char line[DISK_LINE_SIZE];
    int matched = 0;
    FILE *fp;

    fp = fopen(BLINK_PROC_ROOT "/diskstats", "r");
    if (fp == NULL)
        return 0;
    while (fgets(line, sizeof(line), fp) != NULL) {
        /* fields: 1 major, 2 minor, 3 name, 6 sectors read, 10 sectors written */
        matched = sscanf(line,
                         "%*d %*d " DISK_NAME_FIELD
                         " %*d %*d %" SCNu64
                         " %*d %*d %*d %" SCNu64,
                         name, &read_sectors, &written_sectors);
        if (matched != 3)
            continue;
        if (BLINK_DISK_DEVICE[0] != '\0') {
            if (strcmp(name, BLINK_DISK_DEVICE) != 0)
                continue;
            break;
        }
        if (strncmp(name, "loop", 4) == 0 || strncmp(name, "ram", 3) == 0)
            continue;
        break;  /* the whole disk comes first, partitions follow it */
    }
    fclose(fp);

    if (matched != 3)
        return 0;
    total = read_sectors + written_sectors;
    if (!primed) {
        /* the first call has no previous sample, report zero not a spike */
        primed = 1;
        prev_total = total;
        return 0;
    }
    diff = total > prev_total ? total - prev_total : 0;
    prev_total = total;

    budget = DISK_SECTORS_PER_SEC / BLINK_HZ;
    if (budget == 0)
        budget = 1;
    if (diff >= budget)
        return 100;
    return (int)(diff * 100 / budget);
}
