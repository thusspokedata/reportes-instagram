from app import create_app
from app.auth.crypto import decrypt_token, encrypt_token


def test_encrypt_decrypt_roundtrip(env):
    app = create_app()
    with app.app_context():
        token = "EAAGtest-super-secret-access-token"

        ciphertext = encrypt_token(token)
        recovered = decrypt_token(ciphertext)

        assert recovered == token


def test_ciphertext_does_not_contain_plaintext(env):
    app = create_app()
    with app.app_context():
        token = "EAAGtest-super-secret-access-token"

        ciphertext = encrypt_token(token)

        assert ciphertext != token
        assert token not in ciphertext
