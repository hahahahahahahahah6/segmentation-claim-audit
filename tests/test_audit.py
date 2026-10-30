import ast
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from segmentation_claim_audit.audit import audit, claims, evidence, _pattern
from segmentation_claim_audit.phrases import SEGMENTATION, NOSEGMENTATION

FIXTURES = Path(__file__).parent / 'fixtures'


class ClaimsTests(unittest.TestCase):
    def test_tuple_values(self):
        import segmentation_claim_audit.phrases as module
        tree = ast.parse(Path(module.__file__).read_text())
        values = {n.targets[0].id: ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)}
        for name, count in [('SEGMENTATION', 58), ('NOSEGMENTATION', 43)]:
            items = values[name]
            self.assertEqual(len(items), count)
            self.assertEqual(len(set(items)), count)
            self.assertEqual(list(items), sorted(items, key=len, reverse=True))

    def test_all_positive_templates(self):
        for phrase in SEGMENTATION:
            with self.subTest(phrase=phrase):
                self.assertEqual(claims(phrase), (True, False))

    def test_all_negative_templates(self):
        for phrase in NOSEGMENTATION:
            with self.subTest(phrase=phrase):
                self.assertEqual(claims(phrase), (False, True))

    def test_longest_first(self):
        self.assertEqual(_pattern(SEGMENTATION).search('segments images into regions')[0], 'segments images into regions')
        self.assertEqual(_pattern(NOSEGMENTATION).search('does not segment images')[0], 'does not segment images')


claim_cases = {
 'backtick_fence': ('```python\nsegments images\n```', (False, False)),
 'tilde_fence': ('   ~~~~\nsegments images\n   ~~~~', (False, False)),
 'inline': ('Uses `segments images`.', (True, False)),
 'negative_removal': ('does not segment images', (False, True)),
 'mixed': ('does not segment images but removes the background', (True, True)),
 'hyphen': ('IMAGE-SEGMENTATION', (True, False)),
 'contraction': ("doesn't segment images", (False, True)),
 'paragraph_join': ('segments\nimages', (True, False)),
 'paragraph_boundary': ('segments\n\nimages', (False, False)),
 'word_boundary': ('resegment imagesuffix', (False, False)),
 'short_fence_inside': ('````\n```\nsegments images\n````', (False, False)),
}
for name, (text, expected) in claim_cases.items():
    def test(self, text=text, expected=expected):
        self.assertEqual(claims(text), expected)
    setattr(ClaimsTests, 'test_' + name, test)


class EvidenceTests(unittest.TestCase):
    pass

positive = {
 'direct': 'import mediapipe\nmediapipe.solutions.selfie_segmentation.SelfieSegmentation()',
 'alias': 'import mediapipe as mp\nmp.solutions.selfie_segmentation.SelfieSegmentation()',
 'from_import': 'from mediapipe.solutions.selfie_segmentation import SelfieSegmentation as S\nS()',
 'with': 'from mediapipe.solutions.selfie_segmentation import SelfieSegmentation as S\nwith S() as model:\n model.segment(frame)',
 'attribute': 'from mediapipe.solutions.selfie_segmentation import SelfieSegmentation as S\nself.model=S()\nself.model.segment(frame)',
 'chained': 'from mediapipe.solutions.selfie_segmentation import SelfieSegmentation as S\nS().segment(frame)',
 'bound': 'from mediapipe.solutions.selfie_segmentation import SelfieSegmentation as S\ns=S()\ns.segment(frame)',
 'annotated': 'from mediapipe.solutions.selfie_segmentation import SelfieSegmentation as S\ns: object=S()\ns.segment(frame)',
 'task_direct_factory': 'import mediapipe as mp\nmp.tasks.vision.ImageSegmenter.create_from_options(opts)',
 'task_import_factory': 'from mediapipe.tasks.vision import ImageSegmenter\nImageSegmenter.create_from_options(opts)',
 'task_construct': 'from mediapipe.tasks.vision import ImageSegmenter\nImageSegmenter(opts)',
}
for method in ['segment', 'segment_for_video', 'segment_async']:
    positive['task_' + method] = 'from mediapipe.tasks.vision import ImageSegmenter\ns=ImageSegmenter.create_from_options(opts)\ns.' + method + '(image)'
