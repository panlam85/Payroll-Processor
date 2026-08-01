from dataclasses import dataclass


@dataclass(frozen=True)
class ThemeTokens:
    bg: str
    surface: str
    text_primary: str
    text_secondary: str
    border: str
    font_base: str


def get_theme_tokens(is_dark: bool) -> ThemeTokens:
    if is_dark:
        return ThemeTokens(
            bg="#1E1F24",
            surface="#2A2C31",
            text_primary="#F2F2F2",
            text_secondary="#B9BCC6",
            border="#3A3D45",
            font_base="SF Pro Text",
        )
    return ThemeTokens(
        bg="#F7F7F9",
        surface="#FFFFFF",
        text_primary="#1B1C1E",
        text_secondary="#5C5F66",
        border="#D7D9DE",
        font_base="SF Pro Text",
    )
