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

// لِيبل على **كل** محادثة اتفحصت، حتى اللي طلعت مش طلب.
//
// من غيره، الرسالة اللي مش طلب مابتاخدش لِيبل فبتفضل في نتيجة
// البحث للأبد وبتاكل من حصة التشغيلة. لما عددها يكبر، الفرز
// بيقف والقديم ما يوصلّهوش دور — وده اللي حصل: 143 اتسجّلوا
// من يوم واحد، ورسايل يوم 23 فضلت في الإنبوكس.
const CHECKED = LABEL + '/Checked';

// نطاق البحث. من غيره الاستعلام بيفحص **كل** إيميل في الصندوق —
// إشعارات ChatGPT و Anthropic و Render و Supabase — ويحطلها لِيبل.
// ده اللي حصل: 247 محادثة اتلبّست Checked وهي مالهاش علاقة.
//
// بنستبعد المرسِلين الآليين، وبنطلب إشارة توظيف في العنوان أو
// وجود مرفق. الفلترة الدقيقة بتحصل بعدين على النص نفسه.
const SCOPE =
  '-from:noreply -from:no-reply -from:notifications -from:notification ' +
  '-category:promotions -category:social -category:forums ' +
  '(has:attachment OR subject:(scraping OR scarping OR scrapping OR ' +
  '"data analyst" OR "python developer" OR "data engineer" OR cv OR ' +
  'resume OR application OR applying OR hiring OR "join the team" OR ' +
  'وظيفة OR تقديم OR مهندس))';

const QUERY = 'newer_than:30d -label:"' + CHECKED + '" ' + SCOPE;

// يطلع من الإنبوكس بعد ما يتسجّل. خليها false لو عايزه يفضل.
const ARCHIVE = true;

// Apps Script بيوقف بعد 6 دقايق. بنشتغل على دفعات لحد ما
// المتراكم يخلص أو نقرّب من الحد — ساعتها التشغيلة اللي بعدها
// بتكمّل من حيث انتهينا.
const BATCH = 25;
const TIME_BUDGET_MS = 4.5 * 60 * 1000;

