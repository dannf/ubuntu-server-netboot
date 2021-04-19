# Autoinstall
By using autoinstall we could automate the subiquity installer like what `preseed` is used for `debian-installer`, a.k.a. `d-i`.

## Usage
1. Upload your `user-data` to a www server. You may use `basic.yaml` as an example. Rename `basic.yaml` to be `user-data` and put it into a www server to serve it. By using `basic.yaml` the default username and password will be both `ubuntu`. You can change the default username and password by following the instruction in the comment block of `basic.yaml`.
2. `touch <your www server>/meta-data` to create an empty but necessary file required by `cloud-init`.
3. Include the necessary kernel parameters `autoinstall "ds=nocloud-net;s=http://<www-server-url>/"`. For UEFI, it is usually the line of `linux` in your `grub.cfg`. If you are working on `pxelinux.cfg` for legacy mode, please do something similar in your `APPEND` line. For example,
     - as is `quiet splash root=/dev/ram0 ramdisk_size=1500000 ip=dhcp url=http://<server-provides-image>/focal-live-server-arm64.iso ---`
     - to be `quiet splash root=/dev/ram0 ramdisk_size=1500000 ip=dhcp url=http://<server-provides-image>/focal-live-server-arm64.iso autoinstall "ds=nocloud-net;s=http://<server-provides-user-data>/" ---`

## Trouble-shooting and Tips
- The format of the first line "shebang", a.k.a. `#cloud-config` matters. Do not change it or input extra spaces
  unless you know what you are doing.
- The double quotes matter when injecting `user-data` in the kernel parameters.
- The file name `user-data` is a must. Its the file name that `cloud-init` will look for.
- The file `meta-data` is also a must, even it is an empty file in our example.
- The trailing slash of the url serving `user-data` matters in the current autoinstall version.
