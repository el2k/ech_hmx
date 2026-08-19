/**
 * <tgo-chat> main component
 *
 * Usage:
 *   <tgo-chat api-key="ak_live_xxx" api-base="https://your-api.com" />
 */
var chatStore = require('../core/chatStore')
var platformStore = require('../core/platformStore')
var i18n = require('../core/i18n')

Component({
  options: {
    multipleSlots: true
  },

  properties: {
    apiKey: {
      type: String,
      value: ''
    },
    apiBase: {
      type: String,
      value: ''
    },
    themeColor: {
      type: String,
      value: ''
    },
    lang: {
      type: String,
      value: 'zh'
    },
    visitorName: {
      type: String,
      value: ''
    },
    visitorAvatar: {
      type: String,
      value: ''
    },
    customAttrs: {
      type: Object,
      value: null
    }
  },

  data: {
    messages: [],
    isStreaming: false,
    streamCanceling: false,
    online: false,
    historyLoading: false,
    historyHasMore: true,
    initializing: false,
    error: null,
    resolvedThemeColor: '#2f80ed',
    title: 'Tgo',
    logoUrl: ''
  },

  lifetimes: {
    attached: function () {
      // Set i18n language
      i18n.setLang(this.properties.lang)

      // Subscribe to stores
      this._bindStores()

      // Initialize
      this._init()
    },

    detached: function () {
      if (this._unsubChat) { this._unsubChat(); this._unsubChat = null }
      if (this._unsubPlatform) { this._unsubPlatform(); this._unsubPlatform = null }
      chatStore.disconnect()
    }
  },

  methods: {
    _bindStores: function () {
      var self = this

      // Subscribe to chat store
      this._unsubChat = chatStore.subscribe(function (state) {
        self.setData({
          messages: state.messages,
          isStreaming: state.isStreaming,
          streamCanceling: state.streamCanceling,
          online: state.online,
          historyLoading: state.historyLoading,
          historyHasMore: state.historyHasMore,
          initializing: state.initializing,
          error: state.error
        })
      })

      // Subscribe to platform store
      this._unsubPlatform = platformStore.subscribe(function (state) {
        var cfg = state.config || {}
        self.setData({
          title: cfg.widget_title || 'Tgo',
          logoUrl: cfg.logo_url || '',
          resolvedThemeColor: self.properties.themeColor || cfg.theme_color || '#2f80ed'
        })

        // Inject welcome message
        if (cfg.welcome_message && !state.welcomeInjected) {
          chatStore.ensureWelcomeMessage(cfg.welcome_message)
          platformStore.markWelcomeInjected()
        }
      })
    },

    _init: function () {
      var apiBase = this.properties.apiBase
      var apiKey = this.properties.apiKey

      if (!apiBase || !apiKey) {
        console.error('[tgo-chat] api-base and api-key are required')
        return
      }

      // Init platform config
      platformStore.init(apiBase, apiKey)

      // Set resolved theme color
      this.setData({
        resolvedThemeColor: this.properties.themeColor || '#2f80ed'
      })

      // Init chat IM
      chatStore.initIM({
        apiBase: apiBase,
        platformApiKey: apiKey
      })
    },

    // Event handlers from child components
    onSendMessage: function (e) {
      var text = e.detail && e.detail.text
      if (text) {
        chatStore.sendMessage(text)
      }
    },

    onCancelStream: function () {
      chatStore.cancelStreaming('user_cancel')
    },

    onLoadMore: function () {
      if (!chatStore.getState().historyLoading && chatStore.getState().historyHasMore) {
        chatStore.loadMoreHistory(20)
      }
    },

    onChooseImage: function (e) {
      var tempFilePath = e.detail && e.detail.tempFilePath
      if (tempFilePath) {
        chatStore.uploadImage(tempFilePath)
      }
    }
  }
})
