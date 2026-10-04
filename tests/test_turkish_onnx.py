import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from meikipop.ocr.turkish_paddle import MODELS, PADDLE_FILES, LocalOCR, file_hash, setup_ocr
from meikipop.scripts.export_turkish_ocr import export_models


class ONNXTests(unittest.TestCase):
    def make_models(self, root):
        for name in MODELS.values():
            (root / name).mkdir(parents=True)
            for filename in PADDLE_FILES:
                (root / name / filename).write_text(name + filename)
        self.manifest(root)

    def manifest(self, root):
        files = {p.relative_to(root).as_posix(): file_hash(p) for p in root.rglob('*')
                 if p.is_file() and p.name != 'manifest.json'}
        (root / 'manifest.json').write_text(json.dumps(dict(models=MODELS, files=files)))

    def export(self, source, target, fail=False):
        def convert(*args, save_file, **kwargs):
            if fail:
                raise RuntimeError('bad export')
            Path(save_file).write_bytes(b'checked ONNX fixture')
        modules = {'paddle': SimpleNamespace(__version__='3.1.1'),
                   'paddle2onnx': SimpleNamespace(__version__='2.1.0', export=convert)}
        with patch.dict('sys.modules', modules):
            return export_models(source, target)

    def test_verified_roundtrip_selects_onnx_with_real_word_box_pipeline(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source, exported, installed = base / 'source', base / 'export', base / 'installed'
            self.make_models(source)
            self.export(source, exported)
            constructor = Mock()
            modules = {'paddleocr': SimpleNamespace(PaddleOCR=constructor),
                       'paddlex.inference.utils.official_models': SimpleNamespace(
                           official_models={name: source / name for name in MODELS.values()})}
            with patch.dict('sys.modules', modules):
                setup_ocr(installed, onnx_dir=exported)
                LocalOCR(installed)
            options = constructor.call_args.kwargs
            self.assertEqual(options['engine'], 'onnxruntime')
            self.assertEqual(options['engine_config']['intra_op_num_threads'], 4)
            self.assertTrue(options['return_word_box'])
            self.assertFalse(options['use_textline_orientation'])
            info = json.loads((installed / 'manifest.json').read_text())
            self.assertEqual(info['onnx_exporter']['paddle'], '3.1.1')
            self.assertTrue(all(f'{name}/inference.onnx' in info['files'] for name in MODELS.values()))

    def test_native_setup_uses_acceleration_and_ignores_unverified_onnx_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_models(root)
            for name in MODELS.values():
                (root / name / 'inference.onnx').write_bytes(b'not in manifest')
            constructor = Mock()
            with patch.dict('sys.modules', {'paddleocr': SimpleNamespace(PaddleOCR=constructor)}):
                LocalOCR(root)
            self.assertTrue(constructor.call_args.kwargs['enable_mkldnn'])
            self.assertNotIn('engine', constructor.call_args.kwargs)

    def test_partial_or_corrupt_export_fails_before_runtime_loading(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_models(root)
            (root / MODELS['det'] / 'inference.onnx').write_bytes(b'detector')
            self.manifest(root)
            constructor = Mock()
            with patch.dict('sys.modules', {'paddleocr': SimpleNamespace(PaddleOCR=constructor)}):
                with self.assertRaises(RuntimeError):
                    LocalOCR(root)
                (root / MODELS['rec'] / 'inference.onnx').write_bytes(b'recognizer')
                self.manifest(root)
                (root / MODELS['rec'] / 'inference.onnx').write_bytes(b'tampered')
                with self.assertRaises(RuntimeError):
                    LocalOCR(root)
            constructor.assert_not_called()

    def test_wrong_source_or_export_hash_preserves_previous_installation(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source, exported, installed = base / 'source', base / 'export', base / 'installed'
            self.make_models(source)
            self.make_models(installed)
            self.export(source, exported)
            previous = (installed / 'manifest.json').read_bytes()
            modules = {'paddlex.inference.utils.official_models': SimpleNamespace(
                official_models={name: source / name for name in MODELS.values()})}
            with patch.dict('sys.modules', modules):
                path = source / MODELS['det'] / 'inference.json'
                original = path.read_bytes()
                path.write_bytes(b'different model')
                with self.assertRaisesRegex(ValueError, 'does not match'):
                    setup_ocr(installed, onnx_dir=exported)
                path.write_bytes(original)
                (exported / MODELS['rec'] / 'inference.onnx').write_bytes(b'tampered')
                with self.assertRaisesRegex(ValueError, 'checksum'):
                    setup_ocr(installed, onnx_dir=exported)
            self.assertEqual((installed / 'manifest.json').read_bytes(), previous)

    def test_failed_export_never_publishes_partial_models(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, output = Path(temporary) / 'source', Path(temporary) / 'output'
            self.make_models(source)
            with self.assertRaisesRegex(RuntimeError, 'bad export'):
                self.export(source, output, fail=True)
            self.assertFalse(output.exists())

    def test_cli_forwards_optional_export_directory_through_rollback_staging(self):
        from meikipop.scripts.turkish import main
        with patch('meikipop.dictionary.turkish_assets.setup_asset', return_value='installed') as setup, \
                patch('builtins.print'):
            main(['setup-turkish-ocr', '--onnx-dir', 'exports'])
        self.assertEqual(setup.call_args.kwargs, {'onnx_dir': Path('exports')})
        self.assertEqual(setup.call_args.args[0], 'ocr')
