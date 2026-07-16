# Third-party notices

Compression Lab's original source is MIT licensed. Its install and benchmark
paths interoperate with the following separately maintained software:

- [python-zstandard](https://github.com/indygreg/python-zstandard),
  BSD-3-Clause. This is the required portable Python distribution dependency.
- [Zstandard](https://github.com/facebook/zstd), BSD-3-Clause and GPL-2.0-only.
  Compression Lab uses its standard compression API, either through
  python-zstandard or a separately installed system library.
- Optional benchmark executables: LZ4 (BSD-2-Clause), Brotli (MIT), and 7-Zip
  (LGPL-2.1-or-later with unRAR restrictions). They are discovered at runtime
  and are not included in Compression Lab wheels.

Public research corpus files are not included in the Python distribution.
Their exact upstream commits, SPDX identifiers, source URLs, and content
digests are recorded under `config/` and `docs/corpus-protocol.md`.

This notice is informational and does not replace the complete license text of
any separately installed dependency or downloaded corpus.
