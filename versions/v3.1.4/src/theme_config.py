"""Design tokens for the Payroll Processor UI.

One token set per appearance. Everything that paints - ttk styles, plain Tk
widgets and matplotlib figures - reads its colours from here, so light and
dark stay consistent and a single edit repaints the whole app.
"""

from dataclasses import dataclass
from typing import Tuple


# Series colours are shared by every chart so a given metric keeps the same
# hue wherever it appears. Both sets are ordered blue, orange, green, red,
# purple, teal, gold, grey.
LIGHT_SERIES: Tuple[str, ...] = (
    "#2F6FEB",
    "#E8833A",
    "#1F8A4C",
    "#C0392B",
    "#7C5CD6",
    "#0E9AA7",
    "#B08A2E",
    "#6B7280",
)

DARK_SERIES: Tuple[str, ...] = (
    "#6BA1FF",
    "#F0A35E",
    "#5FD48B",
    "#F07C72",
    "#A98CF0",
    "#35C2CE",
    "#D8B44A",
    "#9AA1AE",
)


@dataclass(frozen=True)
class ThemeTokens:
    bg: str
    surface: str
    text_primary: str
    text_secondary: str
    border: str
    font_base: str
    # Actions
    accent: str = "#2F6FEB"
    accent_active: str = "#2558C0"
    accent_text: str = "#FFFFFF"
    danger: str = "#C0392B"
    danger_active: str = "#9E2E22"
    danger_text: str = "#FFFFFF"
    # Semantic status
    positive: str = "#1F8A4C"
    negative: str = "#C0392B"
    muted: str = "#6B7280"
    warning: str = "#B26B00"
    # Inputs and selection
    field_bg: str = "#FFFFFF"
    selection: str = "#E4EDFD"
    hover: str = "#EDF1F7"
    # Charts
    chart_bg: str = "#FFFFFF"
    chart_grid: str = "#E4E6EB"
    chart_series: Tuple[str, ...] = LIGHT_SERIES
    # Heat-maps and sequential scales
    chart_colormap: str = "YlOrRd"
    # True for the dark appearance. Widgets that cannot read a style - plain
    # Tk widgets, matplotlib - branch on this.
    dark: bool = False


LIGHT_BG = "#F7F7F9"
DARK_BG = "#1E1F24"


def get_theme_tokens(is_dark: bool) -> ThemeTokens:
    if is_dark:
        return ThemeTokens(
            bg=DARK_BG,
            surface="#2A2C31",
            text_primary="#F2F2F2",
            text_secondary="#B9BCC6",
            border="#3A3D45",
            font_base="SF Pro Text",
            accent="#4C8DFF",
            accent_active="#6BA1FF",
            accent_text="#10131A",
            danger="#E5645A",
            danger_active="#F0837A",
            danger_text="#17191D",
            positive="#4ADE80",
            negative="#F87171",
            muted="#9AA1AE",
            warning="#E0A73B",
            field_bg="#22242A",
            selection="#33507A",
            hover="#33363D",
            chart_bg="#2A2C31",
            chart_grid="#3A3D45",
            chart_series=DARK_SERIES,
            chart_colormap="magma",
            dark=True,
        )
    return ThemeTokens(
        bg=LIGHT_BG,
        surface="#FFFFFF",
        text_primary="#1B1C1E",
        text_secondary="#5C5F66",
        border="#D7D9DE",
        font_base="SF Pro Text",
        chart_series=LIGHT_SERIES,
    )
