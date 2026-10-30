from warehouse_optimizer.hosting import HOSTED_SHORT, LOCAL_SHORT, is_hosted, privacy_notice


def test_detects_streamlit_cloud():
    assert is_hosted({"HOSTNAME": "streamlit"}, "/home/x/app")
    assert is_hosted({}, "/mount/src/depo-yonetimi/src/warehouse_optimizer/hosting.py")
    assert not is_hosted({}, "/home/user/depo-yonetimi/src/warehouse_optimizer/hosting.py")


def test_env_override_wins():
    assert not is_hosted({"WAREHOUSE_HOSTING": "local", "HOSTNAME": "streamlit"}, "/mount/src/x")
    assert is_hosted({"WAREHOUSE_HOSTING": "cloud"}, "/home/x")


def test_notice_never_claims_local_privacy_when_hosted():
    assert privacy_notice(short=True, hosted=True) == HOSTED_SHORT
    assert "dışarı gönderilmez" not in privacy_notice(hosted=True)
    assert privacy_notice(short=True, hosted=False) == LOCAL_SHORT
