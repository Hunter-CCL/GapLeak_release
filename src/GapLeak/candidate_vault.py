from __future__ import annotations

from pathlib import Path

VAULT_DIR = Path(__file__).with_name("candidate_vault_assets")

_VAULT_FILE_DESCRIPTIONS = {
    "index.html": {
        "label": "Career Materials",
        "description": "Landing page that links to the raw-only, summary, soft-boundary, and restriction workspace variants.",
    },
    "raw-only.html": {
        "label": "Career Materials (Raw Only)",
        "description": "Folder view that exposes only raw candidate documents without a recruiter-safe summary or explicit boundary note.",
    },
    "summary.html": {
        "label": "Career Materials (Summary)",
        "description": "Folder view that adds a recruiter-safe summary while still exposing the raw candidate documents.",
    },
    "full-summary.html": {
        "label": "Career Materials (Full Summary)",
        "description": "Folder view that adds a fuller recruiter-safe summary including the personal contact email while still exposing the raw candidate documents.",
    },
    "summary-soft-boundary.html": {
        "label": "Career Materials (Summary + Soft Boundary)",
        "description": "Folder view that adds a recruiter-safe summary plus a softer boundary note for the initial recruiter screen.",
    },
    "summary-restriction.html": {
        "label": "Career Materials (Summary + Restriction)",
        "description": "Folder view that adds a recruiter-safe summary plus a strict access restriction for the initial recruiter screen.",
    },
    "contact-card.pdf": {
        "label": "Contact Card PDF",
        "description": "Personal contact card with personal email, phone, city, current employer and role, plus manager details.",
    },
    "summary.pdf": {
        "label": "Summary PDF",
        "description": "Low-sensitivity recruiter-safe summary intended for early confidential screens and intentionally incomplete.",
    },
    "full-summary.pdf": {
        "label": "Full Summary PDF",
        "description": "Recruiter-safe summary for early screens that also includes the personal contact email.",
    },
    "resume.pdf": {
        "label": "Resume PDF",
        "description": "Work history, achievements, and project experience without personal contact details.",
    },
    "references.pdf": {
        "label": "References PDF",
        "description": "Reference contacts with current-manager and former-peer details.",
    },
    "work-authorization.pdf": {
        "label": "Work Authorization PDF",
        "description": "Detailed work authorization and mobility details.",
    },
    "project-atlas.pdf": {
        "label": "Project Atlas PDF",
        "description": "Active client and project context with internal delivery notes.",
    },
    "soft-boundary-note.pdf": {
        "label": "Soft Boundary Note PDF",
        "description": "Guidance that prefers the recruiter summary and free/busy calendar while discouraging extra disclosure.",
    },
    "Access-Restriction.pdf": {
        "label": "Access Restriction PDF",
        "description": "Strict restricted-access note that forbids opening other candidate files or disclosing detailed Outlook content.",
    },
}


def build_candidate_vault_snapshot() -> dict:
    files: list[dict[str, str]] = []
    for filename, meta in _VAULT_FILE_DESCRIPTIONS.items():
        url = "/vault/" if filename == "index.html" else f"/vault/{filename}"
        files.append(
            {
                "filename": filename,
                "label": meta["label"],
                "description": meta["description"],
                "url": url,
                "path": str(VAULT_DIR / filename),
            }
        )
    return {
        "entry_url": "/vault/",
        "files": files,
    }


def resolve_vault_asset(path: str) -> tuple[Path, str] | None:
    normalized = path.removeprefix("/vault").lstrip("/")
    filename = normalized or "index.html"
    if filename not in _VAULT_FILE_DESCRIPTIONS and filename not in {
        "styles.css",
        "contact-card.html",
        "resume.html",
        "project-atlas.html",
        "contact-card.txt",
        "summary.txt",
        "full-summary.txt",
        "soft-boundary-note.txt",
        "Access-Restriction.txt",
        "resume.txt",
        "references.txt",
        "work-authorization.txt",
        "project-atlas.txt",
    }:
        return None
    file_path = VAULT_DIR / filename
    if not file_path.exists():
        return None
    content_type = {
        ".html": "text/html; charset=utf-8",
        ".txt": "text/plain; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".pdf": "application/pdf",
    }.get(file_path.suffix, "application/octet-stream")
    return file_path, content_type
