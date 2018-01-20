from functools import partial
import itertools
import math
import statistics
import warnings

from .evidence import TranscriptomeEvidence
from ..align import SplitAlignment, query_coverage_interval, call_read_events, call_paired_read_event
from ..bam import read as _read

from ..breakpoint import Breakpoint, BreakpointPair
from ..constants import CALL_METHOD, CIGAR, COLUMNS, ORIENT, PROTOCOL, PYSAM_READ_FLAGS, STRAND, SVTYPE, reverse_complement
from ..interval import Interval


class EventCall(BreakpointPair):
    """
    class for holding evidence and the related calls since we can't freeze the evidence object
    directly without a lot of copying. Instead we use call objects which are basically
    just a reference to the evidence object and decisions on class, exact breakpoints, etc
    """
    @property
    def has_compatible(self):
        return False if self.compatible_type is None else True

    def __init__(
        self,
        b1, b2,
        source_evidence,
        event_type,
        call_method,
        contig=None,
        contig_alignment=None,
        untemplated_seq=None
    ):
        """
        Args:
            evidence (Evidence): the evidence object we are calling based on
            event_type (SVTYPE): the type of structural variant
            breakpoint_pair (BreakpointPair): the breakpoint pair representing the exact breakpoints
            call_method (CALL_METHOD): the way the breakpoints were called
            contig (Contig): the contig used to call the breakpoints (if applicable)
        """
        BreakpointPair.__init__(
            self, b1, b2,
            stranded=source_evidence.stranded and source_evidence.bam_cache.stranded,
            untemplated_seq=untemplated_seq
        )
        self.data.update(source_evidence.data)
        if not source_evidence.bam_cache.stranded:
            self.break1.strand = STRAND.NS
            self.break2.strand = STRAND.NS
        self.source_evidence = source_evidence
        self.spanning_reads = set()
        self.flanking_pairs = set()
        self.break1_split_reads = set()
        self.break2_split_reads = set()
        self.compatible_flanking_pairs = set()
        # check that the event type is compatible
        if event_type == SVTYPE.DUP:
            self.compatible_type = SVTYPE.INS
        elif event_type == SVTYPE.INS:
            self.compatible_type = SVTYPE.DUP
        else:
            self.compatible_type = None
        if event_type not in BreakpointPair.classify(self) and self.compatible_type in BreakpointPair.classify(self):
            event_type, self.compatible_type = self.compatible_type, event_type
        self.event_type = SVTYPE.enforce(event_type)
        if event_type not in BreakpointPair.classify(self) | {self.compatible_type}:
            raise ValueError(
                'event_type is not compatible with the breakpoint call',
                event_type, BreakpointPair.classify(self), self.compatible_type)
        self.contig = contig
        self.call_method = CALL_METHOD.enforce(call_method)
        if contig and self.call_method != CALL_METHOD.CONTIG:
            raise ValueError('if a contig is given the call method must be by contig')
        self.contig_alignment = contig_alignment

    def get_bed_repesentation(self):
        bed = []
        name = self.data.get(COLUMNS.validation_id, None) + '-' + self.event_type
        if self.interchromosomal:
            bed.append((self.break1.chr, self.break1.start - 1, self.break1.end, name))
            bed.append((self.break2.chr, self.break2.start - 1, self.break2.end, name))
        else:
            bed.append((self.break1.chr, self.break1.start - 1, self.break2.end, name))
        return bed

    def support(self):
        """return a set of all reads which support the call"""
        support = set()
        support.update(self.spanning_reads)
        for read, mate in self.flanking_pairs | self.compatible_flanking_pairs:
            support.add(read)
            support.add(mate)
        support.update(self.break1_split_reads)
        support.update(self.break2_split_reads)
        if self.contig:
            support.update(self.contig.input_reads)
        return support

    def is_supplementary(self):
        """
        check if the current event call was the target event given the source evidence object or an off-target call, i.e.
        something that was called as part of the original target.
        This is important b/c if the current event was not one of the original target it may not be fully investigated in
        other libraries
        """
        return not all([
            {self.event_type, self.compatible_type} & BreakpointPair.classify(self.source_evidence),
            self.break1 & self.source_evidence.outer_window1,
            self.break2 & self.source_evidence.outer_window2,
            self.break1.chr == self.source_evidence.break1.chr,
            self.break2.chr == self.source_evidence.break2.chr,
            self.opposing_strands == self.source_evidence.opposing_strands
        ])

    def add_flanking_support(self, flanking_pairs, is_compatible=False):
        """
        counts the flanking read-pair support for the event called. The original source evidence may
        have contained evidence for multiple events and uses a larger range so flanking pairs here
        are checked specifically against the current breakpoint call

        Returns:
            tuple:
            * :class:`set` of :class:`str` - set of the read query_names
            * :class:`int` - the median insert size
            * :class:`int` - the standard deviation (from the median) of the insert size

        see :ref:`theory - determining flanking support <theory-determining-flanking-support>`
        """
        min_frag = max([
            self.source_evidence.min_expected_fragment_size + Interval.dist(self.break1, self.break2),
            self.source_evidence.max_expected_fragment_size])
        max_frag = len(self.break1 | self.break2) + self.source_evidence.max_expected_fragment_size
        for read, mate in flanking_pairs:
            # check that the fragment size is reasonable
            fragment_size = self.source_evidence.compute_fragment_size(read, mate)
            if self.event_type == SVTYPE.DEL:
                if fragment_size.end < min_frag or fragment_size.start > max_frag:
                    continue
            elif self.event_type == SVTYPE.INS:
                if fragment_size.start >= self.source_evidence.min_expected_fragment_size:
                    continue
            if self.interchromosomal != (read.reference_id != mate.reference_id):
                continue
            # check that the flanking reads work with the current call
            if not _read.orientation_supports_type(
                    read, self.event_type if not is_compatible else self.compatible_type):
                continue
            # check that the positions make sense
            left = ORIENT.LEFT if not is_compatible else ORIENT.RIGHT
            if self.break1.orient == left:
                if self.break2.orient == left:  # L L
                    if not all([
                        read.reference_start + 1 <= self.break1.end,
                        mate.reference_start + 1 <= self.break2.end,
                        mate.reference_end > self.break1.start or self.interchromosomal
                    ]):
                        continue
                else:  # L R
                    if not all([
                        read.reference_start + 1 <= self.break1.end,
                        mate.reference_end >= self.break2.start
                    ]):
                        continue
            else:
                if self.break2.orient == left:  # R L
                    if not all([
                        read.reference_end >= self.break1.start,
                        mate.reference_start + 1 <= self.break2.end
                    ]):
                        continue
                else:  # R R
                    if not all([
                        read.reference_end >= self.break1.start,
                        mate.reference_end >= self.break2.start,
                        read.reference_end < self.break2.end or self.interchromosomal
                    ]):
                        continue
            if is_compatible:
                self.compatible_flanking_pairs.add((read, mate))
            else:
                self.flanking_pairs.add((read, mate))

    def add_break1_split_read(self, read):
        """
        Args:
            read (pysam.AlignedSegment): putative split read supporting the first breakpoint
        """
        try:
            pos = _read.breakpoint_pos(read, self.break1.orient) + 1
            if Interval.overlaps((pos, pos), self.break1):
                self.break1_split_reads.add(read)
        except AttributeError:
            pass

    def add_break2_split_read(self, read):
        """
        Args:
            read (pysam.AlignedSegment): putative split read supporting the second breakpoint
        """
        try:
            pos = _read.breakpoint_pos(read, self.break2.orient) + 1
            if Interval.overlaps((pos, pos), self.break2):
                self.break2_split_reads.add(read)
        except AttributeError:
            pass

    def add_spanning_read(self, read):
        """
        Args:
            read (pysam.AlignedSegment): putative spanning read
        """
        for event in call_read_events(read):
            if event == self and self.event_type in BreakpointPair.classify(event, distance=self.source_evidence.distance):
                self.spanning_reads.add(read)

    def __hash__(self):
        raise NotImplementedError('this object type does not support hashing')

    def flanking_metrics(self):
        """
        computes the median and standard deviation of the flanking pairs. Note that standard
        deviation is calculated wrt the median and not the average. Also that the fragment size
        is calculated as a range so the start and end of the range are used in computing these
        metrics

        Returns:
            tuple:
                - ``float`` - the median fragment size
                - ``float`` - the fragment size standard deviation wrt the median
        """
        fragment_sizes = []
        for read, mate in self.flanking_pairs:
            # check that the fragment size is reasonable
            fsize_range = self.source_evidence.compute_fragment_size(read, mate)
            fragment_sizes.append(fsize_range.start)
            fragment_sizes.append(fsize_range.end)
        median = 0
        stdev = 0
        if fragment_sizes:
            median = statistics.median(fragment_sizes)
            err = 0
            for insert in fragment_sizes:
                err += math.pow(insert - median, 2)
            err /= len(fragment_sizes)
            stdev = math.sqrt(err)
        return median, stdev

    def break1_tgt_align_split_read_names(self):
        reads = set()
        for read in self.break1_split_reads:
            if read.has_tag(PYSAM_READ_FLAGS.TARGETED_ALIGNMENT) and read.get_tag(PYSAM_READ_FLAGS.TARGETED_ALIGNMENT):
                reads.add(read.query_name)
        return reads

    def break2_tgt_align_split_read_names(self):
        reads = set()
        for read in self.break2_split_reads:
            if read.has_tag(PYSAM_READ_FLAGS.TARGETED_ALIGNMENT) and read.get_tag(PYSAM_READ_FLAGS.TARGETED_ALIGNMENT):
                reads.add(read.query_name)
        return reads

    def linking_split_read_names(self):
        reads1 = set()
        for read in self.break1_split_reads:
            reads1.add(read.query_name)

        reads2 = set()
        for read in self.break2_split_reads:
            reads2.add(read.query_name)

        return reads1 & reads2

    @staticmethod
    def characterize_repeat_region(event, reference_genome):
        """
        For a given event, determines the number of repeats the insertion/duplication/deletion is following.
        This is most useful in flagging homopolymer regions. Will raise a ValueError if the current event is
        not an expected type or is non-specific.
        """
        if len(event.break1) + len(event.break2) > 2:
            raise ValueError('Cannot characterize a repeat region for a non-specific call')
        elif not any([
            event.event_type == SVTYPE.INS and event.untemplated_seq,
            event.event_type in {SVTYPE.DEL, SVTYPE.DUP} and not event.untemplated_seq
        ]):
            raise ValueError(
                'Characterizing repeat regions does not make sense for the given event type',
                event.event_type, event.untemplated_seq)

        expected_sequence = None
        rightmost = None
        if event.event_type == SVTYPE.DEL:
            expected_sequence = reference_genome[event.break1.chr].seq[event.break1.start:event.break2.end - 1]
            rightmost = event.break1.start
        elif event.event_type == SVTYPE.DUP:
            expected_sequence = reference_genome[event.break1.chr].seq[event.break1.start - 1:event.break2.end]
            rightmost = event.break1.start - 1
        else:
            expected_sequence = event.untemplated_seq
            rightmost = event.break1.start

        repeat_count = 0
        while rightmost - len(expected_sequence) > 0:
            ref = reference_genome[event.break1.chr].seq[rightmost - len(expected_sequence):rightmost].upper()
            if ref != expected_sequence:
                break
            repeat_count += 1
            rightmost -= len(expected_sequence)
        return repeat_count

    def flatten(self):
        """
        converts the current call to a dictionary for a row in a tabbed file
        """
        row = self.source_evidence.flatten()
        row.update(BreakpointPair.flatten(self))  # this will overwrite the evidence breakpoint which is what we want
        row.update({
            COLUMNS.call_method: self.call_method,
            COLUMNS.event_type: self.event_type,
            COLUMNS.contig_seq: None,
            COLUMNS.contig_remap_score: None,
            COLUMNS.contig_alignment_score: None,
            COLUMNS.contig_blat_rank: None,
            COLUMNS.contig_remapped_reads: None,
            COLUMNS.contig_remapped_read_names: None,
            COLUMNS.contig_strand_specific: None,
            COLUMNS.contig_alignment_query_consumption: None,
            COLUMNS.contig_build_score: None,
            COLUMNS.contig_alignment_query_name: None,
            COLUMNS.contig_remap_coverage: None,
            COLUMNS.contig_read_depth: None,
            COLUMNS.contig_break1_read_depth: None,
            COLUMNS.contig_break2_read_depth: None,
            COLUMNS.supplementary_call: self.is_supplementary()
        })
        try:
            row[COLUMNS.repeat_count] = EventCall.characterize_repeat_region(self, self.source_evidence.reference_genome)
        except ValueError:
            row[COLUMNS.repeat_count] = None

        median, stdev = self.flanking_metrics()
        flank = set()
        for read, mate in self.flanking_pairs:
            flank.update({read.query_name, mate.query_name})
        row.update({
            COLUMNS.flanking_pairs: len(self.flanking_pairs),
            COLUMNS.flanking_median_fragment_size: median,
            COLUMNS.flanking_stdev_fragment_size: stdev,
            COLUMNS.flanking_pairs_read_names: ';'.join(sorted(list(flank)))
        })

        b1 = set()
        b1_tgt = set()
        b2 = set()
        b2_tgt = set()

        for read in self.break1_split_reads:
            name = read.query_name
            b1.add(name)
            if read.has_tag(PYSAM_READ_FLAGS.TARGETED_ALIGNMENT) and read.get_tag(PYSAM_READ_FLAGS.TARGETED_ALIGNMENT):
                b1_tgt.add(name)
        for read in self.break2_split_reads:
            name = read.query_name
            b2.add(name)
            if read.has_tag(PYSAM_READ_FLAGS.TARGETED_ALIGNMENT) and read.get_tag(PYSAM_READ_FLAGS.TARGETED_ALIGNMENT):
                b2_tgt.add(name)

        linking = b1 & b2

        row.update({
            COLUMNS.break1_split_reads: len(b1),
            COLUMNS.break1_split_reads_forced: len(b1_tgt),
            COLUMNS.break1_split_read_names: ';'.join(sorted(b1)),
            COLUMNS.break2_split_reads: len(b2),
            COLUMNS.break2_split_reads_forced: len(b2_tgt),
            COLUMNS.break2_split_read_names: ';'.join(sorted(b2)),
            COLUMNS.linking_split_reads: len(linking),
            COLUMNS.linking_split_read_names: ';'.join(sorted(linking)),
            COLUMNS.spanning_reads: len(self.spanning_reads),
            COLUMNS.spanning_read_names: ';'.join(sorted([r.query_name for r in self.spanning_reads]))
        })
        if self.has_compatible:
            row[COLUMNS.flanking_pairs_compatible] = len(self.compatible_flanking_pairs)
            names = {f[0].query_name for f in self.compatible_flanking_pairs}
            names.update({f[1].query_name for f in self.compatible_flanking_pairs})
            row[COLUMNS.flanking_pairs_compatible_read_names] = ';'.join(sorted(names))
        try:
            row[COLUMNS.net_size] = '{}-{}'.format(*self.net_size(self.source_evidence.distance))
        except ValueError:
            row[COLUMNS.net_size] = None
        # add contig specific metrics and columns
        if self.contig:
            blat_score = None
            if self.contig_alignment.read1.has_tag('br'):
                blat_score = self.contig_alignment.read1.get_tag('br')
                if self.contig_alignment.read2:
                    blat_score += self.contig_alignment.read2.get_tag('br')
                    blat_score = round(blat_score / 2, 1)
            cseq = self.contig_alignment.query_sequence
            try:
                break1_read_depth = SplitAlignment.breakpoint_contig_remapped_depth(
                    self.break1, self.contig, self.contig_alignment.read1
                )
            except AssertionError:
                break1_read_depth = None
            try:
                break2_read_depth = SplitAlignment.breakpoint_contig_remapped_depth(
                    self.break2, self.contig,
                    self.contig_alignment.read1 if self.contig_alignment.read2 is None else self.contig_alignment.read2
                )
            except AssertionError:
                break2_read_depth = None
            row.update({
                COLUMNS.contig_seq: cseq,  # don't output sequence directly from contig b/c must always be wrt to the positive strand
                COLUMNS.contig_remap_score: self.contig.remap_score(),
                COLUMNS.contig_alignment_score: self.contig_alignment.score(),
                COLUMNS.contig_blat_rank: blat_score,
                COLUMNS.contig_remapped_reads: len(self.contig.input_reads),
                COLUMNS.contig_remapped_read_names:
                    ';'.join(sorted(set([r.query_name for r in self.contig.input_reads]))),
                COLUMNS.contig_strand_specific: self.contig.strand_specific,
                COLUMNS.contig_alignment_query_consumption: self.contig_alignment.query_consumption(),
                COLUMNS.contig_build_score: self.contig.score,
                COLUMNS.contig_alignment_query_name: self.contig_alignment.query_name,
                COLUMNS.contig_remap_coverage: self.contig.remap_coverage(),
                COLUMNS.contig_read_depth: self.contig.remap_depth(),
                COLUMNS.contig_break1_read_depth: break1_read_depth,
                COLUMNS.contig_break2_read_depth: break2_read_depth
            })
        return row


