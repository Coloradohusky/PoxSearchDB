import datetime

def log_message(message: str, verbose: bool) -> str | None:
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    if not verbose:
        return None
    else:
        return f"[{timestamp}] {message}"
