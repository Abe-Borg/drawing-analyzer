"""Read link / bookmark destinations and annotation rects straight from PDF objects.

Deliberately NOT ``page.get_links()`` / ``doc.get_toc()``: PyMuPDF's readers map
a stored destination back through its own transforms and reduce a ``/FitR``
rectangle to a point, so they cannot tell a correct destination from a wrong
one. Everything here is in the PDF's **default user space** — the space a
destination and an annotation ``/Rect`` share (PDF 32000-1 §12.3.2.2, §12.5.2),
which is what lets a test compare the two directly.
"""
from __future__ import annotations

import re

_NUM = r"(-?[\d.]+)"
_FITR = re.compile(rf"/FitR\s+{_NUM}\s+{_NUM}\s+{_NUM}\s+{_NUM}")
_RECT = re.compile(rf"/Rect\s*\[\s*{_NUM}\s+{_NUM}\s+{_NUM}\s+{_NUM}")


def _rect(match) -> tuple:
    a, b, c, d = (float(v) for v in match.groups())
    return (min(a, c), min(b, d), max(a, c), max(b, d))


def fit_rect_destinations(doc) -> dict:
    """Every ``/FitR`` destination in ``doc``, by the kind of object carrying it.

    ``{"link": [rect, …], "outline": [rect, …]}`` with each rect
    ``(left, bottom, right, top)``. Links are ordered top-of-page first by their
    own ``/Rect`` (so an index page's links come back in row order); outline
    entries in object order, which is the order the bookmarks were written.
    """
    links: list[tuple[float, tuple]] = []
    outline: list[tuple] = []
    for xref in range(1, doc.xref_length()):
        try:
            obj = doc.xref_object(xref, compressed=True)
        except Exception:  # noqa: BLE001 - a free/odd xref carries no destination
            continue
        dest = _FITR.search(obj)
        if not dest:
            continue
        if "/Title" in obj:
            outline.append(_rect(dest))
        elif "/Link" in obj:
            own = _RECT.search(obj)
            links.append((-(_rect(own)[3]) if own else 0.0, _rect(dest)))
    links.sort(key=lambda pair: pair[0])
    return {"link": [rect for _top, rect in links], "outline": outline}


def annot_user_rects(doc, page, subtype: str = "Square") -> list:
    """Raw ``/Rect`` of each ``subtype`` annotation on ``page``, in user space."""
    kind, value = doc.xref_get_key(page.xref, "Annots")
    if kind == "xref":
        value = doc.xref_object(int(value.split()[0]), compressed=True)
    out = []
    for xref in (int(n) for n in re.findall(r"(\d+) 0 R", value or "")):
        obj = doc.xref_object(xref, compressed=True)
        if f"/Subtype/{subtype}" in obj.replace(" ", ""):
            m = _RECT.search(obj)
            if m:
                out.append(_rect(m))
    return out


def contains(outer, inner, tol: float = 0.5) -> bool:
    """Whether rect ``outer`` contains rect ``inner`` (both l, b, r, t)."""
    return (
        outer[0] <= inner[0] + tol and outer[1] <= inner[1] + tol
        and outer[2] >= inner[2] - tol and outer[3] >= inner[3] - tol
    )


def callout_text_boxes(doc, page) -> list:
    """The text box of each FreeText **callout** on ``page``, in user space.

    A callout's ``/Rect`` also spans its leader, so it always touches the thing
    it points at; the box the words sit in is ``/Rect`` inset by ``/RD``
    (written by MuPDF as left, bottom, right, top differences).
    """
    kind, value = doc.xref_get_key(page.xref, "Annots")
    if kind == "xref":
        value = doc.xref_object(int(value.split()[0]), compressed=True)
    out = []
    for xref in (int(n) for n in re.findall(r"(\d+) 0 R", value or "")):
        obj = doc.xref_object(xref, compressed=True)
        if "FreeTextCallout" not in obj:
            continue
        rect = _RECT.search(obj)
        rd = re.search(rf"/RD\s*\[\s*{_NUM}\s+{_NUM}\s+{_NUM}\s+{_NUM}", obj)
        if rect and rd:
            left, bottom, right, top = _rect(rect)
            d = [float(v) for v in rd.groups()]
            out.append((left + d[0], bottom + d[1], right - d[2], top - d[3]))
    return out


def overlaps(a, b) -> bool:
    """Whether rects ``a`` and ``b`` (both l, b, r, t) share any area."""
    return a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]
