def acquire_financial_action_lock(cursor) -> None:
    cursor.execute("SELECT pg_advisory_xact_lock(74123, 1001);")
