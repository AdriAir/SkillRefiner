import pytest
from refinerlib.common import RefinerError, ensure_outside, redact, relative_path, secret_values


_DSA_BODY = "synthetic-dsa-body-marker-0123456789"


@pytest.mark.parametrize("text", ['{"token": "jsonsecretvalue123"}', 'Authorization: Bearer bearercredential123', "password = 'quotedcredential123'"])
def test_secrets_redacted_in_common_encodings(text):
    values = secret_values(text)
    assert values
    safe = redact(text)
    assert "credential123" not in safe
    assert "jsonsecretvalue123" not in safe


def test_output_cannot_be_input_ancestor(tmp_path):
    with pytest.raises(RefinerError):
        ensure_outside(tmp_path, tmp_path / "skill")


@pytest.mark.parametrize("value", ['x\n.py', 'a"b.py', 'file?.py', 'x|y'])
def test_nonportable_path_rejected(value):
    with pytest.raises(RefinerError):
        relative_path(value)


@pytest.mark.parametrize("text,secret", [
    ('client_secret=dummysecretvalue123', 'dummysecretvalue123'),
    ('refresh_token=dummyrefreshtoken123', 'dummyrefreshtoken123'),
    ('Authorization: Basic ZHVtbXk6cGFzc3dvcmQ=', 'ZHVtbXk6cGFzc3dvcmQ='),
    ('aws_secret_access_key=syntheticawsvalue123', 'syntheticawsvalue123'),
    ('postgresql://user:syntheticpassword@localhost/db', 'syntheticpassword'),
    ('eyJhbGciOiJub25lIn0.eyJzdWIiOiJzeW50aGV0aWMifQ.signaturevalue', 'eyJhbGciOiJub25lIn0.eyJzdWIiOiJzeW50aGV0aWMifQ.signaturevalue'),
])
def test_compound_credentials_are_detected_before_any_payload(text, secret):
    assert secret in secret_values(text)
    assert secret not in redact(text)


def test_labelled_multiline_pem_does_not_hide_body_from_detector():
    block = "-----BEGIN PRIVATE KEY-----\nsyntheticPrivateBodyValue123\n-----END PRIVATE KEY-----"
    text = 'private_key="' + block + '"'
    assert block in secret_values(text)
    assert "syntheticPrivateBodyValue123" not in redact(text)


@pytest.mark.parametrize("secret", [
    "github_pat_" + "A" * 82,
    "glpat-" + "A" * 24,
    "xoxb-" + "1" * 12 + "-" + "A" * 24,
    "sk_live_" + "A" * 24,
    "ASIA" + "A" * 16,
    "-----BEGIN DSA PRIVATE KEY-----\n" + _DSA_BODY + "\n-----END DSA PRIVATE KEY-----",
])
def test_recognizable_secret_prefixes_are_detected_and_redacted(secret):
    assert secret in secret_values(secret)
    rendered = redact(secret)
    assert secret not in rendered
    if secret.startswith("-----BEGIN DSA"):
        assert _DSA_BODY not in rendered
