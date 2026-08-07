# InvoiceApp for macOS

InvoiceApp is a local-only invoice management application. The installed app stores all user data outside the app bundle at:

```text
~/Documents/InvoiceApp/
```

## Final DMG Data Policy

- The final `.dmg` does not include dummy data.
- The final `.dmg` does not include real company, client, invoice, project, payment, media, report, backup, or log data.
- The app creates an empty SQLite database on first launch.
- The user creates the first admin account during first-time setup.
- Existing passwords are not changed during app updates.

## First Launch

1. Open `InvoiceApp`.
2. The app creates `~/Documents/InvoiceApp/` if needed.
3. The app creates an empty database and runs migrations.
4. The browser opens the first-time admin setup page.
5. Create your admin username and password.
6. Log in and begin adding your own business data.

## Existing Install or Update

If `~/Documents/InvoiceApp/db.sqlite3` already exists, InvoiceApp uses it as-is. App updates do not reset passwords, recreate users, overwrite the database, or insert sample data.

## Password Policy

- The password is created by the user during first launch.
- Passwords must be at least 8 characters and include a capital letter, number, and symbol.
- App updates do not change the password.
- If a password is forgotten, use the Django password change/reset or administrator recovery process for the local database.

## Runtime Files

The app may create these folders under `~/Documents/InvoiceApp/`:

```text
db.sqlite3
media/company_logos/
media/company_signatures/
media/invoices/
media/reports/
media/project_attachments/
backups/
logs/
```
