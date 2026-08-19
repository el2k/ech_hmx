/**
 * miniprogram-ci verification script
 *
 * Usage:
 *   node ci.js pack-npm    # 验证 npm 构建 (不需要密钥)
 *   node ci.js compile     # 编译验证 (需要密钥, 不需要IP白名单)
 *   node ci.js preview     # 完整编译+预览 (需要密钥+IP白名单)
 *
 * 密钥获取: 微信公众平台 → 管理 → 开发管理 → 开发设置 → 小程序代码上传
 * 将下载的密钥文件放到项目目录，命名为 private.wx.key
 */
const ci = require('miniprogram-ci')
const path = require('path')
const fs = require('fs')

const PROJECT_DIR = __dirname
const PRIVATE_KEY_PATH = path.join(PROJECT_DIR, 'private.wx.key')

const projectConfig = JSON.parse(
  fs.readFileSync(path.join(PROJECT_DIR, 'project.config.json'), 'utf8')
)
const APPID = projectConfig.appid

async function packNpm() {
  console.log('[ci] 开始验证 npm 构建...')

  const result = await ci.packNpmManually({
    packageJsonPath: path.join(PROJECT_DIR, 'package.json'),
    miniprogramNpmDistDir: PROJECT_DIR,
  })

  console.log('[ci] npm 构建完成:', JSON.stringify(result, null, 2))

  if (result.warnList && result.warnList.length > 0) {
    console.warn('[ci] 警告:', result.warnList)
  }
  console.log(
    `[ci] 构建成功 - miniprogram: ${result.miniProgramPackNum}, other: ${result.otherNpmPackNum}`
  )
}

function createProject() {
  if (!fs.existsSync(PRIVATE_KEY_PATH)) {
    console.error(`[ci] 未找到密钥文件: ${PRIVATE_KEY_PATH}`)
    console.error('[ci] 请从微信公众平台下载代码上传密钥并命名为 private.wx.key')
    process.exit(1)
  }

  return new ci.Project({
    appid: APPID,
    type: 'miniProgram',
    projectPath: PROJECT_DIR,
    privateKeyPath: PRIVATE_KEY_PATH,
    ignores: ['node_modules/**/*', 'ci.js', 'private.wx.key', 'preview-qrcode.png'],
  })
}

async function compile() {
  console.log('[ci] 开始编译验证...')
  const project = createProject()

  const compiledResult = await ci.getCompiledResult({
    project,
    desc: 'compile check',
    setting: projectConfig.setting,
    onProgressUpdate: (info) => {
      if (info._msg) console.log(`[ci]   ${info._msg}`)
    },
  })

  const fileCount = Object.keys(compiledResult).length
  console.log(`[ci] 编译验证通过! 共 ${fileCount} 个文件`)
}

async function preview() {
  console.log('[ci] 开始完整编译验证 (preview)...')
  const project = createProject()

  const previewResult = await ci.preview({
    project,
    setting: projectConfig.setting,
    qrcodeFormat: 'terminal',
    qrcodeOutputDest: path.join(PROJECT_DIR, 'preview-qrcode.png'),
    pagePath: 'pages/index/index',
    onProgressUpdate: (info) => {
      if (info._msg) console.log(`[ci]   ${info._msg}`)
    },
  })

  console.log('[ci] 编译验证通过!', JSON.stringify(previewResult, null, 2))
}

async function main() {
  const cmd = process.argv[2]

  if (!cmd || cmd === 'pack-npm') {
    await packNpm()
  } else if (cmd === 'compile') {
    await packNpm()
    await compile()
  } else if (cmd === 'preview') {
    await packNpm()
    await preview()
  } else {
    console.error(`未知命令: ${cmd}`)
    console.error('用法: node ci.js [pack-npm|compile|preview]')
    process.exit(1)
  }
}

main().then(() => {
  process.exit(0)
}).catch((err) => {
  console.error('[ci] 失败:', err.message || err)
  process.exit(1)
})
