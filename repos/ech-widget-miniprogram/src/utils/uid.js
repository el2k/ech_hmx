/**
 * Generate unique clientMsgNo
 */
function generateClientMsgNo(prefix) {
  var p = prefix || 'cmn'
  var ts = Date.now()
  var rand = Math.random().toString(36).slice(2, 8)
  return p + '-' + ts + '-' + rand
}

module.exports = { generateClientMsgNo: generateClientMsgNo }
