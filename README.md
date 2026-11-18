# AI-Based Smart Document Processing System

**DocuMind** is a full-stack document-processing application for the CAT-03 Cloud Computing assignment. It accepts invoices as PDF, PNG, and JPG files, sends valid documents to OCR.space for text extraction through the browser upload flow, and retains a separate Google Cloud Document AI Invoice Parser integration for structured invoice entities and confidence scores.

> **Important:** Successful extractions are never simulated. OCR.space and Google Cloud are distinct external services; a successful result is stored only after the selected service returns actual data.

## 1. Problem statement

Invoices and other business documents contain important information trapped in unstructured files. Manually keying supplier, invoice, tax, and line-item details into another system takes time and can introduce errors. The project demonstrates a cloud AI workflow that turns supported invoice files into structured data.

## 2. Objectives

- Accept invoice documents through a browser-based upload experience.
- Validate file extensions, actual file signatures, MIME type, and size on the server.
- Use Google Cloud Document AI's Invoice Parser for OCR and entity extraction.
- Display the actual response, extracted text, and confidence scores.
- Keep processing history and extracted results in SQLite.
- Provide JSON and CSV downloads, deletion, and basic processing analytics.
- Demonstrate the browser-to-Flask-to-Google-Cloud architecture clearly.

## 3. Technology stack

| Layer | Technology |
| --- | --- |
| Frontend | HTML5, CSS3, JavaScript, Lucide icons |
| Backend | Python 3.9+, Flask |
| AI | Google Cloud Document AI Invoice Parser, OCR.space, PyMuPDF |
| Database | SQLite |
| Authentication | Google Application Default Credentials (ADC) |

Google Cloud Storage is not required: this demonstration sends documents directly to the synchronous Document AI API, with a 15 MB application upload limit.

## 4. System architecture

```text
Browser (HTML/CSS/JS)
  | multipart upload: PDF / PNG / JPG
  v
Flask API (backend/routes/upload.py)
  | extension + MIME + signature + size validation
  | provider=ocr_space (browser) or provider=google (API default)
  +-------------------------------+
  |                               |
  v                               v
OCR.space OCR API          Google ADC + Document AI
  |                               |
  | recognized text               | invoice entities + confidence
  +---------------+---------------+
                  v
 Extraction normalization -> SQLite (metadata + result JSON)
  | JSON APIs
  v
Dashboard, results, history, analytics, TXT/JSON/CSV downloads
```

Documents are retained locally under `uploads/` so that the local document history can be managed; deleting a document removes its uploaded file and its SQLite record. Extracted text and structured results are stored in the `processed/` SQLite database. Neither uploaded files nor credentials should be committed to source control.

### Backend modules

- `backend/app.py` creates the Flask app and registers the API blueprints.
- `backend/config.py` loads environment variables and sets file/database limits and paths.
- `backend/routes/upload.py` validates, stores, and processes uploaded documents.
- `backend/routes/documents.py` provides history, result lookup, and deletion.
- `backend/routes/analytics.py` provides processing totals and daily/type summaries.
- `backend/services/document_ai.py` calls the official Google Cloud client using regional endpoint and ADC.
- `backend/services/ocr_space.py` splits and optimizes PDFs within OCR.space request limits, submits chunks sequentially, and normalizes page-level text.
- `backend/services/extraction.py` normalizes processor entities and text anchors.
- `backend/database/db.py` initializes and queries the SQLite database.

## 5. Google Cloud Document AI integration

For each upload, the Flask backend validates the file and builds a `ProcessRequest` containing the raw document bytes and verified MIME type. `DocumentProcessorServiceClient` calls the configured Invoice Parser processor in its regional endpoint. The returned Document AI document is normalized into:

- full OCR text;
- entity names, normalized values, and raw values;
- per-entity confidence scores;
- line-item properties and confidence scores;
- page count and processor identification.

The browser renders only the result saved from the actual cloud response. A missing project/region/processor configuration returns HTTP 503; Document AI API errors return a visible failed result. No local OCR or fabricated extraction is used.

## 6. OCR.space text extraction

The existing upload dialog submits documents to OCR.space using the `ocr_space` provider. The backend reads `OCR_SPACE_API_KEY` from the root `.env` file and sends files as multipart form data to `https://api.ocr.space/parse/image`; the key is sent only in the request header and is never returned by status or document APIs. PDF, PNG, and JPG signatures are validated before the API request. OCR.space text is stored in the same SQLite document history and displayed in the existing results view. JSON, TXT, and CSV downloads are available when extraction results exist.

OCR.space returns recognized text but does not classify document type, so its uploads are labeled **Document** in history. Uploads processed through the Google Invoice Parser are labeled **Invoice**.

The OCR.space free API documents a **1 MB file limit** and a **3-page PDF limit per request**. DocuMind keeps each chunk under 1 MB and at no more than three pages, reduces the chunk size when needed, and applies safe PDF optimization before rejecting a single page that remains too large. The application upload limit remains 15 MB. A 75-page PDF therefore requires at least 25 OCR.space requests.

The provider currently documents quotas of up to **500 requests per day per IP** and **25,000 requests per month**. To leave headroom for other applications using the same account/IP, DocuMind reserves requests in SQLite and caps its own use at **450 per day and 22,500 per month**. These local counters cannot see OCR.space traffic sent by other apps on the same IP/account, so check provider usage before processing large files. Requests are not automatically retried after rate limits or failures.

The upload progress display polls the document's SQLite-backed progress record and reports attempted pages and chunks. Successful page text is combined in original page order with page-number headings. The stored JSON also includes each page's status and each chunk's size/status; if any chunk fails, the document is marked failed and successful partial text remains available for review and export. Chunk PDFs are built in memory and released after processing; only the original uploaded document follows the existing retention behavior.

