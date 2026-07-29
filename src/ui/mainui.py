"""
CustomTkinter Modular Desktop Framework
Includes: Sidebar Navigation, Responsive Layout, View Controller, 
KPI Metric Cards, Form Controls, Log Console, and Dynamic Themes.
"""

import time
from typing import Callable, List, Optional
import customtkinter as ctk

# Set initial visual themes
ctk.set_appearance_mode("Dark")  # Modes: "System", "Dark", "Light"
ctk.set_default_color_theme("blue")  # Themes: "blue", "green", "dark-blue"


# =========================================================================
# 1. REUSABLE UI COMPONENTS
# =========================================================================
class MetricCard(ctk.CTkFrame):
    """Card widget displaying key metrics/KPIs."""

    def __init__(self, master, title: str, value: str, subtext: str = "", **kwargs):
        super().__init__(master, corner_radius=10, **kwargs)

        self.grid_columnconfigure(0, weight=1)

        self.lbl_title = ctk.CTkLabel(
            self, text=title.upper(), font=ctk.CTkFont(size=11, weight="bold"), text_color="gray"
        )
        self.lbl_title.grid(row=0, column=0, padx=15, pady=(12, 2), sticky="w")

        self.lbl_val = ctk.CTkLabel(
            self, text=value, font=ctk.CTkFont(size=24, weight="bold")
        )
        self.lbl_val.grid(row=1, column=0, padx=15, pady=(0, 2), sticky="w")

        if subtext:
            self.lbl_sub = ctk.CTkLabel(
                self, text=subtext, font=ctk.CTkFont(size=11), text_color="#10B981"
            )
            self.lbl_sub.grid(row=2, column=0, padx=15, pady=(0, 12), sticky="w")

    def update_value(self, new_value: str, subtext: str = ""):
        self.lbl_val.configure(text=new_value)
        if subtext and hasattr(self, "lbl_sub"):
            self.lbl_sub.configure(text=subtext)


class LogConsole(ctk.CTkFrame):
    """Embedded logging console widget with clear and auto-scroll functionality."""

    def __init__(self, master, **kwargs):
        super().__init__(master, corner_radius=10, **kwargs)

        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # Header Bar
        self.header_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.header_frame.grid(row=0, column=0, padx=10, pady=(8, 4), sticky="ew")

        self.lbl_title = ctk.CTkLabel(
            self.header_frame, text="System Log Console", font=ctk.CTkFont(weight="bold")
        )
        self.lbl_title.pack(side="left")

        self.btn_clear = ctk.CTkButton(
            self.header_frame, text="Clear", width=60, height=24, command=self.clear
        )
        self.btn_clear.pack(side="right")

        # Text Output Area
        self.textbox = ctk.CTkTextbox(self, font=ctk.CTkFont(family="Consolas", size=12), wrap="none")
        self.textbox.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="nsew")
        self.textbox.configure(state="disabled")

    def log(self, message: str, level: str = "INFO"):
        self.textbox.configure(state="normal")
        timestamp = time.strftime("%H:%M:%S")
        formatted = f"[{timestamp}] [{level}] {message}\n"
        self.textbox.insert("end", formatted)
        self.textbox.see("end")
        self.textbox.configure(state="disabled")

    def clear(self):
        self.textbox.configure(state="normal")
        self.textbox.delete("1.0", "end")
        self.textbox.configure(state="disabled")


