/**
 * Markdown to HTML using marked
 * Output is used with <rich-text> component
 */
var marked = require('marked')

// Configure marked for simple output
marked.setOptions({
  breaks: true,
  gfm: true
})

/**
 * Parse markdown string to HTML (safe for rich-text)
 * rich-text does its own sanitization so no DOMPurify needed
 */
function parseMarkdown(text) {
  if (!text) return ''
  try {
    var html = marked.parse(text)
    // Remove outer <p> wrapper for simple single-paragraph text
    if (typeof html === 'string') {
      return html.trim()
    }
    return String(html || '')
  } catch (e) {
    return text
  }
}

module.exports = { parseMarkdown: parseMarkdown }
