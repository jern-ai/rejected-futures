"""Redaction runs on every string before it is stored. Transcripts hold pasted secrets
(keys in debug output, tokens on command lines); nothing is kept unredacted."""
import re

SECRET_PATTERNS = [
    re.compile(r"(?i)\b([A-Z_]*(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD)[A-Z_]*)\s*[=:]\s*\S{12,}"),
    re.compile(r"\b(?:sk-[A-Za-z0-9_-]{16,}|jern_[0-9a-f]{12,}|ghp_[A-Za-z0-9]{20,}|gho_[A-Za-z0-9]{20,}"
               r"|github_pat_[A-Za-z0-9_]{20,}|xox[abp]-[A-Za-z0-9-]{20,}|AKIA[A-Z0-9]{16}"
               r"|AIza[0-9A-Za-z_-]{30,}|glpat-[A-Za-z0-9_-]{20,}|npm_[A-Za-z0-9]{30,}"
               r"|pypi-[A-Za-z0-9_-]{30,}|fo1_[A-Za-z0-9_-]{30,}|FlyV1 \S{20,})\b"),
    re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}:[0-9a-f]{32}\b"),
    re.compile(r"(?i)\b(?:api[ _-]?key|bearer|authorization)\s*[:=]?\s*\S{20,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
]


def redact(s: str) -> str:
    if not s:
        return s

    def sub(m):
        head = m.group(1) if m.lastindex else ""
        return (head + "=<redacted>") if head else "<redacted>"

    for p in SECRET_PATTERNS:
        s = p.sub(sub, s)
    return s
