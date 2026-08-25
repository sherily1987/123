import launch


def test_launch_uses_formal_b3_port():
    assert launch.PORT == 8766
