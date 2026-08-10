"""Small math helpers with an intentional off-by-one bug."""

def clamp_index(i: int, length: int) -> int:
    """Return i clamped to [0, length-1]. Currently off-by-one on the upper bound."""
    if length <= 0:
        return 0
    if i < 0:
        return 0
    # BUG: should be length - 1
    if i > length:
        return length
    return i


def add(a: int, b: int) -> int:
    return a + b
