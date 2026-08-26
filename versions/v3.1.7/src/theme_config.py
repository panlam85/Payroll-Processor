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
    "#167D9A",
    "#D88A24",
    "#2C9B72",
    "#C0392B",
    "#7C5CD6",
    "#0E9AA7",
    "#B08A2E",
    "#6B7280",
)

DARK_SERIES: Tuple[str, ...] = (
    "#4CB3C8",
    "#F0B35F",
    "#61C69E",
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
    font_display: str = "SF Pro Display"
    font_mono: str = "SF Mono"
    sidebar_bg: str = "#14232D"
    sidebar_text: str = "#F3F8FA"
    sidebar_muted: str = "#91A6B2"
    sidebar_hover: str = "#203642"
    surface_raised: str = "#E9EFF2"
    accent_soft: str = "#DCEEF2"
    # Actions
    accent: str = "#167D9A"
    accent_active: str = "#11677F"
    accent_text: str = "#FFFFFF"
    danger: str = "#C0392B"
    danger_active: str = "#9E2E22"
    danger_text: str = "#FFFFFF"
    # Semantic status
    positive: str = "#2C9B72"
    negative: str = "#C0392B"
    muted: str = "#6B7280"
    warning: str = "#D88A24"
    # Inputs and selection
    field_bg: str = "#FFFFFF"
    selection: str = "#DDEFF4"
    hover: str = "#EAF2F5"
    # Charts
    chart_bg: str = "#FFFFFF"
    chart_grid: str = "#E4E6EB"
    chart_series: Tuple[str, ...] = LIGHT_SERIES
    # Heat-maps and sequential scales
    chart_colormap: str = "YlOrRd"
    # True for the dark appearance. Widgets that cannot read a style - plain
    # Tk widgets, matplotlib - branch on this.
    dark: bool = False


LIGHT_BG = "#F3F6F8"
DARK_BG = "#101B22"


def get_theme_tokens(is_dark: bool) -> ThemeTokens:
    if is_dark:
        return ThemeTokens(
            bg=DARK_BG,
            surface="#18262F",
            text_primary="#F2F7F8",
            text_secondary="#A9BBC4",
            border="#2E414C",
            font_base="SF Pro Text",
            sidebar_bg="#0B151B",
            sidebar_text="#F2F7F8",
            sidebar_muted="#8197A2",
            sidebar_hover="#152832",
            surface_raised="#20333E",
            accent_soft="#173D49",
            accent="#4CB3C8",
            accent_active="#70CADB",
            accent_text="#07151A",
            danger="#E5645A",
            danger_active="#F0837A",
            danger_text="#17191D",
            positive="#61C69E",
            negative="#F87171",
            muted="#9AA1AE",
            warning="#F0B35F",
            field_bg="#122029",
            selection="#244D5A",
            hover="#20333E",
            chart_bg="#18262F",
            chart_grid="#2E414C",
            chart_series=DARK_SERIES,
            chart_colormap="magma",
            dark=True,
        )
    return ThemeTokens(
        bg=LIGHT_BG,
        surface="#FFFFFF",
        text_primary="#14232D",
        text_secondary="#52636E",
        border="#D8E1E7",
        font_base="SF Pro Text",
        chart_series=LIGHT_SERIES,
    )
