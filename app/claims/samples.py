"""Fictional sample text PDFs, generated locally without an external service."""
from copy import deepcopy
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak

SAMPLE_NAMES = {'clean': 'Clean repair case', 'conflicting': 'Conflicting documents', 'missing': 'Missing information'}


def sample_pages(name: str):
    if name not in SAMPLE_NAMES:
        raise KeyError(name)
    docs = {
        'policy': [[
            'Document type: Policy', 'Policy ID: HOME-FIC-2026-001',
            'Policyholder: Alex Example (fictional)', 'Property address: 14 Example Lane, Sampletown',
            'Policy start: 2026-01-01', 'Policy end: 2026-12-31',
            'Fictional property-repair policy schedule. Dates are provided for consistency checks only.',
            'This demonstration omits policy wording, exclusions, excess and settlement rules.',
            'An incident within the stated dates does not establish insurance coverage.',
        ]],
        'claim': [[
            'Document type: Claim', 'Claim ID: CLM-FIC-1001', 'Policy ID: HOME-FIC-2026-001',
            'Claimant: Alex Example (fictional)', 'Property address: 14 Example Lane, Sampletown',
            'Incident date: 2026-06-10', 'Reported date: 2026-06-11', 'Claimed amount: EUR 595.00',
            'Damage description: Accidental breakage of a kitchen window; frame repair requested.',
            'Fictional declaration: this form is training data, not a real claim.',
        ]],
        'invoice': [[
            'Document type: Invoice', 'Invoice ID: INV-FIC-3001', 'Policy ID: HOME-FIC-2026-001',
            'Supplier: Example Window Repair Ltd (fictional)', 'Invoice date: 2026-06-15',
            'Item count: 2', 'Subtotal: EUR 500.00', 'Tax: EUR 95.00', 'Invoice total: EUR 595.00',
            'See page 2 for repair quantities and line totals.',
            'The stated tax amount is fictional; the workbench does not assess tax rates.',
        ], [
            'Document type: Invoice', 'Repair details - fictional kitchen window',
            'Item 1 description: Replacement glass', 'Item 1 quantity: 2',
            'Item 1 unit price: EUR 150.00', 'Item 1 line total: EUR 300.00',
            'Item 2 description: Frame repair labour', 'Item 2 quantity: 4',
            'Item 2 unit price: EUR 50.00', 'Item 2 line total: EUR 200.00',
        ]],
    }
    docs = deepcopy(docs)
    if name == 'conflicting':
        docs['claim'][0] = [s.replace('2026-06-10', '2025-12-31').replace('EUR 595.00', 'EUR 650.00') for s in docs['claim'][0]]
        docs['invoice'][0] = [s.replace('HOME-FIC-2026-001', 'HOME-FIC-2026-999') for s in docs['invoice'][0]]
        docs['invoice'][1] = [s.replace('Item 2 line total: EUR 200.00', 'Item 2 line total: EUR 190.00') for s in docs['invoice'][1]]
    if name == 'missing':
        del docs['invoice']
        docs['claim'][0] = [s for s in docs['claim'][0] if not s.startswith(('Incident date:', 'Damage description:'))]
    return docs


def render_pdf(role: str, pages: list[list[str]]) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=48, leftMargin=48, topMargin=86, bottomMargin=55,
                            title=f'FICTIONAL - {role.title()}', author='Claims Review Workbench', invariant=1)
    body = ParagraphStyle('body', fontName='Helvetica', fontSize=10, leading=16, textColor=colors.HexColor('#243447'), alignment=TA_LEFT)
    story = []
    for number, lines in enumerate(pages):
        if number:
            story.append(PageBreak())
        for line in lines:
            story.extend([Paragraph(escape(line), body), Spacer(1, 10)])

    def frame(canvas, document):
        canvas.setFillColor(colors.HexColor('#123047'))
        canvas.rect(0, A4[1] - 64, A4[0], 64, fill=1, stroke=0)
        canvas.setFillColor(colors.white)
        canvas.setFont('Helvetica-Bold', 17)
        canvas.drawString(48, A4[1] - 32, f'{role.title()} | property repair')
        canvas.setFont('Helvetica', 9)
        canvas.drawString(48, A4[1] - 49, 'FICTIONAL SAMPLE - for software demonstration only')
        canvas.setFillColor(colors.HexColor('#526577'))
        canvas.setFont('Helvetica', 8)
        canvas.drawString(48, 30, 'No real customer, policy or claim. Not an insurance decision.')
        canvas.drawRightString(A4[0] - 48, 30, f'Page {document.page}')

    doc.build(story, onFirstPage=frame, onLaterPages=frame)
    return buffer.getvalue()


def sample_files(name: str) -> dict[str, tuple[str, bytes]]:
    return {role: (f'fictional-{name}-{role}.pdf', render_pdf(role, pages)) for role, pages in sample_pages(name).items()}
