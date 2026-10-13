"""Request payload validation helpers for the REST API bridge."""

from typing import Any, Optional, Tuple


def validate_vote_payload(data: Any) -> Tuple[bool, Optional[str], Optional[str], Optional[str]]:
    """Validate POST /api/votes payload.

    Returns:
        (is_valid, error_code, error_message, (client_id, choice))
    """
    if not isinstance(data, dict):
        return False, "invalid_json", "Request body must be a JSON object", None

    client_id = data.get("client_id")
    choice = data.get("choice")

    if client_id is None or choice is None:
        return False, "missing_fields", "Both 'client_id' and 'choice' are required", None

    if not isinstance(client_id, str):
        return False, "invalid_client_id", "'client_id' must be a string", None

    if not isinstance(choice, str):
        return False, "invalid_choice", "'choice' must be a string", None

    cleaned_client = client_id.strip()
    if not cleaned_client:
        return False, "invalid_client_id", "client_id must be non-empty", None

    if ":" in cleaned_client:
        return False, "invalid_client_id", "client_id must not contain ':'", None

    cleaned_choice = choice.strip()
    if not cleaned_choice:
        return False, "invalid_choice", "choice must be non-empty", None

    return True, None, None, (cleaned_client, cleaned_choice)
