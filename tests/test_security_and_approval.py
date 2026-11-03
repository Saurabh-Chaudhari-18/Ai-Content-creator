import pytest
from app.core.security import (
    hash_password, verify_password,
    create_access_token, decode_token,
    compute_content_hash,
    encrypt_token, decrypt_token,
)


def test_password_hashing():
    raw_password = "SecretPassword123!"
    hashed = hash_password(raw_password)

    assert hashed != raw_password
    assert verify_password(raw_password, hashed) is True
    assert verify_password("WrongPassword!", hashed) is False


def test_jwt_generation_and_decode():
    subject = "user-12345-uuid"
    token = create_access_token(subject)

    payload = decode_token(token)
    assert payload["sub"] == subject
    assert payload["type"] == "access"
    assert "exp" in payload


def test_content_hashing_tamper_detection():
    caption_orig = "Enjoy our new seasonal menu!"
    media_orig = ["https://s3.aws.com/media/photo1.jpg", "https://s3.aws.com/media/photo2.jpg"]

    # Original hash
    hash_orig = compute_content_hash(caption_orig, media_orig)
    assert len(hash_orig) == 64  # SHA-256 hex digest

    # Order of media should not alter hash because of sorting
    media_reversed = ["https://s3.aws.com/media/photo2.jpg", "https://s3.aws.com/media/photo1.jpg"]
    hash_reversed = compute_content_hash(caption_orig, media_reversed)
    assert hash_orig == hash_reversed

    # ANY edit to caption must change the hash (Invalidates approval)
    caption_modified = "Enjoy our new seasonal menu! Use code 50OFF"
    hash_modified = compute_content_hash(caption_modified, media_orig)
    assert hash_orig != hash_modified

    # Adding or removing media must change the hash
    hash_media_added = compute_content_hash(caption_orig, media_orig + ["https://s3.aws.com/media/photo3.jpg"])
    assert hash_orig != hash_media_added


def test_oauth_token_encryption():
    raw_oauth_token = "EAABwzLIXf...long_meta_access_token_xyz123"
    encrypted = encrypt_token(raw_oauth_token)

    assert encrypted != raw_oauth_token
    decrypted = decrypt_token(encrypted)
    assert decrypted == raw_oauth_token
