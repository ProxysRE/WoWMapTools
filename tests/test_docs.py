import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('docs_checker',ROOT/'tools/check_docs.py')
checker=importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


class DocumentationTests(unittest.TestCase):
    def test_checker_ignores_examples_external_urls_and_heading_fragments(self):
        text='''[file](guide.md#section)
`[example](missing.md)`
```md
[example](missing.md)
```
~~~md
[example](missing.md)
~~~
[external](https://example.invalid/file.md)
[anchor](#section)
![image](<folder/my image.png>)
'''
        self.assertEqual(list(checker.local_links(text)),[(1,'guide.md'),(11,'folder/my image.png')])

    def test_missing_and_escaping_targets_fail_but_existing_relative_links_work(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);(root/'docs').mkdir();(root/'target.md').touch()
            doc=root/'docs/guide.md'
            doc.write_text('[valid](../target.md)\n[missing](missing.md)\n[escape](../../outside.md)',encoding='utf-8')
            count,errors=checker.check_documents(root,[doc])
            self.assertEqual(count,1);self.assertEqual(len(errors),2)
            self.assertIn(':2:',errors[0]);self.assertIn(':3:',errors[1])
