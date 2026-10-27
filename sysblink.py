#!/usr/bin/env python3
"""sysblink: builds small daemons that show system metrics on leds.

the installer lists the leds and patches it finds, renders the engine
template with one patch, compiles it and optionally registers the binary
with the init system it detects. a project local sysblink.conf holds defaults,
see readme.md for the full picture.
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

SHARE_DIR = Path("/usr/share/sysblink")


def find_base_dir():
    """the tree runs from a checkout or from a packaged share dir."""
    here = Path(__file__).resolve().parent
    if (here / "engine.c").is_file():
        return here
    if (SHARE_DIR / "engine.c").is_file():
        return SHARE_DIR
    return here


BASE_DIR = find_base_dir()
ENGINE_FILE = BASE_DIR / "engine.c"
PATCHES_DIR = BASE_DIR / "patches"
CONF_FILE = BASE_DIR / "sysblink.conf"
LED_BASE = Path("/sys/class/leds")
PROC_ROOT = "/proc"
SYS_ROOT = "/sys"

# a packaged tree lives in a root owned share dir, builds go to var instead
PACKAGED = BASE_DIR == SHARE_DIR
BUILD_DIR = Path("/var/lib/sysblink/build") if PACKAGED else BASE_DIR / "build"

BIN_DIR = Path("/usr/local/bin")
SYSTEMD_UNIT_DIR = Path("/etc/systemd/system")
INITD_DIR = Path("/etc/init.d")
RUNIT_SCANDIRS = ("/etc/service", "/var/service", "/run/runit/service")
S6_SCANDIRS = ("/run/s6", "/etc/s6", "/var/run/s6")

VERSION = "1.0"
DEFAULT_HZ = 10
MIN_HZ = 1
MAX_HZ = 100
BINARY_PERMS = 0o755
MANUAL = "none"

TEXTS = {
    "en": {
        "lang_prompt": "choose language: [1] english [2] russian",
        "menu": "\n=== sysblink ===\n[1] create and install a daemon\n[2] remove daemons\n[3] remove all daemons\n[0] exit",
        "leds_header": "\n=== available leds ===",
        "patches_header": "\n=== available patches ===",
        "leds_prompt": "led numbers separated by space, all, or enter for {default}: ",
        "patch_prompt": "patch number, or enter for {default}: ",
        "default_none": "none",
        "hz_prompt": "update frequency in hz [1 to 100, enter for 10]: ",
        "choose": "your choice: ",
        "building": "[*] rendering and compiling",
        "built": "[+] daemon built: ",
        "install_prompt": "install as a service? [y/n]: ",
        "installed": "[+] service installed and started: ",
        "failed": "[!] the operation failed",
        "root_required": "[!] this action needs root, run it with sudo",
        "no_leds": "[!] no writable led found in /sys/class/leds",
        "no_patches": "[!] no patch found, the patches directory is empty",
        "no_cc": "[!] no c compiler found, install gcc or cc",
        "no_services": "[*] no sysblink services found",
        "remove_header": "\n=== installed sysblink services ===",
        "removed": "[+] removed: ",
        "unknown_patch": "[!] unknown patch: ",
        "unknown_led": "[!] unknown led: ",
        "bad_hz": "[*] frequency must be a number from 1 to 100, using 10",
        "detect_line": "[*] init system: {name}",
        "manual_hint": "[*] run it with sudo and stop it with ctrl c",
        "bye": "[*] bye",
    },
    "ru": {
        "lang_prompt": "выберите язык: [1] english [2] русский",
        "menu": "\n=== sysblink ===\n[1] создать и установить демона\n[2] удалить демонов\n[0] выход",
        "leds_header": "\n=== доступные светодиоды ===",
        "patches_header": "\n=== доступные патчи ===",
        "leds_prompt": "номера диодов через пробел, all, или enter для {default}: ",
        "patch_prompt": "номер патча, или enter для {default}: ",
        "default_none": "нет",
        "hz_prompt": "частота обновления в герцах [от 1 до 100, enter для 10]: ",
        "choose": "ваш выбор: ",
        "building": "[*] генерация кода и сборка",
        "built": "[+] демон собран: ",
        "install_prompt": "установить как службу? [y/n]: ",
        "installed": "[+] служба установлена и запущена: ",
        "failed": "[!] операция не удалась",
        "root_required": "[!] действие требует root, запустите через sudo",
        "no_leds": "[!] в /sys/class/leds нет доступных для записи светодиодов",
        "no_patches": "[!] патчи не найдены, каталог patches пуст",
        "no_cc": "[!] компилятор c не найден, установите gcc или cc",
        "no_services": "[*] службы sysblink не найдены",
        "remove_header": "\n=== установленные службы sysblink ===",
        "removed": "[+] удалено: ",
        "unknown_patch": "[!] неизвестный патч: ",
        "unknown_led": "[!] неизвестный диод: ",
        "bad_hz": "[*] частота должна быть числом от 1 до 100, используем 10",
        "detect_line": "[*] система инициализации: {name}",
        "manual_hint": "[*] запустите через sudo, остановка по ctrl c",
        "bye": "[*] до встречи",
    },
}


def load_texts(lang):
    return TEXTS.get(lang, TEXTS["en"])


def detect_lang():
    locale = os.environ.get("LC_ALL") or os.environ.get("LANG") or ""
    return "ru" if locale.lower().startswith("ru") else "en"


def load_config():
    """read sysblink.conf, key = value lines, comments start with #."""
    conf = {}
    if not CONF_FILE.is_file():
        return conf
    for line in CONF_FILE.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or "=" not in line:
            continue
        key, _, value = line.partition("=")
        conf[key.strip().lower()] = value.strip()
    return conf


