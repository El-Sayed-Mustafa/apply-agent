/**
 * الشريحة 12 — صندوق الطلبات (Apps Script)
 *
 * بيشتغل على سيرفر جوجل نفسه كل عشر دقايق:
 *
 *   Gmail  →  لِيبل "Applications" + أرشفة من الإنبوكس
 *          →  المرفقات في Drive: Applications/<المرشّح>/
 *          →  صف في شيت "Applications Log"
 *
 * ليه هنا مش على الجهاز:
 *
 * حساب Workspace مابيسمحش بـApp Password، وOAuth محتاج مشروع
 * في Google Cloud وملف اعتماديات على الجهاز. الكود ده بيشتغل
 * **جوّه حسابك** — مفيش سر بيتخزّن في أي مكان، والتنقيل بيحصل
 * أول ما الرسالة توصل مش لما تشغّل حاجة.
 *
 * التركيب:
 *   1. script.google.com ← New project ← الصق الملف ده
 *   2. شغّل setUp مرة واحدة (هيطلب صلاحيات Gmail و Drive)
 *   3. خلاص. بيشتغل لوحده كل عشر دقايق.
 *
 * المرفقات دي ملفات من ناس مش معروفين. بنخزّنها وبس — مابنفتحش
 * ولا بننفّذ حاجة، وبنقبل امتدادات المستندات وخلاص.
 */

// ── الإعدادات ───────────────────────────────────────────────────────────

const LABEL = 'Applications';
const FOLDER = 'Applications';
const SHEET_NAME = 'Applications Log';

// آخر 30 يوم، واللي ماخدش اللِيبل لسه. الشرط التاني هو اللي
// بيمنع التكرار وبيخلّي المتراكم يخلص على مدار كام تشغيلة.
const QUERY = 'newer_than:30d -label:' + LABEL;

// يطلع من الإنبوكس بعد ما يتسجّل. خليها false لو عايزه يفضل.
const ARCHIVE = true;

// Apps Script بيوقف بعد 6 دقايق. 40 محادثة في التشغيلة تخلص
// في أقل من دقيقتين، والباقي بياخد دوره في اللي بعدها.
const MAX_THREADS = 40;

const ALLOWED = ['pdf', 'doc', 'docx', 'rtf', 'odt', 'txt', 'md',
                 'png', 'jpg', 'jpeg'];
const MAX_BYTES = 15 * 1024 * 1024;

// العناوين اتكتبت بأشكال كتير: "Scarping" و"Join the team" وواحد
// بالعربي. فمابنطابقش العنوان — بنشوف الرسالة كلها، وأي رسالة
// معاها مرفق مستند بتعدّي على طول.
const APPLY = new RegExp(
  'scrap|scarp|data\\s*analyst|python\\s*develop|data\\s*&?\\s*sql|' +
  'data\\s*engineer|apply|application|resume|\\bcv\\b|hiring|position|' +
  'join\\s+(the|our|your)\\s+team|graduat|intern|' +
  'وظيف|تقديم|السيرة|مهندس|خريج|حديث\\s*ال?تخرج', 'i');


// ── التشغيل ─────────────────────────────────────────────────────────────

function processApplications() {
  const label = getLabel_(LABEL);
  const root = getFolder_(FOLDER);
  const sheet = getSheet_(root, SHEET_NAME);
  const seen = seenIds_(sheet);

  const threads = GmailApp.search(QUERY, 0, MAX_THREADS);
  let moved = 0, skipped = 0;

  threads.forEach(function (thread) {
    let matched = false;

    thread.getMessages().forEach(function (msg) {
      const id = msg.getId();
      if (seen[id]) { return; }

      const files = saveAttachments_(msg, root);
      const subject = msg.getSubject() || '';
      const body = (msg.getPlainBody() || '').slice(0, 2000);

      if (files.length === 0 && !APPLY.test(subject + ' ' + body)) {
        skipped++;
        return;
      }

      sheet.appendRow([
        msg.getDate(),
        senderName_(msg),
        senderEmail_(msg),
        subject,
        body.replace(/\s+/g, ' ').slice(0, 500),
        files.map(function (f) { return f.getName(); }).join(', '),
        files.length ? files[0].getUrl() : '',
        id,
        ''          // Status — تملاه انت
      ]);
      seen[id] = true;
      matched = true;
      moved++;
    });

    if (matched) {
      thread.addLabel(label);
      if (ARCHIVE) { thread.moveToArchive(); }
    }
  });

  console.log(moved + ' طلب جديد · ' + skipped + ' مش طلب · ' +
              threads.length + ' محادثة اتفحصت');
}


