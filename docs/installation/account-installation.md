# Account-scoped installation

Run `install.sh` (POSIX) or `install.ps1` (Windows) from this checkout. Installer performs `pip install -e .` into `~/.forge/installs/forge-doctor-api/.venv`, outside project workspaces.

Published variables use prefix `FORGE_DOCTOR_API`: `HOME`, `INSTALL_ROOT`, `VENV`, `PYTHON`, `CLI`, and `LAUNCHER`. Underscores are canonical because POSIX shells reject hyphens. Windows also receives aliases such as `FORGE-DOCTOR-API-HOME`, without administrator permission.

POSIX installer writes `~/.config/forjas/env.sh`; open a new shell or run `source ~/.config/forjas/env.sh`. Windows processes opened after installation receive HKCU variables. Under Windows Git Bash, `install.sh` writes both HKCU variables and this Bash environment file; reload with `source ~/.config/forjas/env.sh`.

`setup.sh`/`setup.ps1` remains compatibility mode. The Forge doctor and Portal validate runtime paths while never reading credentials.
