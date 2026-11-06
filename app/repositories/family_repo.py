from typing import Any

from app.database import get_db


def _insert_audit(
    cursor: Any,
    member_id: str,
    relative_id: int | None,
    actor_name: str,
    actor_role: str,
    action: str,
    details: str,
    previous_value: str = "",
    new_value: str | None = None,
) -> None:
    cursor.execute(
        """
        INSERT INTO public.audit_logs (
            entity_type, entity_id, action, actor_name, actor_role,
            details, previous_value, new_value, created_at
        )
        VALUES ('family_registry', %s, %s, %s, %s, %s, %s, %s, NOW());
        """,
        (
            str(relative_id if relative_id is not None else member_id),
            action,
            actor_name,
            actor_role,
            details,
            previous_value,
            details if new_value is None else new_value,
        ),
    )


def get_registry_by_member(member_id: str) -> dict:
    with get_db() as cursor:
        cursor.execute(
            """
            SELECT submitted_at, submitted_by, reviewed_at, reviewed_by
            FROM public.family_registry_submissions
            WHERE member_id = %s;
            """,
            (member_id,),
        )
        submission = cursor.fetchone()
        cursor.execute(
            """
            SELECT id, member_id, relationship_type, full_legal_name,
                   primary_contact, vital_status, created_at
            FROM public.family_registry
            WHERE member_id = %s
            ORDER BY created_at, id;
            """,
            (member_id,),
        )
        return {
            "member_id": member_id,
            "submitted": submission is not None,
            "submission": submission,
            "relatives": cursor.fetchall(),
        }


def get_relatives_by_member(member_id: str) -> list[Any]:
    with get_db() as cursor:
        cursor.execute(
            """
            SELECT id, member_id, relationship_type, full_legal_name,
                   primary_contact, vital_status, created_at
            FROM public.family_registry
            WHERE member_id = %s
            ORDER BY created_at, id;
            """,
            (member_id,),
        )
        return cursor.fetchall()


def get_executive_registries() -> list[dict]:
    with get_db() as cursor:
        cursor.execute(
            """
            SELECT
                member.member_id,
                member.full_name AS member_name,
                submission.submitted_at,
                submission.submitted_by,
                submission.reviewed_at,
                submission.reviewed_by,
                relative.id,
                relative.relationship_type,
                relative.full_legal_name,
                relative.primary_contact,
                relative.vital_status,
                relative.created_at
            FROM public.members AS member
            LEFT JOIN public.family_registry_submissions AS submission
                ON submission.member_id = member.member_id
            LEFT JOIN public.family_registry AS relative
                ON relative.member_id = member.member_id
            ORDER BY member.full_name, member.member_id, relative.created_at, relative.id;
            """
        )
        rows = cursor.fetchall()

    registries_by_member: dict[str, dict] = {}
    for row in rows:
        member_id = row["member_id"]
        registry = registries_by_member.setdefault(
            member_id,
            {
                "member_id": member_id,
                "member_name": row["member_name"],
                "submitted": row["submitted_at"] is not None,
                "submitted_at": row["submitted_at"],
                "submitted_by": row["submitted_by"],
                "reviewed_at": row["reviewed_at"],
                "reviewed_by": row["reviewed_by"],
                "relatives": [],
            },
        )
        if row["id"] is not None:
            registry["relatives"].append(
                {
                    "id": row["id"],
                    "relationship_type": row["relationship_type"],
                    "full_legal_name": row["full_legal_name"],
                    "primary_contact": row["primary_contact"],
                    "vital_status": row["vital_status"],
                    "created_at": row["created_at"],
                }
            )
    return list(registries_by_member.values())


def _lock_member_and_submission(cursor: Any, member_id: str) -> tuple[bool, bool]:
    cursor.execute(
        "SELECT member_id FROM public.members WHERE member_id = %s FOR UPDATE;",
        (member_id,),
    )
    if cursor.fetchone() is None:
        return False, False
    cursor.execute(
        """
        SELECT member_id
        FROM public.family_registry_submissions
        WHERE member_id = %s
        FOR UPDATE;
        """,
        (member_id,),
    )
    return True, cursor.fetchone() is not None


def submit_registry(
    member_id: str,
    actor_name: str,
    actor_role: str,
) -> dict:
    with get_db() as cursor:
        exists, submitted = _lock_member_and_submission(cursor, member_id)
        if not exists:
            return {"error": "member_not_found"}
        if submitted:
            return {"error": "already_submitted"}
        cursor.execute(
            "SELECT COUNT(*) AS relative_count FROM public.family_registry WHERE member_id = %s;",
            (member_id,),
        )
        count = cursor.fetchone()
        if count is None or count["relative_count"] == 0:
            return {"error": "empty_registry"}
        cursor.execute(
            """
            INSERT INTO public.family_registry_submissions (
                member_id, submitted_by
            )
            VALUES (%s, %s)
            RETURNING submitted_at, submitted_by, reviewed_at, reviewed_by;
            """,
            (member_id, actor_name),
        )
        submission = cursor.fetchone()
        if submission is None:
            raise RuntimeError("Family registry submission returned no confirmation.")
        _insert_audit(
            cursor,
            member_id,
            None,
            actor_name,
            actor_role,
            "family_registry_submitted",
            f"Member {member_id} submitted their family registry for Chairperson review.",
        )
        return {"submission": submission}


