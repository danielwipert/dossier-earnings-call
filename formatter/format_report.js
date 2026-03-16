/**
 * Chorus AI Systems — Earnings Call Intelligence
 * Report Formatter v2.0 — Magazine-style layout
 *
 * Called by report_formatter.py — not run directly.
 * Usage: node format_report.js <report_json_path> <chart_png_path> <output_docx_path>
 */

const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  ImageRun, AlignmentType, BorderStyle, WidthType, ShadingType,
  VerticalAlign, PageBreak
} = require('docx');
const fs = require('fs');

// =============================================================================
// DESIGN TOKENS
// =============================================================================
const NAVY        = "1A2E4A";   // deep navy — primary brand
const GOLD        = "C9A84C";   // warm gold — accent
const GOLD_LIGHT  = "FEF9EC";   // gold tint — first takeaway bg
const CHARCOAL    = "1F2937";   // near-black body text
const DARK_GRAY   = "374151";   // secondary text
const MID_GRAY    = "6B7280";   // labels, captions
const LIGHT_BG    = "F3F4F6";   // alternating row bg
const BORDER      = "E5E7EB";   // subtle borders
const GREEN       = "15803D";   // positive signal
const GREEN_BG    = "DCFCE7";   // green card bg
const RED         = "B91C1C";   // negative / watch
const RED_BG      = "FEE2E2";   // red card bg
const AMBER       = "B45309";   // mid-range score
const AMBER_BG    = "FEF3C7";   // amber card bg
const WHITE       = "FFFFFF";
const NAVY_FAINT  = "9CB3D4";   // faint navy for masthead subtext

const CONTENT_WIDTH = 9360;     // DXA — US Letter minus 1" margins

// =============================================================================
// UTILITIES
// =============================================================================

// Strip inline fact citations: [F001], [F001, F002], (F001), (F001, F002)
function stripCitations(text) {
  if (!text) return "";
  return text
    .replace(/\[F\d{3}(?:,\s*F\d{3})*\]/g, "")
    .replace(/\(F\d{3}(?:,\s*F\d{3})*\)/g, "")
    .replace(/\s{2,}/g, " ")
    .trim();
}

// Return score background fill based on value
function scoreColor(score) {
  if (score >= 7) return GREEN_BG;
  if (score >= 5) return AMBER_BG;
  return RED_BG;
}

// Return score text color based on value
function scoreTextColor(score) {
  if (score >= 7) return GREEN;
  if (score >= 5) return AMBER;
  return RED;
}

// =============================================================================
// ELEMENT BUILDERS
// =============================================================================

function run(text, opts = {}) {
  return new TextRun({
    text: text || "",
    font: opts.font || "Calibri",
    size: opts.size || 22,
    bold: opts.bold || false,
    italics: opts.italics || false,
    color: opts.color || CHARCOAL,
    break: opts.break || undefined,
  });
}

function para(children, opts = {}) {
  return new Paragraph({
    alignment: opts.align || AlignmentType.LEFT,
    spacing: {
      before: opts.spaceBefore || 0,
      after: opts.spaceAfter !== undefined ? opts.spaceAfter : 100,
      line: opts.lineSpacing || undefined,
    },
    children: Array.isArray(children) ? children : [children],
    border: opts.border || undefined,
    indent: opts.indent || undefined,
  });
}

function spacer(pts = 6) {
  return new Paragraph({
    children: [new TextRun({ text: "", size: pts * 2 })],
    spacing: { before: 0, after: 0 },
  });
}

function divider(color = BORDER, thickness = 8) {
  return new Paragraph({
    children: [new TextRun({ text: "" })],
    border: { bottom: { style: BorderStyle.SINGLE, size: thickness, color, space: 1 } },
    spacing: { before: 80, after: 80 },
  });
}

