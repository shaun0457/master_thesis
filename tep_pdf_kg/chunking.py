from __future__ import annotations

from .schema import ChunkRecord, NormalizedDocument, slugify


def build_chunks(document: NormalizedDocument, min_chars: int = 80, max_chars: int = 900) -> list[ChunkRecord]:
    chunks: list[ChunkRecord] = []
    pending_text: list[str] = []
    pending_refs: list[str] = []
    pending_bbox = None
    pending_pages: list[int] = []
    current_heading = "Document"
    heading_path = ["Document"]

    def flush() -> None:
        nonlocal pending_text, pending_refs, pending_bbox, pending_pages, current_heading, heading_path
        text = "\n\n".join(part.strip() for part in pending_text if part.strip()).strip()
        if not text:
            pending_text = []
            pending_refs = []
            pending_pages = []
            pending_bbox = None
            return
        if len(text) < min_chars and chunks and chunks[-1].section_title == current_heading:
            chunks[-1].text_md = f"{chunks[-1].text_md}\n\n{text}".strip()
            chunks[-1].page_end = max(chunks[-1].page_end, max(pending_pages or [chunks[-1].page_end]))
            chunks[-1].element_refs.extend(pending_refs)
        else:
            chunk_index = len(chunks)
            chunk_id = f"{document.doc_id}__chunk_{chunk_index:04d}_{slugify(current_heading)}"
            chunks.append(
                ChunkRecord(
                    doc_id=document.doc_id,
                    chunk_id=chunk_id,
                    section_title=current_heading,
                    page_start=min(pending_pages or [1]),
                    page_end=max(pending_pages or [1]),
                    chunk_index=chunk_index,
                    text_md=text,
                    chunk_type="section_paragraph",
                    parser_used=document.parser_used,
                    prev_chunk_id=chunks[-1].chunk_id if chunks else None,
                    next_chunk_id=None,
                    bbox=pending_bbox,
                    element_refs=pending_refs[:],
                    heading_path=heading_path[:],
                    review_status="pending",
                )
            )
        pending_text = []
        pending_refs = []
        pending_pages = []
        pending_bbox = None

    for section in document.sections:
        section_heading = section.heading_path[-1] if section.heading_path else "Document"
        section_path = section.heading_path[:] or ["Document"]
        text = section.text_md.strip()
        if not text:
            continue
        if section_heading != current_heading and pending_text:
            flush()
        current_heading = section_heading
        heading_path = section_path
        projected = "\n\n".join(pending_text + [text]).strip()
        if pending_text and len(projected) > max_chars:
            flush()
        pending_text.append(text)
        if section.element_ref:
            pending_refs.append(section.element_ref)
        pending_pages.extend([section.page_start, section.page_end])
        if pending_bbox is None and section.bbox is not None:
            pending_bbox = section.bbox

    flush()

    for idx, chunk in enumerate(chunks):
        chunk.prev_chunk_id = chunks[idx - 1].chunk_id if idx > 0 else None
        chunk.next_chunk_id = chunks[idx + 1].chunk_id if idx + 1 < len(chunks) else None

    return chunks
