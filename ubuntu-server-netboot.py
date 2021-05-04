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

Netboot_Args = ["root=/dev/ram0", "ramdisk_size=1500000", "ip=dhcp"]


class UbuntuDistroInfoWithVersionSupport(distro_info.UbuntuDistroInfo):
    """
    The version() method wasn't supported by distro_info until
    version 0.23, which is newer than some supported releases
    ship (Ubuntu 18.04 currently has 0.18). Extend the class
    to provide our own copy for backwards compatibility.
    """

    def version(self, name, default=None):
        """Map codename or series to version"""
        for release in self._releases:
            if name in (release.codename, release.series):
                return release.version
        return default


class ServerLiveIso:
    def __init__(self, iso_path):
        self.path = iso_path
        iso_info_output = subprocess.check_output(
            ["isoinfo", "-d", "-i", iso_path],
        )
        for line in iso_info_output.decode("utf-8").split("\n"):
            if not line.startswith("Volume id: "):
                continue
            vol_id = line[len("Volume id: ") :]
            break
        ubuntu_vol_id_re = re.compile(
            r"^Ubuntu-Server "
            + "(?P<release>[0-9]{2}.[0-9]{2})(.[0-9]+)?"
            + "(?P<lts> LTS)? (?P<arch>.*)$"
        )
        m = ubuntu_vol_id_re.match(vol_id)
        if not m:
            raise Exception("%s does not look like an Ubuntu Server ISO" % (self.path))
        self.architecture = m.group("arch")
        self.version = m.group("release")
        if m.group("lts"):
            self.version = self.version + m.group("lts")
        udi = UbuntuDistroInfoWithVersionSupport()
        for codename in udi.supported():
            if self.version != udi.version(codename):
                continue
            self.codename = codename
            break

    def has_file(self, path):
        for entry in (
            subprocess.check_output(["isoinfo", "-J", "-f", "-i", self.path])
            .decode("utf-8")
            .split("\n")
        ):
            if entry.lstrip("/") == path.lstrip("/"):
                return True
        return False

    def extract_file(self, path, dest):
        # isoinfo reports success extracting a file even if it doesn't
        # exist, so let's check that it exists before proceeding
        if not self.has_file(path):
            raise FileNotFoundError("%s not found on Ubuntu Server ISO" % (path))

        with open(dest, "w") as outf:
            child = subprocess.Popen(
                ["isoinfo", "-J", "-i", self.path, "-x", path],
                stdout=outf,
            )
            child.communicate()
        if child.returncode != 0:
            raise Exception("Error extracting %s from Ubuntu Server ISO" % (path))

    def read_file(self, path):
        return subprocess.check_output(
            ["isoinfo", "-J", "-i", self.path, "-x", path],
        )


class BootloaderConfig:
    """
    A base class that can be overridden for specific bootloaders
    """

    def add_kernel_params(self, params, install_only=False):
        new_cfg = ""
        for line in self.cfg.split("\n"):
            index = line.find("---")
            if index != -1:
                param_str = " ".join(params)
                if install_only:
                    replace = "%s ---" % (param_str)
                else:
                    replace = "--- %s" % (param_str)
                line = line.replace("---", replace)
            new_cfg += "%s\n" % (line)
        self.cfg = new_cfg

    def __str__(self):
        return self.cfg


class GrubConfig(BootloaderConfig):
    """
    This BootloaderConfig subclass for GRUB takes a seedcfg - the
    grub.cfg scraped from the ISO - and modifies it from there.
    """

    def __init__(self, seedcfg):
        self.cfg = seedcfg


class PxelinuxConfig(BootloaderConfig):
    """
    This BootloaderConfig subclass for pxelinux needs to generate
    a starting config. Unlike for GRUB, there's no file to use as
    a seed on the ISO.
    """

    def __init__(self):
        self.cfg = """DEFAULT install
LABEL install
  KERNEL casper/vmlinuz
  INITRD casper/initrd
  APPEND ---"""


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
        url = "%s/dists/%s/main/uefi/grub2-%s/current/grubnet%s.efi.signed" % (
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


def setup_kernel_params(bootloader_cfg):
    bootloader_cfg.add_kernel_params(
        Netboot_Args + ["url=%s" % (args.url)], install_only=True
    )
    if args.autoinstall_url:
        bootloader_cfg.add_kernel_params(
            [
                'autoinstall "ds=nocloud-net;s=%s"' % (args.autoinstall_url),
            ],
            install_only=True,
        )
    if args.extra_args:
        bootloader_cfg.add_kernel_params(args.extra_args.split(" "))


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
    parser.add_argument(
        "--autoinstall-url",
        help="URL to Autoinstall config file to be used during Subiquity installation",
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
    try:
        for hwe_f in ["hwe-vmlinuz", "hwe-initrd"]:
            iso.extract_file(
                os.path.join(os.sep, "casper", hwe_f),
                os.path.join(staging_dir, "casper", hwe_f),
            )
    except FileNotFoundError:
        logger.info("No HWE boot files found, skipping")
        pass

    grub_cfg_orig = iso.read_file(os.path.join(os.sep, "boot", "grub", "grub.cfg"))
    grub_cfg = GrubConfig(grub_cfg_orig.decode("utf-8"))
    setup_kernel_params(grub_cfg)

    os.mkdir(os.path.join(staging_dir, "grub"))
    with open(os.path.join(staging_dir, "grub", "grub.cfg"), "w") as grub_f:
        grub_f.write(str(grub_cfg))

    if architecture == "amd64":
        local_files = [
            (os.path.join(os.sep, "usr", "lib", "PXELINUX", "pxelinux.0"), "pxelinux"),
            (
                os.path.join(
                    os.sep, "usr", "lib", "syslinux", "modules", "bios", "ldlinux.c32"
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
        pxelinux_cfg = PxelinuxConfig()
        setup_kernel_params(pxelinux_cfg)
        with open(os.path.join(pxelinux_dir, "default"), "w") as pxelinux_f:
            pxelinux_f.write(str(pxelinux_cfg))

    atexit.unregister(cleanup)
    logger.info("Netboot generation complete: %s" % (staging_dir))
