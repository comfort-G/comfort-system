# app/database.py
import logging
import time
from contextlib import contextmanager
from typing import Generator, Optional
from psycopg2 import InterfaceError, OperationalError
from psycopg2.pool import ThreadedConnectionPool
from psycopg2.extras import RealDictCursor
from app.config import settings

logger = logging.getLogger("uvicorn")

db_pool: Optional[ThreadedConnectionPool] = None


def _connection_is_healthy(conn) -> bool:
    try:
        if conn is None:
            return False
        closed = getattr(conn, "closed", None)
        if closed is None:
            return True
        return closed == 0
    except Exception:
        return False


def _cursor_is_healthy(cursor) -> bool:
    try:
        if cursor is None:
            return False
        closed = getattr(cursor, "closed", None)
        if closed is None:
            return True
        return closed == 0
    except Exception:
        return False


def _discard_connection(pool: ThreadedConnectionPool, conn) -> None:
    if conn is None:
        return

    try:
        if _connection_is_healthy(conn):
            try:
                conn.rollback()
            except (OperationalError, InterfaceError):
                logger.warning("Discarding a stale database connection after rollback failure.", exc_info=True)
            except Exception:
                logger.exception("Failed to roll back a connection before discarding it.")

        pool.putconn(conn, close=True)
    except (OperationalError, InterfaceError):
        logger.warning("Connection pool rejected a dead connection during discard.", exc_info=True)
    except Exception:
        logger.exception("Failed to discard a database connection from the pool.")
    finally:
        try:
            if conn is not None and getattr(conn, "closed", 1) != 0:
                conn.close()
        except Exception:
            logger.exception("Failed to close a discarded database connection.")


def _rollback_connection(conn) -> bool:
    if not _connection_is_healthy(conn):
        return False

    try:
        conn.rollback()
    except (OperationalError, InterfaceError):
        logger.warning("Could not roll back a disconnected database connection.", exc_info=True)
        return False
    except Exception:
        logger.exception("Database transaction rollback failed.")
        return False

    return _connection_is_healthy(conn)

def _get_healthy_connection(pool: ThreadedConnectionPool):
    max_retries = 3
    retry_delay = 1.0

    for attempt in range(max_retries):
        conn = None
        try:
            conn = pool.getconn()
            if not _connection_is_healthy(conn):
                _discard_connection(pool, conn)
                raise OperationalError("Database pool returned a closed connection.")

            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("SELECT 1")
                if not _cursor_is_healthy(cursor):
                    raise OperationalError("Database cursor failed its health check.")

            if not _connection_is_healthy(conn):
                raise OperationalError("Database connection failed its health check.")

            return conn

        except (OperationalError, InterfaceError):
            logger.warning(
                "Connection attempt %s of %s failed. Retrying in %.1f seconds.",
                attempt + 1,
                max_retries,
                retry_delay,
                exc_info=True,
            )
            if conn is not None:
                _discard_connection(pool, conn)

            if attempt == max_retries - 1:
                raise
            time.sleep(retry_delay)
            retry_delay *= 2

        except Exception:
            if conn is not None:
                _discard_connection(pool, conn)
            raise

    raise OperationalError("Unable to obtain a healthy database connection after multiple retries.")


