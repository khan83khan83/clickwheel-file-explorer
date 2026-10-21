from app import config


def advance(index: int, steps: int, count: int, wrap: bool = True):
    """Move a selection by `steps`, optionally wrapping past either end.

    Returns (new_index, wrapped). `wrapped` tells the caller the move was not a
    neighbouring one, so it can play the wrap animation rather than an ordinary
    slide.

    `wrap=False` is for spatial views. Cover Flow shows the neighbouring covers
    on either side of the centre, so looping from the last to the first would
    contradict what is on screen; it stops at both ends instead. Lists have no
    such continuity, so they wrap.

    Wrapping can also be turned off globally with "wrap": false in config.json.
    """
    if count <= 0:
        return 0, False
    if not steps:
        return index, False

    if not wrap or not config.get("wrap", True):
        return max(0, min(count - 1, index + steps)), False

    raw = index + steps
    new = raw % count
    # A wrap is a move whose result sits on the far side of where it started.
    wrapped = raw < 0 or raw >= count
    return new, wrapped

class WheelAccumulator:
    THRESHOLD = 120
    ACCEL_WINDOW_MS = 130
    ACCEL_RESET_MS = 320
    MAX_MULT = 8

    def __init__(self):
        self._acc = 0
        self._last_ms = 0
        self._streak = 0

    def feed(self, angle_delta_y: int, now_ms: int) -> int:
        self._acc += angle_delta_y
        notches = int(self._acc / self.THRESHOLD)
        self._acc -= notches * self.THRESHOLD
        
        if notches == 0:
            return 0
            
        if now_ms - self._last_ms < self.ACCEL_WINDOW_MS:
            self._streak += 1
        else:
            self._streak = 0
            
        if now_ms - self._last_ms > self.ACCEL_RESET_MS:
            self._streak = 0
            
        mult = min(self.MAX_MULT, 1 + self._streak // 3)
        self._last_ms = now_ms
        
        # Round away from zero, minimum magnitude 1
        steps = notches * mult * config.SCROLL_SPEED
        if steps > 0:
            steps = max(1, int(steps + 0.5))
        else:
            steps = min(-1, int(steps - 0.5))
            
        return steps
