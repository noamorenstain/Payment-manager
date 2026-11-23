"""All Hebrew UI strings live here so wording stays consistent across the app."""

APP_TITLE = "מנהל תשלומים"

# ------------------------------------------------------------------ navigation
# Sidebar navigation: (path, label). Order matches the specification §8.
NAV_ITEMS = [
    ("/", "לוח בקרה"),
    ("/payments", "כל התשלומים"),
    ("/invoices/new", "חשבונית חדשה"),
    ("/recurring", "תשלומים קבועים"),
    ("/history", "היסטוריה"),
    ("/settings", "הגדרות"),
]

PAGE_TITLES = {
    "/": "לוח בקרה",
    "/payments": "כל התשלומים",
    "/invoices/new": "חשבונית חדשה",
    "/recurring": "תשלומים קבועים",
    "/history": "היסטוריה",
    "/settings": "הגדרות",
}

# Python date.weekday(): Monday == 0
WEEKDAYS = ["יום שני", "יום שלישי", "יום רביעי", "יום חמישי", "יום שישי", "שבת", "יום ראשון"]

TODAY_LABEL = "היום"
LAST_BACKUP_LABEL = "גיבוי אחרון"
NO_BACKUP_YET = "טרם בוצע גיבוי"

# ------------------------------------------------------------------ generic pages
DASHBOARD_EMPTY_TITLE = "אין כרגע פריטים הדורשים טיפול"
DASHBOARD_EMPTY_BODY = "כאן יופיעו תשלומים באיחור, תשלומים קרובים, תזכורות ותשלומים שחסר בהם סכום."

UNDER_CONSTRUCTION_TITLE = "המסך ייבנה בשלב הבא"
UNDER_CONSTRUCTION_BODY = "התשתית מוכנה. מסך זה יתווסף בהמשך תוכנית הפיתוח."

NOT_FOUND_TITLE = "הדף לא נמצא"
NOT_FOUND_BODY = "הכתובת שביקשת אינה קיימת."
BACK_TO_DASHBOARD = "חזרה ללוח הבקרה"

SERVER_ERROR_TITLE = "אירעה שגיאה"
SERVER_ERROR_BODY = "הפעולה לא הושלמה. הנתונים שנשמרו קודם לכן לא נפגעו. פרטי השגיאה נרשמו ביומן."

FORBIDDEN_TITLE = "הפעולה נחסמה"

# ------------------------------------------------------------------ security
SECURITY_BLOCKED_TITLE = "הבקשה נחסמה"
SECURITY_BAD_HOST = "מנהל התשלומים זמין רק מהכתובת http://127.0.0.1 במחשב זה."
SECURITY_CROSS_SITE = "הבקשה לא נשלחה מתוך מנהל התשלומים ולכן נחסמה לשם הגנה על הנתונים."
CSRF_FAILED = "תוקף הטופס פג או שהבקשה אינה מאומתת. רענן את הדף ונסה שוב."

# ------------------------------------------------------------------ dates
DATE_REQUIRED = "יש להזין תאריך."
DATE_BAD_FORMAT = "תאריך לא תקין. יש להזין תאריך בפורמט DD/MM/YYYY, לדוגמה 15/03/2026."
DATE_NOT_EXISTS = "תאריך לא קיים: {value}"
DATE_INVALID_MONTH = "חודש לא תקין בתאריך: {value}"
DATE_YEAR_RANGE = "השנה חייבת להיות בין {min} ל-{max}."
DATE_IN_FUTURE = "התאריך אינו יכול להיות עתידי."
DATE_PAYMENT_IN_FUTURE = "תאריך התשלום אינו יכול להיות עתידי."
DATE_MUST_BE_AFTER = "התאריך חייב להיות מאוחר מ-{other}."
DATE_RANGE_INVERTED = "תאריך ההתחלה חייב להיות לפני תאריך הסיום או שווה לו."

# ------------------------------------------------------------------ amounts
AMOUNT_REQUIRED = "יש להזין סכום."
AMOUNT_BAD_FORMAT = "סכום לא תקין. יש להזין מספר, לדוגמה 1,200 או 1200.50."
AMOUNT_NEGATIVE = "הסכום חייב להיות חיובי."
AMOUNT_ZERO = "הסכום חייב להיות גדול מאפס."
AMOUNT_TOO_MANY_DECIMALS = "ניתן להזין עד שתי ספרות אחרי הנקודה העשרונית."
AMOUNT_TOO_LARGE = "הסכום גדול מדי."
INSTALLMENTS_TOO_MANY = "מספר התשלומים גדול מהסכום הכולל."

