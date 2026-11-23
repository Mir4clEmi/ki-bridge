# ki-bridge

ki-bridge is a small local MCP server that lets Claude act as a main AI that hands work to
other AIs and to you. Claude keeps the overview and does most of the work itself. When another
model is clearly better at a part of the task, Claude delegates it. When a part cannot be done
by any of the connected systems, Claude turns it into a precise task for you and keeps working
on everything else in the meantime.

The problem it solves: using several AI tools side by side usually means copying prompts between
browser tabs, losing track of what is done and finding out halfway through a project that
something is still missing. ki-bridge gives that coordination to one assistant and makes the
human an explicit part of the workflow.

## The idea: clear roles

| Who | Role |
|---|---|
| **Claude** | Main AI. Planning, writing, code, structure and merging all results. Does everything it can do well itself. |
| **Gemini** | Analysis of video, audio and very long documents, image understanding with coordinates, answers grounded in Google Search. |
| **ChatGPT** | Image generation and targeted second opinions. |
| **You** | Tasks that are outside the connected systems. |

Delegation follows a fixed order. Claude first tries to do a task itself, then with its own tools
(web search, browser control, connected apps, files and code), then through Gemini or ChatGPT.
Only when none of that works does the task become a handoff to you. Every delegation comes with
a one sentence reason, so you can see why a task went where it went.

### Why the human is part of the system

Not every step of a real project can be done by an AI. Instead of pretending these steps do not
exist, ki-bridge treats them as normal tasks with a clear format:

- what exactly to do, in concrete steps
- where to do it (an app, a website or "offline")
- what to bring back (a file, text, a photo, a measurement or a confirmation)
- how urgent it is: does it block Claude now or only later
- if something has to be bought: exact name, quantity, rough price and where to get it
- if another AI tool is involved: a ready to copy prompt with the right settings

Every open task is written to a `handoffs.md` in the project and ticked off when it is done. If
the result is a file, ki-bridge watches your Downloads folder for up to 15 minutes. It only
reacts to new files of the expected type, renames them and moves them into the project. Other
files in the folder are never opened or changed.

## The kickoff

Before any larger task Claude gives a short kickoff:

- what Claude does itself
- what it delegates to Gemini or ChatGPT and why
- everything you need to deliver or do, all at once and sorted by urgency
- at most three open questions that would really change the result

The point is parallel work. If you learn on minute one what you need to provide, you can do that
while Claude writes the code or the text. Requests that trickle in one by one leave both sides
waiting. If something is still missing later, Claude has to explain why it could not be foreseen.

Small tasks skip the kickoff and are simply done.

## Cost control and privacy

- **Estimated cost tracking.** You can store your current OpenAI balance with `set_balance`.
  After every call the estimated cost is subtracted and logged locally in `state/usage_log.csv`.
- **Confirmation before expensive calls.** Any single OpenAI call above a configurable cost
  threshold is blocked until you approve it. Image quality and the number of images per request
  are limited by default.
- **Low balance warnings** at configurable thresholds.
- **Stop on insufficient funds.** If the API reports `insufficient_quota` or a similar error,
  the server stops all OpenAI calls without retrying, tells you and offers a handoff for the
  affected task. Calls resume after you update the balance.
- **No automatic top ups.** The server never adds credit or touches billing settings.
- **No paid Gemini usage.** Only models listed as free in `src/ki_bridge/gemini_tools.py` are
  used. When a model hits a limit, the server tries the next one and finally returns a wait time
  or a handoff instead of anything paid.
- **Confidential content.** Google may use input on its free API tier to improve its products.
  The suggested rules tell Claude not to send personal or confidential material to Gemini
  without asking you first.

All costs are estimates. Your provider dashboard is the source of truth.

## Tools

| Tool | What it does |
|---|---|
| `generate_image` | Creates images with the OpenAI Images API, optionally with a transparent background |
| `ask_chatgpt` | Asks an OpenAI model via the Responses API (a low cost model by default) |
| `ask_gemini` | Asks Gemini with optional files (images, PDF, audio, video) and Google Search |
| `handoff_to_me` | Creates a task for the human, writes it to `handoffs.md` and optionally watches Downloads |
| `handoff_status` | Shows open handoffs or waits for an expected file |
| `complete_handoff` | Ticks off a handoff |
| `set_balance` | Stores your current OpenAI balance and lifts a stop after insufficient funds |
| `usage_report` | Shows estimated balance, spending this month and what it was spent on |

