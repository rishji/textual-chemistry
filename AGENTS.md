# AGENTS.md

Codebase guidance for AI agents working in `/Users/rishi/Projects/vow-metrics`.

## Project Goal

Build a relationship analytics website for Rishi and Esha that turns iMessage
history, travel history, trips, photos, and manually supplied memories into a
polished story site.

The site should feel personal, editorial, and data-rich. The main safety
boundary is publication: do not expose raw private exports or unreviewed message
content in a public browser build. Local analysis is allowed when it supports
the project and stays on this machine.

## Current Phase

The project has moved past initial discovery. A first static prototype exists in
`site/`, backed by local iMessage analysis tools in `scripts/analyze-messages/`.

The next priority is improving the content layer before spending more time on
visual polish:

- Rename site title/copy from "Our Messages, Mapped" to something closer to
  "Our Messages in Data".
- Improve topic filtering, relationship-specific first mentions, snippet
  selection, terms of endearment, and emoji breakdowns.
- Add semantic filters for false positives such as `proposal` as proposing a
  plan, `ring` as phone ringing, `baby` as non-endearment, and other people's
  weddings.
- Generate richer story modules: message gaps/Vipassana, topic arcs,
  endearment evolution, wedding/proposal arc, travel/photo bursts, and
  conversation eras.
- Later: improve visual design, add a lightweight shared-password gate, and
  replace hand-curated `site/data.js` with generated publishable data.

## Repository Shape

```text
AGENTS.md
CLAUDE.md
data/
  private/                 # local message DB and generated private analysis
scripts/
  analyze-messages/
    imessage_analyzer.py   # local iMessage analysis CLI
    test_imessage_analyzer.py
site/
  index.html               # static prototype
  styles.css
  app.js
  data.js                  # currently hand-curated publishable-ish data
```

This directory is not currently a Git repository. Do not assume git commands
will work here.

## Data Handling

- `data/private/` may contain copied chat databases and generated private JSON.
  It is fine to use these files for local analysis when needed, but do not
  casually open large private outputs just for orientation.
- Do not publish raw exports, `chat.db`, attachments, or unreviewed message
  dumps to the website.
- Keep public/shareable data separate from raw inputs. Prefer `data/public/` or
  generated static data files only after the content has been reviewed.
- Do not send message text, contacts, attachments, or derived private datasets
  to external services without explicit approval for the exact data and purpose.
- Snippets in `site/data.js` are intentionally selected examples, not an
  automatic dump. Treat changes there as editorial choices.

## Local Analysis Commands

The analyzer is local-first and reads `data/private/messages/chat.db` by
default.

```sh
python3 scripts/analyze-messages/imessage_analyzer.py --month 2024-07
python3 scripts/analyze-messages/imessage_analyzer.py --month 2024-07 --include-text
python3 scripts/analyze-messages/imessage_analyzer.py --aggregate-monthly
python3 scripts/analyze-messages/imessage_analyzer.py --topic-snippets
```

Generated outputs currently go under `data/private/processed/`.

## Verification

Use focused checks after relevant changes:

```sh
python3 -m unittest scripts/analyze-messages/test_imessage_analyzer.py
python3 -m py_compile scripts/analyze-messages/imessage_analyzer.py scripts/analyze-messages/test_imessage_analyzer.py
node --check site/app.js
node --check site/data.js
```

For the static site, a simple local server is enough:

```sh
python3 -m http.server 5179 --directory site
```

## Agent Workflow

- Follow the workspace policy in `/Users/rishi/Projects/AGENTS.md` when present.
- Read this file before source files.
- Prefer targeted reads of `scripts/`, `site/`, and docs. Avoid opening
  `data/private/` unless the exact task needs it.
- Before writing changes, show the proposed changes and wait for confirmation.
- Keep edits scoped and list modified files after edits.
- When changing analyzer behavior, add or update tests first.
- When changing public content, distinguish derived aggregate facts from
  manually selected editorial snippets.

## Environment

No required environment variables yet.

Future integrations should distinguish between:

- local-only private analysis credentials or paths
- public website build-time configuration
- deployment secrets
