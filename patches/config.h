/*
 * sysblink shared patch tuning
 * rates are per second unless the comment says otherwise
 * every threshold is a hand picked approximation, tune it to taste
 */

/* net: traffic that means 100 percent, bytes per second, approx 10 mbit */
#define NET_BYTES_PER_SEC 1250000

/* disk: io that means 100 percent, sectors per second, 512 byte sectors,
 * approx 10 mb per second */
#define DISK_SECTORS_PER_SEC 20000

/* thermal: this celsius range maps onto the 0 to 100 scale */
#define THERMAL_COLD_C 40
#define THERMAL_HOT_C  90

/* thermal: sysfs reports temperature in millidegrees */
#define THERMAL_MILLI_C 1000

/* loadavg: per core load that reads as 100 percent */
#define LOAD_FULL_PER_CORE 1.0
