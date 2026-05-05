'''Wire-format models for talking to the agentclip backend.

Kept separate from the public SDK surface so we can evolve transport
shapes (multipart vs JSON, field renames the backend may do) without
churning the SDK call signatures users write against.
'''

from __future__ import annotations

from pydantic import BaseModel, Field


class SlideshowCreated(BaseModel):
    '''Response from POST /api/slideshow/.'''

    id: str
    share_url: str
    write_token: str = Field(repr=False)


class SlideAdded(BaseModel):
    '''Response from POST /api/slideshow/<id>/slides/.'''

    id: int
    position: int
    caption: str
    media_url: str


class SlideUpdated(BaseModel):
    '''Response from PATCH /api/slideshow/<id>/slides/<position>/.'''

    id: int
    position: int
    caption: str
    media_url: str


class SlideshowPatched(BaseModel):
    '''Response from PATCH /api/slideshow/<id>/.'''

    id: str
    title: str | None = None
    description: str | None = None
    summary: str | None = None
