import unittest
from mavis.illustrate.constants import DiagramSettings
from mavis.illustrate.scatter import ScatterPlot
from mavis.illustrate.diagram import *
from mavis.illustrate.elements import draw_template, draw_ustranscript, draw_genes
from mavis.annotate import *
from svgwrite import Drawing
from mavis.constants import STRAND, ORIENT, SVTYPE, PROTOCOL
from mavis.breakpoint import Breakpoint, BreakpointPair
from mavis.interval import Interval
from . import MockSeq, MockString, build_transcript, TEMPLATE_METADATA_FILE, OUTPUT_SVG
import random

TEMPLATE_METADATA = None


def setUpModule():
    global TEMPLATE_METADATA
    TEMPLATE_METADATA = load_templates(TEMPLATE_METADATA_FILE)


class TestDraw(unittest.TestCase):
    def setUp(self):
        self.canvas = Drawing(height=100, width=1000)

    def test_generate_interval_mapping_outside_range_error(self):
        temp = [
            Interval(48556470, 48556646),
            Interval(48573290, 48573665),
            Interval(48575056, 48575078)
        ]
        mapping = generate_interval_mapping(
            input_intervals=temp,
            target_width=431.39453125,
            ratio=20,
            min_width=14,
            buffer_length=None,
            end=None,
            start=None,
            min_inter_width=10
        )
        st = min([x.start for x in temp])
        end = min([x.end for x in temp])
        Interval.convert_pos(mapping, st)
        Interval.convert_pos(mapping, end)

    def test_generate_gene_mapping(self):
        d = DiagramSettings()
        a = Gene('1', 1000, 2000)
        b = Gene('1', 5000, 7000)
        c = Gene('1', 1500, 2500)
        genes = [a, b, c]
        """return self.generate_interval_mapping(
            target_width,
            genes,
            self.GENE_INTERGENIC_RATIO,
            self.MIN_WIDTH + self.GENE_ARROW_WIDTH,
            buffer=self.GENE_MIN_BUFFER
        )
        with self.assertRaises(AttributeError):
            m = d._generate_gene_mapping(100, genes)
        m = d._generate_gene_mapping(500, genes)
        u = Interval.union(*m.values())
        self.assertLessEqual(1, u.start)
        self.assertGreaterEqual(500, u.end)"""

    def test_generate_gene_mapping_err(self):
        #  _generate_interval_mapping [IntergenicRegion(11:77361962_77361962+)] 1181.39453125 5 30 None 77356962 77366962)
        ir = IntergenicRegion('11', 5000, 5000, STRAND.POS)
        tgt_width = 1000
        d = DiagramSettings()
        d.gene_min_buffer = 10
        # (self, canvas, gene, width, height, fill, label='', REFERENCE_GENOME=None)
        draw_genes(d, self.canvas, [ir], tgt_width, [])

        # _generate_interval_mapping ['Interval(29684391, 29684391)', 'Interval(29663998, 29696515)'] 1181.39453125 5 60 None 29662998 29697515
        # def generate_interval_mapping(cls, input_intervals, target_width, ratio, min_width, buffer_length=None, start=None, end=None, min_inter_width=None)
        itvls = [Interval(29684391, 29684391), Interval(29663998, 29696515)]
        mapping = generate_interval_mapping(itvls, 1181.39, 5, 60, None, 29662998, 29697515)

    def test_split_intervals_into_tracks(self):
        # ----======---------
        # ------======--------
        # -----===============
        t = split_intervals_into_tracks(
            [(1, 3), (3, 7), (2, 2), (4, 5), (3, 10)]
        )
        self.assertEqual(3, len(t))
        self.assertEqual([(1, 3), (4, 5)], t[0])
        self.assertEqual([(2, 2), (3, 7)], t[1])
        self.assertEqual([(3, 10)], t[2])

    def test_draw_genes(self):

        x = Gene('1', 1000, 2000, strand=STRAND.POS)
        y = Gene('1', 5000, 7000, strand=STRAND.NEG)
        z = Gene('1', 1500, 2500, strand=STRAND.POS)

        d = DiagramSettings()
        breakpoints = [
            Breakpoint('1', 1100, 1200, orient=ORIENT.RIGHT)
        ]
        g = draw_genes(
            d, self.canvas, [x, y, z], 500, breakpoints,
            {x: d.gene1_color, y: d.gene2_color_selected, z: d.gene2_color})

        # test the class structure
        self.assertEqual(6, len(g.elements))
        self.assertEqual('scaffold', g.elements[0].attribs.get('class', ''))
        for i in range(1, 4):
            self.assertEqual('gene', g.elements[i].attribs.get('class', ''))
        self.assertEqual('mask', g.elements[4].attribs.get('class', ''))
        self.assertEqual('breakpoint', g.elements[5].attribs.get('class', ''))
        self.assertEqual(
            d.track_height * 2 + d.padding + d.breakpoint_bottom_margin + d.breakpoint_top_margin,
            g.height
        )
        self.canvas.add(g)
        self.assertEqual(len(g.labels), 4)
        self.assertEqual(x, g.labels['G1'])
        self.assertEqual(z, g.labels['G2'])
        self.assertEqual(y, g.labels['G3'])
        self.assertEqual(breakpoints[0], g.labels['B1'])

    def test_draw_ustranscript(self):
        d = DiagramSettings()
        # domains = [Domain()]
        d1 = Domain('first', [(55, 61), (71, 73)])
        d2 = Domain('second', [(10, 20), (30, 34)])

        t = build_transcript(
            gene=None,
            cds_start=50,
            cds_end=249,
            exons=[(1, 99), (200, 299), (400, 499)],
            strand=STRAND.NEG,
            domains=[d2, d1]
        )
        b = Breakpoint('1', 350, 410, orient=ORIENT.LEFT)
        g = draw_ustranscript(
            d, self.canvas, t, 500,
            colors={t.exons[1]: '#FFFF00'},
            breakpoints=[b]
        )
        self.canvas.add(g)
        # self.canvas.saveas('test_draw_ustranscript.svg')
        self.assertEqual(2, len(self.canvas.elements))
        self.assertEqual(3, len(g.elements))
        for el, cls in zip(g.elements[0].elements, ['splicing', 'exon_track', 'protein']):
            self.assertEqual(cls, el.attribs.get('class', ''))

        for el, cls in zip(g.elements[0].elements[1].elements, ['scaffold', 'exon', 'exon', 'exon']):
            self.assertEqual(cls, el.attribs.get('class', ''))

        for el, cls in zip(g.elements[0].elements[2].elements, ['translation', 'domain', 'domain']):
            self.assertEqual(cls, el.attribs.get('class', ''))

        self.assertEqual(
            d.track_height + d.splice_height +
            2 * d.padding + d.domain_track_height * 2 +
            d.translation_track_height + d.padding +
            d.breakpoint_top_margin +
            d.breakpoint_bottom_margin,
            g.height)
        self.assertEqual(d1.name, g.labels['D1'])
        self.assertEqual(d2.name, g.labels['D2'])

    def test_dynamic_label_color(self):
        self.assertEqual(HEX_WHITE, dynamic_label_color(HEX_BLACK))
        self.assertEqual(HEX_BLACK, dynamic_label_color(HEX_WHITE))

    def test_draw_legend(self):
        d = DiagramSettings()
        swatches = [
            ('#000000', 'black'),
            ('#FF0000', 'red'),
            ('#0000FF', 'blue'),
            ('#00FF00', 'green'),
            ('#FFFF00', 'yellow')
        ]
        g = draw_legend(d, self.canvas, swatches)
        self.canvas.add(g)

        self.assertEqual('legend', g.attribs.get('class', ''))
        self.assertEqual(
            d.legend_swatch_size * len(swatches) + d.padding * (len(swatches) - 1 + 2),
            g.height
        )
        self.assertEqual(6, len(g.elements))
        self.assertEqual(
            6 * d.legend_font_size * d.font_width_height_ratio + d.padding * 3 + d.legend_swatch_size,
            g.width
        )

    def test_draw_layout_single_transcript(self):
        d = DiagramSettings()
        d1 = Domain('first', [(55, 61), (71, 73)])
        d2 = Domain('second', [(10, 20), (30, 34)])
        g1 = Gene('1', 150, 1000, strand=STRAND.POS)
        t = build_transcript(g1, [(200, 299), (400, 499), (700, 899)], 50, 249, [d2, d1])
        b1 = Breakpoint('1', 350, orient=ORIENT.RIGHT)
        b2 = Breakpoint('1', 600, orient=ORIENT.LEFT)
        bpp = BreakpointPair(b1, b2, opposing_strands=False, untemplated_seq='')
        ann = Annotation(bpp, transcript1=t, transcript2=t, event_type=SVTYPE.DUP, protocol=PROTOCOL.GENOME)
        ann.add_gene(Gene('1', 1500, 1950, strand=STRAND.POS))

        reference_genome = {'1': MockSeq(MockString('A'))}
        ft = FusionTranscript.build(ann, reference_genome)
        ann.fusion = ft
        canvas, legend = draw_sv_summary_diagram(d, ann)
        self.assertEqual(4, len(canvas.elements))  # defs counts as element
        expected_height = d.top_margin + d.bottom_margin + \
            d.track_height + d.breakpoint_bottom_margin + d.breakpoint_top_margin + \
            d.inner_margin + \
            d.track_height + d.splice_height + \
            d.padding + d.translation_track_height + \
            d.padding * 2 + d.domain_track_height * 2 + \
            d.inner_margin + \
            d.track_height + d.breakpoint_bottom_margin + d.breakpoint_top_margin + d.splice_height
        if OUTPUT_SVG:
            canvas.saveas('test_draw_layout_single_transcript.svg')
        self.assertEqual(expected_height, canvas.attribs['height'])

    def test_draw_layout_single_genomic(self):
        d = DiagramSettings()
        d1 = Domain('first', [(55, 61), (71, 73)])
        d2 = Domain('second', [(10, 20), (30, 34)])
        g1 = Gene('1', 150, 1000, strand=STRAND.POS)
        g2 = Gene('1', 5000, 7500, strand=STRAND.POS)
        t1 = build_transcript(
            gene=g1,
            cds_start=50,
            cds_end=249,
            exons=[(200, 299), (400, 499), (700, 899)],
            domains=[d2, d1]
        )
        t2 = build_transcript(
            gene=g2,
            cds_start=20,
            cds_end=500,
            exons=[(5100, 5299), (5800, 6199), (6500, 6549), (6700, 6799)],
            domains=[]
        )
        b1 = Breakpoint('1', 350, orient=ORIENT.LEFT)
        b2 = Breakpoint('1', 6500, orient=ORIENT.RIGHT)
        bpp = BreakpointPair(b1, b2, opposing_strands=False, untemplated_seq='')
        ann = Annotation(bpp, transcript1=t1, transcript2=t2, event_type=SVTYPE.DEL, protocol=PROTOCOL.GENOME)
        ann.add_gene(Gene('1', 1500, 1950, strand=STRAND.POS))
        ann.add_gene(Gene('1', 3000, 3980, strand=STRAND.POS))
        ann.add_gene(Gene('1', 3700, 4400, strand=STRAND.NEG))

        reference_genome = {'1': MockSeq(MockString('A'))}

        ft = FusionTranscript.build(ann, reference_genome)
        ann.fusion = ft
        self.assertEqual(t1.exons[0], ft.exon_mapping[ft.exons[0].position])
        self.assertEqual(t2.exons[2], ft.exon_mapping[ft.exons[1].position])
        self.assertEqual(t2.exons[3], ft.exon_mapping[ft.exons[2].position])

        canvas, legend = draw_sv_summary_diagram(d, ann)
        self.assertEqual(5, len(canvas.elements))  # defs counts as element

        expected_height = d.top_margin + d.bottom_margin + \
            d.track_height + d.breakpoint_bottom_margin + d.breakpoint_top_margin + \
            d.inner_margin + \
            d.track_height + d.splice_height + d.breakpoint_bottom_margin + d.breakpoint_top_margin + \
            d.padding + d.translation_track_height + \
            d.padding * 2 + d.domain_track_height * 2 + \
            d.inner_margin + \
            d.track_height + d.splice_height
        self.assertEqual(expected_height, canvas.attribs['height'])
        if OUTPUT_SVG:
            canvas.saveas('test_draw_layout_single_genomic.svg')

    def test_draw_layout_translocation(self):
        d = DiagramSettings()
        d1 = Domain('first', [(55, 61), (71, 73)])
        d2 = Domain('second', [(10, 20), (30, 34)])
        g1 = Gene('1', 150, 1000, strand=STRAND.POS)
        g2 = Gene('2', 5000, 7500, strand=STRAND.NEG)
        t1 = build_transcript(
            gene=g1,
            cds_start=50,
            cds_end=249,
            exons=[(200, 299), (400, 499), (700, 899)],
            domains=[d2, d1]
        )
        t2 = build_transcript(
            gene=g2,
            cds_start=120,
            cds_end=700,
            exons=[(5100, 5299), (5800, 6199), (6500, 6549), (6700, 6799)],
            domains=[]
        )
        b1 = Breakpoint('1', 350, orient=ORIENT.LEFT)
        b2 = Breakpoint('2', 6520, orient=ORIENT.LEFT)
        bpp = BreakpointPair(b1, b2, opposing_strands=True, untemplated_seq='')
        ann = Annotation(bpp, transcript1=t1, transcript2=t2, event_type=SVTYPE.ITRANS, protocol=PROTOCOL.GENOME)
        # genes 1
        ann.add_gene(Gene('1', 1500, 1950, strand=STRAND.POS))
        ann.add_gene(Gene('1', 3000, 3980, strand=STRAND.POS))
        ann.add_gene(Gene('1', 3700, 4400, strand=STRAND.NEG))
        # genes 2
        ann.add_gene(Gene('2', 1500, 1950, strand=STRAND.NEG))
        ann.add_gene(Gene('2', 5500, 9000, strand=STRAND.POS))
        ann.add_gene(Gene('2', 3700, 4400, strand=STRAND.NEG))

        reference_genome = {'1': MockSeq(MockString('A')), '2': MockSeq(MockString('A'))}

        ft = FusionTranscript.build(ann, reference_genome)
        ann.fusion = ft
        canvas, legend = draw_sv_summary_diagram(d, ann)
        self.assertEqual(6, len(canvas.elements))  # defs counts as element
        expected_height = d.top_margin + d.bottom_margin + \
            d.track_height * 2 + d.padding + d.breakpoint_bottom_margin + d.breakpoint_top_margin + \
            d.inner_margin + \
            d.track_height + d.splice_height + d.breakpoint_bottom_margin + d.breakpoint_top_margin + \
            d.padding + d.translation_track_height + \
            d.padding * 2 + d.domain_track_height * 2 + \
            d.inner_margin + \
            d.track_height + d.splice_height
        self.assertEqual(expected_height, canvas.attribs['height'])

    def test_draw_template(self):
        # def draw_template(self, canvas, template, target_width, height, labels=None, colors=None):
        d = DiagramSettings()
        canvas = Drawing(size=(1000, 50))
        t = Template(
            '1', 1, 100000,
            bands=[
                BioInterval(None, 1, 8000, 'p1'),
                BioInterval(None, 10000, 15000, 'p2')
            ])
        g = draw_template(d, canvas, t, 1000)
        canvas.add(g)
        canvas.attribs['height'] = g.height
        canvas = Drawing(size=(1000, 50))

        g = draw_template(d, canvas, TEMPLATE_METADATA['1'], 1000)
        self.assertEqual(d.breakpoint_top_margin + d.breakpoint_bottom_margin + d.template_track_height, g.height)
        canvas.add(g)
        canvas.attribs['height'] = g.height
        self.assertEqual(2, len(canvas.elements))

    def test_draw_translocation_with_template(self):
        d = DiagramSettings()
        d1 = Domain('PF0001', [(55, 61), (71, 73)])
        d2 = Domain('PF0002', [(10, 20), (30, 34)])
        g1 = Gene(TEMPLATE_METADATA['1'], 150, 1000, strand=STRAND.POS, aliases=['HUGO2'])
        g2 = Gene(TEMPLATE_METADATA['X'], 5000, 7500, strand=STRAND.NEG, aliases=['HUGO3'])
        t1 = build_transcript(
            gene=g1,
            cds_start=50,
            cds_end=249,
            exons=[(200, 299), (400, 499), (700, 899)],
            domains=[d2, d1]
        )
        t2 = build_transcript(
            gene=g2,
            cds_start=120,
            cds_end=700,
            exons=[(5100, 5299), (5800, 6199), (6500, 6549), (6700, 6799)],
            domains=[]
        )
        b1 = Breakpoint('1', 350, orient=ORIENT.LEFT)
        b2 = Breakpoint('2', 6520, orient=ORIENT.LEFT)
        bpp = BreakpointPair(b1, b2, opposing_strands=True, untemplated_seq='')
        ann = Annotation(bpp, transcript1=t1, transcript2=t2, event_type=SVTYPE.ITRANS, protocol=PROTOCOL.GENOME)
        # genes 1
        ann.add_gene(Gene('1', 1500, 1950, strand=STRAND.POS, aliases=['HUGO5']))
        ann.add_gene(Gene('1', 3000, 3980, strand=STRAND.POS))
        ann.add_gene(Gene('1', 3700, 4400, strand=STRAND.NEG))
        # genes 2
        ann.add_gene(Gene('2', 1500, 1950, strand=STRAND.NEG))
        ann.add_gene(Gene('2', 5500, 9000, strand=STRAND.POS))
        ann.add_gene(Gene('2', 3700, 4400, strand=STRAND.NEG))

        reference_genome = {'1': MockSeq(MockString('A')), '2': MockSeq(MockString('A'))}

        ft = FusionTranscript.build(ann, reference_genome)
        ann.fusion = ft
        canvas, legend = draw_sv_summary_diagram(d, ann, draw_reference_templates=True, templates=TEMPLATE_METADATA)
        if OUTPUT_SVG:
            canvas.saveas('test_draw_translocation_with_template.svg')
        self.assertEqual(8, len(canvas.elements))  # defs counts as element
        expected_height = d.top_margin + d.bottom_margin + \
            d.track_height * 2 + d.padding + d.breakpoint_bottom_margin + d.breakpoint_top_margin + \
            d.inner_margin + \
            d.track_height + d.splice_height + d.breakpoint_bottom_margin + d.breakpoint_top_margin + \
            d.padding + d.translation_track_height + \
            d.padding * 2 + d.domain_track_height * 2 + \
            d.inner_margin * 2 + \
            d.track_height + d.breakpoint_bottom_margin + d.breakpoint_top_margin + d.splice_height + \
            d.template_track_height
        self.assertAlmostEqual(expected_height, canvas.attribs['height'])

    def test_draw_overlay(self):
        gene = Gene('12', 25357723, 25403870, strand=STRAND.NEG, name='KRAS')
        marker = BioInterval('12', 25403865, name='splice site mutation')
        t = build_transcript(
            cds_start=193, cds_end=759,
            exons=[
                (25403685, 25403865),
                (25398208, 25398329),
                (25380168, 25380346),
                (25378548, 25378707),
                (25357723, 25362845)],
            gene=gene, domains=[])
        build_transcript(
            cds_start=198, cds_end=425,
            exons=[(25403685, 25403870), (25398208, 25398329), (25362102, 25362845)],
            gene=gene, domains=[])
        build_transcript(
            cds_start=65, cds_end=634,
            exons=[
                (25403685, 25403737),
                (25398208, 25398329),
                (25380168, 25380346),
                (25378548, 25378707),
                (25368371, 25368494),
                (25362365, 25362845)],
            gene=gene, domains=[Domain('domain1', [(1, 10)]), Domain('domain1', [(4, 10)])],
            is_best_transcript=True)
        build_transcript(
            cds_start=65, cds_end=634,
            exons=[(25403698, 25403863), (25398208, 25398329), (25386753, 25388160)],
            gene=gene, domains=[])
        d = DiagramSettings()
        for i, t in enumerate(gene.transcripts):
            t.name = 'transcript {}'.format(i + 1)
        scatterx = [Interval(x, x + 200) for x in range(gene.start, gene.end + 1, 400)]
        scattery = [Interval(random.uniform(-0.2, 0.2)) for x in scatterx]
        s = ScatterPlot(
            list(zip(scatterx, scattery)),
            'cna',
            ymin=-1,
            ymax=1,
            yticks=[-1, 0, 1]
        )

        d.gene_min_buffer = 0
        canvas = draw_multi_transcript_overlay(d, gene, vmarkers=[marker], plots=[s, s])
        self.assertEqual(2, len(canvas.elements))  # defs counts as element
        if OUTPUT_SVG:
            canvas.saveas('test_draw_overlay.svg')