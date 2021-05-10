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
import argparse
import atexit
import logging
import os
import shutil
import sys
import tempfile
import urllib.request
from usn.ubuntu_server_netboot import (
    GrubConfig,
    ServerLiveIso,
    PxelinuxConfig,
    cleanup,
    download_bootnet,
    setup_kernel_params,
)


def ubuntu_server_netboot():
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
        logger.info("Downloading %s" % args.url)
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
        atexit.register(cleanup, staging_dir, logger)
    else:
        atexit.register(cleanup, staging_root, logger)

    download_bootnet(release, architecture, staging_dir, logger)

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
    setup_kernel_params(grub_cfg, args.url, args.autoinstall_url, args.extra_args)

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
                sys.stderr.write("%s\n" % err)
                sys.stderr.write("Try installing %s.\n" % pkg)
                sys.exit(1)

        pxelinux_dir = os.path.join(staging_dir, "pxelinux.cfg")
        os.mkdir(pxelinux_dir)
        pxelinux_cfg = PxelinuxConfig()
        setup_kernel_params(
            pxelinux_cfg, args.url, args.autoinstall_url, args.extra_args
        )
        with open(os.path.join(pxelinux_dir, "default"), "w") as pxelinux_f:
            pxelinux_f.write(str(pxelinux_cfg))

    atexit.unregister(cleanup)
    logger.info("Netboot generation complete: %s" % staging_dir)
