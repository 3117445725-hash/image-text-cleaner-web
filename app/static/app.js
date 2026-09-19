const $ = (id) => document.getElementById(id);
let currentJob = sessionStorage.getItem('currentJobId') || null;
let pollTimer = null;
let config = { password_required: false, max_upload_mb: 50 };

async function apiFetch(url, options = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 30000);
  try {
    const headers = { ...(options.headers || {}), ...passwordHeader() };
    return await fetch(url, { ...options, headers, signal: controller.signal });
  } finally {
    clearTimeout(timeout);
  }
}

async function loadConfig() {
  const res = await fetch('/api/config', { cache: 'no-store' });
  if (!res.ok) throw new Error('配置接口不可用');
  config = await res.json();
  $('brandTitle').textContent = config.title;
  $('fileHint').textContent = `支持 .xlsx / .xlsm，最大 ${config.max_upload_mb}MB`;
  if (config.password_required) $('passwordField').classList.remove('hidden');
  if (currentJob) resumeJob();
}

const dropzone = $('dropzone');
['dragenter', 'dragover'].forEach(type => dropzone.addEventListener(type, e => {
  e.preventDefault();
  dropzone.classList.add('drag');
}));
['dragleave', 'drop'].forEach(type => dropzone.addEventListener(type, e => {
  e.preventDefault();
  dropzone.classList.remove('drag');
}));
dropzone.addEventListener('drop', e => {
  if (e.dataTransfer.files.length) {
    const transfer = new DataTransfer();
    transfer.items.add(e.dataTransfer.files[0]);
    $('fileInput').files = transfer.files;
    updateFileName();
  }
});
$('fileInput').addEventListener('change', updateFileName);
function updateFileName() {
  const f = $('fileInput').files[0];
  $('fileLabel').textContent = f ? f.name : '点击选择或拖入 Excel 文件';
}

function passwordHeader() {
  return config.password_required ? { 'X-App-Password': $('password').value } : {};
}

$('jobForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  const file = $('fileInput').files[0];
  const keywords = $('keywords').value.trim();
  if (!file) return alert('请选择 Excel 文件');
  if (!keywords) return alert('请输入至少一个检测关键词');
  if (file.size > config.max_upload_mb * 1024 * 1024) return alert(`文件不能超过 ${config.max_upload_mb}MB`);
  if (config.password_required && !$('password').value) return alert('请输入网站访问密码');

  clearTimeout(pollTimer);
  $('submitButton').disabled = true;
  $('formPanel').classList.add('hidden');
  $('errorPanel').classList.add('hidden');
  $('resultPanel').classList.add('hidden');
  $('progressPanel').classList.remove('hidden');
  setProgress({ progress: 1, message: '正在上传文件', total_links: 0, processed_links: 0, matched_links: 0, failed_links: 0 });

  const data = new FormData();
  data.append('file', file);
  data.append('keywords_raw', keywords);
  data.append('match_mode', $('matchMode').value);
  data.append('case_sensitive', $('caseSensitive').checked);
  data.append('enhanced_ocr', $('enhancedOcr').checked);

  try {
    const response = await apiFetch('/api/jobs', { method: 'POST', body: data });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || '创建任务失败');
    currentJob = payload.job_id;
    sessionStorage.setItem('currentJobId', currentJob);
    pollJob();
  } catch (error) {
    showError(error.name === 'AbortError' ? '上传超时，请检查网络后重试' : error.message);
  }
});

function resumeJob() {
  $('formPanel').classList.add('hidden');
  $('resultPanel').classList.add('hidden');
  $('errorPanel').classList.add('hidden');
  $('progressPanel').classList.remove('hidden');
  setProgress({ progress: 1, message: '正在恢复上次任务状态' });
  pollJob();
}

