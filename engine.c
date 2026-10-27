/*
 * sysblink engine
 * the installer fills the placeholders below, inserts one patch and
 * compiles the result into a tiny daemon that keeps one or more leds in
 * sync with a metric. the patch contract is described in docs/patches.md.
 */

#define _POSIX_C_SOURCE 200809L

#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#define LED_COUNT {{LED_COUNT}}
static const char *const led_paths[LED_COUNT] = { {{LED_PATHS}} };
static const int led_max[LED_COUNT] = { {{LED_MAXS}} };

/*
 * patches build their source paths from these roots, the test suite points
 * them at fixtures to get deterministic numbers
 */
#define BLINK_PROC_ROOT "{{PROC_ROOT}}"
#define BLINK_SYS_ROOT "{{SYS_ROOT}}"

/*
 * selection hints from sysblink.conf, empty strings mean the patch default,
 * disk pins the watched device and iface pins the counted interface
 */
#define BLINK_DISK_DEVICE "{{DISK_DEVICE}}"
#define BLINK_NET_IFACE "{{NET_IFACE}}"

#define VERSION   "{{VERSION}}"   /* printed once at startup, see --version */
#define SLEEP_US  {{SLEEP_US}}    /* tick period in microseconds */
#define BLINK_HZ    {{BLINK_HZ}}      /* tick frequency in hertz, patches read it */
#define BLINK_TICKS {{BLINK_TICKS}}   /* ticks to run, 0 means run until a signal */

#define OUT_BUF_SIZE      16      /* decimal int plus the terminator */
#define OPEN_ATTEMPTS     10      /* tries to open a led before giving up */
#define OPEN_RETRY_MS     100
#define OFF_LEVEL         0
#define TRIGGER_PATH_SIZE 128
#define MAX_WRITE_FAILURES 10     /* failing ticks in a row before giving up */

/* the patch provides this, it must return a level from 0 to 100 */
int get_led_value(void);

/* the patch code replaces this marker */
/* PATCH_INSERT */

static volatile sig_atomic_t stop_requested;

static void on_signal(int sig)
{
    (void)sig;
    stop_requested = 1;
}

static int clamp_level(int level, int max)
{
    int out;

    if (max > 1)
        out = level * max / 100;
    else
        out = level > 50 ? 1 : 0;
    if (out < 0)
        out = 0;
    if (out > max)
        out = max;
    return out;
}

/*
 * write the whole value and rewind, truncating keeps a regular file clean
 * when a shorter number replaces a longer one, sysfs ignores it
 * returns 0 when the write landed, nonzero when the led refused it
 */
static int write_level(int fd, int level, int max)
{
    char buf[OUT_BUF_SIZE];
    int len = snprintf(buf, sizeof(buf), "%d", clamp_level(level, max));

    if (len < 0 || write(fd, buf, (size_t)len) < 0)
        return 1;
    /* best effort, sysfs may refuse truncation and the write already landed */
    if (ftruncate(fd, (off_t)len) < 0) {
        /* nothing to do */
    }
    (void)lseek(fd, 0, SEEK_SET);
    return 0;
}

/*
 * a kernel trigger owns the led until told otherwise and would fight our
 * brightness writes, so switch it off once at startup, the setting stays
 * none after the daemon exits, put the trigger back by hand if you need it
 */
static void disable_trigger(const char *led_path)
{
    char trigger_path[TRIGGER_PATH_SIZE];
    const char *slash = strrchr(led_path, '/');
    int fd, len;

    if (slash == NULL)
        return;
    len = snprintf(trigger_path, sizeof(trigger_path), "%.*s/trigger",
                   (int)(slash - led_path), led_path);
    if (len < 0 || len >= (int)sizeof(trigger_path))
        return;
    fd = open(trigger_path, O_WRONLY);
    if (fd < 0)
        return;  /* no trigger file means nothing owns the led */
    /* best effort, a refusal here changes nothing about our own writes */
    if (write(fd, "none", 4) < 0) {
        /* nothing to do */
    }
    close(fd);
}

static int open_leds(int *fds)
{
    struct timespec pause = {0, OPEN_RETRY_MS * 1000000L};
    int opened = 0;
    int attempt, i;

    for (i = 0; i < LED_COUNT; i++)
        fds[i] = -1;
    /* a service can start before the led nodes show up, give them a moment */
    for (attempt = 0; attempt < OPEN_ATTEMPTS && opened < LED_COUNT; attempt++) {
        for (i = 0; i < LED_COUNT; i++) {
            if (fds[i] >= 0)
                continue;
            fds[i] = open(led_paths[i], O_WRONLY);
            if (fds[i] >= 0)
                opened++;
        }
        if (opened < LED_COUNT)
            nanosleep(&pause, NULL);
    }
    return opened == LED_COUNT ? 0 : -1;
}

int main(void)
{
    struct sigaction sa;
    struct timespec pause;
    int fds[LED_COUNT];
    int failures = 0;
    long tick;
    int i;

    fprintf(stderr, "sysblink %s\n", VERSION);

    for (i = 0; i < LED_COUNT; i++)
        disable_trigger(led_paths[i]);

    if (open_leds(fds) != 0) {
        perror("sysblink: cannot open the led");
        for (i = 0; i < LED_COUNT; i++) {
            if (fds[i] >= 0)
                close(fds[i]);
        }
        return 1;
    }

    memset(&sa, 0, sizeof(sa));
    sa.sa_handler = on_signal;
    sigaction(SIGINT, &sa, NULL);
    sigaction(SIGTERM, &sa, NULL);

    pause.tv_sec = SLEEP_US / 1000000;
    pause.tv_nsec = (long)(SLEEP_US % 1000000) * 1000L;

    for (tick = 0; BLINK_TICKS == 0 || tick < BLINK_TICKS; tick++) {
        int level = get_led_value();
        int bad = 0;

        for (i = 0; i < LED_COUNT; i++)
            bad |= write_level(fds[i], level, led_max[i]);
        failures = bad ? failures + 1 : 0;
        if (failures >= MAX_WRITE_FAILURES) {
            /* exit nonzero so the init system restarts us with a fresh open */
            fprintf(stderr, "sysblink: led writes keep failing\n");
            break;
        }
        nanosleep(&pause, NULL);
        if (stop_requested)
            break;
    }

    /* leave the leds dark when stopped, a batch run keeps the last value */
    if (BLINK_TICKS == 0) {
        for (i = 0; i < LED_COUNT; i++)
            write_level(fds[i], OFF_LEVEL, led_max[i]);
    }
    for (i = 0; i < LED_COUNT; i++)
        close(fds[i]);
    return failures >= MAX_WRITE_FAILURES ? 1 : 0;
}
