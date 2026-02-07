# Docker Compose Fix on Windows (UpToWes v2)

## Goal
Make `docker compose` work on this host and remove `Access is denied` on `//./pipe/dockerDesktopLinuxEngine`.

## Terminal and prerequisites
- Terminal for all commands in this doc: `Windows PowerShell` (not WSL terminal).
- Project folder: `C:\Users\wesle\Desktop\uptowes_v2`.
- If you need DB commands from project scripts, activate venv first:
  - `.\.venv\Scripts\Activate.ps1`
  - `python -c "import sys; print(sys.executable)"`
  - Expected: path ending with `\.venv\Scripts\python.exe`

## Quick checklist (copy/paste in PowerShell)
Run these in order and compare expected outputs:

```powershell
docker version
docker info
docker context ls
docker compose version
docker compose ps
```

Expected:
- `docker version`: both `Client` and `Server` sections.
- `docker info`: no pipe permission error; shows `Operating System: Docker Desktop`.
- `docker context ls`: one context with `*` (usually `desktop-linux`).
- `docker compose version`: prints compose version.
- `docker compose ps`: table output (may be empty if services are down, but command must succeed).

## Decision tree for `Access is denied` on dockerDesktopLinuxEngine
If you see:
- `error during connect: ... open //./pipe/dockerDesktopLinuxEngine: Access is denied`

Follow this order:
1. Docker Desktop is not running:
   - Open Start menu, search `Docker Desktop`, click app.
   - Wait until status says `Engine running`.
2. Wrong container mode:
   - In Docker Desktop top-right menu, ensure Linux containers mode.
   - If you see `Switch to Linux containers...`, click it.
3. User not in `docker-users` group:
   - Open PowerShell as Admin and run:
   ```powershell
   net localgroup docker-users
   ```
   - If your username is not listed, add it:
   ```powershell
   net localgroup docker-users "$env:USERNAME" /add
   ```
   - Then `Sign out` and `Sign in` again (required).
4. WSL backend not healthy:
   - In Admin PowerShell:
   ```powershell
   wsl --shutdown
   ```
   - Quit Docker Desktop (system tray icon -> right click -> `Quit Docker Desktop`).
   - Open Docker Desktop again and wait for `Engine running`.
5. Context broken:
   - Run:
   ```powershell
   docker context ls
   docker context use desktop-linux
   ```
6. Still failing:
   - Docker Desktop -> `Troubleshoot` -> `Restart Docker Desktop`.
   - If still failing, `Troubleshoot` -> `Clean / Purge data` (warning: removes local images/containers/volumes).
   - Last resort: reinstall Docker Desktop.

## Non-dev-friendly step-by-step (click-by-click)

### 1) Open Docker Desktop
1. Press `Windows` key.
2. Type `Docker Desktop`.
3. Click `Docker Desktop`.
4. Wait until app shows `Engine running` (bottom left status).

If it keeps spinning for more than 2 minutes:
- Close app from system tray icon.
- Reopen it and wait again.

### 2) Confirm Linux containers mode
1. In Docker Desktop window, click top-right menu (profile/settings area).
2. If you see `Switch to Linux containers...`, click it and wait.
3. If you only see `Switch to Windows containers...`, you are already in Linux mode.

### 3) Open PowerShell as Administrator
1. Press `Windows` key.
2. Type `PowerShell`.
3. Right-click `Windows PowerShell`.
4. Click `Run as administrator`.
5. Click `Yes` in UAC prompt.

### 4) Verify docker-users group
Run:

```powershell
net localgroup docker-users
```

Expected:
- output contains your user name.

If user is missing, run:

```powershell
net localgroup docker-users "$env:USERNAME" /add
```

Then:
- Sign out Windows account.
- Sign back in.
- Reopen Docker Desktop.

### 5) Verify WSL integration in Docker Desktop
1. Open Docker Desktop.
2. Click gear icon `Settings`.
3. Click `General` and ensure `Use the WSL 2 based engine` is checked.
4. Click `Resources` -> `WSL Integration`.
5. Enable integration for your distro(s).
6. Click `Apply & Restart`.

### 6) Validate compose and DB service
In PowerShell (normal user is fine once permissions are fixed):

```powershell
cd C:\Users\wesle\Desktop\uptowes_v2
docker compose up -d db
docker compose ps
docker compose logs --tail 120 db
docker compose exec db sh -lc "psql -U \$POSTGRES_USER -d \$POSTGRES_DB -c 'select now();'"
```

Expected:
- `up -d db`: service starts without permission errors.
- `compose ps`: shows `db` with `Up`.
- `logs`: Postgres ready message.
- `exec ... psql`: one row with current timestamp.

### 7) If nothing works (reset/reinstall path)
1. Docker Desktop -> `Troubleshoot`.
2. Try `Restart Docker Desktop`.
3. If still broken, try `Clean / Purge data` (this removes local Docker data).
4. If still broken, uninstall Docker Desktop.
5. Reboot Windows.
6. Install latest Docker Desktop again.
7. Recheck `docker-users` group and WSL integration.

## Acceptance criteria
- `docker compose ps` works (no permission/pipe errors).
- `docker compose exec db ... psql ...` works and returns a query result.