function cell(children, opts = {}) {
  const none  = { style: BorderStyle.NONE };
  const line  = (c) => ({ style: BorderStyle.SINGLE, size: 2, color: c || opts.borderColor || BORDER });
  const borders = opts.noBorder
    ? { top: none, bottom: none, left: none, right: none }
    : { top: line(), bottom: line(), left: line(), right: line() };

  return new TableCell({
    borders,
    width: opts.width ? { size: opts.width, type: WidthType.DXA } : undefined,
    shading: opts.fill ? { fill: opts.fill, type: ShadingType.CLEAR } : undefined,
    verticalAlign: opts.vAlign || VerticalAlign.CENTER,
    margins: {
      top:    opts.padV  !== undefined ? opts.padV  : 120,
      bottom: opts.padV  !== undefined ? opts.padV  : 120,
      left:   opts.padH  !== undefined ? opts.padH  : 160,
      right:  opts.padH  !== undefined ? opts.padH  : 160,
    },
    columnSpan: opts.span || 1,
    children: Array.isArray(children) ? children : [children],
  });
}

// =============================================================================
// BLOCK: MASTHEAD / COVER BAND
// =============================================================================
function buildHeader(snapshot) {
  const company = (snapshot.company_name || "").toUpperCase();
  const ticker  = snapshot.ticker || "";
  const quarter = snapshot.quarter || "";

  return [
    // Dark navy masthead band
    new Table({
      width: { size: CONTENT_WIDTH, type: WidthType.DXA },
      columnWidths: [CONTENT_WIDTH],
      rows: [new TableRow({ children: [
        cell([
          para(run("CHORUS AI  ·  EARNINGS CALL INTELLIGENCE", {
            bold: true, size: 17, color: NAVY_FAINT, font: "Arial",
          }), { align: AlignmentType.CENTER, spaceAfter: 60 }),
          para(run(company, {
            bold: true, size: 60, color: WHITE, font: "Arial",
          }), { align: AlignmentType.CENTER, spaceAfter: 60 }),
          para([
            run(ticker, { size: 22, color: NAVY_FAINT, font: "Arial" }),
            run("   ·   ", { size: 22, color: NAVY_FAINT }),
            run(quarter + " Earnings Call", { size: 22, color: NAVY_FAINT, font: "Arial" }),
          ], { align: AlignmentType.CENTER }),
        ], { fill: NAVY, noBorder: true, padV: 220, padH: 280 }),
      ]})]
    }),

    spacer(4),

    // Gold accent rule
    new Paragraph({
      children: [new TextRun({ text: "" })],
      border: { bottom: { style: BorderStyle.SINGLE, size: 20, color: GOLD, space: 1 } },
      spacing: { before: 0, after: 100 },
    }),

    spacer(4),
  ];
}

// =============================================================================
// BLOCK: HEADLINE + VERIFICATION BADGE
// =============================================================================
function buildHeadline(snapshot, verificationSummary) {
  const headline = stripCitations(snapshot.headline || "");

  return [
    new Paragraph({
      children: [new TextRun({
        text: headline,
        font: "Georgia",
        size: 36,
        bold: true,
        color: CHARCOAL,
      })],
      spacing: { before: 100, after: 80 },
    }),

    para([
      run("✓ AI-Verified  ", { size: 18, bold: true, color: GREEN, font: "Arial" }),
      run(
        `${verificationSummary.avg_grounding} source grounding  ·  ` +
        `${verificationSummary.contradictions} contradictions  ·  ` +
        `Model agreement: ${verificationSummary.model_agreement}`,
        { size: 18, color: MID_GRAY, font: "Arial" }
      ),
    ], { spaceAfter: 180 }),

    divider(BORDER, 6),
    spacer(6),
  ];
}

