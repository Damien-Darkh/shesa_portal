"""Converts the profile editor's HTML into Sanity Portable Text.

Supported: paragraphs, headings (h2-h4), blockquotes, bullet and numbered lists (nested),
bold, italic, underline, strikethrough, inline code, and http(s) links.
"""
import re
import secrets
from html.parser import HTMLParser

MARKS = {"strong": "strong", "b": "strong", "em": "em", "i": "em", "u": "underline",
         "s": "strike-through", "strike": "strike-through", "del": "strike-through", "code": "code"}
HEADINGS = {"h1": "h2", "h2": "h2", "h3": "h3", "h4": "h4", "h5": "h4", "h6": "h4"}


def _key() -> str:
    return secrets.token_hex(6)


def _span(text: str, marks=None) -> dict:
    return {"_type": "span", "_key": _key(), "text": text, "marks": marks or []}


class _Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks = []
        self.cur = None
        self.lists = []   # "bullet" / "number" for each open list
        self.marks = []   # (tag, mark) for each open inline tag
        self.quote = 0

    def _new(self, style="normal", list_item=None):
        self.flush()
        if style == "normal" and self.quote:
            style = "blockquote"
        block = {"_type": "block", "_key": _key(), "style": style, "markDefs": [], "children": []}
        if list_item:
            block["listItem"] = list_item
            block["level"] = max(1, len(self.lists))
        self.cur = block

    def _ensure(self):
        if self.cur is None:
            self._new(list_item=self.lists[-1] if self.lists else None)

    def flush(self):
        block, self.cur = self.cur, None
        if block and any(c["text"].strip() for c in block["children"]):
            self.blocks.append(block)

    def handle_starttag(self, tag, attrs):
        if tag in ("p", "div"):
            self._new(list_item=self.lists[-1] if self.lists else None)
        elif tag in HEADINGS:
            self._new(HEADINGS[tag])
        elif tag == "blockquote":
            self.flush()
            self.quote += 1
        elif tag in ("ul", "ol"):
            self.flush()
            self.lists.append("bullet" if tag == "ul" else "number")
        elif tag == "li":
            self._new(list_item=self.lists[-1] if self.lists else "bullet")
        elif tag in MARKS:
            self.marks.append((tag, MARKS[tag]))
        elif tag == "a":
            href = dict(attrs).get("href", "") or ""
            if href.startswith(("http://", "https://")):
                self._ensure()
                key = _key()
                self.cur["markDefs"].append({"_key": key, "_type": "link", "href": href})
                self.marks.append((tag, key))
            else:
                self.marks.append((tag, None))
        elif tag == "br":
            self.flush()

    def handle_endtag(self, tag):
        if tag in ("p", "div", "li") or tag in HEADINGS:
            self.flush()
        elif tag == "blockquote":
            self.flush()
            self.quote = max(0, self.quote - 1)
        elif tag in ("ul", "ol"):
            self.flush()
            if self.lists:
                self.lists.pop()
        elif tag in MARKS or tag == "a":
            for i in range(len(self.marks) - 1, -1, -1):
                if self.marks[i][0] == tag:
                    del self.marks[i]
                    break

    def handle_data(self, data):
        if self.cur is None and not data.strip():
            return
        self._ensure()
        marks = [m for _, m in self.marks if m]
        self.cur["children"].append(_span(data.replace("\n", " "), marks))


def html_to_blocks(html: str | None) -> list:
    """Portable Text blocks for the full profile. Returns [] when empty."""
    if not html or not html.strip():
        return []
    if not re.search(r"</?[a-zA-Z][^>]*>", html):
        # Plain text saved before the rich editor existed: blank lines separate paragraphs.
        paragraphs = [re.sub(r"\s*\n\s*", " ", p).strip() for p in re.split(r"\n\s*\n", html)]
        return [{"_type": "block", "_key": _key(), "style": "normal", "markDefs": [],
                 "children": [_span(p)]} for p in paragraphs if p]
    parser = _Parser()
    parser.feed(html)
    parser.close()
    parser.flush()
    return parser.blocks