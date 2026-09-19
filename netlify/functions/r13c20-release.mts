const META = {
  endpoint: 'https://listingtool-user-center.3117445725.workers.dev',
  patchUrl: 'https://raw.githubusercontent.com/3117445725-hash/image-text-cleaner-web/listingtool-release-relay/listingtool_r13c20.ltpatch',
  timestamp: '1789802324',
  nonce: 'z6W8kAnxIdUPZ-MD6Ra_2goYzWsshIjm',
  keyId: 'ltrel-20260918-primary-v1',
  signature: 'ubwyD5C1WDJC9H4Z5CmeUH-EZq-24oVPCdClUaEI_6FY07Filhhfxt5vLrppBR-ekCuM1qkZvH89QCdsBDwEDA',
  notesSha256: '4c08d4eb16b6d6c8e74680b2ccefbd0a0f029bf1e673bdf88c3acdcc8c7887bf',
  patchVersion: 'FIX36R13C20-FColumn-Legacy-Matcher-SafeVocabulary-Cumulative-v1',
  appVersion: 'V1.1.6 RC18 FIX36R13C20 F-Column Legacy Matcher Safe Vocabulary Stable',
  sha256: '643c7543774f0ab97c29951e9628c9ba32905563a20242f8b3c616f6068ce21a',
  fileSize: 217466,
  notes: 'R13C20 cumulative patch. Restores the exact historical V3.x F-column keyword matcher and removes R13C19 generated title n-gram categories. E remains fixed 品类. F is determined only from title keyword dictionaries: B optimized title first, A original title only if B has no keyword hit; within one dictionary pass, keywords are matched with historical boundary rules and longest configured keyword wins; the mapped standard category value is returned. Product Type/Item Type/Type, cost-table category, SoldEazy task category and source filename are never F sources. To keep older users compatible with newly supported product families without allowing new system aliases to steal the user taxonomy, shipped aliases map to stable standard categories (for example all spoiler/wing/trunk/roof spoiler variants map to Spoiler rather than becoming dozens of F values). If the user has overridden a base system alias such as spoiler, that user label is propagated to the same system canonical family unless the user explicitly maps a more specific alias. Exact user aliases always overwrite identical system aliases. Final template regeneration recomputes F from current A/B titles and the effective keyword dictionary, so an old task cache cannot preserve bad F. Images/OCR, gallery/detail rules, QA, reference persistence, SoldEazy, layout, fixed R10 EXE and online-update modules remain unchanged.'
};

async function sha256Hex(bytes) {
  const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', bytes));
  return Array.from(digest, b => b.toString(16).padStart(2, '0')).join('');
}

async function submitResult(result) {
  const body = new URLSearchParams({
    'form-name': 'listingtool-release-result',
    state: String(result.state || ''),
    patch_version: META.patchVersion,
    sha256: META.sha256,
    file_size: String(META.fileSize),
    verified_online: String(Boolean(result.verifiedOnline)),
    error: String(result.error || ''),
    run_at: new Date().toISOString()
  });
  await fetch('https://venerable-bunny-dd3634.netlify.app/r13c20-release-result.html', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body
  });
}

async function verifyOnline() {
  const versionResponse = await fetch(META.endpoint + '/api/v1/code-update/version', { headers: { 'User-Agent': 'ListingTool-Netlify-R13C20/1.0' } });
  if (!versionResponse.ok) throw new Error('version readback HTTP ' + versionResponse.status);
  const version = await versionResponse.json();
  if (String(version.patch_version || '') !== META.patchVersion) throw new Error('online patch_version mismatch: ' + String(version.patch_version || ''));
  if (String(version.sha256 || '').toLowerCase() !== META.sha256) throw new Error('online sha mismatch: ' + String(version.sha256 || ''));
  if (Number(version.file_size) !== META.fileSize) throw new Error('online size mismatch: ' + String(version.file_size || ''));
  const downloadUrl = String(version.download_url || '');
  if (!downloadUrl) throw new Error('online download_url missing');
  const response = await fetch(downloadUrl, { headers: { 'User-Agent': 'ListingTool-Netlify-R13C20/1.0' } });
  if (!response.ok) throw new Error('online download HTTP ' + response.status);
  const bytes = new Uint8Array(await response.arrayBuffer());
  const sha = await sha256Hex(bytes);
  if (bytes.length !== META.fileSize || sha !== META.sha256) throw new Error('online bytes mismatch size=' + bytes.length + ' sha=' + sha);
  return { version, bytes };
}

export default async () => {
  let result = { state: 'started', verifiedOnline: false, error: '' };
  try {
    try {
      await verifyOnline();
      result = { state: 'already-published', verifiedOnline: true, error: '' };
      console.log('R13C20 already published and verified');
      await submitResult(result);
      return;
    } catch (currentError) {
      console.log('R13C20 not online yet:', String(currentError));
    }

    const patchResponse = await fetch(META.patchUrl, { headers: { 'User-Agent': 'ListingTool-Netlify-R13C20/1.0' } });
    if (!patchResponse.ok) throw new Error('patch fetch HTTP ' + patchResponse.status);
    const patch = new Uint8Array(await patchResponse.arrayBuffer());
    const patchSha = await sha256Hex(patch);
    if (patch.length !== META.fileSize || patchSha !== META.sha256) throw new Error('staged patch mismatch size=' + patch.length + ' sha=' + patchSha);

    const query = new URLSearchParams({ patch_version: META.patchVersion, app_version: META.appVersion, notes: META.notes });
    const publishResponse = await fetch(META.endpoint + '/api/v1/signed/code-update/publish?' + query.toString(), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/zip',
        'X-ListingTool-Key-Id': META.keyId,
        'X-ListingTool-Timestamp': META.timestamp,
        'X-ListingTool-Nonce': META.nonce,
        'X-ListingTool-Sha256': META.sha256,
        'X-ListingTool-Size': String(META.fileSize),
        'X-ListingTool-Notes-Sha256': META.notesSha256,
        'X-ListingTool-Signature': META.signature,
        'User-Agent': 'ListingTool-Netlify-R13C20/1.0'
      },
      body: patch
    });
    const publishText = await publishResponse.text();
    if (!publishResponse.ok) throw new Error('publish HTTP ' + publishResponse.status + ': ' + publishText);
    const published = JSON.parse(publishText);
    if (String(published.patch_version || '') !== META.patchVersion || String(published.sha256 || '').toLowerCase() !== META.sha256) throw new Error('publish response metadata mismatch');

    await verifyOnline();
    result = { state: 'published', verifiedOnline: true, error: '' };
    console.log('R13C20_RELEASE_VERIFIED_OK', JSON.stringify(result));
  } catch (error) {
    result = { state: 'failed', verifiedOnline: false, error: String(error && error.message ? error.message : error) };
    console.error('R13C20_RELEASE_FAILED', result.error);
  }
  try { await submitResult(result); } catch (error) { console.error('R13C20_RESULT_SUBMIT_FAILED', error); }
};

export const config = { schedule: '* * * * *' };
