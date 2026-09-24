// Book typesetting for manuscript PDFs.
//
// The measurements do NOT come from a design proposal but from the reference
// PDF in `pdf/` — measured with pdftotext -bbox on one verso and one recto
// page. Changing them changes the match with the reference.
//
// The reference was set with XeTeX and TeX Gyre Pagella. macOS ships Palatino,
// metrically compatible with the same design — which is why the line breaks
// come close to the original without needing a TeX distribution.
//
// Called from `bookcli/pdf.py`; all values arrive as `sys.inputs`, so that
// `shared/book.json` stays the single source.

#let data = json(sys.inputs.at("data"))
#let typeset = data.typeset
#let work = data.work

#let mm(x) = x * 1mm

// ── Base layout ────────────────────────────────────────────────────────────
#set page(
  width: 170mm,
  height: 245mm,
  margin: (
    inside: mm(typeset.text_block.inner_mm),
    outside: mm(typeset.text_block.outer_mm),
    top: mm(typeset.text_block.top_mm),
    bottom: mm(typeset.text_block.bottom_mm),
  ),
  binding: left,
)

#set text(
  font: typeset.font,
  size: typeset.font_size_pt * 1pt,
  lang: "de",
  region: "DE",
  // Old-style figures: the reference sets the page numbers that way, and in
  // running text lining figures disturb the grey value.
  number-type: "old-style",
)

#set par(
  justify: true,
  leading: 0.76em,
  // First-line indent — but NOT in the first paragraph after a heading or a
  // section break. Typst can do that itself; the reference does the same.
  first-line-indent: (amount: 1.2em, all: false),
)

// German hyphenation; without it justified setting tears holes, and the
// reference hyphenates visibly („Handtü-chern", „sechsköp-fige").
#set par(spacing: 0.76em)
#show par: set block(spacing: 0.76em)

// ── Running head and page number ───────────────────────────────────────────
// verso (even) = book title, recto (odd) = chapter title, both italic.
// The first page of a chapter carries no running head.
#let chapter-state = state("chapter", "")
#let chapter-opening = state("chapter-opening", false)

#set page(
  header: context {
    if chapter-opening.get() { return }
    let n = counter(page).get().first()
    set text(size: 9pt, style: "italic")
    if calc.even(n) {
      align(left, work.title)
    } else {
      align(right, chapter-state.get())
    }
  },
  footer: context {
    if chapter-opening.get() { return }
    set text(size: 9.5pt)
    align(center, counter(page).display("1"))
  },
)

// ── Building blocks ────────────────────────────────────────────────────────
#let section-break() = {
  chapter-opening.update(false)
  v(1.1em)
  align(center, text(size: 11pt, typeset.section_break))
  v(1.1em)
}

#let chapter-page(number, title, subtitle) = {
  // Chapters start on the right (recto). `pagebreak(to: "odd")` inserts a blank
  // page if needed — exactly as in the reference PDF.
  pagebreak(to: "odd", weak: true)
  chapter-state.update(title)
  chapter-opening.update(true)
  v(2.2cm)
  text(size: 18pt)[#title]
  if subtitle != "" {
    linebreak()
    v(0.2em)
    text(size: 11pt, style: "italic")[#subtitle]
  }
  v(1.8cm)
  chapter-opening.update(false)
}

// ── Front matter ───────────────────────────────────────────────────────────
#set page(header: none, footer: none)
#v(5cm)
#align(center)[
  #text(size: 22pt)[#work.title]
  #v(0.4em)
  #text(size: 12pt, style: "italic")[#work.subtitle]
  #v(3cm)
  #text(size: 13pt)[#work.author]
  #v(3.5cm)
  #text(size: 10.5pt)[Manuskript · Entwurf]
  #v(0.6em)
  #text(size: 10.5pt)[#data.scope_text]
  #v(0.6em)
  #text(size: 10.5pt)[Stand: #data.as_of]
]

#pagebreak(to: "odd")
#v(2cm)
#text(size: 16pt)[Inhalt]
#v(1.2em)
#for c in data.chapters [
  #text(size: 11.5pt)[#c.number #h(0.8em) #c.title]
  #if c.subtitle != "" [
    #linebreak()
    #h(1.6em) #text(size: 10pt, style: "italic")[#c.subtitle]
  ]
  #v(1.1em)
]

// From here the page count starts — the front matter stays uncounted, as in the
// reference (page 1 is the first chapter page).
#counter(page).update(1)
#set page(
  header: context {
    if chapter-opening.get() { return }
    let n = counter(page).get().first()
    set text(size: 9pt, style: "italic")
    if calc.even(n) { align(left, work.title) } else { align(right, chapter-state.get()) }
  },
  footer: context {
    set text(size: 9.5pt)
    align(center, counter(page).display("1"))
  },
)

// ── The text ───────────────────────────────────────────────────────────────
#for c in data.chapters {
  chapter-page(c.number, c.title, c.subtitle)
  for (i, s) in c.sections.enumerate() {
    if i > 0 and s.break_before { section-break() }
    for paragraph in s.paragraphs {
      // parbreak() is mandatory: without it Typst joins consecutive content
      // blocks into ONE paragraph. The result was a wall of text with no
      // first-line indent — 56 pages instead of 70 at an identical word count,
      // so 25 percent too dense. The text block was never the problem.
      paragraph
      parbreak()
    }
  }
}
