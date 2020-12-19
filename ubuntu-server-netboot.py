#!/usr/bin/env python3
#
# Copyright (C) 2020 Canonical, Ltd.
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
import argparse
import atexit
import distro_info
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request

Netboot_Args = "root=/dev/ram0 ramdisk_size=1500000 ip=dhcp"


class ServerLiveIso:
    def __init__(self, iso_path):
        self.path = iso_path
        iso_info_output = subprocess.check_output(
            ["isoinfo", "-d", "-i", iso_path],
        )
        for line in iso_info_output.decode("utf-8").split("\n"):
            if not line.startswith("Volume id: "):
                continue
            vol_id = line[len("Volume id: "):]
            break
        ubuntu_vol_id_re = re.compile(
            r"^Ubuntu-Server "
            + "(?P<release>[0-9]{2}.[0-9]{2})(.[0-9]+)?"
            + "(?P<lts> LTS)? (?P<arch>.*)$"
        )
        m = ubuntu_vol_id_re.match(vol_id)
        if not m:
            raise Exception(
                "%s does not look like an Ubuntu Server ISO" % (self.path)
            )
        self.architecture = m.group("arch")
        self.version = m.group("release")
        if m.group("lts"):
            self.version = self.version + m.group("lts")
        udi = distro_info.UbuntuDistroInfo()
        for codename in udi.supported():
            if self.version != udi.version(codename):
                continue
            self.codename = codename
            break

    def extract_file(self, path, dest):
        with open(dest, "w") as outf:
            subprocess.Popen(
                ["isoinfo", "-J", "-i", self.path, "-x", path],
                stdout=outf,
            )

    def read_file(self, path):
        return subprocess.check_output(
            ["isoinfo", "-J", "-i", self.path, "-x", path],
        )


def select_mirror(arch):
    # FIXME: When I try to use https, I get:
    # urllib.error.URLError:
    #  <urlopen error [Errno 97] Address family not supported by protocol>
    if arch in ["amd64", "i386"]:
        return "http://archive.ubuntu.com/ubuntu"
    else:
        return "http://ports.ubuntu.com/ubuntu-ports"


Ubuntu_Arch_to_Uefi_Arch_Abbrev = {
    "amd64": "x64",
    "arm64": "aa64",
}


def download_bootnet(release, architecture, destdir):
    uefi_arch_abbrev = Ubuntu_Arch_to_Uefi_Arch_Abbrev[architecture]
    for pocket in ["%s-updates" % (release), release]:
        url = "%s/dists/%s/main/uefi/grub2-%s/current/grub%s.efi.signed" % (
            select_mirror(architecture),
            pocket,
            architecture,
            uefi_arch_abbrev,
        )
        outfile = os.path.join(destdir, "grubnet%s.efi" % (uefi_arch_abbrev))
        try:
            logger.info("Attempting to download %s" % (url))
            with urllib.request.urlopen(url) as response:
                with open(outfile, "wb") as outf:
                    shutil.copyfileobj(response, outf)
                    return
        except urllib.error.HTTPError:
            # Assuming a 404
            continue
    raise Exception("Could not download %s" % (url))


def download_pxelinux(release, destdir):
    for pocket in ["%s-updates" % (release), release]:
        mirror = select_mirror("amd64")
        url = (
            "%s/dists/%s/main/installer-amd64/" % (mirror, pocket)
            + "current/images/netboot/ubuntu-installer/amd64/pxelinux.0"
        )
        outfile = os.path.join(destdir, "pxelinux.0")
        try:
            logger.info("Attempting to download %s" % (url))
            with urllib.request.urlopen(url) as response:
                with open(outfile, "wb") as outf:
                    shutil.copyfileobj(response, outf)
                    return
        except urllib.error.HTTPError:
            # Assuming a 404
            continue
    raise Exception("Could not download %s" % (url))


def cleanup(directory):
    logger.info("Cleaning up %s" % (directory))
    shutil.rmtree(directory)


