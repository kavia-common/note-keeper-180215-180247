from typing import List, Optional, Dict, Any
from fastapi import FastAPI, Depends, HTTPException, status, Query, Path
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime, timezone
from threading import RLock

# Application metadata for OpenAPI
app = FastAPI(
    title="Notes API",
    description="A simple Notes service providing CRUD operations with search and pagination.",
    version="1.0.0",
    openapi_tags=[
        {"name": "health", "description": "Service health endpoints"},
        {"name": "notes", "description": "Operations on notes resources"},
        {"name": "utils", "description": "Utility and seed endpoints for development"},
    ],
)

# CORS configuration for localhost origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost",
        "http://localhost:3000",
        "http://127.0.0.1",
        "http://127.0.0.1:3000",
        "https://localhost",
        "https://127.0.0.1",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================
# Models / Schemas
# =========================

class NoteBase(BaseModel):
    title: str = Field(..., description="Title of the note", min_length=1, max_length=200)
    content: str = Field(..., description="Content of the note", min_length=1)
    tags: Optional[List[str]] = Field(default=None, description="Optional list of tags")


class NoteCreate(NoteBase):
    """Schema for creating a note."""
    pass


class NoteUpdate(BaseModel):
    title: Optional[str] = Field(default=None, description="New title", min_length=1, max_length=200)
    content: Optional[str] = Field(default=None, description="New content", min_length=1)
    tags: Optional[List[str]] = Field(default=None, description="New tags list (replaces existing)")


class Note(NoteBase):
    id: int = Field(..., description="Unique identifier of the note")
    created_at: datetime = Field(..., description="Creation timestamp in UTC")
    updated_at: datetime = Field(..., description="Last update timestamp in UTC")

    model_config = ConfigDict(from_attributes=True)


class PaginatedNotes(BaseModel):
    items: List[Note] = Field(..., description="List of notes for the current page")
    total: int = Field(..., description="Total number of notes")
    page: int = Field(..., description="Current page index (1-based)")
    page_size: int = Field(..., description="Number of items per page")


# =========================
# Thread-safe In-Memory Storage
# =========================

class InMemoryNoteStore:
    """
    Thread-safe, in-memory storage for notes.
    This serves as a simple repository until a database is integrated.
    """
    def __init__(self):
        self._notes: Dict[int, Note] = {}
        self._lock = RLock()
        self._next_id = 1

    def _utcnow(self) -> datetime:
        return datetime.now(timezone.utc)

    # PUBLIC_INTERFACE
    def list_notes(self, q: Optional[str], page: int, page_size: int) -> PaginatedNotes:
        """List notes with optional search and pagination."""
        with self._lock:
            notes = list(self._notes.values())

            if q:
                q_lower = q.lower()
                notes = [
                    n for n in notes
                    if (q_lower in n.title.lower()) or (q_lower in n.content.lower())
                ]

            total = len(notes)
            start = (page - 1) * page_size
            end = start + page_size
            page_items = notes[start:end]

            return PaginatedNotes(items=page_items, total=total, page=page, page_size=page_size)

    # PUBLIC_INTERFACE
    def create_note(self, data: NoteCreate) -> Note:
        """Create and store a new note."""
        with self._lock:
            now = self._utcnow()
            note = Note(
                id=self._next_id,
                title=data.title,
                content=data.content,
                tags=data.tags or [],
                created_at=now,
                updated_at=now,
            )
            self._notes[self._next_id] = note
            self._next_id += 1
            return note

    # PUBLIC_INTERFACE
    def get_note(self, note_id: int) -> Optional[Note]:
        """Get a note by id."""
        with self._lock:
            return self._notes.get(note_id)

    # PUBLIC_INTERFACE
    def update_note(self, note_id: int, patch: NoteUpdate) -> Optional[Note]:
        """Update an existing note fields."""
        with self._lock:
            existing = self._notes.get(note_id)
            if not existing:
                return None

            updated_fields: Dict[str, Any] = {}
            if patch.title is not None:
                updated_fields["title"] = patch.title
            if patch.content is not None:
                updated_fields["content"] = patch.content
            if patch.tags is not None:
                updated_fields["tags"] = patch.tags

            if updated_fields:
                for k, v in updated_fields.items():
                    setattr(existing, k, v)
                existing.updated_at = self._utcnow()

            return existing

    # PUBLIC_INTERFACE
    def delete_note(self, note_id: int) -> bool:
        """Delete a note by id."""
        with self._lock:
            if note_id in self._notes:
                del self._notes[note_id]
                return True
            return False

    # PUBLIC_INTERFACE
    def seed(self, count: int = 5) -> int:
        """Seed the store with demo notes."""
        with self._lock:
            for i in range(count):
                self.create_note(
                    NoteCreate(
                        title=f"Sample Note {i + 1}",
                        content=f"This is a sample note #{i + 1}.",
                        tags=["sample", "demo"] if i % 2 == 0 else ["notes"],
                    )
                )
            return count

    # PUBLIC_INTERFACE
    def reset(self) -> None:
        """Clear the store."""
        with self._lock:
            self._notes.clear()
            self._next_id = 1


