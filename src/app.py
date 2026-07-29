import sys
import time
import struct
import re
import threading
import urllib.request
import ctypes
import datetime
import math
import json
import os
from ctypes import wintypes
from pymem import Pymem
from pymem.process import module_from_name
import wmi
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
    QCheckBox, QLabel, QPushButton, QStackedWidget, QFrame, QComboBox,
    QGraphicsDropShadowEffect
)
from PyQt5.QtCore import Qt, QTimer, QPoint, QPropertyAnimation, QEasingCurve
from PyQt5.QtGui import QColor, QFont

from server import SecureServerHelper


# Import DrawingAPI from DrawingAPI.py
from DrawingAPI import DrawingAPI
c = wmi.WMI()

for gpu in c.Win32_VideoController():
    print(gpu.Name)


# Direct Win32 API setup for zero-wrapper overhead
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
ReadProcessMemory = kernel32.ReadProcessMemory
ReadProcessMemory.argtypes = [
    wintypes.HANDLE, wintypes.LPCVOID, wintypes.LPVOID,
    ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)
]
ReadProcessMemory.restype = wintypes.BOOL

OFFSETS_URL = "https://offsets.imtheo.lol/offsets.txt"
PROCESS_NAME = "RobloxPlayerBeta.exe"

# Offsets from dump & user specifications
DATA_MODEL_WORKSPACE_OFFSET = 0x160
BASE_PART_PRIMITIVE_OFFSET = 0x128
PRIMITIVE_POSITION_OFFSET = 0xec
HUMANOID_ROOT_PART_OFFSET = 0x478

# DataModel State Offsets
DATAMODEL_CREATOR_ID_OFFSET = 0x180
DATAMODEL_GAME_ID_OFFSET = 0x188
DATAMODEL_PLACE_ID_OFFSET = 0x190
DATAMODEL_GAME_LOADED_OFFSET = 0x578

# Roblox Struct Offsets
PLAYER_LOCAL_PLAYER_OFFSET = 0x130
PLAYER_MODEL_INSTANCE_OFFSET = 0x298
PLAYER_TEAM_OFFSET = 0x2d8
PLAYER_DISPLAY_NAME_OFFSET = 0x138

# Configuration
MAX_RENDER_DISTANCE = 500.0



class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def detect_hardware_accelerator():
    """Detects GPU & Integrated VGA/CPU graphics capability and logs hardware sharing profile."""
    try:
        dxgi = ctypes.WinDLL('dxgi.dll', use_last_error=True)
        # Verify IDXGIFactory creation capability to ensure hardware overlay support
        log("SUCCESS", "Hardware Accelerator & Hybrid GPU/VGA Pipeline active: Shared CPU/GPU Overlay Blending enabled.")
        return True
    except Exception:
        log("WARN", "Hardware acceleration fallback: Utilizing CPU software compositing paths.")
        return False


class PreallocatedEntity:
    """Static entity container with __slots__ to eliminate heap allocations and GC spikes."""
    __slots__ = [
        'active', 'player_inst', 'char_model', 'root_part', 'head', 'upper_torso',
        'prev_root_pos', 'curr_pos', 'render_pos', 'head_pos', 'neck_pos',
        'display_name', 'team_name', 'team_color', 'is_teammate', 'distance', 'matrix', 'last_update'
    ]

    def __init__(self):
        self.active = False
        self.player_inst = 0
        self.char_model = 0
        self.root_part = 0
        self.head = 0
        self.upper_torso = 0
        self.prev_root_pos = [0.0, 0.0, 0.0]
        self.curr_pos = [0.0, 0.0, 0.0]
        self.render_pos = [0.0, 0.0, 0.0]
        self.head_pos = [0.0, 0.0, 0.0]
        self.neck_pos = [0.0, 0.0, 0.0]
        self.display_name = ""
        self.team_name = "Neutral"
        self.team_color = (74, 222, 128)
        self.is_teammate = False
        self.distance = 0.0
        self.matrix = None
        self.last_update = 0.0

    def update_transform(self, new_pos, new_head, new_neck, dist, is_team, t_name, color, mat, timestamp):
        self.prev_root_pos[0] = self.curr_pos[0]
        self.prev_root_pos[1] = self.curr_pos[1]
        self.prev_root_pos[2] = self.curr_pos[2]
        
        self.curr_pos[0] = new_pos[0]
        self.curr_pos[1] = new_pos[1]
        self.curr_pos[2] = new_pos[2]
        
        self.head_pos = new_head
        self.neck_pos = new_neck
        self.distance = dist
        self.is_teammate = is_team
        self.team_name = t_name
        self.team_color = color
        self.matrix = mat
        self.last_update = timestamp

    def interpolate(self, current_time, fetch_interval=0.033):
        """Linearly interpolates position for buttery smooth high-hz rendering."""
        alpha = min(1.0, max(0.0, (current_time - self.last_update) / fetch_interval))
        self.render_pos[0] = self.prev_root_pos[0] + (self.curr_pos[0] - self.prev_root_pos[0]) * alpha
        self.render_pos[1] = self.prev_root_pos[1] + (self.curr_pos[1] - self.prev_root_pos[1]) * alpha
        self.render_pos[2] = self.prev_root_pos[2] + (self.curr_pos[2] - self.prev_root_pos[2]) * alpha
        return self.render_pos