def _call_by_contigs(source_evidence):
    # try calling by contigs
    contig_calls = []
    for ctg in source_evidence.contigs:
        for aln in ctg.alignments:
            if aln.is_putative_indel and aln.net_size(source_evidence.distance) == Interval(0):
                continue
            for event_type in BreakpointPair.classify(aln, distance=source_evidence.distance):
                new_event = EventCall(
                    aln.break1,
                    aln.break2,
                    source_evidence,
                    event_type,
                    contig=ctg,
                    contig_alignment=aln,
                    untemplated_seq=aln.untemplated_seq,
                    call_method=CALL_METHOD.CONTIG
                )
                # add the flanking support
                new_event.add_flanking_support(source_evidence.flanking_pairs)
                if new_event.has_compatible:
                    new_event.add_flanking_support(source_evidence.compatible_flanking_pairs, is_compatible=True)

                # add any spanning reads that call the same event
                for read in source_evidence.spanning_reads:
                    new_event.add_spanning_read(read)
                # add any split read support (this will be consumed for non-contig calls)
                for read in source_evidence.split_reads[0]:
                    new_event.add_break1_split_read(read)
                for read in source_evidence.split_reads[1]:
                    new_event.add_break2_split_read(read)

                contig_calls.append(new_event)
    return contig_calls


