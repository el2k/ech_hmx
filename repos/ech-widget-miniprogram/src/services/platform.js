/**
 * Platform info service
 * API: GET /v1/platforms/info?platform_api_key=...
 */
var adapter = require('../adapters/request')

function fetchPlatformInfo(params) {
  var apiBase = (params.apiBase || '').replace(/\/$/, '')
  var platformApiKey = params.platformApiKey || ''
  var url = apiBase + '/v1/platforms/info?platform_api_key=' + encodeURIComponent(platformApiKey)

  return adapter.request({
    url: url,
    method: 'GET',
    headers: { 'X-Platform-API-Key': platformApiKey },
    timeout: 10000
  }).then(function (res) {
    if (!res.ok) {
      return res.text().then(function (text) {
        throw new Error('[Platform] info failed: ' + res.status + ' ' + text)
      })
    }
    return res.json()
  })
}

module.exports = { fetchPlatformInfo: fetchPlatformInfo }
