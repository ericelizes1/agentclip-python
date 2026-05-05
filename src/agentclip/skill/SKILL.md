---
name: agentclip
description: Publish a QA slideshow of your work. Use after driving a browser through a feature, bug repro, or onboarding flow whose result the user wants to see at a glance. Triggers on "QA this", "post a slideshow of what you did", "show me what happened", "share a run of X", or whenever your work produces visual evidence worth keeping. Output is a shareable URL with screenshots, captions, and a summary.
---

# agentclip

You drove a browser. The user wants the receipts. Turn what you did into a
shareable slideshow URL using the four `slideshow_*` tools.

This file is the contract for how to do that well. The tools work without it,
but the artifact is only as good as the captions and structure you give it.

## When to use this skill

Use it when:

- The user asks you to QA a flow, repro a bug, or test an onboarding.
- The user says "post a slideshow", "share a run", "show me what happened".
- You finished a non-trivial browser-driven task and the result deserves
  visual evidence (a regression report, a competitive analysis, a smoke test
  after a deploy).
- You want a permanent artifact tied to this run that the user can paste in
  Slack, a PR description, or a recruiter message.

Skip it when:

- The task is purely code edits with no visible browser surface.
- The user explicitly only wants a written summary.
- You took fewer than two screenshots, since a one-slide "slideshow" is
  not worth a URL.

## The four tools

| Tool | When | Required args |
|---|---|---|
| `slideshow_create` | Once, at the start. | `title`, `description` |
| `slideshow_add_slide` | After each meaningful action you screenshotted. | `slideshow_id`, `image_path`, `caption` |
| `slideshow_update_slide` | Whenever you'd otherwise post a corrected duplicate. | `slideshow_id`, `slide_position`, plus what's changing |
| `slideshow_set_summary` | Once, near the end. | `slideshow_id`, `summary` |

The tools persist your `write_token` locally for you. You only need the
`slideshow_id` after `slideshow_create`.

## When to take a screenshot

A slideshow is a story, not a flipbook. Screenshot the moments a teammate
would actually want to see if you were walking them through the run.

Take a screenshot:

- **After meaningful actions land.** Form submitted, navigation completed,
  modal opened, async result rendered.
- **Before each assertion.** The state you're about to check should be
  visible, so the caption can describe what passed or failed.
- **At every error.** Console errors, 500 pages, broken layouts, unexpected
  redirects. These are the most valuable slides.
- **At the start of a new sub-flow.** "Now testing settings" is a useful
  inflection point.

Do not screenshot:

- Every click. The intermediate states between meaningful results are noise.
- Pure scrolling. If nothing changed, no slide.
- The same state twice. Use `update_slide` to fix the existing one.

A good ratio is roughly one slide per minute of agent run time. Ten to
fifteen slides for a typical onboarding QA. Three to five for a focused
bug repro.

## How to write captions

Active voice. Action plus expectation plus result. One or two sentences.

Good:

- "Clicked Sign Up. Form posted. Saw the email-verification screen as expected."
- "Submitted with an empty password. Got the inline validation error."
- "Reloaded the dashboard. The new project showed up at the top of the list."

Bad:

- "I am now clicking the submit button." (narration of self)
- "Screenshot of homepage." (redundant with the screenshot)
- "Page" (no information)
- "This is where we test the login functionality and observe the behavior of
  the authentication system as it processes credentials." (jargon, length)

If a slide captures an error or surprise, say so plainly: "Got a 500 from
/api/teams. Stack trace mentioned a missing tenant_id." A reader skimming
the slideshow needs the bug to jump out, not be buried.

## Narrative arc

Order the slides as a story:

1. **Setup.** The first one or two slides establish what you set out to do
   and where you started. The slideshow's `title` and `description` carry
   the high-level framing; slide one zooms in on the starting state.
2. **Walk-through.** Steps in the order you actually took them. If you
   backtracked, that backtrack is part of the story, so show it.
