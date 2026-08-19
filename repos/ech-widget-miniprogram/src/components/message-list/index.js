var types = require('../../core/types')
var timeUtil = require('../../utils/time')

Component({
  properties: {
    messages: {
      type: Array,
      value: [],
      observer: function (newVal) {
        this._processMessages(newVal)
      }
    },
    historyLoading: {
      type: Boolean,
      value: false
    },
    historyHasMore: {
      type: Boolean,
      value: true
    },
    isStreaming: {
      type: Boolean,
      value: false
    },
    themeColor: {
      type: String,
      value: '#2f80ed'
    }
  },

  data: {
    displayMessages: [],
    scrollTop: 0,
    scrollAnimated: true,
    _prevLen: 0,
    _scrollCounter: 0
  },

  lifetimes: {
    attached: function () {
      if (this.properties.messages.length) {
        this._processMessages(this.properties.messages)
      }
    }
  },

  methods: {
    _processMessages: function (messages) {
      var prevLen = this.data._prevLen
      var list = (messages || []).map(function (m) {
        var isSystem = m.payload && types.isSystemMessageType(m.payload.type)
        var hasUiParts = Array.isArray(m.uiParts) && m.uiParts.length > 0
        return {
          id: m.id,
          role: m.role,
          payload: m.payload,
          streamData: m.streamData,
          errorMessage: m.errorMessage,
          status: m.status,
          uploadProgress: m.uploadProgress,
          isSystem: isSystem,
          isSelf: m.role === 'user',
          _time: m.time ? timeUtil.formatMessageTime(m.time) : '',
          uiParts: hasUiParts ? m.uiParts : null,
          hasUiParts: hasUiParts
        }
      })

      var shouldScroll = false
      if (list.length > prevLen) {
        shouldScroll = true
      } else if (list.length > 0) {
        var last = list[list.length - 1]
        if (last.streamData) {
          shouldScroll = true
        }
      }

      var setObj = {
        displayMessages: list,
        _prevLen: list.length
      }

      if (shouldScroll && list.length > 0) {
        // Toggle between two large values to force scroll-top re-trigger
        var c = this.data._scrollCounter + 1
        setObj.scrollTop = 999999 + (c % 2)
        setObj._scrollCounter = c
        setObj.scrollAnimated = !last || !last.streamData
      }

      this.setData(setObj)
    },

    onScrollToUpper: function () {
      this.triggerEvent('loadmore')
    },

    onTapImage: function (e) {
      var url = e.currentTarget.dataset.url
      if (url) {
        wx.previewImage({
          current: url,
          urls: [url]
        })
      }
    },

    onJsonRenderSend: function (e) {
      this.triggerEvent('sendmessage', e.detail)
    }
  }
})