# Single store instance for the app lifecycle
store = InMemoryNoteStore()


# Dependency to inject the store (extensible for future database refactor)
def get_store() -> InMemoryNoteStore:
    return store


# =========================
# Routes
# =========================

@app.get(
    "/health",
    tags=["health"],
    summary="Health Check",
    description="Returns service health status for readiness/liveness probes.",
    response_model=dict,
)
def health_check() -> dict:
    """
    Health Check endpoint.

    Returns:
        JSON object containing service status.
    """
    return {"status": "ok"}


@app.post(
    "/notes",
    tags=["notes"],
    summary="Create a note",
    description="Create a new note with title, content, and optional tags.",
    status_code=status.HTTP_201_CREATED,
    response_model=Note,
)
def create_note_endpoint(payload: NoteCreate, repo: InMemoryNoteStore = Depends(get_store)) -> Note:
    """
    Create Note.

    Parameters:
        payload: NoteCreate - The note content to create.

    Returns:
        The created note with generated id and timestamps.
    """
    return repo.create_note(payload)


@app.get(
    "/notes",
    tags=["notes"],
    summary="List notes",
    description="List notes with optional full-text search over title and content, with pagination.",
    response_model=PaginatedNotes,
)
def list_notes_endpoint(
    page: int = Query(1, ge=1, description="Page number starting from 1"),
    page_size: int = Query(10, ge=1, le=100, description="Number of items per page"),
    q: Optional[str] = Query(None, description="Search query for title/content"),
    repo: InMemoryNoteStore = Depends(get_store),
) -> PaginatedNotes:
    """
    List Notes with pagination and optional search.

    Parameters:
        page: int - Page number (1-based).
        page_size: int - Items per page (1-100).
        q: Optional[str] - Search query.

    Returns:
        PaginatedNotes containing items and metadata.
    """
    return repo.list_notes(q=q, page=page, page_size=page_size)


@app.get(
    "/notes/{note_id}",
    tags=["notes"],
    summary="Get a note",
    description="Retrieve a single note by its ID.",
    response_model=Note,
    responses={
        404: {"description": "Note not found", "content": {"application/json": {"example": {"detail": "Note not found"}}}}
    },
)
def get_note_endpoint(
    note_id: int = Path(..., ge=1, description="ID of the note to retrieve"),
    repo: InMemoryNoteStore = Depends(get_store),
) -> Note:
    """
    Get a Note by ID.

    Parameters:
        note_id: int - The note identifier.

    Returns:
        The corresponding Note if found.

    Raises:
        HTTPException 404 if the note does not exist.
    """
    note = repo.get_note(note_id)
    if not note:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")
    return note


@app.put(
    "/notes/{note_id}",
    tags=["notes"],
    summary="Update a note",
    description="Update the title, content, or tags of a note by ID.",
    response_model=Note,
    responses={
        404: {"description": "Note not found", "content": {"application/json": {"example": {"detail": "Note not found"}}}}
    },
)
def update_note_endpoint(
    note_id: int = Path(..., ge=1, description="ID of the note to update"),
    patch: NoteUpdate = ...,
    repo: InMemoryNoteStore = Depends(get_store),
) -> Note:
    """
    Update a Note.

    Parameters:
        note_id: int - The note identifier.
        patch: NoteUpdate - Fields to update.

    Returns:
        The updated note.

    Raises:
        HTTPException 404 if the note does not exist.
    """
    updated = repo.update_note(note_id, patch)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")
    return updated


@app.delete(
    "/notes/{note_id}",
    tags=["notes"],
    summary="Delete a note",
    description="Delete a note by its ID.",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        204: {"description": "Deleted successfully"},
        404: {"description": "Note not found", "content": {"application/json": {"example": {"detail": "Note not found"}}}},
    },
)
def delete_note_endpoint(
    note_id: int = Path(..., ge=1, description="ID of the note to delete"),
    repo: InMemoryNoteStore = Depends(get_store),
) -> None:
    """
    Delete a Note.

    Parameters:
        note_id: int - The note identifier.

    Returns:
        204 No Content on success.

    Raises:
        HTTPException 404 if the note does not exist.
    """
    ok = repo.delete_note(note_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")
    return None


@app.post(
    "/utils/seed",
    tags=["utils"],
    summary="Seed sample notes",
    description="Seeds the store with sample notes for development purposes.",
    response_model=dict,
)
def seed_notes_endpoint(
    count: int = Query(5, ge=1, le=100, description="Number of sample notes to create"),
    repo: InMemoryNoteStore = Depends(get_store),
) -> dict:
    """
    Seed sample notes.

    Parameters:
        count: int - How many notes to seed.

    Returns:
        JSON with number of created notes.
    """
    created = repo.seed(count=count)
    return {"created": created}


@app.post(
    "/utils/reset",
    tags=["utils"],
    summary="Reset note store",
    description="Clears the in-memory store and resets IDs.",
    response_model=dict,
)
def reset_store_endpoint(repo: InMemoryNoteStore = Depends(get_store)) -> dict:
    """
    Reset the in-memory note store.

    Returns:
        JSON confirmation of reset.
    """
    repo.reset()
    return {"status": "reset"}