def filter_consumed_pairs(pairs, consumed_reads):
    """
    given a set of read tuples, returns all tuples where neither read in the tuple is in the consumed set

    Args:
        pairs (set of tuples of :class:`pysam.AlignedSegment` and :class:`pysam.AlignedSegment`): pairs to be filtered
        consumed_reads: (set of :class:`pysam.AlignedSegment`): set of reads that have been used/consumed

    Returns:
        set of tuples of :class:`pysam.AlignedSegment` and :class:`pysam.AlignedSegment`: set of filtered tuples

    Note:
        this will work with any hash-able object

    Example:
        >>> pairs = {(1, 2), (3, 4), (5, 6)}
        >>> consumed_reads = {1, 2, 4}
        >>> filter_consumed_pairs(pairs, consumed_reads)
        {(5, 6)}
    """
    temp = set()
    for read, mate in pairs:
        if read not in consumed_reads and mate not in consumed_reads:
            temp.add((read, mate))
    return temp


def _call_by_spanning_reads(source_evidence, consumed_evidence):
    spanning_calls = {}
    available_flanking_pairs = filter_consumed_pairs(source_evidence.flanking_pairs, consumed_evidence)

    for read in source_evidence.spanning_reads - consumed_evidence:
        for event in call_read_events(read):
            if event.query_consumption() >= source_evidence.contig_aln_min_query_consumption:
                spanning_calls.setdefault(event, set()).add(read)
    result = []
    for event, reads in spanning_calls.items():
        if any([
            len(reads) < source_evidence.min_spanning_reads_resolution,
            source_evidence.opposing_strands != event.opposing_strands
        ]):
            continue
        event.break1.seq = None  # unless we are collecting a consensus we shouldn't assign sequences to the breaks
        event.break2.seq = None
        if not source_evidence.stranded:
            event.break1.strand = STRAND.NS
            event.break2.strand = STRAND.NS
        for event_type in BreakpointPair.classify(source_evidence) & BreakpointPair.classify(event, distance=source_evidence.distance):
            new_event = EventCall(
                event.break1, event.break2,
                source_evidence,
                event_type,
                CALL_METHOD.SPAN,
                untemplated_seq=event.untemplated_seq
            )
            new_event.spanning_reads.update(reads)
            # add any supporting split reads
            # add the flanking support
            new_event.add_flanking_support(available_flanking_pairs)
            if new_event.has_compatible:
                new_event.add_flanking_support(available_flanking_pairs, is_compatible=True)
            # add any split read support (this will be consumed for non-contig calls)
            for read in source_evidence.split_reads[0] - consumed_evidence:
                new_event.add_break1_split_read(read)
            for read in source_evidence.split_reads[1] - consumed_evidence:
                new_event.add_break2_split_read(read)

            result.append(new_event)
    return result


