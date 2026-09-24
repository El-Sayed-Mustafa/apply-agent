"""
اختبارات صندوق الطلبات.

الفرق بين الشريحة دي وباقي المشروع إن المدخلات هنا **من ناس مش
معروفين**: اسم الملف والعنوان والنص كلهم جايين من برّه. فمعظم
الاختبارات على اللي بنرفضه، مش اللي بنقبله.
"""
import email
from email.message import EmailMessage

import pytest

from src import inbox


def mail(subject="Data Analyst - Scraping", body="Please find my CV attached.",
         frm="Marwan Ragaa <marob27105@gmail.com>", files=()):
    m = EmailMessage()
    m["From"] = frm
    m["To"] = "company@bluebug.io"
    m["Subject"] = subject
    m["Message-ID"] = "<abc@mail.gmail.com>"
    m.set_content(body)
    for name, data in files:
        m.add_attachment(data, maintype="application", subtype="pdf",
                         filename=name)
    return email.message_from_bytes(m.as_bytes())


# ── اسم الملف ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", [
    "Marwan_Basem_s_Resume (23).pdf", "cv.docx", "سيرة ذاتية.pdf",
    "My CV.PDF", "resume.odt",
])
def test_document_names_accepted(name):
    assert inbox.safe_name(name)


@pytest.mark.parametrize("bad", [
    "../../../etc/passwd", "..\\..\\windows\\system32\\evil.exe",
    "resume.exe", "cv.bat", "setup.msi", "script.js", "payload.zip",
    ".hidden", "",
])
def test_dangerous_or_irrelevant_names_rejected(bad):
    """
    اسم الملف جاي من المرسِل. لو عدّى زي ما هو، ممكن يكتب برّه
    المجلد أو يسيب ملف تنفيذي على الجهاز.
    """
    assert inbox.safe_name(bad) is None


def test_path_is_stripped_not_the_whole_name():
    """مسار جوّه الاسم بيتشال، والملف نفسه بيفضل."""
    out = inbox.safe_name("folder/sub/My Resume.pdf")
    assert out and out.endswith(".pdf") and "/" not in out


# ── قراءة الرسالة ───────────────────────────────────────────────────────

def test_sender_split():
    name, addr = inbox.sender(mail())
    assert name == "Marwan Ragaa"
    assert addr == "marob27105@gmail.com"


def test_encoded_subject_decoded():
    """العناوين العربية بتيجي مشفّرة base64."""
    m = mail(subject="مهندس برمجيات . حديث تخرج")
    assert "مهندس" in inbox._text(m.get("Subject"))


def test_body_extracted():
    assert "CV attached" in inbox.body_text(mail())


# ── هل دي طلب وظيفة ─────────────────────────────────────────────────────

@pytest.mark.parametrize("subject", [
    "Data Analyst - Scraping", "Data analyst- scraping",
    '"Data Analyst - Scarping"', "Junior Python Developer Application",
    "Data & SQL", "Python Developer", "مهندس برمجيات . حديث تخرج",
    "Join the team",
])
def test_subject_variants_recognised(subject):
    """
    الطلبات اللي وصلت كتبت العنوان بأشكال كتير — وواحد كتب
    "Scarping". المطابقة الحرفية على عنوان واحد كانت هتضيّعهم.
    """
    assert inbox.looks_like_application(subject, "", [])


def test_attachment_alone_is_enough():
    """حد بعت الـCV من غير أي كلام — ده طلب برضه."""
    assert inbox.looks_like_application("", "", ["cv.pdf"])


@pytest.mark.parametrize("subject,body", [
    ("Your Amazon.com order", "Your package is on the way"),
    ("Invoice #4421", "Payment received"),
])
def test_ordinary_mail_ignored(subject, body):
    assert not inbox.looks_like_application(subject, body, [])


# ── المرفقات ────────────────────────────────────────────────────────────

def test_attachment_saved(tmp_path):
    m = mail(files=[("cv.pdf", b"%PDF-1.4 fake")])
    saved = inbox.save_parts(m, tmp_path / "marob27105", dry=False)
    assert saved == ["cv.pdf"]
    assert (tmp_path / "marob27105" / "cv.pdf").read_bytes().startswith(b"%PDF")


def test_dry_run_writes_nothing(tmp_path):
    m = mail(files=[("cv.pdf", b"%PDF-1.4 fake")])
    saved = inbox.save_parts(m, tmp_path / "x", dry=True)
    assert saved == ["cv.pdf"]
    assert not (tmp_path / "x").exists()


def test_oversized_attachment_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(inbox, "MAX_BYTES", 10)
    m = mail(files=[("cv.pdf", b"x" * 500)])
    assert inbox.save_parts(m, tmp_path / "x", dry=False) == []


def test_executable_attachment_never_written(tmp_path):
    m = EmailMessage()
    m["From"] = "x@y.com"
    m["Subject"] = "cv"
    m.set_content("hi")
    m.add_attachment(b"MZ\x90\x00", maintype="application",
                     subtype="octet-stream", filename="resume.exe")
    saved = inbox.save_parts(email.message_from_bytes(m.as_bytes()),
                             tmp_path / "x", dry=False)
    assert saved == []
    assert not (tmp_path / "x" / "resume.exe").exists()


# ── الحالة ──────────────────────────────────────────────────────────────

def test_state_survives_a_corrupt_file(tmp_path, monkeypatch):
    bad = tmp_path / "applications.json"
    bad.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(inbox, "STATE", bad)
    assert inbox.load() == {}


def test_folder_name_is_safe():
    assert inbox.slug("Marwan Ragaa!! <>") == "marwan-ragaa"
    assert inbox.slug("") == "unknown"


# ── الإعداد ─────────────────────────────────────────────────────────────

def test_missing_credentials_fail_loudly(monkeypatch):
    """
    الفشل الصامت هنا معناه "0 طلب" وإحنا فاكرين إن الصندوق فاضي.
    """
    monkeypatch.delenv("GMAIL_USER", raising=False)
    monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)
    with pytest.raises(RuntimeError, match="GMAIL"):
        inbox.connect()
