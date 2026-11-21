// على صفحات نتايج البحث في مواقع التوظيف: استنى الصفحة تخلص تحميل، اقرا
// الكروت، وابعتها للمساعد. صفحة وظيفة واحدة (مش نتايج) بتتساب — أقل من
// 3 وظايف يعني مش صفحة نتايج.
(function () {
  let sent = "";
  async function scan() {
    const r = window.ApplyAgentSiteJobs.extract(document, location);
    if (!r || (r.jobs.length < 3 && !r.blocked)) return;
    const key = r.page + "|" + r.jobs.length + "|" + (r.jobs[0] ? r.jobs[0].url : "");
    if (key === sent) return;              // نفس النتايج — مانبعتش تاني
    sent = key;
    try {
      chrome.runtime.sendMessage({ kind: "sitejobs", payload: r }, () => void chrome.runtime.lastError);
    } catch (e) { /* الإضافة اتحدّثت — refresh */ }
  }
  // التحميل بياخد ثواني، وبعض المواقع بتكمّل الكروت بعد التمرير
  setTimeout(scan, 5000);
  setTimeout(scan, 12000);
  setTimeout(scan, 25000);            // مواقع بطيئة (GulfTalent في شباك اللفة)
})();
