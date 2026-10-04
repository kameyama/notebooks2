# CLAUDE.md

## papers/ 以下の論文ページ

`papers/<名前>/index.qmd` は、親ファイルの LaTeX ソースから pandoc で生成したものである。親ファイルはこのリポジトリの外にあり、各ページに対応する親ディレクトリの場所は `CLAUDE.local.md`（git 管理外）に書く。

- 親ディレクトリの `main.tex` が正本である。`refs.bib` と `paper.pdf`（親の `main.pdf`）はコピーである。
- 本文・数式・文献は index.qmd を直接編集しない。親の `main.tex` を直して再生成する。
- 直接編集してよいのは qmd 固有の部分だけである。
  - front matter（title, subtitle, description, date, categories, author, bibliography, number-sections, toc, resources, other-links, abstract の書式）
  - Quarto の記法への変換（定理ブロック `::: {#prp-...}` / `{#lem-...}` / `{#rem-...}`、`.proof`、クロスリファレンス `@prp-...` / `@tbl-...` / `@sec-...`、`{.appendix}`、callout）

### 再生成の手順

```bash
quarto pandoc <親>/main.tex -f latex -t markdown --wrap=none
```

出力に次の後処理をかけて index.qmd の本文にする。

1. LaTeX の参照（`[1](#prop:rule){reference-type="ref" ...}`）を Quarto のクロスリファレンスに置き換える
2. 定理環境と proof を Quarto の定理ブロックにする
3. `$$\begin{equation}...\end{equation}$$` を `$$...$$` にする
4. 綴りをアメリカ式にする（regularisation → regularization, colour → color, analogue → analog など）
5. 既存の front matter と qmd 固有の部分を残す

再生成したら `refs.bib` と `paper.pdf` も親からコピーし直す。
