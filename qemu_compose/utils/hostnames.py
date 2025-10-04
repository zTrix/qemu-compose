def to_valid_hostname(name: str) -> str:
    """Translate an arbitrary name to a valid Linux hostname label.

    Rules applied:
    - Keep only [a-z0-9-]; replace others with '-'
    - Lowercase the result
    - Collapse multiple '-'
    - Trim leading/trailing '-'
    - Truncate to 63 characters
    - If empty, fall back to 'vm'
    """
    import re

    s = name.lower()
    s = re.sub(r"[^a-z0-9-]", "-", s)
    s = re.sub(r"-+", "-", s)
    s = s.strip('-')
    if len(s) > 63:
        s = s[:63]
    if not s:
        s = 'vm'
    return s

