/**
 * File upload service using wx.uploadFile
 * API: POST /v1/chat/upload
 */

function uploadChatFile(params) {
  var apiBase = (params.apiBase || '').replace(/\/$/, '')
  var apiKey = params.apiKey || ''
  var channelId = params.channelId || ''
  var channelType = params.channelType || 251
  var filePath = params.filePath
  var onProgress = params.onProgress

  return new Promise(function (resolve, reject) {
    var task = wx.uploadFile({
      url: apiBase + '/v1/chat/upload',
      filePath: filePath,
      name: 'file',
      header: {
        'X-Platform-API-Key': apiKey
      },
      formData: {
        channel_id: channelId,
        channel_type: String(channelType)
      },
      success: function (res) {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          try {
            var data = JSON.parse(res.data)
            if (!data || !data.file_id) {
              return reject(new Error('[Upload] invalid response'))
            }
            resolve(data)
          } catch (e) {
            reject(new Error('[Upload] invalid JSON response'))
          }
        } else {
          reject(new Error('[Upload] failed: ' + res.statusCode))
        }
      },
      fail: function (err) {
        reject(new Error('[Upload] ' + (err.errMsg || 'upload failed')))
      }
    })

    if (onProgress && task) {
      task.onProgressUpdate(function (r) {
        onProgress(r.progress)
      })
    }
  })
}

/**
 * Get image dimensions using wx.getImageInfo
 */
function getImageInfo(filePath) {
  return new Promise(function (resolve) {
    wx.getImageInfo({
      src: filePath,
      success: function (res) {
        resolve({ width: res.width, height: res.height })
      },
      fail: function () {
        resolve(null)
      }
    })
  })
}

module.exports = {
  uploadChatFile: uploadChatFile,
  getImageInfo: getImageInfo
}
