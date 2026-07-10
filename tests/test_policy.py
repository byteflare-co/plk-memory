from plk_memory.policy import scan_text


def test_scan_text_detects_secret_without_writing_a_file():
    fake_aws_key = "AKIA" + "IOSFODNN7EXAMPLE"

    assert any("AWS" in finding for finding in scan_text(f"key={fake_aws_key}"))


def test_scan_text_accepts_normal_knowledge_content():
    assert scan_text("複数 writer の更新は transaction 内で直列化する") == []


def test_scan_text_detects_long_high_entropy_token():
    token = "a94f3c20" * 5

    assert any("entropy" in finding for finding in scan_text(token))
