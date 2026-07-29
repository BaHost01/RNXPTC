"""
Production-Ready ImGui Bundle Helper Framework
Includes Component Architecture, Docking Layout Engine, Theme Tweaks, and Context Helpers.
"""

from abc import ABC, abstractmethod
from contextlib import contextmanager
from typing import Callable, List, Optional, Tuple
import time

from imgui_bundle import imgui, hello_imgui


# =========================================================================
# 1. CONTEXT MANAGERS & SCOPE HELPERS
# =========================================================================
class UIContext:
    """Helper context managers for ergonomic ImGui layout control."""

    @staticmethod
    @contextmanager
    def group():
        """Groups elements together visually and logically."""
        imgui.begin_group()
        try:
            yield
        finally:
            imgui.end_group()

    @staticmethod
    @contextmanager
    def disabled(is_disabled: bool = True):
        """Conditionally disables all child widgets."""
        if is_disabled:
            imgui.begin_disabled(True)
        try:
            yield
        finally:
            if is_disabled:
                imgui.end_disabled()

    @staticmethod
    @contextmanager
    def child(str_id: str, size: Tuple[float, float] = (0.0, 0.0), border: bool = True, flags: int = 0):
        """Creates a scrollable child region within a window."""
        imgui.begin_child(str_id, imgui.ImVec2(*size), border, flags)
        try:
            yield
        finally:
            imgui.end_child()

    @staticmethod
    @contextmanager
    def item_width(width: float):
        """Sets fixed width for upcoming input widgets."""
        imgui.push_item_width(width)
        try:
            yield
        finally:
            imgui.pop_item_width()


# =========================================================================
# 2. ABSTRACT BASE UI COMPONENTS
# =========================================================================
class FloatingComponent(ABC):
    """Base class for standalone floating ImGui windows (manual lifecycle)."""

    def __init__(self, title: str, is_open: bool = True, flags: int = 0):
        self.title: str = title
        self.is_open: bool = is_open
        self.flags: int = flags

    def render(self) -> None:
        if not self.is_open:
            return

        expanded, self.is_open = imgui.begin(self.title, self.is_open, self.flags)
        if expanded:
            try:
                self.draw()
            finally:
                imgui.end()
        else:
            imgui.end()

    @abstractmethod
    def draw(self) -> None:
        pass


class DockableComponent(ABC):
    """Base class for panels integrated directly into HelloImGui's Docking Workspace."""

    def __init__(self, title: str, default_dock_space: str = "MainDockSpace", is_open: bool = True):
        self.title: str = title
        self.default_dock_space: str = default_dock_space
        self.is_open: bool = is_open

    def to_dockable_window(self) -> hello_imgui.DockableWindow:
        window = hello_imgui.DockableWindow()
        window.label = self.title
        window.dock_space_name = self.default_dock_space
        window.gui_function = self.draw
        window.is_visible = self.is_open
        return window

    @abstractmethod
    def draw(self) -> None:
        pass


# =========================================================================
# 3. THEME & STYLE MANAGER
# =========================================================================
class ThemeManager:
    """Manages application palette, presets, and padding tweaks."""

    @staticmethod
    def apply_theme(
        preset: hello_imgui.ImGuiTheme_ = hello_imgui.ImGuiTheme_.material_flat,
        rounding: float = 6.0,
    ) -> None:
        hello_imgui.imgui_default_settings.setup_default_imgui_style()

        tweaked = hello_imgui.ImGuiTweakedTheme()
        tweaked.theme = preset
        tweaked.tweaks.rounding = rounding
        hello_imgui.apply_tweaked_theme(tweaked)

        style = imgui.get_style()
        style.window_padding = imgui.ImVec2(10.0, 10.0)
        style.frame_padding = imgui.ImVec2(8.0, 5.0)
        style.item_spacing = imgui.ImVec2(8.0, 6.0)
        style.scrollbar_size = 14.0
        style.grab_rounding = 4.0
        style.frame_rounding = 4.0
        style.popup_rounding = 6.0


