"""Small, durable storage for expiring, shareable music playlists."""

from __future__ import annotations

import json
import re
import secrets
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Callable, Mapping


CODE_PATTERN = re.compile(r"^[a-z0-9]{4}-[a-z0-9]{4}$")
CODE_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"
DEFAULT_EXPIRY = timedelta(days=30)


@dataclass(frozen=True)
class SavedPlaylist:
    """Validated metadata and tracks for one saved playlist."""

    code: str
    owner_id: int
    created_at: datetime
    expires_at: datetime
    tracks: list[dict[str, str]]


class PlaylistStoreError(Exception):
    """Base exception for a saved-playlist storage problem."""


class PlaylistNotFoundError(PlaylistStoreError):
    """The supplied code does not identify a stored playlist."""


class PlaylistExpiredError(PlaylistStoreError):
    """The supplied code identifies an expired playlist."""


class PlaylistDataError(PlaylistStoreError):
    """Stored playlist JSON is malformed or otherwise unusable."""


def generate_playlist_code() -> str:
    """Return a code suitable for use as a playlist identifier."""
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(4)) + "-" + "".join(
        secrets.choice(CODE_ALPHABET) for _ in range(4)
    )


class PlaylistStore:
    """A locked JSON datastore with creator metadata and expiring playlists."""

    def __init__(
        self,
        storage_dir: str | Path = "data/playlists",
        *,
        expiry: timedelta = DEFAULT_EXPIRY,
        now: Callable[[], datetime] | None = None,
        code_factory: Callable[[], str] = generate_playlist_code,
    ):
        self.storage_dir = Path(storage_dir)
        self.path = self.storage_dir / "playlists.json"
        self.expiry = expiry
        self._now = now or (lambda: datetime.now(UTC))
        self._code_factory = code_factory
        self._lock = threading.Lock()

    def save(self, owner_id: int, tracks: list[Mapping[str, str]]) -> str:
        clean_tracks = self._validate_tracks(tracks)
        with self._lock:
            data = self._read()
            code = self._new_code(data["playlists"])
            now = self._now()
            data["playlists"][code] = {
                "owner_id": owner_id,
                "created_at": now.isoformat(),
                "expires_at": (now + self.expiry).isoformat(),
                "tracks": clean_tracks,
            }
            self._write(data)
        return code

    def load(self, code: str) -> list[dict[str, str]]:
        normalized_code = self._normalize_code(code)
        with self._lock:
            data = self._read()
            return self._playlist_info(data, normalized_code).tracks

    def consume(self, code: str) -> list[dict[str, str]]:
        """Return a valid playlist and permanently remove it in the same write."""
        normalized_code = self._normalize_code(code)
        with self._lock:
            data = self._read()
            tracks = self._playlist_info(data, normalized_code).tracks
            del data["playlists"][normalized_code]
            self._write(data)
        return tracks

    def details(self, code: str) -> SavedPlaylist:
        """Return display metadata without consuming a valid playlist."""
        normalized_code = self._normalize_code(code)
        with self._lock:
            return self._playlist_info(self._read(), normalized_code)

    def list_playlists(self) -> list[SavedPlaylist]:
        """Return all valid, unexpired playlists ordered by most recent first."""
        with self._lock:
            data = self._read()
            playlists: list[SavedPlaylist] = []
            for code in list(data["playlists"]):
                try:
                    playlists.append(self._playlist_info(data, code))
                except (PlaylistDataError, PlaylistExpiredError):
                    # One bad or expired record should not hide the usable list.
                    continue
        return sorted(playlists, key=lambda playlist: playlist.created_at, reverse=True)

    @staticmethod
    def _normalize_code(code: str) -> str:
        normalized_code = code.strip().lower()
        if not CODE_PATTERN.fullmatch(normalized_code):
            raise PlaylistNotFoundError("Invalid playlist code format")
        return normalized_code

    def _playlist_info(
        self, data: dict[str, dict[str, object]], code: str
    ) -> SavedPlaylist:
        playlist = data["playlists"].get(code)
        if not isinstance(playlist, dict):
            raise PlaylistNotFoundError("Playlist code does not exist")

        owner_id = playlist.get("owner_id")
        if not isinstance(owner_id, int) or isinstance(owner_id, bool):
            raise PlaylistDataError("Playlist owner is invalid")

        created_at = self._parse_timestamp(playlist.get("created_at"), "creation time")
        expires_at = self._parse_timestamp(playlist.get("expires_at"), "expiry")
        if expires_at <= self._now():
            del data["playlists"][code]
            self._write(data)
            raise PlaylistExpiredError("Playlist code has expired")

        return SavedPlaylist(
            code=code,
            owner_id=owner_id,
            created_at=created_at,
            expires_at=expires_at,
            tracks=self._validate_tracks(playlist.get("tracks")),
        )

    def _new_code(self, playlists: Mapping[str, object]) -> str:
        for _ in range(100):
            code = self._code_factory().lower()
            if CODE_PATTERN.fullmatch(code) and code not in playlists:
                return code
        raise PlaylistStoreError("Could not generate a unique playlist code")

    def _read(self) -> dict[str, dict[str, object]]:
        if not self.path.exists():
            return {"version": 1, "playlists": {}}
        try:
            with self.path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, json.JSONDecodeError) as error:
            raise PlaylistDataError("Playlist datastore is unreadable") from error

        if (
            not isinstance(data, dict)
            or data.get("version") != 1
            or not isinstance(data.get("playlists"), dict)
        ):
            raise PlaylistDataError("Playlist datastore has an unsupported format")
        return data

    def _write(self, data: Mapping[str, object]) -> None:
        try:
            self.storage_dir.mkdir(parents=True, exist_ok=True)
            temporary_path = self.path.with_suffix(".tmp")
            with temporary_path.open("w", encoding="utf-8") as file:
                json.dump(data, file, ensure_ascii=False, separators=(",", ":"))
            temporary_path.replace(self.path)
        except OSError as error:
            raise PlaylistStoreError("Could not save playlist data") from error

    @staticmethod
    def _parse_timestamp(value: object, field_name: str) -> datetime:
        if not isinstance(value, str):
            raise PlaylistDataError(f"Playlist {field_name} is missing")
        try:
            timestamp = datetime.fromisoformat(value)
        except ValueError as error:
            raise PlaylistDataError(f"Playlist {field_name} is invalid") from error
        if timestamp.tzinfo is None:
            raise PlaylistDataError(f"Playlist {field_name} has no timezone")
        return timestamp.astimezone(UTC)

    @staticmethod
    def _validate_tracks(tracks: object) -> list[dict[str, str]]:
        if not isinstance(tracks, list) or not tracks:
            raise PlaylistDataError("Playlist has no tracks")

        clean_tracks: list[dict[str, str]] = []
        for track in tracks:
            if not isinstance(track, Mapping):
                raise PlaylistDataError("Playlist track is invalid")
            query = track.get("query")
            title = track.get("title")
            if not isinstance(query, str) or not query.strip():
                raise PlaylistDataError("Playlist track has no search query")
            clean_tracks.append(
                {"query": query.strip(), "title": title.strip() if isinstance(title, str) else ""}
            )
        return clean_tracks