negative = {
 'bare_import': 'import mediapipe',
 'open': 'import cv2\ncv2.imread(path)\nfrom PIL import Image\nImage.open(path)',
 'camera': 'import cv2\ncv2.VideoCapture(0).read()',
 'mask': 'import cv2\ncv2.imshow("mask", supplied_mask)',
 'threshold': 'import cv2\ncv2.threshold(image, 127, 255, 0)\nmask = image > 0',
 'face': 'import mediapipe as mp\nmp.solutions.face_detection.FaceDetection()',
 'hand': 'import mediapipe as mp\nmp.solutions.hands.Hands()',
 'pose': 'import mediapipe as mp\nmp.solutions.pose.Pose()',
 'yolo': 'from ultralytics import YOLO\nYOLO("model")',
 'shadow_class': 'from mediapipe.tasks.vision import ImageSegmenter\nclass ImageSegmenter: pass\nImageSegmenter()',
 'shadow_function': 'from mediapipe.solutions.selfie_segmentation import SelfieSegmentation\ndef SelfieSegmentation(): pass\nSelfieSegmentation()',
 'shadow_module': 'import mediapipe as mp\nclass mp: pass\nmp.solutions.selfie_segmentation.SelfieSegmentation()',
 'unbound': 's.segment(frame)\nsegment(frame)\ns.segment_for_video(frame)',
 'string': 's="mediapipe.tasks.vision.ImageSegmenter()"',
 'subprocess': 'import subprocess\nsubprocess.run(["segment", "image"])',
 'syntax': 'import mediapipe\nthis is invalid python !!!',
 'foreign': 'from unrelated import ImageSegmenter\nImageSegmenter()',
}
for expected, cases in [(True, positive), (False, negative)]:
    for name, source in cases.items():
        def test(self, source=source, expected=expected):
            self.assertEqual(evidence(source), expected)
        setattr(EvidenceTests, 'test_' + name, test)


class IntegrationTests(unittest.TestCase):
    def cli(self, *args):
        return subprocess.run([sys.executable, '-m', 'segmentation_claim_audit', *map(str, args)], capture_output=True, text=True)

    def test_fixtures(self):
        for fixture, severity, rule, code in [('good', None, None, 0), ('bad', 'HIGH', 'documented-segmentation-claim-false', 2), ('testonly', 'MEDIUM', 'documented-segmentation-claim-false', 0), ('no_segmentation', 'HIGH', 'documented-no-segmentation-claim-false', 2)]:
            with self.subTest(fixture=fixture):
                result = self.cli(FIXTURES / fixture, '--json')
                self.assertEqual(result.returncode, code, result.stderr)
                data = json.loads(result.stdout)
                self.assertEqual(set(data), {'verdict', 'findings', 'files_scanned'})
                self.assertIsInstance(data['files_scanned'], int)
                self.assertEqual(len(data['findings']), 1 if severity else 0)
                self.assertEqual(data['verdict'], 'FAIL' if severity else 'PASS')
                if severity:
                    self.assertEqual(data['findings'][0]['severity'], severity)
                    self.assertEqual(data['findings'][0]['rule'], rule)
                    self.assertEqual(set(data['findings'][0]), {'rule', 'severity', 'message'})

    def test_medium_threshold(self):
        self.assertEqual(self.cli(FIXTURES / 'testonly', '--fail-on', 'MEDIUM').returncode, 2)

    def test_ignore(self):
        self.assertEqual(audit(FIXTURES / 'good', ['app.py'])['findings'][0]['severity'], 'HIGH')
        self.assertEqual(audit(FIXTURES / 'bad', ['README.*'])['verdict'], 'PASS')

    def test_verbose(self):
        self.assertIn('Files scanned: 2', self.cli(FIXTURES / 'good', '--verbose').stdout)

    def test_version(self):
        result = self.cli('--version')
        self.assertEqual((result.returncode, result.stdout.strip()), (0, '0.1.0'))

    def test_invalid_root(self):
        self.assertEqual(self.cli('/nonexistent-segmentation-audit-root').returncode, 1)

    def test_usage_error(self):
        for args in [(), ('--unknown',), ('.', '--fail-on', 'LOW')]:
            self.assertEqual(self.cli(*args).returncode, 1)

    def test_no_claim(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, 'app.py').write_text(positive['direct'])
            self.assertEqual(audit(d)['verdict'], 'PASS')

    def test_exclusions(self):
        for location in ['fixtures/app.py', 'docs/app.py', 'examples/app.py', 'tests/app.py', 'test_app.py', 'app_test.py']:
            with self.subTest(location=location), tempfile.TemporaryDirectory() as d:
                root = Path(d)
                (root / 'README.md').write_text('segments images')
                target = root / location
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(positive['direct'])
                expected = 'MEDIUM' if 'test' in location else 'HIGH'
                self.assertEqual(audit(root)['findings'][0]['severity'], expected)

    def test_symlinks(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as outside:
            root = Path(d)
            (root / 'README.md').write_text('segments images')
            Path(outside, 'app.py').write_text(positive['direct'])
            (root / 'app.py').symlink_to(Path(outside, 'app.py'))
            (root / 'linked').symlink_to(outside, target_is_directory=True)
            self.assertEqual(audit(root)['findings'][0]['severity'], 'HIGH')

    def test_docs_scope(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'other.md').write_text('segments images')
            self.assertEqual(audit(root)['verdict'], 'PASS')
            (root / 'nested/docs').mkdir(parents=True)
            (root / 'nested/docs/page.md').write_text('segments images')
            self.assertEqual(len(audit(root)['findings']), 1)

    def test_unreadable_root(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            root.chmod(0o000)
            try:
                self.assertEqual(self.cli(root).returncode, 1)
            finally:
                root.chmod(0o700)

    def test_self_audit(self):
        self.assertEqual(audit(Path(__file__).resolve().parents[1])['verdict'], 'PASS')
