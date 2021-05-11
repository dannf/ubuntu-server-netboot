import pytest

from pkg_resources import resource_filename
from usn import ubuntu_server_netboot


class TestGrubCfg:
    @pytest.fixture(scope="class")
    def grub_cfg_orig_filename(self):
        resource = "tests/data/grub_ubuntu-20.04.2-live-server-arm64.cfg"
        grub_cfg_orig_filename = resource_filename("usn", resource)

        return grub_cfg_orig_filename

    @pytest.fixture(scope="class")
    def grub_cfg_expected_filename(self):
        resource = "tests/data/grub_expected.cfg"
        grub_cfg_expected_filename = resource_filename("usn", resource)

        return grub_cfg_expected_filename

    def test_grub_cfg_ubuntu_20_4_2_live_server_arm64(
        self, grub_cfg_orig_filename, grub_cfg_expected_filename
    ):
        """
        Check the generated grub.cfg content

        Compare the grub.cfg generated with the original grub.cfg extracted from the iso ubuntu 20.04.2 live server
        arm64.
        """
        with open(grub_cfg_orig_filename, "r", encoding="utf-8") as grub_cfg_orig_f:
            bootloader_cfg = ubuntu_server_netboot.GrubConfig(grub_cfg_orig_f.read())

            url = "http://cdimage.ubuntu.com/ubuntu/releases/20.04.2/release/ubuntu-20.04.2-live-server-arm64.iso"
            autoinstall_url = "http://12.34.56.78/"
            extra_args = ""
            ubuntu_server_netboot.setup_kernel_params(
                bootloader_cfg, url, autoinstall_url, extra_args
            )
            cfg_modified = bootloader_cfg.cfg

        with open(
            grub_cfg_expected_filename, "r", encoding="utf-8"
        ) as grub_cfg_expected_f:
            bootloader_cfg_expected = ubuntu_server_netboot.GrubConfig(
                grub_cfg_expected_f.read()
            )
            cfg_expected = bootloader_cfg_expected.cfg

        assert cfg_modified == cfg_expected
