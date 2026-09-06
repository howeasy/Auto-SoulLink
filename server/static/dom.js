// Small DOM constructors: dynamic values become text or attribute values,
// never parsed HTML. Callers choose the element/attribute names in source.
(function () {
  'use strict';
  function el(tag, properties) {
    var node = document.createElement(tag);
    Object.entries(properties || {}).forEach(function (entry) {
      var name = entry[0], value = entry[1];
      if (name === 'className') node.className = value;
      else if (name === 'style') Object.assign(node.style, value);
      else if (name.startsWith('on') && typeof value === 'function') node.addEventListener(name.slice(2), value);
      else node.setAttribute(name, String(value));
    });
    Array.prototype.slice.call(arguments, 2).flat().forEach(function (child) {
      if (child !== undefined && child !== null) node.append(child);
    });
    return node;
  }
  function table(headers, rows, className) {
    return el('table', {className: className || ''},
      el('thead', {}, el('tr', {}, headers.map(function (name) { return el('th', {}, name); }))),
      el('tbody', {}, rows.map(function (cells) {
        return el('tr', {}, cells.map(function (value) { return el('td', {}, value); }));
      })));
  }
  window.SLinkDOM = Object.freeze({el: el, table: table});
})();
