# 2026-11-12 插备注列后原图文件要跟着图纸写回去

- 状态：active
- 条目：ICD 出表
- 闸门：`tests/test_icd.py`（`test_shifted_drawing_keeps_the_original_picture_file`）

## 代价

整车低压和变速器插入备注列后，图还在原文件里，打开导出的表却一张都看不到。

## 反事实

只把原图纸 XML 和关系写回去、不把关系指向的图片文件一起放进新包，下一份仍会指向 `image17.png` 这种保存时已经被重新编号、包里已经没有的文件。列号只认不带前缀的 `<col>` 时，客户文件里的 `<xdr:col>` 也不会跟着备注列右移。

## 二级依据

- 保存前记下原图纸、它的关系，以及关系指向的图片字节。openpyxl 保存会重排图片文件名。写回原图纸时，关系指向的图片字节要按原路径盖回去；只在包里缺文件时才补，会把别的表的图留在这个文件名上。
- 把整车低压和变速器改成固定大小、并跳过原图纸写回，下一份会把图填到别的表上，备注列也会消失。这两张表的备注和图怎么一起留在原表，见 `2026-11-12-icd-picture-stays-on-its-sheet.md`。

## 闸门

`test_shifted_drawing_keeps_the_original_picture_file`：源图关系指向 `../media/image17.png`。出表后这张图仍在包里，并且是 PNG。锚点从第 2 列移到第 3 列，列内偏移不变。`<xdr:col>1</xdr:col>` 变成 2，`<xdr:colOff>` 不变。
