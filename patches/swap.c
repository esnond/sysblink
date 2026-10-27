/*
 * sysblink patch: swap usage
 * example patch from docs/patches.md, reads SwapTotal and SwapFree from
 * /proc/meminfo and returns the share of swap in use, no swap means dark
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

    fp = fopen(BLINK_PROC_ROOT "/meminfo", "r");
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
