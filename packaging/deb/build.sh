#!/bin/sh
# builds a deb from the project tree, needs dpkg-deb
# the package installs the installer to /usr/bin and the project tree to
# /usr/share/sysblink, sysblink.py finds the tree there on its own
# the release workflow passes VERSION from the git tag, default is 1.0.0

set -eu
cd "$(dirname "$0")/../.."

VERSION=${VERSION:-$(cat VERSION 2>/dev/null || echo 1.0.0)}
stage=build/deb
rm -rf "$stage"
mkdir -p "$stage/DEBIAN" "$stage/usr/bin" "$stage/usr/share/sysblink/patches" \
         "$stage/usr/share/sysblink/docs" "$stage/usr/share/sysblink/tests" \
         "$stage/usr/share/man/man1"

install -m 755 sysblink.py "$stage/usr/bin/sysblink"
install -m 644 VERSION engine.c README.md README.ru.md sysblink.conf.example "$stage/usr/share/sysblink/"
install -m 644 patches/*.c patches/config.h "$stage/usr/share/sysblink/patches/"
install -m 644 docs/patches.md docs/patches.ru.md "$stage/usr/share/sysblink/docs/"
install -m 644 docs/sysblink.1 "$stage/usr/share/man/man1/sysblink.1"
sed -i "s/\"sysblink [0-9][^\"]*\"/\"sysblink $VERSION\"/" "$stage/usr/share/man/man1/sysblink.1"
install -m 644 tests/run.sh "$stage/usr/share/sysblink/tests/"

cat > "$stage/DEBIAN/control" <<CONF
Package: sysblink
Version: $VERSION
Section: utils
Priority: optional
Architecture: all
Maintainer: esnond
Depends: python3, gcc | cc
Description: led system meters built from patches
 sysblink builds small daemons that show cpu, memory, disk, network, thermal
 and battery levels on sysfs leds, and registers them with the init
 system it finds.
CONF

dpkg-deb --root-owner-group --build "$stage" "build/sysblink_${VERSION}_all.deb"
echo "built build/sysblink_${VERSION}_all.deb"
