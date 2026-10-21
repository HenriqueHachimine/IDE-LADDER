/*
 * Gera relatorio.docx (ABNT NBR 14724) a partir de relatorio.md.
 *
 *   cd docs/report
 *   npm install docx@9      (uma vez; node_modules fica fora do Git)
 *   node build_docx.js
 *
 * Formatacao: A4; margens superior/esquerda 3 cm e inferior/direita 2 cm; Times New Roman 12;
 * espacamento 1,5; recuo de paragrafo 1,25 cm; secoes primarias em nova pagina (NBR 6024);
 * legendas, fontes e quadros em tamanho 10; referencias em espaco simples (NBR 6023);
 * paginas contadas a partir da folha de rosto e numeradas a partir da Introducao.
 * Ao abrir no Word, confirme "atualizar campos" para preencher o sumario e a lista de quadros.
 */
const fs = require("fs");
const path = require("path");
const {
  AlignmentType, BorderStyle, Document, Header, HeadingLevel, LevelFormat, Packer, PageNumber, Paragraph,
  SequentialIdentifier, ShadingType, Table, TableCell, TableOfContents, TableRow, TabStopType, TextRun, WidthType,
} = require("docx");

const SRC = path.join(__dirname, "relatorio.md");
const OUT = path.join(__dirname, "relatorio.docx");
const FONT = "Times New Roman";
const CM = 567;                                   // 1 cm em DXA
const PAGE = { width: 11906, height: 16838 };     // A4
const MARGIN = { top: 3 * CM, left: 3 * CM, bottom: 2 * CM, right: 2 * CM };
const TEXT_W = PAGE.width - MARGIN.left - MARGIN.right;
const LINE_15 = 360, LINE_1 = 240;

// ------------------------------------------------------------------ leitura
const md = fs.readFileSync(SRC, "utf8").replace(/<!--[\s\S]*?-->/g, "");
const lines = md.split(/\r?\n/);
const meta = {};
let title = "";
const blocks = [];          // {type, ...}
for (let i = 0; i < lines.length; i++) {
  const line = lines[i];
  const t = line.trim();
  if (!t) continue;
  let m;
  if ((m = /^# (.+)$/.exec(t))) { title = m[1]; continue; }
  if ((m = /^\*\*([^*]+):\*\*\s*(.*)$/.exec(t)) && !blocks.length) { meta[m[1]] = m[2]; continue; }
  if ((m = /^(#{2,4}) (.+)$/.exec(t))) { blocks.push({ type: "h", level: m[1].length - 1, text: m[2] }); continue; }
  if (t.startsWith("|")) {
    const rows = [];
    while (i < lines.length && lines[i].trim().startsWith("|")) {
      const cells = lines[i].trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
      if (!cells.every((c) => /^:?-+:?$/.test(c))) rows.push(cells);
      i++;
    }
    i--;
    blocks.push({ type: "table", rows });
    continue;
  }
  if (/^(- |\d+\. )/.test(t)) {
    const ordered = /^\d+\. /.test(t);
    const items = [];
    while (i < lines.length && /^(- |\d+\. )/.test(lines[i].trim())) {
      items.push(lines[i].trim().replace(/^(- |\d+\. )/, ""));
      i++;
    }
    i--;
    blocks.push({ type: "list", ordered, items });
    continue;
  }
  if ((m = /^Quadro (\d+) – (.+)$/.exec(t))) { blocks.push({ type: "caption", text: m[2] }); continue; }
  if (t.startsWith("Fonte:")) { blocks.push({ type: "source", text: t }); continue; }
  blocks.push({ type: "p", text: t });
}

// ------------------------------------------------------------------ texto
function runs(text, base = {}) {
  const out = [];
  const re = /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`|\[PREENCHER[^\]]*\])/g;
  let last = 0, m;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(new TextRun({ text: text.slice(last, m.index), ...base }));
    const tok = m[0];
    if (tok.startsWith("**")) out.push(new TextRun({ text: tok.slice(2, -2), bold: true, ...base }));
    else if (tok.startsWith("`")) out.push(new TextRun({ text: tok.slice(1, -1), font: "Courier New", ...base,
      size: (base.size || 24) - 2 }));
    else if (tok.startsWith("[")) out.push(new TextRun({ text: tok, highlight: "yellow", ...base }));
    else out.push(new TextRun({ text: tok.slice(1, -1), italics: true, ...base }));
    last = m.index + tok.length;
  }
  if (last < text.length) out.push(new TextRun({ text: text.slice(last), ...base }));
  return out;
}

const body = (text, opts = {}) => new Paragraph({
  children: runs(text), alignment: AlignmentType.JUSTIFIED,
  indent: { firstLine: Math.round(1.25 * CM) }, spacing: { line: LINE_15, after: 0 }, ...opts,
});
const centered = (text, opts = {}) => new Paragraph({
  children: runs(text, opts.run || {}), alignment: AlignmentType.CENTER, spacing: { line: LINE_15, ...(opts.spacing || {}) },
  ...(opts.pageBreakBefore ? { pageBreakBefore: true } : {}),
});

// elementos sem numero: pre-textuais fora do sumario; pos-textuais (referencias, apendices) no sumario
const PRE = ["RESUMO", "ABSTRACT", "LISTA DE QUADROS", "LISTA DE ABREVIATURAS E SIGLAS", "SUMÁRIO"];

function heading(b, first) {
  const numbered = /^\d/.test(b.text);
  if (b.level === 1 && !numbered) {
    if (PRE.includes(b.text)) {
      return new Paragraph({ children: [new TextRun({ text: b.text, bold: true })], alignment: AlignmentType.CENTER,
        spacing: { line: LINE_15, after: LINE_15 }, pageBreakBefore: !first });
    }
    return new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun({ text: b.text, bold: true })],
      alignment: AlignmentType.CENTER, pageBreakBefore: !first });
  }
  const level = [HeadingLevel.HEADING_1, HeadingLevel.HEADING_2, HeadingLevel.HEADING_3][b.level - 1];
  const text = b.level === 2 ? b.text.toUpperCase() : b.text;            // secundaria: maiusculas, sem negrito
  return new Paragraph({ heading: level, children: [new TextRun({ text, bold: b.level !== 2 })],
    pageBreakBefore: b.level === 1 && !first, keepNext: true });
}

