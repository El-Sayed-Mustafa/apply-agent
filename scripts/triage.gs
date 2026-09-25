/**
 * فرز الطلبات — بيتحط في نفس مشروع Apps Script.
 *
 *   cleanLog()        → ينقل الصفوف اللي مش طلبات لشيت لوحده
 *   buildShortlist()  → يفلتر ويرتّب اللي فاضل
 *
 * الفرز بيحصل جنب الداتا: 200 طلب × 500 حرف رسالة كتير على
 * القراءة الكاملة، والمراجعة البشرية بتحصل على الأوائل بس.
 *
 * **الفلترة على الدليل، مش على الاسم.**
 *
 * مفيش طريقة نعرف بيها جنسية حد من اسمه، والمحاولة غلط أصلاً.
 * اللي بنقيسه هو **دليل إنه في مصر**: جامعة مصرية، إيميل .eg،
 * رقم مصري، أو ذكر مدينة. اللي مفيش عنده دليل بيروح شيت
 * "Review" — مش بيتشال.
 */

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
const CV_NAME = /\b(cv|resume|r[ée]sum[ée]|سيرة|ذاتية)\b/i;
const APPLY = /scrap|scarp|data\s*analyst|python\s*develop|data\s*engineer|apply|application|resume|\bcv\b|hiring|position|join\s+(the|our|your)\s+team|graduat|intern|وظيف|تقديم|السيرة|مهندس|خريج/i;


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
