# 导师汇报PPT源文件

`build_deck.mjs`读取同级的`source-deck-reference.json`和相邻的`../assets/`，生成14页可编辑PPTX。数据图表由已归档数值构建，两张SVisual原生图保持原始图像字节。

重建时保留以下相对目录：

```text
可编辑源文件/
  assets/
  slides/
    build_deck.mjs
    source-deck-reference.json
    qa/verify_delivery.py
```

在已配置的Codex依赖环境中，使用一个未用过的版本标识运行：

```powershell
& 'C:/Users/sun/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe' ./build_deck.mjs new_revision
```

如运行环境路径变化，可设置`CODEX_ARTIFACT_RUNTIME`和`PRESENTATIONS_SKILL_DIR`。程序读取已有依赖，不安装软件。

最终PPTX写入`output/`，校验和从最终PPTX导入后生成的逐页PNG写入`qa/<版本>/`，文字与备注清单写入`slides-text-<版本>.json`及`.md`。原16页PPTX在工作区存在时另做只读复核；打包后无需该原文件，已有来源记录保存在`source-deck-reference.json`。需要检查其他位置的原版时，可设置`MENTOR_SOURCE_DECK`。

当前交付版本为`r4`。`qa/r4/validation.json`记录结构、版面、字体和可编辑表图检查；`content-verification.json`记录文字、表格、图表数据、备注及原生图字节核对。`visual-review.json`记录逐页目视结果。未在原生PowerPoint中执行编辑或播放测试。
