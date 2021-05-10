# Copyright (C) 2020-2021 Canonical, Ltd.
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
import distro_info
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.request


Netboot_Args = ["root=/dev/ram0", "ramdisk_size=1500000", "ip=dhcp"]
Ubuntu_Arch_to_Uefi_Arch_Abbrev = {
    "amd64": "x64",
    "arm64": "aa64",
}


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
        vol_id = None
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
        if vol_id:
            m = ubuntu_vol_id_re.match(vol_id)
        else:
            raise Exception("No Volume ID is found.")
        if not m:
            raise Exception("%s does not look like an Ubuntu Server ISO" % self.path)
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
            raise FileNotFoundError("%s not found on Ubuntu Server ISO" % path)

        with open(dest, "w") as outf:
            child = subprocess.Popen(
                ["isoinfo", "-J", "-i", self.path, "-x", path],
                stdout=outf,
            )
            child.communicate()
        if child.returncode != 0:
            raise Exception("Error extracting %s from Ubuntu Server ISO" % path)

    def read_file(self, path):
        return subprocess.check_output(
            ["isoinfo", "-J", "-i", self.path, "-x", path],
        )


class BootloaderConfig:
    """
    A base class that can be overridden for specific bootloaders
    """

    def __init__(self):
        self.cfg = None

    def add_kernel_params(self, params, install_only=False):
        new_cfg = ""
        for line in self.cfg.split("\n"):
            index = line.find("---")
            if index != -1:
                param_str = " ".join(params)
                if install_only:
                    replace = "%s ---" % param_str
                else:
                    replace = "--- %s" % param_str
                line = line.replace("---", replace)
            new_cfg += "%s\n" % line
        self.cfg = new_cfg

    def __str__(self):
        return self.cfg


class GrubConfig(BootloaderConfig):
    """
    This BootloaderConfig subclass for GRUB takes a seedcfg - the
    grub.cfg scraped from the ISO - and modifies it from there.
    """

    def __init__(self, seedcfg):
        super().__init__()
        self.cfg = seedcfg


class PxelinuxConfig(BootloaderConfig):
    """
    This BootloaderConfig subclass for pxelinux needs to generate
    a starting config. Unlike for GRUB, there's no file to use as
    a seed on the ISO.
    """

    def __init__(self):
        super().__init__()
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


def download_bootnet(release, architecture, destdir, logger):
    uefi_arch_abbrev = Ubuntu_Arch_to_Uefi_Arch_Abbrev[architecture]
    for pocket in ["%s-updates" % release, release]:
        url = "%s/dists/%s/main/uefi/grub2-%s/current/grubnet%s.efi.signed" % (
            select_mirror(architecture),
            pocket,
            architecture,
            uefi_arch_abbrev,
        )
        outfile = os.path.join(destdir, "grubnet%s.efi" % uefi_arch_abbrev)
        try:
            logger.info("Attempting to download %s" % url)
            with urllib.request.urlopen(url) as response:
                with open(outfile, "wb") as outf:
                    shutil.copyfileobj(response, outf)
                    return
        except urllib.error.HTTPError:
            # Assuming a 404
            continue
    raise Exception("Could not download %s" % url)


def download_pxelinux(release, destdir, logger):
    for pocket in ["%s-updates" % release, release]:
        mirror = select_mirror("amd64")
        url = (
            "%s/dists/%s/main/installer-amd64/" % (mirror, pocket)
            + "current/images/netboot/ubuntu-installer/amd64/pxelinux.0"
        )
        outfile = os.path.join(destdir, "pxelinux.0")
        try:
            logger.info("Attempting to download %s" % url)
            with urllib.request.urlopen(url) as response:
                with open(outfile, "wb") as outf:
                    shutil.copyfileobj(response, outf)
                    return
        except urllib.error.HTTPError:
            # Assuming a 404
            continue
    raise Exception("Could not download %s" % url)


def setup_kernel_params(bootloader_cfg, url, autoinstall_url, extra_args):
    bootloader_cfg.add_kernel_params(Netboot_Args + ["url=%s" % url], install_only=True)
    if autoinstall_url:
        bootloader_cfg.add_kernel_params(
            [
                'autoinstall "ds=nocloud-net;s=%s"' % autoinstall_url,
            ],
            install_only=True,
        )
    if extra_args:
        bootloader_cfg.add_kernel_params(extra_args.split(" "))


def cleanup(directory, logger):
    logger.info("Cleaning up %s" % directory)
    shutil.rmtree(directory)
