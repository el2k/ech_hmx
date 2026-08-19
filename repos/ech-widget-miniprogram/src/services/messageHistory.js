/**
 * Message history sync service
 * API: POST /v1/visitors/messages/sync
 */
var adapter = require('../adapters/request')

function syncVisitorMessages(params) {
  var apiBase = (params.apiBase || '').replace(/\/$/, '')
  var platformApiKey = params.platformApiKey || ''
  var url = apiBase + '/v1/visitors/messages/sync'

  var body = {
    platform_api_key: platformApiKey,
    channel_id: params.channelId,
    channel_type: params.channelType,
    start_message_seq: params.startSeq != null ? params.startSeq : null,
    end_message_seq: params.endSeq != null ? params.endSeq : null,
    limit: params.limit != null ? params.limit : null,
    pull_mode: params.pullMode != null ? params.pullMode : null
  }

  return adapter.request({
    url: url,
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Platform-API-Key': platformApiKey
    },
    body: body,
    timeout: 10000
  }).then(function (res) {
    if (!res.ok) {
      return res.text().then(function (text) {
        throw new Error('[History] sync failed: ' + res.status + ' ' + text)
      })
    }
    return res.json().then(function (data) {
      if (!data || !Array.isArray(data.messages)) {
        throw new Error('[History] invalid response')
      }
      return data
    })
  })
}

module.exports = { syncVisitorMessages: syncVisitorMessages }
