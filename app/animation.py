import math

class Animator:
    """Frame-driven float springs. Stage ticks all of them at 60 Hz."""
    def __init__(self, value: float):
        self.value = value
        self._target = value
        self.active = False
        self.tau = 0.075
        self.epsilon = 0.004
        self.on_done = None

    @property
    def target_value(self) -> float:
        """Where this animator is heading. Callers that need to act on the
        settled position (page prefetch, scroll clamping) must use this, not
        `value`, which is still mid-flight."""
        return self._target

    def target(self, v: float) -> None:
        self._target = v
        if abs(self._target - self.value) >= self.epsilon:
            self.active = True
        else:
            self.value = self._target
            self.active = False
            if self.on_done:
                cb, self.on_done = self.on_done, None
                cb()

    def snap(self, v: float) -> None:
        self._target = v
        self.value = v
        self.active = False
        if self.on_done:
            cb, self.on_done = self.on_done, None
            cb()

    def tick(self, dt: float) -> bool:
        if not self.active:
            return False
            
        k = 1 - math.exp(-dt / self.tau)        # tau in seconds
        self.value += (self._target - self.value) * k
        if abs(self._target - self.value) < self.epsilon:
            self.value = self._target
            self.active = False
            if self.on_done:
                cb, self.on_done = self.on_done, None
                cb()
            
        return self.active
