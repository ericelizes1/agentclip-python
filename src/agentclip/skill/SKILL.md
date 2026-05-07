---
name: agentclip
description: Capture a narrated clip of your work. Use after driving a browser through a feature, bug repro, or onboarding flow the user wants to see at a glance. Triggers on "QA this", "show me what happened", "share a run of X", "demo this", "repro the bug visually", or whenever your work produces visual evidence worth keeping. Output is a shareable URL that plays as a narrated video and falls back to a slide-by-slide scroll.
---

# agentclip

You drove a browser. The user wants the receipts. This skill turns the run into a shareable URL — a narrated walkthrough that plays as a video by default and offers a slide-by-slide scroll fallback. Four tools do the work: `slideshow_create`, `slideshow_add_slide`, `slideshow_update_slide`, `slideshow_set_summary`.

The tools work without this skill. **The artifact is only as good as the captions and structure you give it.** Read on.

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

## Step 0: Pick the spine and the run type before you click

A clip is a story, not a flipbook. Before clicking, answer two questions:

**1. What's the spine?** What is the one thing the reader of this clip should walk away knowing?

**2. What kind of run is this?** This determines the narration voice + pacing for the rendered video. Pass `--type <value>` to `agentclip slideshow create` (or `run_type` via the SDK). Pick from the trigger phrasing — you almost never need to ask the user:

| Trigger phrasing in the user prompt | `run_type` | Voice |
|---|---|---|
| "QA", "smoke test", "smoke" | `smoke_test` | nova |
| "repro", "reproduce", "bug" | `bug_repro` | onyx |
| "demo", "walkthrough", "show off", "showcase" | `demo` | shimmer |
| "onboarding", "first impression", "friction", "fresh user" | `onboarding_eval` | nova |
| "compare", "teardown", "vs", "competitive" | `competitive_teardown` | echo |
| Plain "make a clip", "show me what happened", anything else | `generic` | nova |

If the trigger is too ambiguous to pick (e.g. user just says "clip this") — ask once, naturally: *"Quick check: is this a bug repro, a smoke test, a demo, or something else? It changes the narration voice."* Don't pause for confirmation on every step; ask once and move.

The same voice runs the whole clip — intro, every slide caption, and outro all share one voice so the listener hears one consistent presenter.

| Run type | Spine |
|---|---|
| Bug repro | The bug — establish, reproduce, prove |
| Smoke test | "Did it work, and if not, where" — walk the flow, stop at the first failure |
| Competitive teardown | The comparison — alternate or annotate the contrast |
| Onboarding evaluation | The friction points — first-impression states + drop-off moments |
| Demo for a recruiter | The polished moments — title screens, hero states, the result |

If you can't name the spine, ask the user before clicking. A clip without a spine is filler.

## Step 2: Create the clip at the start, not the end

Call `slideshow_create` **before** you take screenshots. Two reasons:

- The returned `slideshow_id` is what every `slideshow_add_slide` call needs. Creating up front means you add slides as you go instead of buffering them.
- Writing the title + description forces you to commit to a spine (Step 0). Both fields are read aloud in the rendered video — `description` becomes the spoken intro, so write it like a one-line "here's what you're about to watch" framing, not a database row.

**Title:** noun phrase. "Project-create flow QA on staging." "Login regression repro." Not a sentence, not a question.

**Description = the spoken intro.** It's read aloud over the title card at the start of the rendered video, so write it as the first thing a presenter would actually say. Run-type-specific:

- **bug_repro** — *"Repro of the rate-limit 503 on signup. Three steps."*
- **smoke_test** — *"Quick smoke of the staging deploy."*
- **demo** — *"A 30-second look at the new signup flow. Three fields, inline validation, success state. Watch what happens on errors."* — direct, present-tense, no welcome.
- **onboarding_eval** — *"First-impression read of agentclip.dev as a brand-new user."*
- **competitive_teardown** — *"Linear vs Notion on project switching. The keyboard-vs-mouse difference."*

Banned openers: *"Welcome to..."*, *"Today we'll be looking at..."*, *"I'm excited to show you..."*, *"In this walkthrough..."*. The MP4 starts where the action is, not in the green room.

**`run_type`:** pass the value you picked in Step 0. Drives the narration voice + pacing.

## Step 3: Take screenshots only at meaningful moments

In priority order — when in doubt, capture the higher tier first:

1. **Errors and surprises.** Console errors, 500 pages, broken layouts, unexpected redirects. Highest-value slides. Never skip one.
2. **State transitions a teammate would care about.** Form submitted → email-verification screen. Modal opened. Async result rendered. Navigation completed.
3. **Pre-assertion states.** The page right before you check whether something works. Lets the caption read "expected X, saw Y."
4. **Sub-flow inflection points.** "Now testing settings" or "Switched to mobile viewport." Keeps multi-act runs cohesive.

