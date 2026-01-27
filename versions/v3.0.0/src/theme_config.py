"""Centralized theme configuration for Payroll Processor UI."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ThemeTokens:
    bg: str
    surface: str
    border: str
    text_primary: str
    text_secondary: str
    accent: str
    font_base: str = "Avenir Next"


def get_theme_tokens(is_dark: bool) -> ThemeTokens:
    if is_dark:
        return ThemeTokens(
            bg="#1f1f1f",
            surface="#2a2a2a",
            border="#3a3a3a",
            text_primary="#f2f2f2",
            text_secondary="#c9c9c9",
            accent="#4c8bf5",
        )
    return ThemeTokens(
        bg="#f5f5f0",
        surface="#ffffff",
        border="#d6d6d0",
        text_primary="#1a1a1a",
        text_secondary="#666666",
        accent="#1f6feb",
    )
