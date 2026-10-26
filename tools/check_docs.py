"""Check local inline Markdown link targets without network access or dependencies.

This is deliberately not a Markdown renderer: headings, reference-style links,
external URLs and the semantic accuracy of prose require separate review.
"""
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r'!?\[[^\]\n]*\]\((<[^>\n]+>|[^\s)]+)(?:\s+"[^"\n]*")?\)')


def local_links(text):
    fence = None
    for number, line in enumerate(text.splitlines(), 1):
        marker = re.match(r'^\s{0,3}(`{3,}|~{3,})', line)
        if marker:
            value = marker.group(1)
            if fence is None:
                fence = value
            elif value[0] == fence[0] and len(value) >= len(fence):
                fence = None
            continue
        if fence is not None:
            continue
        line = re.sub(r'(`+).*?\1', '', line)
        for match in LINK.finditer(line):
            target = match.group(1).strip('<>')
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            yield number, unquote(parsed.path)


def check_documents(root, documents):
    root = Path(root).resolve()
    errors = []
    count = 0
    for document in sorted(documents):
        count += 1
        for line, target in local_links(document.read_text(encoding='utf-8-sig')):
            path = (document.parent / target).resolve()
            if not path.is_relative_to(root) or not path.exists():
                errors.append(f'{document.relative_to(root)}:{line}: missing local link: {target}')
    return count, errors


def main():
    documents = [*ROOT.glob('*.md'), *(ROOT/'foundry_builder').rglob('*.md')]
    count, errors = check_documents(ROOT, documents)
    if errors:
        print('\n'.join(errors))
        return 1
    print(f'Local Markdown links checked: {count} documents')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
