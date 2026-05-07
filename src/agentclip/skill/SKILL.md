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

**Description:** one or two sentences naming what you're testing, with the relevant assumptions (browser, user role, environment). Written to be heard — em-dashes give the TTS a natural pause beat.

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

## Step 4: Caption every slide in active voice

Format: **action + expectation + result.** One or two sentences. Readers skim captions, not screenshots — and the TTS pipeline reads them aloud in the rendered video, so they need to sound natural when spoken.

**Captions are required.** The API rejects empty captions with a 400 — a slide with no spoken context is broken output.

**Narration-friendly tips:**
- Write in complete sentences. "Clicked submit. Got a 500." plays better than "submit, 500."
- Em-dashes give nova/onyx/shimmer a natural pause beat.
- Avoid jargon a listener wouldn't catch on the first pass — readers can re-skim, listeners can't.

Good:

- "Clicked Sign Up. Form posted. Saw the email-verification screen as expected."
- "Submitted with an empty password. Got the inline validation error."
- "Reloaded the dashboard. The new project appeared at the top of the list."

Bad — and why:

- "I am now clicking the submit button." — narration of yourself, not the app.
- "Screenshot of homepage." — redundant with the screenshot.
- "Page" — no information.
- "This is where we test the login functionality and observe the behavior of the system as it processes credentials." — length, jargon, zero actionable content.

When a slide captures an error or surprise, say so plainly: **"Got a 500 from /api/teams. Stack trace mentioned a missing tenant_id."** Buried bugs are useless bugs.

`media_path` accepts PNG / JPEG / GIF / WebP for stills, MP4 / WebM / MOV for short clips. Use a clip when motion **is** the story (janky animation, race condition only visible in recording, fluid demo of a flow). Cap clips at a few seconds; upload limit is 25 MB.

## Step 5: Fix slides in place — don't pile on corrections

If a slide has a typo, a wrong caption, or a screenshot that didn't capture what you meant, fix it with `slideshow_update_slide`. **Do not append a "correction" slide.**

If a slide should not exist at all, leave it for now and call it out in the summary. v1 has no `delete_slide`; honesty in the summary is the right move, not a fake "redacted" slide.

## Step 6: Set the summary before you hand off the URL

`slideshow_set_summary` is the TL;DR. **Under 80 words.** It's read aloud as the spoken outro on the rendered video AND shown as a callout box on the share page, so write it for both surfaces — short, factual, complete sentences. Structure:

1. **One sentence on outcome** — what was tested, did it work.
2. **Counts** — how many flows passed, how many failed, how many warnings.
3. **Bug list, if any** — one line per real bug, with the slide number a reader can jump to.

Example:

> Tested signup, login, and password reset on production. Signup and login passed. Password reset failed: the email never arrived (slide 8) and the success page lied about it (slide 9). Two minor UI bugs noted (slides 4, 11).

No praise, no hedging, no apologies. The summary is read by someone with 10 seconds. Make those seconds count.

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

- **Narrating yourself.** "I will now navigate to the login page." Captions are about the app, not you.
- **Filler slides.** "Loading…" is not a slide. Wait for the loaded state.
- **Terminal screenshots.** If you ran a CLI command, paste the output in the caption. Terminal shots break the browser narrative.
- **Mixing flows in one clip.** Signup and checkout are two clips. The user reorders context per audience.
- **Skipping the summary.** Without it the clip has no spoken outro and the share page has no callout box — it's a stack of screenshots. With it, it's a deliverable.
- **Asking before every slide.** Don't. Take the screenshots, write the captions, set the summary, hand over the URL.
- **Faking it.** If you can't actually drive the browser (no MCP browser tool, no Playwright, no Chromium available in your runtime), say so explicitly: "Real evidence would require a browser-driving tool. Recommending [the user runs it themselves / a different surface]." Never invent screenshots.

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

The user gets one share URL. They paste it into Slack, a Linear ticket, a PR description, a cold-app message. **The URL is the artifact. The captions are what makes it worth opening.**
