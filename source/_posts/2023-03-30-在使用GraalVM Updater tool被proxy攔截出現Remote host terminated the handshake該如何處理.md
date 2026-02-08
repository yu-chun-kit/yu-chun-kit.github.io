---
title: "在使用GraalVM Updater tool被proxy攔截出現Remote host terminated the handshake該如何處理"
date: 2023-03-30 10:44:00
categories:
  - coding
tags:
---

## 解法

在使用GraalVM Updater tool被proxy攔截出現Remote host terminated the handshake該如何處理，以下是解決方法：

* 設定 `HTTP_PROXY` 環境變數
* 設定 `HTTPS_PROXY` 環境變數
* [重點] 用 `gu --vm.Dhttps.protocols=SSLv3,TLSv1,TLSv1.1,TLSv1.2 install native-image` 來安裝native-image

## 結語

在使用GraalVM Updater tool被proxy攔截出現Remote host terminated the handshake該如何處理，以上是解決方法。

## 參考資料

* [gu install native-image - java.net.UnknownHostException: github.com](https://github.com/oracle/graal/issues/1506) 最後一個comment