3. **Climax.** The point of the run. The bug repro frame. The successful
   submission. The unexpected behavior.
4. **Resolution.** What state did you leave the app in. What did you
   confirm or fail to confirm.

Then `slideshow_set_summary` lands the TL;DR for readers who do not scroll.

## Update vs append

If you notice a typo, a wrong caption, or a screenshot that did not capture
what you meant, fix it with `slideshow_update_slide`. Do not pile up a
"correction" slide after the original.

If you took a screenshot that should not exist at all, leave it for now
and call it out in the summary. v1 has no `delete_slide`; the right move
is honesty in the summary, not a fake "redacted" slide.

## Summary format

`slideshow_set_summary` is the TL;DR. Aim for under 80 words. Structure:

- One sentence on outcome (what was tested, did it work).
- Counts: how many flows passed, how many failed, how many warnings.
- Bug list if any: one line per real bug, with the slide number it lives
  at so a reader can jump straight to the screenshot.

Example:

> Tested signup, login, and password reset on production. Signup and login
> passed. Password reset failed: the email never arrived (slide 8) and the
> success page lied about it (slide 9). Two minor UI bugs noted (slides 4, 11).

Do not include praise, hedging, or apologies. The summary is read by
someone who has 10 seconds. Make those seconds count.

## Anti-patterns to avoid

- **Narrating yourself.** "I will now navigate to the login page." Captions
  are about the app, not about you.
- **Filler slides.** "Loading..." is not a slide. Wait for the loaded state
  and screenshot that.
- **Screenshot-of-terminal slides.** If you ran a CLI command, paste its
  output in the caption text. The slideshow is a browser story; terminal
  shots break the narrative and look like clutter.
- **Mixing two flows in one slideshow.** If you tested signup and then
  switched to testing checkout, those are two slideshows. The user can
  share them separately and reorder context per audience.
- **Skipping the summary.** Without one, the slideshow is a stack of
  screenshots. With one, it's a deliverable.

## A worked example

The user asked: "QA the new project-create flow on staging."

```
slideshow_create(
  title="Project-create flow QA on staging",
  description="Walking through the flow as a brand-new user would. Looking for friction, broken validation, and surprises."
)
# returns slideshow_id="ss_abc123"

# Slide 1: starting state
slideshow_add_slide(
  slideshow_id="ss_abc123",
  image_path="/tmp/01-empty-projects.png",
  caption="Logged in as a brand-new account. Projects list is empty as expected. The 'New Project' CTA is the only obvious next step."
)

# Slide 2: open the form
slideshow_add_slide(
  slideshow_id="ss_abc123",
  image_path="/tmp/02-form-open.png",
  caption="Clicked New Project. Modal opened with three fields: name, description, visibility. Defaulted to 'private' which feels right."
)

# Slide 3: submitted empty
slideshow_add_slide(
  slideshow_id="ss_abc123",
  image_path="/tmp/03-empty-submit.png",
  caption="Submitted with no name to test validation. Got an inline 'Name is required' error and the field highlighted in red. Good."
)

# ... 5 more slides through the flow ...

# Found a real bug
slideshow_add_slide(
  slideshow_id="ss_abc123",
  image_path="/tmp/09-bug-redirect.png",
  caption="Created a project named 'Test 1'. The success toast fired, but the redirect went to /projects/undefined instead of /projects/<id>. Bug: the response payload appears to be missing the 'id' field."
)

# Wrap with a summary
slideshow_set_summary(
  slideshow_id="ss_abc123",
  summary="Tested project creation end-to-end on staging. Form validation passed all five edge cases. One real bug: post-create redirect lands at /projects/undefined when the response is missing the id field (slide 9). Two minor copy issues flagged in slides 5 and 7."
)
```

The user gets a single share URL. They can paste it into Slack, a Linear
ticket, a PR description, or a cold-app message. That URL is the artifact.
The captions are what makes it worth opening.