if __name__ == "__main__":
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    ch = logging.StreamHandler()
    formatter = logging.Formatter("%(levelname)s: %(message)s")
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    parser = argparse.ArgumentParser(
        description="Generate a netboot tree from an Ubuntu Server live ISO"
    )
    parser.add_argument(
        "-e",
        "--extra-args",
        help="Any additional kernel command line arguments",
    )
    parser.add_argument(
        "--iso",
        help="Local copy of Server Live ISO"
        + " (--url should point to a copy of the same file)",
    )
    parser.add_argument(
        "-o",
        "--out-dir",
        help="Output directory",
    )
    parser.add_argument(
        "--url",
        help="URL to Server Live ISO to be downloaded at install-time",
        required=True,
    )

    args = parser.parse_args()
    if args.iso:
        iso = ServerLiveIso(args.iso)
    else:
        logger.info("Downloading %s" % (args.url))
        with urllib.request.urlopen(args.url) as response:
            with tempfile.NamedTemporaryFile(delete=False) as iso:
                atexit.register(os.remove, iso.name)
                shutil.copyfileobj(response, iso)
                iso = ServerLiveIso(iso.name)

    architecture = iso.architecture
    release = iso.codename

    staging_root = args.out_dir or tempfile.mkdtemp()
    staging_dir = os.path.join(staging_root, "ubuntu-installer")
    os.mkdir(staging_dir)
    if args.out_dir:
        atexit.register(cleanup, staging_dir)
    else:
        atexit.register(cleanup, staging_root)

    download_bootnet(release, architecture, staging_dir)

    os.mkdir(os.path.join(staging_dir, "casper"))
    for f in ["vmlinuz", "initrd"]:
        iso.extract_file(
            os.path.join(os.sep, "casper", f),
            os.path.join(staging_dir, "casper", f),
        )

    grub_cfg_orig = iso.read_file(
        os.path.join(os.sep, "boot", "grub", "grub.cfg")
    )
    os.mkdir(os.path.join(staging_dir, "grub"))
    with open(os.path.join(staging_dir, "grub", "grub.cfg"), "w") as grub_cfg:
        netboot_args = "%s url=%s" % (Netboot_Args, args.url)
        for line in grub_cfg_orig.decode("utf-8").split("\n"):
            index = line.find("---")
            if index != -1:
                line = "%s%s %s" % (line[:index], netboot_args, line[index:])
                if args.extra_args:
                    line = "%s %s" % (line, args.extra_args)
            grub_cfg.write(line + "\n")

    if architecture == "amd64":
        local_files = [
            (
                os.path.join(os.sep, "usr", "lib", "PXELINUX", "pxelinux.0"),
                "pxelinux"
            ),
            (
                os.path.join(
                    os.sep, "usr", "lib", "syslinux", "modules", "bios",
                    "ldlinux.c32"
                ),
                "syslinux-common",
            ),
        ]
        for (local_file, pkg) in local_files:
            try:
                shutil.copy(local_file, staging_dir)
            except FileNotFoundError as err:
                sys.stderr.write("%s\n" % (err))
                sys.stderr.write("Try installing %s.\n" % (pkg))
                sys.exit(1)

        pxelinux_dir = os.path.join(staging_dir, "pxelinux.cfg")
        os.mkdir(pxelinux_dir)
        with open(os.path.join(pxelinux_dir, "default"), "w") as pxelinux_cfg:
            pxelinux_cfg.write("DEFAULT install\n")
            pxelinux_cfg.write("LABEL install\n")
            pxelinux_cfg.write("  KERNEL casper/vmlinuz\n")
            pxelinux_cfg.write("  INITRD casper/initrd\n")
            pxelinux_cfg.write(
                "  APPEND %s url=%s ---" % (Netboot_Args, args.url)
            )
            if args.extra_args:
                pxelinux_cfg.write(" %s" % (args.extra_args))
            pxelinux_cfg.write("\n")
    atexit.unregister(cleanup)
    logger.info("Netboot generation complete: %s" % (staging_dir))
