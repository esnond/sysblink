#!/usr/bin/env python3
"""unit checks for the python side of sysblink, run via make test."""

import contextlib
import importlib.util
import io
import os
import pathlib
import tempfile
import unittest

_SPEC = importlib.util.spec_from_file_location(
    "sysblink", pathlib.Path(__file__).resolve().parent.parent / "sysblink.py",
)
sysblink = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(sysblink)


def make_fake_leds(root, specs):
    """create fake led dirs, specs are (name, max) pairs, return led dicts."""
    leds = []
    for name, top in specs:
        led_dir = root / name
        led_dir.mkdir(parents=True, exist_ok=True)
        (led_dir / "brightness").write_text("0")
        (led_dir / "max_brightness").write_text(top)
        leds.append({"name": name, "path": str(led_dir), "max": top})
    return leds


class ParserChecks(unittest.TestCase):
    def test_sanitize_name(self):
        self.assertEqual(sysblink.sanitize_name("input13::scrolllock"), "input13_scrolllock")
        self.assertEqual(sysblink.sanitize_name("TPacpi::Power"), "tpacpi_power")

    def test_normalize_patch(self):
        self.assertEqual(sysblink.normalize_patch("cpu"), "cpu.c")
        self.assertEqual(sysblink.normalize_patch("breathe.c"), "breathe.c")

    def test_parse_led_pick(self):
        self.assertEqual(sysblink.parse_led_pick("0", 3), [0])
        self.assertEqual(sysblink.parse_led_pick("0 2", 3), [0, 2])
        self.assertEqual(sysblink.parse_led_pick("all", 3), [0, 1, 2])
        self.assertIsNone(sysblink.parse_led_pick("2 2", 3))
        self.assertIsNone(sysblink.parse_led_pick("5", 3))
        self.assertIsNone(sysblink.parse_led_pick("x", 3))
        self.assertIsNone(sysblink.parse_led_pick("", 3))

    def test_resolve_leds(self):
        leds = [
            {"name": "input13::scrolllock", "path": "/x", "max": "1"},
            {"name": "tpacpi::power", "path": "/y", "max": "255"},
        ]
        self.assertEqual(sysblink.resolve_leds("input13::scrolllock,tpacpi::power", leds), leds)
        self.assertEqual(sysblink.resolve_leds("input13::scrolllock", leds), [leds[0]])
        self.assertIsNone(sysblink.resolve_leds("nope", leds))
        self.assertIsNone(sysblink.resolve_leds("tpacpi::power,nope", leds))

    def test_unit_name(self):
        leds = [{"name": "input13::scrolllock"}, {"name": "tpacpi::power"}]
        self.assertEqual(sysblink.unit_name_for(leds), "sysblink_input13_scrolllock_tpacpi_power")


class ConfigChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_conf = sysblink.CONF_FILE
        self.conf_path = pathlib.Path(self.tmp.name) / "sysblink.conf"

    def tearDown(self):
        sysblink.CONF_FILE = self.old_conf
        self.tmp.cleanup()

    def test_load_config(self):
        self.conf_path.write_text(
            "# comment\nlang = ru\nhz = 30\nled = input13::scrolllock\n\njunk line\n",
        )
        sysblink.CONF_FILE = self.conf_path
        self.assertEqual(
            sysblink.load_config(),
            {"lang": "ru", "hz": "30", "led": "input13::scrolllock"},
        )

    def test_missing_config(self):
        sysblink.CONF_FILE = pathlib.Path(self.tmp.name) / "absent.conf"
        self.assertEqual(sysblink.load_config(), {})

    def test_pick_lang_and_hz(self):
        class Args:
            lang = None
            hz = None

        self.assertEqual(sysblink.pick_lang(Args, {"lang": "ru"}), "ru")
        self.assertIn(sysblink.pick_lang(Args, {}), ("en", "ru"))
        self.assertEqual(sysblink.pick_hz(Args, {"hz": "25"}), 25)
        self.assertEqual(sysblink.pick_hz(Args, {"hz": "junk"}), sysblink.DEFAULT_HZ)
        Args.hz = 7
        self.assertEqual(sysblink.pick_hz(Args, {"hz": "25"}), 7)


