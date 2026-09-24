import importlib.util as u, io, tempfile, inspect
from pathlib import Path
from reportlab.pdfgen import canvas
from reportlab.lib import pdfencrypt

assert u.find_spec("pypdf") is None, "pypdf still installed"
import pypdfium2
print("D1 image ok: pypdf absent, pypdfium2", pypdfium2.V_PYPDFIUM2 if hasattr(pypdfium2, "V_PYPDFIUM2") else "")

from decision_assistant.ingestion.profiles import resolve_corpus_profile, CURRENT_CHUNKING_PROFILE
from decision_assistant.config import Settings
p = resolve_corpus_profile("baseline", "passage_hybrid")["pdf_parser"]
exp = {"name":"docling","version":"2.130.0","ocr":"tesseract-eng","layout":"docling-layout-v1"}
print("D8 profile", p == exp, p == CURRENT_CHUNKING_PROFILE["pdf_parser"])
print("D8 settings has pdf_parser:", hasattr(Settings(), "pdf_parser"))
try:
    resolve_corpus_profile("baseline", "passage_hybrid", "pypdf"); print("D8 3-arg: NO TypeError")
except TypeError: print("D8 3-arg: TypeError ok")
import os
os.environ["PDF_PARSER"] = "pypdf"
print("D8 stale env absorbed:", not hasattr(Settings(), "pdf_parser"))

from decision_assistant.ingestion.parsers import parse_document, DocumentParseError
tmp = Path(tempfile.mkdtemp())
def mk(name, enc=None, text=True):
    f = tmp / name
    c = canvas.Canvas(str(f), encrypt=enc)
    if text: c.drawString(72, 720, "Secret decision: ship Atlas in Q3.")
    c.showPage(); c.save(); return f
cases = {
  "encrypted": (mk("enc.pdf", pdfencrypt.StandardEncryption("userpw", ownerPassword="ownerpw")), "pdf_password_protected"),
  "corrupt": (tmp / "bad.pdf", "pdf_parse_failed"),
  "truncated": (tmp / "trunc.pdf", "pdf_parse_failed"),
  "blank": (mk("blank.pdf", text=False), "pdf_no_extractable_text"),
  "empty0": (tmp / "zero.pdf", "pdf_parse_failed"),
}
(tmp / "bad.pdf").write_bytes(b"%PDF-1.7\nthis is not a pdf \x00\x01\x02" * 50)
(tmp / "trunc.pdf").write_bytes(mk("full.pdf").read_bytes()[:300])
(tmp / "zero.pdf").write_bytes(b"")
bad = 0
for label, (path, code) in cases.items():
    try:
        doc = parse_document(path); print(label, "NO ERROR", len(doc.blocks) if hasattr(doc,"blocks") else doc); bad += 1; continue
    except DocumentParseError as e:
        msg = str(getattr(e, "message", e))
        leak = [w for w in ("docling", "pdfium", str(tmp).lower(), "/tmp") if w in msg.lower()]
        retry = getattr(e, "retryable", None)
        ok = e.code == code and retry is False and not leak
        bad += not ok
        print(f"{label}: code={e.code} expect={code} retryable={retry} msg={msg!r} leak={leak} -> {'OK' if ok else 'FAIL'}")
    except Exception as e:
        bad += 1; print(label, "RAW EXCEPTION", type(e).__name__, str(e)[:200])
print("D6 failures:", bad)
