"""Document loaders and the path walker.

Loaders read a single file and yield one (or more) `Document`s. The
walker resolves a list of root paths plus include/exclude globs into a
stream of file paths. Both are sync — local disk only.
"""

from __future__ import annotations

import fnmatch
import hashlib
from collections.abc import Iterable
from pathlib import Path

from pebble.core.errors import PebbleError
from pebble.core.interfaces import Document

DOC_ID_LENGTH = 16


class UnsupportedFileType(PebbleError):
    """No loader is registered for this file's extension."""


class TextLoader:
    """Loader for plain-text and markdown files."""

    def load(self, path: Path) -> Iterable[Document]:
        text = path.read_text(encoding="utf-8", errors="replace")
        yield Document(
            doc_id=doc_id_for(path),
            source_path=str(path),
            text=text,
        )


class PdfLoader:
    """Loader for PDF files. Yields one Document per file, pages joined."""

    def load(self, path: Path) -> Iterable[Document]:
        import pypdf

        reader = pypdf.PdfReader(str(path))
        pages = [page.extract_text() or "" for page in reader.pages]
        yield Document(
            doc_id=doc_id_for(path),
            source_path=str(path),
            text="\n\n".join(pages),
            metadata={"pages": len(pages)},
        )


_LOADER_BY_SUFFIX: dict[str, type[TextLoader] | type[PdfLoader]] = {
    ".txt": TextLoader,
    ".md": TextLoader,
    ".markdown": TextLoader,
    ".pdf": PdfLoader,
}


def loader_for(path: Path) -> TextLoader | PdfLoader:
    cls = _LOADER_BY_SUFFIX.get(path.suffix.lower())
    if cls is None:
        raise UnsupportedFileType(
            f"no loader registered for suffix {path.suffix!r} ({path})"
        )
    return cls()


def doc_id_for(path: Path) -> str:
    """Stable, short document ID derived from the absolute path.

    Same path → same ID across runs. `pebble delete <doc_id>` then becomes
    a meaningful operator command.
    """
    canonical = str(path.resolve())
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return digest[:DOC_ID_LENGTH]


def walk_paths(
    roots: Iterable[Path],
    include: list[str],
    exclude: list[str],
) -> Iterable[Path]:
    """Yield files under `roots` matching `include` and not `exclude`.

    `roots` may contain a mix of files and directories. Patterns are
    standard fnmatch globs; `**` matches any number of path components.
    """

    seen: set[Path] = set()
    for root in roots:
        for path in _walk_one(root):
            if path in seen or not path.is_file():
                continue
            if not _matches_any(path, include):
                continue
            if _matches_any(path, exclude):
                continue
            seen.add(path)
            yield path


def _walk_one(root: Path) -> Iterable[Path]:
    if root.is_file():
        yield root
        return
    if not root.exists():
        return
    yield from root.rglob("*")


def _matches_any(path: Path, patterns: list[str]) -> bool:
    if not patterns:
        return False
    name = path.name
    posix = path.as_posix()
    for pattern in patterns:
        if "/" in pattern:
            if fnmatch.fnmatch(posix, pattern):
                return True
        elif fnmatch.fnmatch(name, pattern):
            return True
    return False
