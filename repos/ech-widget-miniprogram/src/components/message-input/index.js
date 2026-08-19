var i18n = require('../../core/i18n')

Component({
  properties: {
    isStreaming: {
      type: Boolean,
      value: false
    },
    streamCanceling: {
      type: Boolean,
      value: false
    },
    themeColor: {
      type: String,
      value: '#2f80ed'
    },
    disabled: {
      type: Boolean,
      value: false
    }
  },
  data: {
    inputValue: '',
    sendLabel: '',
    interruptLabel: '',
    placeholder: ''
  },
  lifetimes: {
    attached: function () {
      this.setData({
        sendLabel: i18n.t('messageInput.send'),
        interruptLabel: i18n.t('messageInput.interrupt'),
        placeholder: i18n.t('messageInput.placeholder')
      })
    }
  },
  methods: {
    onInput: function (e) {
      this.setData({ inputValue: e.detail.value })
    },

    onConfirm: function () {
      this._doSend()
    },

    onTapSend: function () {
      if (this.properties.isStreaming) {
        this.triggerEvent('cancel')
      } else {
        this._doSend()
      }
    },

    _doSend: function () {
      var text = (this.data.inputValue || '').trim()
      if (!text) return
      this.setData({ inputValue: '' })
      this.triggerEvent('send', { text: text })
    },

    onChooseImage: function () {
      var self = this
      wx.chooseMedia({
        count: 1,
        mediaType: ['image'],
        sourceType: ['album', 'camera'],
        success: function (res) {
          var file = res.tempFiles && res.tempFiles[0]
          if (file) {
            self.triggerEvent('image', { tempFilePath: file.tempFilePath })
          }
        }
      })
    }
  }
})
