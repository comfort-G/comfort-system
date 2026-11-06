import hashlib
import json
import logging
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from app.config import settings
from app.repositories import home_gallery_repo

logger = logging.getLogger(__name__)

MAX_GALLERY_IMAGES = 100
MAX_IMAGE_SIZE_BYTES = 5 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {
    "jpeg": ("image/jpeg", b"\xff\xd8\xff"),
    "png": ("image/png", b"\x89PNG\r\n\x1a\n"),
    "webp": ("image/webp", b"RIFF"),
}
DEFAULT_GALLERY_IMAGE = {
    "slot": 1,
    "image_url": "/static/images/cbo.jpeg",
    "cloudinary_public_id": None,
    "uploaded_by": "Default",
    "updated_at": None,
}


class CloudinaryError(RuntimeError):
    pass


def _cloudinary_credentials() -> tuple[str, str, str]:
    cloud_name = settings.CLOUDINARY_CLOUD_NAME
    api_key = settings.CLOUDINARY_API_KEY
    api_secret = settings.CLOUDINARY_API_SECRET
    if not cloud_name or not api_key or not api_secret:
        raise CloudinaryError("Cloudinary is not configured for image uploads.")
    return cloud_name, api_key, api_secret


def _image_extension(contents: bytes) -> str:
    if contents.startswith(ALLOWED_IMAGE_TYPES["jpeg"][1]):
        return "jpeg"
    if contents.startswith(ALLOWED_IMAGE_TYPES["png"][1]):
        return "png"
    if contents.startswith(ALLOWED_IMAGE_TYPES["webp"][1]) and contents[8:12] == b"WEBP":
        return "webp"
    raise ValueError("Upload a valid JPEG, PNG, or WebP image.")


