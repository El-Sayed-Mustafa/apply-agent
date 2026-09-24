/**
 * فرز الطلبات — بيتحط في نفس مشروع Apps Script.
 *
 * بيقرا شيت "Applications Log" وبيطلّع شيت "Shortlist" فيه
 * المرشّحين مرتّبين، وكل واحد جنبه **الدليل** اللي اداله الدرجة.
 *
 * ليه الفرز هنا مش عندنا:
 *
 * 143 طلب × 500 حرف رسالة = كتير على القراءة الكاملة. الفرز الرخيص
 * بيحصل جنب الداتا، والمراجعة البشرية بتحصل على العشرين الأوائل بس.
 *
 * شغّل buildShortlist مرة، وكل ما طلبات جديدة توصل شغّلها تاني.
 */

const LOG_SHEET = 'Applications Log';
const SHORT_SHEET = 'Shortlist';

// أداة scraping بالاسم = الدليل الأقوى. حد بيقول "Playwright" غالبًا
// فتحها بإيده؛ حد بيقول "data collection" ممكن يقصد تحميل ملف CSV.
const TOOLS = /playwright|selenium|scrapy|beautiful\s?soup|\bbs4\b|puppeteer|crawler|crawling|requests\s*\+|httpx/gi;

// ذكر الـscraping من غير أداة — أضعف، بس لسه إشارة
const SCRAPE = /scrap\w*|web\s*harvest|data\s*extraction/i;

// بيقول بصراحة إنه ماعملش scraping. دي مش نقطة سلبية على طول —
// الصراحة نفسها إشارة كويسة، بس الدور محتاج المهارة.
const ADMITS = /have\s+not\s+(?:yet\s+)?(?:completed|done|built)|no\s+(?:dedicated\s+)?scraping|rather\s+than\s+web\s*scraping|interested\s+in\s+developing\s+my\s+scraping|eager\s+to\s+(?:further\s+)?develop\s+my\s+(?:web\s*)?scraping/i;

const SQL_RX = /\bsql\b|postgres|mysql|bigquery|sql\s*server|t-sql|ssis/i;
const GRAD_RX = /\b(202[3-8])\b/g;


function buildShortlist() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const log = ss.getSheetByName(LOG_SHEET) || ss.getSheets()[0];
  const rows = log.getDataRange().getValues();
  const out = [];

  for (let i = 1; i < rows.length; i++) {
    const r = rows[i];
    const name = r[1], email = r[2], subject = r[3];
    const msg = String(r[4] || '');
    const files = String(r[5] || '');
    const link = r[6];
    if (!email) { continue; }

    const tools = uniq_(msg.match(TOOLS) || []);
    const hasScrape = SCRAPE.test(msg);
    const admits = ADMITS.test(msg);
    const hasSql = SQL_RX.test(msg);
    const years = uniq_(msg.match(GRAD_RX) || []);

    // الدرجة بتقيس **الدليل**، مش الحماس. أداة بالاسم أقوى من
    // كلمة "scraping"، وكلمة "scraping" أقوى من رسالة فاضية.
    let score = 0;
    if (tools.length) { score += 4 + Math.min(tools.length - 1, 2); }
    else if (hasScrape && !admits) { score += 2; }
    if (admits) { score -= 1; }
    if (hasSql) { score += 2; }
    if (files) { score += 1; }
    if (!msg.trim()) { score -= 2; }     // بعت CV من غير كلمة

    out.push([
      score,
      name, email,
      tools.join(', '),
      admits ? 'قال إنه ماعملهاش' : (hasScrape ? 'ذكرها' : ''),
      hasSql ? 'SQL' : '',
      years.join(', '),
      files ? 'نعم' : 'لا',
      link || '',
      msg.replace(/\s+/g, ' ').slice(0, 300),
      subject,
      ''                                  // Decision — تملاه انت
    ]);
  }

  out.sort(function (a, b) { return b[0] - a[0]; });

  let sheet = ss.getSheetByName(SHORT_SHEET);
  if (sheet) { ss.deleteSheet(sheet); }
  sheet = ss.insertSheet(SHORT_SHEET);
  sheet.appendRow(['Score', 'Name', 'Email', 'Tools named', 'Scraping',
                   'SQL', 'Years', 'CV?', 'CV link', 'Message', 'Subject',
                   'Decision']);
  sheet.getRange('A1:L1').setFontWeight('bold').setBackground('#1F3A5F')
    .setFontColor('#FFFFFF');
  sheet.setFrozenRows(1);
  if (out.length) {
    sheet.getRange(2, 1, out.length, out[0].length).setValues(out);
  }
  sheet.setColumnWidth(10, 420);
  sheet.autoResizeColumns(1, 9);

  const withTools = out.filter(function (r) { return r[3]; }).length;
  console.log(out.length + ' طلب · ' + withTools + ' ذكروا أداة scraping بالاسم');
}

function uniq_(arr) {
  const seen = {}, out = [];
  arr.forEach(function (x) {
    const k = String(x).toLowerCase();
    if (!seen[k]) { seen[k] = true; out.push(x); }
  });
  return out;
}