def call_events(source_evidence):
    """
    generates a set of event calls based on the evidence associated with the source_evidence object
    will also narrow down the event type

    Args:
        source_evidence (Evidence): the input evidence
        event_type (SVTYPE): the type of event we are collecting evidence for

    Returns:
        :class:`list` of :class:`EventCall`: list of calls
    """
    consumed_evidence = set()  # keep track to minimize evidence re-use
    calls = []
    errors = set()

    contig_calls = _call_by_contigs(source_evidence)
    calls.extend(contig_calls)
    for call in contig_calls:
        consumed_evidence.update(call.support())

    spanning_calls = _call_by_spanning_reads(source_evidence, consumed_evidence)
    for call in spanning_calls:
        consumed_evidence.update(call.support())
    calls.extend(spanning_calls)

    for event_type in sorted(source_evidence.putative_event_types()):
        # try calling by split/flanking reads
        try:
            contig_consumed_evidence = set()
            contig_consumed_evidence.update(consumed_evidence)
            calls.extend(_call_by_supporting_reads(source_evidence, event_type, contig_consumed_evidence))
        except UserWarning as err:
            errors.add(str(err))

    if not calls and errors:
        raise UserWarning(';'.join(sorted(list(errors))))
    elif not calls:
        raise UserWarning('insufficient evidence to call events')
    return calls


