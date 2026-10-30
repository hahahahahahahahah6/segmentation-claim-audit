# segmentation-claim-audit

An offline static checker for documentation about pixel-region processing.
Version 0.1.0 requires Python 3.9 or newer and has no runtime dependencies.
Source files are parsed with the standard AST module and never executed.

Install and run:

```sh
pip install segmentation-claim-audit
segmentation-claim-audit . --json
python3 -m segmentation_claim_audit . --verbose
segmentation-claim-audit . --ignore 'vendor/*' --fail-on MEDIUM
segmentation-claim-audit --version
```

The checker reads the root README.md and Markdown files beneath any docs
path component. It skips backtick and tilde fences; inline code counts.
Paragraphs are normalized for case, contractions, hyphens and whitespace.
Exact bounded templates are matched longest first, with negative spans
removed before positive matching. The complete vocabulary is in phrases.py.

Examples of recognized wording and the two rule identifiers:

```text
segments images
does not segment images
documented-segmentation-claim-false
documented-no-segmentation-claim-false
```

Evidence comes from provider-resolved MediaPipe SelfieSegmentation and
ImageSegmenter constructors, including the tasks create_from_options factory.
Calls through bound objects are recognized for segment, segment_for_video and
segment_async as appropriate. Aliases, annotated assignments, attribute
assignments, context managers and chained calls are handled. Local definitions
shadow imported names. Construction alone counts; successful runtime output
is not established.

Bare imports, image loading, camera capture, supplied-mask drawing, thresholds,
face/hand/pose detectors, box detectors, strings and subprocess commands do
not establish evidence. Invalid Python yields no evidence. Symlinks are
excluded. Sources within fixtures, docs and examples are excluded; tests,
test_*.py and *_test.py contribute only test evidence.

Each family produces at most one finding. A positive assertion lacking
production evidence is HIGH, or MEDIUM when only test evidence exists.
A negative assertion conflicting with production evidence is HIGH. With no
assertions the result is PASS. Static analysis is module-local, does not follow
cross-module bindings, and cannot establish runtime correctness or coverage.
Exact vocabulary can miss paraphrases. This is a review aid.

JSON contains verdict, findings (rule, severity, message), and files_scanned.
Human output includes each finding; --verbose adds the scanned file count.
A result with findings displays FAIL even when its severity is below the exit
threshold. Exit 0 means no finding meets the threshold; exit 2 means one does;
exit 1 means invalid usage or unreadable input. The default threshold is HIGH;
--fail-on MEDIUM includes both levels. Repeat --ignore for relative POSIX-path
fnmatch patterns. The scanned count includes eligible documents and Python
files read, including excluded evidence locations.

Development checks:

```sh
python3 -m unittest discover
python3 -m build
```

Distributed under the MIT license.