def insert_relative(
    member_id: str,
    relationship_type: str,
    full_legal_name: str,
    primary_contact: str,
    vital_status: str,
    actor_name: str,
    actor_role: str,
    chairperson_edit: bool = False,
) -> dict:
    with get_db() as cursor:
        exists, submitted = _lock_member_and_submission(cursor, member_id)
        if not exists:
            return {"error": "member_not_found"}
        if submitted and not chairperson_edit:
            return {"error": "registry_locked"}
        cursor.execute(
            """
            INSERT INTO public.family_registry (
                member_id, relationship_type, full_legal_name,
                primary_contact, vital_status
            )
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id, member_id, relationship_type, full_legal_name,
                      primary_contact, vital_status, created_at;
            """,
            (
                member_id,
                relationship_type,
                full_legal_name,
                primary_contact,
                vital_status,
            ),
        )
        relative = cursor.fetchone()
        if relative is None:
            raise RuntimeError("Family registry insert returned no record.")
        _insert_audit(
            cursor,
            member_id,
            relative["id"],
            actor_name,
            actor_role,
            "family_relative_added",
            f"Added {relationship_type} {full_legal_name} to member {member_id}'s registry.",
        )
        return {"relative": relative}


def update_relative(
    relative_id: int,
    relationship_type: str,
    full_legal_name: str,
    primary_contact: str,
    vital_status: str,
    actor_name: str,
    actor_role: str,
    chairperson_edit: bool = False,
    expected_member_id: str | None = None,
) -> dict:
    with get_db() as cursor:
        cursor.execute(
            "SELECT member_id FROM public.family_registry WHERE id = %s;",
            (relative_id,),
        )
        target = cursor.fetchone()
        if target is None:
            return {"error": "relative_not_found"}
        member_id = target["member_id"]
        if expected_member_id is not None and member_id != expected_member_id:
            return {"error": "relative_not_found"}
        member_exists, registry_submitted = _lock_member_and_submission(
            cursor, member_id
        )
        if not member_exists:
            return {"error": "member_not_found"}
        if registry_submitted and not chairperson_edit:
            return {"error": "registry_locked"}
        cursor.execute(
            """
            SELECT id, member_id, relationship_type, full_legal_name,
                   primary_contact, vital_status
            FROM public.family_registry
            WHERE id = %s AND member_id = %s
            FOR UPDATE;
            """,
            (relative_id, member_id),
        )
        existing = cursor.fetchone()
        if existing is None:
            return {"error": "relative_not_found"}

        old_status = (existing["vital_status"] or "").strip().casefold()
        new_status = vital_status.strip().casefold()
        if old_status == "deceased" and new_status != "deceased":
            return {"error": "deceased_status_final"}
        if not chairperson_edit and new_status != old_status:
            return {"error": "status_change_requires_chairperson"}

        cursor.execute(
            """
            UPDATE public.family_registry
            SET relationship_type = %s,
                full_legal_name = %s,
                primary_contact = %s,
                vital_status = %s
            WHERE id = %s
            RETURNING id, member_id, relationship_type, full_legal_name,
                      primary_contact, vital_status, created_at;
            """,
            (
                relationship_type,
                full_legal_name,
                primary_contact,
                vital_status,
                relative_id,
            ),
        )
        relative = cursor.fetchone()
        if relative is None:
            raise RuntimeError("Family registry update returned no record.")
        _insert_audit(
            cursor,
            relative["member_id"],
            relative_id,
            actor_name,
            actor_role,
            "family_relative_updated",
            (
                f"Updated {relationship_type} {full_legal_name} in member "
                f"{relative['member_id']}'s registry; status {existing['vital_status']} "
                f"to {vital_status}."
            ),
            previous_value=(
                f"{existing['relationship_type']}: {existing['full_legal_name']}; "
                f"contact {existing['primary_contact']}; {existing['vital_status']}"
            ),
            new_value=(
                f"{relationship_type}: {full_legal_name}; contact {primary_contact}; "
                f"{vital_status}"
            ),
        )
        return {"relative": relative}


def delete_relative(
    relative_id: int,
    member_id: str,
    actor_name: str,
    actor_role: str,
) -> dict:
    with get_db() as cursor:
        exists, submitted = _lock_member_and_submission(cursor, member_id)
        if not exists:
            return {"error": "member_not_found"}
        if submitted:
            return {"error": "registry_locked"}
        cursor.execute(
            """
            DELETE FROM public.family_registry
            WHERE id = %s AND member_id = %s
            RETURNING id, relationship_type, full_legal_name;
            """,
            (relative_id, member_id),
        )
        relative = cursor.fetchone()
        if relative is None:
            return {"error": "relative_not_found"}
        _insert_audit(
            cursor,
            member_id,
            relative_id,
            actor_name,
            actor_role,
            "family_relative_deleted",
            f"Removed {relative['relationship_type']} {relative['full_legal_name']} from member {member_id}'s registry.",
        )
        return {"relative": relative}


def mark_registry_reviewed(
    member_id: str,
    actor_name: str,
    actor_role: str,
) -> dict:
    with get_db() as cursor:
        cursor.execute(
            """
            UPDATE public.family_registry_submissions
            SET reviewed_at = NOW(), reviewed_by = %s
            WHERE member_id = %s
              AND reviewed_at IS NULL
            RETURNING submitted_at, submitted_by, reviewed_at, reviewed_by;
            """,
            (actor_name, member_id),
        )
        submission = cursor.fetchone()
        if submission is None:
            cursor.execute(
                "SELECT member_id FROM public.family_registry_submissions WHERE member_id = %s;",
                (member_id,),
            )
            if cursor.fetchone() is None:
                return {"error": "registry_not_submitted"}
            return {"error": "already_reviewed"}
        _insert_audit(
            cursor,
            member_id,
            None,
            actor_name,
            actor_role,
            "family_registry_reviewed",
            f"Chairperson reviewed member {member_id}'s family registry.",
        )
        return {"submission": submission}
