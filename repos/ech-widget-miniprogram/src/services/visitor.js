/**
 * Visitor registration & caching service
 * API: POST /v1/visitors/register
 */
var adapter = require('../adapters/request')
var storage = require('../adapters/storage')

function _cacheKey(apiBase, platformApiKey) {
  return 'tgo:visitor:' + apiBase + ':' + platformApiKey
}

function loadCachedVisitor(apiBase, platformApiKey) {
  return storage.getJSON(_cacheKey(apiBase, platformApiKey))
}

function saveCachedVisitor(apiBase, platformApiKey, v, expiresAtMs) {
  var cached = {
    apiBase: apiBase,
    platform_api_key: platformApiKey,
    visitor_id: v.id,
    platform_open_id: v.platform_open_id,
    channel_id: v.channel_id,
    channel_type: v.channel_type,
    im_token: v.im_token,
    project_id: v.project_id,
    platform_id: v.platform_id,
    created_at: v.created_at,
    updated_at: v.updated_at,
    expires_at: expiresAtMs
  }
  storage.setJSON(_cacheKey(apiBase, platformApiKey), cached)
}

function registerVisitor(params) {
  var apiBase = (params.apiBase || '').replace(/\/$/, '')
  var platformApiKey = params.platformApiKey || ''
  var extra = params.extra || {}
  var url = apiBase + '/v1/visitors/register'

  var body = Object.assign({ platform_api_key: platformApiKey }, extra)

  return adapter.request({
    url: url,
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body,
    timeout: 10000
  }).then(function (res) {
    if (!res.ok) {
      return res.text().then(function (text) {
        throw new Error('[Visitor] register failed: ' + res.status + ' ' + text)
      })
    }
    return res.json().then(function (data) {
      if (!data || !data.id || !data.channel_id) {
        throw new Error('[Visitor] invalid register response: missing id/channel_id')
      }
      return data
    })
  })
}

module.exports = {
  loadCachedVisitor: loadCachedVisitor,
  saveCachedVisitor: saveCachedVisitor,
  registerVisitor: registerVisitor
}
