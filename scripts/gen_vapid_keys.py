"""Generate a VAPID keypair for Web Push.

One-time setup. Run this locally with the project venv active::

    .venv\\Scripts\\python.exe scripts\\gen_vapid_keys.py

Output:

    VAPID_PUBLIC_KEY=<urlsafe-base64 NO padding>
    VAPID_PRIVATE_KEY=<urlsafe-base64 NO padding>

Append both lines to ``.env`` locally, AND seed them into SSM Parameter
Store at::

    /pa-agent/prod/VAPID_PUBLIC_KEY
    /pa-agent/prod/VAPID_PRIVATE_KEY (SecureString)

Do NOT commit the values to git. Public key can be exposed to the PWA;
private key MUST stay server-side and rotation is not implemented yet, so
treat the file output like any other secret until then.
"""

from __future__ import annotations

import base64

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization


def _b64url(data: bytes) -> str:
    """URL-safe base64 without padding — the Web Push wire format."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def main() -> None:
    # The Web Push spec mandates P-256 ECDSA keys.
    private = ec.generate_private_key(ec.SECP256R1())
    private_bytes = private.private_numbers().private_value.to_bytes(32, "big")
    public_bytes = private.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    print(f"VAPID_PUBLIC_KEY={_b64url(public_bytes)}")
    print(f"VAPID_PRIVATE_KEY={_b64url(private_bytes)}")
    print()
    print("# Add both to .env (local) and to SSM Parameter Store:")
    print("#   /pa-agent/prod/VAPID_PUBLIC_KEY  (String)")
    print("#   /pa-agent/prod/VAPID_PRIVATE_KEY (SecureString)")


if __name__ == "__main__":
    main()