// ── المرفقات ────────────────────────────────────────────────────────────

/**
 * احفظ مرفقات المستندات في مجلد باسم المرشّح.
 *
 * اسم الملف جاي من المرسِل، فبنشيل منه أي مسار وبنقبل الامتدادات
 * المعروفة بس. ملف تنفيذي مابيتكتبش على Drive أصلاً.
 */
function saveAttachments_(msg, root) {
  const out = [];
  const who = slug_(senderEmail_(msg).split('@')[0]);

  msg.getAttachments({ includeInlineImages: false }).forEach(function (att) {
    const name = safeName_(att.getName());
    if (!name) { return; }
    if (att.getSize() > MAX_BYTES) { return; }

    const folder = getChild_(root, who);
    // نفس المرشّح ممكن يبعت مرتين — مابنكررش نفس الملف
    const existing = folder.getFilesByName(name);
    out.push(existing.hasNext() ? existing.next()
                                : folder.createFile(att.copyBlob().setName(name)));
  });

  return out;
}

function safeName_(raw) {
  let name = String(raw || '').replace(/[\\/]+/g, ' ').trim();
  name = name.replace(/[^\w\s.()\-؀-ۿ]/g, '_').slice(0, 120);
  if (!name || name.charAt(0) === '.') { return null; }
  const ext = name.split('.').pop().toLowerCase();
  return ALLOWED.indexOf(ext) === -1 ? null : name;
}

function slug_(text) {
  const s = String(text || '').toLowerCase().replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '');
  return (s || 'unknown').slice(0, 48);
}


// ── المساعدات ───────────────────────────────────────────────────────────

function senderEmail_(msg) {
  const m = /<(.+?)>/.exec(msg.getFrom());
  return (m ? m[1] : msg.getFrom()).trim().toLowerCase();
}

function senderName_(msg) {
  const from = msg.getFrom();
  const m = /^\s*"?([^"<]+?)"?\s*</.exec(from);
  return (m ? m[1] : senderEmail_(msg).split('@')[0]).trim();
}

function getLabel_(name) {
  return GmailApp.getUserLabelByName(name) || GmailApp.createLabel(name);
}

function getFolder_(name) {
  const it = DriveApp.getFoldersByName(name);
  return it.hasNext() ? it.next() : DriveApp.createFolder(name);
}

function getChild_(parent, name) {
  const it = parent.getFoldersByName(name);
  return it.hasNext() ? it.next() : parent.createFolder(name);
}

function getSheet_(folder, name) {
  const it = folder.getFilesByName(name);
  if (it.hasNext()) {
    return SpreadsheetApp.open(it.next()).getSheets()[0];
  }
  const ss = SpreadsheetApp.create(name);
  const file = DriveApp.getFileById(ss.getId());
  folder.addFile(file);
  DriveApp.getRootFolder().removeFile(file);

  const sheet = ss.getSheets()[0];
  sheet.appendRow(['Date', 'Name', 'Email', 'Subject', 'Message',
                   'Files', 'File link', 'Message ID', 'Status']);
  sheet.getRange('A1:I1').setFontWeight('bold').setBackground('#1F3A5F')
    .setFontColor('#FFFFFF');
  sheet.setFrozenRows(1);
  return sheet;
}

/** الرسايل اللي اتسجّلت قبل كده — عمود Message ID هو المرجع. */
function seenIds_(sheet) {
  const last = sheet.getLastRow();
  const seen = {};
  if (last < 2) { return seen; }
  sheet.getRange(2, 8, last - 1, 1).getValues().forEach(function (row) {
    if (row[0]) { seen[row[0]] = true; }
  });
  return seen;
}


// ── التركيب ─────────────────────────────────────────────────────────────

/** شغّلها مرة واحدة: بتاخد الصلاحيات وبتظبّط التشغيل التلقائي. */
function setUp() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'processApplications') {
      ScriptApp.deleteTrigger(t);
    }
  });
  ScriptApp.newTrigger('processApplications').timeBased()
    .everyMinutes(10).create();

  processApplications();
  console.log('تمام — هيشتغل كل عشر دقايق من دلوقتي.');
}