def _call_interval_by_flanking_coverage(coverage, orientation, max_expected_fragment_size, read_length, distance, traverse):
    if max_expected_fragment_size <= 0 or read_length <= 0:
        raise ValueError(
            'max_expected_fragment_size and read_length must be positive integers',
            max_expected_fragment_size, read_length)

    coverage_d = distance(coverage.start, coverage.end).start + 1  # minimum distance of the coverage
    max_interval = max_expected_fragment_size - read_length
    if coverage_d > max_interval:
        msg = 'length of the coverage interval ({}) is greater than the maximum expected ({})'.format(
            coverage_d, max_interval)
        warnings.warn(msg)
        raise AssertionError(msg)
    if orientation == ORIENT.LEFT:
        start = coverage.end
        end = traverse(coverage.end, max_interval - coverage_d, ORIENT.RIGHT).end
        return Interval(start, end)
    elif orientation == ORIENT.RIGHT:
        end = coverage.start
        start = max([1, traverse(coverage.start, max_interval - coverage_d, ORIENT.LEFT).start])
        return Interval(start, end)
    else:
        raise ValueError('orientation must be specific', orientation)


def _call_by_flanking_pairs(
        evidence, event_type, first_breakpoint_called=None, second_breakpoint_called=None, consumed_evidence=None):
    """
    Given a set of flanking reads, computes the coverage interval (the area that is covered by flanking read alignments)
    this area gives the starting position for computing the breakpoint interval.

    .. todo::

        pre-split pairs into clusters by position and fragment size. This will enable calling multiple
        events in close proximity by flanking reads only. It will also aid in stopping FP reads from
        interfering with resolving events by flanking pairs.
    """
    if consumed_evidence is None:
        consumed_evidence = set()
    # for all flanking read pairs mark the farthest possible distance to the breakpoint
    # the start/end of the read on the breakpoint side
    first_positions = []
    second_positions = []

    flanking_count = 0
    cover1_reads = []
    cover2_reads = []
    available_flanking_pairs = filter_consumed_pairs(evidence.flanking_pairs, consumed_evidence)

    for read, mate in available_flanking_pairs:
        # check that the fragment size is reasonable
        fragment_size = evidence.compute_fragment_size(read, mate)
        if event_type == SVTYPE.DEL:
            if fragment_size.end <= evidence.max_expected_fragment_size:
                continue
        elif event_type == SVTYPE.INS:
            if fragment_size.start >= evidence.min_expected_fragment_size:
                continue
        flanking_count += 1
        cover1_reads.append(read)
        cover2_reads.append(mate)
        first_positions.extend([read.reference_start + 1, read.reference_end])
        second_positions.extend([mate.reference_start + 1, mate.reference_end])
    if flanking_count < evidence.min_flanking_pairs_resolution:
        raise AssertionError('insufficient coverage to call {} by flanking reads'.format(event_type))

    cover1 = Interval(min(first_positions), max(first_positions))
    cover2 = Interval(min(second_positions), max(second_positions))
    if not evidence.interchromosomal:
        if Interval.overlaps(cover1, cover2) and event_type != SVTYPE.DUP:
            raise AssertionError('flanking read coverage overlaps. cannot call by flanking reads', cover1, cover2)
        elif event_type == SVTYPE.DUP and (cover1.start > cover2.start or cover2.end < cover1.end):
            raise AssertionError('flanking coverage for duplications must have some distinct positions', cover1, cover2)

    break1_strand = STRAND.NS
    break2_strand = STRAND.NS
    if evidence.stranded:
        break1_strand = evidence.decide_sequenced_strand(cover1_reads)
        break2_strand = evidence.decide_sequenced_strand(cover2_reads)

    if first_breakpoint_called is None and second_breakpoint_called is None:

        window1 = _call_interval_by_flanking_coverage(
            cover1, evidence.break1.orient, evidence.max_expected_fragment_size, evidence.read_length,
            distance=evidence.distance, traverse=evidence.traverse
        )

        window2 = _call_interval_by_flanking_coverage(
            cover2, evidence.break2.orient, evidence.max_expected_fragment_size, evidence.read_length,
            distance=evidence.distance, traverse=evidence.traverse
        )

        if not evidence.interchromosomal:
            if window1.start > window2.end:
                raise AssertionError('flanking window regions are incompatible', window1, window2)
            window1.end = min([window1.end, window2.end, cover2.start - (0 if event_type == SVTYPE.DUP else 1)])
            window2.start = max([window1.start, window2.start, cover1.end + (0 if event_type == SVTYPE.DUP else 1)])
        first_breakpoint_called = Breakpoint(
            evidence.break1.chr, window1.start, window1.end,
            orient=evidence.break1.orient,
            strand=break1_strand
        )

        second_breakpoint_called = Breakpoint(
            evidence.break2.chr, window2.start, window2.end,
            orient=evidence.break2.orient,
            strand=break2_strand
        )
        return first_breakpoint_called, second_breakpoint_called

    elif second_breakpoint_called is None:
        # does the input breakpoint make sense with the coverage?
        if any([
            first_breakpoint_called.orient == ORIENT.LEFT and cover1.end > first_breakpoint_called.end,
            first_breakpoint_called.orient == ORIENT.RIGHT and cover1.start < first_breakpoint_called.start
        ]):
            raise AssertionError(
                'input breakpoint is incompatible with flanking coverage', cover1, first_breakpoint_called)

        window = _call_interval_by_flanking_coverage(
            cover2, evidence.break2.orient, evidence.max_expected_fragment_size, evidence.read_length,
            distance=evidence.distance, traverse=evidence.traverse
        )
        # trim the putative window by the input breakpoint location for intrachromosomal events
        if not evidence.interchromosomal:
            window.start = max([
                window.start, first_breakpoint_called.start + (0 if event_type == SVTYPE.DUP else 1), cover1.end + 1])
            if window.start > window.end or window.end < first_breakpoint_called.start:
                raise AssertionError('input breakpoint incompatible with call', window, first_breakpoint_called)
        second_breakpoint_called = Breakpoint(
            evidence.break2.chr, window.start, window.end,
            orient=evidence.break2.orient,
            strand=break2_strand
        )
        return first_breakpoint_called, second_breakpoint_called

    elif first_breakpoint_called is None:
        # does the input breakpoint make sense with the coverage?
        if any([
            second_breakpoint_called.orient == ORIENT.LEFT and cover2.end > second_breakpoint_called.end,
            second_breakpoint_called.orient == ORIENT.RIGHT and cover2.start < second_breakpoint_called.start
        ]):
            raise AssertionError(
                'input breakpoint is incompatible with flanking coverage', cover2, second_breakpoint_called)

        window = _call_interval_by_flanking_coverage(
            cover1, evidence.break1.orient, evidence.max_expected_fragment_size, evidence.read_length,
            distance=evidence.distance, traverse=evidence.traverse
        )

        # trim the putative window by the input breakpoint location for intrachromosomal events
        if not evidence.interchromosomal:
            window.end = min([
                window.end, second_breakpoint_called.end - (0 if event_type == SVTYPE.DUP else 1), cover2.start - 1])
            if window.end < window.start or window.start > second_breakpoint_called.end:
                raise AssertionError('input breakpoint incompatible with call', window, second_breakpoint_called)
        first_breakpoint_called = Breakpoint(
            evidence.break1.chr, window.start, window.end,
            orient=evidence.break1.orient,
            strand=break1_strand
        )
        return first_breakpoint_called, second_breakpoint_called
    else:
        raise ValueError('cannot input both breakpoints')