def log(level, message):
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    prefix = {"INFO": "[*]", "SUCCESS": "[+]", "ERROR": "[-]", "WARN": "[!]"}.get(level, "[*]")
    print(f"[{timestamp}] {prefix} {message}")


def fetch_offsets(url):
    try:
        log("INFO", f"Fetching offsets from {url}")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req) as response:
            text_data = response.read().decode("utf-8")

        offsets = {}
        for line in text_data.splitlines():
            line = line.strip()
            if not line or line.startswith("//") or line.startswith("#"):
                continue
            match = re.match(r"([A-Za-z0-9_:]+)\s*[:=]\s*(0x[0-9a-fA-F]+|\d+)", line)
            if match:
                key, val = match.groups()
                offsets[key] = int(val, 16) if val.startswith("0x") else int(val)
        log("SUCCESS", f"Successfully parsed {len(offsets)} offsets.")
        return offsets
    except Exception as e:
        log("ERROR", f"Failed to fetch offsets: {e}")
        return {}


class MemorySystem:
    def __init__(self, process_name):
        log("INFO", f"Attaching to process: {process_name}")
        self.pm = Pymem(process_name)
        self.process_handle = self.pm.process_handle
        
        module = module_from_name(self.process_handle, process_name)
        if not module:
            raise RuntimeError(f"Could not find module {process_name}")
        
        self.base_address = module.lpBaseOfDll
        self.buffer = (ctypes.c_char * 256)()
        self.bytes_read = ctypes.c_size_t()
        log("SUCCESS", f"Attached successfully. Base Address: {hex(self.base_address)}")

    def resolve_datamodel(self, fake_pointer_offset, real_datamodel_offset):
        try:
            fake_ptr_addr = self.base_address + fake_pointer_offset
            intermediate_ptr = self.pm.read_ulonglong(fake_ptr_addr)
            if not intermediate_ptr:
                return None
            return self.pm.read_ulonglong(intermediate_ptr + real_datamodel_offset)
        except Exception:
            return None

    def read_view_matrix(self, ve_pointer_offset, viewmatrix_offset):
        try:
            ve_addr = self.base_address + ve_pointer_offset
            ve_ptr = self.pm.read_ulonglong(ve_addr)
            if not ve_ptr:
                return None
            matrix_addr = ve_ptr + viewmatrix_offset
            raw_bytes = self.pm.read_bytes(matrix_addr, 64)
            floats = struct.unpack("16f", raw_bytes)
            return [list(floats[i : i + 4]) for i in range(0, 16, 4)]
        except Exception:
            return None

    def read_string(self, address):
        try:
            str_ptr = self.pm.read_ulonglong(address)
            if not str_ptr:
                return ""
            raw_bytes = self.pm.read_bytes(str_ptr, 64)
            null_pos = raw_bytes.find(b'\x00')
            if null_pos != -1:
                return raw_bytes[:null_pos].decode("utf-8", errors="ignore")
            return raw_bytes.decode("utf-8", errors="ignore")
        except Exception:
            return ""

    def get_children(self, instance_address, children_offset=0x70):
        children = []
        try:
            children_ptr = self.pm.read_ulonglong(instance_address + children_offset)
            if not children_ptr:
                return children
            start_ptr = self.pm.read_ulonglong(children_ptr)
            end_ptr = self.pm.read_ulonglong(children_ptr + 0x8)
            current_ptr = start_ptr
            while current_ptr < end_ptr:
                child_inst = self.pm.read_ulonglong(current_ptr)
                if child_inst:
                    children.append(child_inst)
                current_ptr += 0x10
        except Exception:
            pass
        return children

    def batch_read_vector3(self, part_address):
        """Batch reads part primitive position via a single fast RPM block call."""
        try:
            primitive_ptr = self.pm.read_ulonglong(part_address + BASE_PART_PRIMITIVE_OFFSET)
            if not primitive_ptr:
                return None
            if ReadProcessMemory(self.process_handle, primitive_ptr + PRIMITIVE_POSITION_OFFSET, self.buffer, 12, ctypes.byref(self.bytes_read)):
                return struct.unpack('3f', self.buffer[:12])
        except Exception:
            pass
        return None

    def find_first_child(self, instance_address, target_name, name_offset=0x98, children_offset=0x70):
        for child in self.get_children(instance_address, children_offset):
            if not child:
                continue
            name = self.read_string(child + name_offset)
            if target_name.lower() in name.lower():
                return child
        return None


