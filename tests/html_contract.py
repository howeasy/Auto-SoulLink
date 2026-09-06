"""Small source-markup tree for contracts (does not repair invalid table markup)."""

from dataclasses import dataclass, field
from html.parser import HTMLParser

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


@dataclass
class Element:
    tag: str
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)
    content: list = field(default_factory=list)
    parent: object = None

    def descendants(self, tag=None):
        for child in self.children:
            if tag is None or child.tag == tag:
                yield child
            yield from child.descendants(tag)

    def closest(self, tag):
        node = self.parent
        while node is not None:
            if node.tag == tag:
                return node
            node = node.parent
        return None

    def has_class(self, name):
        return name in (self.attrs.get("class") or "").split()

    def normalized(self):
        """Keep element order, attributes and text; discard indentation only."""
        content = []
        for item in self.content:
            if isinstance(item, Element):
                content.append(item.normalized())
            elif item.strip():
                content.append(" ".join(item.split()))
        return [self.tag, dict(sorted(self.attrs.items())), content]


class Document(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.root = Element("document")
        self.stack = [self.root]
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        node = Element(tag, dict(attrs), parent=self.stack[-1])
        node.parent.children.append(node)
        node.parent.content.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_data(self, data):
        content = self.stack[-1].content
        if content and isinstance(content[-1], str):
            content[-1] += data
        else:
            content.append(data)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def by_id(self, value):
        matches = [node for node in self.root.descendants() if node.attrs.get("id") == value]
        assert len(matches) == 1, f"expected exactly one #{value}, found {len(matches)}"
        return matches[0]