# =========================================================================
# 2. APPLICATION VIEWS (PAGES)
# =========================================================================
class DashboardView(ctk.CTkFrame):
    """Main Dashboard view showing summary statistics and operational controls."""

    def __init__(self, master, logger_cb: Callable[[str, str], None], **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.logger_cb = logger_cb

        self.grid_columnconfigure((0, 1, 2), weight=1)
        self.grid_rowconfigure(2, weight=1)

        # 1. Top Metrics Section
        self.card1 = MetricCard(self, title="Active Tasks", value="24", subtext="+12% from yesterday")
        self.card1.grid(row=0, column=0, padx=(0, 10), pady=(0, 15), sticky="ew")

        self.card2 = MetricCard(self, title="CPU Load", value="38.4%", subtext="Normal range")
        self.card2.grid(row=0, column=1, padx=5, pady=(0, 15), sticky="ew")

        self.card3 = MetricCard(self, title="System Health", value="99.8%", subtext="All services operational")
        self.card3.grid(row=0, column=2, padx=(10, 0), pady=(0, 15), sticky="ew")

        # 2. Control Panel Section
        self.controls_group = ctk.CTkFrame(self, corner_radius=10)
        self.controls_group.grid(row=1, column=0, columnspan=3, pady=(0, 15), sticky="ew")
        self.controls_group.grid_columnconfigure((0, 1), weight=1)

        # Slider
        self.lbl_slider = ctk.CTkLabel(
            self.controls_group, text="Processing Speed Multiplier:", font=ctk.CTkFont(weight="bold")
        )
        self.lbl_slider.grid(row=0, column=0, padx=15, pady=(12, 0), sticky="w")

        self.slider = ctk.CTkSlider(self.controls_group, from_=0.1, to=5.0, command=self._on_slider_change)
        self.slider.set(1.0)
        self.slider.grid(row=1, column=0, padx=15, pady=(5, 15), sticky="ew")

        # Dropdown & Buttons
        self.opt_mode = ctk.CTkOptionMenu(
            self.controls_group, values=["Standard Run", "Batch Export", "Diagnostic Sweep"]
        )
        self.opt_mode.grid(row=1, column=1, padx=15, pady=(5, 15), sticky="e")

        self.btn_run = ctk.CTkButton(
            self.controls_group, text="Execute Workload", command=self._on_execute
        )
        self.btn_run.grid(row=0, column=1, padx=15, pady=(12, 0), sticky="e")

        # 3. Log Console Section
        self.console = LogConsole(self)
        self.console.grid(row=2, column=0, columnspan=3, sticky="nsew")

    def _on_slider_change(self, val: float):
        self.card2.update_value(f"{val * 25:.1f}%")

    def _on_execute(self):
        selected_mode = self.opt_mode.get()
        speed = self.slider.get()
        msg = f"Triggered execution mode '{selected_mode}' at speed x{speed:.2f}"
        self.console.log(msg, level="ACTION")
        self.logger_cb(msg, "INFO")


class SettingsView(ctk.CTkFrame):
    """Settings Configuration view."""

    def __init__(self, master, **kwargs):
        super().__init__(master, corner_radius=10, **kwargs)

        self.grid_columnconfigure(1, weight=1)

        lbl_title = ctk.CTkLabel(self, text="Application Preferences", font=ctk.CTkFont(size=18, weight="bold"))
        lbl_title.grid(row=0, column=0, columnspan=2, padx=20, pady=20, sticky="w")

        # Setting 1: Server URL
        ctk.CTkLabel(self, text="API Endpoint:").grid(row=1, column=0, padx=20, pady=10, sticky="w")
        self.entry_url = ctk.CTkEntry(self, placeholder_text="https://api.example.com/v1")
        self.entry_url.grid(row=1, column=1, padx=20, pady=10, sticky="ew")

        # Setting 2: Auto-save switch
        ctk.CTkLabel(self, text="Auto-Save Logs:").grid(row=2, column=0, padx=20, pady=10, sticky="w")
        self.switch_autosave = ctk.CTkSwitch(self, text="Enabled")
        self.switch_autosave.grid(row=2, column=1, padx=20, pady=10, sticky="w")
        self.switch_autosave.select()


# =========================================================================
# 3. SIDEBAR NAVIGATION
# =========================================================================
class SidebarFrame(ctk.CTkFrame):
    """Sidebar navigation panel with mode toggles."""

    def __init__(self, master, nav_callback: Callable[[str], None], **kwargs):
        super().__init__(master, corner_radius=0, **kwargs)
        self.nav_callback = nav_callback

        self.grid_rowconfigure(4, weight=1)  # Spacer row

        # App Brand Title
        self.logo_label = ctk.CTkLabel(
            self, text="⚡ PySuite App", font=ctk.CTkFont(size=20, weight="bold")
        )
        self.logo_label.grid(row=0, column=0, padx=20, pady=(20, 30))

        # Navigation Buttons
        self.btn_dash = ctk.CTkButton(
            self, text="Dashboard", fg_color="transparent", text_color=("gray10", "gray90"),
            hover_color=("gray70", "gray30"), anchor="w", command=lambda: self._select_nav("Dashboard")
        )
        self.btn_dash.grid(row=1, column=0, padx=10, pady=5, sticky="ew")

        self.btn_settings = ctk.CTkButton(
            self, text="Settings", fg_color="transparent", text_color=("gray10", "gray90"),
            hover_color=("gray70", "gray30"), anchor="w", command=lambda: self._select_nav("Settings")
        )
        self.btn_settings.grid(row=2, column=0, padx=10, pady=5, sticky="ew")

        # Appearance / Theme Selectors at Bottom
        self.lbl_mode = ctk.CTkLabel(self, text="Appearance:", anchor="w")
        self.lbl_mode.grid(row=5, column=0, padx=20, pady=(10, 0), sticky="w")

        self.opt_appearance = ctk.CTkOptionMenu(
            self, values=["Dark", "Light", "System"], command=self._change_appearance_mode
        )
        self.opt_appearance.grid(row=6, column=0, padx=20, pady=(5, 20), sticky="ew")

    def _select_nav(self, name: str):
        self.nav_callback(name)

    def _change_appearance_mode(self, mode: str):
        ctk.set_appearance_mode(mode)


# =========================================================================
# 4. MAIN WINDOW ORCHESTRATOR
# =========================================================================
class App(ctk.CTk):
    """Main window coordinator managing layouts and active views."""

    def __init__(self):
        super().__init__()

        # Window Geometry & Configuration
        self.title("CustomTkinter Modular Application")
        self.geometry("1100 x 700")
        self.minsize(900, 600)

        # Layout Configuration (1x2 Grid: Sidebar on left, View on right)
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        # 1. Sidebar Component
        self.sidebar = SidebarFrame(self, nav_callback=self.show_view, width=200)
        self.sidebar.grid(row=0, column=0, sticky="nsew")

        # 2. Main Content Container
        self.view_container = ctk.CTkFrame(self, fg_color="transparent")
        self.view_container.grid(row=0, column=1, padx=20, pady=20, sticky="nsew")
        self.view_container.grid_rowconfigure(0, weight=1)
        self.view_container.grid_columnconfigure(0, weight=1)

        # 3. Instantiate Views
        self.views = {
            "Dashboard": DashboardView(self.view_container, logger_cb=self.global_log),
            "Settings": SettingsView(self.view_container),
        }

        # Show default view
        self.show_view("Dashboard")

    def show_view(self, name: str):
        """Switches the visible view frame."""
        for view_name, view_frame in self.views.items():
            if view_name == name:
                view_frame.grid(row=0, column=0, sticky="nsew")
            else:
                view_frame.grid_forget()

    def global_log(self, msg: str, level: str = "INFO"):
        """Central logging hook."""
        print(f"[{level}] {msg}")


if __name__ == "__main__":
    app = App()
    app.mainloop()
