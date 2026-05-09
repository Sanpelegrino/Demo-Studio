# Demo Studio — Setup Guide

## What you need

The install script handles Python, PostgreSQL, and all dependencies automatically. You only need one thing:

**Your Bedrock gateway bearer token.**

### How to get your token

**Already have Claude Code installed?** Your token is in your Claude Code settings file:

- **Mac/Linux:** `~/.claude/settings.json`
- **Windows:** `C:\Users\<you>\.claude\settings.json`

Open the file and copy the value of `ANTHROPIC_AUTH_TOKEN` from the `env` section.

**Don't have a token yet?** Follow the provisioning steps in this Slack canvas:
https://salesforce.enterprise.slack.com/docs/T5J4Q04QG/F0AU8DXM71R

---

## Install

Open a terminal in the Demo Studio folder and run the install script for your platform:

**Windows (Command Prompt or PowerShell):**
```
install.bat
```

**Mac/Linux (Terminal):**
```bash
chmod +x install.sh
./install.sh
```

The script will:

1. Detect or install **Python 3.12** (via winget on Windows, Homebrew on Mac).
2. Detect or install **PostgreSQL 16/17**.
3. Start the PostgreSQL service.
4. Create the `demo_studio` database and user.
5. Create a Python virtual environment and install all dependencies.
6. Prompt you for your **bearer token** and write it to `.env`.
7. Launch the app and open your browser to http://localhost:3777.

When the browser opens, you're ready to go.

---

## Subsequent launches

After the first install, use the start script — it skips setup and just launches the server:

**Windows:**
```
start.bat
```

**Mac/Linux:**
```bash
./start.sh
```

---

## Next steps: Tableau extensions

If you're using Tableau Desktop, Demo Studio includes two dashboard extensions that connect Tableau directly to your workspace:

- **Live Refresh** — automatically refreshes your data sources when you reshape data.
- **Live Chat** — embeds the chat interface inside a Tableau dashboard so analysts can make changes without leaving Tableau.

See the **Tableau Extensions** section in the [User Guide](USER_GUIDE.md) for setup instructions. The extension files are `static/live-refresh.trex` and `static/live-chat.trex` in the Demo Studio folder.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| **"winget not found"** (Windows) | Install "App Installer" from the Microsoft Store, then re-run `install.bat`. |
| **"Python not found on PATH after install"** (Windows) | Close the terminal, open a new one, and re-run `install.bat`. Windows needs a new terminal to pick up PATH changes. |
| **PostgreSQL won't start** | Windows: open Services (`services.msc`), find `postgresql-x64-17`, and start it manually. Mac: run `brew services start postgresql@16`. |
| **"Cannot authenticate to PostgreSQL as postgres"** | The script tries common default passwords (empty, "postgres", "password"). If yours is different, enter it when prompted. If you don't know your postgres password, check the `pg_hba.conf` file or reinstall PostgreSQL. |
| **pip install fails** | Delete the `.venv` folder and re-run the install script. This recreates the virtual environment from scratch. |
| **Port 3777 already in use** | Another instance is running. Close it, or find the process: Windows: `netstat -ano | findstr 3777`, Mac: `lsof -i :3777`. |
| **Chat returns an error on first message** | Check that your bearer token is correct in `.env`. The `ANTHROPIC_AUTH_TOKEN` value should start with `sk-`. |
| **"Homebrew not found"** (Mac) | Install Homebrew first: https://brew.sh — then re-run `./install.sh`. |
