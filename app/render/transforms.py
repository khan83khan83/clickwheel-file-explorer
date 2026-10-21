import math
from PySide6.QtGui import QTransform
from app import theme

def perspective_y(angle_deg: float, d: float = theme.CF_PERSP_D) -> QTransform:
    r = math.radians(angle_deg)
    return QTransform(math.cos(r), 0.0, math.sin(r) / d,
                      0.0,          1.0, 0.0,
                      0.0,          0.0, 1.0)
