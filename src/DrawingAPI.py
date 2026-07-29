import sys
from enum import IntEnum, auto
from typing import Tuple, List, Dict

from PyQt5.QtWidgets import QApplication, QWidget
from PyQt5.QtGui import QPainter, QPen, QColor, QFont, QLinearGradient, QBrush
from PyQt5.QtCore import Qt, QTimer, QRectF


class DrawShape(IntEnum):
    """Integer enums are much faster to compare than strings in a loop."""
    RECT = auto()
    FILLED_RECT = auto()
    GRADIENT_RECT = auto()
    LINE = auto()
    TEXT = auto()
    CIRCLE = auto()
    OUTLINED_TEXT = auto()


class DrawingAPI(QWidget):
    def __init__(self):
        super().__init__()
        
        # Configure Window Attributes for Transparent Overlay
        self.setWindowFlags(
            Qt.FramelessWindowHint |         # No border/title bar
            Qt.WindowStaysOnTopHint |        # Always on top
            Qt.WindowTransparentForInput |   # Mouse clicks pass through to the game
            Qt.Tool                          # Hide from Taskbar
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        
        # Cover the entire screen
        screen = QApplication.primaryScreen().geometry()
        self.setGeometry(0, 0, screen.width(), screen.height())
        
        # Buffer to store objects to be drawn in each frame
        self.render_queue: List[tuple] = []

        # Caches to prevent instantiating Qt objects thousands of times per second
        self._pens: Dict[tuple, QPen] = {}
        self._colors: Dict[tuple, QColor] = {}
        self._fonts: Dict[int, QFont] = {}

        # Refresh timer (60 FPS ~ 16ms)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update)
        self.timer.start(16)

    # --- Private helper methods for caching ---
    
    def _get_color(self, rgba: tuple) -> QColor:
        if rgba not in self._colors:
            self._colors[rgba] = QColor(*rgba)
        return self._colors[rgba]

    def _get_pen(self, rgba: tuple, thickness: int) -> QPen:
        key = (*rgba, thickness)
        if key not in self._pens:
            self._pens[key] = QPen(self._get_color(rgba), thickness)
        return self._pens[key]

    def _get_font(self, size: int) -> QFont:
        if size not in self._fonts:
            self._fonts[size] = QFont("Arial", size, QFont.Bold)
        return self._fonts[size]

    # --- Public API ---

    def clear(self):
        """Clears previous frame elements."""
        self.render_queue.clear()

    def draw_rect(self, x, y, width, height, color=(255, 0, 0), thickness=2):
        """Adds a rectangle to the render queue."""
        self.render_queue.append((
            DrawShape.RECT, 
            int(x), int(y), int(width), int(height), 
            self._get_pen(color, thickness)
        ))

    def draw_line(self, x1, y1, x2, y2, color=(255, 255, 255), thickness=1):
        """Adds a line (for tracers/skeletons) to the render queue."""
        self.render_queue.append((
            DrawShape.LINE, 
            int(x1), int(y1), int(x2), int(y2), 
            self._get_pen(color, thickness)
        ))

    def draw_text(self, x, y, text, color=(255, 255, 255), size=12):
        """Adds text to the render queue."""
        self.render_queue.append((
            DrawShape.TEXT, 
            int(x), int(y), text, 
            self._get_color(color), 
            self._get_font(size)
        ))

    def draw_circle(self, x, y, radius, color=(255, 255, 255), thickness=1):
        """Adds a circle to the render queue."""
        self.render_queue.append((
            DrawShape.CIRCLE,
            int(x), int(y), int(radius),
            self._get_pen(color, thickness)
        ))

    def draw_outlined_text(self, x, y, text, color=(255, 255, 255), outline_color=(0, 0, 0), size=12):
        """Adds text with a 1px outline to the render queue."""
        self.render_queue.append((
            DrawShape.OUTLINED_TEXT,
            int(x), int(y), text,
            self._get_color(color),
            self._get_color(outline_color),
            self._get_font(size)
        ))

    def draw_filled_rect(self, x, y, width, height, color=(0, 0, 0, 120)):
        """Adds a filled rectangle with optional alpha to the render queue."""
        self.render_queue.append((
            DrawShape.FILLED_RECT,
            int(x), int(y), int(width), int(height),
            self._get_color(color)
        ))

    def draw_gradient_rect(self, x, y, width, height, color_start, color_end, vertical=True):
        """Adds a vertical or horizontal gradient-filled rectangle (e.g. for health bars)."""
        self.render_queue.append((
            DrawShape.GRADIENT_RECT,
            int(x), int(y), int(width), int(height),
            self._get_color(color_start),
            self._get_color(color_end),
            vertical
        ))

    def paintEvent(self, event):
        """PyQt render cycle triggered by self.update()."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # We only need to set the brush once globally for this use case
        painter.setBrush(Qt.NoBrush)

        for item in self.render_queue:
            shape = item[0]
            
            if shape == DrawShape.RECT:
                _, x, y, w, h, pen = item
                painter.setPen(pen)
                painter.drawRect(x, y, w, h)
                
            elif shape == DrawShape.LINE:
                _, x1, y1, x2, y2, pen = item
                painter.setPen(pen)
                painter.drawLine(x1, y1, x2, y2)
                
            elif shape == DrawShape.TEXT:
                _, x, y, text, text_color, font = item
                painter.setPen(text_color)
                painter.setFont(font)
                painter.drawText(x, y, text)

            elif shape == DrawShape.CIRCLE:
                _, x, y, r, pen = item
                painter.setPen(pen)
                painter.drawEllipse(x - r, y - r, r * 2, r * 2)

            elif shape == DrawShape.OUTLINED_TEXT:
                _, x, y, text, text_color, outline_color, font = item
                painter.setFont(font)
                painter.setPen(outline_color)
                painter.drawText(x - 1, y - 1, text)
                painter.drawText(x + 1, y - 1, text)
                painter.drawText(x - 1, y + 1, text)
                painter.drawText(x + 1, y + 1, text)
                painter.drawText(x, y - 1, text)
                painter.drawText(x, y + 1, text)
                painter.drawText(x - 1, y, text)
                painter.drawText(x + 1, y, text)
                painter.setPen(text_color)
                painter.drawText(x, y, text)

            elif shape == DrawShape.FILLED_RECT:
                _, x, y, w, h, fill_color = item
                painter.setPen(Qt.NoPen)
                painter.setBrush(QBrush(fill_color))
                painter.drawRect(x, y, w, h)
                painter.setBrush(Qt.NoBrush)

            elif shape == DrawShape.GRADIENT_RECT:
                _, x, y, w, h, c_start, c_end, vertical = item
                grad = QLinearGradient(
                    x, y,
                    x if vertical else x + w,
                    y + h if vertical else y
                )
                grad.setColorAt(0.0, c_start)
                grad.setColorAt(1.0, c_end)
                painter.setPen(Qt.NoPen)
                painter.setBrush(QBrush(grad))
                painter.drawRect(x, y, w, h)
                painter.setBrush(Qt.NoBrush)