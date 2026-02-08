---
layout: post
title:  "How to create a react package"
date:   2022-07-10 17:34:00 +0800
categories: can't sleep
---



Referred to website [How to Create and Publish a React Component Library - DEV Community](https://dev.to/alexeagleson/how-to-create-and-publish-a-react-component-library-2oe)

## create project and set config by shell script
```sh
mkdir new_project && cd !$

# init node project without default
yarn init -y

yarn add --dev react typescript @types/react

npx tsc --init

yarn add --dev rollup @rollup/plugin-node-resolve @rollup/plugin-commonjs rollup-plugin-dts

# create a config file
touch rollup.config.js
```

## write some code in `rollup.config.js`

```js
import resolve from "@rollup/plugin-node-resolve";
import commonjs from "@rollup/plugin-commonjs";
import typescript from "@rollup/plugin-typescript";
import dts from "rollup-plugin-dts";

const packageJson = require("./package.json");

export default [
  {
    input: "src/index.ts",
    output: [
      {
        file: packageJson.main,
        format: "cjs",
        sourcemap: true,
      },
      {
        file: packageJson.module,
        format: "esm",
        sourcemap: true,
      },
    ],
    plugins: [
      resolve(),
      commonjs(),
      typescript({ tsconfig: "./tsconfig.json" }),
    ],
  },
  {
    input: "dist/esm/types/index.d.ts",
    output: [{ file: "dist/index.d.ts", format: "esm" }],
    plugins: [dts()],
  },
];
```

## add two lines in `package.json`
```js
{
//   "name": "template-react-component-library",
//   "version": "0.0.1",
//   "description": "A simple template for a custom React component library",
//   "scripts": {
//     "rollup": "rollup -c"
//   },
//   "author": "Alex Eagleson",
//   "license": "ISC",
//   "devDependencies": {
//     "@rollup/plugin-commonjs": "^21.0.1",
//     "@rollup/plugin-node-resolve": "^13.0.6",
//     "@rollup/plugin-typescript": "^8.3.0",
//     "@types/react": "^17.0.34",
//     "react": "^17.0.2",
//     "rollup": "^2.60.0",
//     "rollup-plugin-dts": "^4.0.1",
//     "typescript": "^4.4.4"
//   },
  "main": "dist/cjs/index.js",
  "module": "dist/esm/index.js",
//   "files": [
//     "dist"
//   ],
//   "types": "dist/index.d.ts"
}
```

## then
```sh
# run rollup
yarn run rollup


```

## add these line to react package.json
```json
{
  "name": "@YOUR_GITHUB_USERNAME/YOUR_REPOSITORY_NAME",
  "publishConfig": {
    "registry": "https://npm.pkg.github.com/YOUR_GITHUB_USERNAME"
  },
  ...  
}
```

%userprofile%\.npmrc or ~/.npmrc
```
registry=https://registry.npmjs.org/
@YOUR_GITHUB_USERNAME:registry=https://npm.pkg.github.com/
//npm.pkg.github.com/:_authToken=YOUR_AUTH_TOKEN
```
