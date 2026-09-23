// Buchsatz für Manuskript-PDFs.
//
// Die Maße stammen NICHT aus einem Gestaltungsvorschlag, sondern aus dem
// Referenz-PDF in `pdf/` — ausgemessen mit pdftotext -bbox auf einer verso- und
// einer recto-Seite. Wer sie ändert, ändert den Abgleich mit der Referenz.
//
// Die Referenz wurde mit XeTeX und TeX Gyre Pagella gesetzt. macOS liefert
// Palatino, metrisch kompatibel mit demselben Entwurf — deshalb kommen die
// Umbrüche nahe an das Original, ohne dass eine TeX-Distribution nötig wäre.
//
// Aufgerufen aus `buchcli/pdf.py`; alle Werte kommen als `sys.inputs` herein,
// damit `shared/buch.json` die einzige Quelle bleibt.

#let daten = json(sys.inputs.at("daten"))
#let satz = daten.satz
#let werk = daten.werk

#let mm(x) = x * 1mm

// ── Grundlayout ────────────────────────────────────────────────────────────
#set page(
  width: 170mm,
  height: 245mm,
  margin: (
    inside: mm(satz.satzspiegel.innen_mm),
    outside: mm(satz.satzspiegel.aussen_mm),
    top: mm(satz.satzspiegel.oben_mm),
    bottom: mm(satz.satzspiegel.unten_mm),
  ),
  binding: left,
)

#set text(
  font: satz.schrift,
  size: satz.schriftgroesse_pt * 1pt,
  lang: "de",
  region: "DE",
  // Mediävalziffern: Die Referenz setzt die Seitenzahlen so, und im Fließtext
  // stören Versalziffern den Grauwert.
  number-type: "old-style",
)

#set par(
  justify: true,
  leading: 0.76em,
  // Erstzeileneinzug — aber NICHT im ersten Absatz nach einer Überschrift oder
  // einem Trenner. Typst kann das selbst; in der Referenz ist es genauso.
  first-line-indent: (amount: 1.2em, all: false),
)

// Deutsche Silbentrennung; ohne sie reißt der Blocksatz Löcher, und die
// Referenz trennt sichtbar („Handtü-chern", „sechsköp-fige").
#set par(spacing: 0.76em)
#show par: set block(spacing: 0.76em)

// ── Kolumnentitel und Seitenzahl ───────────────────────────────────────────
// verso (gerade) = Buchtitel, recto (ungerade) = Kapiteltitel, beide kursiv.
// Auf der ersten Seite eines Kapitels steht kein Kolumnentitel.
#let kapitel-state = state("kapitel", "")
#let kapitelanfang = state("kapitelanfang", false)

#set page(
  header: context {
    if kapitelanfang.get() { return }
    let n = counter(page).get().first()
    set text(size: 9pt, style: "italic")
    if calc.even(n) {
      align(left, werk.titel)
    } else {
      align(right, kapitel-state.get())
    }
  },
  footer: context {
    if kapitelanfang.get() { return }
    set text(size: 9.5pt)
    align(center, counter(page).display("1"))
  },
)

// ── Bausteine ──────────────────────────────────────────────────────────────
#let trenner() = {
  kapitelanfang.update(false)
  v(1.1em)
  align(center, text(size: 11pt, satz.abschnittstrenner))
  v(1.1em)
}

#let kapitelseite(nummer, titel, untertitel) = {
  // Kapitel beginnen rechts (recto). `pagebreak(to: "odd")` schiebt notfalls
  // eine Leerseite ein — genau wie im Referenz-PDF.
  pagebreak(to: "odd", weak: true)
  kapitel-state.update(titel)
  kapitelanfang.update(true)
  v(2.2cm)
  text(size: 18pt)[#titel]
  if untertitel != "" {
    linebreak()
    v(0.2em)
    text(size: 11pt, style: "italic")[#untertitel]
  }
  v(1.8cm)
  kapitelanfang.update(false)
}

// ── Titelei ────────────────────────────────────────────────────────────────
#set page(header: none, footer: none)
#v(5cm)
#align(center)[
  #text(size: 22pt)[#werk.titel]
  #v(0.4em)
  #text(size: 12pt, style: "italic")[#werk.untertitel]
  #v(3cm)
  #text(size: 13pt)[#werk.autor]
  #v(3.5cm)
  #text(size: 10.5pt)[Manuskript · Entwurf]
  #v(0.6em)
  #text(size: 10.5pt)[#daten.umfang_text]
  #v(0.6em)
  #text(size: 10.5pt)[Stand: #daten.stand]
]

#pagebreak(to: "odd")
#v(2cm)
#text(size: 16pt)[Inhalt]
#v(1.2em)
#for k in daten.kapitel [
  #text(size: 11.5pt)[#k.nummer #h(0.8em) #k.titel]
  #if k.untertitel != "" [
    #linebreak()
    #h(1.6em) #text(size: 10pt, style: "italic")[#k.untertitel]
  ]
  #v(1.1em)
]

// Ab hier zählt die Seitenzählung — die Titelei bleibt ungezählt, wie in der
// Referenz (Seite 1 ist die erste Kapitelseite).
#counter(page).update(1)
#set page(
  header: context {
    if kapitelanfang.get() { return }
    let n = counter(page).get().first()
    set text(size: 9pt, style: "italic")
    if calc.even(n) { align(left, werk.titel) } else { align(right, kapitel-state.get()) }
  },
  footer: context {
    set text(size: 9.5pt)
    align(center, counter(page).display("1"))
  },
)

// ── Der Text ───────────────────────────────────────────────────────────────
#for k in daten.kapitel {
  kapitelseite(k.nummer, k.titel, k.untertitel)
  for (i, a) in k.abschnitte.enumerate() {
    if i > 0 and a.trenner_davor { trenner() }
    for absatz in a.absaetze {
      // parbreak() ist zwingend: Ohne ihn verbindet Typst aufeinanderfolgende
      // Inhaltsblöcke zu EINEM Absatz. Das Ergebnis war eine Textwand ohne
      // Erstzeileneinzug — 56 Seiten statt 70 bei identischer Wortzahl, also
      // 25 Prozent zu dicht. Der Satzspiegel war nie das Problem.
      absatz
      parbreak()
    }
  }
}
