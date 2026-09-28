from html.parser import HTMLParser


VOID_ELEMENTS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}


class HtmlNode:
    def __init__(self, tag, attrs=None):
        self.tag = tag
        self.attrs = dict(attrs or ())
        self.children = []


class _TreeBuilder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = HtmlNode("document")
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        if tag in {"a", "li", "option", "p"}:
            self.handle_endtag(tag)

        node = HtmlNode(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in VOID_ELEMENTS:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].children.append(HtmlNode(tag, attrs))

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def parse_html(markup):
    parser = _TreeBuilder()
    parser.feed(markup)
    parser.close()
    return parser.root


def find_all(node, tag=None, class_name=None):
    matches = []
    for child in node.children:
        if isinstance(child, HtmlNode):
            classes = child.attrs.get("class", "").split()
            if (tag is None or child.tag == tag) and (
                class_name is None or class_name in classes
            ):
                matches.append(child)
            matches.extend(find_all(child, tag, class_name))
    return matches


def get_text(node):
    parts = []
    for child in node.children:
        if isinstance(child, HtmlNode):
            parts.append(get_text(child))
        else:
            parts.append(child)
    return " ".join(" ".join(parts).split())