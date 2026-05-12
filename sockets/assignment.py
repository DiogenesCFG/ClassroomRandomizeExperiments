import hashlib


def assign_arm(student_id: str, survey_id: int, num_arms: int) -> int:
    """
    Deterministically assign a student to an arm index in [0, num_arms-1].

    Uses SHA-256 so the result is stable across page refreshes and server restarts.
    """
    key = f"{student_id}:{survey_id}"
    hash_bytes = hashlib.sha256(key.encode('utf-8')).digest()
    hash_int = int.from_bytes(hash_bytes[:4], byteorder='big')
    return hash_int % num_arms
