# Agent Rules

- Do not modify any files under `teleapp/` or `_vendor_teleapp/` unless the user explicitly approves in the current conversation.
- If a change there is necessary, ask for confirmation first and wait for approval before editing.
- When teleapp changes are approved, keep both copies in sync: `C:\Users\kevin\codex\robot\teleapp` and `C:\Users\kevin\teleapp\teleapp` (and corresponding `_vendor_teleapp` mirrors when applicable).
- For document-analysis tasks, prefer `markitdown` first:
  - If user provides `.pdf`, `.docx`, `.pptx`, `.xlsx`, `.xls`, `.html`, `.htm`, or similar office/web documents, convert to Markdown before summarizing, searching, comparing, or extracting structured notes.
  - If user explicitly asks for direct raw-file handling instead of conversion, follow user instruction.
- For email delivery tasks, use local sendmail project by default:
  - Preferred command path: `python C:\Users\kevin\codex\sendmail\sendmail.py ...`
  - Trigger when user asks to "寄信", "寄到信箱", "email", or "send".
  - If recipient, subject, or body is missing, ask for missing fields first.
  - Attach generated Markdown report files by default when available, unless user says not to attach.
