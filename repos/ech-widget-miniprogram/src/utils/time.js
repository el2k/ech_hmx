/**
 * Time formatting utilities (ported from widget-app)
 */
var i18n = require('../core/i18n')

function formatMessageTime(input) {
  var msgDate = normalizeToDate(input)
  if (!msgDate) return ''

  var now = new Date()
  var diff = now.getTime() - msgDate.getTime()

  var lang = i18n.getLang()

  // < 1 minute
  if (diff < 60 * 1000) return lang === 'zh' ? '刚才' : 'Just now'

  // < 1 hour
  if (diff < 60 * 60 * 1000) {
    var minutes = Math.floor(diff / (60 * 1000))
    return lang === 'zh' ? minutes + '分钟前' : minutes + 'm ago'
  }

  var startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 0, 0, 0, 0)
  var startOfYesterday = new Date(startOfToday.getTime() - 24 * 60 * 60 * 1000)

  // Today
  if (msgDate >= startOfToday) {
    return fmt(msgDate, 'HH:mm')
  }

  // Yesterday
  if (msgDate >= startOfYesterday) {
    var prefix = lang === 'zh' ? '昨天' : 'Yesterday'
    return prefix + ' ' + fmt(msgDate, 'HH:mm')
  }

  // Within 7 days
  var sevenDaysAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000)
  if (msgDate > sevenDaysAgo) {
    var weekday = lang === 'zh' ? weekdayCN(msgDate) : weekdayEN(msgDate)
    return weekday + ' ' + fmt(msgDate, 'HH:mm')
  }

  // Same year
  if (msgDate.getFullYear() === now.getFullYear()) {
    return fmt(msgDate, 'MM-DD HH:mm')
  }

  // Cross year
  return fmt(msgDate, 'YYYY-MM-DD HH:mm')
}

function normalizeToDate(input) {
  if (input instanceof Date) return input
  if (typeof input === 'number' && isFinite(input)) {
    var ms = input < 1e12 ? input * 1000 : input
    var d = new Date(ms)
    return isNaN(d.getTime()) ? null : d
  }
  return null
}

function pad(n) { return n < 10 ? '0' + n : String(n) }

function fmt(d, pattern) {
  var Y = d.getFullYear()
  var M = pad(d.getMonth() + 1)
  var D = pad(d.getDate())
  var h = pad(d.getHours())
  var m = pad(d.getMinutes())
  if (pattern === 'HH:mm') return h + ':' + m
  if (pattern === 'MM-DD HH:mm') return M + '-' + D + ' ' + h + ':' + m
  return Y + '-' + M + '-' + D + ' ' + h + ':' + m
}

function weekdayCN(d) {
  return ['星期日','星期一','星期二','星期三','星期四','星期五','星期六'][d.getDay()]
}

function weekdayEN(d) {
  return ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'][d.getDay()]
}

module.exports = { formatMessageTime: formatMessageTime }