Model names, thresholds and limits live in `src/ki_bridge/config.py` and can be overridden in
`state/config.json`. They were taken from the official OpenAI and Google documentation at the
time of writing. Check them again when you set this up.

## Setup on macOS

1. **Install uv** (Python package manager):
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```
2. **Clone the repository** and install dependencies:
   ```bash
   git clone https://github.com/Mir4clEmi/ki-bridge.git ~/ki-bridge && cd ~/ki-bridge && ~/.local/bin/uv sync
   ```
3. **Get API keys.**
   - Gemini: create a key in Google AI Studio (aistudio.google.com/apikey).
   - OpenAI: create a key at platform.openai.com/api-keys.
4. **Store the keys as environment variables.** Copy the two `export` lines from `.env.example`
   into `~/.zshenv` and insert your keys. This file is read by every zsh, including when the
   Claude desktop app starts the server. Then quit and restart Claude completely.
5. **Register the server in Claude Code** for all projects:
   ```bash
   claude mcp add --scope user ki-bridge -- /bin/zsh ~/ki-bridge/bin/ki-bridge
   ```
6. **Optional: Claude desktop app.** Add this to
   `~/Library/Application Support/Claude/claude_desktop_config.json` and keep existing entries.
   Replace `/Users/<you>` with your home folder, because the app does not expand `~`:
   ```json
   "mcpServers": {
     "ki-bridge": { "command": "/bin/zsh", "args": ["/Users/<you>/ki-bridge/bin/ki-bridge"] },
     "claude-code": { "command": "/bin/zsh", "args": ["/Users/<you>/ki-bridge/bin/claude-code", "mcp", "serve"] }
   }
   ```
   The second entry exposes Claude Code itself, so the desktop app can edit files and run
   commands. `bin/claude-code` uses an installed `claude` CLI or the one bundled with the app.
7. **Add the working rules.** Append `CLAUDE.example.md` to `~/.claude/CLAUDE.md`. For the
   desktop app paste the text from `DESKTOP_ANWEISUNGEN.example.md` into your profile preferences.
8. **Optional: set your balance.** Tell Claude your current OpenAI balance so it can track
   estimated costs and warn you in time.

Quick check without Claude:
```bash
cd ~/ki-bridge && ~/.local/bin/uv run python tools/mcp_client.py usage_report
```

**Update:** `cd ~/ki-bridge && git pull && ~/.local/bin/uv sync`

**Uninstall:** `claude mcp remove --scope user ki-bridge`, remove the entries from the desktop
config, delete the folder and remove the keys from `~/.zshenv`.

## Limitations

These are deliberate:

- **No browser automation of ChatGPT or Gemini.** Only the official APIs are used. Anything that
  would need the web apps becomes a handoff with a ready to copy prompt.
- **Tasks outside the connected systems go to the user.** ki-bridge does not try to cover
  everything. It hands those tasks over in a clear format and picks up the results.
- **No paid Gemini features.** Some features, such as Google Search grounding, may be unavailable
  depending on your API access. In that case Gemini answers without search and says so clearly.
- **Estimated costs only.** The balance is tracked locally from token usage and price tables. It
  does not read your real balance from OpenAI.
- **The download watcher runs inside the server process.** If Claude restarts during a handoff,
  the watch stops and you move the file yourself.
- **macOS first.** Paths and the launcher scripts are written for macOS with zsh.
- **German messages.** Tool descriptions and messages are currently in German. The control words
  `RÜCKFRAGE NÖTIG` (confirmation needed) and `STOPP` (stop) are part of the protocol between
  the server and Claude.

`tools/clean_sprite.py` is a small helper for transparent pixel art: image models often add a
soft half transparent glow. The script removes it, crops the image and scales it down without
smoothing.

## Examples from real use

_Coming soon._

## License

MIT, see [LICENSE](LICENSE).