// =============================================================================
// BLOCK: KEY METRICS CARDS
// =============================================================================
function buildMetricCards(snapshot) {
  const financials = (snapshot.key_financials || []).slice(0, 4);
  if (financials.length === 0) return [];

  const elements = [];

  elements.push(
    para(run("BY THE NUMBERS", { bold: true, size: 17, color: MID_GRAY, font: "Arial" }),
         { spaceAfter: 80 })
  );

  const cardW = Math.floor(CONTENT_WIDTH / financials.length);

  const cardCells = financials.map((m, i) => {
    const value = m.reported_value || "—";
    const label = m.metric_name || "";
    const delta = m.yoy_change || "";
    const vs    = m.vs_estimate || "";

    const shortLabel = label.length > 32 ? label.substring(0, 30) + "…" : label;
    let deltaColor = MID_GRAY;
    if (delta.startsWith("+")) deltaColor = GREEN;
    else if (delta.startsWith("-")) deltaColor = RED;

    const cardFill = i % 2 === 0 ? LIGHT_BG : WHITE;

    return cell([
      para(run(shortLabel, { size: 16, color: MID_GRAY, font: "Arial" }),
           { align: AlignmentType.CENTER, spaceAfter: 40 }),
      para(run(value, { bold: true, size: 44, color: NAVY, font: "Arial" }),
           { align: AlignmentType.CENTER, spaceAfter: 20 }),
      delta
        ? para(run(delta, { bold: true, size: 20, color: deltaColor, font: "Arial" }),
               { align: AlignmentType.CENTER, spaceAfter: 20 })
        : spacer(0),
      vs
        ? para(run(vs, { size: 16, italics: true, color: MID_GRAY }),
               { align: AlignmentType.CENTER, spaceAfter: 0 })
        : spacer(0),
    ], { width: cardW, fill: cardFill, borderColor: BORDER, padV: 180, padH: 100 });
  });

  elements.push(new Table({
    width: { size: CONTENT_WIDTH, type: WidthType.DXA },
    columnWidths: financials.map(() => cardW),
    rows: [new TableRow({ children: cardCells })],
  }));

  elements.push(spacer(12));
  return elements;
}

// =============================================================================
// BLOCK: THREE TAKEAWAYS
// =============================================================================
function buildTakeaways(snapshot) {
  const takeaways = (snapshot.key_takeaways || []);
  if (takeaways.length === 0) return [];

  const elements = [];
  elements.push(spacer(4));
  elements.push(
    para(run("THE STORY IN THREE POINTS", { bold: true, size: 17, color: MID_GRAY, font: "Arial" }),
         { spaceAfter: 100 })
  );

  const numW  = 520;
  const textW = CONTENT_WIDTH - numW;

  takeaways.forEach((t, i) => {
    const text = stripCitations(t.text || "");
    const num  = String(t.number || i + 1);

    // Try to split into bold lead sentence + body
    const match = text.match(/^(.*?[.!?])\s+([\s\S]+)$/);
    const lead  = match ? match[1] : text;
    const body  = match ? match[2] : "";

    const cardFill = i === 0 ? GOLD_LIGHT : WHITE;
    const cardBorder = i === 0 ? GOLD : BORDER;

    const numberCell = cell(
      para(run(num, { bold: true, size: 52, color: WHITE, font: "Arial" }),
           { align: AlignmentType.CENTER, spaceAfter: 0 }),
      { width: numW, fill: NAVY, noBorder: true, padV: 180, padH: 80, vAlign: VerticalAlign.CENTER }
    );

    const textContent = [
      para(run(lead, { bold: true, size: 23, color: CHARCOAL, font: "Calibri" }),
           { spaceAfter: body ? 60 : 0 }),
    ];
    if (body) {
      textContent.push(
        para(run(body, { size: 21, color: DARK_GRAY, font: "Calibri" }),
             { spaceAfter: 0 })
      );
    }

    const textCell = cell(textContent, {
      width: textW,
      fill: cardFill,
      borderColor: cardBorder,
      padV: 160, padH: 200,
      vAlign: VerticalAlign.CENTER,
    });

    elements.push(new Table({
      width: { size: CONTENT_WIDTH, type: WidthType.DXA },
      columnWidths: [numW, textW],
      rows: [new TableRow({ children: [numberCell, textCell] })],
    }));
    elements.push(spacer(5));
  });

  elements.push(spacer(8));
  elements.push(divider(BORDER, 6));
  elements.push(spacer(8));
  return elements;
}

