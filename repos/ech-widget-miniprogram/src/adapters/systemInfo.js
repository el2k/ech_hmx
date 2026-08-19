/**
 * wx system info adapter (replaces navigator.userAgent)
 */

function collectSystemInfo() {
  try {
    var info = wx.getSystemInfoSync()
    return {
      browser: 'WeChat MiniProgram',
      operating_system: (info.platform || '') + ' ' + (info.system || ''),
      source_detail: 'WeChat ' + (info.version || '') + ', SDK ' + (info.SDKVersion || '')
    }
  } catch (e) {
    return {
      browser: 'WeChat MiniProgram',
      operating_system: '',
      source_detail: ''
    }
  }
}

module.exports = { collectSystemInfo: collectSystemInfo }
