/**
 * Self-recursive json-render element component.
 * Renders a single element from the spec by type, recursing for children.
 */
Component({
  options: {
    virtualHost: true
  },

  properties: {
    elementKey: {
      type: String,
      value: ''
    },
    spec: {
      type: Object,
      value: null
    },
    stateSnapshot: {
      type: Object,
      value: null
    },
    depth: {
      type: Number,
      value: 0
    }
  },

  data: {
    el: null,
    elType: '',
    childKeys: [],
    // Text
    textContent: '',
    textVariant: '',
    kvLabel: '',
    kvValue: '',
    isKV: false,
    isSectionTitle: false,
    // Badge
    badgeTone: 'info',
    badgeLabel: '',
    // KV element
    kvElLabel: '',
    kvElValue: '',
    kvHighlight: false,
    // PriceRow
    priceLabel: '',
    priceValue: '',
    priceEmphasis: false,
    priceDiscount: false,
    // OrderItem
    orderName: '',
    orderSku: '',
    orderQty: '1',
    orderPrice: '',
    // Image
    imageSrc: '',
    imageAlt: '',
    // Button
    btnLabel: 'Submit',
    btnVariant: '',
    btnDisabled: false,
    // Card
    cardVariant: '',
    // Section
    sectionTitle: '',
    // Row
    rowJustify: '',
    rowAlign: '',
    rowGap: '',
    rowWrap: false,
    // Column
    colGap: '',
    // Input
    inputLabel: '',
    inputPlaceholder: '',
    inputValue: '',
    inputBindingPath: '',
    // Checkbox
    cbLabel: '',
    cbChecked: false,
    cbBindingPath: '',
    // MultipleChoice
    mcLabel: '',
    mcOptions: [],
    mcOptionLabels: [],
    mcValue: '',
    mcIndex: 0,
    mcBindingPath: '',
    // DateTimeInput
    dtLabel: '',
    dtValue: '',
    dtMode: 'date',
    dtBindingPath: '',
    // Max recursion
    tooDeep: false
  },

  observers: {
    'elementKey, spec, stateSnapshot': function (key, spec) {
      this._resolve(key, spec)
    }
  },

  methods: {
    _resolve: function (key, spec) {
      if (!key || !spec || !spec.elements) {
        this.setData({ el: null, elType: '' })
        return
      }
      if (this.properties.depth > 10) {
        this.setData({ tooDeep: true, elType: '' })
        return
      }

      var el = spec.elements[key]
      if (!el) {
        this.setData({ el: null, elType: '' })
        return
      }

      var t = (el.type || '').toLowerCase()
      var props = el.props || {}
      var children = el.children || []
      var setObj = {
        el: el,
        elType: t,
        childKeys: children,
        tooDeep: false
      }

      // Type-specific data extraction
      if (t === 'text') {
        var text = this._pickStr(props, ['text', 'label', 'value', 'content'])
        var variant = this._str(props.variant).toLowerCase()
        var pair = this._splitKV(text)
        var isST = variant === 'section-title' || this._isSectionTitle(text)
        setObj.textContent = text
        setObj.textVariant = variant
        setObj.isKV = !isST && !!pair && variant !== 'plain'
        setObj.isSectionTitle = isST
        if (pair) {
          setObj.kvLabel = pair.label
          setObj.kvValue = pair.value
        }
      } else if (t === 'badge' || t === 'statusbadge') {
        setObj.elType = 'badge'
        setObj.badgeTone = this._str(props.tone).toLowerCase() || 'info'
        setObj.badgeLabel = this._pickStr(props, ['label', 'text', 'value'])
      } else if (t === 'kv' || t === 'keyvalue') {
        setObj.elType = 'kv'
        setObj.kvElLabel = this._pickStr(props, ['label', 'key', 'name'])
        setObj.kvElValue = this._pickStr(props, ['value', 'text', 'amount'])
        setObj.kvHighlight = this._toBool(props.highlight) || this._isHeadlineKey(setObj.kvElLabel)
      } else if (t === 'pricerow' || t === 'amountrow') {
        setObj.elType = 'pricerow'
        var pLabel = this._pickStr(props, ['label', 'title', 'name'])
        var rawVal = props.amount != null ? props.amount : (props.value != null ? props.value : props.text)
        var valText = this._str(rawVal)
        var numeric = this._toNum(rawVal)
        var currency = this._pickStr(props, ['currency']) || '\u00a5'
        var emphasis = this._toBool(props.emphasis) || this._isHeadlineKey(pLabel)
        var discount = this._toBool(props.discount) || this._isDiscountKey(pLabel) || (numeric !== null && numeric < 0)
        var shownVal = valText || (numeric !== null ? currency + Math.abs(numeric).toFixed(2) : '')
        if (discount && numeric !== null && numeric > 0) {
          shownVal = '-' + currency + numeric.toFixed(2)
        }
        setObj.priceLabel = pLabel
        setObj.priceValue = shownVal
        setObj.priceEmphasis = emphasis
        setObj.priceDiscount = discount
      } else if (t === 'orderitem' || t === 'lineitem') {
        setObj.elType = 'orderitem'
        setObj.orderName = this._pickStr(props, ['name', 'title', 'label'])
        setObj.orderSku = this._pickStr(props, ['sku'])
        setObj.orderQty = this._pickStr(props, ['quantity', 'qty']) || '1'
        setObj.orderPrice = this._pickStr(props, ['subtotal', 'price', 'amount'])
      } else if (t === 'image') {
        setObj.imageSrc = this._pickStr(props, ['url', 'src'])
        setObj.imageAlt = this._pickStr(props, ['alt']) || 'image'
      } else if (t === 'button') {
        setObj.btnLabel = this._pickStr(props, ['label', 'text']) || 'Submit'
        var bv = this._str(props.variant).toLowerCase()
        if (this._toBool(props.primary) || bv === 'primary') bv = 'primary'
        setObj.btnVariant = bv
        setObj.btnDisabled = this._toBool(props.disabled)
      } else if (t === 'buttongroup' || t === 'actions') {
        setObj.elType = 'buttongroup'
      } else if (t === 'card') {
        setObj.cardVariant = this._str(props.variant).toLowerCase()
      } else if (t === 'section' || t === 'sectioncard') {
        setObj.elType = 'section'
        setObj.sectionTitle = this._pickStr(props, ['title', 'label', 'text'])
      } else if (t === 'row') {
        setObj.rowJustify = this._str(props.justify).toLowerCase()
        setObj.rowAlign = this._str(props.align).toLowerCase()
        setObj.rowGap = this._str(props.gap).toLowerCase()
        setObj.rowWrap = this._toBool(props.wrap)
      } else if (t === 'column' || t === 'list') {
        setObj.elType = 'column'
        setObj.colGap = this._str(props.gap).toLowerCase()
      } else if (t === 'input' || t === 'textfield') {
        setObj.elType = 'input'
        setObj.inputLabel = this._str(props.label)
        setObj.inputPlaceholder = this._str(props.placeholder)
        var iBind = (el.bindings && el.bindings.value) || ''
        setObj.inputBindingPath = iBind
        setObj.inputValue = iBind ? this._getState(iBind) : this._str(props.value)
      } else if (t === 'checkbox') {
        var rawCb = props.value != null ? props.value : (props.checked != null ? props.checked : props.selected)
        var cbBind = (el.bindings && (el.bindings.value || el.bindings.checked || el.bindings.selected)) || ''
        setObj.cbLabel = this._str(props.label) || this._str(props.text)
        setObj.cbBindingPath = cbBind
        setObj.cbChecked = cbBind ? this._toBool(this._getState(cbBind)) : this._toBool(rawCb)
      } else if (t === 'multiplechoice') {
        var rawOpts = Array.isArray(props.options) ? props.options : []
        var opts = []
        var optLabels = []
        for (var oi = 0; oi < rawOpts.length; oi++) {
          var item = rawOpts[oi]
          if (typeof item === 'string' && item) {
            opts.push({ label: item, value: item })
            optLabels.push(item)
          } else if (item && typeof item === 'object') {
            var ol = this._str(item.label)
            var ov = this._str(item.value)
            if (ov) {
              opts.push({ label: ol || ov, value: ov })
              optLabels.push(ol || ov)
            }
          }
        }
        var mcRaw = props.value != null ? props.value : (props.selectedValue != null ? props.selectedValue : props.selectedValues)
        var mcInit = Array.isArray(mcRaw) ? this._str(mcRaw[0]) : this._str(mcRaw)
        var mcBind = (el.bindings && (el.bindings.value || el.bindings.selectedValue || el.bindings.selectedValues)) || ''
        var mcVal = mcBind ? this._str(this._getState(mcBind)) : mcInit
        var mcIdx = 0
        for (var mi = 0; mi < opts.length; mi++) {
          if (opts[mi].value === mcVal) { mcIdx = mi; break }
        }
        setObj.mcLabel = this._str(props.label)
        setObj.mcOptions = opts
        setObj.mcOptionLabels = optLabels
        setObj.mcValue = mcVal
        setObj.mcIndex = mcIdx
        setObj.mcBindingPath = mcBind
      } else if (t === 'datetimeinput') {
        var dtBind = (el.bindings && (el.bindings.value || el.bindings.date || el.bindings.selectedDate)) || ''
        var dtRaw = props.value != null ? props.value : (props.date != null ? props.date : props.selectedDate)
        var dtMode = this._str(props.mode).toLowerCase() || this._str(props.type).toLowerCase() || 'date'
        setObj.dtLabel = this._str(props.label)
        setObj.dtBindingPath = dtBind
        setObj.dtValue = dtBind ? this._str(this._getState(dtBind)) : this._str(dtRaw)
        setObj.dtMode = dtMode === 'time' ? 'time' : 'date'
      } else if (t === 'divider') {
        // no extra data needed
      }

      this.setData(setObj)
    },

    // -- Helpers --
    _str: function (v) {
      if (typeof v === 'string') return v
      if (typeof v === 'number' || typeof v === 'boolean') return String(v)
      return ''
    },
    _pickStr: function (props, keys) {
      for (var i = 0; i < keys.length; i++) {
        var v = this._str(props[keys[i]])
        if (v) return v
      }
      return ''
    },
    _toBool: function (v) {
      if (typeof v === 'boolean') return v
      if (typeof v === 'string') return v === 'true'
      return false
    },
    _toNum: function (v) {
      if (typeof v === 'number' && isFinite(v)) return v
      if (typeof v === 'string') {
        var n = Number(v.replace(/[^0-9.+-]/g, ''))
        if (isFinite(n)) return n
      }
      return null
    },
    _splitKV: function (text) {
      var t = (text || '').trim()
      if (!t) return null
      var m = t.match(/^([^:\uff1a]{1,24})[:\uff1a]\s*(.+)$/)
      if (!m) return null
      var label = m[1].trim()
      var value = m[2].trim()
      if (!label || !value) return null
      return { label: label, value: value }
    },
    _isSectionTitle: function (text) {
      return /^(商品详情|支付信息|收货信息|订单信息|物流信息|商品明细|支付详情|配送信息|订单详情|items|payment|shipping|order)$/i.test((text || '').trim())
    },
    _isHeadlineKey: function (label) {
      return /(实付金额|应付金额|支付金额|合计|总额|payable|grand total|total)/i.test(label || '')
    },
    _isDiscountKey: function (label) {
      return /(优惠|折扣|减免|discount|coupon)/i.test(label || '')
    },
    _getState: function (path) {
      var ss = this.properties.stateSnapshot
      if (!ss || !path) return ''
      var parts = path.split('.')
      var cur = ss
      for (var i = 0; i < parts.length; i++) {
        if (cur == null || typeof cur !== 'object') return ''
        cur = cur[parts[i]]
      }
      return cur != null ? cur : ''
    },

    // -- Events --
    onButtonTap: function () {
      if (this.data.btnDisabled) return
      var el = this.data.el
      if (!el || !el.on || !el.on.press) return
      var binding = el.on.press
      var actions = Array.isArray(binding) ? binding : [binding]
      for (var i = 0; i < actions.length; i++) {
        var act = actions[i]
        if (act && act.action) {
          this.triggerEvent('action', {
            actionName: act.action,
            params: act.params || {}
          }, { bubbles: true, composed: true })
        }
      }
    },
    onInputChange: function (e) {
      var val = e.detail.value
      var path = this.data.inputBindingPath
      if (path) {
        this.triggerEvent('statechange', { path: path, value: val }, { bubbles: true, composed: true })
      }
      this.setData({ inputValue: val })
    },
    onCheckboxTap: function () {
      var newVal = !this.data.cbChecked
      this.setData({ cbChecked: newVal })
      var path = this.data.cbBindingPath
      if (path) {
        this.triggerEvent('statechange', { path: path, value: newVal }, { bubbles: true, composed: true })
      }
    },
    onPickerChange: function (e) {
      var idx = parseInt(e.detail.value, 10)
      var opts = this.data.mcOptions
      if (idx >= 0 && idx < opts.length) {
        var val = opts[idx].value
        this.setData({ mcValue: val, mcIndex: idx })
        var path = this.data.mcBindingPath
        if (path) {
          this.triggerEvent('statechange', { path: path, value: val }, { bubbles: true, composed: true })
        }
      }
    },
    onDateChange: function (e) {
      var val = e.detail.value
      this.setData({ dtValue: val })
      var path = this.data.dtBindingPath
      if (path) {
        this.triggerEvent('statechange', { path: path, value: val }, { bubbles: true, composed: true })
      }
    }
  }
})
