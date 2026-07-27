import hashlib
import hmac

from ph_repo_auditor.webhook import verify_signature


def test_signature_verification():
    body = b'{"zen":"Public health"}'
    signature = "sha256=" + hmac.new(
        b"secret", body, hashlib.sha256
    ).hexdigest()

    assert verify_signature("secret", body, signature)
    assert not verify_signature("wrong", body, signature)
    assert not verify_signature("secret", body, None)