def _call_by_supporting_reads(evidence, event_type, consumed_evidence=None):
    """
    use split read evidence to resolve bp-level calls for breakpoint pairs (where possible)
    if a bp level call is not possible for one of the breakpoints then returns None
    if no breakpoints can be resolved returns the original event only with NO split read evidence
    also sets the SV type call if multiple are input
    """
    if consumed_evidence is None:
        consumed_evidence = set()
    pos1 = {}
    pos2 = {}

    available_flanking_pairs = filter_consumed_pairs(evidence.flanking_pairs, consumed_evidence)

    for i, breakpoint, pos_dict in [(0, evidence.break1, pos1), (1, evidence.break2, pos2)]:
        for read in evidence.split_reads[i] - consumed_evidence:
            try:
                pos = _read.breakpoint_pos(read, breakpoint.orient) + 1
                if pos not in pos_dict:
                    pos_dict[pos] = set()
                pos_dict[pos].add(read)
            except AttributeError:
                pass
        putative_positions = list(pos_dict.keys())
        for pos in putative_positions:
            if len(pos_dict[pos]) < evidence.min_splits_reads_resolution:
                del pos_dict[pos]
            else:
                count = 0
                for read in pos_dict[pos]:
                    if not read.has_tag(PYSAM_READ_FLAGS.TARGETED_ALIGNMENT) or \
                            not read.get_tag(PYSAM_READ_FLAGS.TARGETED_ALIGNMENT):
                        count += 1
                if count < evidence.min_non_target_aligned_split_reads:
                    del pos_dict[pos]

    linked_pairings = []
    # now pair up the breakpoints with their putative partners
    for first, second in itertools.product(pos1, pos2):
        if evidence.break1.chr == evidence.break2.chr:
            if first >= second:
                continue
        links = 0
        read_names = set([r.query_name for r in pos1[first]])
        reads = set([(r.query_name, r.query_sequence) for r in pos1[first]])
        tgt_align = 0
        for read in pos2[second]:
            if read.query_name in read_names:
                links += 1
            if (read.query_name, read.query_sequence) in reads:
                tgt_align += 1
        if links < evidence.min_linking_split_reads:
            continue
        deletion_size = second - first - 1
        if tgt_align >= evidence.min_double_aligned_to_estimate_insertion_size:
            # we can estimate the fragment size
            max_insert = evidence.read_length - 2 * evidence.min_softclipping
            if event_type == SVTYPE.INS and max_insert < deletion_size:
                continue
            elif event_type == SVTYPE.DEL and deletion_size < max_insert:
                continue
        elif links >= evidence.min_double_aligned_to_estimate_insertion_size:
            if deletion_size > evidence.max_expected_fragment_size and event_type == SVTYPE.INS:
                continue

        # check if any of the aligned reads are 'double' aligned
        double_aligned = {}
        for read in pos1[first] | pos2[second]:
            seq_key = tuple(sorted([
                read.query_name, read.query_sequence, reverse_complement(read.query_sequence)
            ]))  # seq and revseq are equal
            double_aligned.setdefault(seq_key, []).append(read)

        # now create calls using the double aligned split read pairs if possible (to resolve untemplated sequence)
        resolved_calls = set()
        event_types = {event_type}
        if event_type in {SVTYPE.DUP, SVTYPE.INS}:
            event_types.update({SVTYPE.DUP, SVTYPE.INS})
        for reads in [d for d in double_aligned.values() if len(d) > 1]:
            for read1, read2 in itertools.combinations(reads, 2):
                if len(resolved_calls) > 1:
                    break
                try:
                    call = call_paired_read_event(read1, read2)
                    if BreakpointPair.classify(call) & event_types:  # ensure we are calling the correct event types
                        resolved_calls.add(call)
                except AssertionError:
                    pass  # will be thrown if the reads do not actually belong together
            if len(resolved_calls) > 1:
                break
        if len(resolved_calls) == 1:
            call = resolved_calls.pop()
            call = EventCall(
                call.break1, call.break2, evidence, event_type,
                call_method=CALL_METHOD.SPLIT, untemplated_seq=call.untemplated_seq
            )
        else:
            first_breakpoint = Breakpoint(evidence.break1.chr, first, strand=evidence.break1.strand, orient=evidence.break1.orient)
            second_breakpoint = Breakpoint(evidence.break2.chr, second, strand=evidence.break2.strand, orient=evidence.break2.orient)
            call = EventCall(
                first_breakpoint, second_breakpoint, evidence, event_type,
                call_method=CALL_METHOD.SPLIT
            )
        call.add_flanking_support(available_flanking_pairs)
        if call.has_compatible:
            call.add_flanking_support(available_flanking_pairs, is_compatible=True)
        call.break1_split_reads.update(pos1[first])
        call.break2_split_reads.update(pos2[second])
        linked_pairings.append(call)

    for call in linked_pairings:
        consumed_evidence.update(call.support())

    error_messages = set()
    available_flanking_pairs = filter_consumed_pairs(available_flanking_pairs, consumed_evidence)

    try:
        first, second = _call_by_flanking_pairs(evidence, event_type, consumed_evidence=consumed_evidence)
        call = EventCall(
            first, second, evidence, event_type,
            call_method=CALL_METHOD.FLANK
        )
        call.add_flanking_support(available_flanking_pairs)
        if call.has_compatible:
            call.add_flanking_support(available_flanking_pairs, is_compatible=True)
        linked_pairings.append(call)
    except (AssertionError, UserWarning) as err:
        error_messages.add(str(err))

    if not linked_pairings:
        raise UserWarning(';'.join(list(error_messages)))
    return linked_pairings
