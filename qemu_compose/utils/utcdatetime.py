
import datetime


'''
when handling datetime related, please follow rules below:

1. all datetime must set tzinfo
2. store and use datetime with tzinfo = UTC
3. only use local time when display to user interface
4. pass timestamp from epoch for API data
'''

beijing_timezone = datetime.timezone(datetime.timedelta(hours=8), "CST")

def to_timestamp(d:datetime.datetime):
    if not d.tzinfo:
        d = d.replace(tzinfo=datetime.timezone.utc)
    return d.timestamp()

def from_timestamp(d:float):
    return datetime.datetime.utcfromtimestamp(d).replace(tzinfo=datetime.timezone.utc)

def utcnow(with_tzinfo=True):
    d = datetime.datetime.utcnow()
    if with_tzinfo:
        return d.replace(tzinfo=datetime.timezone.utc)
    else:
        return d

def as_beijing_time(d:datetime.datetime):
    if not d.tzinfo:
        d = d.replace(tzinfo=datetime.timezone.utc)
    return d.astimezone(beijing_timezone)

def as_utc_time(d:datetime.datetime):
    if not d.tzinfo:
        d = d.replace(tzinfo=datetime.timezone.utc)
    return d.astimezone(datetime.timezone.utc)

def parse_datetime(v: str | int | float) -> datetime.datetime:
	if isinstance(v, (int, float)):
		return datetime.datetime.fromtimestamp(float(v), tz=datetime.timezone.utc)

	if not isinstance(v, str) or not v:
		return datetime.datetime.fromtimestamp(0, tz=datetime.timezone.utc)

	s = v.strip()
	# Normalize trailing Z and trim fractional seconds to microseconds
	if s.endswith("Z"):
		s = s[:-1] + "+00:00"
	try:
		if "." in s:
			head, tail = s.split(".", 1)
			# tail may contain timezone like 190005011+00:00
			frac = ""
			tz = ""
			for i, ch in enumerate(tail):
				if ch.isdigit():
					frac += ch
				else:
					tz = tail[i:]
					break
			if tz == "" and len(frac) != len(tail):
				tz = tail[len(frac):]
			frac = (frac + "000000")[:6]
			s_norm = f"{head}.{frac}{tz}"
			return datetime.datetime.fromisoformat(s_norm)
		return datetime.datetime.fromisoformat(s)
	except Exception:
		# Fallback to epoch if parsing fails
		return datetime.datetime.fromtimestamp(0, tz=datetime.timezone.utc)
