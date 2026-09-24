import asyncio
from pathlib import Path
from decision_assistant import config
from decision_assistant.ingestion import service
from decision_assistant.ingestion.parsers import DocumentParseError
real = config.get_settings()
class S:
    def __getattr__(self, k): return 1e-9 if k == "model_timeout_seconds" else getattr(real, k)
service.get_settings = lambda: S()
for p in ["/workspace/sample_data/atlas/" + n for n in sorted(__import__("os").listdir("/workspace/sample_data/atlas"))]:
    try:
        d = asyncio.run(service._parse_for_ingestion(Path(p))); print(Path(p).name, "parsed", len(d.blocks))
    except DocumentParseError as e:
        print(Path(p).name, "error", e.code)
