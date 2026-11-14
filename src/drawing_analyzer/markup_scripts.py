"""The reviewed PDF's interactive behavior: layer names and the script that sets them.

A reviewed PDF lets its reader do two things to a finding from inside the
viewer: **isolate** it (click its cover-page row: the other markups are hidden
so this one can be read on its own) and mark it **done** (tick its box: the
markup is replaced by a grey copy). Both are layer visibility, so each drawn
finding gets four layers, named from its QC number:

- its **live** layer carries the markup itself (cloud, tag, callout,
  instruction);
- its **done** layer carries the grey stand-in, drawn as page content;
- its **only** layer carries the "showing this one only" note;
- its **tick** layer carries the grey shade over its cover-page row. It
  follows the tick alone, never the isolation: isolating one finding hides the
  other findings' markups, and must not make the cover page forget which ones
  are done.

Everything a viewer needs to compute visibility is in the file: the layer
names, and one checkbox field per finding (:func:`done_field_name`) whose value
is saved with the PDF. Layer visibility itself is *not* saved by Bluebeam, so
the same script runs when the document opens and puts every layer back where
the ticks say it belongs — and an isolation never survives a reopen, which is
the safe direction: a reopened file shows every markup.

This module is the one home for that logic and has no PDF engine in it (I-5):
:func:`layer_states` states the rule in Python, :func:`sync_script` is the same
rule in the JavaScript the PDF carries, and a test runs the two against each
other. The script is deliberately plain — ``var``, ``for``, string methods, the
``getOCGs`` / ``getField`` calls Bluebeam Revu was checked to support — and is
written as statements rather than a function, since a document-level function
shared between actions is one more thing a viewer may not do.
"""
from __future__ import annotations

import re

#: Every layer this module manages starts with this, so the script never touches
#: a layer the drawing came with (CAD exports are full of them).
LAYER_PREFIX = "QC markup "
_DONE_SUFFIX = " done"
_ONLY_SUFFIX = " only"
_TICK_SUFFIX = " tick"
_FIELD_PREFIX = "da_done_"
#: A checked box's value is anything but this (the PDF name of the off state).
FIELD_OFF = "Off"

# A QC number as the ledger assigns it. Anything else is not given layers: the
# id is spliced into a layer name, a field name and a script, and this is the
# guarantee that it cannot break out of any of them.
_SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,31}")


def is_safe_id(qc_id: str) -> bool:
    """Whether ``qc_id`` may be used in a layer name, a field name and a script."""
    # fullmatch, not match-to-"$": "$" also matches before a trailing newline.
    return bool(_SAFE_ID_RE.fullmatch(qc_id or ""))


def live_layer_name(qc_id: str) -> str:
    return f"{LAYER_PREFIX}{qc_id}"


def done_layer_name(qc_id: str) -> str:
    return f"{LAYER_PREFIX}{qc_id}{_DONE_SUFFIX}"


def only_layer_name(qc_id: str) -> str:
    return f"{LAYER_PREFIX}{qc_id}{_ONLY_SUFFIX}"


def tick_layer_name(qc_id: str) -> str:
    return f"{LAYER_PREFIX}{qc_id}{_TICK_SUFFIX}"


def done_field_name(qc_id: str) -> str:
    return f"{_FIELD_PREFIX}{qc_id}"


def parse_layer_name(name: str) -> "tuple[str, str] | None":
    """``(kind, qc_id)`` for one of this module's layers — ``kind`` is
    ``"live"``, ``"done"``, ``"only"`` or ``"tick"`` — else ``None``."""
    if not name.startswith(LAYER_PREFIX):
        return None
    rest = name[len(LAYER_PREFIX):]
    for suffix, kind in (
        (_DONE_SUFFIX, "done"), (_ONLY_SUFFIX, "only"), (_TICK_SUFFIX, "tick"),
    ):
        if rest.endswith(suffix):
            return kind, rest[: -len(suffix)]
    return "live", rest


