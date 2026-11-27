#!/usr/bin/env python3
"""GabGo Pro license generator (Ed25519, offline).

Key format:  GABGO1-<base64url(payload-json)>.<base64url(signature)>
The signature covers the raw UTF-8 bytes of the payload JSON.

Examples:
  python generate_gabgo_license.py --name "Max Mustermann"
  python generate_gabgo_license.py --name "Familie Gabbas" --email max@example.com --count 3
  python generate_gabgo_license.py --new-keypair            # creates gabgo_private.pem / gabgo_public.pem
  python generate_gabgo_license.py --verify GABGO1-...
  python generate_gabgo_license.py --print-public-key       # base64 raw key for LicensePublicKey.kt

Requires: pip install cryptography
"""
import argparse
import base64
import datetime as dt
import json
import pathlib
import sys
import uuid

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

PREFIX = "GABGO1-"
HERE = pathlib.Path(__file__).resolve().parent
DEFAULT_PRIVATE = HERE / "gabgo_private.pem"
DEFAULT_PUBLIC = HERE / "gabgo_public.pem"


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def new_keypair(private_path: pathlib.Path, public_path: pathlib.Path, force: bool) -> None:
    if private_path.exists() and not force:
        sys.exit(f"{private_path} existiert bereits (mit --force überschreiben).")
    key = Ed25519PrivateKey.generate()
    private_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    public_path.write_bytes(key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
    print(f"Neues Schlüsselpaar: {private_path.name} / {public_path.name}")
    print("Public Key (für LicensePublicKey.kt):", raw_public_b64(key.public_key()))


def load_private(path: pathlib.Path) -> Ed25519PrivateKey:
    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        sys.exit("Kein Ed25519-Private-Key.")
    return key


def load_public(path: pathlib.Path) -> Ed25519PublicKey:
    key = serialization.load_pem_public_key(path.read_bytes())
    if not isinstance(key, Ed25519PublicKey):
        sys.exit("Kein Ed25519-Public-Key.")
    return key


def raw_public_b64(key: Ed25519PublicKey) -> str:
    raw = key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode("ascii")


def make_license(key: Ed25519PrivateKey, name: str, email: str | None, expires: str | None) -> str:
    payload = {
        "v": 1,
        "lid": uuid.uuid4().hex[:12].upper(),
        "plan": "pro",
        "name": name,
        "iat": dt.date.today().isoformat(),
    }
    if email:
        payload["email"] = email
    if expires:
        dt.date.fromisoformat(expires)
        payload["exp"] = expires
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return PREFIX + b64url(body) + "." + b64url(key.sign(body))


def verify_license(key: Ed25519PublicKey, license_key: str) -> dict:
    license_key = "".join(license_key.split())
    if not license_key.startswith(PREFIX):
        raise ValueError("Präfix GABGO1- fehlt")
    body_b64, sig_b64 = license_key[len(PREFIX):].split(".", 1)
    body = b64url_decode(body_b64)
    key.verify(b64url_decode(sig_b64), body)
    return json.loads(body)


def main() -> None:
    ap = argparse.ArgumentParser(description="GabGo-Pro-Lizenzschlüssel erzeugen/prüfen")
    ap.add_argument("--name", default="GabGo Pro")
    ap.add_argument("--email")
    ap.add_argument("--expires", help="optionales Ablaufdatum YYYY-MM-DD")
    ap.add_argument("--count", type=int, default=1)
    ap.add_argument("--private-key", type=pathlib.Path, default=DEFAULT_PRIVATE)
    ap.add_argument("--public-key", type=pathlib.Path, default=DEFAULT_PUBLIC)
    ap.add_argument("--new-keypair", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--verify", metavar="KEY")
    ap.add_argument("--print-public-key", action="store_true")
    args = ap.parse_args()

    if args.new_keypair:
        new_keypair(args.private_key, args.public_key, args.force)
        return
    if args.print_public_key:
        print(raw_public_b64(load_public(args.public_key)))
        return
    if args.verify:
        try:
            print("GÜLTIG:", json.dumps(verify_license(load_public(args.public_key), args.verify), ensure_ascii=False))
        except Exception as exc:  # noqa: BLE001
            sys.exit(f"UNGÜLTIG: {exc}")
        return

    key = load_private(args.private_key)
    for _ in range(max(1, args.count)):
        print(make_license(key, args.name, args.email, args.expires))


if __name__ == "__main__":
    main()