# =========================================================================
# 4. CONCRETE APPLICATION COMPONENTS
# =========================================================================
class ControlPanel(DockableComponent):
    """Sidebar component holding application input controls."""

    def __init__(self, logger_callback: Callable[[str], None]):
        super().__init__(title="Control Settings", default_dock_space="SidebarSpace")
        self.logger_callback = logger_callback

        # State persistent to this panel instance
        self.user_name: str = "Developer"
        self.simulation_speed: float = 1.0
        self.mode_index: int = 0
        self.modes: List[str] = ["Interactive", "Automated", "Diagnostic"]
        self.feature_enabled: bool = True
        self.accent_color: List[float] = [0.2, 0.6, 1.0, 1.0]

    def draw(self) -> None:
        imgui.text_disabled("USER PARAMETERS")
        imgui.separator()

        with UIContext.item_width(-1):
            changed, self.user_name = imgui.input_text("##Username", self.user_name)
            if changed:
                self.logger_callback(f"User changed name to: {self.user_name}")

        _, self.mode_index = imgui.combo("Operation Mode", self.mode_index, self.modes)

        imgui.spacer(imgui.ImVec2(0, 10))
        imgui.text_disabled("EXECUTION")
        imgui.separator()

        _, self.simulation_speed = imgui.slider_float("Speed Ratio", self.simulation_speed, 0.1, 5.0)
        _, self.feature_enabled = imgui.checkbox("Enable Processing", self.feature_enabled)

        imgui.spacer(imgui.ImVec2(0, 10))
        _, self.accent_color = imgui.color_edit4("Theme Accent", self.accent_color)

        imgui.spacer(imgui.ImVec2(0, 15))
        with UIContext.disabled(not self.feature_enabled):
            if imgui.button("Trigger Processing Step", imgui.ImVec2(-1, 35)):
                self.logger_callback(
                    f"Executed [{self.modes[self.mode_index]}] step at speed x{self.simulation_speed:.2f}"
                )


class WorkspacePanel(DockableComponent):
    """Main panel displaying output statistics and canvas graphics."""

    def __init__(self, control_panel: ControlPanel):
        super().__init__(title="Main Canvas Workspace", default_dock_space="MainDockSpace")
        self.control_panel = control_panel

    def draw(self) -> None:
        imgui.text_colored(
            imgui.ImVec4(*self.control_panel.accent_color),
            f"Active Workspace Mode: {self.control_panel.modes[self.control_panel.mode_index]}",
        )
        imgui.text(f"Target User: {self.control_panel.user_name}")
        imgui.separator()

        imgui.spacer(imgui.ImVec2(0, 10))
        
        # Simple Custom ImGui Draw List Box
        draw_list = imgui.get_window_draw_list()
        pos = imgui.get_cursor_screen_pos()
        canvas_size = (imgui.get_content_region_avail().x, 150.0)

        # Background Box
        bg_col = imgui.get_color_u32(imgui.ImGuiCol_.frame_bg)
        border_col = imgui.get_color_u32(imgui.ImGuiCol_.border)
        draw_list.add_rect_filled(pos, imgui.ImVec2(pos.x + canvas_size[0], pos.y + canvas_size[1]), bg_col, 6.0)
        draw_list.add_rect(pos, imgui.ImVec2(pos.x + canvas_size[0], pos.y + canvas_size[1]), border_col, 6.0)

        # Pulsing circle visualization
        t = time.time() * self.control_panel.simulation_speed
        radius = 20.0 + (10.0 if self.control_panel.feature_enabled else 0.0)
        cx = pos.x + 40 + (t * 60 % (canvas_size[0] - 80))
        cy = pos.y + canvas_size[1] / 2.0

        circle_col = imgui.color_convert_float4_to_u32(imgui.ImVec4(*self.control_panel.accent_color))
        draw_list.add_circle_filled(imgui.ImVec2(cx, cy), radius, circle_col)
        draw_list.add_circle(imgui.ImVec2(cx, cy), radius + 5, border_col, 0, 2.0)

        # Advance cursor past canvas
        imgui.dummy(imgui.ImVec2(canvas_size[0], canvas_size[1]))