Do **not** screenshot:

- Every click. Intermediate states between meaningful results are noise.
- Pure scrolling or unchanged states.
- Loading spinners or skeletons. Wait for the loaded state.
- The same state twice — use `slideshow_update_slide` instead.

Target ratio: roughly **one slide per minute** of agent run time. Onboarding QA: 10–15 slides. Focused bug repro: 3–5 slides.

## Step 4: Write captions for the run type — one voice doesn't fit all

A bug repro and a recruiter demo are not the same artifact. **The caption style depends on the run_type you picked in Step 0.** Get this wrong and the rendered video sounds either like a stack-trace dump (when it shouldn't) or like a corporate webinar (please no).

**One rule across all types: captions are required.** The API rejects empty captions with a 400. A slide without spoken context is broken output.

**Banned across all types** — these read as "AI demo" the moment you hear them:
- "I'm excited to show you today..." / "Welcome to this walkthrough" / "Today we'll be diving into..." — corporate-presenter cringe. Cut it.
- "I am now clicking..." / "Let me navigate to..." — narrating yourself instead of the app.
- "Screenshot of homepage" / "Page" / "Loading" — redundant with the screenshot, or empty.
- "Seamless", "robust", "leverage", "powerful", "intuitive" — buzzword filler. Whatever the marketing site claims, your captions describe what *actually* happened.
- Long sentences with multiple clauses linked by "and" — the listener can't re-read; break into two.

### Per-run-type caption style

#### `bug_repro` — terse, factual, stack-trace-adjacent

Voice: a senior engineer narrating a repro to another senior engineer. No setup. No closure. Just facts.

```
Cleared cookies. Cold-loaded /signup.
Submitted with valid data. Got 503 from /api/auth/signup.
Stack trace pointed at a missing rate-limit Redis key.
```

#### `smoke_test` — brisk pass/fail progression

Voice: someone running through a checklist out loud. Each slide ends with the verdict ("worked", "passed", "broken").

```
Home loaded — hero, nav, footer all present.
Login worked with seeded credentials. Dashboard rendered.
Logout cleared the session. Cookie gone.
```

#### `demo` — presenter, present-tense, no preamble

Voice: someone showing the product to a friend who already knows roughly what it does. Skip introductions. Land each slide on the *interesting* detail, not the obvious one.

```
Three fields, sensible defaults — private visibility checked.
Submit empty? Clean inline error, no page reload.
Submit valid? Email-verification screen, ready to share.
```

Not:

```
The user clicks the Sign Up button. The form is then submitted to the server. After a brief loading state, the application displays the verification screen as expected.
```

That's a court reporter, not a presenter. Cut every word that doesn't earn its place.

#### `onboarding_eval` — observational, first-impression

Voice: a new user thinking out loud. Notice what catches the eye and what doesn't. Mention what's *missing* as much as what's there.

```
Landed at agentclip.dev. Headline names the value upfront — no metaphor, no tagline.
Pricing's visible on the home, no separate page. Free forever, two paid tiers.
Sign-up's one click from anywhere — including from inside the marketing copy.
```

#### `competitive_teardown` — analytical, comparative

Voice: an analyst comparing two products side by side. Name the difference; explain why it matters. Specifics win.

```
Linear uses a keyboard command palette to switch projects. Notion uses a sidebar dropdown.
At 5+ projects Linear's lookup is faster — palette-fuzzy-search beats scroll.
The cost: Linear's discoverability is worse. Notion's dropdown is impossible to miss.
```

#### `generic` — defaults to demo style

When you didn't pick a type or none fit cleanly, write demo-style captions. They read well in the most contexts.

### Universal narration tips (apply to every type)

- **Write for the ear, not the eye.** Captions are read aloud by TTS. Re-read each one in your head; if you stumble, rewrite.
- **Em-dashes give the TTS a natural pause beat.** Use them where a presenter would breathe.
- **Active voice, present-tense for demos and onboarding evals.** Past-tense ("clicked", "got") is fine for bug repros and smoke tests where you're recapping.
- **No jargon the listener can't catch on first pass.** Readers can re-skim; listeners can't.
- **When a slide captures an error or surprise, say so plainly.** *"Got a 500 from /api/teams — stack trace mentioned a missing tenant_id."* Buried bugs are useless bugs.

`media_path` accepts PNG / JPEG / GIF / WebP for stills, MP4 / WebM / MOV for short clips. Use a clip when motion **is** the story (janky animation, race condition only visible in recording, fluid demo of a flow). Cap clips at a few seconds; upload limit is 25 MB.

## Step 5: Fix slides in place — don't pile on corrections

If a slide has a typo, a wrong caption, or a screenshot that didn't capture what you meant, fix it with `slideshow_update_slide`. **Do not append a "correction" slide.**

If a slide should not exist at all, leave it for now and call it out in the summary. v1 has no `delete_slide`; honesty in the summary is the right move, not a fake "redacted" slide.

## Step 6: Set the summary — the spoken outro

`slideshow_set_summary` is the TL;DR. **Under 80 words.** It's read aloud as the spoken outro on the rendered video AND shown as a callout box on the share page. Run-type-specific again:

- **bug_repro** — outcome + slide reference. *"Bug confirmed at slide 2. /api/auth/signup returns 503 instead of either succeeding or rate-limit-error."*
- **smoke_test** — pass/fail counts + flagged failures. *"Three flows tested. Signup and login passed. Password reset failed at slide 4 — email never arrived."*
- **demo** — one-sentence wrap that lands the value, not a recap. *"Three fields, two error states, one success path. Clean."* Not *"In conclusion, we have demonstrated..."* — the listener was just there, don't recap.
- **onboarding_eval** — verdict on the experience. *"Clear hero, transparent pricing, signup never further than one click. Strong onboarding."*
- **competitive_teardown** — the takeaway, named. *"Linear's keyboard palette wins at scale. Notion's sidebar wins for new users. Pick by user count."*

Structure (regardless of type):

1. **One sentence on outcome** — what happened, did it work / what's the verdict.
2. **Counts or specifics** — pass/fail counts, named differences, or the actual change you noticed.
3. **Bug list (only for bug_repro / smoke_test)** — one line per real bug, with the slide number.

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
- **Filler slides.** *"Loading…"* is not a slide. Wait for the loaded state.
- **Terminal screenshots.** If you ran a CLI command, paste the output in the caption. Terminal shots break the browser narrative.
- **Mixing flows in one clip.** Signup and checkout are two clips. The user reorders context per audience.
- **Skipping the summary.** Without it the clip has no spoken outro and the share page has no callout box — it's a stack of screenshots. With it, it's a deliverable.
- **Asking before every slide.** Don't. Take the screenshots, write the captions, set the summary, hand over the URL.
- **Faking it.** If you can't actually drive the browser (no MCP browser tool, no Playwright, no Chromium available in your runtime), say so explicitly: *"Real evidence would require a browser-driving tool. Recommending [the user runs it themselves / a different surface]."* Never invent screenshots.

## Worked example

User: *"QA the new project-create flow on staging."*

```python
slideshow_create(
    title="Project-create flow QA on staging",
    description="A walkthrough of the new project-create flow as a brand-new user — looking for friction, broken validation, and surprises.",
    run_type="smoke_test",  # picked from "QA" in the trigger phrase
)
# returns slideshow_id="ss_abc123"

slideshow_add_slide(
    slideshow_id="ss_abc123",
    media_path="/tmp/01-empty-projects.png",
    caption="Logged in as a brand-new account. Projects list is empty as expected. The 'New Project' CTA is the only obvious next step.",
)

slideshow_add_slide(
    slideshow_id="ss_abc123",
    media_path="/tmp/02-form-open.png",
    caption="Clicked New Project. Modal opened with three fields: name, description, visibility. Defaulted to 'private', which feels right.",
)

slideshow_add_slide(
    slideshow_id="ss_abc123",
    media_path="/tmp/03-empty-submit.png",
    caption="Submitted with no name to test validation. Got an inline 'Name is required' error and the field highlighted in red. Good.",
)

# … more slides through the flow …

slideshow_add_slide(
    slideshow_id="ss_abc123",
    media_path="/tmp/09-bug-redirect.png",
    caption="Created a project named 'Test 1'. Success toast fired, but the redirect went to /projects/undefined instead of /projects/<id>. Bug: response payload appears to be missing the 'id' field.",
)

slideshow_set_summary(
    slideshow_id="ss_abc123",
    summary="Tested project creation end-to-end on staging. Form validation passed all five edge cases. One real bug: post-create redirect lands at /projects/undefined when the response is missing the id field (slide 9). Two minor copy issues flagged in slides 5 and 7.",
)
```

### Same flow, but recorded as a demo for a recruiter

Same screenshots, totally different copy — the run_type changes the voice (shimmer instead of nova) and the captions read like a presenter, not a QA log.

```python
slideshow_create(
    title="Project-create flow on AgentClip",
    description="A 30-second look at how creating a project feels. Three fields, inline validation, a clean redirect on success.",
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