// =============================================================================
// BLOCK: SIGNALS AT A GLANCE
// =============================================================================
function buildSignals(sections) {
  const elements = [];

  elements.push(
    para(run("SIGNALS AT A GLANCE", { bold: true, size: 17, color: MID_GRAY, font: "Arial" }),
         { spaceAfter: 80 })
  );

  const greenItems = [];
  const redItems   = [];

  if (sections.S2b) {
    sections.S2b.claims
      .filter(c => c.claim_type === "grounded" || c.claim_type === "derived")
      .slice(0, 4)
      .forEach(c => greenItems.push(stripCitations(c.claim_text)));
  }
  if (sections.S2c) {
    sections.S2c.claims
      .slice(0, 4)
      .forEach(c => redItems.push(stripCitations(c.claim_text)));
  }

  const maxRows = Math.max(greenItems.length, redItems.length, 1);
  const colW = Math.floor(CONTENT_WIDTH / 2);

  const headerRow = new TableRow({ children: [
    cell(
      para(run("  ▲  GREEN FLAGS", { bold: true, size: 21, color: WHITE, font: "Arial" })),
      { width: colW, fill: "166534", noBorder: true, padV: 100 }
    ),
    cell(
      para(run("  ▼  WATCH POINTS", { bold: true, size: 21, color: WHITE, font: "Arial" })),
      { width: colW, fill: "991B1B", noBorder: true, padV: 100 }
    ),
  ]});

  const dataRows = Array.from({ length: maxRows }, (_, i) => {
    const green = greenItems[i] || "";
    const red   = redItems[i]   || "";
    const rowBg = i % 2 === 0;

    return new TableRow({ children: [
      cell(
        green
          ? para([run("  ", { size: 20 }), run(green, { size: 20, color: CHARCOAL })], { spaceAfter: 0 })
          : para(run("", { size: 20 }), { spaceAfter: 0 }),
        { width: colW, fill: rowBg ? GREEN_BG : WHITE, borderColor: BORDER, padV: 100 }
      ),
      cell(
        red
          ? para([run("  ", { size: 20 }), run(red, { size: 20, color: CHARCOAL })], { spaceAfter: 0 })
          : para(run("", { size: 20 }), { spaceAfter: 0 }),
        { width: colW, fill: rowBg ? RED_BG : WHITE, borderColor: BORDER, padV: 100 }
      ),
    ]});
  });

  elements.push(new Table({
    width: { size: CONTENT_WIDTH, type: WidthType.DXA },
    columnWidths: [colW, colW],
    rows: [headerRow, ...dataRows],
  }));

  elements.push(spacer(12));
  return elements;
}

// =============================================================================
// BLOCK: SCORECARD (radar chart + color-coded score table)
// =============================================================================
function buildScorecard(radarScores, chartPngPath) {
  const elements = [];

  elements.push(divider(BORDER, 6));
  elements.push(spacer(8));
  elements.push(
    para(run("SCORECARD", { bold: true, size: 17, color: MID_GRAY, font: "Arial" }),
         { spaceAfter: 80 })
  );

  // Radar chart
  try {
    const imageBuffer = fs.readFileSync(chartPngPath);
    elements.push(new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 0, after: 160 },
      children: [new ImageRun({
        data: imageBuffer,
        transformation: { width: 380, height: 380 },
        type: "png",
      })],
    }));
  } catch {
    elements.push(para(run("[Radar chart unavailable]", { italics: true, color: MID_GRAY })));
  }

  if (radarScores && radarScores.dimension_scores) {
    const DISPLAY_NAMES = {
      revenue_momentum:    "Revenue Momentum",
      margin_health:       "Margin Health",
      guidance_confidence: "Guidance Confidence",
      mgmt_transparency:   "Mgmt Transparency",
      strategic_clarity:   "Strategic Clarity",
      earnings_quality:    "Earnings Quality",
      forward_visibility:  "Forward Visibility",
    };

    const labelW = 2400;
    const scoreW = 720;
    const noteW  = CONTENT_WIDTH - labelW - scoreW;

    const headerRow = new TableRow({ children: [
      cell(para(run("DIMENSION", { bold: true, size: 18, color: WHITE, font: "Arial" })),
           { width: labelW, fill: NAVY, noBorder: true }),
      cell(para(run("SCORE", { bold: true, size: 18, color: WHITE, font: "Arial" }),
               { align: AlignmentType.CENTER }),
           { width: scoreW, fill: NAVY, noBorder: true }),
      cell(para(run("RATIONALE", { bold: true, size: 18, color: WHITE, font: "Arial" })),
           { width: noteW, fill: NAVY, noBorder: true }),
    ]});

    const dataRows = radarScores.dimension_scores.map((d, i) => {
      const name      = DISPLAY_NAMES[d.dimension] || d.dimension;
      const score     = d.published_score;
      const rationale = (d.scoring_rationale || "").substring(0, 160);
      const rowFill   = i % 2 === 0 ? WHITE : LIGHT_BG;

      return new TableRow({ children: [
        cell(para(run(name, { bold: true, size: 21, font: "Calibri" })),
             { width: labelW, fill: rowFill, borderColor: BORDER }),
        cell(para(run(String(score), { bold: true, size: 30, color: scoreTextColor(score), font: "Arial" }),
                  { align: AlignmentType.CENTER }),
             { width: scoreW, fill: scoreColor(score), borderColor: BORDER }),
        cell(para(run(rationale, { size: 19, italics: true, color: DARK_GRAY })),
             { width: noteW, fill: rowFill, borderColor: BORDER }),
      ]});
    });

    elements.push(new Table({
      width: { size: CONTENT_WIDTH, type: WidthType.DXA },
      columnWidths: [labelW, scoreW, noteW],
      rows: [headerRow, ...dataRows],
    }));
  }

  elements.push(spacer(12));
  return elements;
}

