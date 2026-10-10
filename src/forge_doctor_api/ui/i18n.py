"""Minimal i18n for the UI kit — pt-BR default, en fallback.

Strings are keyed; a missing key falls back to English then to the key
itself (never a crash). ``FORGE_LANG`` or locale env decides.
"""

from __future__ import annotations

import locale
import os

_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "choose": "Choose",
        "continue": "Continue",
        "cancel": "Cancel",
        "back": "Back",
        "quit": "Quit",
        "yes": "yes",
        "no": "no",
        "confirm_q": "Continue?",
        "select_hint": "up/down or j/k + enter; q or esc to cancel",
        "toggle_hint": "space toggles, enter confirms; j/k moves",
        "install_scope_q": "Where do you want to install?",
        "install_profile_q": "Installation profile?",
        "install_hosts_q": "Configure AI hosts?",
        "install_components_q": "Optional components?",
        "review": "Review installation",
        "scope_project": "Current repository",
        "scope_workspace": "Entire workspace",
        "scope_user": "My user account",
        "profile_balanced": "Balanced (Recommended)",
        "profile_economy": "Economy",
        "profile_full": "Full",
        "env_detected": "Environment detected",
        "dry_run_banner": "plan only — nothing was written",
        "approved_banner": "changes applied",
        "need_decision": "required decision missing in non-interactive mode",
        "health": "Health",
        "status": "Status",
    },
    "pt": {
        "choose": "Escolha",
        "continue": "Continuar",
        "cancel": "Cancelar",
        "back": "Voltar",
        "quit": "Sair",
        "yes": "sim",
        "no": "não",
        "confirm_q": "Continuar?",
        "select_hint": "setas ou j/k + enter; q ou esc cancela",
        "toggle_hint": "espaço alterna, enter confirma; j/k move",
        "install_scope_q": "Onde instalar?",
        "install_profile_q": "Perfil de instalação?",
        "install_hosts_q": "Configurar hosts de IA?",
        "install_components_q": "Componentes opcionais?",
        "review": "Revisar instalação",
        "scope_project": "Repositório atual",
        "scope_workspace": "Workspace inteira",
        "scope_user": "Minha conta de usuário",
        "profile_balanced": "Balanced (Recomendado)",
        "profile_economy": "Economy",
        "profile_full": "Full",
        "env_detected": "Ambiente detectado",
        "dry_run_banner": "somente plano — nada foi escrito",
        "approved_banner": "alterações aplicadas",
        "need_decision": "decisão obrigatória ausente em modo não-interativo",
        "health": "Saúde",
        "status": "Status",
    },
}


def lang() -> str:
    explicit = os.environ.get("FORGE_LANG", "").lower()
    if explicit.startswith("pt"):
        return "pt"
    if explicit.startswith("en"):
        return "en"
    try:
        loc = (locale.getlocale()[0] or "").lower()
    except (ValueError, AttributeError):
        loc = ""
    return "pt" if loc.startswith("pt") else "en"


def t(key: str, language: str | None = None) -> str:
    language = language or lang()
    return _STRINGS.get(language, _STRINGS["en"]).get(key, _STRINGS["en"].get(key, key))
