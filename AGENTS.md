# Antigravity AI Agent Rules & Development Philosophy

This document defines the strict operating rules, safety constraints, and workflows required for all AI agents (including Google Antigravity) working on the **Personalised Invoice Generation Application**.

---

## 1. Core Mandate & Philosophy

> **Rule #1:** This is an active, production-grade business application.  
> **Do NOT rebuild, redesign, refactor, upgrade, or replace existing functionality unless explicitly instructed.**

### Prefer Targeted Fixes Over Rewrites
- Always prefer minimal, targeted, surgical code modifications over large multi-file rewrites.
- Preserve existing data schemas, URL structures, function signatures, form fields, and template structure.
- Respect established UI designs, CSS styling, and layout decisions.

---

## 2. Mandatory Workflow Before Modifying Code

Every code modification or feature addition MUST strictly follow this 8-step process:

```text
1. Understand Requirement
       ↓
2. Inspect Existing Implementation (Models, Views, Forms, Services, Templates)
       ↓
3. Trace Data Flow & Database Relationships
       ↓
4. Formulate Implementation Plan
       ↓
5. Make Minimal Targeted Code Changes
       ↓
6. Execute Automated Validation (.venv/bin/python manage.py check && test)
       ↓
7. Compare Behaviour Against Existing Baseline
       ↓
8. Report Specific Files Modified and Results
```

---

## 3. Strict Prohibitions (NEVER Automatically Do)

Unless explicitly requested by the user, AI agents MUST NEVER:

1. **Database Destructive Actions:**
   - Run `flush`, `reset_db`, `drop database`, or manually delete `db.sqlite3`.
   - Delete existing database migration files or reset migration history.
   - Re-create migrations unnecessarily without inspecting existing model states.
   - Delete existing user media, invoice PDFs, company logos, or backup archives.

2. **Business & Financial Logic Changes:**
   - Alter financial calculation logic, GST percentage formulas, or rounding rules (`_money`).
   - Change invoice numbering format rules or reset sequence numbering algorithms.
   - Alter currency handling logic between INR and USD.
   - Remove or bypass soft-deletion checks (`is_deleted`) for clients or invoices.

3. **Dependency & Environment Changes:**
   - Upgrade Python, Django, WeasyPrint, openpyxl, or other core packages without explicit authorization.
   - Commit sensitive credentials, API keys, passwords, or `db.sqlite3` to Git.
   - Commit runtime generated PDFs (`media/invoices/*`) or backup archives (`backups/*`) to Git.

---

## 4. Verification & Testing Commands

After making any code changes, always verify system integrity using the local virtual environment Python:

```bash
# Check Django app configuration health
.venv/bin/python manage.py check

# Check migration state
.venv/bin/python manage.py showmigrations

# Run full test suite
.venv/bin/python manage.py test
```

Never declare success without running and verifying these commands cleanly.