def _multipart_body(
    fields: dict[str, str],
    file_contents: bytes,
    content_type: str,
) -> tuple[bytes, str]:
    boundary = f"----ComfortGallery{secrets.token_hex(16)}"
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                value.encode(),
                b"\r\n",
            ]
        )
    parts.extend(
        [
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="file"; filename="gallery-image"\r\n',
            f"Content-Type: {content_type}\r\n\r\n".encode(),
            file_contents,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    return b"".join(parts), boundary


def _cloudinary_request(
    endpoint: str,
    fields: dict[str, str],
    file_contents: bytes | None = None,
) -> dict[str, Any]:
    cloud_name, _, _ = _cloudinary_credentials()
    if file_contents is None:
        body = urllib.parse.urlencode(fields).encode()
        content_type = "application/x-www-form-urlencoded"
    else:
        body, boundary = _multipart_body(
            fields,
            file_contents,
            fields.pop("_content_type"),
        )
        content_type = f"multipart/form-data; boundary={boundary}"

    request = urllib.request.Request(
        f"https://api.cloudinary.com/v1_1/{cloud_name}/image/{endpoint}",
        data=body,
        headers={"Content-Type": content_type},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise CloudinaryError("Cloudinary could not complete the image operation.") from exc
    if not isinstance(result, dict):
        raise CloudinaryError("Cloudinary returned an invalid image response.")
    if result.get("error"):
        raise CloudinaryError("Cloudinary rejected the image operation.")
    return result


def _signature(parameters: dict[str, str], api_secret: str) -> str:
    canonical = "&".join(
        f"{key}={parameters[key]}" for key in sorted(parameters)
    )
    return hashlib.sha1(f"{canonical}{api_secret}".encode("utf-8")).hexdigest()


def _upload_to_cloudinary(
    contents: bytes,
    extension: str,
    public_id: str,
) -> dict[str, str]:
    cloud_name, api_key, api_secret = _cloudinary_credentials()
    timestamp = str(int(time.time()))
    signed_parameters = {
        "public_id": public_id,
        "timestamp": timestamp,
    }
    fields = {
        **signed_parameters,
        "api_key": api_key,
        "signature": _signature(signed_parameters, api_secret),
        "_content_type": ALLOWED_IMAGE_TYPES[extension][0],
    }
    result = _cloudinary_request("upload", fields, contents)
    secure_url = result.get("secure_url")
    uploaded_public_id = result.get("public_id")
    if not isinstance(secure_url, str) or not secure_url.startswith("https://"):
        raise CloudinaryError("Cloudinary did not return a secure image URL.")
    if not isinstance(uploaded_public_id, str) or not uploaded_public_id:
        raise CloudinaryError("Cloudinary did not return an image identifier.")
    return {"image_url": secure_url, "public_id": uploaded_public_id}


def _destroy_cloudinary_image(public_id: str) -> None:
    _, api_key, api_secret = _cloudinary_credentials()
    timestamp = str(int(time.time()))
    signed_parameters = {"public_id": public_id, "timestamp": timestamp}
    fields = {
        **signed_parameters,
        "api_key": api_key,
        "signature": _signature(signed_parameters, api_secret),
    }
    _cloudinary_request("destroy", fields)


def _upload_team_profile_image(
    contents: bytes,
    office_key: str,
    team_name: str,
) -> dict[str, str]:
    if not contents:
        raise ValueError("Select an image to upload.")
    if len(contents) > MAX_IMAGE_SIZE_BYTES:
        raise ValueError("Profile images must be 5 MB or smaller.")

    extension = _image_extension(contents)
    public_id = f"comfort_group/{team_name}/{office_key}_{secrets.token_hex(12)}"
    return _upload_to_cloudinary(contents, extension, public_id)


def upload_executive_profile_image(contents: bytes, office_key: str) -> dict[str, str]:
    return _upload_team_profile_image(contents, office_key, "executive_team")


def upload_loans_committee_profile_image(contents: bytes, office_key: str) -> dict[str, str]:
    return _upload_team_profile_image(contents, office_key, "loans_committee")


def upload_member_profile_image(contents: bytes, member_id: str) -> dict[str, str]:
    if not contents:
        raise ValueError("Select an image to upload.")
    if len(contents) > MAX_IMAGE_SIZE_BYTES:
        raise ValueError("Profile images must be 5 MB or smaller.")

    extension = _image_extension(contents)
    safe_member_id = "".join(
        character for character in member_id if character.isalnum() or character in "-_"
    )
    if not safe_member_id:
        raise ValueError("Member ID is not valid for profile image storage.")
    public_id = (
        f"comfort_group/member_profiles/{safe_member_id}_{secrets.token_hex(12)}"
    )
    return _upload_to_cloudinary(contents, extension, public_id)


def upload_subscription_payment_proof(contents: bytes) -> dict[str, str]:
    if not contents:
        raise ValueError("Select a transaction SMS screenshot to upload.")
    if len(contents) > MAX_IMAGE_SIZE_BYTES:
        raise ValueError("Payment proof images must be 5 MB or smaller.")

    extension = _image_extension(contents)
    public_id = f"comfort_group/subscription_payment_proofs/proof_{secrets.token_hex(12)}"
    return _upload_to_cloudinary(contents, extension, public_id)


def delete_cloudinary_image(public_id: str) -> None:
    _destroy_cloudinary_image(public_id)


def list_gallery_images() -> list[dict]:
    images = home_gallery_repo.list_gallery_images()
    if not any(image["slot"] == 1 for image in images):
        images.insert(0, DEFAULT_GALLERY_IMAGE.copy())
    return images


def replace_gallery_image(slot: int, contents: bytes, uploaded_by: str) -> dict:
    if not 1 <= slot <= MAX_GALLERY_IMAGES:
        raise ValueError(f"Image slot must be between 1 and {MAX_GALLERY_IMAGES}.")
    if not contents:
        raise ValueError("Select an image to upload.")
    if len(contents) > MAX_IMAGE_SIZE_BYTES:
        raise ValueError("Each image must be 5 MB or smaller.")

    extension = _image_extension(contents)
    old_image = home_gallery_repo.get_gallery_image(slot)
    public_id = f"comfort_group/home_gallery/slot_{slot}_{secrets.token_hex(12)}"
    uploaded = _upload_to_cloudinary(contents, extension, public_id)
    try:
        saved = home_gallery_repo.save_gallery_image(
            slot=slot,
            image_url=uploaded["image_url"],
            cloudinary_public_id=uploaded["public_id"],
            uploaded_by=uploaded_by,
        )
    except Exception:
        try:
            _destroy_cloudinary_image(uploaded["public_id"])
        except CloudinaryError:
            logger.exception("Could not clean up an unreferenced Cloudinary gallery image.")
        raise

    old_public_id = old_image.get("cloudinary_public_id") if old_image else None
    if old_public_id and old_public_id != uploaded["public_id"]:
        try:
            _destroy_cloudinary_image(old_public_id)
        except CloudinaryError:
            logger.exception("Could not remove the replaced Cloudinary gallery image.")
    return saved
