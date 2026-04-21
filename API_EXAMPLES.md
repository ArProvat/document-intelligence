# API Examples

This file shows the main request and response shapes for the backend.

Base URL:

```text
http://localhost:8000
```

## 1. Health Check

Request:

```powershell
curl.exe http://localhost:8000/health
```

Response:

```json
{
  "status": "ok"
}
```

## 2. Create Session

Request:

```powershell
curl.exe -X POST http://localhost:8000/sessions `
  -H "Content-Type: application/json" `
  -d "{\"user_id\":\"operator_001\"}"
```

Response:

```json
{
  "session_id": "2e7d5d14-4348-4217-a779-545689326fe3",
  "user_id": "operator_001",
  "created_at": "2026-04-21T07:20:13.021469Z",
  "document_ids": []
}
```

## 3. Upload Files

Request:

```powershell
curl.exe -X POST "http://localhost:8000/sessions/2e7d5d14-4348-4217-a779-545689326fe3/files" `
  -F "files=@C:\docs\sample_notice.pdf" `
  -F "files=@C:\docs\property_sheet.xlsx"
```

Response:

```json
{
  "session_id": "2e7d5d14-4348-4217-a779-545689326fe3",
  "uploaded_count": 2,
  "documents": [
    {
      "doc_id": "4930b36f-c304-4514-9cb8-a5a04af87db4",
      "filename": "sample_notice.pdf",
      "status": "processed",
      "message": "File processed successfully",
      "processing_time_seconds": 0.0,
      "quality_score": 0.87,
      "doc_type": "legal_notice",
      "total_pages": 4,
      "avg_confidence": 0.91,
      "chunk_count": 11,
      "entity_count": 7,
      "warnings": []
    },
    {
      "doc_id": "4c4af19a-a7c0-4df0-a707-40ca9f4d59d8",
      "filename": "property_sheet.xlsx",
      "status": "processed",
      "message": "File processed successfully",
      "processing_time_seconds": 0.0,
      "quality_score": 1.0,
      "doc_type": "unknown",
      "total_pages": 2,
      "avg_confidence": 1.0,
      "chunk_count": 6,
      "entity_count": 3,
      "warnings": [
        "Could not determine document type. Classification keywords may be absent."
      ]
    }
  ]
}
```

## 4. Generate Draft

Request:

```powershell
curl.exe -X POST "http://localhost:8000/sessions/2e7d5d14-4348-4217-a779-545689326fe3/drafts" `
  -H "Content-Type: application/json" `
  -d "{\"draft_type\":\"notice_related_summary\",\"instructions\":\"Focus on deadlines, issuing party, recipient, and missing service details.\"}"
```

Response:

```json
{
  "draft_id": "720ff8cb-f46f-4d14-bd55-3aaf744da60a",
  "session_id": "2e7d5d14-4348-4217-a779-545689326fe3",
  "draft_type": "notice_related_summary",
  "retrieval_query": "notice issuer recipient service date deadline cure period default allegations method of service",
  "draft": "This notice appears to have been issued by ABC Finance Ltd. to Rahim Traders regarding alleged payment default under the supply agreement. The retrieved materials indicate a cure deadline of 15 March 2026. The evidence identifies the recipient and the alleged default, but the mode of service is not clearly stated in the available documents. If service method is material, manual review is required.",
  "evidence": [
    {
      "doc_id": "4930b36f-c304-4514-9cb8-a5a04af87db4",
      "filename": "sample_notice.pdf",
      "chunk_id": "78f8d5bb-f1d5-4f06-b62b-50901477a4aa",
      "page_start": 1,
      "page_end": 2,
      "snippet": "Legal Notice dated 1 March 2026 issued by ABC Finance Ltd. to Rahim Traders ..."
    },
    {
      "doc_id": "4930b36f-c304-4514-9cb8-a5a04af87db4",
      "filename": "sample_notice.pdf",
      "chunk_id": "f0fe28a9-6ea8-4021-bff4-13020c77dc92",
      "page_start": 3,
      "page_end": 3,
      "snippet": "The recipient is required to cure the default on or before 15 March 2026 ..."
    }
  ],
  "applied_rules": [
    {
      "rule_id": "a44bca9f-3f5e-42c8-9f82-a963f66bfdd1",
      "description": "Lead with a one-sentence executive summary before detail.",
      "category": "structure",
      "confidence": 0.8
    }
  ],
  "generated_at": "2026-04-21T07:27:33.518712Z"
}
```