// =============================================================================
// BLOCK: NARRATIVE DEEP DIVE
// =============================================================================
function buildNarrative(sections) {
  const elements = [];

  const SECTION_META = [
    { id: "S2a", label: "THE QUARTER IN CONTEXT" },
    { id: "S2b", label: "WHAT MANAGEMENT IS SIGNALING" },
    { id: "S2c", label: "WHAT WASN'T SAID" },
    { id: "S2d", label: "THE BIGGER PICTURE" },
  ];

  SECTION_META.forEach(({ id, label }) => {
    elements.push(spacer(4));
    elements.push(divider(BORDER, 6));
    elements.push(spacer(4));

    // Section label band
    elements.push(new Table({
      width: { size: CONTENT_WIDTH, type: WidthType.DXA },
      columnWidths: [CONTENT_WIDTH],
      rows: [new TableRow({ children: [
        cell(
          para(run(label, { bold: true, size: 20, color: WHITE, font: "Arial" })),
          { fill: NAVY, noBorder: true, padV: 100, padH: 200 }
        ),
      ]})]
    }));

    const section = sections[id];
    if (!section) {
      elements.push(spacer(6));
      elements.push(para(run(
        "[This section was omitted — verification could not be completed after maximum retries.]",
        { italics: true, size: 20, color: MID_GRAY }
      ), { spaceBefore: 80, spaceAfter: 160 }));
      return;
    }

    elements.push(spacer(10));

    const narrative = stripCitations(section.narrative || "");
    const paragraphs = narrative.split(/\n\n+/);
    let isFirst = true;

    paragraphs.forEach(p => {
      p = p.trim();
      if (!p) return;

      // Standalone subheading: **text**
      if (p.startsWith("**") && p.endsWith("**")) {
        elements.push(
          para(run(p.replace(/\*\*/g, ""), { bold: true, size: 22, color: NAVY, font: "Calibri" }),
               { spaceBefore: 200, spaceAfter: 80 })
        );
        return;
      }

      // First paragraph → pullquote with gold left rule
      if (isFirst) {
        isFirst = false;
        elements.push(new Paragraph({
          children: [new TextRun({
            text: p.replace(/\*\*/g, ""),
            font: "Georgia",
            size: 25,
            italics: true,
            color: NAVY,
          })],
          spacing: { before: 100, after: 180, line: 320 },
          indent: { left: 500, right: 300 },
          border: {
            left: { style: BorderStyle.SINGLE, size: 28, color: GOLD, space: 14 },
          },
        }));
        return;
      }

      // Blockquote: lines starting with ">"
      if (p.startsWith(">")) {
        elements.push(new Paragraph({
          children: [new TextRun({
            text: p.replace(/^>\s*/, "").replace(/\*\*/g, ""),
            font: "Georgia",
            size: 21,
            italics: true,
            color: MID_GRAY,
          })],
          spacing: { before: 120, after: 120 },
          indent: { left: 720, right: 360 },
          border: { left: { style: BorderStyle.SINGLE, size: 12, color: BORDER, space: 8 } },
        }));
        return;
      }

      // Normal paragraph — parse inline **bold**
      const parts = p.split(/(\*\*[^*]+\*\*)/g);
      const runs = parts.map(part => {
        if (part.startsWith("**") && part.endsWith("**")) {
          return new TextRun({ text: part.replace(/\*\*/g, ""), font: "Calibri", size: 22, bold: true, color: CHARCOAL });
        }
        return new TextRun({ text: part, font: "Calibri", size: 22, color: CHARCOAL });
      });

      elements.push(new Paragraph({
        children: runs,
        spacing: { before: 0, after: 160, line: 280 },
      }));
    });

    elements.push(spacer(8));
  });

  return elements;
}

