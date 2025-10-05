from typing import Optional
from datetime import datetime, timezone

def human_readable_size(num_bytes: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(num_bytes)
    for unit in units:
        if size < 1024.0 or unit == units[-1]:
            return f"{size:.1f}{unit}"
        size /= 1024.0
    return f"{size:.1f}TB"

def humanize_age(created: Optional[datetime], now: Optional[datetime] = None) -> str:
    if created is None:
        return "<unknown>"
    base = now or datetime.now(timezone.utc)
    # Ensure timezone-aware comparison
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    delta = base - created

    seconds = int(delta.total_seconds())
    if seconds < 60: 
        return f"{seconds}s ago"
    minutes = seconds // 60
    if minutes < 60: 
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24: 
        return f"{hours}h ago"
    days = hours // 24
    if days < 30:
        return f"{days}d ago"
    months = days // 30
    if months < 12:
        return f"{months}mo ago"
    years = months // 12
    return f"{years}y ago"

