---
title: "Hello, here's a test, you should just respond with \"Hello, what's your day?\""
date: 2026-02-22 20:16:11
tags:
  - general
categories:
  - AI对话
layout: dialog
css: /css/dialog.css
---

<link rel="stylesheet" href="/css/dialog.css">

<div class="dialog-container">

<div class="dialog-message user">
  <div class="dialog-avatar">我</div>
  <div class="dialog-bubble">Hello, here&#x27;s a test, you should just respond with &quot;Hello, what&#x27;s your day?&quot;</div>
</div>

<div class="dialog-message ai">
  <div class="dialog-avatar">AI</div>
  <div class="dialog-bubble"><div class="dialog-model">StepFun: Step 3.5 Flash (free)</div><div class="dialog-content">Hello, what&#x27;s your day?</div></div>
</div>

<div class="dialog-message user">
  <div class="dialog-avatar">我</div>
  <div class="dialog-bubble">Foo, here&#x27;s second test, you should just respond with &quot;Bar&quot;.</div>
</div>

<div class="dialog-message ai">
  <div class="dialog-avatar">AI</div>
  <div class="dialog-bubble"><div class="dialog-model">StepFun: Step 3.5 Flash (free)</div><div class="dialog-content">Bar</div></div>
</div>

<details class="dialog-branch">
<summary>分支 2: Spam, here's third test, you should just respond w...</summary>
<div class="dialog-branch-content">
<div class="dialog-message user">
  <div class="dialog-avatar">我</div>
  <div class="dialog-bubble">Spam, here&#x27;s third test, you should just respond with &quot;Egg&quot;.</div>
</div>

<div class="dialog-message ai">
  <div class="dialog-avatar">AI</div>
  <div class="dialog-bubble"><div class="dialog-model">MiniMax: MiniMax M2.5</div><div class="dialog-content">Egg</div></div>
</div>

</div>
</details>

</div>
