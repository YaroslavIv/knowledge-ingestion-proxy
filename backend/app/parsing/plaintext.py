from charset_normalizer import from_bytes


def parse_plaintext(data: bytes) -> tuple[str, list[str]]:
    warnings: list[str] = []
    best = from_bytes(data).best()
    if best is None:
        warnings.append("Could not confidently detect text encoding; decoded as UTF-8 with replacement")
        return data.decode("utf-8", errors="replace"), warnings
    return str(best), warnings
