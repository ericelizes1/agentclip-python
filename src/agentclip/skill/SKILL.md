---
name: agentclip
description: Create narrated, shareable AgentClip videos from browser-driven QA, demos, bug repros, and investigations. Use when the user asks to record or share visual evidence.
---

# agentclip

You drove a browser. The user wants the receipts. This skill turns the run into a shareable URL — a narrated walkthrough that plays as a video by default and offers a slide-by-slide scroll fallback. The built-in browser tools drive the page and capture media, then the slideshow tools publish the result.

The tools work without this skill. **The artifact is only as good as the captions and structure you give it.** Read on.

## Built-in tools (and what to do when they're missing)

AgentClip ships two parallel surfaces — MCP tools (preferred when present, the host invokes them directly) and a `agentclip` CLI (works everywhere, including when MCP isn't registered yet). They map 1:1; pick the path your environment supports and the rest of this skill applies the same.

**Drive the browser** (viewport-only — never captures the IDE/terminal/desktop):

| What you want | MCP tool | CLI equivalent |
|---|---|---|
| Launch Chromium at a URL | `browser_open(url, record_video=…)` | (use MCP — long-lived sessions don't have a CLI mirror yet) |
| Navigate / click / type / press-key / wait-for-text | `browser_navigate`, `browser_click`, `browser_type`, `browser_press_key`, `browser_wait_for_text` | (same as above) |
| One-shot viewport PNG from a URL | `browser_screenshot` (in-session) | `agentclip capture <url> --out <path>` (no session needed) |
| Record motion | `browser_open(record_video=True)` then `browser_stop_recording` | (motion needs MCP) |
| Close the session | `browser_close` | (same) |

**Publish the slideshow**:

| What you want | MCP tool | CLI equivalent |
|---|---|---|
| Create the clip up front | `slideshow_create(title, description, run_type)` | `agentclip slideshow create --title … -d … --type …` |
| Append a slide | `slideshow_add_slide(slideshow_id, media_path, caption)` | `agentclip slideshow add <id> <media_path> --caption …` |
| Fix a slide in place | `slideshow_update_slide(slideshow_id, slide_position, …)` | `agentclip slideshow update <id> <position> …` |
| Set the spoken outro | `slideshow_set_summary(slideshow_id, summary)` | `agentclip slideshow summary <id> "…"` |

If the MCP tools aren't visible in your tool list, the agentclip MCP server isn't registered yet — see **Step 0** below.

## Recording motion

Playwright requires recording to be enabled at session open time; you cannot start it mid-session. So:

1. `browser_open(url=…, record_video=True)` — recording starts here. Optional confirm with `browser_start_recording`.
2. Drive the flow normally.
3. `browser_stop_recording(session_id)` to finalize the WebM and return its `path`. After this, the session is closed; open a new one if you need to keep driving.
4. Pass the returned `path` straight to `slideshow_add_slide` (the API accepts WebM, MP4, MOV for motion slides; cap at 25 MB / a few seconds).

If you forgot `record_video=True` and find yourself needing motion, `browser_close` the session, re-open with the flag set, and re-drive. There is no in-session "start recording now" — that's a Playwright constraint, not an agentclip one.

## When this skill applies

Run this skill when the user asks for visual evidence of a browser-driven task. Triggers include:

- "QA this", "QA the X flow", "run a smoke on Y"
- "Show me what happened", "share a run", "post a clip", "make a clip"
- "Repro the bug" — finish by showing it
- "Demo this" / "walk through this" / "record this"
- The user is going to share the result externally (Slack, PR description, recruiter ping)

Skip the skill when:

- The task is code-only with no observable browser surface
- The user explicitly asked only for a written report
- You captured fewer than two distinct states (a one-slide clip isn't worth a URL)

If skipping, still summarize the run in chat — just don't create a clip.

## Step 0: Bootstrap — make sure the tools are actually there

Before the first clip on a fresh machine, verify the tools you're about to call exist. The common failure mode is "tools that look installed but aren't loaded yet" — `pip install agentclip` succeeds, but until first-run setup writes the MCP registration and the host restarts, `mcp__agentclip__*` tools are invisible.

Check the tool list. If `browser_open` / `slideshow_create` (or `mcp__agentclip__*` namespaced variants) are missing:

1. Run `agentclip setup` once — it writes the MCP registration to the host config and installs the bundled Chromium. Idempotent.
2. Tell the user: *"agentclip is installed and registered — restart this session and the tools will load."*
3. Don't keep trying random alternatives. The `agentclip` CLI still works in this same session for everything that doesn't need a long-lived browser session, including `agentclip capture <url> --out` for viewport-only screenshots. Use that path for the current turn if you can't restart.

**Do not fall through to `screencapture` (macOS), `scrot`, or any OS-level capture tool.** Those include the IDE, terminal panes, and any other open windows in the captured frame — and that frame becomes a public URL when the clip ships. Privacy-bug-not-stylistic.

## Step 1: Pick the spine and the run type before you click

A clip is a story, not a flipbook. Before clicking, answer two questions:

**1. What's the spine?** What is the one thing the reader of this clip should walk away knowing?

**2. What kind of run is this?** This determines the narration voice + pacing for the rendered video. Pass `--type <value>` to `agentclip slideshow create` (or `run_type` via the SDK). Four canonical types, each with one voice. Pick from the trigger phrasing — you almost never need to ask the user:

| Trigger phrasing in the user prompt | `run_type` | Voice |
|---|---|---|
| "demo", "show off", "showcase", "walk through", "walkthrough", "onboarding", "first impression", "fresh user", "feature reveal" | `demo` | Loom recording — first-person, casual, present-tense, lands on non-obvious detail |
| "QA", "smoke test", "smoke", "regression", "verify", "did this work" | `qa` | checklist, brisk, blunt pass/fail verdicts |
| "guide", "how-to", "explain", "compare", "teardown", "vs", "investigate", "inspect", "research" | `guide` | analyst, comparative, lands a takeaway |
| "repro", "reproduce", "bug", "broken", "failing flow", "incident" | `bug` | terse, factual, stack-trace-adjacent |

If the trigger is too ambiguous to pick (e.g. user just says "clip this") — default to `demo`. Ask only when the difference changes the actual story, not just the label.

The same voice runs the whole clip — intro, every slide caption, and outro all share one voice so the listener hears one consistent presenter. **One type = one voice.** This is the load-bearing reason `demo` and `qa` are separate types: a recruiter clip and a QA pass call for genuinely different voices, and the renderer needs the type to pick the right one.

`walkthrough` is accepted as a deprecated synonym for `demo` so legacy rows keep validating. Don't pick it for new clips.

| Run type | Spine |
|---|---|
| `demo` | "What's it like to use" — feature reveal, walking the flow, landing on the *interesting* detail |
| `qa` | "Did it work" — checklist pass/fail across the meaningful states |
| `guide` | "Here's what's going on" — inspect, compare, or teach the thing someone came to understand |
| `bug` | "Here's exactly what broke" — establish, reproduce, prove |

If you can't name the spine, ask the user before clicking. A clip without a spine is filler.

## Step 2: Create the clip at the start, not the end

Call `slideshow_create` **before** you take screenshots. Two reasons:

- The returned `slideshow_id` is what every `slideshow_add_slide` call needs. Creating up front means you add slides as you go instead of buffering them.
- Writing the title + description forces you to commit to a spine (Step 1). Both fields are read aloud in the rendered video — `description` becomes the spoken intro, so write it like a one-line "here's what you're about to watch" framing, not a database row.

**Title:** noun phrase. "Project-create flow QA on staging." "Login regression repro." Not a sentence, not a question.

**Description = the spoken intro.** It's read aloud over the title card at the start of the rendered video, so write it as the first thing a presenter would actually say. Run-type-specific:

- **demo** — *"Three fields, inline validation, a clean redirect on success. Here's how the new signup flow feels."* — direct, present-tense, no welcome, no meta-framing.
- **qa** — *"Smoke test of the checkout flow on staging — happy path, expired-card failure, and post-success state."*
- **guide** — *"A quick read on what changed in the AI chatbot market, using the latest public market-share chart."*
- **bug** — *"Repro of the rate-limit 503 on signup. Three steps."*

Banned openers: *"Welcome to..."*, *"Today we'll be looking at..."*, *"I'm excited to show you..."*, *"In this walkthrough..."*, *"A 30-second look at..."* (meta-framing — the listener doesn't care about runtime). The MP4 starts where the action is, not in the green room.

**`run_type`:** pass the value you picked in Step 1. Drives the narration voice + pacing.

## Step 3: Capture only meaningful moments

In priority order — when in doubt, capture the higher tier first:

1. **Errors and surprises.** Console errors, 500 pages, broken layouts, unexpected redirects. Highest-value slides. Never skip one.
2. **State transitions a teammate would care about.** Form submitted → email-verification screen. Modal opened. Async result rendered. Navigation completed.
3. **Pre-assertion states.** The page right before you check whether something works. Lets the caption read "expected X, saw Y."
4. **Sub-flow inflection points.** "Now testing settings" or "Switched to mobile viewport." Keeps multi-act runs cohesive.

Do **not** capture:

- Every click. Intermediate states between meaningful results are noise.
- Pure scrolling or unchanged states.
- Loading spinners or skeletons. Wait for the loaded state.
- The same state twice — use `slideshow_update_slide` instead.

Use a screenshot when one frame tells the story. Use a short recording when motion is the story: drag-and-drop, animation, timing bugs, or a fast flow that is easier to understand in sequence.

### Directing attention — when a caption says "watch X," annotate X

A static screenshot can't move the viewer's eye. If your caption is *"watch the password meter"* or *"notice the error sits right under the field,"* the screenshot must actually direct the eye to that element — otherwise the viewer is hunting around while the narration races ahead.

Use `browser_screenshot(annotations=[...])` to bake an SVG overlay onto the PNG. Four annotation types:

| Type | What it does | When to use |
|---|---|---|
| `circle` | Draws a circle around an element with optional label | "look at this element" / "watch this button" |
| `rect` | Highlights a region with tinted background + outline | "this whole panel matters" / "everything in here changed" |
| `arrow` | Curved arrow from element A to element B with optional label | "this causes that" / "click here, result lands there" |
| `label` | Sticky-note callout pointing at an element | Free-text annotation tied to an element |

**Anchor to CSS selectors, not pixel coordinates.** The agent already uses selectors for `browser_click` / `browser_type` — annotations use the same. Pixel-coord fallback exists (`{"x": 412, "y": 287}`) but use it only when no clean selector exists.

**Target the smallest representative element, not the parent container.** This is the most common mistake. If the caption is *"each tile is a real clip,"* don't draw a rect around the entire gallery row containing all 4 tiles — pick ONE tile and circle it. The viewer's eye lands somewhere specific, then generalizes. A rect that covers half the viewport reads as "boxing off a giant block" and directs attention to nothing. Rough sizing rule: if your annotation's bounding box is wider than 40% of the viewport, you almost certainly picked the parent — go one level deeper.

```python
# Slide caption: "Watch the password meter — it grades you live as you type."
browser_screenshot(
    session_id=sid,
    out_path="/tmp/02-form.png",
    annotations=[
        {"type": "circle", "target": "[data-testid='password-strength']",
         "label": "live, no submit needed"},
    ],
)

# Slide caption: "Submit stays disabled and the error sits right under the field."
browser_screenshot(
    session_id=sid,
    out_path="/tmp/03-error.png",
    annotations=[
        {"type": "rect",  "target": "#password-error", "label": "error at the field"},
        {"type": "arrow", "from": "#submit-button", "to": "#password-error",
                          "label": "no toast at the top"},
    ],
)
```

**Caption ↔ annotation contract.** If a caption uses deictic words like *"watch / notice / see / look at / right here / this part,"* the slide MUST have an annotation pointing at the referenced element. Captions that point at nothing visual are weak — the narration tells you where to look but the screen doesn't follow.

**Failure recovery.** The result includes `placed[]` and `failed[]` — if a selector didn't match (target removed, modal closed, off-screen), the failure is informational, not fatal. Retry with a better selector or fall back to a screenshot without that annotation. Never invent a screenshot.

**Color.** Default is `#ff3b30` (Apple-style attention red). For multi-annotation slides, pass distinct hex colors to keep them legible — e.g. red for the broken thing, blue for the expected thing.

Annotations bake into the PNG bytes, so they ship downstream in PDFs, MP4 frames, OG cards, and raw `<img>` pastes — no render-time work needed. (Future versions will support animated annotations that fade in synced to narration. For now, baked-in is the foundation.)

### Stabilize the page before stilling it

Modern hero sections like to animate — typewriter cyclers, autoplay carousels, Lottie loops. A still grabbed mid-animation freezes a meaningless half-word and discards the point. Before `browser_screenshot` on a state with motion:

- Wait for the animation to land on its terminal frame (`browser_wait_for_text` for the final word of a typewriter, or a known idle class on a carousel).
- If the motion never lands (infinite loop), pause it: `page.evaluate("document.getAnimations().forEach(a => a.pause())")` via whatever JS escape hatch your runtime exposes.
- If the motion *is* the story (the cycle is the pitch), don't still it at all — record it. `browser_open(record_video=True)` then `browser_stop_recording`.

Target ratio: 3–5 slides for focused tasks, 10–15 for sprawling QA. Measure by distinct meaningful states, not wall-clock — "one slide per minute" lies for tasks with no temporal axis (a homepage audit isn't a flow).

## Step 4: Write captions for the run type — one voice doesn't fit all

A bug repro and a recruiter demo are not the same artifact. **The caption style depends on the run_type you picked in Step 1.** Get this wrong and the rendered video sounds either like a stack-trace dump (when it shouldn't) or like a corporate webinar (please no).

**One rule across all types: captions are required.** The API rejects empty captions with a 400. A slide without spoken context is broken output.

**Banned across all types** — these read as "AI demo" the moment you hear them:
- "I'm excited to show you today..." / "Welcome to this walkthrough" / "Today we'll be diving into..." — corporate-presenter cringe. Cut it.
- "I am now clicking..." / "Let me navigate to..." — narrating yourself instead of the app.
- "Screenshot of homepage" / "Page" / "Loading" — redundant with the screenshot, or empty.
- "Seamless", "robust", "leverage", "powerful", "intuitive" — buzzword filler. Whatever the marketing site claims, your captions describe what *actually* happened.
- Long sentences with multiple clauses linked by "and" — the listener can't re-read; break into two.

### Per-run-type caption style

Read every caption out loud in your head before shipping it. TTS will say what you wrote. If you stumble or it sounds like a press release, rewrite.

#### `demo` — Loom recording, first-person, "friend showing friend"

Voice: someone who just shipped something and hit record on Loom to show you. Casual. First-person ("I'll show you," "we just shipped"). Acknowledges the viewer ("watch this," "you can see"). Mild editorial reactions allowed ("which I really like," "took us a few iterations"). Contractions throughout. **Do not** sound like marketing copy.

This voice is fixed by the run type, **not** by how the user phrased the request. "Demo it like a quick walkthrough," "just show what's in it," "give me a tour" — all still get the full Loom voice. A flat request never licenses flat narration: if the run type is `demo`, the captions are first-person and casual, period. Neutral product narration ("The form contains three fields") is a failure, not a safe default.

Example clip (use this as a reference, not as a template — write fresh for the actual content):

```
Title: Walking through the new signup
Description: Hey — quick walkthrough of the new signup flow we just shipped. I'll show you the cold-start path and one of the error states. Three fields total.

Slide 1: Alright, fresh browser, no cookies. This is the homepage logged out. One CTA — sign up free, right above the fold. That's intentional, we cut everything else.
Slide 2: Click sign up and the form just pops in — no full page reload, no separate /signup route. Three fields: email, password, workspace name. And the password meter grades you live as you type, which I really like.
Slide 3: Now if you try a weak password — watch this — the submit button won't even let you click through. Error sits right where the field is, no toast to chase down at the corner of the screen.

Summary: So yeah — one CTA, three fields, live validation, and a verification screen that previews the actual email. Took us a few iterations to land on the inline modal but I think it ended up pretty clean.
```

**The tells that make it work:** "Alright," "I'll show you," "watch this," "I really like," "took us a few iterations," "pretty clean." Casual filler is good in demo voice — it's what makes a Loom recording sound like a person, not a press release. Don't strip it.

**Don't write:**
- "A 30-second look at the new signup flow." (meta-framing — the listener doesn't care about runtime)
- "Inline modal, no page reload — three fields total." (Linear marketing copy — too tight, no human)
- "The hero has one job and doesn't compete with a carousel." (design-critic voice — wrong register)

#### `qa` — checklist out loud, brisk pass/fail

Voice: someone running through a checklist for another engineer. Each slide ends with a verdict — *worked*, *passed*, *broken*, *clean*. When something fails, say what failed plainly; the listener can't re-skim. **No filler, no editorial.** This is the one place tight reads correctly.

```
Cart loaded with two items — $48 subtotal. Free-shipping prompt fired at the $50 threshold. Correct.
Submitted with an expired card. Got 'Card expired — try another' inline, no charge attempted. Failure mode handled cleanly.
Refreshed after success. Cart cleared, back button safe. Post-success state is clean.
```

#### `guide` — friendly YouTuber explaining a thing

Voice: a product-explainer YouTube channel (Fireship, Theo, Web Dev Simplified vibe). Second-person ("you'll notice," "watch what happens"). Stakes-aware ("most signup flows still get this wrong"). Editorial asides allowed ("small thing, big difference"). Specifics over generalities — concrete numbers, named things, real time windows.

```
Title: Signup, rebuilt
Description: A look at signup that doesn't fight you. One screen, three fields, live errors — and a verification screen that shows you the email you're about to receive.

Slide 1: You land here logged out. Notice what's missing — there's no carousel, no nav tour, no five-step onboarding modal. Just one button. That's the whole pitch.
Slide 2: Click sign up and the form opens in place. Three fields, that's it. See the password meter? It scores you in real time — you'll never hit submit only to find out your password was 'too short.'
Slide 3: Try a weak password and watch the submit button — it stays disabled. The error doesn't fly in from the top as a toast; it lands right under the field, where your eyes already are. That's the part most signup flows still get wrong.

Summary: One button, three fields, live errors, and a verification screen that actually shows you the email. The whole flow takes about 12 seconds — and unlike most signup pages you've seen this week, this one isn't trying to upsell you on a trial.
```

**The tells that make it work:** "you'll notice," "watch what happens," "the part most flows get wrong," "small thing, big difference," contrasts with "most signup pages." Stakes + editorial + second-person.

#### `bug` — terse, factual, stack-trace-adjacent

Voice: a senior engineer narrating a repro to another senior engineer. No setup. No closure. Just facts. Past-tense is fine here — you're recapping what you ran.

```
Cleared cookies. Cold-loaded /signup.
Submitted with valid data. Got 503 from /api/auth/signup.
Stack trace pointed at a missing rate-limit Redis key.
```

#### Default — use demo

When you didn't pick a type or none fit cleanly, use `demo`. The Loom voice reads well in most contexts.

### Titles per type — drop the engineer frame on demos

- **demo:** *"New signup flow"*, *"Signup, redesigned"*, *"Walking through the new signup"*. **Not** *"Signup flow on staging"* — that leaks the QA frame into a demo title.
- **qa:** *"Project-create flow QA on staging"*, *"Checkout smoke test"*, *"Login regression"*. Engineer-readable is correct here — the audience is another engineer.
- **guide:** *"ISP-level attribution with Cloudflare Radar"*, *"Linear vs Notion: project switching"*. Name the payoff or the comparison — still a noun phrase. **Not** *"How to inspect internet traffic with Cloudflare Radar"* — that's an instructional sentence, not a title.
- **bug:** *"Login regression repro"*, *"Rate-limit 503 on signup"*. Tight, blunt, names the bug.

### Universal narration tips (apply to every type)

- **Write for the ear, not the eye.** Captions are read aloud by TTS. Re-read each one in your head; if you stumble, rewrite.
- **Em-dashes give the TTS a natural pause beat.** Use them where a presenter would breathe.
- **Active voice, present-tense for demo, qa, and guide.** Past-tense ("clicked", "got") is fine for bug repros where you're recapping.
- **No jargon the listener can't catch on first pass.** Readers can re-skim; listeners can't.
- **When a slide captures an error or surprise, say so plainly.** *"Got a 500 from /api/teams — stack trace mentioned a missing tenant_id."* Buried bugs are useless bugs.

`media_path` accepts PNG / JPEG / GIF / WebP for stills, MP4 / WebM / MOV for short clips. Use a clip when motion **is** the story (janky animation, race condition only visible in recording, fluid demo of a flow). Cap clips at a few seconds; upload limit is 25 MB.

## Step 3.5: Caption verifier — fire after every `slideshow_add_slide`

**Fire timing:** immediately after each successful `slideshow_add_slide`. Don't batch — one verifier per slide, while the captured frame is still fresh in context.

**Why this gate exists:** captions drift toward enumerating what's on screen rather than landing on the *interesting* detail. The host LLM can't easily self-critique inside the same turn that wrote the caption — by spawning a fresh subagent that hasn't seen your reasoning, you get an independent read that catches drift before it ships.

**Spawn shape** (Claude Code `Task`; equivalent native primitive in Codex / OpenCode):

```
description: Caption verifier for slide N
subagent_type: general-purpose
prompt: |
  You are a strict caption verifier for an AgentClip slideshow. Independent of how the caption was written, score whether it lands a useful point.

  Run type: <demo | qa | guide | bug>
  Slide media path: <absolute path to PNG/MP4>
  Caption being verified: "<exact caption text>"
  Slide position: <N>

  Step 1. Enumerate every distinct UI element visible in the frame. Don't write a sentence; list them.
  Step 2. Decide whether the caption (a) names something *not* obvious from the frame's literal contents (good), or (b) reads as a description of what's visible (bad — that's the screenshot's job). For qa, additionally require an explicit verdict (worked/passed/broken/clean). For bug, require factual past-tense framing. For guide, require a specific finding, not a UX observation.
  Step 2b. Check the caption's voice register against the run type. For demo, the caption must sound like a person narrating a Loom — first-person and/or direct viewer address, contractions, casual. A demo caption written as detached third-person product copy ("The form contains three fields," "The submit button is disabled") fails here even if it lands a point — set matches=false and rewrite it in voice.
  Step 3. Check the caption against the banned-phrase list: "welcome to", "today we'll", "I'm excited to show", "in this walkthrough", "I am now clicking", "let me navigate", "as we can see", "observe how", "notice that", "in conclusion", "seamless", "robust", "leverage", "powerful", "intuitive". Case-insensitive substring.
  Step 4. If it fails on any axis, write a one-line replacement caption in the run-type's voice that does land a point. Stay close to the original facts.

  Return ONLY JSON matching this schema:
  {
    "visible_elements": ["..."],
    "matches": true | false,
    "reason": "one short sentence",
    "banned_phrases_found": ["..."],
    "suggested_caption": "..."   // present iff matches=false
  }
```

**On `matches: false`:** call `slideshow_update_slide(slideshow_id=…, slide_position=N, caption=<suggested_caption>)` exactly once with the suggested caption. Don't loop — one fix per slide. If the verifier flags a banned phrase, the suggested caption must not contain any of them. Move on.

**On `matches: true`:** continue. No update needed.

## Step 4.5: Script reviewer — fire once before `slideshow_set_summary`

**Fire timing:** exactly once, after the final slide is added (and verified) but before you call `slideshow_set_summary`. Don't fire per-slide — this gate looks at the whole clip as a script.

**Why this gate exists:** voice drift across slides is invisible from inside the same conversation that wrote them. A separate subagent reading the title + description + every caption in one pass catches: voice inconsistency (slide 3 sounds like a presenter, slide 4 sounds like a court reporter), opener-shape regressions (description starts with a banned phrase), spine drift (the clip wandered off the picked spine), and any banned-phrase slips the per-slide verifier missed. As a bonus, it pre-cooks a summary in the right voice that you can pass straight to `slideshow_set_summary`.

**Spawn shape** (Claude Code `Task`; equivalent in other hosts):

```
description: Script reviewer before set_summary
subagent_type: general-purpose
prompt: |
  You are reviewing the full script of an AgentClip clip before the spoken outro is set. Independent of how it was written, judge whether the whole clip holds together.

  Run type: <demo | qa | guide | bug>
  Picked spine: "<one-sentence spine from Step 1>"

  Title: "<exact title>"
  Description (spoken intro): "<exact description>"
  Captions (in order):
  1. "<caption 1>"
  2. "<caption 2>"
  ...
  N. "<caption N>"

  Voice definition for <run_type>: <copy-paste the relevant Step 4 voice block>

  Check:
  - voice_consistent: does one voice run through intro + every caption? If even one slide breaks register (analyst voice in a demo clip, court-reporter past tense in a present-tense run), flag it.
  - voice_matches_register: do the captions actually land the voice in the definition above — not just match each other? Captions that are uniformly flat still fail this. A demo clip whose captions read as detached third-person product copy ("The form contains three fields") is wrong even if all N captions are wrong the same way. The intro and outro carrying the voice does not cover for flat captions. Flag every caption that doesn't carry the run-type voice.
  - opener_shape: does the description avoid banned openers ("welcome to", "today we'll", "I'm excited to show", "in this walkthrough", "A 30-second look at...", and meta-framing in general)?
  - banned_phrases: scan title, description, and every caption against the universal banned-phrase list. Return every match.
  - spine_adherence: does the clip actually deliver on the picked spine? If three slides chase a different thread, flag it.
  - suggested_summary: write the spoken outro this clip should ship. Under 80 words. In the run-type's voice. For qa, include an explicit pass/fail count. For bug, name the bug + slide reference. For guide, land a takeaway. For demo, name the demo outcome.

  Return ONLY JSON matching this schema:
  {
    "voice_consistent": true | false,
    "voice_matches_register": true | false,
    "voice_issues": ["slide N: reason", ...],
    "opener_shape_ok": true | false,
    "opener_issue": "..." | null,
    "banned_phrases_found": ["..."],
    "spine_adherence_ok": true | false,
    "spine_issues": ["..."],
    "suggested_summary": "..."
  }
```

**Acting on the result:**
- `voice_consistent: false`, `voice_matches_register: false`, or `banned_phrases_found` nonempty → call `slideshow_update_slide` on each slide named in `voice_issues` with a rewritten caption that fixes the issue. One pass — don't loop.
- `opener_shape_ok: false` → call `slideshow_create`'s update path or, if no such path, accept that the description is locked at create time and note in the final report that next clip should pick a better opener.
- Always use `suggested_summary` as the input to `slideshow_set_summary` unless you have a strong reason not to. The reviewer wrote it in the right voice; trust it.

## Step 5: Fix slides in place — don't pile on corrections

If a slide has a typo, a wrong caption, or a screenshot that didn't capture what you meant, fix it with `slideshow_update_slide`. **Do not append a "correction" slide.**

If a slide should not exist at all, leave it for now and call it out in the summary. v1 has no `delete_slide`; honesty in the summary is the right move, not a fake "redacted" slide.

## Step 6: Set the summary — the spoken outro

`slideshow_set_summary` is the TL;DR. **Under 80 words.** It's read aloud as the spoken outro on the rendered video AND shown as a callout box on the share page. Run-type-specific again:

- **demo** — the demo outcome or the key observed result. *"Three fields, two error states, one success path. Clean."* Not *"In conclusion, we have demonstrated..."* — the listener was just there, don't recap.
- **qa** — explicit pass/fail count + slide references for failures. *"5/5 passed end-to-end. One copy nit on slide 3 — submit button stays 'Continue' instead of 'Pay $48'."* Always state the count.
- **guide** — the takeaway, named. *"Gemini gained share while ChatGPT stayed dominant. The market is no longer a one-model story."*
- **bug** — outcome + slide reference. *"Bug confirmed at slide 2. /api/auth/signup returns 503 instead of either succeeding or rate-limit-error."*

Structure (regardless of type):

1. **One sentence on outcome** — what happened, did it work / what's the verdict.
2. **Counts or specifics** — pass/fail counts, named differences, or the actual change you noticed.
3. **Bug list (only for `bug` or `qa`)** — one line per real bug, with the slide number.

No praise, no hedging, no apologies. No "as we have seen". The summary is read by someone with 10 seconds. Make those seconds count.

## Step 7: Hand off the URL

The `slideshow_create` response includes a few URLs. They are **different**:

- **`share_url`** — public. Paste it into Slack, iMessage, Discord, a recruiter message. The page renders the narrated walkthrough as a video by default with a Slides toggle for skim mode. Link unfurls show inline video automatically.
- **`clip_mp4_url`** — public, ends in `.mp4`. Use this in **GitHub PR descriptions, READMEs, and any Markdown surface that only renders inline video for direct video files**. Pasting `share_url` in a GitHub PR shows a bare link; pasting `clip_mp4_url` shows an inline `<video>` element.
- **`clip_pdf_url`** — public, downloadable branded walkthrough. Useful for attaching to a Jira ticket or a client email when video isn't an option.
- **`embed_url`** — public iframe target. The `share_url` page exposes a "Copy embed code" button that wraps this in `<iframe>` HTML for Notion, Substack, blog posts.
- **`edit_url`** — **private**. It's the only credential that authorizes caption fixes later. Mention it exists; do not include it inline unless asked. **Treat it like a password.**

The MP4 and PDF render lazily on first external fetch and are pre-warmed when you call `slideshow_set_summary` (Step 6). The render task auto-narrates any slides without audio before stitching, so you don't need to think about narration as a separate step — captions go in, narrated video comes out. You don't need to call any render or narrate command; the URLs work as soon as someone clicks them.

If the user mentions sharing externally and they haven't run `agentclip whoami`, suggest it **once**. Their name and URL become the creator credit credit on every clip from then on, automatically. Skip the suggestion for casual internal QA where attribution adds nothing.

## Tool reference

| Tool | When | Required args |
|---|---|---|
| `slideshow_create` | Once, at the start (Step 2) | `title`, `description`, `run_type` |
| `slideshow_add_slide` | After each meaningful state (Step 3) | `slideshow_id`, `media_path`, `caption` |
| `slideshow_update_slide` | To fix in place (Step 5) | `slideshow_id`, `slide_position`, what's changing |
| `slideshow_set_summary` | Once, near the end (Step 6) | `slideshow_id`, `summary` |

The tools persist your `write_token` locally. After `slideshow_create` returns, you only need the `slideshow_id`.

## Anti-patterns

- **Corporate-presenter cringe.** *"I'm excited to show you today..."*, *"Welcome to this walkthrough"*, *"Today we'll be diving into..."*, *"In this demo we will explore..."*, *"Without further ado..."*. The MP4 starts where the action is. Cut every word that doesn't earn its place.
- **Narrating yourself instead of the app.** *"I will now navigate to the login page."* The viewer doesn't care about you driving the mouse. Describe the app's response, not your motion.
- **Court-reporter past tense in a demo.** *"The user clicked. The form was submitted. The application then displayed..."* Demos read in present tense, declaratively. *"Three fields. Submit empty? Inline error."*
- **Buzzword filler.** *"seamless"*, *"robust"*, *"leverage"*, *"powerful"*, *"intuitive"*, *"best-in-class"*. If the marketing team writes the caption, the demo is dead.
- **As-we-can-see-isms.** *"As we can see"*, *"observe how"*, *"notice that"*, *"in conclusion"*. The viewer is *literally watching*. Don't tell them to look.
- **Enumerating what's visible.** *"Page shows hero, nav, footer, with a sign-up CTA in the top right."* That's a description of the screenshot, not a caption. The screenshot already does that job. Pick the *non-obvious* detail and land on it: *"Sign-up CTA is the only thing above the fold — no carousel, no nav competing for the click."*
- **Filler slides.** *"Loading…"* is not a slide. Wait for the loaded state.
- **Terminal screenshots.** If you ran a CLI command, paste the output in the caption. Terminal shots break the browser narrative.
- **Mixing flows in one clip.** Signup and checkout are two clips. The user reorders context per audience.
- **Skipping the summary.** Without it the clip has no spoken outro and the share page has no callout box — it's a stack of screenshots. With it, it's a deliverable.
- **Asking before every slide.** Don't. Take the screenshots, write the captions, set the summary, hand over the URL.
- **Tools that aren't loaded.** If the MCP browser tools are missing in your tool list, don't fall through to `screencapture` or improvise. The fallback ladder, in order, is: (a) `agentclip capture <url> --out` for a viewport-only PNG from a URL — works without MCP, returns a real path; (b) `agentclip setup` then ask the user to restart the session, then retry. Never invent screenshots, never use OS screen capture (it leaks the IDE/terminal/desktop to the public clip URL).

## Worked example

User: *"QA the new project-create flow on staging."*

```python
slideshow_create(
    title="Project-create flow QA on staging",
    description="Smoke test of the new project-create flow as a brand-new user. Validation, success path, and the obvious failure modes.",
    run_type="qa",  # picked from "QA" in the trigger phrase
)
# returns slideshow_id="ss_abc123"

slideshow_add_slide(
    slideshow_id="ss_abc123",
    media_path="/tmp/01-empty-projects.png",
    caption="Brand-new account, empty projects list. 'New Project' CTA is the only obvious next step. Correct.",
)

slideshow_add_slide(
    slideshow_id="ss_abc123",
    media_path="/tmp/02-form-open.png",
    caption="Clicked New Project. Modal opened with three fields. Defaulted to 'private' visibility. Worked.",
)

slideshow_add_slide(
    slideshow_id="ss_abc123",
    media_path="/tmp/03-empty-submit.png",
    caption="Submitted with no name. Inline 'Name is required' error, field highlighted red. Validation worked.",
)

# … more slides through the flow …

slideshow_add_slide(
    slideshow_id="ss_abc123",
    media_path="/tmp/09-bug-redirect.png",
    caption="Created project 'Test 1'. Success toast fired, but redirect went to /projects/undefined instead of /projects/<id>. Broken — response payload missing the 'id' field.",
)

slideshow_set_summary(
    slideshow_id="ss_abc123",
    summary="8/9 passed end-to-end on staging. One real bug at slide 9: post-create redirect lands at /projects/undefined when the response is missing the id field. Two minor copy nits flagged in slides 5 and 7.",
)
```

### Same flow, but recorded as a demo for a recruiter

Same screenshots, totally different copy — the captions read like a presenter, not a QA log.

```python
slideshow_create(
    title="Project-create flow on AgentClip",
    description="Three fields, inline validation, a clean redirect on success. Here's how creating a project feels.",
    run_type="demo",  # presenter voice, present-tense captions
)

slideshow_add_slide(
    slideshow_id="ss_xyz",
    media_path="/tmp/01-empty-projects.png",
    caption="A fresh account, no projects yet — one obvious next step.",
)

slideshow_add_slide(
    slideshow_id="ss_xyz",
    media_path="/tmp/02-form-open.png",
    caption="Three fields, sensible defaults — private visibility checked.",
)

slideshow_add_slide(
    slideshow_id="ss_xyz",
    media_path="/tmp/03-empty-submit.png",
    caption="Submit empty? Clean inline error, no page reload.",
)

slideshow_set_summary(
    slideshow_id="ss_xyz",
    summary="Three fields, two error states, one success path. Clean.",
)
```

Notice: no *"the user clicks"*, no *"as we can see"*, no *"in conclusion"*. Each caption lands on the *interesting* detail — what's *non-obvious* about that screen, not what's literal.

The user gets one share URL. They paste it into Slack, a Linear ticket, a PR description, a cold-app message. **The URL is the artifact. The captions are what makes it worth opening.**