// اسم ملف شكله سيرة ذاتية — بيفرّق بين CV.pdf و invoice.pdf.
//
// مابنستخدمش  هنا: الشرطة السفلية محسوبة حرف كلمة، فـ
// "Mahmoud_Mabrouk_ATS_CV.pdf" مكنش بيتطابق و"CV.pdf" كان
// بيتطابق — وأي حد بعت سيرته من غير رسالة راح لسلة "مش طلبات".
const CV_NAME = /(^|[^a-z])(cv|resume|r[ée]sum[ée]|سيرة|ذاتية)([^a-z]|$)/i;

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
  const started = Date.now();
  const label = getLabel_(LABEL);
  const checked = getLabel_(CHECKED);
  const root = getFolder_(FOLDER);
  const sheet = getSheet_(root, SHEET_NAME);
  const seen = seenIds_(sheet);

  let moved = 0, skipped = 0, scanned = 0;

  // دفعات لحد ما المتراكم يخلص أو الوقت يقرّب. البحث دايمًا
  // بيرجّع اللي ماتفحصش، فمفيش صفحة تانية — كل دفعة بتبدأ من صفر.
  while (Date.now() - started < TIME_BUDGET_MS) {
    const threads = GmailApp.search(QUERY, 0, BATCH);
    if (!threads.length) { break; }
    scanned += threads.length;

    threads.forEach(function (thread) {
      let matched = false;

      thread.getMessages().forEach(function (msg) {
        const id = msg.getId();
        if (seen[id]) { return; }

        const files = saveAttachments_(msg, root);
        const subject = msg.getSubject() || '';
        const body = (msg.getPlainBody() || '').slice(0, 2000);

        // وجود مرفق لوحده **مش** كفاية: فواتير Anthropic وتقارير
        // Supabase بتيجي PDF، وكانت بتتسجّل كطلبات. لازم إشارة
        // توظيف في النص، أو اسم ملف شكله سيرة ذاتية.
        const cvFile = files.some(function (f) {
          return CV_NAME.test(f.getName());
        });
        if (!cvFile && !APPLY.test(subject + ' ' + body)) {
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

      // اللِيبل ده بيتحط على كل محادثة اتفحصت — هو اللي بيخرّجها
      // من البحث. من غيره الدفعة الجاية بترجعها تاني والفرز بيقف.
      thread.addLabel(checked);
      if (matched) {
        thread.addLabel(label);
        if (ARCHIVE) { thread.moveToArchive(); }
      }
    });
  }

  console.log(moved + ' طلب جديد · ' + skipped + ' مش طلب · ' +
              scanned + ' محادثة اتفحصت · ' +
              Math.round((Date.now() - started) / 1000) + 'ث');
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

/**
 * شيل لِيبل Checked من اللي اتلبّس وهو مش طلب.
 *
 * أول نسخة كانت بتفحص الصندوق كله، فـ247 محادثة — إشعارات
 * وفواتير — خدت اللِيبل. دي بتشيله من أي محادثة مالهاش لِيبل
 * Applications، فالنطاق الجديد يبدأ نضيف.
 *
 * شغّلها **مرة واحدة** بعد ما تحدّث السكريبت.
 */
function cleanupChecked() {
  const started = Date.now();
  const checked = GmailApp.getUserLabelByName(CHECKED);
  if (!checked) {
    console.log('مفيش لِيبل Checked أصلاً.');
    return;
  }

  let removed = 0;
  while (Date.now() - started < TIME_BUDGET_MS) {
    const threads = GmailApp.search(
      'label:"' + CHECKED + '" -label:"' + LABEL + '"', 0, 100);
    if (!threads.length) { break; }
    checked.removeFromThreads(threads);
    removed += threads.length;
  }
  console.log('اتشال اللِيبل من ' + removed + ' محادثة.');
}


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


// ═══ الفرز ═══

const LOG_SHEET = 'Applications Log';
const JUNK_SHEET = 'Not applications';
const SHORT_SHEET = 'Shortlist';
const REVIEW_SHEET = 'Review';
const OUT_SHEET = 'Filtered out';


// ── الإشارات ────────────────────────────────────────────────────────────

// دليل إنه في مصر: جامعة أو معهد أو مدينة أو رقم أو نطاق إيميل
const EGYPT = new RegExp(
  '\\begypt\\b|\\bcairo\\b|\\bgiza\\b|alexandria|mansoura|zagazig|tanta|' +
  'benha|helwan|ain\\s*shams|assiut|asyut|minia|fayoum|suez|port\\s*said|' +
  'ismailia|damietta|beni\\s*suef|sohag|qena|aswan|luxor|menoufia|minufiya|' +
  'sharkia|dakahlia|gharbia|kafr\\s*el|6th\\s*of\\s*october|nasr\\s*city|' +
  'maadi|obour|shorouk|new\\s*cairo|rehab|madinaty|zaqaziq|' +
  '\\biti\\b|\\bdepi\\b|digital\\s*egypt|ejust|\\bmiu\\b|\\bguc\\b|\\bauc\\b|' +
  '\\bmsa\\b|\\bmti\\b|nile\\s*university|modern\\s*academy|' +
  'higher\\s*technological|culture\\s*and\\s*science|akhbar|sadat\\s*academy|' +
  '\\.eg\\b|\\+20\\s*1|\\b01[0125]\\d{8}\\b|' +
  'مصر|القاهرة|الجيزة|الإسكندرية|المنصورة|الزقازيق|بنها|حلوان|عين\\s*شمس',
  'i');

// دليل إنه برّه — الاسم مش دليل، دي أماكن ومؤسسات مذكورة بالنص
const OUTSIDE = [
  ['السعودية', /saudi|riyadh|jeddah|dammam|hafr\s*al\s*batin|\bhail\b|taif|imam\s*mohammad|king\s*saud|kfupm|king\s*fahad|\bksa\b|السعودية|الرياض|جدة/i],
  ['المغرب', /morocco|casablanca|rabat|marrakech|insea|centrale-casa|\.ma\b|المغرب|الدار\s*البيضاء/i],
  ['الهند', /\bindia\b|pune|mumbai|bangalore|bengaluru|hyderabad|chennai|\bdelhi\b|\bvit\b|\biit\b|\.in\b/i],
  ['باكستان', /pakistan|lahore|karachi|islamabad|punjab|mianwali|\bnust\b|\bfast\b/i],
  ['الأردن', /jordan|amman|الأردن|عمّان/i],
  ['الإمارات', /\buae\b|dubai|abu\s*dhabi|sharjah|الإمارات|دبي/i],
  ['سوريا', /syria|damascus|aleppo|سوريا|دمشق/i],
  ['اليمن', /yemen|sana'?a|اليمن/i],
  ['تونس', /tunisia|tunis|تونس/i],
  ['الجزائر', /algeria|algiers|الجزائر/i],
  ['نيجيريا', /nigeria|lagos|abuja/i],
  ['بنجلاديش', /bangladesh|dhaka|kushtia|khulna/i],
];

const SQL_RX = /\bsql\b|mysql|postgres\w*|sql\s*server|t-sql|pl\/?sql|\bssis\b|bigquery|oracle\s*db|قواعد\s*بيانات/i;
const PY_RX = /\bpython\b|\bpandas\b|numpy|django|flask|fastapi|scrapy|selenium|beautiful\s?soup|\bbs4\b|playwright|بايثون/i;

// أداة scraping بالاسم = أقوى دليل
const TOOLS = /playwright|selenium|scrapy|beautiful\s?soup|\bbs4\b|puppeteer|crawler|crawling|httpx/gi;
const SCRAPE = /scrap\w*|web\s*harvest|data\s*extraction/i;
const ADMITS = /have\s+not\s+(?:yet\s+)?(?:completed|done|built)|no\s+(?:dedicated\s+)?scraping|rather\s+than\s+web\s*scraping|interested\s+in\s+developing\s+my\s+scraping|eager\s+to\s+(?:further\s+)?develop\s+my\s+(?:web\s*)?scraping/i;

// رسالة مش طلب — إشعار أو فاتورة
const AUTOMATED = /noreply|no-reply|notification|billing|receipt|invoice|support@|@(anthropic|openai|supabase|render|linkedin|google|github|stripe|vercel)\./i;


// ── تنضيف السجل ─────────────────────────────────────────────────────────

/**
 * انقل الصفوف اللي مش طلبات لشيت لوحده.
 *
 * **نقل مش مسح** عن قصد: الفلترة ممكن تغلط، والصف اللي اتمسح
 * مايرجعش. لو لقيت حاجة في "Not applications" هي طلب فعلاً،
 * ارجّعها بإيدك.
 */
function cleanLog() {
  const ss = logBook_();
  const log = ss.getSheetByName(LOG_SHEET) || ss.getSheets()[0];
  const rows = log.getDataRange().getValues();
  const head = rows[0];

  const keep = [], junk = [];
  for (let i = 1; i < rows.length; i++) {
    const r = rows[i];
    const email = String(r[2] || '');
    const text = String(r[3] || '') + ' ' + String(r[4] || '');
    const files = String(r[5] || '');

    const isJunk = AUTOMATED.test(email) ||
      (!CV_NAME.test(files) && !APPLY.test(text));
    (isJunk ? junk : keep).push(r);
  }

  if (junk.length) {
    let sheet = ss.getSheetByName(JUNK_SHEET);
    if (!sheet) {
      sheet = ss.insertSheet(JUNK_SHEET);
      sheet.appendRow(head);
      styleHead_(sheet, head.length);
    }
    sheet.getRange(sheet.getLastRow() + 1, 1, junk.length, junk[0].length)
      .setValues(junk);
  }

  log.getRange(2, 1, rows.length - 1, head.length).clearContent();
  if (keep.length) {
    log.getRange(2, 1, keep.length, keep[0].length).setValues(keep);
  }
  console.log('السجل: ' + keep.length + ' طلب · اتنقل ' + junk.length +
              ' مش طلبات');
}


// ── الفرز ───────────────────────────────────────────────────────────────

function buildShortlist() {
  const ss = logBook_();
  const log = ss.getSheetByName(LOG_SHEET) || ss.getSheets()[0];
  const rows = log.getDataRange().getValues();

  const short = [], review = [], out = [];

  for (let i = 1; i < rows.length; i++) {
    const r = rows[i];
    const name = r[1], email = String(r[2] || ''), subject = r[3];
    const msg = String(r[4] || '');
    const files = String(r[5] || '');
    const link = r[6] || '';
    if (!email) { continue; }

    const text = name + ' ' + email + ' ' + subject + ' ' + msg + ' ' + files;

    // ١) المكان
    let place = '';
    for (let j = 0; j < OUTSIDE.length; j++) {
      if (OUTSIDE[j][1].test(text)) { place = OUTSIDE[j][0]; break; }
    }
    const inEgypt = EGYPT.test(text);
    if (place && !inEgypt) {
      out.push([name, email, place, subject, msg.slice(0, 200), link]);
      continue;
    }

    // ٢) المهارتين
    const hasSql = SQL_RX.test(text);
    const hasPy = PY_RX.test(text);

    // ٣) دليل الـscraping
    const tools = uniq_(msg.match(TOOLS) || []);
    const admits = ADMITS.test(msg);
    const scrape = SCRAPE.test(msg);

    let score = 0;
    if (tools.length) { score += 4 + Math.min(tools.length - 1, 2); }
    else if (scrape && !admits) { score += 2; }
    if (admits) { score -= 1; }
    if (hasSql) { score += 2; }
    if (hasPy) { score += 2; }
    if (inEgypt) { score += 1; }
    if (link) { score += 1; }
    if (!msg.trim()) { score -= 2; }

    const row = [
      score, name, email,
      inEgypt ? 'مصر' : 'غير مذكور',
      hasSql ? 'SQL' : '', hasPy ? 'Python' : '',
      tools.join(', '),
      admits ? 'قال إنه ماعملهاش' : (scrape ? 'ذكرها' : ''),
      link ? 'نعم' : 'لا', link,
      msg.replace(/\s+/g, ' ').slice(0, 300),
      ''
    ];

    // المهارة مش مذكورة في الإيميل ≠ مش موجودة: الرسالة 500 حرف
    // والـCV ممكن يكون فيها. دول بيتراجعوا مش بيتشالوا.
    (inEgypt && hasSql && hasPy ? short : review).push(row);
  }

  short.sort(byScore_);
  review.sort(byScore_);
  const shortU = dedupe_(short), reviewU = dedupe_(review);

  write_(ss, SHORT_SHEET,
    ['Score', 'Name', 'Email', 'Place', 'SQL', 'Python', 'Tools',
     'Scraping', 'CV?', 'CV link', 'Message', 'Decision'], shortU);
  write_(ss, REVIEW_SHEET,
    ['Score', 'Name', 'Email', 'Place', 'SQL', 'Python', 'Tools',
     'Scraping', 'CV?', 'CV link', 'Message', 'Decision'], reviewU);
  write_(ss, OUT_SHEET,
    ['Name', 'Email', 'Place', 'Subject', 'Message', 'CV link'], out);

  const withTools = shortU.filter(function (x) { return x[6]; }).length;
  console.log('Shortlist ' + shortU.length + ' (منهم ' + withTools +
              ' ذكروا أداة scraping) · Review ' + review.length +
              ' · برّه مصر ' + out.length);
}


// ── مساعدات ─────────────────────────────────────────────────────────────

/**
 * افتح دفتر الشيت بالاسم.
 *
 * `getActiveSpreadsheet()` بيشتغل بس لو السكريبت متربط بالشيت.
 * ده مشروع مستقل، فبيرجّع null والفرز بيقع على أول سطر.
 */
function logBook_() {
  const root = getFolder_(FOLDER);
  const it = root.getFilesByName(SHEET_NAME);
  if (!it.hasNext()) {
    throw new Error('مالقيتش شيت "' + SHEET_NAME + '" في فولدر ' + FOLDER);
  }
  return SpreadsheetApp.open(it.next());
}


function byScore_(a, b) { return b[0] - a[0]; }

function write_(ss, name, head, rows) {
  let sheet = ss.getSheetByName(name);
  if (sheet) { ss.deleteSheet(sheet); }
  sheet = ss.insertSheet(name);
  sheet.appendRow(head);
  styleHead_(sheet, head.length);
  if (rows.length) {
    sheet.getRange(2, 1, rows.length, rows[0].length).setValues(rows);
  }
  sheet.autoResizeColumns(1, Math.min(head.length, 10));
  const msgCol = head.indexOf('Message') + 1;
  if (msgCol) { sheet.setColumnWidth(msgCol, 420); }
  return sheet;
}

function styleHead_(sheet, n) {
  sheet.getRange(1, 1, 1, n).setFontWeight('bold')
    .setBackground('#1F3A5F').setFontColor('#FFFFFF');
  sheet.setFrozenRows(1);
}

function uniq_(arr) {
  const seen = {}, out = [];
  arr.forEach(function (x) {
    const k = String(x).toLowerCase();
    if (!seen[k]) { seen[k] = true; out.push(x); }
  });
  return out;
}


/** نفس الشخص بيبعت مرتين — بنسيب الأعلى درجة. */
function dedupe_(rows) {
  const best = {}, order = [];
  rows.forEach(function (r) {
    const k = String(r[2] || "").toLowerCase();
    if (!best[k]) { best[k] = r; order.push(k); }
    else if (r[0] > best[k][0]) { best[k] = r; }
  });
  return order.map(function (k) { return best[k]; });
}


/**
 * اكتب القايمة القصيرة كملف نصي في Drive.
 *
 * الشيت بيتقرا كعيّنة من برّه مهما كان حجمه — سبع صفوف وبس.
 * الملف النصي بيتقرا كامل، فالمراجعة بتشوف الليستة كلها.
 */
function exportShortlist() {
  const ss = logBook_();
  const root = getFolder_(FOLDER);
  [SHORT_SHEET, REVIEW_SHEET].forEach(function (which) {
    const sh = ss.getSheetByName(which);
    if (!sh) { return; }
    const rows = sh.getDataRange().getValues();
    const lines = [];
    for (let i = 1; i < rows.length; i++) {
      const r = rows[i];
      lines.push(r[0] + " | " + r[1] + " | " + r[2] + " | " + r[3] +
        " | " + r[4] + " " + r[5] + " | " + (r[6] || "-") + " | " + r[7] +
        " | " + (r[9] || "-") + " | " + String(r[10] || "").slice(0, 260));
    }
    const name = which + ".txt";
    const old = root.getFilesByName(name);
    while (old.hasNext()) { old.next().setTrashed(true); }
    root.createFile(name, lines.join("\n"), MimeType.PLAIN_TEXT);
    console.log(name + ": " + lines.length + " سطر");
  });
}
