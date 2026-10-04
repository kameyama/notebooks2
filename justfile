set shell := ["bash", "-euo", "pipefail", "-c"]

# レシピ一覧
default:
    just --list

# ローカルでサイトをプレビューする (http://localhost:4321)
preview:
    quarto preview --port 4321 --no-browser

# サイト全体を _site/ にレンダリングする
render:
    quarto render
