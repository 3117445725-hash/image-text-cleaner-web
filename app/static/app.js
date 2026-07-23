const $ = (id) => document.getElementById(id);
let currentJob = null;
let config = { password_required: false, max_upload_mb: 50 };

async function loadConfig() {
  const res = await fetch('/api/config');
  config = await res.json();
  $('brandTitle').textContent = config.title;
  $('fileHint').textContent = `支持 .xlsx / .xlsm，最大 ${config.max_upload_mb}MB`;
  if (config.password_required) $('passwordField').classList.remove('hidden');
}

const dropzone = $('dropzone');
['dragenter','dragover'].forEach(type => dropzone.addEventListener(type, e => { e.preventDefault(); dropzone.classList.add('drag'); }));
['dragleave','drop'].forEach(type => dropzone.addEventListener(type, e => { e.preventDefault(); dropzone.classList.remove('drag'); }));
dropzone.addEventListener('drop', e => { if (e.dataTransfer.files.length) { $('fileInput').files = e.dataTransfer.files; updateFileName(); }});
$('fileInput').addEventListener('change', updateFileName);
function updateFileName(){ const f=$('fileInput').files[0]; $('fileLabel').textContent=f?f.name:'点击选择或拖入 Excel 文件'; }

function passwordHeader(){ return config.password_required ? { 'X-App-Password': $('password').value } : {}; }

$('jobForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  const file = $('fileInput').files[0];
  if (!file) return alert('请选择 Excel 文件');
  if (file.size > config.max_upload_mb * 1024 * 1024) return alert(`文件不能超过 ${config.max_upload_mb}MB`);
  if (config.password_required && !$('password').value) return alert('请输入网站访问密码');

  $('submitButton').disabled = true;
  $('formPanel').classList.add('hidden');
  $('progressPanel').classList.remove('hidden');
  setProgress({progress:1,message:'正在上传文件',total_links:0,processed_links:0,matched_links:0,failed_links:0});

  const data = new FormData();
  data.append('file', file);
  data.append('keywords_raw', $('keywords').value);
  data.append('match_mode', $('matchMode').value);
  data.append('case_sensitive', $('caseSensitive').checked);
  data.append('enhanced_ocr', $('enhancedOcr').checked);

  try {
    const response = await fetch('/api/jobs', { method:'POST', headers: passwordHeader(), body:data });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || '创建任务失败');
    currentJob = payload.job_id;
    pollJob();
  } catch (error) { showError(error.message); }
});

async function pollJob(){
  if (!currentJob) return;
  try {
    const response = await fetch(`/api/jobs/${currentJob}`, { headers: passwordHeader() });
    const job = await response.json();
    if (!response.ok) throw new Error(job.detail || '读取任务失败');
    setProgress(job);
    if (job.status === 'completed') return showResult(job);
    if (job.status === 'failed') return showError(job.error || '处理失败');
    setTimeout(pollJob, 1000);
  } catch(error){ showError(error.message); }
}
function setProgress(job){
  $('progressPercent').textContent=`${job.progress || 0}%`;
  $('progressBar').style.width=`${job.progress || 0}%`;
  $('progressTitle').textContent=job.message || '正在处理';
  $('progressMessage').textContent=job.message || '';
  $('totalLinks').textContent=job.total_links || 0;
  $('processedLinks').textContent=job.processed_links || 0;
  $('matchedLinks').textContent=job.matched_links || 0;
  $('failedLinks').textContent=job.failed_links || 0;
}
function showResult(job){
  $('progressPanel').classList.add('hidden'); $('resultPanel').classList.remove('hidden');
  $('resultSummary').textContent=`共检测 ${job.total_links} 个唯一图片链接，命中 ${job.matched_links} 个，修改 ${job.changed_cells} 个单元格，失败保留 ${job.failed_links} 个。`;
  $('downloadExcel').href='#';
  $('downloadLog').href='#';
}
function showError(message){
  $('progressPanel').classList.add('hidden'); $('resultPanel').classList.add('hidden'); $('errorPanel').classList.remove('hidden');
  $('errorMessage').textContent=message; $('submitButton').disabled=false;
}
function reset(){
  currentJob=null; $('formPanel').classList.remove('hidden'); $('progressPanel').classList.add('hidden'); $('resultPanel').classList.add('hidden'); $('errorPanel').classList.add('hidden'); $('submitButton').disabled=false;
}
async function downloadFile(kind){
  try {
    const response = await fetch(`/api/jobs/${currentJob}/download/${kind}`, { headers: passwordHeader() });
    if (!response.ok) { const payload = await response.json(); throw new Error(payload.detail || '下载失败'); }
    const blob = await response.blob();
    const disposition = response.headers.get('content-disposition') || '';
    const utf8 = disposition.match(/filename\*=utf-8''([^;]+)/i);
    const plain = disposition.match(/filename=\"?([^\";]+)\"?/i);
    const name = utf8 ? decodeURIComponent(utf8[1]) : plain ? plain[1] : (kind === 'excel' ? '处理结果.xlsx' : 'OCR识别记录.csv');
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a'); a.href=url; a.download=name; document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch(error) { alert(error.message); }
}
$('downloadExcel').addEventListener('click', e => { e.preventDefault(); downloadFile('excel'); });
$('downloadLog').addEventListener('click', e => { e.preventDefault(); downloadFile('log'); });
$('newTask').addEventListener('click', reset); $('retryButton').addEventListener('click', reset);
loadConfig().catch(err => showError(`无法读取网站配置：${err.message}`));
