"""Employee photo handling for the website profile.

The portal validates the image, uploads it to the Sanity asset store, and points
the teamMember's `image` field at it. Postgres keeps only the asset id (photo_uri).
"""
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


def validate(upload) -> tuple[bytes, str, str]:
    """Returns (bytes, content_type, extension) or raises PhotoError."""
    if upload.size > MAX_BYTES:
        raise PhotoError("Photo must be 5 MB or smaller.")
    data = upload.read()
    try:
        Image.open(io.BytesIO(data)).verify()  # detects truncated/corrupt files
        img = Image.open(io.BytesIO(data))
    except Exception as exc:
        raise PhotoError("The file is not a valid image.") from exc
    if img.format not in FORMATS:
        raise PhotoError("Use a JPEG, PNG or WebP image.")
    if min(img.size) < MIN_SIDE:
        raise PhotoError(f"Photo must be at least {MIN_SIDE} × {MIN_SIDE} pixels.")
    content_type, ext = FORMATS[img.format]
    return data, content_type, ext


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


def set_photo(user, upload) -> str:
    """Validates, uploads and attaches the photo. Returns the new CDN URL."""
    if not sanity_sync.is_enabled():
        raise PhotoError("The company website is not connected, so photos can't be saved yet.")
    data, content_type, ext = validate(upload)
    try:
        if not user.sanity_id:
            sanity_sync.push_user(user)  # creates the teamMember first
        asset = sanity_client.upload_asset(data, content_type, f"user-{user.id}.{ext}")
        asset_id = asset["_id"]
        sanity_client.mutate([{
            "patch": {"id": user.sanity_id, "set": {"image": _image_ref(asset_id)}}
        }])
    except (SanityError, sanity_sync.PushError) as exc:
        raise PhotoError(f"Could not update the website photo: {exc}") from exc

    user.photo_uri = asset_id
    user.save(update_fields=["photo_uri"])
    return display_url(user)


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