# ------------------------------------------------------------------ database rule violations
DB_ERRORS = {
    "overpayment": "סכום התשלום גבוה מהיתרה לתשלום. לא ניתן לשלם יותר מהיתרה.",
    "payment_on_inactive_obligation": "לא ניתן לרשום תשלום על התחייבות שבוטלה או פוצלה מחדש.",
    "payment_on_missing_amount": "יש להזין קודם את סכום החיוב ורק אחר כך לרשום תשלום.",
    "payment_inserted_voided": "לא ניתן ליצור תשלום מבוטל.",
    "payment_immutable": "לא ניתן לשנות תשלום שנרשם. לתיקון יש לבטל את התשלום ולרשום תשלום מתוקן.",
    "payment_already_voided": "התשלום כבר בוטל.",
    "void_on_restructured": "לא ניתן לבטל תשלום של התחייבות שפוצלה מחדש. יש לרשום תיקון באחד מתשלומי ההמשך.",
    "obligation_identity_immutable": "לא ניתן לשנות את פרטי הזיהוי המקוריים של ההתחייבות.",
    "obligation_closed": "ההתחייבות סגורה (בוטלה או פוצלה מחדש) ולא ניתן לשנות את הסכום, המועד או המצב שלה.",
    "amount_cannot_be_removed": "לא ניתן למחוק סכום שכבר הוזן.",
    "amount_below_paid": "הסכום אינו יכול להיות נמוך מהסכום שכבר שולם.",
    "missing_amount_not_variable": "יש להזין סכום. סכום לא ידוע מותר רק בתשלום קבוע עם סכום משתנה.",
    "invoice_total_required": "יש להזין את הסכום הכולל של החשבונית.",
    "attachment_immutable": "לא ניתן לשנות קובץ מצורף. ניתן להחליף אותו בגרסה חדשה.",
    "attachment_already_superseded": "הקובץ כבר הוחלף בגרסה חדשה.",
    "history_immutable": "רשומות היסטוריה אינן ניתנות לשינוי.",
    "pause_immutable": "לא ניתן לשנות פרטי השהיה קיימת.",
    "pause_already_resumed": "ההשהיה כבר הסתיימה.",
    "delete_forbidden": "מחיקה לצמיתות אינה אפשרית. ניתן לבטל או להעביר לארכיון.",
    "foreign_key": "הרשומה מקושרת לנתונים שאינם קיימים.",
    "unique": "רשומה זהה כבר קיימת.",
    "check": "אחד הערכים אינו תקין.",
    "not_null": "חסר שדה חובה.",
    "unknown": "הפעולה נכשלה בשל ערך לא תקין. הנתונים לא השתנו.",
}

# ------------------------------------------------------------------ integrity
INTEGRITY_BANNER_TITLE = "נמצאה בעיה בבדיקת תקינות הנתונים"
INTEGRITY_BANNER_BODY = "הנתונים לא שונו. מומלץ לא להזין נתונים חדשים ולפנות לבדיקה. הפרטים נרשמו ביומן."
INTEGRITY_SQLITE = "קובץ מסד הנתונים פגום."
INTEGRITY_FOREIGN_KEYS = "נמצאו קישורים שבורים בין רשומות."
INTEGRITY_CHANGE_COUNTER = "מונה השינויים חסר."
INTEGRITY_INVOICE_SUM = "סכום חשבונית אינו תואם לסכום התשלומים, הביטולים והיתרה."
INTEGRITY_RESTRUCTURE_SUM = "פיצול יתרה אינו תואם לסכום תשלומי ההמשך."
INTEGRITY_PAUSE_STATE = "מצב השהיה של תשלום קבוע אינו עקבי."
INTEGRITY_MISSING_AMOUNT = "נמצא חיוב ללא סכום שאינו תשלום קבוע עם סכום משתנה."

# ------------------------------------------------------------------ labels
OBLIGATION_STATES = {
    "open": "פתוח",
    "partial": "שולם חלקית",
    "paid": "שולם במלואו",
    "missing_amount": "חסר סכום",
    "canceled": "בוטל",
    "restructured": "פוצל מחדש",
}
URGENCY_FLAGS = {
    "overdue": "באיחור",
    "due_today": "היום",
    "due_soon": "בקרוב",
    "reminder": "תזכורת",
}
INVOICE_STATES = {
    "open": "פתוחה",
    "partial": "שולמה חלקית",
    "paid": "שולמה במלואה",
    "missing_amount": "חסר סכום",
    "canceled": "בוטלה",
    "closed_partly_canceled": "נסגרה – חלקה בוטל",
}
CANCELED_AFTER_PARTIAL = "שולם חלקית לפני ביטול"
UNKNOWN_AMOUNT = "סכום לא ידוע"