async function pollJob() {
  if (!currentJob) return;
  try {
    const response = await apiFetch(`/api/jobs/${currentJob}`, { cache: 'no-store' });
    const job = await response.json();
    if (!response.ok) {
      if (response.status === 401 && config.password_required && !$('password').value) {
        reset(false);
        $('passwordField').classList.remove('hidden');
        return showError('页面刷新后请重新输入访问密码，再提交或恢复任务。');
      }
      throw new Error(job.detail || '读取任务失败');
    }
    setProgress(job);
    if (job.status === 'completed') return showResult(job);
    if (job.status === 'failed') return showError(job.error || '处理失败', false);
    pollTimer = setTimeout(pollJob, 1200);
  } catch (error) {
    const message = error.name === 'AbortError' ? '读取任务状态超时，正在重试…' : error.message;
    $('progressMessage').textContent = message;
    pollTimer = setTimeout(pollJob, 2500);
  }
}

function setProgress(job) {
  const progress = Math.max(0, Math.min(100, Number(job.progress) || 0));
  $('progressPercent').textContent = `${progress}%`;
  $('progressBar').style.width = `${progress}%`;
  $('progressTitle').textContent = job.message || '正在处理';
  $('progressMessage').textContent = job.message || '';
  $('totalLinks').textContent = job.total_links || 0;
  $('processedLinks').textContent = job.processed_links || 0;
  $('matchedLinks').textContent = job.matched_links || 0;
  $('failedLinks').textContent = job.failed_links || 0;
}

function showResult(job) {
  clearTimeout(pollTimer);
  $('progressPanel').classList.add('hidden');
  $('errorPanel').classList.add('hidden');
  $('resultPanel').classList.remove('hidden');
  $('resultSummary').textContent = `共检测 ${job.total_links} 个唯一图片链接，命中 ${job.matched_links} 个，修改 ${job.changed_cells} 个单元格，失败保留 ${job.failed_links} 个。`;
}

function showError(message, enableSubmit = true) {
  clearTimeout(pollTimer);
  $('progressPanel').classList.add('hidden');
  $('resultPanel').classList.add('hidden');
  $('errorPanel').classList.remove('hidden');
  $('errorMessage').textContent = message;
  if (enableSubmit) $('submitButton').disabled = false;
}

function reset(clearJob = true) {
  clearTimeout(pollTimer);
  if (clearJob) {
    currentJob = null;
    sessionStorage.removeItem('currentJobId');
  }
  $('formPanel').classList.remove('hidden');
  $('progressPanel').classList.add('hidden');
  $('resultPanel').classList.add('hidden');
  $('errorPanel').classList.add('hidden');
  $('submitButton').disabled = false;
}

async function downloadFile(kind) {
  if (!currentJob) return alert('当前没有可下载的任务');
  try {
    const response = await apiFetch(`/api/jobs/${currentJob}/download/${kind}`);
    if (!response.ok) {
      let detail = '下载失败';
      try {
        const payload = await response.json();
        detail = payload.detail || detail;
      } catch (_) {}
      throw new Error(detail);
    }
    const blob = await response.blob();
    const disposition = response.headers.get('content-disposition') || '';
    const utf8 = disposition.match(/filename\*=utf-8''([^;]+)/i);
    const plain = disposition.match(/filename=\"?([^\";]+)\"?/i);
    const name = utf8 ? decodeURIComponent(utf8[1]) : plain ? plain[1] : (kind === 'excel' ? '处理结果.xlsx' : 'OCR识别记录.csv');
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (error) {
    alert(error.name === 'AbortError' ? '下载超时，请重试' : error.message);
  }
}

$('downloadExcel').addEventListener('click', e => { e.preventDefault(); downloadFile('excel'); });
$('downloadLog').addEventListener('click', e => { e.preventDefault(); downloadFile('log'); });
$('newTask').addEventListener('click', () => reset(true));
$('retryButton').addEventListener('click', () => reset(true));

loadConfig().catch(err => showError(`无法读取网站配置：${err.message}`));
