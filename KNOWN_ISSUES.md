# Known Issues & Observations Catalog

This document records existing application issues, potential edge cases, and observations cataloged during the initial project inspection and onboarding.

> **Note:** As per onboarding protocol, these issues are documented for cataloging only and have NOT been modified or fixed during Git migration. They will be addressed systematically in future targeted development tasks.

---

## 1. Project Assignment Integrity Check

- **Issue:** Project Assignment Duplicate Vendor Edge Case
- **Module:** Projects / Developers / Vendors (`billing/views.py:project_assign_developer`)
- **Current Behaviour:** Assigning the same developer/vendor to a project multiple times with identical parameters may trigger a database or integrity constraint error if unique key parameters overlap.
- **Expected Behaviour:** Form validation should display a clean, user-friendly validation error preventing duplicate active assignments for the same developer on the same project role.
- **Possible Cause:** Lack of explicit unique validation constraint check in `ProjectAssignmentForm` or view validation prior to model saving.
- **Risk:** Low (Occurs only on manual duplicate assignment submission).
- **Recommended Next Step:** Add form validation in `ProjectAssignmentForm.clean()` to check for existing active assignment records.

---

## 2. Dynamic Invoice Item-Row Deletion in UI Formset

- **Issue:** Dynamic Formset Row Index Shift on Deletion
- **Module:** Invoice Creation & Editing (`billing/forms.py`, `templates/billing/invoice_form.html`)
- **Current Behaviour:** When deleting an intermediate line item row during dynamic invoice creation or editing, row indices or serial numbers may occasionally require re-indexing before post-submission.
- **Expected Behaviour:** Deleting a row dynamically in JavaScript should auto-renumber serial numbers (`serial_number`) seamlessly before form submission.
- **Possible Cause:** Client-side JavaScript DOM removal does not auto-update the hidden input `serial_number` fields for remaining rows.
- **Risk:** Low (Mainly impacts UI serial number sequencing).
- **Recommended Next Step:** Enhance formset JavaScript helper in `invoice_form.html` to re-sequence serial numbers dynamically on row deletion.

---

## 3. Currency Aggregation in Dashboard Summary Cards

- **Issue:** INR / USD Dashboard Metrics Aggregation Mismatch
- **Module:** Dashboard (`billing/views.py:dashboard`)
- **Current Behaviour:** Dashboard aggregate summary metrics (total received amount, total pending amount) calculate across invoices and projects, but require strict segregation when handling mixed currency records (INR vs USD).
- **Expected Behaviour:** Separate currency totals (Total INR Received/Pending vs Total USD Received/Pending) should display in dedicated currency breakdown cards.
- **Possible Cause:** Combined aggregation queries without explicit `group_by` currency filter in summary views.
- **Risk:** Medium (Can cause visual misrepresentation of total financial metrics if INR and USD totals are combined without currency conversion).
- **Recommended Next Step:** Ensure all dashboard aggregation queries explicitly split totals by `currency` field (`CURRENCY_INR` vs `CURRENCY_USD`).

---

## 4. PDF Invoice Static Asset Caching in Local Server Mode

- **Issue:** WeasyPrint Font / Image Cache Directory Creation
- **Module:** PDF Generation (`billing/services.py:generate_invoice_pdf`)
- **Current Behaviour:** When running under non-standard local user permission environments, WeasyPrint fontconfig cache initialization writes temporary cache files to local directories.
- **Expected Behaviour:** Fontconfig cache path should gracefully redirect to a user-writable local directory (`LOCAL_CACHE_DIR`).
- **Possible Cause:** System default fontconfig path requires write access.
- **Risk:** Low (Handled by existing settings `LOCAL_CACHE_DIR` configuration in `settings.py`).
- **Recommended Next Step:** Maintain environment variable setting `XDG_CACHE_HOME` pointed to local project data directory.