// =============================================================================
// BLOCK: VERIFICATION APPENDIX
// =============================================================================
function buildVerification(verification, radarScores) {
  const elements = [];

  elements.push(new Paragraph({ children: [new PageBreak()] }));

  elements.push(new Table({
    width: { size: CONTENT_WIDTH, type: WidthType.DXA },
    columnWidths: [CONTENT_WIDTH],
    rows: [new TableRow({ children: [
      cell(
        para(run("VERIFICATION REPORT", { bold: true, size: 20, color: WHITE, font: "Arial" })),
        { fill: CHARCOAL, noBorder: true, padV: 120, padH: 200 }
      ),
    ]})]
  }));

  elements.push(spacer(8));
  elements.push(para(run(
    "Every factual claim in this report was independently verified against the source transcript " +
    "by a separate AI model. This appendix documents the verification process and its findings.",
    { size: 20, italics: true, color: MID_GRAY }
  ), { spaceAfter: 160 }));

  // Grounding scores by section
  if (verification && verification.source_grounding_scores) {
    elements.push(para(run("Source Grounding by Section", { bold: true, size: 22, color: CHARCOAL }),
                       { spaceAfter: 80 }));
    const entries = Object.entries(verification.source_grounding_scores);
    const colW = Math.floor(CONTENT_WIDTH / Math.max(entries.length, 1));

    elements.push(new Table({
      width: { size: CONTENT_WIDTH, type: WidthType.DXA },
      columnWidths: entries.map(() => colW),
      rows: [
        new TableRow({ children: entries.map(([sec]) =>
          cell(para(run(sec, { bold: true, size: 20, color: WHITE, font: "Arial" }),
                    { align: AlignmentType.CENTER }),
               { width: colW, fill: NAVY, noBorder: true })
        )}),
        new TableRow({ children: entries.map(([, score]) =>
          cell(para(run(`${(score * 100).toFixed(0)}%`, { bold: true, size: 30, color: GREEN }),
                    { align: AlignmentType.CENTER }),
               { width: colW })
        )}),
      ],
    }));
    elements.push(spacer(12));
  }

  // Contradiction count
  const totalContradictions = Object.values((verification || {}).contradiction_counts || {})
    .reduce((a, b) => a + b, 0);
  elements.push(para([
    run("Contradiction Check: ", { bold: true, size: 22 }),
    run(
      totalContradictions === 0
        ? "✓ 0 contradictions detected"
        : `✗ ${totalContradictions} contradictions found`,
      { size: 22, color: totalContradictions === 0 ? GREEN : RED }
    ),
  ], { spaceAfter: 120 }));

  // Scoring disagreements
  if (radarScores && radarScores.dimension_scores) {
    const disagreements = radarScores.dimension_scores.filter(d => !d.models_agreed);
    if (disagreements.length > 0) {
      elements.push(para(run("Scoring Disagreements", { bold: true, size: 22, color: CHARCOAL }),
                         { spaceBefore: 120, spaceAfter: 80 }));
      disagreements.forEach(d => {
        elements.push(para(run(`• ${d.dimension}: ${d.disagreement_note || ""}`,
                               { size: 20, italics: true }),
                           { spaceAfter: 80 }));
      });
    }
  }

  // S5 advisory flags
  const s5 = (verification || {}).s5_issues || {};
  const allFlags = [
    ...(s5.cross_section_issues || []),
    ...(s5.labeling_issues || []),
    ...(s5.framing_concerns || []),
  ];
  if (allFlags.length > 0) {
    elements.push(para(run("Advisory Flags", { bold: true, size: 22, color: CHARCOAL }),
                       { spaceBefore: 120, spaceAfter: 80 }));
    allFlags.forEach(issue => {
      const text = issue.issue_description || issue.concern_description || JSON.stringify(issue);
      elements.push(para(run(`• ${text}`, { size: 20, italics: true }), { spaceAfter: 80 }));
    });
  }

  // Verification limitations (always shown — Principle 13)
  if (verification && verification.verification_limitations) {
    elements.push(para(run("Verification Limitations", { bold: true, size: 22, color: CHARCOAL }),
                       { spaceBefore: 160, spaceAfter: 80 }));
    elements.push(para(run(verification.verification_limitations,
                            { size: 19, italics: true, color: MID_GRAY }),
                       { spaceAfter: 120 }));
  }

  elements.push(spacer(16));
  elements.push(divider(BORDER, 6));
  elements.push(para(
    run("Produced by Chorus AI Systems  ·  Multi-model verification pipeline with source grounding",
        { size: 17, italics: true, color: MID_GRAY }),
    { align: AlignmentType.CENTER, spaceBefore: 120 }
  ));

  return elements;
}

