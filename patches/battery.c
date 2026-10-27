/*
 * sysblink patch: battery charge
 * returns the charge percent of the first battery it finds in sysfs
 * while the battery charges the led blinks between the charge level and
 * dark so it also says that power is flowing, on battery or full it holds
 * the level steady
 * the names are probed in order because listing a directory would need
 * dirent.h which sits beyond the posix subset this project compiles with
 * no battery means a dark led
 */

#include <stdio.h>
#include <string.h>
#include <time.h>

#define BATTERY_BASE BLINK_SYS_ROOT "/class/power_supply/"
#define BATTERY_PATH_SIZE 128
#define BATTERY_STATUS_SIZE 32
#define BATTERY_BLINK_MS 500  /* half of the blink period while charging */

int get_led_value(void)
{
    static const char *const names[] = {"BAT0", "BAT1", "BATT"};
    char path[BATTERY_PATH_SIZE];
    char status[BATTERY_STATUS_SIZE];
    struct timespec now;
    int charge, charging;
    size_t i;
    FILE *fp;

    for (i = 0; i < sizeof(names) / sizeof(names[0]); i++) {
        snprintf(path, sizeof(path), "%s%s/capacity", BATTERY_BASE, names[i]);
        fp = fopen(path, "r");
        if (fp == NULL)
            continue;
        charge = 0;
        if (fscanf(fp, "%d", &charge) != 1)
            charge = 0;
        fclose(fp);

        charging = 0;
        snprintf(path, sizeof(path), "%s%s/status", BATTERY_BASE, names[i]);
        fp = fopen(path, "r");
        if (fp != NULL) {
            status[0] = '\0';
            if (fscanf(fp, "%31s", status) == 1)
                charging = strcmp(status, "Charging") == 0;
            fclose(fp);
        }

        if (charge < 0)
            charge = 0;
        if (charge > 100)
            charge = 100;
        if (charging && clock_gettime(CLOCK_MONOTONIC, &now) == 0) {
            long ms = now.tv_sec * 1000L + now.tv_nsec / 1000000L;

            if (ms % (BATTERY_BLINK_MS * 2) >= BATTERY_BLINK_MS)
                return 0;
        }
        return charge;
    }
    return 0;
}
