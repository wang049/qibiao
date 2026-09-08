# 2026-09-07 扫描件摘录说明要写出花字，不要说「乱码」

- 状态：active
- 条目：核对表说明列（扫描件摘录）
- 闸门：`electrical/tests/test_extract_quality.py` `test_ocr_garbage_excerpt_becomes_partial`、`test_markdown_heading_hashes_are_not_ocr_garbage`；`_looks_like_ocr_garbage` 忽略 Markdown `###`；摘录通顺时 `_scrub_false_ocr_note` 去掉「乱码 / 花成」句。禁止再用「乱码，请对照原页确认」。

## 代价

说明写成「原文摘录含扫描件乱码，请对照原页确认」，现场看不懂「乱码 / 对照原页」指什么，也不知道要核哪一页。

## 反事实

不把花字样本和页码写进说明，下次仍会：值能读、摘录是 `th#Hi#E&E` 这类扫描识别花字，格子只标局部对应，人却不知道原因。

## 二级依据

- 扫描件 OCR 常把中文认成 `#H` `#R` `#E`；抽出值可能仍是页上的数，摘录不能当已核对原句。
- 产品口径：宁标局部对应，也不要把扫描件假「已检索到」。说明必须能指导打开对应印页核对抽出值。

## 闸门

`_ocr_excerpt_note`：说明含「扫描识别花成」+ 摘录里的花字样本；有印页则写「请打开第 N 页核对抽出值」。禁止再用「乱码，请对照原页确认」。Markdown 标题 `### Y-电容选择` 不是花字，不得降成局部对应。模型若抄旧「乱码」句，出表前刮掉。
