from app.database import get_db


def list_gallery_images() -> list[dict]:
    with get_db() as cursor:
        cursor.execute(
            """
            SELECT slot, image_url, cloudinary_public_id, uploaded_by, updated_at
            FROM public.home_gallery_images
            ORDER BY slot;
            """
        )
        return cursor.fetchall()


def get_gallery_image(slot: int) -> dict | None:
    with get_db() as cursor:
        cursor.execute(
            """
            SELECT slot, image_url, cloudinary_public_id, uploaded_by, updated_at
            FROM public.home_gallery_images
            WHERE slot = %s;
            """,
            (slot,),
        )
        return cursor.fetchone()


def save_gallery_image(
    slot: int,
    image_url: str,
    cloudinary_public_id: str,
    uploaded_by: str,
) -> dict:
    with get_db() as cursor:
        cursor.execute(
            """
            INSERT INTO public.home_gallery_images (
                slot, image_url, cloudinary_public_id, uploaded_by, updated_at
            )
            VALUES (%s, %s, %s, %s, NOW())
            ON CONFLICT (slot) DO UPDATE
            SET image_url = EXCLUDED.image_url,
                cloudinary_public_id = EXCLUDED.cloudinary_public_id,
                uploaded_by = EXCLUDED.uploaded_by,
                updated_at = NOW()
            RETURNING slot, image_url, cloudinary_public_id, uploaded_by, updated_at;
            """,
            (slot, image_url, cloudinary_public_id, uploaded_by),
        )
        return cursor.fetchone()