let listInstance = 0;
function list(b) {
  listInstance++;
  return b.items.map((it) => new Paragraph({
    children: runs(it), alignment: AlignmentType.JUSTIFIED, spacing: { line: LINE_15 },
    numbering: { reference: b.ordered ? "numeros" : "alineas", level: 0, instance: listInstance },
  }));
}

function table(rows, bordered = true) {
  const cols = rows[0].length;
  const weights = [...Array(cols).keys()].map((c) =>
    Math.min(60, Math.max(8, ...rows.map((r) => (r[c] || "").replace(/[*`]/g, "").length))));
  const sum = weights.reduce((a, b) => a + b, 0);
  const widths = weights.map((w) => Math.floor((w / sum) * TEXT_W));
  widths[cols - 1] += TEXT_W - widths.reduce((a, b) => a + b, 0);
  const line = { style: BorderStyle.SINGLE, size: 4, color: "000000" };
  const borders = { top: line, bottom: line, left: line, right: line };
  return new Table({
    width: { size: TEXT_W, type: WidthType.DXA }, columnWidths: widths,
    rows: rows.map((r, ri) => new TableRow({
      tableHeader: ri === 0,
      children: r.map((cell, ci) => new TableCell({
        width: { size: widths[ci], type: WidthType.DXA }, borders: bordered ? borders : undefined,
        shading: ri === 0 ? { type: ShadingType.CLEAR, fill: "E7E6E6", color: "auto" } : undefined,
        margins: { top: 40, bottom: 40, left: 80, right: 80 },
        children: [new Paragraph({ children: runs(cell, { size: 20, bold: ri === 0 || undefined }),
          spacing: { line: LINE_1 } })],
      })),
    })),
  });
}

// lista de siglas: sigla e significado em uma linha, com tabulacao (sem bordas, como lista)
function acronyms(rows) {
  return rows.slice(1).map(([sigla, desc]) => new Paragraph({
    children: [new TextRun({ text: sigla }), new TextRun({ text: "\t" }), ...runs(desc)],
    tabStops: [{ type: TabStopType.LEFT, position: 2 * CM }], spacing: { line: LINE_15 },
  }));
}

// ------------------------------------------------------------------ elementos
const upper = (s) => (s || "").toUpperCase();
const capa = [
  centered(upper(meta["Instituição"]), { run: { bold: true } }),
  centered(upper(meta["Curso"]), { run: { bold: true } }),
  centered("", { spacing: { before: 2400 } }),
  centered(meta["Autores"] || ""),
  centered(upper(title), { run: { bold: true }, spacing: { before: 3600 } }),
  centered(meta["Local"] || "", { spacing: { before: 5200 } }),
  centered(meta["Ano"] || ""),
];
const natureza = `Relatório técnico apresentado à disciplina de ${meta["Disciplina"]} do curso de ` +
  `${meta["Curso"]} da ${meta["Instituição"]}, como requisito parcial para aprovação.`;
const rosto = [
  centered(meta["Autores"] || ""),
  centered(upper(title), { run: { bold: true }, spacing: { before: 3200 } }),
  new Paragraph({ children: runs(natureza), alignment: AlignmentType.JUSTIFIED, indent: { left: 8 * CM },
    spacing: { before: 1400, line: LINE_1 } }),
  new Paragraph({ children: runs(`Professor: ${meta["Professor"]}`), indent: { left: 8 * CM },
    spacing: { before: 240, line: LINE_1 } }),
  centered(meta["Local"] || "", { spacing: { before: 4000 } }),
  centered(meta["Ano"] || ""),
];

// divide os blocos: pre-textuais (ate o sumario) e textuais/pos-textuais
const pre = [], main = [];
let target = pre;
for (const b of blocks) {
  if (b.type === "h" && b.level === 1 && /^\d/.test(b.text)) target = main;
  target.push(b);
}

function render(list_, firstHeadingNoBreak) {
  const out = [];
  let first = firstHeadingNoBreak;
  let section = "";
  for (const b of list_) {
    if (b.type === "h") {
      out.push(heading(b, first));
      first = false;
      if (b.level === 1) section = b.text;
      if (section === "LISTA DE QUADROS") {
        out.push(new TableOfContents("Lista de quadros", { captionLabelIncludingNumbers: "Quadro", hyperlink: true }));
      }
      if (section === "SUMÁRIO") {
        out.push(new TableOfContents("Sumário", { hyperlink: true, headingStyleRange: "1-3" }));
      }
      continue;
    }
    if (b.type === "p") {
      if (section === "REFERÊNCIAS") {
        out.push(new Paragraph({ children: runs(b.text), alignment: AlignmentType.LEFT,
          spacing: { line: LINE_1, after: LINE_1 } }));
      } else if (b.text.startsWith("**Palavras-chave:**") || b.text.startsWith("**Keywords:**")) {
        out.push(new Paragraph({ children: runs(b.text), spacing: { before: LINE_15, line: LINE_15 } }));
      } else {
        out.push(body(b.text));
      }
    } else if (b.type === "list") {
      out.push(...list(b));
    } else if (b.type === "table") {
      out.push(...(section === "LISTA DE ABREVIATURAS E SIGLAS" ? acronyms(b.rows) : [table(b.rows)]));
    } else if (b.type === "caption") {
      out.push(new Paragraph({
        children: [new TextRun({ text: "Quadro ", size: 20 }), new SequentialIdentifier("Quadro"),
          new TextRun({ text: ` – ${b.text}`, size: 20 })],
        style: "Caption", alignment: AlignmentType.CENTER, keepNext: true, spacing: { before: 240, line: LINE_1 },
      }));
    } else if (b.type === "source") {
      out.push(new Paragraph({ children: runs(b.text, { size: 20 }), spacing: { after: 240, line: LINE_1 } }));
    }
  }
  return out;
}

const header = new Header({
  children: [new Paragraph({ alignment: AlignmentType.RIGHT,
    children: [new TextRun({ children: [PageNumber.CURRENT], size: 20 })] })],
});
const pageProps = (extra = {}) => ({ page: { size: PAGE, margin: MARGIN, ...extra } });

const doc = new Document({
  creator: meta["Autores"], title, features: { updateFields: true },
  styles: {
    default: { document: { run: { font: FONT, size: 24 }, paragraph: { spacing: { line: LINE_15 } } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { font: FONT, size: 24, bold: true, color: "000000" },
        paragraph: { spacing: { before: 0, after: LINE_15, line: LINE_15 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { font: FONT, size: 24, bold: false, color: "000000" },
        paragraph: { spacing: { before: LINE_15, after: LINE_15, line: LINE_15 }, outlineLevel: 1 } },
      { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { font: FONT, size: 24, bold: true, color: "000000" },
        paragraph: { spacing: { before: LINE_15, after: LINE_15, line: LINE_15 }, outlineLevel: 2 } },
      { id: "Caption", name: "Caption", basedOn: "Normal", next: "Normal",
        run: { font: FONT, size: 20, color: "000000" } },
    ],
  },
  numbering: {
    config: [
      { reference: "alineas", levels: [{ level: 0, format: LevelFormat.LOWER_LETTER, text: "%1)",
        alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 1134, hanging: 425 } } } }] },
      { reference: "numeros", levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.",
        alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 1134, hanging: 425 } } } }] },
    ],
  },
  sections: [
    { properties: pageProps(), children: capa },                                   // capa: nao contada
    { properties: { ...pageProps(), page: { size: PAGE, margin: MARGIN, pageNumbers: { start: 1 } } },
      children: [...rosto, ...render(pre, false)] },                              // contadas, sem numero
    { properties: pageProps(), headers: { default: header }, children: render(main, true) },
  ],
});

Packer.toBuffer(doc).then((buf) => {
  fs.writeFileSync(OUT, buf);
  console.log(`gerado: ${OUT} (${blocks.length} blocos)`);
});