## 5. Submit Draft Feedback

This endpoint is asynchronous. It creates a feedback job and returns immediately.

Request:

```powershell
curl.exe -X POST "http://localhost:8000/drafts/720ff8cb-f46f-4d14-bd55-3aaf744da60a/feedback" `
  -H "Content-Type: application/json" `
  -d "{\"edited_draft\":\"Executive summary: ABC Finance Ltd. issued a legal notice to Rahim Traders concerning alleged payment default. The notice appears to set a cure deadline of 15 March 2026. The documents identify the issuer, recipient, and deadline, but do not clearly confirm service method. Always cite the date in the opening sentence when available.\",\"operator_notes\":\"Always open with a one-line summary and cite exact dates early.\"}"
```

Initial response:

```json
{
  "feedback_id": "f3ab9671-dccd-47fa-8f3e-ccba3bd57619",
  "draft_id": "720ff8cb-f46f-4d14-bd55-3aaf744da60a",
  "status": "pending",
  "extracted_rules": [],
  "active_rules": [
    {
      "rule_id": "a44bca9f-3f5e-42c8-9f82-a963f66bfdd1",
      "description": "Lead with a one-sentence executive summary before detail.",
      "category": "structure",
      "example_before": "The notice appears to have been issued by ABC Finance Ltd...",
      "example_after": "Executive summary: ABC Finance Ltd. issued a legal notice...",
      "applicable_draft_types": [
        "notice_related_summary"
      ],
      "confidence": 0.8,
      "support_count": 2,
      "status": "active",
      "last_updated": "2026-04-21T07:27:33.519185Z"
    }
  ],
  "structured_diff": [],
  "error_message": null,
  "submitted_at": "2026-04-21T07:31:10.118991Z",
  "processed_at": null
}
```

## 6. Poll Feedback Status

Request:

```powershell
curl.exe "http://localhost:8000/feedback/f3ab9671-dccd-47fa-8f3e-ccba3bd57619"
```

Completed response:

```json
{
  "feedback_id": "f3ab9671-dccd-47fa-8f3e-ccba3bd57619",
  "draft_id": "720ff8cb-f46f-4d14-bd55-3aaf744da60a",
  "status": "completed",
  "extracted_rules": [
    {
      "rule_id": "6cda1714-aa5e-4f14-93fd-2263a844fbc1",
      "description": "When a concrete date is available, mention it in the opening summary sentence.",
      "category": "completeness",
      "example_before": "This notice appears to have been issued by ABC Finance Ltd. to Rahim Traders regarding alleged payment default.",
      "example_after": "Executive summary: ABC Finance Ltd. issued a legal notice to Rahim Traders on 1 March 2026 concerning alleged payment default.",
      "applicable_draft_types": [
        "notice_related_summary"
      ],
      "confidence": 0.78,
      "support_count": 1,
      "status": "active",
      "last_updated": "2026-04-21T07:31:12.881334Z"
    }
  ],
  "active_rules": [
    {
      "rule_id": "a44bca9f-3f5e-42c8-9f82-a963f66bfdd1",
      "description": "Lead with a one-sentence executive summary before detail.",
      "category": "structure",
      "example_before": "The notice appears to have been issued by ABC Finance Ltd...",
      "example_after": "Executive summary: ABC Finance Ltd. issued a legal notice...",
      "applicable_draft_types": [
        "notice_related_summary"
      ],
      "confidence": 0.9,
      "support_count": 3,
      "status": "active",
      "last_updated": "2026-04-21T07:31:12.881311Z"
    },
    {
      "rule_id": "6cda1714-aa5e-4f14-93fd-2263a844fbc1",
      "description": "When a concrete date is available, mention it in the opening summary sentence.",
      "category": "completeness",
      "example_before": "This notice appears to have been issued by ABC Finance Ltd. to Rahim Traders regarding alleged payment default.",
      "example_after": "Executive summary: ABC Finance Ltd. issued a legal notice to Rahim Traders on 1 March 2026 concerning alleged payment default.",
      "applicable_draft_types": [
        "notice_related_summary"
      ],
      "confidence": 0.78,
      "support_count": 1,
      "status": "active",
      "last_updated": "2026-04-21T07:31:12.881334Z"
    }
  ],
  "structured_diff": [
    {
      "operation": "replace",
      "before": "This notice appears to have been issued by ABC Finance Ltd. to Rahim Traders regarding alleged payment default under the supply agreement.",
      "after": "Executive summary: ABC Finance Ltd. issued a legal notice to Rahim Traders concerning alleged payment default."
    },
    {
      "operation": "insert",
      "before": "",
      "after": "Always cite the date in the opening sentence when available."
    }
  ],
  "error_message": null,
  "submitted_at": "2026-04-21T07:31:10.118991Z",
  "processed_at": "2026-04-21T07:31:12.881362Z"
}
```