// =============================================================================
// MAIN
// =============================================================================
async function main() {
  const args = process.argv.slice(2);
  if (args.length < 3) {
    console.error("Usage: node format_report.js <report_json> <chart_png> <output_docx>");
    process.exit(1);
  }

  const [reportJsonPath, chartPngPath, outputDocxPath] = args;
  const reportData = JSON.parse(fs.readFileSync(reportJsonPath, 'utf8'));
  const { snapshot, sections, radar_scores, verification } = reportData;

  // Build verification summary for header badge
  const groundingVals = verification && verification.source_grounding_scores
    ? Object.values(verification.source_grounding_scores) : [];
  const avgGrounding = groundingVals.length
    ? groundingVals.reduce((a, b) => a + b, 0) / groundingVals.length : null;

  const verificationSummary = {
    avg_grounding: avgGrounding ? `${(avgGrounding * 100).toFixed(0)}%` : "—",
    contradictions: verification
      ? Object.values(verification.contradiction_counts || {}).reduce((a, b) => a + b, 0) : "—",
    model_agreement: (radar_scores && radar_scores.dimension_scores &&
      radar_scores.dimension_scores.every(d => d.models_agreed)) ? "High" : "Partial",
  };

  const children = [
    ...buildHeader(snapshot),
    ...buildHeadline(snapshot, verificationSummary),
    ...buildMetricCards(snapshot),
    ...buildTakeaways(snapshot),
    ...buildSignals(sections),
    ...buildScorecard(radar_scores, chartPngPath),
    ...buildNarrative(sections),
    ...buildVerification(verification, radar_scores),
  ];

  const doc = new Document({
    styles: {
      default: {
        document: { run: { font: "Calibri", size: 22 } },
      },
    },
    sections: [{
      properties: {
        page: {
          size: { width: 12240, height: 15840 },
          margin: { top: 1080, right: 1080, bottom: 1080, left: 1080 },
        },
      },
      children,
    }],
  });

  const buffer = await Packer.toBuffer(doc);
  fs.writeFileSync(outputDocxPath, buffer);
  console.log(`Report saved: ${outputDocxPath}`);
}

main().catch(err => { console.error(err); process.exit(1); });
