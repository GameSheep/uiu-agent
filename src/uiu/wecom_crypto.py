"""WeCom callback cryptography — official AES-CBC decryption + signature.

Protocol (企业微信自建应用回调):
  - Every callback carries query params: msg_signature, timestamp, nonce,
    and (for GET verification) echostr.
  - Signature = sha1(sorted([token, timestamp, nonce, payload])) where payload is
    echostr (GET) or the `encrypt` value (POST).
  - POST body: {"encrypt": "<base64>"}; decrypting yields:
        random(16) + msg_len(4, big-endian) + msg + receiveid
  - AESKey = base64.b64decode(EncodingAESKey + "=") → 32 bytes; AES-256-CBC with
    IV = AESKey[:16]; PKCS#7 padding.

Uses the `cryptography` package for AES (universally present when a real WeCom
callback is configured). Decryption raises ValueError on any integrity failure.
"""

from __future__ import annotations

import base64
import hashlib
import struct


def _aes_cbc_decrypt(key: bytes, iv: bytes, ciphertext: bytes) -> bytes:
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    except ImportError as e:  # pragma: no cover - env-specific
        raise ValueError(
            "企业微信回调解密需要 cryptography：pip install cryptography"
        ) from e
    decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()
    if not padded:
        raise ValueError("empty plaintext")
    pad_len = padded[-1]
    if pad_len < 1 or pad_len > 32 or padded[-pad_len:] != bytes([pad_len]) * pad_len:
        raise ValueError("bad PKCS#7 padding")
    return padded[:-pad_len]


def verify_signature(token: str, timestamp: str, nonce: str, payload: str, signature: str) -> bool:
    """WeCom signature check: sha1 of sorted([token, timestamp, nonce, payload])."""
    if not signature:
        return False
    raw = "".join(sorted([token, timestamp, nonce, payload]))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest() == signature.lower()


def decrypt_encrypt_msg(
    encrypt: str,
    encoding_aes_key: str,
    receiveid: str,
    token: str,
    timestamp: str,
    nonce: str,
    msg_signature: str,
) -> str:
    """Verify signature then AES-decrypt a WeCom callback's `encrypt` field.

    Returns the plaintext JSON message body. Raises ValueError on any mismatch
    (signature / key / length / receiveid / padding).
    """
    if not verify_signature(token, timestamp, nonce, encrypt, msg_signature):
        raise ValueError("msg_signature mismatch")
    try:
        aes_key = base64.b64decode(encoding_aes_key + "=")
    except Exception as e:
        raise ValueError(f"bad EncodingAESKey: {e}") from e
    if len(aes_key) != 32:
        raise ValueError("EncodingAESKey must decode to 32 bytes")
    try:
        ciphertext = base64.b64decode(encrypt)
    except Exception as e:
        raise ValueError(f"bad base64 encrypt: {e}") from e
    plain = _aes_cbc_decrypt(aes_key, aes_key[:16], ciphertext)
    if len(plain) < 20:
        raise ValueError("plaintext too short")
    msg_len = struct.unpack(">I", plain[16:20])[0]
    if 20 + msg_len > len(plain):
        raise ValueError("message length exceeds plaintext")
    msg = plain[20:20 + msg_len].decode("utf-8")
    receiveid_check = plain[20 + msg_len:].decode("utf-8")
    if receiveid and receiveid_check and receiveid_check != receiveid:
        raise ValueError(f"receiveid mismatch: got {receiveid_check!r}, want {receiveid!r}")
    return msg