The Google Cloud Document AI integration remains in its own service and is still used by API callers that omit `provider` (or explicitly send `provider=google`). The browser upload action selects OCR.space with `provider=ocr_space`. OCR.space extracts text only; it does not return the structured invoice entities or confidence scores produced by the Google Invoice Parser. Invalid API keys, rate limits, network errors, and empty OCR responses are recorded as failed attempts.

### API routes

| Method | Route | Purpose |
| --- | --- | --- |
| `GET` | `/api/status` | Check whether cloud processor settings are present |
| `POST` | `/api/upload` | Validate/process a document (multipart field `document`; `provider=google` or `ocr_space`) |
| `GET` | `/api/documents` | List recent processing attempts |
| `GET` | `/api/documents/<id>` | Get a record, stored result, and live processing progress |
| `DELETE` | `/api/documents/<id>` | Delete the database record and local file |
| `GET` | `/api/analytics` | Get totals, success rate, by-type, and daily counts |

## 7. Application workflow

1. Select or drag a PDF, PNG, or JPG into the upload dialog.
2. The browser checks basic filename, MIME, and size information for a quick user feedback loop.
3. Flask repeats validation using file extension, MIME, content signature, and the 15 MB limit.
4. Flask stores the original document locally and records the processing attempt in SQLite.
5. The browser selects OCR.space using the `provider=ocr_space` field. PDF uploads are counted and split into chunks respecting the provider's per-request page and file-size limits. API clients that omit the provider continue to use Google Document AI.
6. The browser polls the document record while Flask submits the chunks sequentially. OCR.space returns the actual page text; Document AI can return structured invoice entities.
7. Flask stores page/chunk results and progress in SQLite. The dashboard displays actual text, page order, and partial failures and allows downloads and deletion.

## 8. Installation

### Requirements

- Python 3.9 or newer.
- An OCR.space API key for the browser upload flow.
- Optionally, a Google Cloud project, Document AI Invoice Parser processor, and Application Default Credentials for the Google integration.

### Create a virtual environment and install dependencies

From the project directory in PowerShell:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r backend\requirements.txt
```

## 9. Google Cloud configuration

1. In Google Cloud Console, create/select a project and enable billing.
2. Enable **Document AI API** (`documentai.googleapis.com`).
3. Open Document AI, create an **Invoice Parser** processor, choose a processor region, and copy its processor ID.
4. Grant the identity used by the app the **Document AI API User** role (or equivalent least-privilege permissions).
5. Authenticate using either:
   - local development ADC: `gcloud auth application-default login`; or
   - a service account JSON key stored securely outside the repository.
6. Copy the sample configuration and fill in the values:

```powershell
Copy-Item .env.example .env
```

Set these values in `.env`:

```dotenv
GOOGLE_CLOUD_PROJECT=your-project-id
GOOGLE_CLOUD_LOCATION=us
GOOGLE_CLOUD_PROCESSOR_ID=your-processor-id
GOOGLE_APPLICATION_CREDENTIALS=
```

Use the location selected for the processor (for example `us` or `eu`). For a service-account key, set `GOOGLE_APPLICATION_CREDENTIALS` to its absolute path. Keep `.env` and the credential file private; `.gitignore` excludes local configuration and credential files. The app uses Google's ADC chain, so `GOOGLE_APPLICATION_CREDENTIALS` may be left blank when ADC is already configured.

For OCR.space, put the API key in the root `.env` file (which is excluded by `.gitignore`):

```dotenv
OCR_SPACE_API_KEY=your-ocr-space-api-key
```

Get an API key from the OCR.space website. Do not paste it into source code, issue reports, or chat messages. The free API currently documents a 1 MB file size, up to 3 PDF pages per request, and request quotas. These provider limits can change; consult the [OCR.space API documentation](https://ocr.space/ocrapi) before processing large files or planning a demonstration.

## 10. Run the application

```powershell
python -m backend.app
```

Open [http://127.0.0.1:5000](http://127.0.0.1:5000). The dashboard checks Google Document AI configuration for its cloud integration guide. The upload dialog uses OCR.space; it requires `OCR_SPACE_API_KEY` in the root `.env`. If the selected processor is missing or fails, the upload is recorded as failed and no extraction is shown as successful.

## 11. Expected output

OCR.space results show the actual recognized text and page count. For structured supplier/customer, invoice, tax, total, and line-item fields with confidence scores, use the separate Google Document AI Invoice Parser integration. Which data appears depends on the service response and source document.

With missing credentials, invalid processor configuration, unsupported file content, or a processing/API error, the attempt appears in history as failed with a clear error. No successful result is generated for these cases.

## 12. Limitations and future enhancements

- The configured processor is an Invoice Parser; this project does not route arbitrary business-document types to specialized processors.
- OCR.space requests are sequential and synchronous; the progress view polls SQLite while Flask is processing them. The 15 MB upload limit and provider quotas suit a college demonstration, not high-volume batch ingestion.
- Uploaded files and the SQLite database are local to the application host; this is not a multi-user production deployment.
- The UI does not provide a document viewer/editor for correcting extracted values.
- Production hardening could add user authentication, role-based access, encrypted object storage, retention policies, background jobs, audit logging, deployment monitoring, and reviewed/corrected extraction feedback.

## 13. Tests

Run the focused backend tests with:

```powershell
python -m unittest discover -s tests -v
```

Tests use temporary SQLite databases and local generated PDFs; OCR.space responses are mocked only at the HTTP boundary, so tests do not consume cloud quotas or produce user-visible mock results. Verify a real extraction by uploading a genuine sample invoice with a valid OCR.space key.
