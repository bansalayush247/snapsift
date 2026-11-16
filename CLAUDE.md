# Snapsift: instructions for the agent

This repo sorts a camera roll (or several Google accounts' Takeout exports) into folders, finds duplicates across accounts, junk and private photos, trips and events, and shows it all on a local dashboard. The person you're helping has probably never used Claude Code or a terminal. Do the technical work yourself, keep messages short, and use plain words ("folder", not "directory").

## Ground rules (never break these)

1. **Never move, rename, change or delete the user's original photos yourself.** The tool only reads them and makes sorted copies. The one exception is the dashboard's **Clean up → Move to Trash**, which the person confirms with the exact count; don't run `trash_dupes.py --confirm` for them unless they explicitly ask in chat and have seen the `--list` numbers.
2. **Ask before anything that costs money or leaves the computer:** Jev (billed per file: run `label_jev.py --estimate` first), Google Photos upload, Apple Photos import, naming trips with Claude.
3. **Keep their photos private.** Never commit anything in `dashboard/data/`, `dashboard/peek/`, `work/`, `config/`, `secrets/` or `.env`. Never paste photo names, captions, locations or account emails into anything outside this computer.
4. Never weaken the Claude lockdown in `common.ask_claude` (only Read, only inside a private temp folder outside the repo, no MCP, no user settings). Photos can contain text written to manipulate a model.
5. One question at a time, with numbered options they can answer with a number.

## When someone gives you this repo's link (the usual case)

They pasted something like "set up https://github.com/bansalayush247/snapsift". Do this without asking:

1. **Download it.** If you're not already inside this repo: `git clone https://github.com/bansalayush247/snapsift.git ~/snapsift` (if that folder exists, `git -C ~/snapsift pull` instead), then work from that folder.
2. **Set up.** Run `./setup.sh`. If Python is missing, ask them to run `xcode-select --install` and wait. If ffmpeg is missing and `brew` exists, offer `brew install ffmpeg` (videos get grey previews and there are no highlight videos without it).
3. **Open the dashboard.** Run `./start.sh` in the background (it keeps running and opens http://127.0.0.1:8765). The `claude` command is found on PATH or inside the VS Code / Cursor extension.
4. **Tell them, in about three lines:**
   - The dashboard is open in their browser.
   - Click **Choose folder** and pick their photos (a Google Takeout or Apple Photos export, or any folder; for several Google accounts, one subfolder per account), pick where the sorted copies go, then **Start sorting**.
   - To open it again later: double-click `Open Snapsift.command` in `~/snapsift`, or ask you to "open Snapsift".
5. Stay available. Answer questions from `dashboard/data/` (inventory, labels, meta, dupes, events, report) and the server's `/api/state`.

If they don't have an export yet:
- **Google Photos:** takeout.google.com, select only Google Photos, download, unzip into one folder. Several accounts: one export per account, each in its own subfolder of one parent folder.
- **iPhone / Apple Photos:** in Photos on the Mac, select all, File > Export > Export Unmodified Originals, into a new folder.
Never read `Photos Library.photoslibrary` directly.

## What the dashboard does by itself

**Start sorting** runs, with live progress and a time estimate: scan (only new files on later runs), duplicates, Claude labels (+ a closer look at unsure ones), trips & events, build folders, report. After sorting the tools bar has Search, Accounts, Clean up, Trips & events, Map, Highlights, Upload and Privacy.

## If they'd rather do it in this chat

| Step | Command |
|---|---|
| Scan | `.venv/bin/python scripts/scan.py "<photos folder>" [--accounts] [--limit 200]` |
| Duplicates | `.venv/bin/python scripts/dupes.py` (check `work/duplicates.jpg`) |
| Sample sheets | `.venv/bin/python scripts/sheets.py --sample` (look at `work/sample/` to suggest folders) |
| Labels (Claude) | `.venv/bin/python scripts/label_claude.py` (`CLAUDE_MODEL=haiku`, `sonnet` or `opus`) |
| Labels (Jev, paid) | `.venv/bin/python scripts/label_jev.py --estimate`, then without `--estimate` |
| Trips & events | `.venv/bin/python scripts/events.py [--name]` |
| Build folders | `.venv/bin/python scripts/apply.py "<output folder>"` |
| Report + delete lists | `.venv/bin/python scripts/report.py` |
| Highlights | `.venv/bin/python scripts/highlights.py [--year 2024] [--local]` |
| Google Photos | `.venv/bin/python scripts/upload_google.py --status`, `--login`, then `[--strip-location]` |
| Apple Photos | `.venv/bin/python scripts/export_apple.py --dry-run`, then without |
| Duplicates to Trash | `.venv/bin/python scripts/trash_dupes.py --list`, then `--confirm N` (see rule 1) |

The open dashboard refreshes itself when these run. Options (model, layout year/month, fix_dates, albums, second_look) live in `dashboard/data/source.json` under `options`; the main account under `main_account`.

**Choosing folders.** Their folders live in `config/categories.json` (copied from the `categories.json` template on first run) (`key`, `kind` photo or video, `label`, `emoji`, `rule`). The `rule` is what the model reads. Offer: 1) the standard folders, 2) folders you suggest after looking at `work/sample/`, or 3) their own list. Keep at least one photo and one video folder, and make the last folder of each kind a catch-all.

## If something breaks

- Port 8765 busy: `PORT=8766 ./start.sh`.
- "claude command not found": install Claude Code, or set `SNAPSIFT_CLAUDE=/path/to/claude`.
- A batch failed: press Start sorting again. Finished batches are kept.
- HEIC photos fail to open: `.venv/bin/pip install -U pillow-heif`.
- Google "access blocked": add their Gmail as a test user on the OAuth consent screen.
- macOS blocked Photos/Finder: System Settings > Privacy & Security > Automation.
- Tests: `.venv/bin/python -m unittest discover -s tests` (drawn fake library, fake Claude, fake Google; never touches their library).
