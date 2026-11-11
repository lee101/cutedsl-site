from validate_host_network_config import validate


def test_rejects_duplicate_ifupdown_dhcp_stanzas():
    interfaces = """\
auto lo
iface lo inet loopback

auto eth0
iface eth0 inet dhcp

auto eth0
iface eth0 inet dhcp
"""

    errors = validate(interfaces, "eth0", networkd_managed=False)

    assert errors == ["eth0 has 2 duplicate ifupdown DHCP stanzas"]


def test_rejects_competing_networkd_and_ifupdown_ownership():
    interfaces = "auto eth0\niface eth0 inet dhcp\n"

    errors = validate(interfaces, "eth0", networkd_managed=True)

    assert errors == [
        "eth0 is managed by systemd-networkd but also has an ifupdown DHCP stanza"
    ]


def test_accepts_networkd_as_the_only_dhcp_owner():
    interfaces = "auto lo\niface lo inet loopback\n"

    assert validate(interfaces, "eth0", networkd_managed=True) == []