PAYMENT_METHODS = {
    "bank_transfer": "העברה בנקאית",
    "card": "כרטיס אשראי",
    "cash": "מזומן",
    "check": "צ'ק",
    "other": "אחר",
}
FREQUENCIES = {
    "monthly": "חודשי",
    "bimonthly": "כל חודשיים",
    "quarterly": "רבעוני",
    "annual": "שנתי",
}

# ------------------------------------------------------------------ lookups (Phase B)
LOOKUP_TITLES = {"properties": "נכסים", "suppliers": "ספקים", "categories": "קטגוריות"}
LOOKUP_SINGULAR = {"properties": "נכס", "suppliers": "ספק", "categories": "קטגוריה"}
LOOKUP_NAME_REQUIRED = "יש להזין שם."
LOOKUP_NAME_EXISTS = "השם \"{name}\" כבר קיים."
LOOKUP_NAME_ARCHIVED = "\"{name}\" קיים בארכיון. ניתן לשחזר אותו מעמוד ההגדרות."
LOOKUP_GENERAL_CANNOT_ARCHIVE = "לא ניתן להעביר לארכיון את \"הוצאה כללית\"."
LOOKUP_ARCHIVED_CHOICE = "הפריט שנבחר נמצא בארכיון. יש לבחור פריט פעיל."
ARCHIVED_LABEL = "בארכיון"

# ------------------------------------------------------------------ invoice form
SUPPLIER_REQUIRED = "יש לבחור ספק או להזין שם ספק חדש."
PROPERTY_REQUIRED = "יש לבחור נכס או \"הוצאה כללית\"."
CATEGORY_INVALID = "הקטגוריה שנבחרה אינה קיימת."
CURRENCY_REQUIRED = "יש לבחור מטבע."
LEAD_DAYS_RANGE = "מספר ימי התזכורת חייב להיות בין 0 ל-365."
LEAD_DAYS_BAD = "יש להזין מספר ימים שלם."
AMOUNT_EDIT_NOT_ALLOWED = "לא ניתן לשנות את הסכום של התחייבות שבוטלה או פוצלה."
WARN_RECEIVED_BEFORE_ISSUE = "תאריך הקבלה מוקדם מתאריך ההנפקה."
CONFIRM_WARNINGS_TITLE = "יש לאשר את האזהרות הבאות לפני השמירה:"
CONFIRM_WARNINGS_LABEL = "בדקתי ואני מאשר/ת לשמור"
NEW_SUPPLIER_HINT = "ניתן לבחור מהרשימה או להקליד שם חדש – ספק חדש ייווצר בשמירה."

# ------------------------------------------------------------------ obligations & payments
OBLIGATION_NOT_ACTIVE = "ההתחייבות סגורה (בוטלה או פוצלה מחדש)."
POSTPONE_NOTHING_OPEN = "אין יתרה פתוחה לדחייה."
DUE_DATE_UNCHANGED = "המועד החדש זהה למועד הנוכחי."
DUE_DATE_EDIT_REASON = "עדכון מועד בעריכת פרטים"
CANCEL_REASON_REQUIRED = "יש לציין סיבת ביטול."
CANCEL_NOTHING_OPEN = "אין יתרה פתוחה לביטול."
REMINDER_RESOLVED_CANCELED = "ההתחייבות בוטלה"
REMINDER_RESOLVED_PAID = "שולם במלואו"
PAYMENT_EXCEEDS_OUTSTANDING = "סכום התשלום גבוה מהיתרה לתשלום ({outstanding})."
PAYMENT_METHOD_REQUIRED = "יש לבחור אמצעי תשלום."
VOID_REASON_REQUIRED = "יש לציין סיבה לביטול התשלום."
PAYMENT_ALREADY_RECORDED = "התשלום כבר נרשם (הטופס נשלח פעמיים)."