class RenderChecks(unittest.TestCase):
    def test_render_source_is_complete(self):
        leds = [
            {"name": "a", "path": "/leds/a", "max": "255"},
            {"name": "b", "path": "/leds/b", "max": "1"},
        ]
        code = sysblink.render_source(leds, 50, "int get_led_value(void) { return 7; }")
        self.assertNotIn("{{", code)
        self.assertNotIn("/* PATCH_INSERT */", code)
        self.assertIn("#define LED_COUNT 2", code)
        self.assertIn("{ 255, 1 }", code)
        self.assertIn("{ \"/leds/a/brightness\", \"/leds/b/brightness\" }", code)
        self.assertIn("int get_led_value(void) { return 7; }", code)
        version_line = code.split("#define VERSION", 1)[1][:40]
        self.assertIn(f'"{sysblink.VERSION}"', version_line)
        self.assertIn('#define BLINK_DISK_DEVICE ""', code)
        self.assertIn('#define BLINK_NET_IFACE ""', code)

    def test_render_source_pins_sources(self):
        leds = [{"name": "a", "path": "/leds/a", "max": "255"}]
        code = sysblink.render_source(leds, 10, "int x;", disk="sdb", iface="wlan0")
        self.assertIn('#define BLINK_DISK_DEVICE "sdb"', code)
        self.assertIn('#define BLINK_NET_IFACE "wlan0"', code)


class LedDiscoveryChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_base = sysblink.LED_BASE
        sysblink.LED_BASE = pathlib.Path(self.tmp.name)

    def tearDown(self):
        sysblink.LED_BASE = self.old_base
        self.tmp.cleanup()

    def test_find_leds(self):
        make_fake_leds(pathlib.Path(self.tmp.name), [("input13::scrolllock", "255")])
        leds = sysblink.find_leds()
        self.assertEqual(len(leds), 1)
        self.assertEqual(leds[0]["name"], "input13::scrolllock")
        self.assertEqual(leds[0]["max"], "255")

    def test_find_leds_skips_unwritable(self):
        leds = make_fake_leds(pathlib.Path(self.tmp.name), [("dark", "1")])
        os.chmod(pathlib.Path(leds[0]["path"]) / "brightness", 0o000)
        try:
            self.assertEqual(sysblink.find_leds(), [])
        finally:
            os.chmod(pathlib.Path(leds[0]["path"]) / "brightness", 0o644)

    def test_find_leds_without_base(self):
        sysblink.LED_BASE = pathlib.Path(self.tmp.name) / "absent"
        self.assertEqual(sysblink.find_leds(), [])


class BackendChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = pathlib.Path(self.tmp.name)
        self.old = {
            name: getattr(sysblink, name)
            for name in ("BIN_DIR", "SYSTEMD_UNIT_DIR", "INITD_DIR",
                         "RUNIT_SCANDIRS", "S6_SCANDIRS", "run_quiet")
        }
        for name in ("bin", "systemd", "init.d", "runit", "s6"):
            (root / name).mkdir()
        (root / "runit" / ".keep").touch()
        (root / "s6" / ".keep").touch()
        sysblink.BIN_DIR = root / "bin"
        sysblink.SYSTEMD_UNIT_DIR = root / "systemd"
        sysblink.INITD_DIR = root / "init.d"
        sysblink.RUNIT_SCANDIRS = (str(root / "runit"),)
        sysblink.S6_SCANDIRS = (str(root / "s6"),)
        sysblink.run_quiet = lambda cmd: None
        self.bin_path = root / "fakebin"
        self.bin_path.write_bytes(b"\x7fELFfake")
        self.unit = "sysblink_test_led"
        self.t = sysblink.load_texts("en")

    def tearDown(self):
        for name, value in self.old.items():
            setattr(sysblink, name, value)
        self.tmp.cleanup()

    def expected(self, *parts):
        return pathlib.Path(self.tmp.name).joinpath(*parts)

    def check_systemd(self):
        sysblink.Systemd().install(self.bin_path, self.unit, "test::led", self.t)
        unit_file = self.expected("systemd", f"{self.unit}.service")
        text = unit_file.read_text()
        self.assertIn(f"ExecStart={sysblink.BIN_DIR / self.unit}", text)
        self.assertIn("ProtectSystem=strict", text)
        self.assertIn("NoNewPrivileges=yes", text)
        self.assertEqual(sysblink.Systemd().installed(), [self.unit])
        sysblink.Systemd().remove(self.unit, self.t)
        self.assertFalse(unit_file.exists())

    def check_scandir_backend(self, backend_class, dirname):
        backend = backend_class()
        backend.install(self.bin_path, self.unit, "test::led", self.t)
        run_file = self.expected(dirname, self.unit, "run")
        self.assertIn(f"exec {sysblink.BIN_DIR / self.unit}", run_file.read_text())
        self.assertEqual(backend.installed(), [self.unit])
        backend.remove(self.unit, self.t)
        self.assertFalse(self.expected(dirname, self.unit).exists())

    def check_initd_backend(self, backend_class, marker):
        backend = backend_class()
        backend.install(self.bin_path, self.unit, "test::led", self.t)
        script = self.expected("init.d", self.unit)
        text = script.read_text()
        self.assertIn(marker, text)
        self.assertEqual(backend.installed(), [self.unit])
        backend.remove(self.unit, self.t)
        self.assertFalse(script.exists())

    def test_systemd(self):
        self.check_systemd()

    def test_openrc(self):
        self.check_initd_backend(sysblink.OpenRC, "#!/sbin/openrc-run")

    def test_sysvinit(self):
        self.check_initd_backend(sysblink.Sysvinit, "### BEGIN INIT INFO")

    def test_runit(self):
        self.check_scandir_backend(sysblink.Runit, "runit")

    def test_s6(self):
        self.check_scandir_backend(sysblink.S6, "s6")

    def test_installed_lists_are_deduped_by_remove_flow_source(self):
        """openrc and sysvinit share /etc/init.d, both list the same unit."""
        sysblink.OpenRC().install(self.bin_path, self.unit, "t", self.t)
        self.assertEqual(sysblink.OpenRC().installed(), [self.unit])
        self.assertEqual(sysblink.Sysvinit().installed(), [self.unit])


class BuildChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_build = sysblink.BUILD_DIR
        sysblink.BUILD_DIR = pathlib.Path(self.tmp.name) / "build"

    def tearDown(self):
        sysblink.BUILD_DIR = self.old_build
        self.tmp.cleanup()

    def test_build_daemon(self):
        led_dir = pathlib.Path(self.tmp.name) / "leds" / "test::led"
        led_dir.mkdir(parents=True)
        (led_dir / "brightness").write_text("0")
        led = {"name": "test::led", "path": str(led_dir), "max": "255"}
        t = sysblink.load_texts("en")
        bin_path = sysblink.build_daemon([led], "breathe", 100, t, disk="sda")
        self.assertIsNotNone(bin_path)
        self.assertTrue(pathlib.Path(bin_path).exists())
        src = (sysblink.BUILD_DIR / "sysblink_test_led.c").read_text()
        self.assertNotIn("{{", src)
        self.assertIn('#define BLINK_DISK_DEVICE "sda"', src)

    def test_build_daemon_unknown_patch(self):
        led = {"name": "x", "path": "/tmp", "max": "255"}
        t = sysblink.load_texts("en")
        self.assertIsNone(sysblink.build_daemon([led], "does_not_exist", 10, t))

    def test_version_flag(self):
        buf = io.StringIO()
        with self.assertRaises(SystemExit) as caught:
            with contextlib.redirect_stdout(buf):
                sysblink.main(["--version"])
        self.assertEqual(caught.exception.code, 0)
        self.assertEqual(buf.getvalue().strip(), f"sysblink {sysblink.VERSION}")


if __name__ == "__main__":
    unittest.main()