class ConsoleLoggerPanel(DockableComponent):
    """Console logging panel at the bottom workspace."""

    def __init__(self):
        super().__init__(title="Event Log Console", default_dock_space="ConsoleSpace")
        self.logs: List[str] = []
        self.auto_scroll: bool = True
        self.log("Console initialized.")

    def log(self, message: str) -> None:
        timestamp = time.strftime("%H:%M:%S")
        self.logs.append(f"[{timestamp}] {message}")

    def draw(self) -> None:
        if imgui.button("Clear Log"):
            self.logs.clear()

        imgui.same_line()
        _, self.auto_scroll = imgui.checkbox("Auto-scroll", self.auto_scroll)

        imgui.separator()

        with UIContext.child("LogRegion"):
            for line in self.logs:
                if "[INFO]" in line or "Executed" in line:
                    imgui.text_colored(imgui.ImVec4(0.4, 0.9, 0.4, 1.0), line)
                else:
                    imgui.text_unformatted(line)

            if self.auto_scroll and imgui.get_scroll_y() >= imgui.get_scroll_max_y():
                imgui.set_scroll_here_y(1.0)


# =========================================================================
# 5. APPLICATION DOCKING BUILDER & RUNNER
# =========================================================================
class Application:
    """Main Application orchestrator wiring components, layout, and runner."""

    def __init__(self):
        self.runner_params = hello_imgui.RunnerParams()

        # Instantiate components
        self.console = ConsoleLoggerPanel()
        self.control_panel = ControlPanel(logger_callback=self.console.log)
        self.workspace_panel = WorkspacePanel(control_panel=self.control_panel)

        self.dockable_components: List[DockableComponent] = [
            self.control_panel,
            self.workspace_panel,
            self.console,
        ]

        self._setup_window_config()
        self._setup_layout_and_docking()
        self._setup_menus_and_status()

    def _setup_window_config(self) -> None:
        self.runner_params.app_window_params.window_title = "ImGui Bundle Modular Architecture"
        self.runner_params.app_window_params.window_geometry.size = (1280, 800)

        # Attach Theme Manager Callback
        self.runner_params.callbacks.setup_imgui_style = lambda: ThemeManager.apply_theme(
            preset=hello_imgui.ImGuiTheme_.material_flat, rounding=6.0
        )

    def _setup_layout_and_docking(self) -> None:
        self.runner_params.imgui_window_params.default_layout_params.layout_condition = (
            hello_imgui.DockingLayoutCondition.first_use_ever
        )

        # 1. Left Sidebar Split (25% width)
        split_sidebar = hello_imgui.DockingSplit()
        split_sidebar.initial_dock_space = "MainDockSpace"
        split_sidebar.new_dock_space = "SidebarSpace"
        split_sidebar.direction = imgui.Dir_.left
        split_sidebar.ratio = 0.25

        # 2. Bottom Console Split (30% height)
        split_console = hello_imgui.DockingSplit()
        split_console.initial_dock_space = "MainDockSpace"
        split_console.new_dock_space = "ConsoleSpace"
        split_console.direction = imgui.Dir_.down
        split_console.ratio = 0.30

        self.runner_params.docking_params.docking_splits = [split_sidebar, split_console]
        self.runner_params.docking_params.dockable_windows = [
            comp.to_dockable_window() for comp in self.dockable_components
        ]

    def _setup_menus_and_status(self) -> None:
        self.runner_params.imgui_window_params.show_menu_bar = True
        self.runner_params.imgui_window_params.show_status_bar = True

        self.runner_params.callbacks.show_menus = self._render_top_menu_bar
        self.runner_params.callbacks.show_status_bar = self._render_status_bar

    def _render_top_menu_bar(self) -> None:
        if imgui.begin_menu("File"):
            if imgui.menu_item("Clear Console Logs")[0]:
                self.console.logs.clear()
            imgui.separator()
            if imgui.menu_item("Exit")[0]:
                self.runner_params.app_shall_exit = True
            imgui.end_menu()

        if imgui.begin_menu("View"):
            for comp in self.dockable_components:
                _, comp.is_open = imgui.menu_item(comp.title, "", comp.is_open)
            imgui.end_menu()

    def _render_status_bar(self) -> None:
        fps = imgui.get_io().framerate
        imgui.text(f"FPS: {fps:.1f}")
        imgui.same_line()
        imgui.text(" | ")
        imgui.same_line()
        imgui.text(f"Panels Active: {sum(1 for c in self.dockable_components if c.is_open)}")

    def run(self) -> None:
        hello_imgui.run(self.runner_params)


if __name__ == "__main__":
    app = Application()
    app.run()
