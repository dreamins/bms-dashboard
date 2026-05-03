class Theme:
    BACKGROUND = "#020617"
    CARD_BG = "#0f172a"
    TEXT_PRIMARY = "#f8fafc"
    TEXT_SECONDARY = "#94a3b8"
    CYAN_NEON = "#22d3ee"
    ERROR_RED = "#ef4444"
    SUCCESS_GREEN = "#10b981"
    WARNING_AMBER = "#f59e0b"
    CELL_LOW = "#ef4444"
    CELL_MID = "#f59e0b"
    CELL_HIGH = "#10b981"

def get_soc_color(soc: float) -> str:
    if soc < 20: return Theme.ERROR_RED
    if soc < 50: return Theme.WARNING_AMBER
    return Theme.SUCCESS_GREEN

def generate_cell_svg(voltage: float, ghost: bool, imbalance: bool, label: str = "") -> str:
    if ghost:
        return (
            f'<svg viewBox="0 0 60 32" xmlns="http://www.w3.org/2000/svg" class="w-full" style="opacity:0.15">'
            f'<rect x="1" y="1" width="58" height="30" rx="4" fill="{Theme.CARD_BG}" stroke="#1e293b" stroke-width="1"/>'
            f'</svg>'
        )
    bg = "rgba(239,68,68,0.12)" if imbalance else "rgba(16,185,129,0.08)"
    border = "rgba(239,68,68,0.5)" if imbalance else "rgba(16,185,129,0.2)"
    text_color = Theme.CELL_LOW if imbalance else Theme.TEXT_PRIMARY
    lbl = (
        f'<text x="30" y="13" font-family="Inter,monospace" font-size="6" font-weight="700"'
        f' fill="#475569" text-anchor="middle">{label}</text>'
    ) if label else ''
    return (
        f'<svg viewBox="0 0 60 32" xmlns="http://www.w3.org/2000/svg" class="w-full">'
        f'<rect x="1" y="1" width="58" height="30" rx="4" fill="{bg}" stroke="{border}" stroke-width="1"/>'
        f'{lbl}'
        f'<text x="30" y="25" font-family="Inter,monospace" font-size="9" font-weight="900"'
        f' fill="{text_color}" text-anchor="middle">{voltage:.3f}V</text>'
        f'</svg>'
    )
