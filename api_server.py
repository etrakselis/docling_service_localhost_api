import io
import os
from dotenv import load_dotenv
import time
import logging
import tempfile
from pathlib import Path
from typing import Optional


import paramiko
from fastapi import FastAPI, File, UploadFile
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.pipeline_options import PdfPipelineOptions, PictureDescriptionApiOptions
from docling.datamodel.base_models import InputFormat
from docling.chunking import HybridChunker

# Load .env from the project root (where api_server.py lives)
BASE_DIR = Path(__file__).parent
load_dotenv(dotenv_path=BASE_DIR / ".env")

# =============================
# FastAPI Setup
# =============================
app = FastAPI(title="Docling Remote Markdown API", version="1.1-env")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(level=logging.INFO)

# =============================
# Load Environment Variables
# =============================
LLM_MODEL = os.getenv("LLM_MODEL")
LLM_BEARER_TOKEN = os.getenv("LLM_BEARER_TOKEN")
LLM_MAX_COMPLTETION_TOKENS = int(os.getenv("LLM_MAX_COMPLETION_TOKENS", 2000))

HYBRID_CHUNKER_MAX_TOKENS = int(os.getenv("HYBRID_CHUNKER_MAX_TOKENS", 3000))

SSH_HOST = os.getenv("SSH_HOST")
SSH_USER = os.getenv("SSH_USER")
SSH_PASSWORD = os.getenv("SSH_PASSWORD")
SSH_PRIVATE_KEY = os.getenv("SSH_PRIVATE_KEY")
SSH_TARGET_PATH = os.getenv("SSH_TARGET_PATH")

if not all([LLM_MODEL, LLM_BEARER_TOKEN, LLM_MAX_COMPLTETION_TOKENS, HYBRID_CHUNKER_MAX_TOKENS, SSH_HOST, SSH_USER, SSH_TARGET_PATH]):
    logging.warning("⚠ Missing required environment variables. The API may not function correctly.")

# =============================
# VLLM/Ollama options
# =============================
def vllm_local_options():
    headers = {
        "Authorization": f"Bearer {LLM_BEARER_TOKEN}",
        "Content-Type": "application/json",
    }

    return PictureDescriptionApiOptions(
        url="https://llm.edwintrakselis.com/api/v1/chat/completions",
        params=dict(
            model=LLM_MODEL,
            seed=42,
            max_completion_tokens=LLM_MAX_COMPLTETION_TOKENS,
        ),
        prompt=(
            "Always begin your response with 'IMAGE DESCRIPTION' then provide a detailed description of the image. "
            "After describing it in detail, summarize the intent of the image. No follow-up questions. "
            "Be accurate and only describe the things you see that you are absolutely certain about."
        ),
        timeout=600,
        headers=headers,
    )

# =============================
# SSH/SFTP Save Function
# =============================
def save_file_via_sftp(remote_path: str, local_temp_path: str):
    """Uploads a local TEMP file to the remote target using SFTP."""
    transport = paramiko.Transport((SSH_HOST, 22))

    if SSH_PRIVATE_KEY:
        key_obj = paramiko.RSAKey.from_private_key(io.StringIO(SSH_PRIVATE_KEY))
        transport.connect(username=SSH_USER, pkey=key_obj)
    else:
        transport.connect(username=SSH_USER, password=SSH_PASSWORD)

    sftp = paramiko.SFTPClient.from_transport(transport)
    sftp.put(local_temp_path, remote_path)
    sftp.close()
    transport.close()

# =============================
# Converter Factory
# =============================
def create_converter():
    picture_api = vllm_local_options()

    pdf_pipeline = PdfPipelineOptions(
        enable_remote_services=True,
        do_picture_description=True,
        do_formula_enrichment=True,
        do_table_structure=True,
        do_code_enrichment=True,
        do_picture_classification=True,
        images_scale=2,
        picture_description_options=picture_api,
    )

    pdf_option = PdfFormatOption(
        pipeline_options=pdf_pipeline,
        image_export_mode="placeholder",
    )

    return DocumentConverter(format_options={InputFormat.PDF: pdf_option})


# =============================
# Save chunks to markdown tmp file
# =============================
def save_chunks_to_markdown_tempfile(chunks, chunker):
    temp_md = tempfile.NamedTemporaryFile(delete=False, suffix=".md", mode="w", encoding="utf-8")

    for chunk in chunks:
        temp_md.write("HYBRID_CHUNK_SPLITTER\n\n")
        contextualized_text = chunker.contextualize(chunk=chunk)
        temp_md.write(contextualized_text + "\n\n")

    temp_md.flush()
    temp_md.close()
    return temp_md.name  # path


# =============================
# API Endpoint
# =============================
@app.post("/convert/")
async def convert_file(file: UploadFile = File(...)):
    start = time.time()
    errors = []
    remote_md_path = None

    try:
        # ----------------------------
        # Save inbound file to TEMP
        # ----------------------------
        suffix = Path(file.filename).suffix.lower()
        stem = Path(file.filename).stem

        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_in:
            tmp_in.write(await file.read())
            tmp_in.flush()
            temp_input_path = tmp_in.name

        EXT_MAP = {
            ".pdf": InputFormat.PDF,
            ".docx": InputFormat.DOCX,
            ".pptx": InputFormat.PPTX,
            ".ppt": InputFormat.PPTX,
            ".xlsx": InputFormat.XLSX,
            ".csv": InputFormat.CSV,
            ".html": InputFormat.HTML,
            ".htm": InputFormat.HTML,
            ".txt": "TXT",
        }

        if suffix not in EXT_MAP:
            raise ValueError(f"Unsupported file extension: {suffix}")

        logging.info(f"Processing format: {EXT_MAP[suffix]}")

        # ----------------------------
        # Convert to docling doc
        # ----------------------------
        converter = create_converter()
        result = converter.convert(temp_input_path)
        doc = result.document

        # ----------------------------
        # Hybrid chunking
        # ----------------------------
        chunker = HybridChunker(max_tokens=HYBRID_CHUNKER_MAX_TOKENS, merge_peers=True)
        chunks = list(chunker.chunk(dl_doc=doc))

        # ----------------------------
        # Save chunked markdown temp
        # ----------------------------
        temp_md_path = save_chunks_to_markdown_tempfile(chunks, chunker)

        # ----------------------------
        # Upload markdown to remote server
        # ----------------------------
        remote_md_path = f"{SSH_TARGET_PATH.rstrip('/')}/{stem}_chunked.md"

        save_file_via_sftp(remote_path=remote_md_path, local_temp_path=temp_md_path)

        status = "success"

    except Exception as e:
        logging.exception("Error during processing:")
        errors.append(str(e))
        status = "failed"

    finally:
        processing_time = time.time() - start

        try:
            if "temp_input_path" in locals() and os.path.exists(temp_input_path):
                os.remove(temp_input_path)
            if "temp_md_path" in locals() and os.path.exists(temp_md_path):
                os.remove(temp_md_path)
        except Exception:
            pass

    return JSONResponse(
        [
            {
                "document": {
                    "filename": file.filename,
                    "saved_remotely": remote_md_path if status == "success" else None,
                },
                "status": status,
                "errors": errors,
                "processing_time": processing_time,
            }
        ]
    )