def pick_lang(args, conf):
    """flag beats config beats locale."""
    lang = args.lang or conf.get("lang") or detect_lang()
    return lang if lang in TEXTS else "en"


def pick_hz(args, conf):
    """flag beats config beats the default."""
    raw = args.hz if args.hz is not None else conf.get("hz")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return DEFAULT_HZ


def find_compiler():
    for name in ("cc", "gcc", "clang"):
        if shutil.which(name):
            return name
    return None


def sanitize_name(raw):
    """turn an led name into a safe chunk for files and unit names."""
    return re.sub(r"[^a-z0-9]+", "_", raw.lower()).strip("_")


def find_leds():
    """list leds the current user may write to."""
    leds = []
    if not LED_BASE.is_dir():
        return leds
    for entry in sorted(LED_BASE.iterdir()):
        brightness = entry / "brightness"
        if not brightness.is_file() or not os.access(brightness, os.W_OK):
            continue
        try:
            top = (entry / "max_brightness").read_text().strip()
        except OSError:
            top = "1"
        leds.append({"name": entry.name, "path": str(entry), "max": top or "1"})
    return leds


def find_patches():
    if not PATCHES_DIR.is_dir():
        return []
    return sorted(p.name for p in PATCHES_DIR.glob("*.c"))


def normalize_patch(raw):
    return raw if raw.endswith(".c") else f"{raw}.c"


def resolve_leds(spec, leds):
    """match a comma separated led spec against the found leds."""
    picked = []
    for want in spec.split(","):
        want = want.strip()
        if not want:
            continue
        key = sanitize_name(want)
        for led in leds:
            if sanitize_name(led["name"]) == key and all(led is not p for p in picked):
                picked.append(led)
                break
        else:
            return None
    return picked or None


