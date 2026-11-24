"""Standalone batch runner: the whole paper -> dataset-usage pipeline against
OpenAI-compatible endpoints (vLLM), with files in and files out.

No database, queue or Django. One worker process per endpoint, one paper per thread,
append-only result shards. See runner/README.md at the repository root.
"""

import os

# config.settings requires these at import; the runner never calls either service.
os.environ.setdefault("OPENAI_API_KEY", "unused-by-runner")
os.environ.setdefault("ADS_TOKEN", "unused-by-runner")

__version__ = "0.1.0"