## 7. List Style Rules For A User

Request:

```powershell
curl.exe "http://localhost:8000/users/operator_001/style-rules?draft_type=notice_related_summary"
```

Response:

```json
[
  {
    "rule_id": "a44bca9f-3f5e-42c8-9f82-a963f66bfdd1",
    "description": "Lead with a one-sentence executive summary before detail.",
    "category": "structure",
    "example_before": "The notice appears to have been issued by ABC Finance Ltd...",
    "example_after": "Executive summary: ABC Finance Ltd. issued a legal notice...",
    "applicable_draft_types": [
      "notice_related_summary"
    ],
    "confidence": 0.9,
    "support_count": 3,
    "status": "active",
    "last_updated": "2026-04-21T07:31:12.881311Z"
  }
]
```

## 8. Disable A Rule

Request:

```powershell
curl.exe -X POST "http://localhost:8000/users/operator_001/style-rules/a44bca9f-3f5e-42c8-9f82-a963f66bfdd1/disable"
```

Response:

```json
{
  "rule_id": "a44bca9f-3f5e-42c8-9f82-a963f66bfdd1",
  "description": "Lead with a one-sentence executive summary before detail.",
  "category": "structure",
  "example_before": "The notice appears to have been issued by ABC Finance Ltd...",
  "example_after": "Executive summary: ABC Finance Ltd. issued a legal notice...",
  "applicable_draft_types": [
    "notice_related_summary"
  ],
  "confidence": 0.9,
  "support_count": 3,
  "status": "disabled",
  "last_updated": "2026-04-21T07:35:44.100011Z"
}
```

## 9. Delete A Rule

Request:

```powershell
curl.exe -X DELETE "http://localhost:8000/users/operator_001/style-rules/a44bca9f-3f5e-42c8-9f82-a963f66bfdd1"
```

Response:

```json
{
  "rule_id": "a44bca9f-3f5e-42c8-9f82-a963f66bfdd1",
  "deleted": true
}
```

## Error Cases

### Session not found

```json
{
  "detail": "Session not found"
}
```

### No documents uploaded

```json
{
  "detail": "No documents uploaded for this session"
}
```

### Rule or draft not found

```json
{
  "detail": "Draft run not found"
}
```

## Notes

- `session_id` is session-scoped and temporary
- style rules are stored user-wise, not session-wise
- `POST /drafts/{draft_id}/feedback` is async and should be polled
- examples use `curl.exe` for Windows PowerShell clarity
- example IDs and timestamps here are illustrative
