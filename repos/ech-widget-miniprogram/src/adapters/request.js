/**
 * wx.request Promise adapter (replaces fetch)
 *
 * Returns: { ok, status, statusText, data, json(), text(), headers }
 */
function request({ url, method, headers, body, timeout }) {
  return new Promise(function (resolve, reject) {
    wx.request({
      url: url,
      method: (method || 'GET').toUpperCase(),
      header: headers || {},
      data: body,
      timeout: timeout || 15000,
      dataType: 'json',
      success: function (res) {
        var ok = res.statusCode >= 200 && res.statusCode < 300
        resolve({
          ok: ok,
          status: res.statusCode,
          statusText: ok ? 'OK' : 'Error',
          data: res.data,
          headers: res.header || {},
          json: function () { return Promise.resolve(res.data) },
          text: function () {
            return Promise.resolve(
              typeof res.data === 'string' ? res.data : JSON.stringify(res.data)
            )
          }
        })
      },
      fail: function (err) {
        reject(new Error('[request] ' + (err.errMsg || 'network error')))
      }
    })
  })
}

module.exports = { request }