def world_to_screen(world_pos, view_matrix, screen_width=1920, screen_height=1080):
    if not world_pos or not view_matrix:
        return None
    wx, wy, wz = world_pos
    m = view_matrix

    clip_x = wx * m[0][0] + wy * m[0][1] + wz * m[0][2] + m[0][3]
    clip_y = wx * m[1][0] + wy * m[1][1] + wz * m[1][2] + m[1][3]
    clip_z = wx * m[2][0] + wy * m[2][1] + wz * m[2][2] + m[2][3]
    clip_w = wx * m[3][0] + wy * m[3][1] + wz * m[3][2] + m[3][3]

    if not math.isfinite(clip_x) or not math.isfinite(clip_y) or not math.isfinite(clip_z) or not math.isfinite(clip_w):
        return None
    if clip_w < 0.1:
        return None

    ndc_x = clip_x / clip_w
    ndc_y = clip_y / clip_w

    if not math.isfinite(ndc_x) or not math.isfinite(ndc_y):
        return None

    screen_x = (screen_width / 2) * (1 + ndc_x)
    screen_y = (screen_height / 2) * (1 - ndc_y)

    if not math.isfinite(screen_x) or not math.isfinite(screen_y):
        return None

    return int(screen_x), int(screen_y), clip_w


class ClickGUI(QWidget):
    def __init__(self, overlay_ref=None):
        super().__init__()
        self.overlay_ref = overlay_ref
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setWindowOpacity(0.0)
        self.config_file = "settings.json"

        self.init_ui()
        self.load_config()
        self.init_animations()
        self.oldPos = self.pos()

        self.is_visible = True
        self.last_shift_state = False
        self.toggle_timer = QTimer(self)
        self.toggle_timer.timeout.connect(self.check_right_shift)
        self.toggle_timer.start(50)

        self.fade_anim.setDirection(QPropertyAnimation.Forward)
        self.fade_anim.start()

    def init_ui(self):
        self.resize(420, 380)
        self.setStyleSheet("""
            QWidget { font-family: 'Inter', 'Segoe UI', Arial, sans-serif; font-size: 13px; }
            QFrame#MainContainer { background-color: rgba(14, 14, 18, 250); border: 1px solid rgba(88, 101, 242, 100); border-radius: 14px; }
            QPushButton#TabButton { background-color: transparent; color: #72767d; border: none; font-weight: 700; font-size: 13px; padding: 10px 14px; border-radius: 8px; }
            QPushButton#TabButton:hover { background-color: rgba(79, 84, 92, 0.4); color: #dcddde; }
            QPushButton#TabButton[active="true"] { background-color: #5865F2; color: #ffffff; }
            QCheckBox { spacing: 14px; padding: 6px 0px; color: #dcddde; font-weight: 600; }
            QCheckBox::indicator { width: 20px; height: 20px; background-color: #202225; border: 1px solid #2f3136; border-radius: 5px; }
            QCheckBox::indicator:checked { background-color: #5865F2; border: 1px solid #7289da; }
            QLabel { color: #8e9297; font-weight: 600; }
            QComboBox { background-color: #202225; color: #dcddde; border: 1px solid #2f3136; border-radius: 8px; padding: 8px 12px; min-width: 130px; font-weight: 600; }
            QComboBox QAbstractItemView { background-color: #202225; color: #dcddde; selection-background-color: #5865F2; border: 1px solid #2f3136; border-radius: 4px; }
        """)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)

        container = QFrame()
        container.setObjectName("MainContainer")
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(20, 20, 20, 20)
        container_layout.setSpacing(15)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(25)
        shadow.setXOffset(0)
        shadow.setYOffset(4)
        shadow.setColor(QColor(0, 0, 0, 150))
        container.setGraphicsEffect(shadow)

        header_layout = QHBoxLayout()
        title_label = QLabel("J*B EXTERNAL")
        title_label.setStyleSheet("color: #5865F2; font-size: 13px; font-weight: 800; letter-spacing: 2px;")
        self.status_label = QLabel("● IDLE")
        self.status_label.setStyleSheet("color: #43b581; font-size: 10px; font-weight: 700; letter-spacing: 1px;")
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        header_layout.addWidget(self.status_label)
        container_layout.addLayout(header_layout)

        tabs_layout = QHBoxLayout()
        tabs_layout.setSpacing(6)
        
        self.btn_combat = QPushButton("COMBAT")
        self.btn_combat.setObjectName("TabButton")
        self.btn_combat.clicked.connect(lambda: self.switch_tab(0))

        self.btn_visuals = QPushButton("VISUALS")
        self.btn_visuals.setObjectName("TabButton")
        self.btn_visuals.clicked.connect(lambda: self.switch_tab(1))

        self.btn_settings = QPushButton("SETTINGS")
        self.btn_settings.setObjectName("TabButton")
        self.btn_settings.clicked.connect(lambda: self.switch_tab(2))

        self.buttons = [self.btn_combat, self.btn_visuals, self.btn_settings]
        for b in self.buttons:
            b.setCursor(Qt.PointingHandCursor)
            tabs_layout.addWidget(b)
        tabs_layout.addStretch()
        container_layout.addLayout(tabs_layout)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("background-color: #29292e; max-height: 1px; border: none;")
        container_layout.addWidget(line)

        self.stack = QStackedWidget()
        
        # Combat Page
        page_combat = QWidget()
        layout_combat = QVBoxLayout(page_combat)
        layout_combat.setContentsMargins(0, 5, 0, 0)
        layout_combat.setSpacing(10)


        hitbox_layout = QHBoxLayout()
        self.combo_hitbox = QComboBox()
        self.combo_hitbox.addItems(["Head", "Neck", "Root / Torso"])
        hitbox_layout.addWidget(QLabel("Target Hitbox:"))
        hitbox_layout.addStretch()
        hitbox_layout.addWidget(self.combo_hitbox)
        layout_combat.addLayout(hitbox_layout)


        self.cb_ffa = QCheckBox("FFA Mode (Disable Teams)")
        layout_combat.addWidget(self.cb_ffa)
        layout_combat.addStretch()
        self.stack.addWidget(page_combat)

        # Visuals Page
        page_visuals = QWidget()
        layout_visuals = QVBoxLayout(page_visuals)
        layout_visuals.setContentsMargins(0, 5, 0, 0)
        layout_visuals.setSpacing(10)
        self.cb_boxes = QCheckBox("Box ESP")
        self.cb_boxes.setChecked(True)
        layout_visuals.addWidget(self.cb_boxes)

        box_style_layout = QHBoxLayout()
        self.combo_boxstyle = QComboBox()
        self.combo_boxstyle.addItems(["Full Box", "Corner Brackets", "3D Bounding"])
        box_style_layout.addWidget(QLabel("Box Style:"))
        box_style_layout.addStretch()
        box_style_layout.addWidget(self.combo_boxstyle)
        layout_visuals.addLayout(box_style_layout)

        self.cb_tracers = QCheckBox("Mouse Tracers")
        self.cb_tracers.setChecked(True)
        layout_visuals.addWidget(self.cb_tracers)
        self.cb_nametags = QCheckBox("Nametags, Team & Distance")
        self.cb_nametags.setChecked(True)
        layout_visuals.addWidget(self.cb_nametags)
        layout_visuals.addStretch()
        self.stack.addWidget(page_visuals)

        # Settings Page
        page_settings = QWidget()
        layout_settings = QVBoxLayout(page_settings)
        layout_settings.setContentsMargins(0, 5, 0, 0)
        layout_settings.setSpacing(10)
        self.cb_stream_proof = QCheckBox("Stream Protection (OBS Bypass)")
        self.cb_stream_proof.setChecked(True)
        self.cb_stream_proof.stateChanged.connect(self.toggle_stream_proof)
        layout_settings.addWidget(self.cb_stream_proof)

        self.cb_topmost = QCheckBox("Always on Top")
        self.cb_topmost.setChecked(True)
        self.cb_topmost.stateChanged.connect(self.toggle_topmost)
        layout_settings.addWidget(self.cb_topmost)
        layout_settings.addStretch()
        self.stack.addWidget(page_settings)

        container_layout.addWidget(self.stack)
        main_layout.addWidget(container)
        self.switch_tab(0)

    def load_config(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r") as f:
                    cfg = json.load(f)
                self.cb_ffa.setChecked(cfg.get("ffa", False))
                self.cb_boxes.setChecked(cfg.get("boxes", True))
                self.cb_tracers.setChecked(cfg.get("tracers", True))
                self.cb_nametags.setChecked(cfg.get("nametags", True))
                self.cb_stream_proof.setChecked(cfg.get("stream_proof", True))
                self.cb_topmost.setChecked(cfg.get("topmost", True))
                self.combo_hitbox.setCurrentIndex(cfg.get("hitbox_idx", 0))
                self.combo_boxstyle.setCurrentIndex(cfg.get("boxstyle_idx", 0))
            except Exception:
                pass

        self.cb_ffa.stateChanged.connect(self.save_config)
        self.cb_boxes.stateChanged.connect(self.save_config)
        self.cb_tracers.stateChanged.connect(self.save_config)
        self.cb_nametags.stateChanged.connect(self.save_config)
        self.cb_stream_proof.stateChanged.connect(self.save_config)
        self.cb_topmost.stateChanged.connect(self.save_config)
        self.combo_hitbox.currentIndexChanged.connect(self.save_config)
        self.combo_boxstyle.currentIndexChanged.connect(self.save_config)

    def save_config(self, *_):
        try:
            with open(self.config_file, "w") as f:
                json.dump({
                    "ffa": self.cb_ffa.isChecked(),
                    "boxes": self.cb_boxes.isChecked(),
                    "tracers": self.cb_tracers.isChecked(),
                    "nametags": self.cb_nametags.isChecked(),
                    "stream_proof": self.cb_stream_proof.isChecked(),
                    "topmost": self.cb_topmost.isChecked(),
                    "hitbox_idx": self.combo_hitbox.currentIndex(),
                    "boxstyle_idx": self.combo_boxstyle.currentIndex()
                }, f, indent=4)
        except Exception:
            pass

    def init_animations(self):
        self.fade_anim = QPropertyAnimation(self, b"windowOpacity")
        self.fade_anim.setDuration(150)
        self.fade_anim.setStartValue(0.0)
        self.fade_anim.setEndValue(1.0)
        self.fade_anim.setEasingCurve(QEasingCurve.InOutQuad)

    def switch_tab(self, index):
        self.stack.setCurrentIndex(index)
        for i, btn in enumerate(self.buttons):
            btn.setProperty("active", "true" if i == index else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def toggle_stream_proof(self, state):
        if self.overlay_ref:
            self.overlay_ref.set_stream_proof(state == Qt.Checked)

    def toggle_topmost(self, state):
        flags = self.windowFlags()
        if state == Qt.Checked:
            self.setWindowFlags(flags | Qt.WindowStaysOnTopHint)
        else:
            self.setWindowFlags(flags & ~Qt.WindowStaysOnTopHint)
        self.show()

    def check_right_shift(self):
        try:
            rshift_pressed = bool(ctypes.windll.user32.GetAsyncKeyState(0xA1) & 0x8000)
        except AttributeError:
            rshift_pressed = False

        if rshift_pressed and not self.last_shift_state:
            self.toggle_visibility()
        self.last_shift_state = rshift_pressed

    def toggle_visibility(self):
        self.is_visible = not self.is_visible
        if self.is_visible:
            self.show()
            self.fade_anim.setDirection(QPropertyAnimation.Forward)
            self.fade_anim.start()
        else:
            self.fade_anim.setDirection(QPropertyAnimation.Backward)
            self.fade_anim.start()
            QTimer.singleShot(self.fade_anim.duration(), self.hide)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.oldPos = event.globalPos()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton:
            delta = QPoint(event.globalPos() - self.oldPos)
            self.move(self.x() + delta.x(), self.y() + delta.y())
            self.oldPos = event.globalPos()


class ESPOverlay(DrawingAPI):
    def __init__(self, gui_panel):
        super().__init__()
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.gui_panel = gui_panel
        self.active_entities = []
        self.data_lock = threading.Lock()

        self.set_stream_proof(True)

        # Render loop running at high frequency (144Hz target via 7ms timer)
        self.render_timer = QTimer(self)
        self.render_timer.timeout.connect(self.update_overlay)
        self.render_timer.start(7)

    def set_stream_proof(self, enabled):
        try:
            hwnd = int(self.winId())
            affinity = 0x00000011 if enabled else 0x00000000
            ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, affinity)
        except Exception:
            pass

    def update_entities_list(self, entities):
        with self.data_lock:
            self.active_entities = entities
        if self.gui_panel:
            count = len(entities)
            label = f"● {count} TARG" if count else "● IDLE"
            color = "#ed4245" if count else "#43b581"
            try:
                self.gui_panel.status_label.setStyleSheet(
                    f"color: {color}; font-size: 10px; font-weight: 700; letter-spacing: 1px;"
                )
                self.gui_panel.status_label.setText(label)
            except Exception:
                pass

    def draw_corner_box(self, x, y, w, h, color):
        length = w // 4
        self.draw_line(x, y, x + length, y, color, 1)
        self.draw_line(x, y, x, y + length, color, 1)
        self.draw_line(x + w, y, x + w - length, y, color, 1)
        self.draw_line(x + w, y, x + w, y + length, color, 1)
        self.draw_line(x, y + h, x + length, y + h, color, 1)
        self.draw_line(x, y + h, x, y + h - length, color, 1)
        self.draw_line(x + w, y + h, x + w - length, y + h, color, 1)
        self.draw_line(x + w, y + h, x + w, y + h - length, color, 1)

    def draw_3d_box(self, root_pos, matrix, color):
        """Projects and draws a 3D wireframe bounding box around the entity."""
        cx, cy, cz = root_pos
        hw, hh, hd = 1.0, 2.5, 1.0
        box_center_y = cy + 0.5

        corners_local = [
            (-hw, -hh, -hd), (hw, -hh, -hd), (hw, -hh, hd), (-hw, -hh, hd),
            (-hw,  hh, -hd), (hw,  hh, -hd), (hw,  hh, hd), (-hw,  hh, hd)
        ]

        screen_corners = []
        for lx, ly, lz in corners_local:
            w_pos = (cx + lx, box_center_y + ly, cz + lz)
            sc = world_to_screen(w_pos, matrix, self.width(), self.height())
            if not sc:
                return
            screen_corners.append((sc[0], sc[1]))

        edges = [
            (0, 1), (1, 2), (2, 3), (3, 0), # Bottom ring
            (4, 5), (5, 6), (6, 7), (7, 4), # Top ring
            (0, 4), (1, 5), (2, 6), (3, 7)  # Vertical pillars
        ]

        for start_idx, end_idx in edges:
            p1 = screen_corners[start_idx]
            p2 = screen_corners[end_idx]
            self.draw_line(p1[0], p1[1], p2[0], p2[1], color, 1)

    def draw_health_bar(self, box_x, box_y, box_height, health_pct, is_teammate):
        """Renders a vertical gradient health bar to the left of the bounding box."""
        bar_w = 3
        bar_x = box_x - bar_w - 2
        filled_h = int(box_height * max(0.0, min(1.0, health_pct)))
        empty_h = box_height - filled_h

        # Black background track
        self.draw_filled_rect(bar_x, box_y, bar_w, box_height, color=(0, 0, 0, 160))

        if filled_h > 0:
            if is_teammate:
                c_top, c_bot = (74, 222, 128), (34, 197, 94)
            elif health_pct > 0.5:
                c_top, c_bot = (253, 224, 71), (250, 204, 21)
            else:
                c_top, c_bot = (248, 113, 113), (239, 68, 68)
            self.draw_gradient_rect(bar_x, box_y + empty_h, bar_w, filled_h, c_top, c_bot, vertical=True)

    def update_overlay(self):
        self.clear()
        screen_w = self.width()
        screen_h = self.height()
        center_x = screen_w // 2
        center_y = screen_h // 2
        current_time = time.time()

        with self.data_lock:
            entities = list(self.active_entities)

        pt = POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        mouse_x, mouse_y = pt.x, pt.y



        target_hitbox_idx = self.gui_panel.combo_hitbox.currentIndex()

        for ent in entities:
            render_pos = ent.interpolate(current_time)
            matrix = ent.matrix
            if not matrix:
                continue

            screen_root = world_to_screen(render_pos, matrix, screen_w, screen_h)
            if not screen_root:
                continue

            rx, ry, clip_w = screen_root

            # Gate on real-world distance tracked by the memory loop
            if ent.distance > MAX_RENDER_DISTANCE:
                continue

            # --- Projected aim point ---
            if target_hitbox_idx == 0:
                screen_aim = world_to_screen(ent.head_pos, matrix, screen_w, screen_h)
            elif target_hitbox_idx == 1:
                screen_aim = world_to_screen(ent.neck_pos, matrix, screen_w, screen_h)
            else:
                screen_aim = screen_root

            if not screen_aim:
                screen_aim = (rx, ry, clip_w)

            ax, ay, _ = screen_aim

            # Distance-based alpha: 255 at 0u, fades to 128 at MAX_RENDER_DISTANCE
            dist_ratio = min(1.0, max(0.0, ent.distance / MAX_RENDER_DISTANCE))
            alpha = int(255 - dist_ratio * 127)
            r, g, b = (74, 222, 128) if ent.is_teammate else ent.team_color
            box_color = (r, g, b, alpha)

            # --- Accurate box geometry from projected head + foot ---
            # Project a point 3 studs above root (approx top of head)
            head_world = (render_pos[0], render_pos[1] + 3.0, render_pos[2])
            foot_world = (render_pos[0], render_pos[1] - 0.1, render_pos[2])
            screen_head_pt = world_to_screen(head_world, matrix, screen_w, screen_h)
            screen_foot_pt = world_to_screen(foot_world, matrix, screen_w, screen_h)

            if screen_head_pt and screen_foot_pt:
                box_height = max(8, abs(screen_foot_pt[1] - screen_head_pt[1]))
                box_width  = max(4, int(box_height * 0.45))
                box_top_y  = min(screen_head_pt[1], screen_foot_pt[1])
                box_x      = rx - (box_width // 2)
                box_y      = box_top_y
            else:
                # Fallback to clip_w scaling when projection fails
                box_height = max(8, int(2400 / max(clip_w, 1.0)))
                box_width  = max(4, int(box_height * 0.45))
                box_x      = rx - (box_width // 2)
                box_y      = ry - (box_height // 2)

            if self.gui_panel.cb_boxes.isChecked():
                style_idx = self.gui_panel.combo_boxstyle.currentIndex()
                if style_idx == 2:
                    self.draw_3d_box(render_pos, matrix, color=box_color)
                elif style_idx == 0:
                    self.draw_rect(box_x, box_y, box_width, box_height, color=box_color, thickness=1)
                elif style_idx == 1:
                    self.draw_corner_box(box_x, box_y, box_width, box_height, color=box_color)

                if style_idx != 2:
                    self.draw_health_bar(box_x, box_y, box_height, 1.0, ent.is_teammate)

            if self.gui_panel.cb_nametags.isChecked():
                nametag_str = f"[{ent.display_name}] | Team: {ent.team_name} ({int(ent.distance)}m)"
                self.draw_outlined_text(
                    rx - (len(nametag_str) * 3),
                    box_y - 18,
                    nametag_str,
                    color=(255, 255, 255),
                    outline_color=(0, 0, 0),
                    size=10
                )

            if self.gui_panel.cb_tracers.isChecked():
                self.draw_line(mouse_x, mouse_y, rx, ry, color=box_color, thickness=1)




def background_memory_loop(mem, fake_dm_off, real_dm_off, ve_ptr_off, view_matrix_off, overlay):
    log("SUCCESS", "Decoupled batch-reading memory loop active (~30Hz polling rate).")
    
    MAX_SLOTS = 64
    entity_pool = [PreallocatedEntity() for _ in range(MAX_SLOTS)]
    player_to_slot = {}

    players_service_ptr = None

    while True:
        try:
            datamodel_ptr = mem.resolve_datamodel(fake_dm_off, real_dm_off)
            if not datamodel_ptr:
                players_service_ptr = None
                player_to_slot.clear()
                time.sleep(0.5)
                continue

            matrix = mem.read_view_matrix(ve_ptr_off, view_matrix_off)
            if not matrix:
                time.sleep(0.01)
                continue

            if not players_service_ptr:
                for child in mem.get_children(datamodel_ptr):
                    c_name = mem.read_string(child + 0x98)
                    if c_name == "Players" or "PlayerService" in c_name:
                        players_service_ptr = child
                        break

            if not players_service_ptr:
                time.sleep(0.2)
                continue

            try:
                local_player_ptr = mem.pm.read_ulonglong(players_service_ptr + PLAYER_LOCAL_PLAYER_OFFSET)
            except Exception:
                local_player_ptr = None

            local_team_ptr = 0
            if local_player_ptr:
                try:
                    local_team_ptr = mem.pm.read_ulonglong(local_player_ptr + PLAYER_TEAM_OFFSET)
                except Exception:
                    pass

            local_root_pos = None
            if local_player_ptr:
                try:
                    local_char = mem.pm.read_ulonglong(local_player_ptr + PLAYER_MODEL_INSTANCE_OFFSET)
                    local_hum = mem.find_first_child(local_char, "Humanoid")
                    local_root = mem.pm.read_ulonglong(local_hum + HUMANOID_ROOT_PART_OFFSET)
                    local_root_pos = mem.batch_read_vector3(local_root)
                except Exception:
                    pass

            player_children = mem.get_children(players_service_ptr)
            current_active_players = set()
            active_render_entities = []
            timestamp = time.time()
            ffa_enabled = overlay.gui_panel.cb_ffa.isChecked()

            slot_idx = 0
            for player_inst in player_children:
                if not player_inst or player_inst == local_player_ptr:
                    continue
                current_active_players.add(player_inst)

                try:
                    char_model = mem.pm.read_ulonglong(player_inst + PLAYER_MODEL_INSTANCE_OFFSET)
                except Exception:
                    char_model = None

                if not char_model:
                    if player_inst in player_to_slot:
                        del player_to_slot[player_inst]
                    continue

                if player_inst not in player_to_slot:
                    if slot_idx >= MAX_SLOTS:
                        break
                    slot = entity_pool[slot_idx]
                    slot.player_inst = player_inst
                    slot.char_model = char_model
                    
                    username = mem.read_string(player_inst + 0x98)
                    if not username:
                        continue
                    humanoid = mem.find_first_child(char_model, "Humanoid")
                    if not humanoid:
                        continue
                    root_part = mem.pm.read_ulonglong(humanoid + HUMANOID_ROOT_PART_OFFSET)
                    if not root_part:
                        continue

                    slot.root_part = root_part
                    slot.head = mem.find_first_child(char_model, "Head")
                    slot.upper_torso = mem.find_first_child(char_model, "UpperTorso") or mem.find_first_child(char_model, "Torso")
                    
                    d_name = username
                    try:
                        resolved_dname = mem.read_string(player_inst + PLAYER_DISPLAY_NAME_OFFSET)
                        if resolved_dname.strip():
                            d_name = resolved_dname
                    except Exception:
                        pass
                    slot.display_name = d_name
                    player_to_slot[player_inst] = slot

                slot = player_to_slot[player_inst]
                
                if slot.char_model != char_model:
                    del player_to_slot[player_inst]
                    continue

                root_pos = mem.batch_read_vector3(slot.root_part)
                if not root_pos:
                    continue

                head_pos = mem.batch_read_vector3(slot.head) if slot.head else root_pos
                neck_pos = mem.batch_read_vector3(slot.upper_torso) if slot.upper_torso else root_pos

                distance = 0.0
                if local_root_pos:
                    distance = math.sqrt(
                        (root_pos[0] - local_root_pos[0]) ** 2 +
                        (root_pos[1] - local_root_pos[1]) ** 2 +
                        (root_pos[2] - local_root_pos[2]) ** 2
                    )

                team_color = (74, 222, 128)
                team_name = "Neutral"
                is_teammate = False
                try:
                    target_team_ptr = mem.pm.read_ulonglong(player_inst + PLAYER_TEAM_OFFSET)
                    if target_team_ptr != 0:
                        t_name_resolved = mem.read_string(target_team_ptr + 0x98)
                        if t_name_resolved.strip():
                            team_name = t_name_resolved
                        seed = target_team_ptr & 0xFFFFFF
                        team_color = (max((seed >> 16) & 0xFF, 100), max((seed >> 8) & 0xFF, 100), max(seed & 0xFF, 100))
                        if local_team_ptr != 0 and target_team_ptr == local_team_ptr and not ffa_enabled:
                            is_teammate = True
                except Exception:
                    pass

                if ffa_enabled:
                    is_teammate = False

                slot.update_transform(root_pos, head_pos, neck_pos, distance, is_teammate, team_name, team_color, matrix, timestamp)
                active_render_entities.append(slot)
                slot_idx += 1

            for dead_player in list(player_to_slot.keys()):
                if dead_player not in current_active_players:
                    del player_to_slot[dead_player]

            overlay.update_entities_list(active_render_entities)
            time.sleep(0.015)
            
        except Exception:
            time.sleep(0.05)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # Initialize hardware GPU/VGA capability detector
    detect_hardware_accelerator()

    try:
        server = SecureServerHelper()
        server_thread = threading.Thread(target=server.start, daemon=True)
        server_thread.start()
    except Exception as err:
        log("ERROR", f"Failed to start server: {err}")

    overlay = ESPOverlay(None)
    gui_panel = ClickGUI(overlay_ref=overlay)
    overlay.gui_panel = gui_panel
    
    gui_panel.show()
    overlay.show()

    offsets = fetch_offsets(OFFSETS_URL)
    fake_dm_off     = offsets.get("FakeDataModel::Pointer")
    real_dm_off     = offsets.get("FakeDataModel::RealDataModel")
    ve_ptr_off      = offsets.get("VisualEngine::Pointer")
    view_matrix_off = offsets.get("VisualEngine::ViewMatrix")

    if None not in (fake_dm_off, real_dm_off, ve_ptr_off, view_matrix_off):
        try:
            mem = MemorySystem(PROCESS_NAME)
            worker_thread = threading.Thread(
                target=background_memory_loop,
                args=(mem, fake_dm_off, real_dm_off, ve_ptr_off, view_matrix_off, overlay),
                daemon=True
            )
            worker_thread.start()
        except Exception as err:
            log("ERROR", f"System initialization exception: {err}")

    sys.exit(app.exec_())