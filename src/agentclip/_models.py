"""Wire-format models for talking to the agentclip backend.

Kept separate from the public SDK surface so we can evolve transport
shapes (multipart vs JSON, field renames the backend may do) without
churning the SDK call signatures users write against.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class SlideshowCreated(BaseModel):
    """Response from POST /api/slideshow/."""

    id: str
    share_url: str
    write_token: str = Field(repr=False)
    # Render-artifact URLs surfaced by the backend so the agent / user
    # can echo them at create time. They resolve lazily — first fetch
    # triggers a render — and are pre-warmed on `agentclip slideshow
    # summary`. Optional so older API versions that haven't deployed
    # the render pipeline still parse cleanly.
    clip_mp4_url: str | None = None
    clip_pdf_url: str | None = None
    embed_url: str | None = None
    edit_url: str | None = None


class SlideAdded(BaseModel):
    """Response from POST /api/slideshow/<id>/slides/."""

    id: int
    position: int
    caption: str
    media_url: str


class SlideUpdated(BaseModel):
    """Response from PATCH /api/slideshow/<id>/slides/<position>/."""

    id: int
    position: int
    caption: str
    media_url: str


class SlideshowPatched(BaseModel):
    """Response from PATCH /api/slideshow/<id>/."""

    id: str
    title: str | None = None
    description: str | None = None
    summary: str | None = None


class RenderRefreshed(BaseModel):
    """Response from POST /api/v1/slideshow/<token>/render-bump/.

    Optional escape hatch — `agentclip slideshow regenerate-clip` calls
    this to force a fresh render after, e.g., a remote retry exhaustion.
    """

    status: str
    render_version: int
