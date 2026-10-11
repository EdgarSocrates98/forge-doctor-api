"""forge-doctor-api vendored Forge UI Kit — stdlib-only interactive terminal layer.

Zero dependencies, cross-platform (msvcrt on Windows, termios on
POSIX). Every interaction has a headless equivalent so automation never
blocks on a TTY that isn't there.
"""

from forge_doctor_api.ui.i18n import t
from forge_doctor_api.ui.kit import (
    UIContext,
    confirm,
    dashboard,
    multi_select,
    prompt,
    select,
    status_table,
)

__all__ = [
    "UIContext",
    "confirm",
    "dashboard",
    "multi_select",
    "prompt",
    "select",
    "status_table",
    "t",
]