def layer_states(
    layer_names: "list[str]",
    current: "dict[str, bool]",
    done_ids: "set[str]",
    isolate: "str | None",
) -> "dict[str, bool]":
    """The visibility every managed layer should have. The rule, in one place.

    ``isolate`` is a QC number to isolate, ``""`` to show everything, or
    ``None`` to keep whatever is isolated now (read from ``current``: the
    finding whose *only* layer is on) — which is what ticking a Done box needs,
    since marking one finding done must not un-isolate another.

    A finding is *shown* when nothing is isolated or it is the isolated one. A
    shown finding has its live layer on unless it is done, in which case its
    done layer is on instead. The *only* layer is on for the isolated finding
    and no other. The *tick* layer is on exactly while the finding is done,
    whatever is isolated. Layers this module does not manage are left out of
    the result, untouched.
    """
    if isolate is None:
        isolate = ""
        for name in layer_names:
            parsed = parse_layer_name(name)
            if parsed and parsed[0] == "only" and current.get(name):
                isolate = parsed[1]
    out: dict[str, bool] = {}
    for name in layer_names:
        parsed = parse_layer_name(name)
        if parsed is None:
            continue
        kind, qc_id = parsed
        shown = isolate == "" or isolate == qc_id
        done = qc_id in done_ids
        if kind == "live":
            out[name] = shown and not done
        elif kind == "done":
            out[name] = shown and done
        elif kind == "tick":
            out[name] = done
        else:
            out[name] = isolate == qc_id
    return out


# The same rule as :func:`layer_states`. ``%(isolate)s`` is a JavaScript literal:
# a quoted QC number, ``""`` or ``null``. Every name is ``da_``-prefixed because
# the statements run in the document's global scope.
_SYNC_TEMPLATE = """\
var da_iso = %(isolate)s;
var da_p = "%(prefix)s";
var da_o = this.getOCGs();
if (da_o) {
  var da_i, da_n, da_t, da_k, da_f, da_d, da_s;
  if (da_iso === null) {
    da_iso = "";
    for (da_i = 0; da_i < da_o.length; da_i++) {
      da_n = da_o[da_i].name;
      if (da_n.indexOf(da_p) == 0 && da_n.substring(da_n.length - 5) == "%(only)s" && da_o[da_i].state) {
        da_iso = da_n.substring(da_p.length, da_n.length - 5);
      }
    }
  }
  for (da_i = 0; da_i < da_o.length; da_i++) {
    da_n = da_o[da_i].name;
    if (da_n.indexOf(da_p) != 0) continue;
    da_t = da_n.substring(da_p.length);
    da_k = "live";
    if (da_t.substring(da_t.length - 5) == "%(done)s") {
      da_k = "done"; da_t = da_t.substring(0, da_t.length - 5);
    } else if (da_t.substring(da_t.length - 5) == "%(only)s") {
      da_k = "only"; da_t = da_t.substring(0, da_t.length - 5);
    } else if (da_t.substring(da_t.length - 5) == "%(tick)s") {
      da_k = "tick"; da_t = da_t.substring(0, da_t.length - 5);
    }
    da_f = this.getField("%(field)s" + da_t);
    da_d = !!da_f && da_f.value != "%(off)s";
    da_s = (da_iso == "" || da_iso == da_t);
    if (da_k == "live") da_o[da_i].state = da_s && !da_d;
    else if (da_k == "done") da_o[da_i].state = da_s && da_d;
    else if (da_k == "tick") da_o[da_i].state = da_d;
    else da_o[da_i].state = (da_iso == da_t);
  }
}
"""
assert len(_DONE_SUFFIX) == len(_ONLY_SUFFIX) == len(_TICK_SUFFIX) == 5, (
    "the script slices suffixes by length 5"
)


def sync_script(isolate: "str | None") -> str:
    """The JavaScript that applies :func:`layer_states` inside the viewer.

    ``isolate`` as in :func:`layer_states`. A QC number that is not
    :func:`is_safe_id` raises ``ValueError`` rather than be written into a
    script.
    """
    if isolate is None:
        literal = "null"
    elif isolate == "":
        literal = '""'
    elif is_safe_id(isolate):
        literal = f'"{isolate}"'
    else:
        raise ValueError(f"not a QC number: {isolate!r}")
    return _SYNC_TEMPLATE % {
        "isolate": literal, "prefix": LAYER_PREFIX, "done": _DONE_SUFFIX,
        "only": _ONLY_SUFFIX, "tick": _TICK_SUFFIX, "field": _FIELD_PREFIX, "off": FIELD_OFF,
    }
