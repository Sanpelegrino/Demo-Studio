# Contributing to Demo Studio

## Getting started

1. Clone the repo and run `install.bat` (Windows) or `./install.sh` (Mac/Linux).
2. See the [Setup Guide](docs/SETUP_GUIDE.md) for token and troubleshooting details.

## Making changes

- Work on a feature branch off `master`.
- Keep commits focused — one logical change per commit.
- Test your changes locally before pushing (launch the app, verify the feature works).

## Code style

- Python: follow existing patterns in the codebase (FastAPI, psycopg, no ORM).
- CSS: use the custom properties defined in `:root` in `static/styles.css`. No new colors without justification.
- JavaScript: vanilla JS, no frameworks. Keep it in `static/app.js`.
- Batch/Bash: match the structure of the existing install and start scripts.

## Pull requests

- Keep the PR title short and descriptive.
- Describe what changed and why in the body.
- If the change affects setup or the user workflow, update the relevant guide in `docs/`.
