var markdown = require('../../utils/markdown')

Component({
  properties: {
    content: {
      type: String,
      value: '',
      observer: function (val) {
        this.setData({ html: markdown.parseMarkdown(val) })
      }
    }
  },
  data: {
    html: ''
  },
  lifetimes: {
    attached: function () {
      if (this.properties.content) {
        this.setData({ html: markdown.parseMarkdown(this.properties.content) })
      }
    }
  }
})
