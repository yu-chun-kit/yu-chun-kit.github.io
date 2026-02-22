---
title: "AI对话示例：如何优化代码性能"
date: 2026-02-22 15:30:00
tags:
  - AI对话
  - 性能优化
categories:
  - 技术分享
layout: dialog
css: /css/dialog.css
---

<link rel="stylesheet" href="/css/dialog.css">

<div class="dialog-container">

<div class="dialog-message user">
  <div class="dialog-avatar">我</div>
  <div class="dialog-bubble">
    我有一个JavaScript数组去重的需求，当前数据量大概是10万条，有什么高效的方案吗？
  </div>
</div>

<div class="dialog-message ai">
  <div class="dialog-avatar">AI</div>
  <div class="dialog-bubble">
    对于10万级别的数据量，推荐使用 <code>Set</code> 数据结构，它的时间复杂度是O(n)：
    <pre><code>const unique = [...new Set(array)];</code></pre>
    或者如果需要保留原始顺序且兼容旧浏览器：
    <pre><code>const unique = array.filter((item, index) => array.indexOf(item) === index);</code></pre>
  </div>
</div>

<div class="dialog-message user">
  <div class="dialog-avatar">我</div>
  <div class="dialog-bubble">
    如果数组元素是对象呢？比如 <code>[{id: 1, name: 'a'}, {id: 1, name: 'a'}]</code> 这种
  </div>
</div>

<div class="dialog-branch">
  对话分支：对象去重需要根据特定字段判断
</div>

<div class="dialog-message ai">
  <div class="dialog-avatar">AI</div>
  <div class="dialog-bubble">
    对象去重需要指定根据哪个字段判断。假设根据 <code>id</code> 字段：
    <pre><code>const unique = array.filter((item, index, self) =>
  index === self.findIndex(t => t.id === item.id)
);</code></pre>
    如果数据量很大，可以用 Map 优化到 O(n)：
    <pre><code>const seen = new Map();
const unique = array.filter(item => {
  if (!seen.has(item.id)) {
    seen.set(item.id, true);
    return true;
  }
  return false;
});</code></pre>
  </div>
</div>

<div class="dialog-message user">
  <div class="dialog-avatar">我</div>
  <div class="dialog-bubble">
    明白了！Map方案在大量数据下性能会更好对吧？
  </div>
</div>

<div class="dialog-message ai">
  <div class="dialog-avatar">AI</div>
  <div class="dialog-bubble">
    是的！性能对比（10万元素）：
    <ul>
      <li>filter + findIndex: ~500ms (O(n²))</li>
      <li>Map方案: ~5ms (O(n))</li>
    </ul>
    100倍的差距！对于你的10万数据量，强烈建议用Map方案。
  </div>
</div>

</div>
