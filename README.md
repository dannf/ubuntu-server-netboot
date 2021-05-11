# ubuntu-server-netboot
This utility generates a netboot directory tree from an Ubuntu Server Live ISO image, an image based on the `subiquity` installer. The tree contents are similar to the contents of the `netboot.tar.gz` file that debian-installer builds provide. Example:

```
$ ./ubuntu-server-netboot --url http://releases.ubuntu.com/focal/ubuntu-20.04.2-live-server-amd64.iso
INFO: Downloading http://releases.ubuntu.com/focal/ubuntu-20.04.2-live-server-amd64.iso
INFO: Attempting to download http://archive.ubuntu.com/ubuntu/dists/focal-updates/main/uefi/grub2-amd64/current/grubx64.efi.signed
INFO: Netboot generation complete: /tmp/tmpo54145m2/ubuntu-installer
```

The `--url` parameter is used for 2 reasons:

1. `ubuntu-server-netboot` will download the image at runtime to extract the necessary files from it.
1. Subiquity-based installs need to download an image at install-time. `ubuntu-server-netboot` will generate configuration files that point the installer to this URL.

If you have a local copy of the ISO, you can point to it with the `--iso` parameter to avoid having `ubuntu-server-netboot` download an extra copy. Just be sure that `--iso` and `--url` point to the same version of the ISO.

Optionally, you can place `--autoinstall-url` to tell the netbooting process to enable subiquity automation. See [our autoinstall example](./autoinstall/README.md) and [the autoinstall and Automated Server Installs
Introduction of Ubuntu Server guide](Automated Server Installs Introduction) for more details.

You can also add additional kernel command line arguments (e.g. `"console=ttyS0"`) to the generated configuration files using the `--extra-args` parameter.

## Usage of the Generated Files
Copy the files generated under the interim folder `/tmp/tmpxxx/ubuntu-installer/`
to your tftp root folder for netboot, for example `/srv/tftp` or `/var/lib/tftpboot`.
You may check your tftpd configuration of the root directory, for instance, tftpd-hpa is `/etc/default/tftpd-hpa`. Let's copy:

```
$ sudo cp -r /tmp/tmpxxx/ubuntu-installer/* /srv/tftp
```

Then your netboot server is ready to go if the corresponding DHCP is set up.

## Troubleshooting
For more details on setting up a PXE environment for x86 systems using a legacy BIOS, see [this discourse post](https://discourse.ubuntu.com/t/netbooting-the-server-installer-on-amd64/16620).

For more details on setting up a PXE environment for UEFI-based systems, see [this discourse post](https://discourse.ubuntu.com/t/netbooting-the-live-server-installer-via-uefi-pxe-on-arm-aarch64-arm64-and-x86-64-amd64/19240).

## Dependencies
Today `ubuntu-server-netboot` needs to run on Ubuntu or another Debian derivative with the following packages installed:

 - genisoimage
 - mtools
 - python3-distro-info
 - pxelinux (x86-only)
 - syslinux-common (x86-only)

This script is tested with Ubuntu 18.04 ("bionic beaver") and above.

## Contribution and Development

Please report bugs to [this github issue tracker](https://github.com/dannf/ubuntu-server-netboot/issues). The github templates including "Issue" and "Pull requests" are originally forked from [this "cookiecutter" templates for python](https://github.com/Lee-W/cookiecutter-python-template).

Place `pytest` to cover the basic test sets.