# ------------------------------------------------------------------ files
FILE_BAD_TYPE = "ניתן לצרף רק קובצי PDF, JPG או PNG."
FILE_TOO_LARGE = "הקובץ גדול מדי (מקסימום {mb} MB)."
FILE_EMPTY = "הקובץ ריק."
FILE_CONTENT_MISMATCH = "תוכן הקובץ אינו תואם לסוג הקובץ. ייתכן שהקובץ פגום או שאינו PDF/תמונה."
FILE_STAGED_MISSING = "הקובץ שנבחר אינו זמין עוד. יש לבחור אותו מחדש."
FILE_REPLACE_MISMATCH = "לא ניתן להחליף קובץ השייך לרשומה אחרת."
FILE_REQUIRED = "יש לבחור קובץ."
FILE_KEPT = "הקובץ נשמר זמנית ויצורף בשמירה:"

# ------------------------------------------------------------------ flash messages (after redirect)
FLASH = {
    "invoice_created": "החשבונית נשמרה.",
    "invoice_updated": "הפרטים עודכנו.",
    "invoice_canceled": "היתרה הפתוחה בוטלה. התשלומים שבוצעו נשמרו.",
    "payment_recorded": "התשלום נרשם.",
    "payment_recorded_full": "התשלום נרשם. החשבון שולם במלואו.",
    "payment_already_recorded": "התשלום כבר נרשם (הטופס נשלח פעמיים).",
    "payment_voided": "התשלום בוטל ונשמר בהיסטוריה.",
    "payment_corrected": "התשלום בוטל ונרשם תשלום מתוקן.",
    "postponed": "המועד נדחה.",
    "obligation_canceled": "היתרה בוטלה. התשלומים שבוצעו נשמרו.",
    "document_added": "המסמך צורף.",
    "document_replaced": "המסמך הוחלף. הגרסה הקודמת נשמרה.",
    "receipt_added": "הקבלה צורפה.",
    "lookup_created": "נשמר.",
    "lookup_updated": "עודכן.",
    "lookup_archived": "הועבר לארכיון. הרשומות הקיימות לא השתנו.",
    "lookup_unarchived": "שוחזר מהארכיון.",
}

# ------------------------------------------------------------------ audit log
ENTITY_TYPES = {
    "invoice": "חשבונית", "obligation": "התחייבות", "payment": "תשלום", "attachment": "מסמך",
    "property": "נכס", "supplier": "ספק", "category": "קטגוריה",
}
AUDIT_ACTIONS = {
    "create": "נוצר",
    "update": "עודכן",
    "cancel": "בוטל",
    "postpone": "מועד נדחה",
    "due_date_change": "מועד עודכן",
    "payment_recorded": "תשלום נרשם",
    "payment_voided": "תשלום בוטל",
    "payment_correction": "תשלום מתוקן נרשם",
    "attachment_added": "מסמך צורף",
    "attachment_replaced": "מסמך הוחלף",
    "reminders_resolved": "תזכורות נסגרו",
    "archive": "הועבר לארכיון",
    "unarchive": "שוחזר מהארכיון",
}

ONBOARDING_TITLE = "ברוכים הבאים למנהל התשלומים"
ONBOARDING_BODY = ("כדי להתחיל, מומלץ להוסיף את הנכסים, הספקים והקטגוריות שלך. "
                   "אפשר גם להתחיל ישר מחשבונית חדשה – ספק חדש ייווצר אוטומטית.")

# ------------------------------------------------------------------ launcher messages
LAUNCH_PORT_IN_USE = (
    "לא ניתן להפעיל את מנהל התשלומים: הפורט {port} תפוס על ידי תוכנה אחרת.\n"
    "סגור את התוכנה האחרת או שנה את הפורט בקובץ ההגדרות:\n{config_path}"
)
LAUNCH_START_FAILED = "הפעלת מנהל התשלומים נכשלה.\nפרטים נרשמו ביומן:\n{log_path}"
LAUNCH_SCHEMA_TOO_NEW = (
    "מסד הנתונים נוצר בגרסה חדשה יותר של מנהל התשלומים ולכן לא נפתח, כדי שלא ייפגע.\n"
    "יש להשתמש בגרסה המעודכנת של התוכנה."
)
LAUNCH_ONEDRIVE_WARNING = (
    "תיקיית הנתונים נמצאת בתוך OneDrive:\n{path}\n"
    "מומלץ להעביר אותה לתיקייה מקומית שאינה מסונכרנת כדי למנוע פגיעה במסד הנתונים."
)
CONSOLE_TITLE = "מנהל תשלומים – אל תסגור חלון זה"
