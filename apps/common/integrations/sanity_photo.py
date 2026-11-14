"""Employee photo handling for the website profile.

Two entry points:
  - set_photo(): the employee uploads from their profile page.
  - sync_profile_photo(): a photo held in the profile as a data URL (saved from the admin
    or employee form) is uploaded during push_user, then cleared from Postgres.

Postgres keeps only the Sanity asset id (photo_uri). The binary is never stored in the database.
"""
import base64
import binascii
import io
import re

from PIL import Image

from apps.common.integrations import sanity_client, sanity_sync
from apps.common.integrations.sanity_client import SanityError

MAX_BYTES = 5 * 1024 * 1024
MIN_SIDE = 200
FORMATS = {
    "JPEG": ("image/jpeg", "jpg"),
    "PNG": ("image/png", "png"),
    "WEBP": ("image/webp", "webp"),
}
ASSET_RE = re.compile(r"image-([a-f0-9]+)-(\d+x\d+)-([a-z]+)")


class PhotoError(Exception):
    pass


def validate_bytes(data: bytes) -> tuple[bytes, str, str]:
    """Returns (bytes, content_type, extension) or raises PhotoError."""
    if len(data) > MAX_BYTES:
        raise PhotoError("Photo must be 5 MB or smaller.")
    try:
        Image.open(io.BytesIO(data)).verify()  # detects truncated or corrupt files
        img = Image.open(io.BytesIO(data))
    except Exception as exc:
        raise PhotoError("The file is not a valid image.") from exc
    if img.format not in FORMATS:
        raise PhotoError("Use a JPEG, PNG or WebP image.")
    if min(img.size) < MIN_SIDE:
        raise PhotoError(f"Photo must be at least {MIN_SIDE} × {MIN_SIDE} pixels.")
    content_type, ext = FORMATS[img.format]
    return data, content_type, ext


def decode_data_url(value: str) -> bytes:
    header, _, payload = value.partition(",")
    if not header.startswith("data:image/") or ";base64" not in header:
        raise PhotoError("Photo must be an image file.")
    try:
        return base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise PhotoError("Photo data is corrupt.") from exc


def cdn_url(asset_id: str | None) -> str | None:
    """Public CDN URL for a Sanity image asset id like image-<hash>-<w>x<h>-<fmt>."""
    if not asset_id:
        return None
    m = ASSET_RE.fullmatch(asset_id)
    if not m:
        return None
    hash_, dims, fmt = m.groups()
    return (f"https://cdn.sanity.io/images/{sanity_client.PROJECT_ID}"
            f"/{sanity_client.DATASET}/{hash_}-{dims}.{fmt}")


def display_url(user) -> str | None:
    return cdn_url(user.photo_uri)


def _image_ref(asset_id: str) -> dict:
    return {"_type": "image", "asset": {"_type": "reference", "_ref": asset_id}}


def attach_bytes(user, data: bytes) -> str:
    """Validates, uploads and points the teamMember's image at the new asset. Returns the asset id.

    Raises PhotoError for an invalid image and SanityError when Sanity is unreachable.
    """
    data, content_type, ext = validate_bytes(data)
    if not user.sanity_id:
        raise PhotoError("The website profile has not been created yet.")
    asset = sanity_client.upload_asset(data, content_type, f"{user.identity_id or user.id}.{ext}")
    asset_id = asset["_id"]
    sanity_client.mutate([{
        "patch": {"id": user.sanity_id, "set": {"image": _image_ref(asset_id)}}
    }])
    user.photo_uri = asset_id
    user.save(update_fields=["photo_uri"])
    return asset_id


def set_photo(user, upload) -> str | None:
    """Employee upload from the profile page. Returns the new CDN URL."""
    if not sanity_sync.is_enabled():
        raise PhotoError("The company website is not connected, so photos can't be saved yet.")
    data = upload.read()
    try:
        if not user.sanity_id:
            sanity_sync.push_user(user)  # creates the teamMember first
        attach_bytes(user, data)
    except (SanityError, sanity_sync.PushError) as exc:
        raise PhotoError(f"Could not update the website photo: {exc}") from exc
    return display_url(user)


def sync_profile_photo(user) -> None:
    """Uploads a photo held in the profile as a data URL, then clears it from Postgres.

    Called from push_user. If the upload fails, the data URL stays in place and the push is retried.
    """
    profile = getattr(user, "profile", None)
    if not profile or not (profile.photo_url or "").startswith("data:"):
        return
    attach_bytes(user, decode_data_url(profile.photo_url))
    profile.photo_url = None
    profile.save(update_fields=["photo_url"])


def remove_photo(user) -> None:
    if not sanity_sync.is_enabled():
        raise PhotoError("The company website is not connected.")
    try:
        if user.sanity_id:
            sanity_client.mutate([{"patch": {"id": user.sanity_id, "unset": ["image"]}}])
    except SanityError as exc:
        raise PhotoError(f"Could not remove the website photo: {exc}") from exc
    user.photo_uri = None
    user.save(update_fields=["photo_uri"])