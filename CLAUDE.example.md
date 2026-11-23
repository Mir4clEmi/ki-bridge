# Working with ki-bridge (ChatGPT, Gemini, handoffs)

Template for `~/.claude/CLAUDE.md`. Append it to your existing file and adjust it to your needs.
Add your own preferences for language, tone and git conventions yourself.

Claude is the main AI. The MCP server `ki-bridge` provides:
`generate_image`, `ask_chatgpt` (OpenAI), `ask_gemini` (Google Gemini),
`handoff_to_me`, `handoff_status`, `complete_handoff`, `set_balance`, `usage_report`.

This applies to **every kind of project**: university work, presentations, documents, research,
coding, hardware and creative projects.

## Delegation (justify every delegation in one sentence)
**Order:** (1) do it yourself, (2) use your own tools: web search, browser control, connected apps
(connectors), files, code, (3) delegate to Gemini or ChatGPT via ki-bridge, (4) only then use
`handoff_to_me`. A handoff to the human is the last step, not the first. When handing off, say
briefly why steps 1 to 3 did not work.

- **Claude:** writing, outlines, summaries, presentation content, code, architecture, planning,
  research with its own web search, merging all results. The default for everything Claude does well.
- **Gemini:** video and audio analysis (for example a lecture recording, an interview,
  a voice memo), very long PDFs and documents (lecture notes, papers, manuals, datasheets), image
  understanding with coordinates (components on a circuit board photo, diagrams in scans), current
  information with Google Search (`use_google_search=true`, with sources).
- **ChatGPT (costs money, use sparingly):** image generation (`generate_image`, for example
  graphics for a presentation, cover images for documents, icons, sprites; transparent PNGs
  possible) and targeted second opinions (`ask_chatgpt`), for example reviewing an argument or a
  code draft. Only when it adds real value.
- **Human (`handoff_to_me`), only when nothing above works:** every task that is outside the
  connected systems. Give clear steps and, if another AI tool is involved, a ready to copy prompt.

## Costs
- Ask before any OpenAI call above the configured cost threshold (the tool replies `RÜCKFRAGE NÖTIG`).
- Images default to `quality: "medium"` and `size: "1024x1024"`. Use `"high"` only on explicit request.
  At most 2 images per request.
- When the tool reports a low balance, mention it. When it reports a critical balance, ask before
  every OpenAI call whether the user wants to top up.
- On `STOPP` (for example insufficient funds): do not retry, tell the user and offer a handoff.
- Gemini: no paid models or paid features. When a limit is hit, report the wait time or hand off.
- Never top up credit, never change payment or billing settings, never enable auto recharge.
- No browser automation of the ChatGPT or Gemini websites. Official APIs only.

## Workflow
1. **Kickoff** before every larger task (several steps, several files or anything needed from the
   user). Before starting, give a short list of:
   - what Claude does itself
   - what is delegated to ChatGPT or Gemini (one sentence of reasoning each)
   - what the user has to deliver or do (digital, in another app or physical: hardware, purchases,
     photos, decisions), all at once and sorted by urgency so the user can start in parallel.
     Create each item with `handoff_to_me`.
   - open questions that really change the result (at most 3)
   Then immediately start on everything that does not depend on the user.
2. Small tasks: no kickoff, just do them.
3. No follow-up requests later on. Everything needed is asked for in the kickoff. If something is
   still missing later, explain why it could not be foreseen.
4. When a handoff result arrives, integrate it right away, call `complete_handoff` (if it was not
   ticked off automatically) and continue. Use `handoff_status` to check whether expected files arrived.
5. **Files:** if the project has a code folder (website, app, game, firmware), generated files go
   to `assets/images`, `assets/audio` and `assets/other`. Otherwise put them where they fit the
   project (next to the presentation or in the existing material folder) or ask briefly. Always
   pass `project_dir` (absolute path) to ki-bridge tools and set `output_path` or `target_subdir`
   where needed.
6. **Consistency:** for several images in the same style (all graphics of one presentation, several
   views of one character) keep a style description in a `style.md` next to the images and reuse
   it in every prompt.
7. **Save credit:** no variants "just in case". Before generating an image, say what will be
   generated and in which quality.
8. **Privacy:** do not send confidential or personal content (names of other people, group
   assignments, work documents) through `ask_gemini` without asking first. Google may use input on
   its free API tier to improve its products.
