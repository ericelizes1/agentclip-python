---
name: agentclip
description: Capture a narrated clip of your work — a walkthrough, how-to guide, or bug repro the user can share as a URL. Use after driving a browser through a feature you shipped, a flow you want to teach, or a bug you reproduced. Triggers on "show me what happened", "make a clip", "share a run", "demo this", "walk through this", "how do I X", "repro the bug visually". Output is a shareable URL that plays as a narrated video and falls back to a slide-by-slide scroll.
---

# agentclip

You drove a browser. The user wants the artifact. This skill turns the run into a shareable URL — a narrated walkthrough that plays as a video by default and falls back to a slide-by-slide scroll. Four tools do the work: `slideshow_create`, `slideshow_add_slide`, `slideshow_update_slide`, `slideshow_set_summary`.

The tools work without this skill. **The artifact is only as good as the captions and structure you give it.** Read on.

## When this skill applies

Run this skill when the user asks for visual evidence of a browser-driven task. Triggers fall into three shapes:

- **Walkthrough** — "show what shipped", "demo this", "make a clip", "share a run", "walk through this"
- **Guide** — "how do I X", "show me how to Y", "tutorial for Z", "first time user trying X"
- **Bug** — "repro the bug", "show what's broken", "evidence of the issue"

Skip the skill when:

- The task is code-only with no observable browser surface
- The user explicitly asked only for a written report
- You captured fewer than two distinct states (a one-slide clip isn't worth a URL)

If skipping, summarize the run in chat — just don't create a clip.

## Browser tooling — pick a method before Step 0

Capturing screenshots is the agent's responsibility. The slideshow tools accept a `media_path`, but **this skill does not provide the browser**. Decide how you'll capture before you start clicking — and never use OS-level screen capture, which leaks unrelated windows to a public URL.

### Method priority (high to low)

1. **agentclip-mcp `browser_*` tools** — preferred. The agentclip MCP server (run with `agentclip-mcp` or registered in your IDE's MCP config) ships viewport-only browser primitives: `browser_open`, `browser_navigate`, `browser_type`, `browser_click`, `browser_press_key`, `browser_wait_for_text`, `browser_screenshot` (returns a disk path), `browser_get_text`, `browser_close`. These use Playwright under the hood with a fixed viewport, so screenshots are *structurally* tab-scoped — they can never include the OS desktop, IDE window, or other tabs. `browser_screenshot` writes a PNG to disk and returns the path; you pass that path straight into `slideshow_add_slide`. Requires `pip install 'agentclip[browser]' && playwright install chromium`. **This is the canonical path.**
2. **Other browser MCP tools** (e.g., `mcp__claude-in-chrome__*`, Playwright MCP, Puppeteer MCP) — fine if agentclip-mcp's browser tools aren't available. These also capture the tab only, not the OS screen. The challenge is getting the screenshot to disk for `agentclip slideshow add`. See "Saving MCP screenshots to disk" below.
3. **Your own scripted Playwright / Puppeteer** — fine. Use a fixed viewport (e.g., 1440×900 or 1280×720) and write screenshots straight to disk.

### Anti-pattern: OS screen capture

Never use `screencapture` (macOS), `scrot` (Linux), `gnome-screenshot`, PowerShell `Get-Screenshot`, `screencapture -x`, or any tool that captures the OS screen. They grab everything visible — including the IDE, the terminal showing the user's chat with the agent, system notifications, and any other open windows. Uploading those PNGs to a public share URL leaks the user's environment to anyone with the link. **This is a privacy bug, not a stylistic one.**

If only OS screen capture is available, stop and tell the user: *"Real screenshots would require a browser-driving tool. Recommending `pip install agentclip[browser]` to enable viewport-only capture."* Do not proceed.

### Saving MCP screenshots to disk

Most browser MCPs return screenshots in-memory and don't expose a disk path. To get them to disk for `agentclip slideshow add`, the typical recipe is:

1. Capture the viewport via the MCP tool (e.g., `mcp__claude-in-chrome__computer` with `action=screenshot`).
2. Use the MCP's javascript-execution tool to encode the captured image as a base64 data URL — most browser MCPs expose `chrome.tabs.captureVisibleTab` or an equivalent that returns a data URL directly.
3. Decode to a PNG via Bash:
   ```
   echo "iVBORw0KGgo..." | base64 -d > /tmp/clip-01.png
   ```

The exact recipe varies per MCP. If your MCP exposes a `save_to_disk` parameter on screenshots, use that — but verify it actually returns a usable path (some MCPs document it but no-op).

### Detect what's available before Step 0

Before any clicking, confirm at least one method is usable. Check in priority order:

1. **agentclip-mcp browser tools** — look for `browser_open` / `browser_screenshot` etc. in your tool list. If present, use them. (To enable: `pip install 'agentclip[browser]'`, then register the `agentclip-mcp` server in your IDE's MCP config; restart the session.)
2. **Other browser MCPs** — look for `mcp__*chrome*`, `mcp__*playwright*`, `mcp__*puppeteer*` in your tool list.
3. **Local Playwright** — `python -c "from playwright.sync_api import sync_playwright" 2>/dev/null && echo "playwright available"`.

If none are available, install `agentclip[browser]` or stop and tell the user. **Do not fall back to OS screen capture.**

### Worked example: the canonical agentclip-mcp flow

```
browser_open(url="https://v0.app", viewport_width=1440, viewport_height=900)
  -> {"session_id": "a1b2c3d4e5f6", "title": "v0 by Vercel", ...}

browser_screenshot(session_id="a1b2c3d4e5f6")
  -> {"path": "/tmp/agentclip-shots/a1b2c3d4e5f6-1715215200000.png", "bytes": 142031}

slideshow_add_slide(slideshow_id="ss_xyz",
                    media_path="/tmp/agentclip-shots/a1b2c3d4e5f6-1715215200000.png",
                    caption="...")
```

That's the entire bytes-to-disk problem solved: `browser_screenshot` writes the file, returns the path, and `slideshow_add_slide` reads it. No base64 dance, no custom Python script, no leaked desktop.

## Step 0: Pick the spine and run type before you click

A clip is a story, not a flipbook. Before clicking, answer two questions.

**1. What's the spine?** What is the one thing the viewer should walk away knowing?

**2. What kind of clip is this?** Pick from the trigger phrasing — you almost never need to ask. Pass `--type <value>` to `agentclip slideshow create` (or `run_type` via the SDK).

| User said something like… | `run_type` | Voice |
|---|---|---|
| "demo", "walkthrough", "show this off", "what shipped" | `walkthrough` | shimmer |
| "how do I X", "tutorial", "show me how to Y" | `guide` | nova |
| "repro", "reproduce", "bug", "what's broken" | `bug` | onyx |

If the trigger is too ambiguous to pick (rare — usually the verb gives it away), ask once: *"Quick check: is this a walkthrough of something you built, a how-to guide, or a bug repro? It changes the narration voice."* Don't pause for confirmation again.

The same voice runs the whole clip — intro, every caption, and outro all share one voice so the listener hears one consistent presenter.

| Run type | Spine |
|---|---|
| `walkthrough` | The feature — establish what it does, show it working, land the value |
| `guide` | The procedure — first step → next step → result |
| `bug` | The bug — establish, reproduce, prove |

If you can't name the spine, ask the user before clicking. A clip without a spine is filler.

## Step 1: Create the clip at the start, not the end

Call `slideshow_create` **before** you take screenshots. Two reasons:

- The returned `slideshow_id` is what every `slideshow_add_slide` call needs. Creating up front means you add slides as you go instead of buffering them.
- Writing the title + description forces you to commit to a spine. Both fields are read aloud in the rendered video — `description` becomes the spoken intro, so write it like the first thing a presenter would actually say.

**Title:** noun phrase. *"Cursor 3 Agents Window — three agents, one PR."* *"Login regression repro."* *"How to enable prompt caching in Aider."* Not a sentence, not a question.

**Description = the spoken intro.** It's read aloud over the title card before any slide plays. The viewer has zero context yet — write it as **complete sentences with subjects and verbs**, not telegraphic bullets. Two to four short sentences is the right length.

Real openers from real product introductions (the shape to imitate):

- *"Introducing Agent 4 — our fastest, most versatile Agent yet. It's built around a simple idea: you should spend your time creating, not coordinating."* (Replit)
- *"This release introduces a new PR review experience, faster execution on plans through parallel agents, and new quick-action pills."* (Cursor)

Per run type:

- **walkthrough** — *"This is Cursor 3's new Agents Window. With one slash command, three agents work on the same task in parallel. You pick the winning version — the PR opens right inside the editor."*
- **guide** — *"Here's how to enable prompt caching in Aider — a sixty-second guide. Three lines of metadata in your model config. Anthropic Sonnet drops to a tenth of the cost on cached reads."*
- **bug** — *"Repro of the rate-limit 503 on signup. Three steps. The trace points at a missing Redis key."*

Banned openers — these read as "AI demo" the moment you hear them:

- *"Welcome to..."* / *"Today we'll be looking at..."* / *"I'm excited to show you..."* / *"In this walkthrough..."* / *"Without further ado..."*

The MP4 starts where the action is, not in the green room.

**`run_type`:** pass the value you picked in Step 0. Drives the narration voice + pacing.

## Step 2: Take screenshots only at meaningful moments

In priority order — when in doubt, capture the higher tier first:

1. **Errors and surprises.** Console errors, 500 pages, broken layouts, unexpected redirects. Highest-value slides. Never skip one.
2. **State transitions a viewer would care about.** Form submitted → email-verification screen. Modal opened. Result rendered. Navigation completed.
3. **Pre-assertion states.** The page right before you check whether something works. Lets the caption read "expected X, saw Y."
4. **Flow inflection points.** "Now testing settings" / "Switched to mobile viewport." Keeps multi-act runs cohesive.

Do **not** screenshot:

- Every click. Intermediate states between meaningful results are noise.
- Pure scrolling or unchanged states.
- Loading spinners or skeletons. Wait for the loaded state.
- The same state twice — use `slideshow_update_slide` instead.

Target ratio: roughly **one slide per minute** of agent run time. Walkthrough/guide: 5–8 slides. Bug repro: 3–5 slides.

## Step 3: Write captions in the right voice for the run type

A bug repro and a feature walkthrough are not the same artifact. **Caption style depends on the `run_type` you picked.** Get this wrong and the clip sounds either like a stack-trace dump (when it shouldn't) or like a corporate webinar (please no).

**Universal rule across all types:** captions are required. The API rejects empty captions with a 400. A slide without spoken context is broken output.

**Banned across all types** — these read as "AI demo" the moment you hear them:

- *"I'm excited to show you today..."* / *"Welcome to this walkthrough"* / *"Today we'll be diving into..."* — corporate-presenter cringe.
- *"I am now clicking..."* / *"Let me navigate to..."* — narrating yourself instead of the app.
- *"Screenshot of homepage"* / *"Page"* / *"Loading"* — redundant with the screenshot, or empty.
- *"Seamless"*, *"robust"*, *"leverage"*, *"powerful"*, *"intuitive"* — buzzword filler.
- **Verbless fragments stacked together.** *"Slash-command spawn three agents — pick the winner, ship the PR"* doesn't parse out loud. Add the subject and verb. The skill writes for SPOKEN output.
- Long run-on sentences with multiple em-dashes. The listener can't re-read; break into two short sentences.

### Per-run-type caption style

#### `walkthrough` — presenter, present-tense, complete sentences

Voice: someone showing the working feature to a friend who roughly knows what it does. Skip introductions. Each caption uses **complete sentences** with subject + verb. Land each slide on the *interesting* detail, not the obvious one.

Good:

```
Same editor, new center pane. The Agents Window replaces the chat panel that used to live here.

Type one slash command and three agents start working on the same task. Each one runs in its own branch, in parallel.

When two agents finish, you get a word-by-word diff. Differences are highlighted; matching parts collapse out of the way.
```

Bad (verbless, telegraphic, jargon):

```
Cursor 3 — same editor, new center pane.
Slash-command spawn three agents — each in its own worktree, parallel.
Diff is word-level. Highlights differences, collapses matches.
```

The good version is the one that scans when read aloud.

#### `guide` — instructional, second-person, step-by-step

Voice: someone walking another person through a procedure. Use "you" — instructions are *for* the viewer. Each step lands on what to click + what happens next.

Good:

```
Open your model config — for Aider that's `aider/models.py`. Find the OpenRouter Sonnet entry.

Add three keys: `cache_creation_input_token_cost`, `cache_read_input_token_cost`, and `supports_assistant_prefill`. Plug in the numbers from Anthropic's pricing page.

Run any prompt twice. The second call should show a `cache_read` count in the response — proof the cache is hot.
```

Bad (vague, hand-wavy):

```
You'll want to update the config.
There are some keys to add for caching.
Try it out and see if it works.
```

The good version is concrete enough to follow without alt-tabbing.

#### `bug` — terse, factual, stack-trace-adjacent

Voice: a senior engineer narrating a repro to another senior engineer. No setup. No closure. Just facts. Past tense is fine here — you're recapping what happened.

Good:

```
Cleared cookies. Cold-loaded /signup.
Submitted with valid data. Got 503 from /api/auth/signup.
Stack trace pointed at a missing rate-limit Redis key.
```

Bad (speculative, padded, hedged):

```
Tried signing up — looks like maybe something went wrong with the rate limiting?
The error seems to indicate that something is missing somewhere.
```

The good version reads like a triage note. The bad one reads like Slack while panicking.

### Universal narration tips (apply to every type)

- **Write for the ear, not the eye.** Captions are read aloud by TTS. Re-read each one in your head; if you stumble, rewrite.
- **Use complete sentences as the spine.** Fragments for emphasis are fine *occasionally*. Stacking them is what makes captions stop sounding like English.
- **Em-dashes give the TTS a natural pause beat.** Use them where a presenter would breathe — not as comma replacements.
- **No jargon the listener can't catch on first pass.** Readers can re-skim; listeners can't. *"Worktree"* trips a non-git listener. *"Cache_control"* trips anyone outside Anthropic's docs.
- **When a slide captures an error or surprise, say so plainly.** *"Got a 500 from /api/teams — stack trace mentioned a missing tenant_id."* Buried bugs are useless bugs.

`media_path` accepts PNG / JPEG / GIF / WebP for stills, MP4 / WebM / MOV for short clips. Use a clip when motion **is** the story (janky animation, race condition only visible in recording, fluid demo of a flow). Cap clips at a few seconds; upload limit is 25 MB.

## Step 4: Fix slides in place — don't pile on corrections

If a slide has a typo, a wrong caption, or a screenshot that didn't capture what you meant, fix it with `slideshow_update_slide`. **Do not append a "correction" slide.**

If a slide should not exist at all, leave it for now and call it out in the summary. v1 has no `delete_slide`; honesty in the summary is the right move, not a fake "redacted" slide.

## Step 5: Set the summary — the spoken outro

`slideshow_set_summary` is the TL;DR. **Under 80 words.** It's read aloud as the spoken outro on the rendered video AND shown as a callout box on the share page.

Per run type:

- **walkthrough** — one-sentence wrap that lands the value, not a recap. *"Three agents, three branches, one PR. Cursor 3's Agents Window turns the old back-and-forth chat into a side-by-side comparison."* Not *"In conclusion, we have demonstrated..."* — the listener was just there, don't recap.
- **guide** — confirms the result + the verification step. *"Three lines of model metadata. The cache_read count in your next response confirms it's working — and your bill on the cached path drops by an order of magnitude."*
- **bug** — outcome + slide reference. *"Bug confirmed at slide 2. /api/auth/signup returns 503 instead of either succeeding or rate-limit-error."*

Structure (regardless of type):

1. **One sentence on outcome** — what happened, what works, what's the verdict.
2. **Counts or specifics** — a number, a named thing, the actual change you noticed.
3. **For `bug` only:** one line per real bug, with the slide number.

No praise, no hedging, no apologies. No *"as we have seen"*. The summary is read by someone with 10 seconds. Make those seconds count.

## Step 6: Hand off the URL

The `slideshow_create` response includes a few URLs. They are **different**:

- **`share_url`** — public. Paste it into Slack, iMessage, Discord, a recruiter message. The page renders the narrated walkthrough as a video by default with a Slides toggle. Link unfurls show inline video automatically.
- **`clip_mp4_url`** — public, ends in `.mp4`. Use this in **GitHub PR descriptions, READMEs, and any Markdown surface that only renders inline video for direct video files.** Pasting `share_url` in a GitHub PR shows a bare link; pasting `clip_mp4_url` shows an inline `<video>` element.
- **`clip_pdf_url`** — public, downloadable branded walkthrough. Useful for attaching to a Jira ticket or a client email when video isn't an option.
- **`embed_url`** — public iframe target. The `share_url` page exposes a "Copy embed code" button that wraps this in `<iframe>` HTML for Notion, Substack, blog posts.
- **`edit_url`** — **private**. It's the only credential that authorizes caption fixes later. Mention it exists; do not include it inline unless asked. **Treat it like a password.**

The MP4 and PDF render lazily on first external fetch and are pre-warmed when you call `slideshow_set_summary` (Step 5). The render task auto-narrates any slides without audio before stitching, so captions go in, narrated video comes out. You don't need to call any render or narrate command.

If the user mentions sharing externally and they haven't run `agentclip whoami`, suggest it **once**. Their name and URL become the creator credit on every clip from then on. Skip the suggestion for casual internal use.

## Tool reference

| Tool | When | Required args |
|---|---|---|
| `slideshow_create` | Once, at the start (Step 1) | `title`, `description`, `run_type` |
| `slideshow_add_slide` | After each meaningful state (Step 2) | `slideshow_id`, `media_path`, `caption` |
| `slideshow_update_slide` | To fix in place (Step 4) | `slideshow_id`, `slide_position`, what's changing |
| `slideshow_set_summary` | Once, near the end (Step 5) | `slideshow_id`, `summary` |

The tools persist your `write_token` locally. After `slideshow_create` returns, you only need the `slideshow_id`.

## Anti-patterns

- **Corporate-presenter cringe.** *"I'm excited to show you today..."*, *"Welcome to..."*, *"Today we'll be diving into..."*. The MP4 starts where the action is. Cut every word that doesn't earn its place.
- **Verbless fragments stacked together.** *"Slash-command spawn three agents — pick the winner, ship the PR"* doesn't parse out loud. Add subjects and verbs. The skill is for SPOKEN output.
- **Narrating yourself instead of the app.** *"I will now navigate to the login page."* The viewer doesn't care about you driving the mouse. Describe the app's response.
- **Court-reporter past tense in a walkthrough.** *"The user clicked. The form was submitted. The application then displayed..."* Walkthroughs are present-tense.
- **Buzzword filler.** *"seamless"*, *"robust"*, *"leverage"*, *"powerful"*, *"intuitive"*, *"best-in-class"*. If marketing wrote the caption, the demo is dead.
- **As-we-can-see-isms.** *"As we can see"*, *"observe how"*, *"notice that"*, *"in conclusion"*. The viewer is *literally watching*. Don't tell them to look.
- **Filler slides.** *"Loading…"* is not a slide. Wait for the loaded state.
- **Terminal screenshots.** If you ran a CLI command, paste the output in the caption. Terminal shots break the browser narrative.
- **Mixing flows in one clip.** Signup and checkout are two clips. The user reorders context per audience.
- **Skipping the summary.** Without it, the clip has no spoken outro. With it, it's a deliverable.
- **Asking before every slide.** Don't. Take the screenshots, write the captions, set the summary, hand over the URL.
- **Faking it.** If you can't actually drive the browser (no MCP browser tool, no Playwright, no Chromium available in your runtime), say so explicitly: *"Real evidence would require a browser-driving tool. Recommending [the user runs it themselves / a different surface]."* Never invent screenshots.
- **OS-level screen capture.** Never use `screencapture` (macOS), `scrot`, `gnome-screenshot`, or any tool that captures the OS screen. They include IDE windows, terminal panes, and the user's chat with the agent — all of which leak to a public URL when the clip ships. Use viewport-only capture: `agentclip[browser]` (Playwright), a browser MCP, or scripted Playwright/Puppeteer with a controlled viewport. See "Browser tooling" near the top of this skill.

## Worked example — walkthrough

User: *"Make a clip of the new project-create flow."*

```python
slideshow_create(
    title="Project-create flow on AgentClip",
    description="This is the new project-create flow. Three fields, inline validation, a clean redirect on success — about thirty seconds end to end.",
    run_type="walkthrough",
)
# returns slideshow_id="ss_abc123"

slideshow_add_slide(
    slideshow_id="ss_abc123",
    media_path="/tmp/01-empty-projects.png",
    caption="A fresh account with no projects yet. The 'New Project' button is the only obvious next step.",
)

slideshow_add_slide(
    slideshow_id="ss_abc123",
    media_path="/tmp/02-form-open.png",
    caption="Three fields with sensible defaults — visibility starts at private, which feels right.",
)

slideshow_add_slide(
    slideshow_id="ss_abc123",
    media_path="/tmp/03-empty-submit.png",
    caption="Submit empty and you get a clean inline error, no page reload.",
)

slideshow_add_slide(
    slideshow_id="ss_abc123",
    media_path="/tmp/04-success.png",
    caption="Submit valid and you land on the project page — ready to share.",
)

slideshow_set_summary(
    slideshow_id="ss_abc123",
    summary="Three fields, one error state, one success path. The whole flow takes under thirty seconds for a new user.",
)
```

## Worked example — bug

Same screenshots, totally different copy — the run_type changes the voice (onyx instead of shimmer) and the captions read like a triage note, not a presenter.

```python
slideshow_create(
    title="Project-create redirect bug on staging",
    description="Repro of the post-create redirect bug. The success path lands at /projects/undefined.",
    run_type="bug",
)

slideshow_add_slide(
    slideshow_id="ss_xyz",
    media_path="/tmp/01-empty-projects.png",
    caption="Logged in as a brand-new account. Projects list is empty as expected.",
)

slideshow_add_slide(
    slideshow_id="ss_xyz",
    media_path="/tmp/04-success.png",
    caption="Created a project named 'Test 1'. Success toast fired, but the redirect went to /projects/undefined instead of /projects/<id>. Response payload appears to be missing the 'id' field.",
)

slideshow_set_summary(
    slideshow_id="ss_xyz",
    summary="Bug confirmed at slide 2. POST /projects returns 200 but the response body omits the id field, so the client redirect lands at /projects/undefined.",
)
```

The user gets one share URL. They paste it into Slack, a Linear ticket, a PR description, a cold message. **The URL is the artifact. The captions are what makes it worth opening.**