def init_db_pool():
    global db_pool
    db_pool = None
    max_retries = 5
    retry_delay = 2.0

    for attempt in range(max_retries):
        pool = None
        conn = None
        try:
            pool = ThreadedConnectionPool(
                minconn=1,
                maxconn=10,
                dsn=settings.DATABASE_URL,
                connect_timeout=10,
            )
            conn = pool.getconn()
            if not _connection_is_healthy(conn):
                raise OperationalError("Database pool returned a closed connection.")

            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT
                        current_database() AS database_name,
                        current_schema() AS schema_name,
                        EXISTS (
                            SELECT 1
                            FROM information_schema.columns
                            WHERE table_schema = 'public'
                              AND table_name = 'members'
                              AND column_name = 'override_status'
                        ) AS has_override_status,
                        EXISTS (
                            SELECT 1
                            FROM information_schema.columns
                            WHERE table_schema = 'public'
                              AND table_name = 'members'
                              AND column_name = 'member_id'
                        ) AS has_member_id,
                        EXISTS (
                            SELECT 1
                            FROM information_schema.columns
                            WHERE table_schema = 'public'
                              AND table_name = 'loans'
                              AND column_name = 'loan_id'
                        ) AS has_loan_id,
                        EXISTS (
                            SELECT 1
                            FROM information_schema.columns
                            WHERE table_schema = 'public'
                              AND table_name = 'loans'
                              AND column_name = 'member_id'
                        ) AS has_loan_member_id,
                        to_regclass('public.welfare_requests') IS NOT NULL
                            AS has_welfare_requests,
                        to_regclass('public.family_registry') IS NOT NULL
                            AS has_family_registry,
                        EXISTS (
                            SELECT 1
                            FROM information_schema.columns
                            WHERE table_schema = 'public'
                              AND table_name = 'family_registry'
                              AND column_name = 'id'
                        ) AS has_family_id,
                        EXISTS (
                            SELECT 1
                            FROM information_schema.columns
                            WHERE table_schema = 'public'
                              AND table_name = 'family_registry'
                              AND column_name = 'member_id'
                        ) AS has_family_member_id,
                        EXISTS (
                            SELECT 1
                            FROM information_schema.columns
                            WHERE table_schema = 'public'
                              AND table_name = 'family_registry'
                              AND column_name = 'relationship_type'
                        ) AS has_family_relationship,
                        EXISTS (
                            SELECT 1
                            FROM information_schema.columns
                            WHERE table_schema = 'public'
                              AND table_name = 'family_registry'
                              AND column_name = 'full_legal_name'
                        ) AS has_family_name,
                        EXISTS (
                            SELECT 1
                            FROM information_schema.columns
                            WHERE table_schema = 'public'
                              AND table_name = 'family_registry'
                              AND column_name = 'primary_contact'
                        ) AS has_family_contact,
                        EXISTS (
                            SELECT 1
                            FROM information_schema.columns
                            WHERE table_schema = 'public'
                              AND table_name = 'family_registry'
                              AND column_name = 'vital_status'
                        ) AS has_family_vital_status,
                        EXISTS (
                            SELECT 1
                            FROM information_schema.columns
                            WHERE table_schema = 'public'
                              AND table_name = 'family_registry'
                              AND column_name = 'created_at'
                        ) AS has_family_created_at;
                    """
                )
                database_info = cursor.fetchone()

            if not _connection_is_healthy(conn):
                raise OperationalError("Database connection failed its startup check.")

            if database_info is None:
                raise RuntimeError("Database health check returned no database information.")

            if not database_info.get("has_override_status"):
                raise RuntimeError(
                    "Database schema mismatch: public.members.override_status is "
                    f"missing in database '{database_info['database_name']}'. "
                    "Verify DATABASE_URL points to the intended Neon branch or "
                    "apply the members.override_status migration to that branch."
                )
            missing_loan_schema = [
                column_name
                for column_name, is_present in (
                    ("public.members.member_id", database_info.get("has_member_id")),
                    ("public.loans.loan_id", database_info.get("has_loan_id")),
                    ("public.loans.member_id", database_info.get("has_loan_member_id")),
                )
                if not is_present
            ]
            if missing_loan_schema:
                raise RuntimeError(
                    "Database schema mismatch: required loan/member columns are "
                    f"missing ({', '.join(missing_loan_schema)}) in database "
                    f"'{database_info['database_name']}'. Verify DATABASE_URL "
                    "points to the intended Neon branch and apply the core "
                    "members/loans schema before starting the application."
                )
            if not database_info.get("has_welfare_requests"):
                raise RuntimeError(
                    "Database schema mismatch: public.welfare_requests is missing "
                    f"in database '{database_info['database_name']}'. Apply the "
                    "base welfare schema before starting the application."
                )
            if database_info.get("has_family_registry"):
                missing_family_columns = [
                    column_name
                    for column_name, is_present in (
                        ("id", database_info.get("has_family_id")),
                        ("member_id", database_info.get("has_family_member_id")),
                        (
                            "relationship_type",
                            database_info.get("has_family_relationship"),
                        ),
                        ("full_legal_name", database_info.get("has_family_name")),
                        ("primary_contact", database_info.get("has_family_contact")),
                        (
                            "vital_status",
                            database_info.get("has_family_vital_status"),
                        ),
                        ("created_at", database_info.get("has_family_created_at")),
                    )
                    if not is_present
                ]
                if missing_family_columns:
                    raise RuntimeError(
                        "Database schema mismatch: public.family_registry is "
                        "missing required column(s) "
                        f"{', '.join(missing_family_columns)} in database "
                        f"'{database_info['database_name']}'. Migrate the family "
                        "registry schema before starting the application."
                    )

            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS public.family_registry (
                        id BIGSERIAL PRIMARY KEY,
                        member_id TEXT NOT NULL
                            REFERENCES public.members(member_id),
                        relationship_type TEXT NOT NULL,
                        full_legal_name TEXT NOT NULL,
                        primary_contact TEXT NOT NULL,
                        vital_status TEXT NOT NULL DEFAULT 'Alive',
                        created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
                    );
                    CREATE TABLE IF NOT EXISTS public.family_registry_submissions (
                        member_id TEXT PRIMARY KEY
                            REFERENCES public.members(member_id),
                        submitted_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
                        submitted_by TEXT NOT NULL,
                        reviewed_at TIMESTAMP WITHOUT TIME ZONE,
                        reviewed_by TEXT
                    );
                    ALTER TABLE public.members
                        ADD COLUMN IF NOT EXISTS address TEXT,
                        ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN NOT NULL DEFAULT FALSE,
                        ADD COLUMN IF NOT EXISTS token_version INTEGER NOT NULL DEFAULT 0,
                        ADD COLUMN IF NOT EXISTS reset_token VARCHAR(255),
                        ADD COLUMN IF NOT EXISTS reset_expires_at TIMESTAMP WITHOUT TIME ZONE,
                        ADD COLUMN IF NOT EXISTS occupation TEXT,
                        ADD COLUMN IF NOT EXISTS date_of_birth DATE,
                        ADD COLUMN IF NOT EXISTS next_of_kin_name TEXT,
                        ADD COLUMN IF NOT EXISTS next_of_kin_relationship TEXT,
                        ADD COLUMN IF NOT EXISTS next_of_kin_phone VARCHAR(20),
                        ADD COLUMN IF NOT EXISTS avatar_url TEXT,
                        ADD COLUMN IF NOT EXISTS avatar_public_id TEXT;
                    ALTER TABLE public.welfare_requests
                        ADD COLUMN IF NOT EXISTS relative_id BIGINT
                            REFERENCES public.family_registry(id) ON DELETE SET NULL,
                        ADD COLUMN IF NOT EXISTS beneficiary_name TEXT,
                        ADD COLUMN IF NOT EXISTS beneficiary_relationship TEXT;
                    CREATE INDEX IF NOT EXISTS welfare_requests_relative_id_idx
                        ON public.welfare_requests (relative_id)
                        WHERE relative_id IS NOT NULL;

                    CREATE TABLE IF NOT EXISTS public.member_welfare_contributions (
                        id BIGSERIAL PRIMARY KEY,
                        member_id TEXT NOT NULL REFERENCES public.members(member_id),
                        amount NUMERIC(12, 2) NOT NULL CHECK (amount > 0 AND amount <= 100000),
                        transfer_reference TEXT NOT NULL UNIQUE,
                        created_by TEXT NOT NULL,
                        created_by_role TEXT NOT NULL,
                        created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
                    );
                    CREATE INDEX IF NOT EXISTS member_welfare_contributions_member_idx
                        ON public.member_welfare_contributions (member_id, created_at);
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS public.welfare_request_member_contributions (
                        id BIGSERIAL PRIMARY KEY,
                        request_id BIGINT NOT NULL
                            REFERENCES public.welfare_requests(id),
                        member_id TEXT NOT NULL
                            REFERENCES public.members(member_id),
                        target_amount NUMERIC(12, 2) NOT NULL
                            CHECK (target_amount IN (0, 20000)),
                        welfare_amount NUMERIC(12, 2) NOT NULL DEFAULT 0
                            CHECK (welfare_amount >= 0),
                        savings_amount NUMERIC(12, 2) NOT NULL DEFAULT 0
                            CHECK (savings_amount >= 0),
                        outstanding_amount NUMERIC(12, 2) NOT NULL DEFAULT 0
                            CHECK (outstanding_amount >= 0),
                        is_exempt BOOLEAN NOT NULL DEFAULT FALSE,
                        created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
                        UNIQUE (request_id, member_id),
                        CONSTRAINT welfare_member_contribution_amounts_check CHECK (
                            (is_exempt AND target_amount = 0 AND welfare_amount = 0
                                AND savings_amount = 0 AND outstanding_amount = 0)
                            OR
                            (NOT is_exempt AND target_amount = 20000
                                AND welfare_amount + savings_amount + outstanding_amount
                                    = target_amount)
                        )
                    );
                    ALTER TABLE public.welfare_request_member_contributions
                        ADD COLUMN IF NOT EXISTS is_exempt BOOLEAN NOT NULL DEFAULT FALSE;
                    ALTER TABLE public.welfare_request_member_contributions
                        DROP CONSTRAINT IF EXISTS welfare_request_member_contributions_target_amount_check;
                    ALTER TABLE public.welfare_request_member_contributions
                        DROP CONSTRAINT IF EXISTS welfare_request_member_contributions_check;
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM pg_constraint
                            WHERE conname = 'welfare_member_contribution_amounts_check'
                              AND conrelid =
                                'public.welfare_request_member_contributions'::regclass
                        ) THEN
                            ALTER TABLE public.welfare_request_member_contributions
                                ADD CONSTRAINT welfare_member_contribution_amounts_check
                                CHECK (
                                    (is_exempt AND target_amount = 0
                                        AND welfare_amount = 0 AND savings_amount = 0
                                        AND outstanding_amount = 0)
                                    OR
                                    (NOT is_exempt AND target_amount = 20000
                                        AND welfare_amount + savings_amount
                                            + outstanding_amount = target_amount)
                                );
                        END IF;
                    END $$;
                    CREATE INDEX IF NOT EXISTS welfare_request_member_contrib_member_idx
                        ON public.welfare_request_member_contributions (member_id, created_at);

                    CREATE TABLE IF NOT EXISTS public.welfare_request_member_arrears_payments (
                        id BIGSERIAL PRIMARY KEY,
                        request_id BIGINT NOT NULL
                            REFERENCES public.welfare_requests(id),
                        member_id TEXT NOT NULL
                            REFERENCES public.members(member_id),
                        amount NUMERIC(12, 2) NOT NULL CHECK (amount > 0),
                        payment_reference TEXT NOT NULL UNIQUE,
                        created_by TEXT NOT NULL,
                        created_by_role TEXT NOT NULL DEFAULT 'Treasurer',
                        created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
                    );
                    ALTER TABLE public.welfare_request_member_arrears_payments
                        ADD COLUMN IF NOT EXISTS created_by_role TEXT NOT NULL DEFAULT 'Treasurer';
                    CREATE INDEX IF NOT EXISTS welfare_member_arrears_payments_member_idx
                        ON public.welfare_request_member_arrears_payments (member_id, request_id);

                    CREATE TABLE IF NOT EXISTS public.welfare_request_disbursements (
                        id BIGSERIAL PRIMARY KEY,
                        request_id BIGINT NOT NULL
                            REFERENCES public.welfare_requests(id),
                        target_amount NUMERIC(12, 2) NOT NULL CHECK (target_amount > 0),
                        amount NUMERIC(12, 2) NOT NULL CHECK (amount >= 0),
                        disbursed_by TEXT NOT NULL,
                        disbursed_role TEXT NOT NULL,
                        payment_reference TEXT NOT NULL UNIQUE,
                        disbursed_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
                    );
                    ALTER TABLE public.welfare_request_disbursements
                        DROP CONSTRAINT IF EXISTS welfare_request_disbursements_request_id_key;
                    CREATE INDEX IF NOT EXISTS welfare_request_disbursements_request_idx
                        ON public.welfare_request_disbursements (request_id, disbursed_at);

                    CREATE TABLE IF NOT EXISTS public.welfare_disbursement_reversals (
                        id BIGSERIAL PRIMARY KEY,
                        disbursement_id BIGINT NOT NULL UNIQUE
                            REFERENCES public.welfare_request_disbursements(id),
                        request_id BIGINT NOT NULL
                            REFERENCES public.welfare_requests(id),
                        amount_returned NUMERIC(12, 2) NOT NULL
                            CHECK (amount_returned > 0),
                        reason TEXT NOT NULL,
                        actor_name TEXT NOT NULL,
                        actor_role TEXT NOT NULL,
                        returned_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
                    );
                    CREATE INDEX IF NOT EXISTS welfare_disbursement_reversals_request_idx
                        ON public.welfare_disbursement_reversals (request_id, returned_at);
                    CREATE TABLE IF NOT EXISTS public.welfare_disbursement_reversal_allocations (
                        id BIGSERIAL PRIMARY KEY,
                        reversal_id BIGINT NOT NULL
                            REFERENCES public.welfare_disbursement_reversals(id),
                        request_id BIGINT NOT NULL
                            REFERENCES public.welfare_requests(id),
                        member_id TEXT NOT NULL
                            REFERENCES public.members(member_id),
                        welfare_amount_returned NUMERIC(12, 2) NOT NULL DEFAULT 0
                            CHECK (welfare_amount_returned >= 0),
                        savings_amount_returned NUMERIC(12, 2) NOT NULL DEFAULT 0
                            CHECK (savings_amount_returned >= 0),
                        arrears_amount_returned NUMERIC(12, 2) NOT NULL DEFAULT 0
                            CHECK (arrears_amount_returned >= 0),
                        created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
                        UNIQUE (reversal_id, member_id),
                        CHECK (
                            welfare_amount_returned
                            + savings_amount_returned
                            + arrears_amount_returned > 0
                        )
                    );
                    CREATE INDEX IF NOT EXISTS welfare_reversal_allocations_member_idx
                        ON public.welfare_disbursement_reversal_allocations (
                            member_id, request_id
                        );
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS public.sharing_withdrawal_requests (
                        id BIGSERIAL PRIMARY KEY,
                        member_id TEXT NOT NULL REFERENCES public.members(member_id),
                        amount NUMERIC(12, 2) NOT NULL CHECK (amount > 0),
                        status TEXT NOT NULL DEFAULT 'Pending',
                        requested_on TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
                        approved_by TEXT,
                        approved_role TEXT,
                        approved_on TIMESTAMP WITHOUT TIME ZONE,
                        rejected_by TEXT,
                        rejected_role TEXT,
                        rejected_on TIMESTAMP WITHOUT TIME ZONE,
                        disbursed_by TEXT,
                        disbursed_role TEXT,
                        disbursed_on TIMESTAMP WITHOUT TIME ZONE,
                        review_comment TEXT
                    );
                    ALTER TABLE public.sharing_withdrawal_requests
                        ADD COLUMN IF NOT EXISTS approved_by TEXT,
                        ADD COLUMN IF NOT EXISTS approved_role TEXT,
                        ADD COLUMN IF NOT EXISTS approved_on TIMESTAMP WITHOUT TIME ZONE,
                        ADD COLUMN IF NOT EXISTS rejected_by TEXT,
                        ADD COLUMN IF NOT EXISTS rejected_role TEXT,
                        ADD COLUMN IF NOT EXISTS rejected_on TIMESTAMP WITHOUT TIME ZONE,
                        ADD COLUMN IF NOT EXISTS disbursed_by TEXT,
                        ADD COLUMN IF NOT EXISTS disbursed_role TEXT,
                        ADD COLUMN IF NOT EXISTS disbursed_on TIMESTAMP WITHOUT TIME ZONE,
                        ADD COLUMN IF NOT EXISTS review_comment TEXT;
                    CREATE INDEX IF NOT EXISTS sharing_withdrawal_member_status_idx
                        ON public.sharing_withdrawal_requests (member_id, status);
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS public.sharing_workflow_state (
                        id BIGSERIAL PRIMARY KEY,
                        active BOOLEAN NOT NULL DEFAULT FALSE,
                        activated_on DATE,
                        deactivated_on DATE,
                        updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
                    );

                    CREATE TABLE IF NOT EXISTS public.home_gallery_images (
                        slot SMALLINT PRIMARY KEY CHECK (slot BETWEEN 1 AND 100),
                        image_url TEXT NOT NULL,
                        cloudinary_public_id TEXT,
                        uploaded_by TEXT NOT NULL,
                        updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
                    );
                    ALTER TABLE public.home_gallery_images
                        DROP CONSTRAINT IF EXISTS home_gallery_images_slot_check;
                    ALTER TABLE public.home_gallery_images
                        ADD CONSTRAINT home_gallery_images_slot_check
                        CHECK (slot BETWEEN 1 AND 100);
                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE public.members
                        ADD COLUMN IF NOT EXISTS suspended_previous_status TEXT,
                        ADD COLUMN IF NOT EXISTS suspension_reason TEXT,
                        ADD COLUMN IF NOT EXISTS suspended_by TEXT,
                        ADD COLUMN IF NOT EXISTS suspended_at TIMESTAMP WITHOUT TIME ZONE;

                    CREATE TABLE IF NOT EXISTS public.treasurer_savings_withdrawals (
                        id BIGSERIAL PRIMARY KEY,
                        member_id TEXT NOT NULL REFERENCES public.members(member_id),
                        amount NUMERIC(12, 2) NOT NULL CHECK (amount > 0),
                        reason TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'Pending',
                        requested_by TEXT NOT NULL,
                        requested_role TEXT NOT NULL,
                        requested_on TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
                        reviewed_by TEXT,
                        reviewed_role TEXT,
                        reviewed_on TIMESTAMP WITHOUT TIME ZONE,
                        review_comment TEXT
                    );
                    CREATE INDEX IF NOT EXISTS treasurer_savings_withdrawals_member_idx
                        ON public.treasurer_savings_withdrawals (member_id, status);
                    CREATE INDEX IF NOT EXISTS treasurer_savings_withdrawals_pending_idx
                        ON public.treasurer_savings_withdrawals (requested_on, id)
                        WHERE LOWER(BTRIM(status)) = 'pending';
                    """
                )
                cursor.execute(
                    """
                    CREATE OR REPLACE FUNCTION public.prevent_suspended_member_ledger_write()
                    RETURNS trigger
                    LANGUAGE plpgsql
                    AS $$
                    DECLARE
                        target_member_id TEXT;
                        target_status TEXT;
                    BEGIN
                        IF TG_OP <> 'INSERT' THEN
                            target_member_id := NULLIF(to_jsonb(OLD)->>'member_id', '');
                            IF target_member_id IS NULL AND TG_TABLE_NAME = 'welfare_payments' THEN
                                SELECT member_id INTO target_member_id
                                FROM public.welfare_requests
                                WHERE id = NULLIF(to_jsonb(OLD)->>'request_id', '')::BIGINT
                                FOR UPDATE;
                            END IF;
                            IF target_member_id IS NOT NULL THEN
                                target_status := NULL;
                                SELECT status INTO target_status
                                FROM public.members
                                WHERE member_id = target_member_id
                                FOR UPDATE;
                                IF LOWER(BTRIM(COALESCE(target_status, ''))) = 'suspended' THEN
                                    RAISE EXCEPTION 'Transactions for suspended member accounts are blocked.'
                                        USING ERRCODE = '55000';
                                END IF;
                            END IF;
                        END IF;

                        IF TG_OP <> 'DELETE' THEN
                            target_member_id := NULLIF(to_jsonb(NEW)->>'member_id', '');
                            IF target_member_id IS NULL AND TG_TABLE_NAME = 'welfare_payments' THEN
                                SELECT member_id INTO target_member_id
                                FROM public.welfare_requests
                                WHERE id = NULLIF(to_jsonb(NEW)->>'request_id', '')::BIGINT
                                FOR UPDATE;
                            END IF;
                            IF target_member_id IS NOT NULL THEN
                                target_status := NULL;
                                SELECT status INTO target_status
                                FROM public.members
                                WHERE member_id = target_member_id
                                FOR UPDATE;
                                IF LOWER(BTRIM(COALESCE(target_status, ''))) = 'suspended' THEN
                                    RAISE EXCEPTION 'Transactions for suspended member accounts are blocked.'
                                        USING ERRCODE = '55000';
                                END IF;
                            END IF;
                        END IF;

                        IF TG_OP = 'DELETE' THEN
                            RETURN OLD;
                        END IF;
                        RETURN NEW;
                    END;
                    $$;

                    """
                )
                cursor.execute(
                    """
                    ALTER TABLE public.loans
                        ADD COLUMN IF NOT EXISTS mobile_money_number TEXT,
                        ADD COLUMN IF NOT EXISTS rejection_reason TEXT,
                        ADD COLUMN IF NOT EXISTS approved_at TIMESTAMP WITHOUT TIME ZONE;

                    CREATE TABLE IF NOT EXISTS public.loan_approval_reversals (
                        id BIGSERIAL PRIMARY KEY,
                        loan_id INTEGER NOT NULL UNIQUE
                            REFERENCES public.loans(loan_id),
                        amount_returned NUMERIC(12, 2) NOT NULL
                            CHECK (amount_returned > 0),
                        reason TEXT NOT NULL,
                        actor_name TEXT NOT NULL,
                        actor_role TEXT NOT NULL,
                        returned_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
                    );
                    CREATE INDEX IF NOT EXISTS loan_approval_reversals_returned_idx
                        ON public.loan_approval_reversals (returned_at);
                    CREATE TABLE IF NOT EXISTS public.historical_loan_imports (
                        loan_id INTEGER PRIMARY KEY
                            REFERENCES public.loans(loan_id),
                        member_id TEXT NOT NULL
                            REFERENCES public.members(member_id),
                        source_reference TEXT NOT NULL,
                        balance_as_of_date DATE NOT NULL,
                        imported_by TEXT NOT NULL,
                        imported_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
                        notes TEXT NOT NULL DEFAULT '',
                        voided_at TIMESTAMP WITHOUT TIME ZONE
                    );
                    ALTER TABLE public.historical_loan_imports
                        ADD COLUMN IF NOT EXISTS member_id TEXT,
                        ADD COLUMN IF NOT EXISTS voided_at TIMESTAMP WITHOUT TIME ZONE;
                    UPDATE public.historical_loan_imports AS imported
                    SET member_id = loan.member_id
                    FROM public.loans AS loan
                    WHERE loan.loan_id = imported.loan_id
                      AND imported.member_id IS DISTINCT FROM loan.member_id;
                    DO $historical_loan_import_schema$
                    DECLARE
                        imports_without_member BIGINT;
                    BEGIN
                        SELECT COUNT(*)
                        INTO imports_without_member
                        FROM public.historical_loan_imports
                        WHERE member_id IS NULL;

                        IF imports_without_member > 0 THEN
                            RAISE EXCEPTION
                                'Cannot migrate historical_loan_imports: % row(s) have no matching member in public.loans.',
                                imports_without_member;
                        END IF;

                        ALTER TABLE public.historical_loan_imports
                            ALTER COLUMN member_id SET NOT NULL;

                        IF NOT EXISTS (
                            SELECT 1
                            FROM pg_constraint
                            WHERE conrelid =
                                'public.historical_loan_imports'::regclass
                              AND conname =
                                'historical_loan_imports_member_id_fkey'
                        ) THEN
                            ALTER TABLE public.historical_loan_imports
                                ADD CONSTRAINT
                                    historical_loan_imports_member_id_fkey
                                FOREIGN KEY (member_id)
                                REFERENCES public.members(member_id);
                        END IF;
                    END;
                    $historical_loan_import_schema$;
                    DROP INDEX IF EXISTS public.historical_loan_import_reference_idx;
                    CREATE UNIQUE INDEX IF NOT EXISTS historical_loan_import_active_reference_idx
                        ON public.historical_loan_imports (
                            member_id, LOWER(BTRIM(source_reference))
                        )
                        WHERE voided_at IS NULL;

                    ALTER TABLE public.loan_repayments
                        ADD COLUMN IF NOT EXISTS repayment_id BIGSERIAL,
                        ADD COLUMN IF NOT EXISTS recorded_at TIMESTAMP WITHOUT TIME ZONE,
                        ADD COLUMN IF NOT EXISTS is_historical BOOLEAN NOT NULL DEFAULT FALSE;
                    CREATE UNIQUE INDEX IF NOT EXISTS loan_repayments_repayment_id_idx
                        ON public.loan_repayments (repayment_id);
                    """
                )
                cursor.execute(
                    """
                    CREATE OR REPLACE VIEW public.member_welfare_balances AS
                    WITH contributions AS (
                        SELECT member_id, SUM(amount) AS total_contributed
                        FROM public.member_welfare_contributions
                        GROUP BY member_id
                    ),
                    assessed AS (
                        SELECT
                            contributions.member_id,
                            GREATEST(
                                SUM(contributions.welfare_amount)
                                    - COALESCE(returns.amount_returned, 0),
                                0
                            ) AS amount_assessed
                        FROM public.welfare_request_member_contributions contributions
                        LEFT JOIN (
                            SELECT
                                member_id,
                                SUM(welfare_amount_returned) AS amount_returned
                            FROM public.welfare_disbursement_reversal_allocations
                            GROUP BY member_id
                        ) returns USING (member_id)
                        GROUP BY contributions.member_id, returns.amount_returned
                    ),
                    arrears_paid AS (
                        SELECT
                            payments.member_id,
                            GREATEST(
                                SUM(payments.amount)
                                    - COALESCE(returns.amount_returned, 0),
                                0
                            ) AS amount_paid
                        FROM public.welfare_request_member_arrears_payments payments
                        LEFT JOIN (
                            SELECT
                                member_id,
                                SUM(arrears_amount_returned) AS amount_returned
                            FROM public.welfare_disbursement_reversal_allocations
                            GROUP BY member_id
                        ) returns USING (member_id)
                        GROUP BY payments.member_id, returns.amount_returned
                    )
                    SELECT
                        members.member_id,
                        COALESCE(contributions.total_contributed, 0)
                            AS total_contributed,
                        COALESCE(assessed.amount_assessed, 0) AS amount_assessed,
                        COALESCE(arrears_paid.amount_paid, 0) AS arrears_paid,
                        GREATEST(
                            COALESCE(contributions.total_contributed, 0)
                                - COALESCE(assessed.amount_assessed, 0)
                                - COALESCE(arrears_paid.amount_paid, 0),
                            0
                        ) AS welfare_balance
                    FROM public.members members
                    LEFT JOIN contributions USING (member_id)
                    LEFT JOIN assessed USING (member_id)
                    LEFT JOIN arrears_paid USING (member_id);
                    """
                )
                cursor.execute(
                    """
                    UPDATE public.sharing_withdrawal_requests
                    SET status = 'Paid',
                        disbursed_by = COALESCE(disbursed_by, 'Legacy workflow migration'),
                        disbursed_role = COALESCE(disbursed_role, 'System'),
                        disbursed_on = COALESCE(disbursed_on, requested_on, NOW())
                    WHERE LOWER(BTRIM(status)) = 'approved'
                      AND approved_on IS NULL
                      AND disbursed_on IS NULL;

                    DROP VIEW IF EXISTS public.sharing_member_payouts CASCADE;

                    CREATE VIEW public.sharing_member_payouts AS
                    WITH loan_values AS (
                        SELECT
                            loan_id,
                            member_id,
                            LOWER(BTRIM(COALESCE(status, ''))) AS status,
                            CASE
                                WHEN COALESCE(amount_requested, 0)::text
                                    IN ('NaN', 'Infinity', '-Infinity') THEN 0
                                ELSE COALESCE(amount_requested, 0)
                            END AS amount_requested,
                            CASE
                                WHEN COALESCE(total_interest_collected, 0)::text
                                    IN ('NaN', 'Infinity', '-Infinity') THEN 0
                                ELSE COALESCE(total_interest_collected, 0)
                            END AS total_interest_collected
                        FROM public.loans
                    ),
                    repayments_by_loan AS (
                        SELECT
                            loan_id,
                            COUNT(*) AS repayment_count,
                            SUM(
                                CASE
                                    WHEN COALESCE(interest_paid, 0)::text
                                        IN ('NaN', 'Infinity', '-Infinity') THEN 0
                                    ELSE COALESCE(interest_paid, 0)
                                END
                            ) AS interest_paid
                        FROM public.loan_repayments
                        GROUP BY loan_id
                    ),
                    per_loan_interest AS (
                        SELECT
                            loans.member_id,
                            CASE
                                WHEN COALESCE(repayments.repayment_count, 0) > 0
                                    THEN repayments.interest_paid
                                WHEN loans.total_interest_collected > 0
                                  AND loans.status IN (
                                      'paid', 'cleared', 'completed', 'settled', 'closed'
                                  )
                                    THEN loans.total_interest_collected
                                ELSE 0
                            END AS interest_amount
                        FROM loan_values loans
                        LEFT JOIN repayments_by_loan repayments
                            ON repayments.loan_id = loans.loan_id
                    ),
                    interest_totals AS (
                        SELECT
                            members.member_id,
                            COALESCE(SUM(per_loan_interest.interest_amount), 0)
                                AS member_interest_paid,
                            COALESCE(SUM(SUM(per_loan_interest.interest_amount)) OVER (), 0)
                                AS total_interest_pool
                        FROM public.members members
                        LEFT JOIN per_loan_interest
                            ON per_loan_interest.member_id = members.member_id
                        GROUP BY members.member_id
                    ),
                    member_savings AS (
                        SELECT
                            members.member_id,
                            LOWER(BTRIM(COALESCE(members.status, '')))
                                = 'suspended' AS is_suspended,
                            GREATEST(
                                COALESCE(subscriptions.paid_savings, 0)
                                    - COALESCE(welfare.transferred, 0)
                                    - COALESCE(support.savings_deducted, 0)
                                    + COALESCE(support_returns.savings_returned, 0)
                                    - COALESCE(treasurer_withdrawals.approved_amount, 0),
                                0
                            ) AS savings
                        FROM public.members members
                        LEFT JOIN (
                            SELECT
                                member_id,
                                SUM(
                                    CASE
                                        WHEN COALESCE(amount_paid, 0)::text
                                            IN ('NaN', 'Infinity', '-Infinity') THEN 0
                                        ELSE COALESCE(amount_paid, 0)
                                    END
                                ) AS paid_savings
                            FROM public.subscriptions
                            WHERE LOWER(BTRIM(COALESCE(status, ''))) = 'paid'
                            GROUP BY member_id
                        ) subscriptions ON subscriptions.member_id = members.member_id
                        LEFT JOIN (
                            SELECT
                                member_id,
                                SUM(
                                    CASE
                                        WHEN COALESCE(amount, 0)::text
                                            IN ('NaN', 'Infinity', '-Infinity') THEN 0
                                        ELSE COALESCE(amount, 0)
                                    END
                                ) AS transferred
                            FROM public.member_welfare_contributions
                            GROUP BY member_id
                        ) welfare ON welfare.member_id = members.member_id
                        LEFT JOIN (
                            SELECT
                                member_id,
                                SUM(savings_amount) AS savings_deducted
                            FROM public.welfare_request_member_contributions
                            GROUP BY member_id
                        ) support ON support.member_id = members.member_id
                        LEFT JOIN (
                            SELECT
                                member_id,
                                SUM(savings_amount_returned) AS savings_returned
                            FROM public.welfare_disbursement_reversal_allocations
                            GROUP BY member_id
                        ) support_returns
                            ON support_returns.member_id = members.member_id
                        LEFT JOIN (
                            SELECT
                                member_id,
                                SUM(amount) AS approved_amount
                            FROM public.treasurer_savings_withdrawals
                            WHERE LOWER(BTRIM(status)) = 'approved'
                            GROUP BY member_id
                        ) treasurer_withdrawals
                            ON treasurer_withdrawals.member_id = members.member_id
                    ),
                    withdrawal_totals AS (
                        SELECT
                            member_id,
                            SUM(
                                CASE
                                    WHEN LOWER(BTRIM(status)) IN ('paid', 'disbursed')
                                        THEN amount
                                    ELSE 0
                                END
                            ) AS disbursed_amount,
                            SUM(
                                CASE
                                    WHEN LOWER(BTRIM(status)) IN ('pending', 'approved')
                                        THEN amount
                                    ELSE 0
                                END
                            ) AS reserved_amount
                        FROM public.sharing_withdrawal_requests
                        GROUP BY member_id
                    ),
                    treasurer_withdrawal_totals AS (
                        SELECT
                            member_id,
                            SUM(amount) AS reserved_amount
                        FROM public.treasurer_savings_withdrawals
                        WHERE LOWER(BTRIM(status)) = 'pending'
                        GROUP BY member_id
                    ),
                    payout_components AS (
                        SELECT
                            members.member_id,
                            member_savings.savings,
                            member_savings.is_suspended,
                            interest_totals.member_interest_paid,
                            interest_totals.total_interest_pool,
                            (
                                SELECT COUNT(*)
                                FROM public.members eligible_members
                                WHERE LOWER(BTRIM(COALESCE(eligible_members.status, '')))
                                    <> 'suspended'
                            ) AS total_members,
                            ROUND(interest_totals.member_interest_paid * 0.30, 2)
                                AS borrower_dividend,
                            CASE
                                WHEN member_savings.is_suspended THEN 0
                                WHEN (
                                    SELECT COUNT(*)
                                    FROM public.members eligible_members
                                    WHERE LOWER(BTRIM(COALESCE(eligible_members.status, '')))
                                        <> 'suspended'
                                ) > 0
                                    THEN ROUND(
                                        interest_totals.total_interest_pool * 0.60
                                        / (
                                            SELECT COUNT(*)
                                            FROM public.members eligible_members
                                            WHERE LOWER(BTRIM(COALESCE(eligible_members.status, '')))
                                                <> 'suspended'
                                        ),
                                        2
                                    )
                                ELSE 0
                            END AS group_dividend,
                            COALESCE(withdrawal_totals.disbursed_amount, 0)
                                AS disbursed_amount,
                            COALESCE(withdrawal_totals.reserved_amount, 0)
                                AS reserved_amount,
                            COALESCE(treasurer_withdrawal_totals.reserved_amount, 0)
                                AS manual_reserved_amount
                        FROM public.members members
                        JOIN member_savings USING (member_id)
                        JOIN interest_totals USING (member_id)
                        LEFT JOIN withdrawal_totals USING (member_id)
                        LEFT JOIN treasurer_withdrawal_totals USING (member_id)
                    )
                    SELECT
                        member_id,
                        savings,
                        member_interest_paid,
                        total_interest_pool,
                        total_members,
                        borrower_dividend,
                        group_dividend,
                        CASE
                            WHEN is_suspended THEN 0
                            ELSE borrower_dividend + group_dividend
                        END AS total_dividends,
                        disbursed_amount,
                        reserved_amount,
                        GREATEST(
                            savings - GREATEST(
                                disbursed_amount - borrower_dividend - group_dividend,
                                0
                            ),
                            0
                        ) AS remaining_savings,
                        CASE
                            WHEN is_suspended THEN 0
                            ELSE GREATEST(
                                GREATEST(
                                    savings - GREATEST(
                                        disbursed_amount - borrower_dividend - group_dividend,
                                        0
                                    ),
                                    0
                                ) - LEAST(
                                    GREATEST(
                                        savings - GREATEST(
                                            disbursed_amount - borrower_dividend - group_dividend,
                                            0
                                        ),
                                        0
                                    ),
                                    GREATEST(
                                        reserved_amount - GREATEST(
                                            borrower_dividend + group_dividend
                                                - disbursed_amount,
                                            0
                                        ),
                                        0
                                    )
                                ) - manual_reserved_amount,
                                0
                            )
                        END AS available_savings,
                        CASE
                            WHEN is_suspended THEN 0
                            ELSE GREATEST(
                                savings + borrower_dividend + group_dividend
                                    - disbursed_amount - reserved_amount
                                    - manual_reserved_amount,
                                0
                            )
                        END AS available_payout
                    FROM payout_components;
                    """
                )
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    DO $$
                    DECLARE
                        target_table TEXT;
                    BEGIN
                        FOREACH target_table IN ARRAY ARRAY[
                            'subscriptions',
                            'subscription_payment_proofs',
                            'loans',
                            'loan_repayments',
                            'welfare_requests',
                            'welfare_payments',
                            'member_welfare_contributions',
                            'welfare_request_member_contributions',
                            'welfare_request_member_arrears_payments',
                            'welfare_request_disbursements',
                            'sharing_withdrawal_requests',
                            'treasurer_savings_withdrawals'
                        ]
                        LOOP
                            IF EXISTS (
                                SELECT 1
                                FROM information_schema.tables
                                WHERE table_schema = 'public'
                                  AND table_name = target_table
                            ) AND (
                                target_table = 'welfare_payments' OR EXISTS (
                                    SELECT 1
                                    FROM information_schema.columns
                                    WHERE table_schema = 'public'
                                      AND table_name = target_table
                                      AND column_name = 'member_id'
                                )
                            ) THEN
                                EXECUTE format(
                                    'DROP TRIGGER IF EXISTS prevent_suspended_member_ledger_write ON public.%I',
                                    target_table
                                );
                                EXECUTE format(
                                    'CREATE TRIGGER prevent_suspended_member_ledger_write '
                                    'BEFORE INSERT OR UPDATE OR DELETE ON public.%I '
                                    'FOR EACH ROW EXECUTE FUNCTION public.prevent_suspended_member_ledger_write()',
                                    target_table
                                );
                            END IF;
                        END LOOP;
                    END;
                    $$;
                    """
                )
            conn.commit()

            if not _rollback_connection(conn):
                raise OperationalError(
                    "Could not reset the database connection after its startup check."
                )

            pool.putconn(conn)
            conn = None

            db_pool = pool
            logger.info(
                "Neon PostgreSQL connection pool initialized for database '%s' "
                "(schema '%s'); required auth schema is present.",
                database_info["database_name"],
                database_info["schema_name"],
            )
            return
        except (OperationalError, InterfaceError):
            if pool is not None:
                if conn is not None:
                    _discard_connection(pool, conn)
                try:
                    pool.closeall()
                except Exception:
                    logger.exception("Failed to close an unsuccessful database pool.")
            db_pool = None

            if attempt == max_retries - 1:
                logger.exception(
                    "Failed to initialize Neon PostgreSQL connection pool after %s attempts.",
                    max_retries,
                )
                raise

            logger.warning(
                "Database connection attempt %s failed. Retrying in %.1f seconds.",
                attempt + 1,
                retry_delay,
                exc_info=True,
            )
            time.sleep(retry_delay)
            retry_delay *= 2
        except Exception:
            if pool is not None:
                if conn is not None:
                    _discard_connection(pool, conn)
                try:
                    pool.closeall()
                except Exception:
                    logger.exception("Failed to close an unsuccessful database pool.")
            db_pool = None
            logger.exception("Failed to initialize Neon PostgreSQL connection pool.")
            raise

def close_db_pool():
    global db_pool
    if db_pool:
        try:
            db_pool.closeall()
            logger.info("Neon PostgreSQL connection pool closed.")
        except Exception:
            logger.exception("Failed to close the Neon PostgreSQL connection pool.")
            raise

@contextmanager
def get_db() -> Generator[RealDictCursor, None, None]:
    """
    Retrieves a healthy pooled connection, yields its cursor, and cleans up safely.
    """
    pool = db_pool
    if pool is None:
        logger.error("Database access requested before the connection pool was initialized.")
        raise RuntimeError("Database pool is not initialized.")

    conn = None
    cursor = None
    discard_connection = False
    try:
        conn = _get_healthy_connection(pool)
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        yield cursor
        conn.commit()
    except (OperationalError, InterfaceError):
        discard_connection = True
        logger.warning("Database connection failed during an operation.", exc_info=True)
        if conn is not None:
            try:
                conn.rollback()
            except (OperationalError, InterfaceError):
                logger.warning("Rollback skipped because the DB connection is already closed or stale.", exc_info=True)
        raise
    except Exception:
        logger.exception("Database operation failed; attempting transaction rollback.")
        if conn is None or not _rollback_connection(conn):
            discard_connection = True
        raise
    finally:
        if cursor is not None:
            try:
                cursor.close()
            except Exception:
                logger.warning("Failed to close a database cursor cleanly.", exc_info=True)

        if conn is not None:
            if discard_connection or not _connection_is_healthy(conn):
                _discard_connection(pool, conn)
            else:
                try:
                    pool.putconn(conn)
                except (OperationalError, InterfaceError):
                    logger.warning("Failed to return a stale connection to the pool; discarding it.", exc_info=True)
                    _discard_connection(pool, conn)
                except Exception:
                    logger.exception("Failed to return database connection to the pool.")
                    if _connection_is_healthy(conn):
                        try:
                            conn.close()
                        except Exception:
                            logger.exception("Failed to close an unreturned database connection.")