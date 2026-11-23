<div dir="rtl">

# מנהל תשלומים

אפליקציה מקומית לניהול חשבוניות, תשלומים ותזכורות. פועלת על המחשב בלבד, ללא אינטרנט, ללא ענן וללא עלות.

## התקנה (פעם אחת)

1. התקן Python 3.13 (64-bit) מהאתר הרשמי python.org. בהתקנה סמן **Add python.exe to PATH** ו-**py launcher**.
2. לחץ פעמיים על `install.bat` בתיקיית הפרויקט. ההתקנה יוצרת סביבה מבודדת, מתקינה את הספריות (נדרש אינטרנט רק בשלב זה), יוצרת את תיקיית הנתונים ומוסיפה קיצור דרך "מנהל תשלומים" לשולחן העבודה.

## הפעלה

לחץ פעמיים על קיצור הדרך **מנהל תשלומים** בשולחן העבודה (או על `start.bat`).
האפליקציה נפתחת בדפדפן בכתובת `http://127.0.0.1:8000`.

* חלון שחור ממוזער בשם "מנהל תשלומים – אל תסגור חלון זה" הוא השרת המקומי. סגירתו עוצרת את האפליקציה. כל מה שנשמר נשאר שמור.
* הפעלה חוזרת כשהאפליקציה כבר פועלת פשוט פותחת את הדפדפן.

## איפה נשמרים הנתונים

`C:\Users\<שם המשתמש>\PaymentManagerData`. התיקייה נמצאת מחוץ ל-OneDrive כדי שהנתונים יישארו במחשב ולא ייפגעו מסנכרון.

| תיקייה | תוכן |
|---|---|
| `live` | מסד הנתונים, החשבוניות והקבלות |
| `backups` | גיבויים |
| `logs` | יומן טכני |

**חשוב:** גיבוי שנשמר באותו מחשב אינו מגן מפני תקלה בדיסק. מומלץ להעתיק מדי פעם קובץ גיבוי לכונן חיצוני.

</div>

---

## Developer notes (English)

* **Stack:** Python 3.13, FastAPI + Uvicorn (bound to 127.0.0.1 only), Jinja2, vanilla JS, SQLite (stdlib). The pinned runtime lock is `requirements.txt`; dev tools are in `requirements-dev.txt`.
* **Virtual environment:** `%LOCALAPPDATA%\PaymentManager\venv`, kept outside OneDrive.
  * Install with dev tools: `install.bat -Dev`
* **Run tests:** `"%LOCALAPPDATA%\PaymentManager\venv\Scripts\python.exe" -m pytest`
* **Run server without opening a browser:** `... python.exe -m app --no-browser`
* **Optional overrides:** `%LOCALAPPDATA%\PaymentManager\config.json` (`{"data_root": "...", "port": 8000}`) or the env vars `PM_DATA_ROOT` / `PM_PORT`.
* **Regenerate the icon:** `python scripts/make_icon.py`
* **Development plan:** phases 0, then A–F.
  * **Phase 0 (complete):** launcher, data layout, single instance, Hebrew shell.
  * **Phase A (complete):** SQLite schema v1 with DB-level guards, migrations, strict dates/money, accounting model, integrity checks, Host/Origin/CSRF protection, RTL UI components.
  * **Phase B (complete):** properties/suppliers/categories with archive, manual invoices with PDF/JPG/PNG documents, details page, full/partial payments with receipts, void/correct, postpone, cancel, Paid tab, History (payments ledger + change log), Hebrew DD/MM/YYYY date picker.
* **Code layout:**
  * `app/db/` — schema, migrations, connection
  * `app/domain/` — pure logic: money, dates, accounting
  * `app/services/` — business operations
  * `app/web/` — HTTP security and dependencies
  * `app/i18n/he.py` — all Hebrew text
