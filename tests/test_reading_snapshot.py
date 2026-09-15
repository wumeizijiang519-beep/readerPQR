import tempfile
import unittest
from pathlib import Path

from readerpqr.pdf_engine import load_paper
from readerpqr.reading_snapshot import load_snapshot, save_snapshot
from readerpqr.smoke import create_sample


class ReadingSnapshotTests(unittest.TestCase):
    def test_restores_after_original_is_removed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = root / "original.pdf"
            create_sample(original)
            paper = load_paper(str(original))
            translations = {paper.blocks[0].id: "已保存的中文译文"}
            snapshot = save_snapshot(paper, translations, 1, root / "snapshots")
            original.unlink()
            restored, texts, page = load_snapshot(snapshot)
            self.assertTrue(Path(restored.path).exists())
            self.assertEqual(texts, translations)
            self.assertEqual(page, 1)
            self.assertEqual(restored.blocks, paper.blocks)
            self.assertNotIn("api_key", snapshot.read_text(encoding="utf-8"))

    def test_rejects_changed_pdf(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = root / "original.pdf"
            create_sample(original)
            snapshot = save_snapshot(load_paper(str(original)), {}, directory=root / "snapshots")
            (snapshot.parent / "source.pdf").write_bytes(b"different PDF")
            with self.assertRaises(ValueError):
                load_snapshot(snapshot)
