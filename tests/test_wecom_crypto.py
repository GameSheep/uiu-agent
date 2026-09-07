"""WeCom official callback protocol tests — signature verification + AES decrypt.

We build a real encrypted payload with `cryptography` (the same lib used for
decryption) and assert the adapter + crypto module accept it, and reject forged
signatures / wrong receiveid / malformed bodies.
"""

import base64
import json
import os
import struct

import pytest

cryptography = pytest.importorskip("cryptography")

from uiu.channels_wecom import WeComAdapter  # noqa: E402
from uiu.config import ChannelConfig  # noqa: E402
from uiu.wecom_crypto import (  # noqa: E402
    decrypt_encrypt_msg,
    verify_signature,
)

TOKEN = "testtoken123"
AES_KEY_B64 = "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG"  # 43 chars


def _aes_key() -> bytes:
    return base64.b64decode(AES_KEY_B64 + "=")


def _encrypt_msg(msg: str, receiveid: str) -> str:
    """Encrypt a plaintext body the way WeCom does (random16 + len + msg + rid)."""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    key = _aes_key()
    iv = key[:16]
    random16 = os.urandom(16)
    payload = random16 + struct.pack(">I", len(msg.encode())) + msg.encode() + receiveid.encode()
    pad_len = 16 - (len(payload) % 16)
    payload += bytes([pad_len]) * pad_len
    enc = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    return base64.b64encode(enc.update(payload) + enc.finalize()).decode()


def _sign(timestamp: str, nonce: str, payload: str) -> str:
    raw = "".join(sorted([TOKEN, timestamp, nonce, payload]))
    import hashlib
    return hashlib.sha1(raw.encode()).hexdigest()


def _adapter(**opts):
    cfg = ChannelConfig(type="wecom", name="w", options=opts)
    return WeComAdapter(cfg, on_message=lambda c, t: None)


def test_signature_roundtrip():
    assert verify_signature(TOKEN, "1", "2", "hello", _sign("1", "2", "hello"))
    assert not verify_signature(TOKEN, "1", "2", "hello", _sign("1", "2", "tampered"))


def test_decrypt_roundtrip():
    body = json.dumps({"MsgType": "text", "FromUserName": "u1", "Content": "你好"},
                      ensure_ascii=False)
    encrypt = _encrypt_msg(body, "corp123")
    ts, nonce = "1700000000", "n1"
    plain = decrypt_encrypt_msg(
        encrypt, AES_KEY_B64, "corp123", TOKEN, ts, nonce, _sign(ts, nonce, encrypt))
    assert json.loads(plain)["Content"] == "你好"


def test_decrypt_wrong_signature_rejected():
    body = json.dumps({"MsgType": "text"})
    encrypt = _encrypt_msg(body, "corp123")
    with pytest.raises(ValueError):
        decrypt_encrypt_msg(encrypt, AES_KEY_B64, "corp123", TOKEN, "1", "2", "forged")


def test_decrypt_wrong_receiveid_rejected():
    body = json.dumps({"MsgType": "text"})
    encrypt = _encrypt_msg(body, "corp123")
    ts, nonce = "1700000000", "n1"
    with pytest.raises(ValueError):
        decrypt_encrypt_msg(encrypt, AES_KEY_B64, "OTHER", TOKEN, ts, nonce, _sign(ts, nonce, encrypt))


def test_adapter_accepts_encrypted_text_message():
    calls = []
    ad = _adapter(corpid="corp123", corpsecret="s", token=TOKEN, aes_key=AES_KEY_B64)
    ad.on_message = lambda c, t: calls.append((c, t))
    body = json.dumps({"MsgType": "text", "FromUserName": "u9", "Content": "加密消息"},
                      ensure_ascii=False)
    encrypt = _encrypt_msg(body, "corp123")
    ts, nonce = "1700000000", "n1"
    resp = ad.handle_webhook({"encrypt": encrypt}, {"timestamp": ts, "nonce": nonce,
                                                    "msg_signature": _sign(ts, nonce, encrypt)})
    assert resp["errcode"] == 0, resp
    assert calls == [("u9", "加密消息")]


def test_adapter_rejects_forged_encrypted():
    ad = _adapter(corpid="corp123", corpsecret="s", token=TOKEN, aes_key=AES_KEY_B64)
    resp = ad.handle_webhook({"encrypt": "AAAA"}, {"timestamp": "1", "nonce": "2",
                                                   "msg_signature": "deadbeef"})
    assert resp["errcode"] == 1, resp


def test_adapter_crypto_requires_signature():
    """Encrypted mode without a signature query is rejected (not silently accepted)."""
    ad = _adapter(corpid="corp123", corpsecret="s", token=TOKEN, aes_key=AES_KEY_B64)
    body = json.dumps({"MsgType": "text", "FromUserName": "u", "Content": "x"})
    encrypt = _encrypt_msg(body, "corp123")
    resp = ad.handle_webhook({"encrypt": encrypt}, {})  # no timestamp/nonce/signature
    assert resp["errcode"] == 1, resp


def test_adapter_url_verification():
    ad = _adapter(corpid="c", corpsecret="s", token=TOKEN, aes_key=AES_KEY_B64)
    echo = "random-echo"
    ts, nonce = "1", "2"
    ok = ad.verify_url({"echostr": echo, "timestamp": ts, "nonce": nonce,
                        "msg_signature": _sign(ts, nonce, echo)})
    assert ok["errcode"] == 0 and ok["echostr"] == echo, ok
    bad = ad.verify_url({"echostr": echo, "timestamp": ts, "nonce": nonce,
                         "msg_signature": "forged"})
    assert bad["errcode"] == 1, bad


def test_adapter_plaintext_legacy_still_works():
    """Without crypto config the legacy plaintext path is preserved."""
    calls = []
    ad = _adapter(corpid="c", corpsecret="s")
    ad.on_message = lambda c, t: calls.append((c, t))
    resp = ad.handle_webhook({"MsgType": "text", "FromUserName": "u1", "Content": "hi"})
    assert resp["errcode"] == 0
    assert calls == [("u1", "hi")]
