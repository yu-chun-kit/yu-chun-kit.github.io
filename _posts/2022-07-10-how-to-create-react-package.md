---
layout: post
title:  "How to create a react package"
date:   2022-07-10 17:34:00 +0800
categories: can't sleep
---



Referred to website [How to Create and Publish a React Component Library - DEV Community](https://dev.to/alexeagleson/how-to-create-and-publish-a-react-component-library-2oe)

```sh
mkdir new_project && cd !$

# init node project without default
yarn init -y

yarn add --dev react typescript @types/react

npx tsc --init

yarn add --dev rollup @rollup/plugin-node-resolve @rollup/plugin-commonjs rollup-plugin-dts

# create a config file
touch rollup.config.js

# write some code...


```