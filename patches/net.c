/*
 * sysblink patch: network activity
 * sums rx and tx bytes over all real interfaces in BLINK_PROC_ROOT /net/dev
 * and turns the rate into a share of the budget from patches/config.h
 * loopback is skipped because talking to yourself is not traffic, an
 * interface pinned in sysblink.conf is the only one counted
 */

#include <inttypes.h>
#include <stdio.h>
#include <string.h>

#include "config.h"

#define NET_LINE_SIZE 256
#define NET_NAME_SIZE 64
#define NET_TX_SKIP 7  /* counters between rx bytes and tx bytes in one row */

int get_led_value(void)
{
    static uint64_t prev_total;
    static int primed;
    uint64_t rx, tx, total = 0, diff, budget;
    char iface[NET_NAME_SIZE];
    char line[NET_LINE_SIZE];
    char *fields;
    FILE *fp;

    fp = fopen(BLINK_PROC_ROOT "/net/dev", "r");
    if (fp == NULL)
        return 0;
    if (fgets(line, sizeof(line), fp) == NULL ||   /* header line one */
        fgets(line, sizeof(line), fp) == NULL) {   /* header line two */
        fclose(fp);
        return 0;
    }
    while (fgets(line, sizeof(line), fp) != NULL) {
        if (sscanf(line, "%63s", iface) != 1)
            continue;
        if (BLINK_NET_IFACE[0] != '\0') {
            size_t want = strlen(BLINK_NET_IFACE);

            if (strncmp(iface, BLINK_NET_IFACE, want) != 0 || iface[want] != ':')
                continue;
        } else if (strcmp(iface, "lo:") == 0) {
            continue;
        }
        fields = strchr(line, ':');
        if (fields == NULL)
            continue;
        if (sscanf(fields + 1,
                   "%" SCNu64
                   " %*u %*u %*u %*u %*u %*u %*u"
                   " %" SCNu64,
                   &rx, &tx) != 2)
            continue;
        total += rx + tx;
    }
    fclose(fp);

    if (!primed) {
        /* the first call has no previous sample, report zero not a spike */
        primed = 1;
        prev_total = total;
        return 0;
    }
    diff = total > prev_total ? total - prev_total : 0;
    prev_total = total;

    budget = NET_BYTES_PER_SEC / BLINK_HZ;
    if (budget == 0)
        budget = 1;
    if (diff >= budget)
        return 100;
    return (int)(diff * 100 / budget);
}
