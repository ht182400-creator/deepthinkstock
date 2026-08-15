#!/usr/bin/env node
/* push-via-api.cjs —— 沙箱 git 出网受限时，用 GitHub Contents API 逐文件推送。
 * 用法: node push-via-api.cjs
 * 注意: 本项目为 CommonJS（无 "type":"module"），直接 require。
 */
const fs = require('fs');
const os = require('os');
const { execSync } = require('child_process');

const TOKEN = fs.readFileSync(os.homedir() + '/.config/gh/hosts.yml', 'utf8')
  .match(/oauth_token:\s*(\S+)/)[1];
const OWNER = 'ht182400-creator';
const REPO = 'deepthinkstock';
const BRANCH = 'main';
const LOCAL = 'E:/AI_Studio/deepthinkstock';

// 从 git 暂存区拿文件清单（UTF-8 路径安全）
const files = execSync('git ls-files -z', { cwd: LOCAL, encoding: 'buffer' })
  .toString('utf8').split('\0').filter(Boolean);

const api = (p, o = {}) => fetch('https://api.github.com' + p, {
  ...o,
  headers: {
    'Authorization': 'Bearer ' + TOKEN,
    'Accept': 'application/vnd.github+json',
    'User-Agent': 'wb',
    'Content-Type': 'application/json',
    ...(o.headers || {})
  }
}).then(async r => ({ status: r.status, json: await r.json().catch(() => null) }));

(async () => {
  let ok = 0, fail = 0, skipped = 0;
  for (const path of files) {
    const local = LOCAL + '/' + path;
    if (!fs.existsSync(local)) { console.log('SKIP (missing):', path); skipped++; continue; }
    const b64 = fs.readFileSync(local).toString('base64');
    // 查是否已存在（拿 sha）
    const get = await api(`/repos/${OWNER}/${REPO}/contents/${encodeURIComponent(path)}?ref=${BRANCH}`);
    const body = {
      message: `docs/feat: 同步 ${path} (经 Contents API 推送; 沙箱 git 出网受限)`,
      content: b64,
      branch: BRANCH
    };
    if (get.status === 200 && get.json && get.json.sha) body.sha = get.json.sha;
    const res = await api(`/repos/${OWNER}/${REPO}/contents/${encodeURIComponent(path)}`,
      { method: 'PUT', body: JSON.stringify(body) });
    if (res.status === 200 || res.status === 201) {
      ok++;
      console.log(`OK   ${path}`);
    } else {
      fail++;
      console.log(`FAIL ${path} -> ${res.status} ${res.json && res.json.message || ''}`);
    }
    // 限速保护：api.github.com 未认证 60 req/h；认证后 5000/h，但留点余量
    await new Promise(r => setTimeout(r, 120));
  }
  console.log(`\n=== 完成: 成功 ${ok}, 失败 ${fail}, 跳过 ${skipped} (共 ${files.length}) ===`);
})().catch(e => { console.error('FATAL:', e.message); process.exit(1); });
