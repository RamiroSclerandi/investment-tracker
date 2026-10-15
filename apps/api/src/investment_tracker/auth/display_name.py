import re

DISPLAY_NAME_MAX_LENGTH = 80
# Control and line separator characters would let a name break headers or log lines.
DISPLAY_NAME_FORBIDDEN_CHARS = r"\x00-\x1f\x7f\x85\u2028\u2029"
DISPLAY_NAME_PATTERN = rf"^[^{DISPLAY_NAME_FORBIDDEN_CHARS}]+$"
DISPLAY_NAME_FORBIDDEN = re.compile(rf"[{DISPLAY_NAME_FORBIDDEN_CHARS}]")
