"""Pure responsive-layout policy; dimensions are terminal cells, not pixels."""
import os

DEFAULT_MIN_COLUMNS = 52
GROW_BUFFER = 4
RESIZE_DELAY = 0.18


def minimum_columns():
    """Optional local preference, inherited by the viewer and its helpers."""
    try:
        value = int(os.environ.get('PI_DESK_MIN_COLUMNS', DEFAULT_MIN_COLUMNS))
        return value if 20 <= value <= 300 else DEFAULT_MIN_COLUMNS
    except ValueError:
        return DEFAULT_MIN_COLUMNS


def capacity(width, previous=None, minimum=None):
    minimum = minimum_columns() if minimum is None else minimum
    width = max(1, width)
    count = max(1, min(3, (width + 1) // (minimum + 1)))
    # Shrink immediately below the usable minimum. Growing requires a little
    # extra room, preventing oscillation while dragging near a breakpoint.
    if previous in (1, 2, 3) and count > previous:
        count = max(previous, min(3, (width + 1 - GROW_BUFFER) // (minimum + 1)))
    return count


def group(number, count):
    if number not in range(1, 11) or count not in (1, 2, 3):
        raise ValueError('Invalid session or layout capacity')
    first = ((number - 1) // count) * count + 1
    return tuple(range(first, min(first + count, 11)))


def shape(numbers):
    return ''.join(f'{i}:{n}:0|' for i, n in enumerate(numbers))
