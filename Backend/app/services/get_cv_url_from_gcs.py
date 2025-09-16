import os, uuid, mimetypes
from datetime import timedelta
from dotenv import load_dotenv
from google.cloud import storage
import google.auth
from google.auth import impersonated_credentials

load_dotenv()

# ENV
GCS_BUCKET = os.getenv("GCS_BUCKET", "cv-uploads-prod")
GCS_PUBLIC_BASE = os.getenv("GCS_PUBLIC_BASE", "https://storage.googleapis.com").rstrip("/")
GCS_MAKE_PUBLIC = os.getenv("GCS_MAKE_PUBLIC", "true").lower() in ("1","true","yes","y","on")
GCS_SIGNED_URL_EXPIRES = int(os.getenv("GCS_SIGNED_URL_EXPIRES", "604800"))
GCS_SIGNING_SA = os.getenv("GCS_SIGNING_SA")
GCP_PROJECT = "interns-2025-467409"

def _build_key(file_path: str, object_key: str | None = None) -> str:
    if object_key: return object_key.lstrip("/")
    base = os.path.basename(file_path) or "file.pdf"
    if not os.path.splitext(base)[1]: base += ".pdf"
    return f"resumes/{uuid.uuid4().hex}/{base}"

def _impersonated_client_and_signer():
    # Dùng ADC (gcloud auth application-default login) để mạo danh SA ký URL
    src_creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    tgt = impersonated_credentials.Credentials(
        source_credentials=src_creds,
        target_principal=GCS_SIGNING_SA,
        target_scopes=["https://www.googleapis.com/auth/devstorage.read_only"],
        lifetime=3600,
    )
    return storage.Client(credentials=tgt), tgt

def upload_pdf_and_get_url_gcs(file_path: str, object_key: str | None = None) -> str:
    if not os.path.exists(file_path): raise FileNotFoundError(file_path)
    if not GCS_BUCKET: raise RuntimeError("Missing GCS_BUCKET")

    print("DEBUG GCS:", {
        "bucket": GCS_BUCKET,
        "public": GCS_MAKE_PUBLIC
    })


    object_key = _build_key(file_path, object_key)

    # Public mode (khuyên dùng để đơn giản): chỉ cần bucket đã cấp public-read (allUsers -> objectViewer)
    if GCS_MAKE_PUBLIC:
        # client = storage.Client()  # ADC: local/Cloud Run
        client = storage.Client(project=os.getenv("GCP_PROJECT"))

        blob = client.bucket(GCS_BUCKET).blob(object_key)
        ctype, _ = mimetypes.guess_type(file_path)
        blob.cache_control = "public, max-age=31536000"
        blob.upload_from_filename(file_path, content_type=ctype or "application/pdf")
        return f"{GCS_PUBLIC_BASE}/{GCS_BUCKET}/{object_key}"

    # Private mode: cần ký URL
    if not GCS_SIGNING_SA:
        raise RuntimeError("Set GCS_MAKE_PUBLIC=true hoặc cung cấp GCS_SIGNING_SA để ký signed URL")

    client, signer = _impersonated_client_and_signer()
    blob = client.bucket(GCS_BUCKET).blob(object_key)
    ctype, _ = mimetypes.guess_type(file_path)
    blob.upload_from_filename(file_path, content_type=ctype or "application/pdf")
    return blob.generate_signed_url(
        expiration=timedelta(seconds=GCS_SIGNED_URL_EXPIRES),
        method="GET",
        credentials=signer,
        version="v4",
    )

if __name__ == "__main__":
    test_file = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "raw", "cvs", "01.pdf"))
    if not os.path.exists(test_file):
        os.makedirs(os.path.dirname(test_file), exist_ok=True)
        with open(test_file, "wb") as f: f.write(b"%PDF-1.4\n%Fake PDF\n%%EOF\n")
    print(upload_pdf_and_get_url_gcs(test_file))