def render_source(leds, hz, patch_code, ticks=0, disk="", iface=""):
    """fill the engine template with led paths, a patch and the timing."""
    code = ENGINE_FILE.read_text()
    paths = ", ".join(f'"{led["path"]}/brightness"' for led in leds)
    tops = ", ".join(led["max"] for led in leds)
    code = code.replace("{{LED_COUNT}}", str(len(leds)))
    code = code.replace("{{LED_PATHS}}", paths)
    code = code.replace("{{LED_MAXS}}", tops)
    code = code.replace("{{SLEEP_US}}", str(1_000_000 // hz))
    code = code.replace("{{BLINK_HZ}}", str(hz))
    code = code.replace("{{BLINK_TICKS}}", str(ticks))
    code = code.replace("{{PROC_ROOT}}", PROC_ROOT)
    code = code.replace("{{SYS_ROOT}}", SYS_ROOT)
    code = code.replace("{{VERSION}}", VERSION)
    code = code.replace("{{DISK_DEVICE}}", disk)
    code = code.replace("{{NET_IFACE}}", iface)
    return code.replace("/* PATCH_INSERT */", patch_code)


def unit_name_for(leds):
    return "sysblink_" + "_".join(sanitize_name(led["name"]) for led in leds)


def build_daemon(leds, patch_name, hz, t, disk="", iface=""):
    """render and compile one daemon, return the binary path or none."""
    compiler = find_compiler()
    if compiler is None:
        print(t["no_cc"])
        return None
    patch_file = PATCHES_DIR / (patch_name if patch_name.endswith(".c") else f"{patch_name}.c")
    if not patch_file.is_file():
        print(t["unknown_patch"], patch_name)
        return None

    unit = unit_name_for(leds)
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    src_path = BUILD_DIR / f"{unit}.c"
    bin_path = BUILD_DIR / unit
    src_path.write_text(render_source(leds, hz, patch_file.read_text(), disk=disk, iface=iface))

    print(t["building"])
    cmd = [
        compiler, "-std=c99", "-O2", "-Wall", "-Wextra",
        "-I", str(PATCHES_DIR), str(src_path), "-o", str(bin_path),
    ]
    if subprocess.run(cmd).returncode != 0:
        print(t["failed"])
        return None
    os.chmod(bin_path, BINARY_PERMS)
    print(t["built"], bin_path)
    return bin_path


def copy_binary(bin_path, unit):
    """put the binary where services expect it and return the path."""
    target = BIN_DIR / unit
    shutil.copy(bin_path, target)
    os.chmod(target, BINARY_PERMS)
    return target


def drop_binary(unit):
    target = BIN_DIR / unit
    if target.exists():
        target.unlink()


def run_quiet(cmd):
    subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class InitSystem:
    """base shape every init backend follows."""

    name = MANUAL

    def detect(self):
        return True

    def install(self, bin_path, unit, led_name, t):
        pass

    def installed(self):
        return []

    def remove(self, unit, t):
        pass


class Systemd(InitSystem):
    name = "systemd"

    def detect(self):
        return Path("/run/systemd/system").is_dir() and shutil.which("systemctl") is not None

    def install(self, bin_path, unit, led_name, t):
        target = copy_binary(bin_path, unit)
        unit_file = SYSTEMD_UNIT_DIR / f"{unit}.service"
        unit_file.write_text(
            "[Unit]\n"
            f"Description=sysblink daemon for {led_name}\n"
            "After=multi-user.target\n"
            "\n[Service]\n"
            f"ExecStart={target}\n"
            "Restart=always\n"
            "RestartSec=5\n"
            "NoNewPrivileges=yes\n"
            "ProtectSystem=strict\n"
            "ProtectHome=yes\n"
            "PrivateTmp=yes\n"
            "RestrictNamespaces=yes\n"
            "\n[Install]\n"
            "WantedBy=multi-user.target\n"
        )
        run_quiet(["systemctl", "daemon-reload"])
        run_quiet(["systemctl", "enable", "--now", unit_file.name])
        print(t["installed"], unit_file)

    def installed(self):
        if not SYSTEMD_UNIT_DIR.is_dir():
            return []
        return sorted(p.stem for p in SYSTEMD_UNIT_DIR.glob("sysblink_*.service"))

    def remove(self, unit, t):
        run_quiet(["systemctl", "disable", "--now", f"{unit}.service"])
        unit_file = SYSTEMD_UNIT_DIR / f"{unit}.service"
        if unit_file.exists():
            unit_file.unlink()
        run_quiet(["systemctl", "daemon-reload"])
        drop_binary(unit)
        print(t["removed"], unit)


class OpenRC(InitSystem):
    name = "openrc"

    def detect(self):
        return shutil.which("rc-service") is not None or Path("/run/openrc").is_dir()

    def install(self, bin_path, unit, led_name, t):
        target = copy_binary(bin_path, unit)
        script = INITD_DIR / unit
        script.write_text(
            "#!/sbin/openrc-run\n"
            f'description="sysblink daemon for {led_name}"\n'
            f'command="{target}"\n'
            'command_background="yes"\n'
            f'pidfile="/run/{unit}.pid"\n'
            "\ndepend() {\n"
            "\tafter local\n"
            "}\n"
        )
        os.chmod(script, BINARY_PERMS)
        run_quiet(["rc-update", "add", unit, "default"])
        run_quiet(["rc-service", unit, "start"])
        print(t["installed"], script)

    def installed(self):
        if not INITD_DIR.is_dir():
            return []
        return sorted(p.name for p in INITD_DIR.glob("sysblink_*"))

    def remove(self, unit, t):
        run_quiet(["rc-service", unit, "stop"])
        run_quiet(["rc-update", "delete", unit, "default"])
        script = INITD_DIR / unit
        if script.exists():
            script.unlink()
        drop_binary(unit)
        print(t["removed"], unit)


class Runit(InitSystem):
    name = "runit"

    def scandir(self):
        for cand in RUNIT_SCANDIRS:
            if Path(cand).is_dir():
                return Path(cand)
        return None

    def detect(self):
        return shutil.which("runsvdir") is not None and self.scandir() is not None

    def install(self, bin_path, unit, led_name, t):
        target = copy_binary(bin_path, unit)
        service = self.scandir() / unit
        service.mkdir(parents=True, exist_ok=True)
        (service / "run").write_text(f"#!/bin/sh\nexec {target}\n")
        os.chmod(service / "run", BINARY_PERMS)
        print(t["installed"], service)

    def installed(self):
        scandir = self.scandir()
        if scandir is None:
            return []
        return sorted(p.name for p in scandir.glob("sysblink_*"))

    def remove(self, unit, t):
        service = self.scandir() / unit
        if shutil.which("sv"):
            run_quiet(["sv", "stop", str(service)])
        shutil.rmtree(service, ignore_errors=True)
        drop_binary(unit)
        print(t["removed"], unit)


class S6(InitSystem):
    """plain s6 supervision, s6 rc setups are not wired, see the readme."""

    name = "s6"

    def scandir(self):
        for cand in S6_SCANDIRS:
            if Path(cand).is_dir():
                return Path(cand)
        return None

    def detect(self):
        return shutil.which("s6-svscanctl") is not None and self.scandir() is not None

    def install(self, bin_path, unit, led_name, t):
        target = copy_binary(bin_path, unit)
        service = self.scandir() / unit
        service.mkdir(parents=True, exist_ok=True)
        (service / "run").write_text(f"#!/bin/sh\nexec {target}\n")
        os.chmod(service / "run", BINARY_PERMS)
        print(t["installed"], service)

    def installed(self):
        scandir = self.scandir()
        if scandir is None:
            return []
        return sorted(p.name for p in scandir.glob("sysblink_*"))

    def remove(self, unit, t):
        service = self.scandir() / unit
        if shutil.which("s6-svc"):
            run_quiet(["s6-svc", "-d", str(service)])
        shutil.rmtree(service, ignore_errors=True)
        drop_binary(unit)
        print(t["removed"], unit)


class Sysvinit(InitSystem):
    name = "sysvinit"

    def detect(self):
        return INITD_DIR.is_dir() and shutil.which("update-rc.d") is not None

    def install(self, bin_path, unit, led_name, t):
        target = copy_binary(bin_path, unit)
        script = INITD_DIR / unit
        script.write_text(
            "#!/bin/sh\n"
            "### BEGIN INIT INFO\n"
            f"# Provides:          {unit}\n"
            "# Required-Start:    $remote_fs $syslog\n"
            "# Required-Stop:     $remote_fs $syslog\n"
            "# Default-Start:     2 3 4 5\n"
            "# Default-Stop:      0 1 6\n"
            f"# Short-Description: sysblink daemon for {led_name}\n"
            "### END INIT INFO\n"
            "\n"
            f'daemon="{target}"\n'
            f'pidfile="/run/{unit}.pid"\n'
            "\n"
            'case "$1" in\n'
            "\tstart)\n"
            '\t\tif [ -f "$pidfile" ] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then\n'
            '\t\t\techo "already running"\n'
            "\t\t\texit 0\n"
            "\t\tfi\n"
            '\t\tnohup "$daemon" >/dev/null 2>&1 &\n'
            '\t\techo $! > "$pidfile"\n'
            "\t\t;;\n"
            "\tstop)\n"
            '\t\t[ -f "$pidfile" ] && kill "$(cat "$pidfile")" 2>/dev/null\n'
            '\t\trm -f "$pidfile"\n'
            "\t\t;;\n"
            "\trestart)\n"
            '\t\t"$0" stop\n'
            '\t\t"$0" start\n'
            "\t\t;;\n"
            "\tstatus)\n"
            '\t\tif [ -f "$pidfile" ] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then\n'
            '\t\t\techo "running"\n'
            "\t\telse\n"
            '\t\t\techo "stopped"\n'
            "\t\t\texit 1\n"
            "\t\tfi\n"
            "\t\t;;\n"
            "\t*)\n"
            '\t\techo "usage: $0 {start|stop|restart|status}"\n'
            "\t\texit 2\n"
            "\t\t;;\n"
            "esac\n"
            "exit 0\n"
        )
        os.chmod(script, BINARY_PERMS)
        if shutil.which("update-rc.d"):
            run_quiet(["update-rc.d", unit, "defaults"])
        elif shutil.which("chkconfig"):
            run_quiet(["chkconfig", unit, "on"])
        run_quiet([str(script), "start"])
        print(t["installed"], script)

    def installed(self):
        if not INITD_DIR.is_dir():
            return []
        return sorted(p.name for p in INITD_DIR.glob("sysblink_*"))

    def remove(self, unit, t):
        script = INITD_DIR / unit
        if script.exists():
            run_quiet([str(script), "stop"])
        if shutil.which("update-rc.d"):
            run_quiet(["update-rc.d", "-f", unit, "remove"])
        elif shutil.which("chkconfig"):
            run_quiet(["chkconfig", unit, "off"])
        if script.exists():
            script.unlink()
        drop_binary(unit)
        print(t["removed"], unit)


class Manual(InitSystem):
    """no init detected, the installer just builds and tells how to run."""

    name = MANUAL

    def install(self, bin_path, unit, led_name, t):
        print(t["manual_hint"], bin_path)


BACKENDS = (Systemd(), OpenRC(), Runit(), S6(), Sysvinit())


def pick_backend(requested, t):
    """find the requested backend or the first one that answers detect."""
    if requested:
        for backend in BACKENDS:
            if backend.name == requested:
                return backend
        return None
    for backend in BACKENDS:
        if backend.detect():
            print(t["detect_line"].format(name=backend.name))
            return backend
    return Manual()


def ask(prompt):
    """read a line, none on end of file so scripts can close the pipe."""
    try:
        return input(prompt).strip()
    except EOFError:
        return None


def parse_led_pick(raw, count):
    """turn a space separated index list or the word all into indices."""
    tokens = raw.lower().split()
    if tokens == ["all"]:
        return list(range(count))
    picks = []
    for token in tokens:
        try:
            idx = int(token)
        except ValueError:
            return None
        if not 0 <= idx < count or idx in picks:
            return None
        picks.append(idx)
    return picks or None


def choose_leds(leds, default, t):
    """ask for one or many leds, fall back to the config default."""
    print(t["leds_header"])
    for i, led in enumerate(leds):
        print(f"[{i}] {led['name']} (max {led['max']})")
    shown = default or t["default_none"]
    raw = ask(t["leds_prompt"].format(default=shown))
    if raw:
        picks = parse_led_pick(raw, len(leds))
        if picks is None:
            return None
        return [leds[i] for i in picks]
    if default:
        return resolve_leds(default, leds)
    return None


def choose_patch(patches, default, t):
    print(t["patches_header"])
    for i, patch in enumerate(patches):
        print(f"[{i}] {patch}")
    shown = default or t["default_none"]
    raw = ask(t["patch_prompt"].format(default=shown))
    if raw:
        want = normalize_patch(raw)
        try:
            idx = int(raw)
        except ValueError:
            idx = None
        if idx is not None and 0 <= idx < len(patches):
            want = patches[idx]
        if want in patches:
            return want
        return None
    if default:
        want = normalize_patch(default)
        return want if want in patches else None
    return None


def normalize_hz(hz, t):
    if MIN_HZ <= hz <= MAX_HZ:
        return hz
    print(t["bad_hz"])
    return DEFAULT_HZ


def ask_hz(default, t):
    raw = ask(t["hz_prompt"])
    if not raw:
        return normalize_hz(default, t)
    try:
        hz = int(raw)
    except ValueError:
        hz = 0
    return normalize_hz(hz, t)


def create_flow(t, args, conf):
    """build one daemon, from flags or from the interactive menus."""
    leds = find_leds()
    if not leds:
        print(t["no_leds"])
        return
    patches = find_patches()
    if not patches:
        print(t["no_patches"])
        return

    if args.build:
        picked = resolve_leds(args.build[0], leds)
        if picked is None:
            print(t["unknown_led"], args.build[0])
            return
        patch_name = normalize_patch(args.build[1])
        if patch_name not in patches:
            print(t["unknown_patch"], args.build[1])
            return
        hz = normalize_hz(pick_hz(args, conf), t)
        install = args.install
    else:
        default_led = conf.get("led")
        picked = choose_leds(leds, default_led, t)
        if not picked:
            if default_led:
                print(t["unknown_led"], default_led)
            print(t["failed"])
            return
        patch_name = choose_patch(patches, conf.get("patch"), t)
        if patch_name is None:
            print(t["failed"])
            return
        hz = ask_hz(pick_hz(args, conf), t)
        install = None

    bin_path = build_daemon(picked, patch_name, hz, t,
                            disk=conf.get("disk", ""), iface=conf.get("iface", ""))
    if bin_path is None:
        return
    if install is None:
        answer = ask(t["install_prompt"])
        install = answer is not None and answer.lower() == "y"
    if not install:
        return
    if os.geteuid() != 0:
        print(t["root_required"])
        return
    led_names = ", ".join(led["name"] for led in picked)
    backend = pick_backend(args.init or conf.get("init"), t)
    if backend is None:
        print(t["failed"])
        return
    backend.install(bin_path, unit_name_for(picked), led_names, t)


def collect_services():
    """every sysblink unit known to any backend, deduped, first backend wins."""
    found = []
    for backend in BACKENDS:
        for unit in backend.installed():
            if all(unit != seen for _, seen in found):
                found.append((backend, unit))
    return found


def remove_flow(t):
    """show every sysblink service known to any backend and remove the pick."""
    if os.geteuid() != 0:
        print(t["root_required"])
        return
    found = collect_services()
    if not found:
        print(t["no_services"])
        return
    print(t["remove_header"])
    for i, (backend, unit) in enumerate(found):
        print(f"[{i}] {backend.name}: {unit}")
    raw = ask(t["choose"])
    if raw is None:
        print(t["failed"])
        return
    try:
        idx = int(raw)
    except ValueError:
        print(t["failed"])
        return
    if not 0 <= idx < len(found):
        print(t["failed"])
        return
    backend, unit = found[idx]
    backend.remove(unit, t)


def remove_all_flow(t):
    """wipe every sysblink service known to any backend."""
    if os.geteuid() != 0:
        print(t["root_required"])
        return
    found = collect_services()
    if not found:
        print(t["no_services"])
        return
    for backend, unit in found:
        backend.remove(unit, t)


def interactive(t, args, conf):
    if not args.lang and not conf.get("lang"):
        raw = ask(t["lang_prompt"])
        t = load_texts("ru" if raw == "2" else "en")
    while True:
        print(t["menu"])
        choice = ask(t["choose"])
        if choice is None or choice == "0":
            print(t["bye"])
            return
        if choice == "1":
            create_flow(t, args, conf)
        elif choice == "2":
            remove_flow(t)
        elif choice == "3":
            remove_all_flow(t)


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog="sysblink", description="build led daemons from patches",
    )
    parser.add_argument("--lang", choices=("en", "ru"), default=None,
                        help="interface language")
    parser.add_argument("--list_leds", action="store_true",
                        help="list leds and exit")
    parser.add_argument("--list_patches", action="store_true",
                        help="list patches and exit")
    parser.add_argument("--list_inits", action="store_true",
                        help="list init backends, the detected one is marked")
    parser.add_argument("--build", nargs=2, metavar=("LED", "PATCH"),
                        help="build a daemon for one led or a comma separated "
                             "list of leds and one patch, then exit")
    parser.add_argument("--hz", type=int, default=None,
                        help=f"update frequency in hz, {MIN_HZ} to {MAX_HZ}")
    parser.add_argument("--install", action="store_true",
                        help="install the built daemon as a service")
    parser.add_argument("--init", choices=[b.name for b in BACKENDS],
                        default=None, help="init backend to use")
    parser.add_argument("--remove", action="store_true",
                        help="remove an installed service, then exit")
    parser.add_argument("--remove_all", action="store_true",
                        help="remove every installed service, then exit")
    parser.add_argument("--version", action="version",
                        version=f"sysblink {VERSION}")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    conf = load_config()
    t = load_texts(pick_lang(args, conf))

    if args.list_leds:
        for led in find_leds():
            print(f"{led['name']} max={led['max']} path={led['path']}")
        return 0
    if args.list_patches:
        for patch in find_patches():
            print(patch)
        return 0
    if args.list_inits:
        for backend in BACKENDS:
            mark = "*" if backend.detect() else " "
            print(f"[{mark}] {backend.name}")
        return 0
    if args.remove:
        remove_flow(t)
        return 0
    if args.remove_all:
        remove_all_flow(t)
        return 0
    if args.build:
        create_flow(t, args, conf)
        return 0
    interactive(t, args, conf)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print()
        sys.exit(130)
